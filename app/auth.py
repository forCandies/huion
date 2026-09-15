from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import Settings
from .db import Database


COOKIE = "ink2vault_session"


class Auth:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.signer = URLSafeTimedSerializer(settings.app_secret, salt="ink2vault-session")

    def session_token(self, user_id: int) -> str:
        return self.signer.dumps({"user_id": user_id})

    def user(self, request: Request):
        token = request.cookies.get(COOKIE)
        if not token:
            return None
        try:
            payload = self.signer.loads(token, max_age=60 * 60 * 24 * 30)
        except (BadSignature, SignatureExpired):
            return None
        return self.db.one("SELECT * FROM users WHERE id=?", (int(payload["user_id"]),))

    def require(self, request: Request):
        user = self.user(request)
        if user is None:
            raise HTTPException(status_code=303, headers={"Location": "/"})
        return user

    def is_allowed(self, email: str) -> bool:
        return email.lower() in self.settings.allowed_emails

    def oauth_url(self) -> tuple[str, str]:
        state = self.signer.dumps({"nonce": secrets.token_urlsafe(20)}, salt="google-oauth")
        query = urlencode({
            "client_id": self.settings.google_client_id,
            "redirect_uri": f"{self.settings.app_url}/auth/google/callback",
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
        })
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}", state

    def drive_oauth_url(self, user_id: int) -> str:
        state = self.signer.dumps({"user_id": user_id}, salt="google-drive-oauth")
        query = urlencode({
            "client_id": self.settings.google_client_id,
            "redirect_uri": f"{self.settings.app_url}/connections/drive/callback",
            "response_type": "code",
            "scope": "openid email https://www.googleapis.com/auth/drive.readonly",
            "state": state,
            "access_type": "offline",
            "prompt": "consent select_account",
        })
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

    async def finish_drive(self, code: str, state: str) -> tuple[int, dict, dict]:
        try:
            payload = self.signer.loads(state, salt="google-drive-oauth", max_age=600)
        except (BadSignature, SignatureExpired) as exc:
            raise HTTPException(400, "Připojení vypršelo. Zkus to znovu.") from exc
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post("https://oauth2.googleapis.com/token", data={
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": f"{self.settings.app_url}/connections/drive/callback",
            })
            response.raise_for_status()
            token = response.json()
            profile_response = await client.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {token['access_token']}"})
            profile_response.raise_for_status()
        if not token.get("refresh_token"):
            raise HTTPException(400, "Google neposlal trvalé oprávnění. Odeber Ink2Vault v Google účtu a připoj ho znovu.")
        return int(payload["user_id"]), token, profile_response.json()

    async def finish_google(self, code: str, state: str):
        try:
            self.signer.loads(state, salt="google-oauth", max_age=600)
        except (BadSignature, SignatureExpired) as exc:
            raise HTTPException(400, "Přihlášení vypršelo. Zkus to znovu.") from exc
        async with httpx.AsyncClient(timeout=20) as client:
            token_response = await client.post("https://oauth2.googleapis.com/token", data={
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": f"{self.settings.app_url}/auth/google/callback",
            })
            token_response.raise_for_status()
            access_token = token_response.json()["access_token"]
            profile_response = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            profile_response.raise_for_status()
        profile = profile_response.json()
        email = str(profile.get("email", "")).lower()
        if not profile.get("email_verified") or not self.is_allowed(email):
            raise HTTPException(403, "Tento Google účet není na seznamu povolených účtů.")
        return self.db.upsert_user(email, profile.get("name") or email.split("@")[0], profile.get("picture"))
