# Dentale Prijsvergelijker

Desktop-app voor **Mac en Windows**. Een lokale webapp die één zoekopdracht tegelijk uitvoert bij:

| Winkel | Prijzen zonder login | Met login |
|---|---|---|
| Dental Discount (BE) | prijs + staffelprijs | idem |
| Basiq Dental (BE) | publieke webshopprijs | klantprijs (indien anders) |
| Dental Addict (BE) | publieke prijs | prijs van je klantengroep |
| Hofmeester (NL) | geen prijzen | exacte prijs |
| ADT (BE) | geen prijzen | exacte prijs |
| Denta (BE) | geen prijzen | exacte prijs |
| Henry Schein (BE) | geen prijzen | exacte prijs |

## Installeren en starten

### Download (aanbevolen)

Op de [Releases-pagina](https://github.com/laurensdehoorne/dental-prijsvergelijker/releases)
staan kant-en-klare versies — geen Python nodig:

- **Mac**: `Prijsvergelijker-mac.zip` → uitpakken → naar *Apps* slepen.
  Eerste keer: rechtsklik → **Open** → **Open** (niet door Apple ondertekend).
- **Windows**: `Prijsvergelijker-windows.zip` → uitpakken → `Prijsvergelijker.exe`.
  Bij "Windows heeft uw pc beschermd": **Meer info** → **Toch uitvoeren**.

Je gegevens (logins, favorieten, instellingen) staan los van de app en blijven
bewaard bij een update:
- Mac: `~/Library/Application Support/Prijsvergelijker`
- Windows: `%APPDATA%\Prijsvergelijker`

### Nieuwe release maken

```bash
git tag v1.0.1 && git push origin v1.0.1
```

GitHub bouwt dan automatisch de Mac- en Windows-versie en zet ze bij de release
(zie `.github/workflows/release.yml`). Pas ook `VERSION` in `paths.py` aan.

### Vanaf de broncode

### Mac

```bash
./build_app.sh
```

Dat maakt **Prijsvergelijker** in je map *Apps* (`~/Applications`); zet hem
in je Dock. De app opent in een eigen venster; venster sluiten stopt alles.
Foutmeldingen: `~/Library/Logs/Prijsvergelijker.log`.

### Windows

1. Haal de code binnen: `git clone` of op GitHub *Code → Download ZIP*
   (en uitpakken, bv. in `Documenten\dental-prijsvergelijker`).
2. Dubbelklik `windows\Installeer.bat`. Dat installeert zo nodig Python 3.12
   (via winget), de benodigde pakketten, en maakt een snelkoppeling
   **Prijsvergelijker** op het bureaublad en in het Startmenu.
3. Inloggen gebeurt in Chrome, of in Edge als Chrome niet geïnstalleerd is.

Foutmeldingen: `%LOCALAPPDATA%\Prijsvergelijker\log.txt`.
Zonder app-venster (in de browser): `windows\start-in-browser.bat`.

### Bijwerken

De app draait de code uit deze map: na `git pull` (of een nieuwe ZIP op
dezelfde plek) meteen de nieuwe versie. Op Windows na een update best
`Installeer.bat` nog eens draaien (voor nieuwe pakketten).

Links naar webshops openen altijd in je gewone browser.

## Inloggen

Klik bij een winkel op **Inloggen**. Er opent een Chrome-venster; log daar
zelf in zoals altijd en **sluit dan het venster**. De app bewaart enkel de
sessie (cookies) in `sessions/`, nooit je wachtwoord. Verloopt een sessie,
dan staat er weer "niet ingelogd": gewoon opnieuw inloggen.

De app controleert de loginstatus bij het openen én bij elke zoekopdracht.
Ben je bij een winkel afgemeld waar je eerder ingelogd was, dan verschijnt
bovenaan een melding met een knop **Opnieuw inloggen**.

Stuurt een winkel een inloglink per e-mail? Klik die dan niet aan (dan
opent hij in Safari), maar kopieer hem en plak hem in het Chrome-venster
van de app.

## Hoe vergelijken

- **Beste match** (standaard): producten die alle woorden van je zoekopdracht
  bevatten staan bovenaan, daarbinnen de goedkoopste eerst. Minder passende
  producten worden lichter getoond. Kleurcodes worden gelijkgetrokken
  ("A 2 D", "a-3d" = A2D), dus zoek gerust op bv. `es flow high a2`.
- **Goedkoopste**: puur op prijs (per stuk waar mogelijk).
- De groene markering = goedkoopste binnen de beste matches.
- **Alles samen**: alle resultaten in één tabel.
- **Per winkel**: vier kolommen naast elkaar.
- Met het filterveld verfijn je zonder opnieuw te zoeken (bv. `medium`).
- "Stuks" wordt uit de productnaam gehaald (bv. "100 stuks", "2 x 50 st",
  "(100)"); dat lukt niet altijd, controleer bij twijfel.

## Favorieten

- **☆ naast de zoekknop** bewaart de huidige zoekterm. Bewaarde zoektermen
  staan als knoppen bovenaan: één klik zoekt meteen bij alle winkels.
- **☆ bij een product** zet het op **Mijn lijst**, in een groep naar keuze.
  Zet hetzelfde product van verschillende winkels in dezelfde groep: de lijst
  toont per groep de goedkoopste (per stuk) in het groen.
- **Prijzen vernieuwen** zoekt alle bewaarde producten opnieuw op en toont
  prijswijzigingen (▲/▼ met de oude prijs).
- Alles staat in `favorites.json` in deze map.

## Winkelmandjes

- **🛒 bij een product** (zoekresultaten en Mijn lijst) legt het rechtstreeks
  in je mandje bij die winkel, met het aantal dat je kiest.
- Tabblad **🛒 Mandjes** toont de mandjes van alle winkels waar je ingelogd
  bent: inhoud, subtotaal, en hoeveel je nog tekortkomt voor gratis verzending.
  Met **🔍 elders** zoek je een product uit je mandje bij alle winkels; met ✕
  haal je het uit het mandje.
- **Bestellen en afrekenen doe je altijd zelf in de webwinkel** (knop
  "Open mandje in webwinkel"). De app bestelt nooit.
- **⚙︎ Verzendvoorwaarden**: gratis-vanaf-bedrag en verzendkosten per winkel
  (excl. btw), aan te passen als je andere afspraken hebt. Dental Addict geeft
  zelf door hoeveel je nog tekortkomt; dat heeft voorrang.

Bekend: Henry Schein meldt je na 1 uur automatisch af.
