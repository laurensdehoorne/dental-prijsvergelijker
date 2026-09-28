# Dentale Prijsvergelijker

Een lokale webapp die één zoekopdracht tegelijk uitvoert bij:

| Winkel | Prijzen zonder login | Met login |
|---|---|---|
| Dental Discount (BE) | prijs + staffelprijs | idem |
| Basiq Dental (BE) | publieke webshopprijs | klantprijs (indien anders) |
| Dental Addict (BE) | publieke prijs | prijs van je klantengroep |
| Hofmeester (NL) | geen prijzen | exacte prijs |
| Denta (BE) | geen prijzen | exacte prijs |
| Henry Schein (BE) | geen prijzen | exacte prijs |

## Starten

**Mac-app:** open **Prijsvergelijker** in je map *Apps* (`~/Applications`),
of zet hem in je Dock. De app opent in een eigen venster; venster sluiten
stopt alles. Links naar webshops openen in je gewone browser.

De app gebruikt de code uit deze map. Na een `git pull` start hij dus meteen
de nieuwe versie. Opnieuw bouwen (bv. op een andere Mac, of na een
verplaatsing van deze map):

```bash
./build_app.sh
```

Alternatief zonder app: dubbelklik `start.command` (opent in je browser op
http://localhost:8765).

Foutmeldingen van de app: `~/Library/Logs/Prijsvergelijker.log`.

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
