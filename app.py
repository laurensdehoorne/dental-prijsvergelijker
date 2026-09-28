"""Lokale webapp: vergelijk prijzen van dentale webshops.

Start met ./start.command en open http://localhost:8765
"""
import json
import subprocess
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import carts
import sites

import paths

PORT = 8765
FAVORITES = paths.FAVORITES
SETTINGS = paths.SETTINGS
fav_lock = threading.Lock()
SITES = sites.SITES
login_procs = {}
pool = ThreadPoolExecutor(max_workers=8)


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


def load_favorites():
    try:
        return json.loads(FAVORITES.read_text())
    except (OSError, ValueError):
        return {"searches": [], "groups": []}


def load_settings():
    try:
        data = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        data = {}
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


def refresh_items(items):
    """Actuele prijzen voor een lijst bewaarde producten; per winkel parallel."""
    by_site = {}
    for i, it in enumerate(items):
        by_site.setdefault(it["site"], []).append(i)

    def work(site, idxs):
        cache = {}
        return [(i, sites.refresh(site, items[i]["code"], items[i]["name"], cache)) for i in idxs]

    out = [None] * len(items)
    for f in [pool.submit(work, s, idxs) for s, idxs in by_site.items() if s in SITES]:
        for i, res in f.result():
            out[i] = res
    return out


def status():
    futures = {s: pool.submit(cfg["logged_in"]) for s, cfg in SITES.items()}
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

    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
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
        elif url.path == "/api/carts":
            self.send_json(read_carts())
        elif url.path == "/api/settings":
            self.send_json(load_settings())
        elif url.path == "/api/synonyms":
            self.send_json(sites.SYNONYMS)
        elif url.path == "/api/favorites":
            self.send_json(load_favorites())
        else:
            self.send_error(404)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_PUT(self):
        if self.path == "/api/settings":
            data = self.read_json()
            SETTINGS.write_text(json.dumps({"shipping": data.get("shipping", {})}, indent=1))
            return self.send_json(load_settings())
        if self.path != "/api/favorites":
            return self.send_error(404)
        data = self.read_json()
        with fav_lock:
            tmp = FAVORITES.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
            tmp.replace(FAVORITES)
        self.send_json({"ok": True})

    def do_POST(self):
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
                    cart.add(d["item"], qty)
                else:
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
            if proc is not None and proc.poll() is None:
                # al een loginvenster open (misschien verdwenen/achter iets): opnieuw beginnen
                proc.terminate()
                try:
                    proc.wait(8)
                except subprocess.TimeoutExpired:
                    proc.kill()
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
