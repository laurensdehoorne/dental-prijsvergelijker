# Dentale Prijsvergelijker — context voor Claude

Desktop-app (Mac + Windows) die prijzen vergelijkt bij 7 dentale webshops en
producten rechtstreeks in hun winkelmandje kan leggen. Gebruiker: tandarts
(Nederlandstalig, België). Antwoord in het Nederlands.

## Architectuur
- `desktop_app.py` — ingang: start `app.py`-server (127.0.0.1:8765) in een thread en
  opent een pywebview-venster (Mac: WebKit, Windows: Edge WebView2).
  Met `--login <site>` draait hetzelfde programma als loginproces (ingepakte app).
- `app.py` — HTTP-server + API (`/api/search`, `/api/status`, `/api/login/<site>`,
  `/api/carts`, `/api/cart/add|remove`, `/api/favorites`, `/api/settings`).
- `sites.py` — zoeken + "ben ik ingelogd?" per winkel (urllib, cookies uit sessiebestand).
- `carts.py` — winkelmandje toevoegen/uitlezen/verwijderen per winkel. **Nooit bestellen.**
- `login.py` — start een *gewone* Chrome (anders Edge) met `--remote-debugging-port` en een
  eigen profiel per winkel; Playwright `connect_over_cdp` leest elke ~2 s cookies
  (`Storage.getCookies`, fallback `Network.getAllCookies`) + localStorage en schrijft
  `sessions/<site>.json`. Venster sluiten = klaar. Een watchdog-thread sluit alles af als
  het venster dicht is of er na 25 s geen tabblad is. Wachtwoorden worden nooit gelezen.
- `paths.py` — gegevensmap: Mac `~/Library/Application Support/Prijsvergelijker`,
  Windows `%APPDATA%\Prijsvergelijker` (sessions/, profiles/, favorites.json,
  settings.json, log.txt). In de ingepakte app: `SSL_CERT_FILE` = certifi (anders
  CERTIFICATE_VERIFY_FAILED).
- `static/index.html` — hele UI (vanilla JS).
- Release: `prijsvergelijker.spec` (PyInstaller) + `.github/workflows/release.yml`
  (tag `vX.Y.Z` pushen). Versie staat in `paths.py`. Mac wordt apart gebouwd voor
  Apple Silicon (`macos-latest`) en Intel (`macos-15-intel`); geen universal2 omdat de
  Playwright-driver (node) en wheels per architectuur zijn.

## Opgelost in v1.0.3: loginvensters werkten niet op Windows
**Symptoom:** in de Windows-app opende het loginvenster (Edge; geen Chrome op die pc), maar
na inloggen bleef de app "niet ingelogd"; `log.txt` bleef leeg, geen cookies bewaard.

**Oorzaak:** het loginproces (gestart via `/api/login/<site>`) erfde de omgevingsvariabele
`__COMPAT_LAYER` van de app. Edge herstart zichzelf dan (`--edge-skip-compat-layer-relaunch`):
het Edge-proces dat `login.py` startte stopt meteen terwijl het venster open blijft.
`login.py` volgde dat proces met `chrome.poll()`, dacht dat het venster dicht was en stopte.
Bewijs: `Prijsvergelijker.exe --login basiq` rechtstreeks → werkt (11 cookies); met
`__COMPAT_LAYER=Installer` → faalt identiek aan via de app.

**Fix (`login.py`):**
- `browser_env()`: browser starten zonder `__COMPAT_LAYER`.
- `alive(chrome, port)`: browser telt als actief als het proces draait óf de debugpoort
  antwoordt; gebruikt in watchdog, hoofdlus en verbind-wachtlus (die geeft pas na 10 s op).
- `PRIJSVERGELIJKER_BROWSER=edge` forceert Edge (voor tests).
- Regressietest: stap "Regressie - login met __COMPAT_LAYER en Edge" in
  `.github/workflows/windows-test.yml` (faalt als er 0 cookies bewaard worden).

**v1.0.4 — niet meer afgemeld door het loginvenster te openen:** tijdens het inloggen schrijft
`login.py` naar `sessions/<site>.pending.json`; `finalize()` (bij sluiten, ook via watchdog)
neemt die enkel in gebruik als je ermee ingelogd bent, of als de oude sessie ook niet meer
werkte. Aanleiding: Henry Schein's logincookie `MSCSAuth` is een sessiecookie die Chrome bij
herstart kwijt is — het venster openen overschreef een geldige sessie.

Eerder (v1.0.2): `AllowSetForegroundWindow` + `page.bring_to_front()` (venster vooraan),
cookie-fallback `Network.getAllCookies`, logregels `[login <site>] N cookies bewaard`.
Let op: GitHub-runners krijgen bij Dental Discount een Cloudflare-controle → 0 cookies;
test daarom met Basiq.

Nuttige checks bij loginproblemen op Windows (naslag):
1. `%APPDATA%\Prijsvergelijker\log.txt` lezen.
2. Is Chrome geïnstalleerd? (`login.find_browser()`; anders Edge.)
3. Handmatig: `dist\Prijsvergelijker\Prijsvergelijker.exe --login basiq` of vanuit broncode
   `python login.py basiq` en kijken wat er gebeurt / welke fout.
4. Draait er al een Chrome met hetzelfde `--user-data-dir` (profiellock)?
5. Antivirus/SmartScreen die `node.exe` (Playwright-driver in `_internal\playwright\driver`)
   of het starten van Chrome met `--remote-debugging-port` blokkeert?
6. Grootte/inhoud van `%APPDATA%\Prijsvergelijker\sessions\<site>.json` na inloggen.

## Werken vanaf broncode op Windows
```
git clone https://github.com/laurensdehoorne/dental-prijsvergelijker.git
cd dental-prijsvergelijker
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python desktop_app.py        (of: python app.py → browser op localhost:8765)
```
Bouwen: `.venv\Scripts\pip install pyinstaller` en `.venv\Scripts\pyinstaller prijsvergelijker.spec`.

## Afspraken
- Commit-berichten in het Nederlands; wijzigingen pushen naar `main` is ok.
- Mandjes: testproducten altijd weer verwijderen; nooit iets van de gebruiker aanraken,
  nooit afrekenen.
- Na een fix: nieuwe versie in `paths.py` + tag pushen voor een release.
