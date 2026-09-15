from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL,
  avatar_url TEXT,
  created_at TEXT NOT NULL,
  last_login_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_settings (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  note_folder TEXT NOT NULL DEFAULT 'Inbox',
  attachment_folder TEXT NOT NULL DEFAULT 'Attachments/Rukopis',
  source_label TEXT NOT NULL DEFAULT 'Rukopis',
  filename_template TEXT NOT NULL DEFAULT '{date} – {title}',
  processing_mode TEXT NOT NULL DEFAULT 'automatic',
  save_original INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS connections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'disconnected',
  account_label TEXT,
  details_json TEXT NOT NULL DEFAULT '{}',
  secret_blob TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE(user_id, kind)
);

CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  source_id TEXT NOT NULL,
  page_number INTEGER NOT NULL,
  title TEXT NOT NULL,
  notebook TEXT NOT NULL,
  status TEXT NOT NULL,
  stage TEXT NOT NULL,
  progress INTEGER NOT NULL DEFAULT 0,
  ocr_confidence REAL,
  target_path TEXT,
  image_path TEXT,
  raw_ocr TEXT,
  markdown TEXT,
  error TEXT,
  source_checksum TEXT,
  protected INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(user_id, source_id)
);

CREATE TABLE IF NOT EXISTS import_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_id INTEGER NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(connections)")}
            if "secret_blob" not in columns:
                conn.execute("ALTER TABLE connections ADD COLUMN secret_blob TEXT")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def upsert_user(self, email: str, name: str, avatar_url: str | None = None) -> sqlite3.Row:
        stamp = now()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO users(email,name,avatar_url,created_at,last_login_at)
                VALUES(?,?,?,?,?) ON CONFLICT(email) DO UPDATE SET
                name=excluded.name,avatar_url=excluded.avatar_url,last_login_at=excluded.last_login_at""",
                (email.lower(), name, avatar_url, stamp, stamp),
            )
            user = conn.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone()
            assert user is not None
            return user

    def ensure_settings(self, user_id: int, defaults: dict[str, str]) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO user_settings
                (user_id,note_folder,attachment_folder,source_label,filename_template,updated_at)
                VALUES(?,?,?,?,?,?)""",
                (user_id, defaults["note_folder"], defaults["attachment_folder"], defaults["source_label"], "{date} – {title}", now()),
            )

    def connection_map(self, user_id: int) -> dict[str, dict[str, Any]]:
        rows = self.all("SELECT * FROM connections WHERE user_id=?", (user_id,))
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json") or "{}")
            item.pop("secret_blob", None)
            result[item["kind"]] = item
        return result

    def set_connection(self, user_id: int, kind: str, status: str, label: str, details: dict[str, Any] | None = None, secret_blob: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO connections(user_id,kind,status,account_label,details_json,secret_blob,updated_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,kind) DO UPDATE SET
                status=excluded.status,account_label=excluded.account_label,
                details_json=excluded.details_json,secret_blob=COALESCE(excluded.secret_blob,connections.secret_blob),updated_at=excluded.updated_at""",
                (user_id, kind, status, label, json.dumps(details or {}, ensure_ascii=False), secret_blob, now()),
            )

    def connection(self, user_id: int, kind: str) -> sqlite3.Row | None:
        return self.one("SELECT * FROM connections WHERE user_id=? AND kind=?", (user_id, kind))

    def seed_demo(self, user_id: int, rows: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            count = conn.execute("SELECT count(*) FROM imports WHERE user_id=?", (user_id,)).fetchone()[0]
            if count:
                return
            for item in rows:
                stamp = item.get("updated_at", now())
                cur = conn.execute(
                    """INSERT INTO imports(user_id,source_id,page_number,title,notebook,status,stage,progress,
                    ocr_confidence,target_path,image_path,raw_ocr,markdown,error,source_checksum,protected,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (user_id, item["source_id"], item["page_number"], item["title"], item["notebook"], item["status"],
                     item["stage"], item["progress"], item.get("ocr_confidence"), item.get("target_path"), item.get("image_path"),
                     item.get("raw_ocr"), item.get("markdown"), item.get("error"), item.get("source_checksum"),
                     int(item.get("protected", False)), stamp, stamp),
                )
                for stage, status, message in item.get("events", []):
                    conn.execute("INSERT INTO import_events(import_id,stage,status,message,created_at) VALUES(?,?,?,?,?)",
                                 (cur.lastrowid, stage, status, message, stamp))
