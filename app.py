"""Lokale webapp: vergelijk prijzen van dentale webshops.

Start met ./start.command en open http://localhost:8765
"""
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import carts
import favsync
import sites

import paths

PORT = 8765
SITES = sites.SITES
login_procs = {}
pool = ThreadPoolExecutor(max_workers=8)
lists_pool = ThreadPoolExecutor(max_workers=7)  # apart: lijsten vernieuwen vertraagt zoeken niet
refresh_pool = ThreadPoolExecutor(max_workers=7)  # idem voor prijzen vernieuwen (Mijn lijst)
LOCAL_HOSTS = ("127.0.0.1", "localhost")


def run_search(site, query):
    try:
        items = SITES[site]["search"](query)
        # niets gevonden -> opnieuw met 'blauw' i.p.v. 'blue', of 'capsule' i.p.v. 'capsules'
        for alt in (sites.translate(query), sites.singular(query)):
            if items or not alt:
                continue
            items = SITES[site]["search"](alt)
        return {"items": items, "error": None}
    except Exception as e:
        traceback.print_exc()
        return {"items": [], "error": f"{type(e).__name__}: {e}"}


def load_settings():
    data = favsync.read_settings()
    shipping = {k: dict(v) for k, v in carts.DEFAULT_SHIPPING.items()}
    for k, v in (data.get("shipping") or {}).items():
        if k in shipping:
            shipping[k].update(v)
    return {"shipping": shipping}


def read_carts():
    """Alle mandjes parallel uitlezen (enkel winkels waar je ingelogd bent)."""
    def one(site):
        if not SITES[site]["logged_in"]():
            return {"items": [], "error": None, "not_logged_in": True, "url": carts.CARTS[site].url}
        try:
            return {**carts.CARTS[site].read(), "error": None}
        except Exception as e:
            traceback.print_exc()
            return {"items": [], "error": str(e), "url": carts.CARTS[site].url}
    futures = {s: pool.submit(one, s) for s in carts.CARTS}
    return {"carts": {s: f.result() for s, f in futures.items()}, **load_settings()}


LISTS_MAX_AGE = 1800  # daarna op de achtergrond vernieuwen
lists_cache = {"time": 0, "data": None, "refreshing": False}
lists_lock = threading.Lock()  # nooit twee keer tegelijk alle winkels afgaan


def _load_lists_file():
    try:
        saved = json.loads(paths.LISTS.read_text())
        lists_cache.update(time=saved["time"], data=saved["sites"])
    except (OSError, ValueError, KeyError):
        pass


def _fetch_lists():
    """Alle winkels parallel (enkel waar je ingelogd bent). Lukt het bij een winkel niet
    (fout, afgemeld), dan blijft de vorige lijst staan: nodig voor 'eerder besteld'."""
    started = time.time()
    with lists_lock:
        if lists_cache["time"] >= started:  # net door een ander verzoek opgehaald
            return

        def one(site):
            cfg = SITES[site]
            if not cfg.get("lists"):
                return {"lists": [], "error": None, "unsupported": True}
            if not cfg["logged_in"]():
                return {"lists": [], "error": None, "not_logged_in": True}
            try:
                return {"lists": cfg["lists"](), "error": None}
            except Exception as e:
                traceback.print_exc()
                return {"lists": [], "error": f"{type(e).__name__}: {e}"}

        futures = {s: lists_pool.submit(one, s) for s in SITES}
        old = lists_cache["data"] or {}
        data = {}
        for s, f in futures.items():
            r = f.result()
            if (r.get("error") or r.get("not_logged_in")) and old.get(s, {}).get("lists"):
                r["lists"] = old[s]["lists"]
            data[s] = r
        now = time.time()
        lists_cache.update(time=now, data=data)
        tmp = paths.LISTS.with_suffix(".tmp")
        tmp.write_text(json.dumps({"time": now, "sites": data}))
        os.chmod(tmp, 0o600)
        tmp.replace(paths.LISTS)


def _refresh_lists_background():
    lists_cache["refreshing"] = True
    try:
        _fetch_lists()
    except Exception:
        traceback.print_exc()
    finally:
        lists_cache["refreshing"] = False


def read_lists(fresh=False):
    """Meteen de bewaarde lijsten (ook na herstarten van de app); te oud = op de achtergrond
    vernieuwen. fresh = nu opnieuw ophalen (knop Vernieuwen)."""
    if lists_cache["data"] is None:
        _load_lists_file()
    if fresh or lists_cache["data"] is None:
        _fetch_lists()
    elif time.time() - lists_cache["time"] > LISTS_MAX_AGE and not lists_cache["refreshing"]:
        lists_cache["refreshing"] = True
        threading.Thread(target=_refresh_lists_background, daemon=True).start()
    return {"time": lists_cache["time"], "refreshing": lists_cache["refreshing"],
            "sites": lists_cache["data"]}


def refresh_items(items):
    """Actuele prijzen voor een lijst bewaarde producten; per winkel parallel."""
    by_site = {}
    for i, it in enumerate(items):
        by_site.setdefault(it["site"], []).append(i)

    def work(site, idxs):
        cache = {}
        return [(i, sites.refresh(site, items[i]["code"], items[i]["name"], cache, items[i].get("url", "")))
                for i in idxs]

    out = [None] * len(items)
    for f in [refresh_pool.submit(work, s, idxs) for s, idxs in by_site.items() if s in SITES]:
        for i, res in f.result():
            out[i] = res
    return out


STATUS_MAX_AGE = 60
_status_cache = {}  # site -> (mtime sessiebestand, tijd, ingelogd)


