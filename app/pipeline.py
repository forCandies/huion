from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import tempfile
from pathlib import Path

import httpx

from .ai import AIEnricher, AIResult
from .config import Settings
from .db import Database, now
from .huion import Page, read_backup
from .secrets import SecretStore


LOG = logging.getLogger("ink2vault.pipeline")


def safe_name(value: str, fallback: str = "Poznámka") -> str:
    value = re.sub(r'[\\/:*?"<>|#^\[\]]+', "-", value).strip(" .-")
    return re.sub(r"\s+", " ", value)[:100] or fallback


class Pipeline:
    def __init__(self, cfg: Settings, db: Database, secrets: SecretStore):
        self.cfg, self.db, self.secrets = cfg, db, secrets
        self.ai = AIEnricher(cfg, db, secrets)
        self.lock = asyncio.Lock()

    async def loop(self) -> None:
        while True:
            try:
                await self.run_all()
            except Exception:
                LOG.exception("Scheduled import failed")
            await asyncio.sleep(self.cfg.sync_interval_seconds)

    async def run_all(self) -> None:
        if self.lock.locked():
            return
        async with self.lock:
            for row in self.db.all("SELECT * FROM connections WHERE kind='drive' AND status='connected' AND secret_blob IS NOT NULL"):
                try:
                    await self.run_user(row["user_id"])
                except Exception as exc:
                    LOG.exception("Import failed for user %s", row["user_id"])
                    self.db.set_connection(row["user_id"], "drive", "attention", row["account_label"] or "Google Drive", {"error": str(exc)[:300]})

    async def _access_token(self, secret: dict) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post("https://oauth2.googleapis.com/token", data={
                "client_id": self.cfg.google_client_id,
                "client_secret": self.cfg.google_client_secret,
                "refresh_token": secret["refresh_token"],
                "grant_type": "refresh_token",
            })
            response.raise_for_status()
            return response.json()["access_token"]

    async def run_user(self, user_id: int) -> None:
        connection = self.db.connection(user_id, "drive")
        if not connection:
            return
        secret = self.secrets.open(connection["secret_blob"])
        token = await self._access_token(secret)
        details = json.loads(connection["details_json"] or "{}")
        folder_id = details.get("folder_id", "root")
        file_versions = details.get("file_versions", {})
        headers = {"Authorization": f"Bearer {token}"}
        query = f"'{folder_id}' in parents and trashed=false"
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get("https://www.googleapis.com/drive/v3/files", headers=headers, params={
                "q": query, "spaces": "drive", "pageSize": 100,
                "fields": "files(id,name,modifiedTime,md5Checksum,mimeType,size)",
            })
            response.raise_for_status()
            files = response.json().get("files", [])
            for item in files:
                name = item.get("name", "")
                if not name.lower().endswith((".zip", ".huionnoteios", ".huionnoteios.zip")):
                    continue
                fingerprint = item.get("md5Checksum") or item.get("modifiedTime")
                if file_versions.get(item["id"]) == fingerprint:
                    continue
                download = await client.get(f"https://www.googleapis.com/drive/v3/files/{item['id']}", headers=headers, params={"alt": "media"})
                download.raise_for_status()
                with tempfile.NamedTemporaryFile(suffix=".zip") as handle:
                    handle.write(download.content); handle.flush()
                    pages = read_backup(Path(handle.name))
                for page in pages:
                    await self.process_page(user_id, item, page)
                file_versions[item["id"]] = fingerprint
        self.db.set_connection(user_id, "drive", "connected", connection["account_label"] or "Google Drive", {**details, "last_sync": now(), "files_seen": len(files), "file_versions": file_versions})

    async def process_page(self, user_id: int, source: dict, page: Page) -> None:
        source_id = f"{source['id']}:{page.page_id}"
        existing = self.db.one("SELECT * FROM imports WHERE user_id=? AND source_id=?", (user_id, source_id))
        if existing:
            if existing["source_checksum"] != page.image_sha256:
                with self.db.connect() as conn:
                    conn.execute("UPDATE imports SET status='review',error=?,updated_at=? WHERE id=?", ("Původní stránka se změnila. Existující poznámka nebyla přepsána.", now(), existing["id"]))
                    conn.execute("INSERT INTO import_events(import_id,stage,status,message,created_at) VALUES(?,?,?,?,?)", (existing["id"], "source", "attention", "Zdroj se změnil; uživatelský obsah zůstal beze změny", now()))
            return
        profile = self.db.one("SELECT * FROM user_settings WHERE user_id=?", (user_id,))
        user_root = self.cfg.data_dir / "users" / str(user_id)
        image_rel = Path("originals") / safe_name(page.notebook_id) / f"page-{safe_name(page.page_id)}{page.image_ext}"
        image_path = user_root / image_rel
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(page.image)
        stamp = now()
        with self.db.connect() as conn:
            cur = conn.execute("""INSERT INTO imports(user_id,source_id,page_number,title,notebook,status,stage,progress,image_path,source_checksum,created_at,updated_at)
                VALUES(?,?,?,?,?,'processing','ocr',35,?,?,?,?)""", (user_id, source_id, page.page_number, f"{page.notebook_name} – strana {page.page_number}", page.notebook_name, str(image_path), page.image_sha256, stamp, stamp))
            import_id = cur.lastrowid
            conn.execute("INSERT INTO import_events(import_id,stage,status,message,created_at) VALUES(?,?,?,?,?)", (import_id, "download", "done", f"Staženo z Google Drive: {source['name']}", stamp))
        try:
            ocr = await self.ocr(page.image, image_path.name)
            with self.db.connect() as conn:
                conn.execute("UPDATE imports SET stage='ai',progress=55,raw_ocr=?,updated_at=? WHERE id=?", (ocr, now(), import_id))
                conn.execute("INSERT INTO import_events(import_id,stage,status,message,created_at) VALUES(?,?,?,?,?)", (import_id, "ocr", "done", "Rukopis byl převeden na text", now()))
            enriched, ai_provider = await self.ai.enrich(user_id, ocr, page.notebook_name, page.page_number)
            title = safe_name(enriched.title, f"{page.notebook_name} – strana {page.page_number}")
            note_folder = Path(profile["note_folder"])
            attachment_folder = Path(profile["attachment_folder"])
            filename = profile["filename_template"]
            filename = filename.replace("{date}", now()[:10]).replace("{title}", title).replace("{notebook}", page.notebook_name).replace("{page}", str(page.page_number))
            note_rel = note_folder / f"{safe_name(filename)}.md"
            attachment_rel = attachment_folder / image_path.name
            vault = user_root / "vault"
            target_image = vault / attachment_rel
            if profile["save_original"]:
                target_image.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(image_path, target_image)
            markdown = self.markdown(profile["source_label"], page, enriched, attachment_rel.as_posix() if profile["save_original"] else "", source_id, ai_provider)
            note_path = vault / note_rel
            note_path.parent.mkdir(parents=True, exist_ok=True)
            if note_path.exists():
                unique = safe_name(page.page_id)[-10:]
                note_path = note_path.with_name(f"{note_path.stem} – {unique}.md")
                note_rel = note_rel.with_name(note_path.name)
            note_path.write_text(markdown, encoding="utf-8")
            with self.db.connect() as conn:
                next_status = "review" if profile["processing_mode"] == "review" else "ready"
                conn.execute("UPDATE imports SET title=?,status=?,stage='livesync',progress=80,ai_json=?,markdown=?,target_path=?,protected=1,updated_at=? WHERE id=?", (title, next_status, json.dumps(enriched.as_dict(), ensure_ascii=False), markdown, note_rel.as_posix(), now(), import_id))
                conn.execute("INSERT INTO import_events(import_id,stage,status,message,created_at) VALUES(?,?,?,?,?)", (import_id, "ai", "done", f"{ai_provider} vytvořil shrnutí, úkoly a štítky", now()))
            if profile["processing_mode"] != "review":
                await self.publish(user_id, import_id, note_path, note_rel, target_image if profile["save_original"] else None, attachment_rel)
        except Exception as exc:
            with self.db.connect() as conn:
                conn.execute("UPDATE imports SET status='error',error=?,updated_at=? WHERE id=?", (str(exc)[:500], now(), import_id))
                conn.execute("INSERT INTO import_events(import_id,stage,status,message,created_at) VALUES(?,?,?,?,?)", (import_id, "error", "error", str(exc)[:300], now()))

    async def ocr(self, image: bytes, filename: str) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{self.cfg.ocr_url}/api/v1/process", files={"image": (filename, image)}, data={"domain": self.cfg.ocr_domain, "fmt": "txt"})
            response.raise_for_status(); job = response.json()["job_id"]
            for _ in range(180):
                status = await client.get(f"{self.cfg.ocr_url}/api/v1/status/{job}"); status.raise_for_status()
                data = status.json()
                if data.get("status") == "done":
                    result = await client.get(f"{self.cfg.ocr_url}/api/v1/result/{job}"); result.raise_for_status(); return result.text.strip()
                if data.get("status") == "failed":
                    raise RuntimeError(data.get("error") or "OCR failed")
                await asyncio.sleep(2)
        raise TimeoutError("OCR exceeded 6 minutes")

    def markdown(self, label: str, page: Page, result: AIResult, attachment: str, source_id: str, ai_provider: str) -> str:
        title = result.title
        original = f"\n## Originál\n\n![[{attachment}]]\n" if attachment else ""
        tasks = "\n".join(f"- [ ] {task['text']}" + (f" 📅 {task['due']}" if task.get("due") else "") for task in result.tasks)
        tasks_section = f"\n## Úkoly\n\n{tasks}\n" if tasks else ""
        tags = " ".join(f"#{tag}" for tag in result.tags)
        tags_section = f"\n## Štítky\n\n{tags}\n" if tags else ""
        return f'''---\ntitle: {json.dumps(title, ensure_ascii=False)}\nsource: {json.dumps(label, ensure_ascii=False)}\nsource_id: {json.dumps(source_id)}\nnotebook: {json.dumps(page.notebook_name, ensure_ascii=False)}\npage: {page.page_number}\ntags: {json.dumps(result.tags, ensure_ascii=False)}\nai_provider: {json.dumps(ai_provider)}\n---\n\n# {title}\n\n## Shrnutí\n\n{result.summary or "_Shrnutí nebylo vytvořeno._"}\n{tasks_section}\n## Poznámka\n\n{result.cleaned_text or "_Text nebyl rozpoznán._"}\n{tags_section}{original}'''

    async def publish(self, user_id: int, import_id: int, note: Path, note_rel: Path, image: Path | None, image_rel: Path) -> None:
        sync = self.db.connection(user_id, "sync")
        if not sync or sync["status"] != "connected":
            return
        cli = Path(self.cfg.livesync_cli_bin)
        if not cli.exists():
            raise RuntimeError("LiveSync CLI není v image")
        root = self.cfg.data_dir / "users" / str(user_id) / "livesync"
        root.mkdir(parents=True, exist_ok=True)
        credentials = self.secrets.open(sync["secret_blob"])
        details = json.loads(sync["details_json"] or "{}")
        config = {"couchDB_URI": self.cfg.couchdb_url, "couchDB_USER": credentials["username"], "couchDB_PASSWORD": credentials["password"], "couchDB_DBNAME": details["database"], "liveSync": True, "syncOnSave": True, "syncOnStart": True, "encrypt": True, "passphrase": credentials["passphrase"], "usePluginSync": False, "isConfigured": True}
        fd, setting_name = tempfile.mkstemp(prefix="livesync-", suffix=".json", dir=root)
        settings_path = Path(setting_name)
        try:
            with __import__("os").fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(config, handle)
            settings_path.chmod(0o600)
            pairs = [(note, note_rel)] + ([(image, image_rel)] if image else [])
            for source, target in pairs:
                proc = await asyncio.create_subprocess_exec(str(cli), str(root), "--settings", str(settings_path), "push", str(source), target.as_posix(), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                _, stderr = await proc.communicate()
                if proc.returncode:
                    raise RuntimeError(stderr.decode(errors="replace")[-500:])
            proc = await asyncio.create_subprocess_exec(str(cli), str(root), "--settings", str(settings_path), "sync", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            _, stderr = await proc.communicate()
            if proc.returncode:
                raise RuntimeError(stderr.decode(errors="replace")[-500:])
        finally:
            settings_path.unlink(missing_ok=True)
        with self.db.connect() as conn:
            conn.execute("UPDATE imports SET status='done',stage='done',progress=100,updated_at=? WHERE id=?", (now(), import_id))
            conn.execute("INSERT INTO import_events(import_id,stage,status,message,created_at) VALUES(?,?,?,?,?)", (import_id, "livesync", "done", "Poznámka byla vložena do Obsidian LiveSync", now()))
