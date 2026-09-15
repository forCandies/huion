from __future__ import annotations

import asyncio
import json
import re
import secrets as random_secrets
from urllib.parse import quote
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import Auth, COOKIE
from .config import settings
from .db import Database, now
from .demo import demo_imports
from .huion import Page
from .pipeline import Pipeline
from .secrets import SecretStore


ROOT = Path(__file__).resolve().parent
db = Database(settings.data_dir / "ink2vault.sqlite3")
auth = Auth(settings, db)
secret_store = SecretStore(settings.encryption_key or settings.app_secret)
pipeline = Pipeline(settings, db, secret_store)
templates = Jinja2Templates(directory=str(ROOT / "templates"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate()
    db.initialize()
    if settings.development:
        user = db.upsert_user(settings.dev_login_email, "David Herzina")
        db.ensure_settings(user["id"], {
            "note_folder": settings.default_note_folder,
            "attachment_folder": settings.default_attachment_folder,
            "source_label": settings.default_source_label,
        })
        db.set_connection(user["id"], "drive", "connected", "ukázkový účet", {"folder_id": "root", "demo": True})
        ai = db.connection(user["id"], "ai")
        ai_details = json.loads(ai["details_json"] or "{}") if ai else {}
        if not ai or ai_details.get("provider") not in {"claude", "gemini"}:
            db.set_connection(user["id"], "ai", "attention", "AI zatím nepřipojena", {"provider": "demo"})
        db.set_connection(user["id"], "sync", "attention", "Self-hosted LiveSync", {"devices": 0})
        db.seed_demo(user["id"], demo_imports())
        with db.connect() as conn:
            for item in demo_imports():
                conn.execute("UPDATE imports SET ai_json=COALESCE(ai_json, ?) WHERE user_id=? AND source_id=?", (item["ai_json"], user["id"], item["source_id"]))
    task = asyncio.create_task(pipeline.loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Ink2Vault", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


def ctx(request: Request, user=None, **extra):
    return {"request": request, "user": user, "settings": settings, "path": request.url.path, **extra}


def current(request: Request):
    return auth.require(request)


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    user = auth.user(request)
    if user:
        return RedirectResponse("/app", 303)
    return templates.TemplateResponse("login.html", ctx(request, google_ready=settings.google_ready))


@app.get("/auth/google")
def google_login():
    if not settings.google_ready:
        return RedirectResponse("/?error=google-not-configured", 303)
    url, state = auth.oauth_url()
    response = RedirectResponse(url, 303)
    response.set_cookie("ink2vault_oauth_state", state, httponly=True, secure=settings.app_url.startswith("https://"), samesite="lax", max_age=600)
    return response


@app.get("/auth/google/callback")
async def google_callback(request: Request, code: str, state: str):
    if not request.cookies.get("ink2vault_oauth_state") or not __import__("secrets").compare_digest(request.cookies["ink2vault_oauth_state"], state):
        raise HTTPException(400, "Přihlášení nebylo zahájeno v tomto prohlížeči.")
    user = await auth.finish_google(code, state)
    db.ensure_settings(user["id"], {
        "note_folder": settings.default_note_folder,
        "attachment_folder": settings.default_attachment_folder,
        "source_label": settings.default_source_label,
    })
    response = RedirectResponse("/app", 303)
    response.set_cookie(COOKIE, auth.session_token(user["id"]), httponly=True, secure=settings.app_url.startswith("https://"), samesite="lax", max_age=2592000)
    response.delete_cookie("ink2vault_oauth_state")
    return response


@app.get("/connections/drive/start")
def drive_start(request: Request):
    user = current(request)
    if not settings.google_ready:
        return RedirectResponse("/settings?error=google-not-configured#connections", 303)
    return RedirectResponse(auth.drive_oauth_url(user["id"]), 303)


@app.get("/connections/drive/callback")
async def drive_callback(request: Request, code: str, state: str):
    signed_in = current(request)
    user_id, token, profile = await auth.finish_drive(code, state)
    if user_id != signed_in["id"]:
        raise HTTPException(403, "Připojení patří jinému přihlášenému účtu")
    db.set_connection(user_id, "drive", "connected", profile.get("email") or "Google Drive", {"folder_id": "root"}, secret_store.seal({"refresh_token": token["refresh_token"]}))
    return RedirectResponse("/settings?connected=drive#connections", 303)


@app.post("/connections/drive/folder")
def drive_folder(request: Request, folder_id: str = Form(...)):
    user = current(request)
    connection = db.connection(user["id"], "drive")
    if not connection:
        raise HTTPException(400, "Nejdřív připoj Google Drive")
    folder_id = folder_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}|root", folder_id):
        raise HTTPException(400, "Neplatné ID složky Google Drive")
    details = json.loads(connection["details_json"] or "{}")
    db.set_connection(user["id"], "drive", "connected", connection["account_label"], {**details, "folder_id": folder_id})
    return RedirectResponse("/settings?saved=1#connections", 303)


@app.post("/actions/sync")
async def run_sync(request: Request):
    user = current(request)
    await pipeline.run_user(user["id"])
    return RedirectResponse("/app", 303)


@app.post("/connections/sync/provision")
async def provision_sync(request: Request):
    user = current(request)
    if not settings.livesync_public_url:
        return RedirectResponse("/settings?error=livesync-url#connections", 303)
    username = f"ink2vault-u{user['id']}"
    database = f"ink2vault-u{user['id']}"
    password = random_secrets.token_urlsafe(24)
    passphrase = random_secrets.token_urlsafe(24)
    async with __import__("httpx").AsyncClient(timeout=30, auth=(settings.couchdb_user, settings.couchdb_password)) as client:
        user_doc = {"_id": f"org.couchdb.user:{username}", "name": username, "roles": [], "type": "user", "password": password}
        existing = await client.get(f"{settings.couchdb_url}/_users/{quote(user_doc['_id'], safe='')}")
        if existing.status_code == 200:
            user_doc["_rev"] = existing.json()["_rev"]
        response = await client.put(f"{settings.couchdb_url}/_users/{quote(user_doc['_id'], safe='')}", json=user_doc)
        response.raise_for_status()
        created = await client.put(f"{settings.couchdb_url}/{database}")
        if created.status_code not in (201, 202, 412):
            created.raise_for_status()
        security = await client.put(f"{settings.couchdb_url}/{database}/_security", json={"admins": {"names": [], "roles": []}, "members": {"names": [username], "roles": []}})
        security.raise_for_status()
    details = {"database": database, "public_url": settings.livesync_public_url}
    db.set_connection(user["id"], "sync", "connected", "Self-hosted LiveSync", details, secret_store.seal({"username": username, "password": password, "passphrase": passphrase}))
    return RedirectResponse("/settings?connected=sync#connections", 303)


@app.post("/connections/ai")
def connect_ai(request: Request, provider: str = Form(...), credential: str = Form(...), model: str = Form("")):
    user = current(request)
    credential = credential.strip()
    if provider not in {"claude", "gemini"} or not credential:
        raise HTTPException(400, "Vyber AI službu a vlož přihlašovací údaj.")
    if len(credential) > 4096:
        raise HTTPException(400, "Přihlašovací údaj je příliš dlouhý.")
    if provider == "claude":
        details = {"provider": "claude", "model": model.strip() or settings.claude_model}
        secret = {"oauth_token": credential}
        label = "Claude · předplatné"
    else:
        details = {"provider": "gemini", "model": model.strip() or settings.gemini_model}
        secret = {"api_key": credential}
        label = "Gemini API"
    db.set_connection(user["id"], "ai", "connected", label, details, secret_store.seal(secret))
    return RedirectResponse("/settings?connected=ai#connections", 303)


@app.post("/auth/demo")
def demo_login():
    if not settings.development:
        raise HTTPException(404)
    user = db.upsert_user(settings.dev_login_email, "David Herzina")
    response = RedirectResponse("/app", 303)
    response.set_cookie(COOKIE, auth.session_token(user["id"]), httponly=True, samesite="lax", max_age=2592000)
    return response


@app.post("/auth/logout")
def logout():
    response = RedirectResponse("/", 303)
    response.delete_cookie(COOKIE)
    return response


@app.get("/app", response_class=HTMLResponse)
def dashboard(request: Request):
    user = current(request)
    imports = db.all("SELECT * FROM imports WHERE user_id=? ORDER BY updated_at DESC", (user["id"],))
    counts = {row["status"]: row["count"] for row in db.all("SELECT status,count(*) count FROM imports WHERE user_id=? GROUP BY status", (user["id"],))}
    connections = db.connection_map(user["id"])
    return templates.TemplateResponse("dashboard.html", ctx(request, user, imports=imports[:6], received=len(imports), counts=counts, connections=connections))


@app.get("/notes", response_class=HTMLResponse)
def notes(request: Request, status: str = "all", q: str = ""):
    user = current(request)
    sql = "SELECT * FROM imports WHERE user_id=?"
    params: list = [user["id"]]
    if status != "all":
        sql += " AND status=?"
        params.append(status)
    if q:
        sql += " AND (title LIKE ? OR notebook LIKE ? OR target_path LIKE ?)"
        params.extend([f"%{q}%"] * 3)
    sql += " ORDER BY updated_at DESC"
    rows = db.all(sql, tuple(params))
    return templates.TemplateResponse("notes.html", ctx(request, user, imports=rows, filter_status=status, query=q))


@app.get("/notes/{note_id}", response_class=HTMLResponse)
def note_detail(note_id: int, request: Request):
    user = current(request)
    note = db.one("SELECT * FROM imports WHERE id=? AND user_id=?", (note_id, user["id"]))
    if not note:
        raise HTTPException(404)
    events = db.all("SELECT * FROM import_events WHERE import_id=? ORDER BY id", (note_id,))
    ai_result = json.loads(note["ai_json"]) if note["ai_json"] else None
    return templates.TemplateResponse("note_detail.html", ctx(request, user, note=note, events=events, ai_result=ai_result))


@app.get("/media/{note_id}")
def note_media(note_id: int, request: Request):
    user = current(request)
    note = db.one("SELECT image_path FROM imports WHERE id=? AND user_id=?", (note_id, user["id"]))
    if not note or not note["image_path"]:
        raise HTTPException(404)
    path = Path(note["image_path"]).resolve()
    allowed_root = settings.data_dir.resolve()
    if allowed_root not in path.parents or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


@app.post("/notes/{note_id}/retry")
async def retry(note_id: int, request: Request):
    user = current(request)
    note = db.one("SELECT * FROM imports WHERE id=? AND user_id=?", (note_id, user["id"]))
    if not note or not note["image_path"] or note["image_path"].startswith("/static"):
        raise HTTPException(400, "Tuto ukázkovou poznámku nelze znovu zpracovat")
    image_path = Path(note["image_path"])
    image = image_path.read_bytes()
    drive_id, _, page_id = note["source_id"].partition(":")
    with db.connect() as conn:
        conn.execute("DELETE FROM imports WHERE id=? AND user_id=?", (note_id, user["id"]))
    page = Page(note["notebook"], note["notebook"], page_id or str(note["page_number"]), note["page_number"], image, image_path.suffix, note["source_checksum"] or "")
    await pipeline.process_page(user["id"], {"id": drive_id, "name": "Ruční opakování"}, page)
    return RedirectResponse("/notes", 303)


def safe_path(value: str) -> str:
    value = value.strip().strip("/")
    if not value or ".." in value or not re.fullmatch(r"[\w\- /Á-ž.]+", value):
        raise HTTPException(400, "Neplatná cesta uvnitř vaultu")
    return value


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: int = 0, connected: str = "", error: str = ""):
    user = current(request)
    profile = db.one("SELECT * FROM user_settings WHERE user_id=?", (user["id"],))
    connections = db.connection_map(user["id"])
    sync_credentials = None
    sync_row = db.connection(user["id"], "sync")
    if sync_row and sync_row["secret_blob"]:
        sync_credentials = {**json.loads(sync_row["details_json"] or "{}"), **secret_store.open(sync_row["secret_blob"])}
    return templates.TemplateResponse("settings.html", ctx(request, user, profile=profile, connections=connections, saved=bool(saved), connected=connected, error=error, sync_credentials=sync_credentials))


@app.post("/settings/destination")
def save_destination(
    request: Request,
    note_folder: str = Form(...), attachment_folder: str = Form(...), source_label: str = Form(""),
    filename_template: str = Form(...), processing_mode: str = Form(...), save_original: str | None = Form(None),
):
    user = current(request)
    note_folder, attachment_folder = safe_path(note_folder), safe_path(attachment_folder)
    if "{title}" not in filename_template:
        raise HTTPException(400, "Šablona názvu musí obsahovat {title}")
    with db.connect() as conn:
        conn.execute("""UPDATE user_settings SET note_folder=?,attachment_folder=?,source_label=?,filename_template=?,
                     processing_mode=?,save_original=?,updated_at=? WHERE user_id=?""",
                     (note_folder, attachment_folder, source_label.strip(), filename_template.strip(), processing_mode,
                      int(save_original == "on"), now(), user["id"]))
    return RedirectResponse("/settings?saved=1#destination", 303)


@app.get("/healthz")
def health():
    return {"status": "ok", "service": "ink2vault"}
