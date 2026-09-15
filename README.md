# Ink2Vault

Ink2Vault je malá lokální aplikace pro macOS. Čte sešity synchronizované aplikací Huion Note přes iCloud, každou novou stránku nechá přečíst Claudem a uloží ji jako samostatnou Markdown poznámku do běžného Obsidian vaultu v iCloud Drive.

```text
Huion Note na iPhonu/iPadu → iCloud → Huion Note na Macu → Ink2Vault + Claude
                                                               ↓
iPhone / iPad / Mac ← iCloud Drive ← Obsidian vault ← Markdown + originální obrázek
```

Nevzniká žádný veřejný server, databáze ani vlastní synchronizační služba. Obsidian dál používáš standardně a hotové poznámky můžeš upravovat, přesouvat i propojovat. Ink2Vault už jednou importovanou stránku nepřepíše.

## Co aplikace vytvoří

Pro každou stránku vznikne jedna poznámka obsahující:

- krátký název a shrnutí,
- vyčištěný přepis rukopisu,
- rozpoznané úkoly jako Obsidian checkboxy,
- navržené štítky,
- vložený originální obrázek stránky,
- stabilní interní ID, díky kterému se stránka neimportuje podruhé.

Označení zdroje je **Rukopis**; název výrobce se v poznámkách nepoužívá.

## Předpoklady

- macOS s Pythonem 3.9 nebo novějším,
- Huion Note nainstalovaný na Apple Silicon Macu se zapnutou iCloud synchronizací,
- Obsidian vault vytvořený v iCloud Drive,
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) přihlášený k účtu, jehož limity chceš používat.

Ink2Vault automaticky nabídne živou datovou složku Huion Note:

```text
~/Library/Containers/com.huion.note/Data/Documents/newData
```

Jako alternativní zdroj lze stále použít běžnou složku se zálohami `.huionnoteios` nebo `.zip`, například z Google Drive.

## První spuštění

V adresáři projektu spusť:

```bash
claude auth login
./bin/ink2vault configure
./bin/ink2vault doctor
./bin/ink2vault scan
```

`configure` se zeptá na:

1. lokální složku se synchronizovanými sešity Huion Note,
2. konkrétní Obsidian vault v iCloud Drive,
3. cílovou složku poznámek uvnitř vaultu,
4. cílovou složku originálních obrázků.

Typická cesta k vaultu v iCloudu vypadá takto:

```text
~/Library/Mobile Documents/iCloud~md~obsidian/Documents/MujVault
```

Pokud macOS vyžádá přístup k datům jiné aplikace nebo k iCloudu, povol ho Terminálu a později i procesu běžícímu na pozadí.

## Automatický provoz

Po úspěšném ručním skenu nainstaluj uživatelskou službu macOS:

```bash
./bin/ink2vault service install
```

Služba se spustí po přihlášení a ve výchozím nastavení kontroluje nové zálohy každou minutu. Správa služby:

```bash
./bin/ink2vault service status
./bin/ink2vault service uninstall
```

Stav importů a poslední chyby:

```bash
./bin/ink2vault status
./bin/ink2vault scan --retry-now
tail -f "$HOME/Library/Application Support/Ink2Vault/ink2vault.log"
```

## Bezpečné chování

- Hotová poznámka se při dalších kontrolách nikdy automaticky nepřepisuje.
- Když se zdrojová stránka později změní, aplikace pouze zapíše upozornění do logu.
- Zápis poznámky i obrázku je atomický, takže Obsidian neuvidí napůl zapsaný soubor.
- Přerušení mezi zápisem souboru a uložením stavu nevytvoří při dalším spuštění duplikát.
- Chyby se při sledování opakují s postupně delší prodlevou; ruční `--retry-now` čekání přeskočí.

Stav aplikace je v `~/Library/Application Support/Ink2Vault/`. Přihlašovací údaje si spravuje Claude Code; Ink2Vault žádné heslo ani API klíč neukládá. Obrázek každé nové stránky se během zpracování odešle službě Claude.

## Obsidian na iPhonu a iPadu

Na všech zařízeních otevři v Obsidianu tentýž vault uložený v iCloudu. iCloud synchronizuje Markdown soubory i obrázky. Poznámky lze po importu normálně měnit; lokální evidence importů brání Ink2Vaultu v jejich přepsání.

Pro spolehlivé zpracování musí Mac běžet, být přihlášený, mít v Huion Note dokončenou iCloud synchronizaci a dostupný iCloud vault. Samotné čtení a úpravy v Obsidianu na mobilních zařízeních na běhu Macu nezávisí.

## Vývoj a kontrola

Aplikace nemá žádné externí Python závislosti. Testy:

```bash
PYTHONPYCACHEPREFIX=/tmp/ink2vault-pycache python3 -m unittest discover -s tests -v
```

Volitelně lze příkaz nainstalovat do virtuálního prostředí:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/ink2vault --help
```
