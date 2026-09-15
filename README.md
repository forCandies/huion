# Huion

Huion je malá lokální aplikace pro macOS. Čte sešity synchronizované aplikací Huion Note přes iCloud, každou novou stránku nechá přečíst AI a uloží ji jako samostatnou Markdown poznámku do běžného Obsidian vaultu v iCloud Drive.

```text
Huion Note na iPhonu/iPadu → iCloud → Huion + Codex/Claude na Macu
                                             ↓
iPhone / iPad / Mac ← iCloud Drive ← Obsidian vault ← Markdown + originální obrázek
```

Nevzniká žádný veřejný server, databáze ani vlastní synchronizační služba. Obsidian dál používáš standardně a hotové poznámky můžeš upravovat, přesouvat i propojovat. Huion už jednou importovanou stránku nepřepíše.

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
- Codex CLI přihlášený přes ChatGPT předplatné, případně Claude Code přihlášený přes Claude Pro/Max.

Huion automaticky nabídne veřejný iCloud kontejner Huion Note:

```text
~/Library/Mobile Documents/iCloud~com~huion~note/Documents
```

Sešity v něm mohou být ZIP archivy bez přípony; Huion je rozpozná podle obsahu. Jako alternativní zdroj lze stále použít lokální data aplikace nebo běžnou složku se zálohami `.huionnoteios` či `.zip`.

## První spuštění

### Instalace na nový Mac

Rozbal distribuční ZIP, otevři jeho složku v Terminálu a spusť:

```bash
./install.sh
```

Instalátor nepotřebuje `sudo`, nic nestahuje a nepřidává externí Python balíčky. Program uloží do:

```text
~/Library/Application Support/Huion/runtime
```

Příkaz vytvoří jako `~/.local/bin/huion`. Pokud `~/.local/bin` ještě není v `PATH`, přidej do `~/.zprofile`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Na novém Macu nainstaluj Codex CLI a přihlas se účtem ChatGPT:

```bash
codex login
```

Pokud Codex není přihlášený, Huion umí jako náhradní variantu použít také [Claude Code](https://docs.anthropic.com/en/docs/claude-code/getting-started):

```bash
claude auth login
```

### Konfigurace

Po instalaci spusť:

```bash
huion configure
huion doctor
huion import
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

Po úspěšném ručním importu nainstaluj uživatelskou službu macOS:

```bash
huion service install
```

Služba se spustí po přihlášení a ve výchozím nastavení kontroluje nové zálohy každou minutu. Správa služby:

```bash
huion service status
huion service uninstall
```

Stav importů a poslední chyby:

```bash
huion status
huion retry
tail -f "$HOME/Library/Application Support/Huion/huion.log"
```

## Příkazy

Samotný příkaz otevře interaktivní menu se všemi běžnými akcemi:

```bash
huion
```

Stejné akce lze spouštět přímo:

```bash
huion import          # importuje všechny dosud neimportované stránky, staré i nové
huion retry           # hned zopakuje chybné importy
huion reprocess       # znovu zpracuje i hotové stránky a zachová staré poznámky
huion status          # ukáže počty a poslední zpracované stránky
huion reset errors    # zapomene chyby, aby je další import zkusil znovu
huion configure       # změní zdrojovou složku a umístění v Obsidianu
huion doctor          # zkontroluje složky, AI nástroje a přihlášení
huion service install # zapne automatické zpracování na pozadí
```

Úplné zapomenutí importní historie je záměrně potvrzované:

```bash
huion reset
```

`huion reset` a `huion reset all` jsou stejné. Reset nikdy nemaže ani nepřepisuje poznámky v Obsidianu. Příští import vytvoří nové kopie stránek, které už dříve zpracoval. Příkaz `huion reprocess` provede úplný reset a nový import v jednom kroku.

## Bezpečné chování

- Hotová poznámka se při dalších kontrolách nikdy automaticky nepřepisuje.
- Když se zdrojová stránka později změní, aplikace pouze zapíše upozornění do logu.
- Zápis poznámky i obrázku je atomický, takže Obsidian neuvidí napůl zapsaný soubor.
- Přerušení mezi zápisem souboru a uložením stavu nevytvoří při dalším spuštění duplikát.
- Chyby se při sledování opakují s postupně delší prodlevou; ruční `huion retry` čekání přeskočí.

Stav aplikace je v `~/Library/Application Support/Huion/`. Přihlašovací údaje si spravuje Codex CLI nebo Claude Code; Huion žádné heslo ani API klíč neukládá. Obrázek každé nové stránky se během zpracování odešle zvolenému AI poskytovateli. Přihlášený Codex má přednost, Claude slouží jako fallback.

## Obsidian na iPhonu a iPadu

Na všech zařízeních otevři v Obsidianu tentýž vault uložený v iCloudu. iCloud synchronizuje Markdown soubory i obrázky. Poznámky lze po importu normálně měnit; lokální evidence importů brání Huionu v jejich přepsání.

Pro spolehlivé zpracování musí Mac běžet, být přihlášený, mít v Huion Note dokončenou iCloud synchronizaci a dostupný iCloud vault. Samotné čtení a úpravy v Obsidianu na mobilních zařízeních na běhu Macu nezávisí.

## Vývoj a kontrola

Aplikace nemá žádné externí Python závislosti. Testy:

```bash
PYTHONPYCACHEPREFIX=/tmp/huion-pycache python3 -m unittest discover -s tests -v
```

Volitelně lze příkaz nainstalovat do virtuálního prostředí:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/huion --help
```
