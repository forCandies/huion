from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS pages (
  source_id TEXT PRIMARY KEY,
  source_file TEXT NOT NULL,
  notebook TEXT NOT NULL,
  page_number INTEGER NOT NULL,
  checksum TEXT NOT NULL,
  status TEXT NOT NULL,
  note_path TEXT,
  error TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get(self, source_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM pages WHERE source_id=?", (source_id,)).fetchone()

    def begin(self, source_id: str, source_file: str, notebook: str, page_number: int, checksum: str) -> None:
        stamp = now()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO pages(source_id,source_file,notebook,page_number,checksum,status,attempts,created_at,updated_at)
                VALUES(?,?,?,?,?,'processing',1,?,?)
                ON CONFLICT(source_id) DO UPDATE SET source_file=excluded.source_file,
                notebook=excluded.notebook,page_number=excluded.page_number,checksum=excluded.checksum,
                status='processing',error=NULL,
                attempts=pages.attempts+1,updated_at=excluded.updated_at""",
                (source_id, source_file, notebook, page_number, checksum, stamp, stamp),
            )

    def done(self, source_id: str, note_path: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE pages SET status='done',note_path=?,error=NULL,updated_at=? WHERE source_id=?", (note_path, now(), source_id))

    def reserve(self, source_id: str, note_path: str) -> None:
        """Persist the intended target before writing so a crash cannot create a duplicate."""
        with self.connect() as conn:
            conn.execute("UPDATE pages SET note_path=?,updated_at=? WHERE source_id=?", (note_path, now(), source_id))

    def fail(self, source_id: str, error: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE pages SET status='error',error=?,updated_at=? WHERE source_id=?", (error[:1000], now(), source_id))

    def counts(self):
        with self.connect() as conn:
            return conn.execute("SELECT status,count(*) AS count FROM pages GROUP BY status ORDER BY status").fetchall()

    def recent(self, limit: int = 20):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM pages ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
