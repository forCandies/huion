from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


APP_SUPPORT = Path(os.getenv("INK2VAULT_HOME", str(Path.home() / "Library" / "Application Support" / "Ink2Vault"))).expanduser()
CONFIG_PATH = APP_SUPPORT / "config.json"
STATE_PATH = APP_SUPPORT / "state.sqlite3"
LOG_PATH = APP_SUPPORT / "ink2vault.log"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "cz.ink2vault.watch.plist"


@dataclass
class Config:
    source_dir: str
    vault_dir: str
    note_folder: str = "Inbox/Rukopis"
    attachment_folder: str = "Attachments/Rukopis"
    source_label: str = "Rukopis"
    filename_template: str = "{date} – {title}"
    claude_model: str = "sonnet"
    interval_seconds: int = 60
    save_original: bool = True

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_PATH.exists():
            raise RuntimeError("Konfigurace neexistuje. Nejdřív spusť: ink2vault configure")
        return cls(**json.loads(CONFIG_PATH.read_text(encoding="utf-8")))

    def save(self) -> None:
        APP_SUPPORT.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(str(CONFIG_PATH), 0o600)

    @property
    def source(self) -> Path:
        return Path(os.path.expanduser(self.source_dir)).resolve()

    @property
    def vault(self) -> Path:
        return Path(os.path.expanduser(self.vault_dir)).resolve()


def suggested_vault_root() -> Path:
    return Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents"


def suggested_source() -> Path:
    icloud = Path.home() / "Library" / "Mobile Documents" / "iCloud~com~huion~note" / "Documents"
    live = Path.home() / "Library" / "Containers" / "com.huion.note" / "Data" / "Documents" / "newData"
    if icloud.is_dir():
        return icloud
    return live if live.is_dir() else Path.home() / "Library" / "CloudStorage"