def _logged_in_cached(site):
    """'Ingelogd?' kost een paginaopvraag per winkel; maximaal 1 keer per minuut, tenzij het
    sessiebestand veranderde (inloggen/afmelden): dan meteen opnieuw."""
    try:
        mtime = (sites.SESSIONS / f"{site}.json").stat().st_mtime
    except OSError:
        mtime = None
    hit = _status_cache.get(site)
    if hit and hit[0] == mtime and time.time() - hit[1] < STATUS_MAX_AGE:
        return hit[2]
    value = bool(SITES[site]["logged_in"]())
    _status_cache[site] = (mtime, time.time(), value)
    return value


def status():
    futures = {s: pool.submit(_logged_in_cached, s) for s in SITES}
    out = {}
    for s, f in futures.items():
        proc = login_procs.get(s)
        out[s] = {
            "label": SITES[s]["label"],
            "note": SITES[s]["note"],
            "logged_in": bool(f.result()),
            "login_open": proc is not None and proc.poll() is None,
        }
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def foreign(self):
        """Verzoek van een andere website? Die mag de app niet aansturen (mandjes, afmelden)
        of uitlezen (DNS-rebinding): enkel de app zelf op 127.0.0.1/localhost."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        origin = self.headers.get("Origin")
        return host not in LOCAL_HOSTS or (
            origin is not None and urllib.parse.urlparse(origin).hostname not in LOCAL_HOSTS)

    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.foreign():
            return self.send_error(403)
        url = urllib.parse.urlparse(self.path)
        if url.path == "/":
            body = (paths.RES / "static" / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/search":
            q = urllib.parse.parse_qs(url.query).get("q", [""])[0].strip()
            if not q:
                return self.send_json({"error": "Geen zoekterm"}, 400)
            futures = {s: pool.submit(run_search, s, q) for s in SITES}
            self.send_json({s: f.result() for s, f in futures.items()})
        elif url.path == "/api/status":
            self.send_json(status())
        elif url.path == "/api/lists":
            self.send_json(read_lists(fresh="fresh" in urllib.parse.parse_qs(url.query)))
        elif url.path == "/api/carts":
            self.send_json(read_carts())
        elif url.path == "/api/settings":
            self.send_json(load_settings())
        elif url.path == "/api/synonyms":
            self.send_json(sites.SYNONYMS)
        elif url.path == "/api/favorites":
            self.send_json(favsync.load())  # samengevoegd met de gedeelde map (als die aan staat)
        elif url.path == "/api/sync":
            self.send_json({"folder": favsync.folder(), "active": favsync.shared_dir() is not None,
                            "candidates": favsync.candidates()})
        else:
            self.send_error(404)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_PUT(self):
        if self.foreign():
            return self.send_error(403)
        if self.path == "/api/settings":
            data = self.read_json()
            favsync.write_settings({"shipping": data.get("shipping", {})})
            return self.send_json(load_settings())
        if self.path == "/api/sync":
            try:
                favsync.set_folder((self.read_json().get("folder") or "").strip())
            except ValueError as e:
                return self.send_json({"error": str(e)}, 400)
            return self.send_json({"ok": True, "favorites": favsync.load()})
        if self.path != "/api/favorites":
            return self.send_error(404)
        self.send_json({"ok": True, "favorites": favsync.sync(self.read_json())})

    def do_POST(self):
        if self.foreign():
            return self.send_error(403)
        if self.path == "/api/refresh":
            return self.send_json({"items": refresh_items(self.read_json().get("items", []))})
        if self.path in ("/api/cart/add", "/api/cart/remove"):
            # Enkel in het mandje leggen of eruit halen; bestellen gebeurt altijd in de webwinkel zelf.
            d = self.read_json()
            cart = carts.CARTS.get(d.get("site"))
            if not cart:
                return self.send_json({"error": "Onbekende winkel"}, 400)
            try:
                if self.path.endswith("add"):
                    qty = int(d.get("qty") or 1)
                    if not 1 <= qty <= 999:
                        return self.send_json({"error": "Ongeldig aantal"}, 400)
                    return self.send_json({"ok": True, "cart": carts.add_checked(cart, d["item"], qty)})
                cart.remove(d["line"])
                return self.send_json({"ok": True, "cart": cart.read()})
            except carts.CartError as e:
                return self.send_json({"error": str(e)}, 400)
            except Exception as e:
                traceback.print_exc()
                return self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)
        parts = self.path.strip("/").split("/")  # api/login/<site>
        if len(parts) != 3 or parts[0] != "api" or parts[2] not in SITES:
            return self.send_error(404)
        action, site = parts[1], parts[2]
        if action == "login":
            proc = login_procs.get(site)
            stop = sites.SESSIONS / f"{site}.stop"
            if proc is not None and proc.poll() is None:
                # al een loginvenster open (misschien verdwenen/achter iets): opnieuw beginnen.
                # Eerst netjes laten stoppen via een stopbestand: op Windows is terminate() hard
                # (geen finally in login.py), dan blijft de browser het profiel vasthouden.
                stop.touch()
                try:
                    proc.wait(8)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            stop.unlink(missing_ok=True)
            if sys.platform == "win32":
                # Windows laat een venster van een ander programma normaal niet naar voren komen;
                # de app (die net aangeklikt werd) mag die toestemming wel geven.
                import ctypes
                ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
            login_procs[site] = subprocess.Popen(paths.login_command(site), cwd=paths.DATA)
            self.send_json({"ok": True})
        elif action == "logout":
            (sites.SESSIONS / f"{site}.json").unlink(missing_ok=True)
            self.send_json({"ok": True})
        else:
            self.send_error(404)


def make_server(port=PORT):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    server = make_server()
    url = f"http://localhost:{PORT}"
    print(f"Prijsvergelijker draait op {url}  (Ctrl+C om te stoppen)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
