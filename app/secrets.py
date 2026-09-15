from __future__ import annotations

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken


class SecretStore:
    def __init__(self, key: str):
        # Development accepts any value; production validation requires an explicit one.
        try:
            Fernet(key.encode())
            derived = key.encode()
        except (ValueError, TypeError):
            derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
        self.fernet = Fernet(derived)

    def seal(self, value: dict) -> str:
        return self.fernet.encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()

    def open(self, value: str | None) -> dict:
        if not value:
            return {}
        try:
            return json.loads(self.fernet.decrypt(value.encode()).decode())
        except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("Stored connection secret cannot be decrypted") from exc
