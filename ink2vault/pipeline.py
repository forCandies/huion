from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .ai import AIResult, process_image
from .config import Config
from .huion import Page, read_backup
from .state import State


LOG = logging.getLogger("ink2vault")
SUPPORTED_SUFFIXES = (".zip", ".huionnoteios")


def safe_name(value: str, fallback: str = "Poznámka") -> str:
    value = re.sub(r'[\\/:*?"<>|#^\[\]]+', "-", value).strip(" .-")
    return re.sub(r"\s+", " ", value)[:120] or fallback


def find_backups(source: Path) -> Iterable[Path]:
    if not source.exists():
        raise RuntimeError("Vstupní složka neexistuje: %s" % source)
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.name.lower().endswith(SUPPORTED_SUFFIXES) and zipfile.is_zipfile(str(path)):
            yield path


def markdown(label: str, page: Page, result: AIResult, attachment: str, source_id: str) -> str:
    tasks = "\n".join(
        "- [ ] %s%s" % (task["text"], " 📅 %s" % task["due"] if task.get("due") else "")
        for task in result.tasks
    )
    tasks_section = "\n## Úkoly\n\n%s\n" % tasks if tasks else ""
    tags_section = "\n## Štítky\n\n%s\n" % " ".join("#%s" % tag for tag in result.tags) if result.tags else ""
    original = "\n## Originál\n\n![[%s]]\n" % attachment if attachment else ""
    return """---
title: {title}
source: {label}
source_id: {source_id}
notebook: {notebook}
page: {page_number}
tags: {tags}
ai_provider: Claude
---

# {plain_title}

## Shrnutí

{summary}
{tasks}
## Poznámka

{text}
{tag_section}{original}""".format(
        title=json.dumps(result.title, ensure_ascii=False), label=json.dumps(label, ensure_ascii=False),
        source_id=json.dumps(source_id), notebook=json.dumps(page.notebook_name, ensure_ascii=False),
        page_number=page.page_number, tags=json.dumps(result.tags, ensure_ascii=False), plain_title=result.title,
        summary=result.summary or "_Shrnutí nebylo vytvořeno._", tasks=tasks_section,
        text=result.cleaned_text or "_Text nebyl rozpoznán._", tag_section=tags_section, original=original,
    )


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".ink2vault-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, str(path))
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


class Pipeline:
    def __init__(self, config: Config, state: State):
        self.config = config
        self.state = state

    def scan(self, retry_errors: bool = True, retry_now: bool = False) -> int:
        if not self.config.vault.exists():
            raise RuntimeError("Obsidian vault neexistuje nebo není stažený z iCloudu: %s" % self.config.vault)
        processed = 0
        for backup in find_backups(self.config.source):
            try:
                pages = read_backup(backup)
            except Exception as exc:
                LOG.error("Nelze přečíst %s: %s", backup.name, exc)
                continue
            for page in pages:
                source_id = "%s:%s" % (page.notebook_id, page.page_id)
                existing = self.state.get(source_id)
                if existing and existing["status"] == "done":
                    if existing["checksum"] != page.image_sha256:
                        LOG.warning("Zdroj %s se změnil; existující poznámka zůstává beze změny", source_id)
                    continue
                if existing and existing["note_path"]:
                    reserved = self.config.vault / existing["note_path"]
                    if reserved.is_file():
                        self.state.done(source_id, existing["note_path"])
                        LOG.info("Obnoven dokončený import: %s", existing["note_path"])
                        continue
                if existing and existing["status"] == "error" and not retry_errors:
                    continue
                if existing and existing["status"] == "error" and not retry_now:
                    updated = datetime.fromisoformat(existing["updated_at"])
                    wait_seconds = min(3600, 60 * (5 ** max(0, existing["attempts"] - 1)))
                    if (datetime.now(timezone.utc) - updated).total_seconds() < wait_seconds:
                        continue
                self.state.begin(source_id, str(backup), page.notebook_name, page.page_number, page.image_sha256)
                try:
                    self._process_page(backup, page, source_id)
                    processed += 1
                except Exception as exc:
                    self.state.fail(source_id, str(exc))
                    LOG.error("%s, strana %s: %s", page.notebook_name, page.page_number, exc)
        return processed

    def _process_page(self, backup: Path, page: Page, source_id: str) -> None:
        with tempfile.TemporaryDirectory(prefix="ink2vault-") as directory:
            image_path = Path(directory) / ("page%s" % page.image_ext)
            image_path.write_bytes(page.image)
            LOG.info("AI zpracovává %s, stranu %s", page.notebook_name, page.page_number)
            result = process_image(image_path, page.notebook_name, page.page_number, self.config.claude_model)

        source_date = datetime.fromtimestamp(backup.stat().st_mtime).date().isoformat()
        filename = self.config.filename_template
        filename = filename.replace("{date}", source_date).replace("{title}", result.title)
        filename = filename.replace("{notebook}", page.notebook_name).replace("{page}", str(page.page_number))
        note_rel = Path(self.config.note_folder) / (safe_name(filename) + ".md")
        note_path = self.config.vault / note_rel
        if note_path.exists():
            note_rel = note_rel.with_name("%s – %s.md" % (note_rel.stem, safe_name(page.page_id)[-10:]))
            note_path = self.config.vault / note_rel

        self.state.reserve(source_id, note_rel.as_posix())

        attachment = ""
        if self.config.save_original:
            attachment_rel = Path(self.config.attachment_folder) / ("%s-%s%s" % (
                safe_name(page.notebook_name), safe_name(page.page_id), page.image_ext,
            ))
            attachment_path = self.config.vault / attachment_rel
            if not attachment_path.exists():
                atomic_write(attachment_path, page.image)
            attachment = attachment_rel.as_posix()

        content = markdown(self.config.source_label, page, result, attachment, source_id).encode("utf-8")
        atomic_write(note_path, content)
        self.state.done(source_id, note_rel.as_posix())
        LOG.info("Uloženo: %s", note_rel.as_posix())
