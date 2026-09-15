from __future__ import annotations

import argparse
import json
import logging
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

from .ai import claude_version
from .config import APP_SUPPORT, CONFIG_PATH, LEGACY_PLIST_PATH, LOG_PATH, PLIST_PATH, STATE_PATH, Config, suggested_source, suggested_vault_root
from .pipeline import Pipeline
from .state import State


LOG = logging.getLogger("huion")


def configure_logging(verbose: bool = False, log_file: bool = False) -> None:
    handlers = [logging.StreamHandler()]
    if log_file:
        APP_SUPPORT.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(str(LOG_PATH), encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def ask(label: str, default: str) -> str:
    answer = input("%s [%s]: " % (label, default)).strip()
    return answer or default


def cmd_configure(args: argparse.Namespace) -> int:
    previous = None
    if CONFIG_PATH.exists():
        previous = Config.load()
    source_default = args.source or (previous.source_dir if previous else str(suggested_source()))
    vault_root = suggested_vault_root()
    vault_default = args.vault or (previous.vault_dir if previous else str(vault_root))
    source = source_default if args.non_interactive else ask("Zdrojová složka Huion", source_default)
    vault = vault_default if args.non_interactive else ask("Obsidian vault v iCloud Drive", vault_default)
    note_folder = args.notes or (previous.note_folder if previous else "Inbox/Rukopis")
    attachment_folder = args.attachments or (previous.attachment_folder if previous else "Attachments/Rukopis")
    if not args.non_interactive:
        note_folder = ask("Složka poznámek uvnitř vaultu", note_folder)
        attachment_folder = ask("Složka příloh uvnitř vaultu", attachment_folder)
    config = Config(
        source_dir=source,
        vault_dir=vault,
        note_folder=note_folder.strip("/"),
        attachment_folder=attachment_folder.strip("/"),
        source_label=(previous.source_label if previous else "Rukopis"),
        filename_template=(previous.filename_template if previous else "{date} – {title}"),
        claude_model=args.model or (previous.claude_model if previous else "sonnet"),
        interval_seconds=args.interval or (previous.interval_seconds if previous else 60),
        save_original=True if previous is None else previous.save_original,
    )
    if not config.source.is_dir():
        raise RuntimeError("Vstupní složka neexistuje: %s" % config.source)
    if not config.vault.is_dir():
        raise RuntimeError("Vault neexistuje: %s" % config.vault)
    config.save()
    print("Konfigurace uložena do %s" % CONFIG_PATH)
    return cmd_doctor(argparse.Namespace())


def claude_auth_status():
    try:
        result = subprocess.run(["claude", "auth", "status", "--json"], capture_output=True, text=True, timeout=20)
        if result.returncode:
            return False, result.stderr.strip() or result.stdout.strip()
        data = json.loads(result.stdout)
        return bool(data.get("loggedIn")), data.get("email") or data.get("subscriptionType") or "přihlášeno"
    except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return False, str(exc)


def cmd_doctor(_: argparse.Namespace) -> int:
    checks = []
    try:
        config = Config.load()
        checks.extend([
            ("Konfigurace", True, str(CONFIG_PATH)),
            ("Vstupní složka", config.source.is_dir(), str(config.source)),
            ("Obsidian vault", config.vault.is_dir(), str(config.vault)),
        ])
    except RuntimeError as exc:
        checks.append(("Konfigurace", False, str(exc)))
    try:
        checks.append(("Claude Code", True, claude_version()))
    except RuntimeError as exc:
        checks.append(("Claude Code", False, str(exc)))
    logged_in, auth_detail = claude_auth_status()
    checks.append(("Claude účet", logged_in, str(auth_detail)))
    for label, okay, detail in checks:
        print("%s  %-18s %s" % ("✓" if okay else "✗", label, detail))
    return 0 if all(item[1] for item in checks) else 1


def create_pipeline() -> Pipeline:
    return Pipeline(Config.load(), State(STATE_PATH))


def cmd_import(args: argparse.Namespace) -> int:
    count = create_pipeline().scan(retry_errors=args.retry_errors, retry_now=args.retry_now)
    print("Hotovo. Nově vytvořených poznámek: %s" % count)
    return 0


def cmd_retry(_: argparse.Namespace) -> int:
    count = create_pipeline().scan(retry_errors=True, retry_now=True)
    print("Hotovo. Po opakování vytvořených poznámek: %s" % count)
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    config = Config.load()
    pipeline = Pipeline(config, State(STATE_PATH))
    interval = args.interval or config.interval_seconds
    LOG.info("Sleduji %s; interval %s sekund", config.source, interval)
    while True:
        try:
            pipeline.scan(retry_errors=True)
        except Exception:
            LOG.exception("Kontrola složky selhala")
        time.sleep(interval)


def cmd_status(args: argparse.Namespace) -> int:
    state = State(STATE_PATH)
    counts = {row["status"]: row["count"] for row in state.counts()}
    print("Hotovo: {done} · Chyby: {error} · Zpracovává se: {processing}".format(
        done=counts.get("done", 0), error=counts.get("error", 0), processing=counts.get("processing", 0),
    ))
    for row in state.recent(args.limit):
        target = row["note_path"] or row["error"] or ""
        print("%-10s %s · strana %s  %s" % (row["status"], row["notebook"], row["page_number"], target))
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    state = State(STATE_PATH)
    if args.scope == "errors":
        removed = state.reset_errors()
        print("Resetováno chybných nebo přerušených importů: %s" % removed)
        return 0
    if not args.yes:
        print("Poznámky v Obsidianu zůstanou zachované.")
        print("Další import vytvoří nové kopie všech nalezených stránek.")
        answer = input("Pro úplný reset napiš RESET: ").strip()
        if answer != "RESET":
            print("Reset zrušen.")
            return 1
    removed = state.reset_all()
    print("Importní historie byla vymazána. Záznamů: %s" % removed)
    return 0


def module_root() -> Path:
    return Path(__file__).resolve().parents[1]


def cmd_service(args: argparse.Namespace) -> int:
    label = "cz.huion.watch"
    if args.action == "status":
        result = subprocess.run(["launchctl", "print", "gui/%s/%s" % (os.getuid(), label)], capture_output=True, text=True)
        print("Služba běží." if result.returncode == 0 else "Služba není načtená.")
        return result.returncode
    domain = "gui/%s" % os.getuid()
    if args.action == "uninstall":
        subprocess.run(["launchctl", "bootout", domain, str(PLIST_PATH)], check=False)
        subprocess.run(["launchctl", "bootout", domain, str(LEGACY_PLIST_PATH)], check=False)
        PLIST_PATH.unlink(missing_ok=True)
        LEGACY_PLIST_PATH.unlink(missing_ok=True)
        print("Služba byla odstraněna.")
        return 0
    config = Config.load()
    if not shutil.which("claude"):
        raise RuntimeError("Claude Code není v PATH. Nejdřív jej nainstaluj a přihlas.")
    logged_in, _ = claude_auth_status()
    if not logged_in:
        raise RuntimeError("Claude účet není přihlášený. Nejdřív spusť: claude auth login")
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    python_path = os.pathsep.join(filter(None, [str(module_root()), os.environ.get("PYTHONPATH", "")]))
    payload = {
        "Label": label,
        "ProgramArguments": [sys.executable, "-m", "ink2vault.cli", "watch"],
        "WorkingDirectory": str(module_root()),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
        "ProcessType": "Background",
        "EnvironmentVariables": {
            "PATH": os.pathsep.join(filter(None, [
                str(Path(shutil.which("claude")).parent) if shutil.which("claude") else "",
                os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            ])),
            "PYTHONPATH": python_path,
        },
    }
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(payload, handle)
    subprocess.run(["launchctl", "bootout", domain, str(LEGACY_PLIST_PATH)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    LEGACY_PLIST_PATH.unlink(missing_ok=True)
    subprocess.run(["launchctl", "bootout", domain, str(PLIST_PATH)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "bootstrap", domain, str(PLIST_PATH)], check=True)
    print("Služba nainstalována. Sleduje %s každých %s sekund." % (config.source, config.interval_seconds))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="huion", description="Poznámky z Huion Note přes Claude do Obsidianu")
    result.add_argument("--verbose", action="store_true")
    sub = result.add_subparsers(dest="command")
    configure = sub.add_parser("configure", help="Nastavit vstupní složku a Obsidian vault")
    configure.add_argument("--source")
    configure.add_argument("--vault")
    configure.add_argument("--notes")
    configure.add_argument("--attachments")
    configure.add_argument("--model")
    configure.add_argument("--interval", type=int)
    configure.add_argument("--non-interactive", action="store_true")
    configure.set_defaults(func=cmd_configure)
    doctor = sub.add_parser("doctor", help="Ověřit složky a přihlášení Claude")
    doctor.set_defaults(func=cmd_doctor)
    import_command = sub.add_parser("import", aliases=["scan"], help="Importovat existující i nové stránky")
    import_command.add_argument("--retry-errors", action="store_true", help="Zopakovat také dříve chybné stránky")
    import_command.add_argument("--retry-now", action="store_true", help=argparse.SUPPRESS)
    import_command.set_defaults(func=cmd_import)
    retry = sub.add_parser("retry", help="Hned zopakovat všechny chybné importy")
    retry.set_defaults(func=cmd_retry)
    watch = sub.add_parser("watch", help="Průběžně sledovat vstupní složku")
    watch.add_argument("--interval", type=int)
    watch.set_defaults(func=cmd_watch)
    status = sub.add_parser("status", help="Vypsat stav a poslední importy")
    status.add_argument("--limit", type=int, default=20)
    status.set_defaults(func=cmd_status)
    reset = sub.add_parser("reset", help="Resetovat chyby nebo celou importní historii")
    reset.add_argument("scope", choices=["errors", "all"], nargs="?", default="errors")
    reset.add_argument("--yes", action="store_true", help="U úplného resetu nevyžadovat potvrzení")
    reset.set_defaults(func=cmd_reset)
    service = sub.add_parser("service", help="Spravovat automatické spouštění přes launchd")
    service.add_argument("action", choices=["install", "uninstall", "status"])
    service.set_defaults(func=cmd_service)
    return result


def interactive_menu() -> int:
    actions = {
        "1": ("Importovat vše, co je v iCloudu", cmd_import, argparse.Namespace(retry_errors=False, retry_now=False)),
        "2": ("Zopakovat chybné importy", cmd_retry, argparse.Namespace()),
        "3": ("Zobrazit stav", cmd_status, argparse.Namespace(limit=20)),
        "4": ("Nastavit zdroj a Obsidian", cmd_configure, argparse.Namespace(
            source=None, vault=None, notes=None, attachments=None, model=None, interval=None, non_interactive=False,
        )),
        "5": ("Spustit kontrolu nastavení", cmd_doctor, argparse.Namespace()),
        "6": ("Zapnout automatickou službu", cmd_service, argparse.Namespace(action="install")),
        "7": ("Zobrazit stav služby", cmd_service, argparse.Namespace(action="status")),
        "8": ("Vypnout automatickou službu", cmd_service, argparse.Namespace(action="uninstall")),
        "9": ("Resetovat chybné importy", cmd_reset, argparse.Namespace(scope="errors", yes=True)),
        "10": ("Resetovat celou importní historii", cmd_reset, argparse.Namespace(scope="all", yes=False)),
    }
    while True:
        print("\nHuion\n=====")
        for key, (label, _, __) in actions.items():
            print("%2s) %s" % (key, label))
        print(" 0) Konec")
        try:
            choice = input("\nVyber akci: ").strip()
        except EOFError:
            return 0
        if choice == "0":
            return 0
        action = actions.get(choice)
        if not action:
            print("Neplatná volba.")
            continue
        try:
            action[1](action[2])
        except Exception as exc:
            LOG.error("%s", exc)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    configure_logging(args.verbose, args.command == "watch")
    if args.command is None:
        return interactive_menu()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nUkončeno.")
        return 130
    except Exception as exc:
        LOG.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
