# Nasazení Ink2Vault na Dockploy

Pro veřejný provoz použij dvě HTTPS adresy:

- `https://poznamky.example.cz` → služba `app`, port `8000`
- `https://sync.example.cz` → služba `couchdb`, port `5984`

Služba `ocr` zůstává neveřejná.

## 1. GitHub a Docker Hub

1. Vytvoř GitHub repozitář a nahraj do něj tento projekt do větve `main`.
2. Na Docker Hub vytvoř repozitář `ink2vault`.
3. V Docker Hub vytvoř access token s oprávněním Read/Write.
4. V GitHub repozitáři otevři **Settings → Secrets and variables → Actions** a přidej:
   - `DOCKERHUB_USERNAME`
   - `DOCKERHUB_TOKEN`
5. Push do `main` sestaví tři tagy:
   - `<uživatel>/ink2vault:latest`
   - `<uživatel>/ink2vault:ocr-latest`
   - `<uživatel>/ink2vault:couchdb-latest`

## 2. DNS

V DNS vytvoř záznamy pro obě domény směrem na veřejnou IP serveru s Dockploy. Pokud používáš Cloudflare proxy, WebSockety a dlouhé HTTP požadavky musí zůstat povolené.

## 3. Google OAuth

1. V Google Cloud Console vytvoř projekt.
2. Povol **Google Drive API**.
3. Nastav OAuth consent screen. Pro Google Workspace lze použít režim **Internal**. U ostatních účtů přidej povolené účty jako test users a před trvalým provozem přepni aplikaci do produkčního režimu.
4. Vytvoř OAuth Client typu **Web application**.
5. Přidej redirect URI:

```text
https://poznamky.example.cz/auth/google/callback
https://poznamky.example.cz/connections/drive/callback
```

Uschovej `GOOGLE_CLIENT_ID` a `GOOGLE_CLIENT_SECRET`.

## 4. Produkční hodnoty

Vygeneruj tři nezávislé hodnoty:

```bash
openssl rand -hex 32
openssl rand -hex 32
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Použij je postupně jako `APP_SECRET`, `COUCHDB_ADMIN_PASSWORD` a `ENCRYPTION_KEY`.

## 5. Dockploy

1. Vytvoř nový **Compose** projekt z GitHub repozitáře.
2. Jako Compose soubor vyber `docker-compose.dockploy.yml`.
3. Do Environment vlož následující hodnoty a nahraď zástupné údaje:

```dotenv
DOCKERHUB_USERNAME=tvuj-dockerhub-ucet
APP_URL=https://poznamky.example.cz
APP_SECRET=<první náhodná hodnota>
ENCRYPTION_KEY=<Fernet klíč>
ALLOWED_EMAILS=prvni@example.cz,druhy@example.cz
GOOGLE_CLIENT_ID=<OAuth client ID>
GOOGLE_CLIENT_SECRET=<OAuth client secret>
COUCHDB_ADMIN_USER=ink2vault
COUCHDB_ADMIN_PASSWORD=<druhá náhodná hodnota>
LIVESYNC_PUBLIC_URL=https://sync.example.cz
CLAUDE_MODEL=sonnet
GEMINI_MODEL=gemini-2.5-flash
SYNC_INTERVAL_SECONDS=300
```

4. Nastav domény:
   - `poznamky.example.cz` na službu `app`, container port `8000`, HTTPS zapnuté.
   - `sync.example.cz` na službu `couchdb`, container port `5984`, HTTPS zapnuté.
5. Službě `ocr` doménu nepřidávej.
6. Proveď deploy a ověř `https://poznamky.example.cz/healthz`.

Pokud jsou Docker Hub image privátní, přidej v Dockploy Docker registry přihlášení. U veřejného repozitáře to není potřeba.

## 6. Připojení služeb ve webu

1. Přihlas se povoleným Google účtem.
2. Připoj Google Drive a vlož ID složky se zálohami.
3. Pro Claude spusť na důvěryhodném počítači `claude setup-token` a token vlož do **Nastavení → AI zpracování**. Token nepatří do Dockploy Environment.
4. Klikni na **Vytvořit vault sync**. Web zobrazí osobní CouchDB údaje a E2E heslo.

## 7. Obsidian na Macu, iPhonu a iPadu

1. Na prvním zařízení otevři cílový vault a nainstaluj komunitní plugin **Self-hosted LiveSync**.
2. Zvol ruční konfiguraci CouchDB a opiš URI, uživatele, heslo, databázi a E2E heslo z Ink2Vault.
3. Otestuj spojení a inicializuj prázdnou vzdálenou databázi.
4. Z fungujícího prvního zařízení vytvoř v pluginu nový Setup URI pro další zařízení.
5. Setup URI použij na iPhonu a iPadu. Mobilní Obsidian vyžaduje platný HTTPS certifikát.

Na stejném vaultu nezapínej současně Obsidian Sync ani iCloud synchronizaci.
