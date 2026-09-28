"""Mijn lijst en de verzendinstellingen synchroniseren via een map die al gesynchroniseerd
wordt (iCloud Drive, Google Drive, OneDrive, Dropbox, Nextcloud...). Logins gaan nooit mee:
die horen bij de browser op elke computer.

Samenvoegen in drie richtingen: 'base' = de lijst bij de vorige synchronisatie, 'mine' = de
lijst op deze computer, 'theirs' = de lijst in de gedeelde map (misschien intussen door de
andere computer aangepast). Wat op deze computer sinds 'base' veranderde (toegevoegd,
gewijzigd, verwijderd), wordt op 'theirs' toegepast; de rest van 'theirs' blijft staan.
"""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import paths

CONFIG = paths.DATA / "sync.json"            # welke map (per computer, gaat zelf niet mee)
BASE = paths.DATA / "favorites.base.json"    # lijst bij de vorige synchronisatie
SUBDIR = "Prijsvergelijker"
lock = threading.Lock()


def _read(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(p, data):
    p = Path(p)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def folder():
    return (_read(CONFIG) or {}).get("folder") or ""


def shared_dir():
    """De map in de cloud, of None als synchroniseren uit staat of de map er (nu) niet is
    (bv. Google Drive nog niet gestart): dan werkt de app gewoon lokaal verder."""
    f = folder()
    if not f or not Path(f).is_dir():
        return None
    d = Path(f) / SUBDIR
    try:
        d.mkdir(exist_ok=True)
    except OSError:
        return None
    return d


def set_folder(f):
    if f and not Path(f).is_dir():
        raise ValueError(f"Map niet gevonden: {f}")
    _write(CONFIG, {"folder": f})
    BASE.unlink(missing_ok=True)  # eerste keer: beide lijsten samen (niets als 'verwijderd' zien)


def _ensure_local(p):
    """iCloud kan bestanden 'enkel in de cloud' bewaren (.naam.icloud): eerst downloaden."""
    if sys.platform != "darwin" or p.exists() or not (p.parent / f".{p.name}.icloud").exists():
        return
    subprocess.run(["brctl", "download", str(p)], capture_output=True, timeout=10)
    for _ in range(20):
        if p.exists():
            return
        time.sleep(0.5)


def _norm(f):
    f = f if isinstance(f, dict) else {}
    return {"searches": list(f.get("searches") or []),
            "groups": [g for g in (f.get("groups") or []) if isinstance(g, dict)]}


def _gkey(g):
    return (g.get("name") or "").strip().lower()


def _ikey(it):
    return f"{it.get('site')}|{it.get('code')}"


def merge(base, mine, theirs):
    base, mine, theirs = _norm(base), _norm(mine), _norm(theirs)

    # bewaarde zoekopdrachten
    low = lambda xs: {x.lower(): x for x in xs}
    b, m, t = low(base["searches"]), low(mine["searches"]), low(theirs["searches"])
    gone = set(b) - set(m)
    searches = [x for k, x in t.items() if k not in gone] + \
               [x for k, x in m.items() if k not in b and k not in t]

    # groepen en hun producten
    bg = {_gkey(g): g for g in base["groups"]}
    mg = {_gkey(g): g for g in mine["groups"]}
    groups = [{**g, "items": list(g.get("items") or [])} for g in theirs["groups"]]
    tg = {_gkey(g): g for g in groups}
    for k in set(bg) - set(mg):  # groep hier verwijderd
        if k in tg:
            groups.remove(tg.pop(k))
    for k, g in mg.items():
        old = {_ikey(i): i for i in bg.get(k, {}).get("items") or []}
        new = {_ikey(i): i for i in g.get("items") or []}
        changed = {ik: it for ik, it in new.items() if old.get(ik) != it}
        removed = set(old) - set(new)
        if not changed and not removed:
            continue
        if k not in tg:
            if not changed:
                continue
            tg[k] = {**g, "items": []}
            groups.append(tg[k])
        cur = tg[k]["items"]
        cur[:] = [i for i in cur if _ikey(i) not in removed]
        pos = {_ikey(i): n for n, i in enumerate(cur)}
        for ik, it in changed.items():
            if ik in pos:
                cur[pos[ik]] = it
            else:
                cur.append(it)
    return {"searches": searches, "groups": [g for g in groups if g["items"]]}


def sync(mine):
    """Lijst van deze computer bewaren en samenvoegen met de gedeelde map.
    Geeft de lijst terug zoals ze nu overal staat."""
    with lock:
        mine = _norm(mine)
        d = shared_dir()
        if d is None:
            _write(paths.FAVORITES, mine)
            return mine
        f = d / "favorites.json"
        _ensure_local(f)
        theirs = _read(f)
        if theirs is None and f.exists():
            # (nog) niet leesbaar, bv. half gesynchroniseerd: niets overschrijven, later opnieuw
            _write(paths.FAVORITES, mine)
            return mine
        result = merge(_read(BASE), mine, theirs) if theirs is not None else mine
        _write(f, result)
        _write(paths.FAVORITES, result)
        _write(BASE, result)
        return result


def load():
    return sync(_read(paths.FAVORITES))


# ---------- verzendinstellingen: klein, gewoon de laatste versie ----------

def read_settings():
    d = shared_dir()
    if d is not None:
        _ensure_local(d / "settings.json")
        data = _read(d / "settings.json")
        if data is not None:
            return data
    return _read(paths.SETTINGS) or {}


def write_settings(data):
    _write(paths.SETTINGS, data)
    d = shared_dir()
    if d is not None:
        _write(d / "settings.json", data)


# ---------- mappen die al gesynchroniseerd worden ----------

def candidates():
    home = Path.home()
    out = []
    if sys.platform == "darwin":
        out.append(("iCloud Drive", home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"))
        cs = home / "Library" / "CloudStorage"
        for p in sorted(cs.iterdir()) if cs.is_dir() else []:
            if p.name.startswith("GoogleDrive-"):
                for sub in ("My Drive", "Mijn Drive"):
                    out.append((f"Google Drive ({p.name.split('-', 1)[1]})", p / sub))
            elif p.is_dir():
                out.append((p.name.split("-", 1)[0], p))
        out.append(("Dropbox", home / "Dropbox"))
    elif sys.platform == "win32":
        import os
        import string
        out.append(("iCloud Drive", home / "iCloudDrive"))
        for letter in string.ascii_uppercase[3:]:  # Google Drive voor desktop: eigen stationsletter
            for sub in ("My Drive", "Mijn Drive"):
                out.append((f"Google Drive ({letter}:)", Path(f"{letter}:/{sub}")))
        if os.environ.get("OneDrive"):
            out.append(("OneDrive", Path(os.environ["OneDrive"])))
        out.append(("Dropbox", home / "Dropbox"))
    seen, res = set(), []
    for label, p in out:
        try:
            ok = p.is_dir()
        except OSError:
            ok = False
        if ok and str(p) not in seen:
            seen.add(str(p))
            res.append({"label": label, "path": str(p)})
    return res
