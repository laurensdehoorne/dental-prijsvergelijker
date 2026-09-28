"""Waar de app zijn bestanden vindt en bewaart.

- RES: meegeleverde bestanden (static/, assets/). In een ingepakte app (PyInstaller)
  staan die in een tijdelijke/alleen-lezen map (sys._MEIPASS).
- DATA: gegevens van de gebruiker (logins, favorieten, instellingen). Altijd in de
  gebruikersmap, zodat updates van de app ze niet wissen:
    Mac:     ~/Library/Application Support/Prijsvergelijker
    Windows: %APPDATA%\\Prijsvergelijker
"""
import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Prijsvergelijker"
VERSION = "1.0.12"
FROZEN = getattr(sys, "frozen", False)
SRC = Path(__file__).parent
RES = Path(getattr(sys, "_MEIPASS", SRC))


def _data_dir():
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_NAME


# Ingepakte app: Python heeft dan geen toegang tot de certificaten van het systeem
# (fout CERTIFICATE_VERIFY_FAILED bij elke webwinkel). Daarom de meegeleverde lijst gebruiken.
if FROZEN and not os.environ.get("SSL_CERT_FILE"):
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass

DATA = _data_dir()
DATA.mkdir(parents=True, exist_ok=True)
SESSIONS = DATA / "sessions"
PROFILES = DATA / "profiles"
FAVORITES = DATA / "favorites.json"
SETTINGS = DATA / "settings.json"
LISTS = DATA / "lists.json"  # afnamelijsten/favorieten van de winkels (cache)


def _migrate_from(old):
    """Eenmalig: gegevens uit de projectmap (oudere versies) overnemen."""
    for name in ("favorites.json", "settings.json"):
        if (old / name).exists() and not (DATA / name).exists():
            shutil.copy2(old / name, DATA / name)
    for name in ("sessions", "profiles"):
        if (old / name).is_dir() and not (DATA / name).exists():
            shutil.copytree(old / name, DATA / name, ignore=shutil.ignore_patterns("Singleton*"))


if not FROZEN:
    _migrate_from(SRC)


def login_command(site):
    """Commando om het loginvenster te starten (ingepakte app: zichzelf met --login)."""
    if FROZEN:
        return [sys.executable, "--login", site]
    return [sys.executable, str(SRC / "login.py"), site]
