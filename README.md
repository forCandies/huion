# Ink2Vault

Ink2Vault sleduje složku se zálohami ručně psaných sešitů na Google Drive. Každou stránku převede na samostatnou Markdown poznámku a jednou ji vloží do běžného Obsidian vaultu.

```text
Google Drive → parser stránky → lokální OCR → AI shrnutí a úkoly → Markdown → Self-hosted LiveSync → Obsidian
```

Výrobce vstupního zařízení je jen technický konektor. V názvech a poznámkách se používá uživatelské označení zdroje, například **Rukopis**.

## Co je zapojené

- přihlášení pouze přes Google OAuth,
- přesný case-insensitive whitelist `ALLOWED_EMAILS`,
- samostatná data, nastavení, Drive token a LiveSync databáze pro každý účet,
- Drive OAuth s read-only oprávněním a šifrovaným refresh tokenem,
- automatické hledání nových `.huionnoteios` / ZIP záloh,
- ověřený parser iOS zálohy; jedna stránka = jedna poznámka,
- lokální české OCR přes TuzkaOCR,
- AI oprava přepisu, shrnutí, úkoly a štítky přes Claude nebo Gemini,
- nastavitelná složka poznámek, příloh, označení zdroje a šablona názvu,
- vytvoření izolovaného CouchDB účtu a databáze z webu,
- vložení nové poznámky přes oficiální Self-hosted LiveSync CLI,
- dashboard, originál, OCR výstup, Markdown, průběh a chyby,
- ochrana hotových importů před pozdějším automatickým přepsáním.

## Lokální náhled

```bash
cp .env.example .env
docker compose up --build
```

Web poběží na [http://localhost:3000](http://localhost:3000). V `APP_ENV=development` je dostupný ukázkový účet s devíti reálnými stránkami vzorové zálohy.

První sestavení trvá déle: image aplikace kompiluje připnutou verzi LiveSync CLI a OCR image obsahuje ONNX modely.

## Produkční nasazení v Dockploy

Kompletní postup je v [DEPLOY.md](DEPLOY.md). Pro Dockploy použij připravený soubor `docker-compose.dockploy.yml`; očekává hotové image z Docker Hubu a nepotřebuje lokální `.env`.

Pro ruční nasazení mimo Dockploy lze stále použít oba původní Compose soubory:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Nastav `DOCKERHUB_USERNAME`; aplikace a OCR se pak stáhnou z:

```text
<DOCKERHUB_USERNAME>/ink2vault:latest
<DOCKERHUB_USERNAME>/ink2vault:ocr-latest
<DOCKERHUB_USERNAME>/ink2vault:couchdb-latest
```

CouchDB není veřejně vystavená v produkčním Compose override automaticky. V Dockploy jí nastav samostatnou HTTPS doménu, například `https://sync.example.cz`, a stejnou adresu vlož do `LIVESYNC_PUBLIC_URL`. Web aplikaci vystav například jako `https://ink.example.cz`.

Minimální produkční proměnné:

```dotenv
APP_URL=https://ink.example.cz
APP_ENV=production
APP_SECRET=<nejméně 32 náhodných znaků>
ENCRYPTION_KEY=<Fernet klíč>
REGISTRATION_MODE=invite
ALLOWED_EMAILS=prvni@example.cz,druhy@example.cz
GOOGLE_CLIENT_ID=<OAuth Web Client ID>
GOOGLE_CLIENT_SECRET=<OAuth Client Secret>
COUCHDB_ADMIN_USER=ink2vault
COUCHDB_ADMIN_PASSWORD=<dlouhé náhodné heslo>
LIVESYNC_PUBLIC_URL=https://sync.example.cz
DOCKERHUB_USERNAME=<docker-hub-uživatel>
```

Fernet klíč vytvoříš například:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

V Google Cloud Console povol **Google Drive API** a přidej obě callback URL:

```text
https://ink.example.cz/auth/google/callback
https://ink.example.cz/connections/drive/callback
```

## Nastavení Obsidianu

1. Ve webu otevři **Nastavení → Vytvořit vault sync**.
2. Ink2Vault vytvoří osobní CouchDB účet, databázi a E2E heslo.
3. V Obsidianu na Macu, iPhonu a iPadu nainstaluj komunitní plugin **Self-hosted LiveSync**.
4. Do pluginu opiš URI, uživatele, heslo, databázi a E2E heslo z webu.
5. Na stejném vaultu nepoužívej zároveň jiný zapisující sync.

Na iOS/iPadOS synchronizuje plugin během otevřené aplikace. Dlouhodobý běh na pozadí omezuje samotný iOS.

## AI zpracování

V **Nastavení → AI zpracování** lze zvolit jednu ze dvou možností:

- **Claude z předplatného:** na počítači s nainstalovaným Claude Code spusť `claude setup-token` a výsledný token vlož do webu. Volání přes `claude -p` čerpají limity Claude Pro/Max. Po vyčerpání limitu import skončí chybou a lze ho později zopakovat.
- **Gemini API:** vytvoř klíč v Google AI Studio a vlož ho do webu. Lze využít samostatnou bezplatnou API kvótu.

Přihlašovací údaje jsou uložené šifrovaně pro každého uživatele. Do AI odchází OCR text, název sešitu a číslo stránky; originální obrázek zůstává u OCR služby.

## GitHub Actions → Docker Hub

`.github/workflows/docker-registry.yaml` se spustí při každém pushi do `main`. Bez release tagů rovnou přepíše `latest`, `ocr-latest` a `couchdb-latest` pro `linux/amd64` a `linux/arm64`.

V GitHub repozitáři nastav Actions secrets:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN` — Docker Hub access token s oprávněním Write

## Data a bezpečnost

- Google tokeny a osobní LiveSync údaje jsou v SQLite šifrované pomocí `ENCRYPTION_KEY`.
- Dočasný LiveSync konfigurační soubor existuje jen během synchronizace a má režim `0600`.
- CouchDB má pro každého uživatele oddělený účet a databázi.
- Identita stránky vychází ze stabilního ID uvnitř zálohy.
- Existující import se znovu nevytvoří ani nepřepíše. Další úpravy a přesuny v Obsidianu zůstanou uživateli.

## OCR licence

Kód TuzkaOCR je Apache-2.0, jeho přibalené modely jsou CC BY-NC-SA 4.0. Výchozí OCR image je tedy určená pro nekomerční použití. Pro firemní/komerční provoz nastav jiné kompatibilní OCR API nebo si vyřeš licenci modelu.

## Kontroly

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
docker compose config
curl http://localhost:3000/healthz
```
