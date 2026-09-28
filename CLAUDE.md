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
  (tag `vX.Y.Z` pushen). Versie staat in `paths.py`.

## Open probleem (sept 2026): loginvensters werken niet op Windows
Gebruiker meldt: in de Windows-app (release v1.0.2) "werken de loginvensters niet".
Exacte symptoom nog onbekend — **eerst uitzoeken**: opent er geen Chrome-venster, opent
het wel maar blijft de app "niet ingelogd", of een foutmelding?

Wat al bekend is:
- Op een GitHub Windows-runner (`.github/workflows/windows-test.yml`) werkt het wél:
  `Prijsvergelijker.exe --login basiq` start, Chrome opent de loginpagina, 13 cookies
  worden bewaard. (Dental Discount toont op runners een Cloudflare-controle → 0 cookies,
  dat is een runner-artefact.)
- v1.0.2 voegde toe: `AllowSetForegroundWindow` in `app.py` + `page.bring_to_front()` in
  `login.py` (vermoeden: venster opende achter de app), cookie-fallback, logregels
  `[login <site>] N cookies bewaard` in `%APPDATA%\Prijsvergelijker\log.txt`.

Nuttige checks op de Windows-pc:
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
