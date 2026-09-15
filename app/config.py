from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _emails(value: str) -> frozenset[str]:
    return frozenset(item.strip().lower() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    app_url: str
    app_secret: str
    encryption_key: str
    app_env: str
    registration_mode: str
    allowed_emails: frozenset[str]
    google_client_id: str
    google_client_secret: str
    dev_login_email: str
    data_dir: Path
    couchdb_url: str
    couchdb_user: str
    couchdb_password: str
    livesync_public_url: str
    default_note_folder: str
    default_attachment_folder: str
    default_source_label: str
    sync_interval_seconds: int
    ocr_url: str
    ocr_domain: str
    livesync_cli_bin: str
    claude_cli_bin: str
    claude_model: str
    gemini_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_url=os.getenv("APP_URL", "http://localhost:3000").rstrip("/"),
            app_secret=os.getenv("APP_SECRET", "development-secret-change-me"),
            encryption_key=os.getenv("ENCRYPTION_KEY", ""),
            app_env=os.getenv("APP_ENV", "development"),
            registration_mode=os.getenv("REGISTRATION_MODE", "invite"),
            allowed_emails=_emails(os.getenv("ALLOWED_EMAILS", "demo@example.com")),
            google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
            dev_login_email=os.getenv("DEV_LOGIN_EMAIL", "demo@example.com").lower(),
            data_dir=Path(os.getenv("DATA_DIR", "/data")),
            couchdb_url=os.getenv("COUCHDB_URL", "http://couchdb:5984").rstrip("/"),
            couchdb_user=os.getenv("COUCHDB_ADMIN_USER", "ink2vault"),
            couchdb_password=os.getenv("COUCHDB_ADMIN_PASSWORD", "change-this-couchdb-password"),
            livesync_public_url=os.getenv("LIVESYNC_PUBLIC_URL", ""),
            default_note_folder=os.getenv("DEFAULT_NOTE_FOLDER", "Inbox"),
            default_attachment_folder=os.getenv("DEFAULT_ATTACHMENT_FOLDER", "Attachments/Rukopis"),
            default_source_label=os.getenv("DEFAULT_SOURCE_LABEL", "Rukopis"),
            sync_interval_seconds=max(30, int(os.getenv("SYNC_INTERVAL_SECONDS", "300"))),
            ocr_url=os.getenv("OCR_URL", "http://ocr:8000").rstrip("/"),
            ocr_domain=os.getenv("OCR_DOMAIN", "handwritten"),
            livesync_cli_bin=os.getenv("LIVESYNC_CLI_BIN", "/usr/local/bin/livesync-cli"),
            claude_cli_bin=os.getenv("CLAUDE_CLI_BIN", "/usr/local/bin/claude"),
            claude_model=os.getenv("CLAUDE_MODEL", "sonnet"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        )

    @property
    def google_ready(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def development(self) -> bool:
        return self.app_env == "development"

    def validate(self) -> None:
        if self.development:
            return
        if not self.allowed_emails:
            raise RuntimeError("ALLOWED_EMAILS must not be empty in production")
        if len(self.app_secret) < 32 or self.app_secret.startswith("change-"):
            raise RuntimeError("APP_SECRET must be a random value with at least 32 characters")
        if not self.encryption_key or self.encryption_key.startswith("change-"):
            raise RuntimeError("ENCRYPTION_KEY must be a valid Fernet key")
        try:
            from cryptography.fernet import Fernet
            Fernet(self.encryption_key.encode())
        except (ValueError, TypeError) as exc:
            raise RuntimeError("ENCRYPTION_KEY must be a valid Fernet key") from exc
        if not self.google_ready:
            raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required in production")
        if not self.app_url.startswith("https://") or not self.livesync_public_url.startswith("https://"):
            raise RuntimeError("APP_URL and LIVESYNC_PUBLIC_URL must use HTTPS in production")
        if self.couchdb_password == "change-this-couchdb-password":
            raise RuntimeError("COUCHDB_ADMIN_PASSWORD must be changed in production")


settings = Settings.from_env()
