"""Opent een gewoon Chrome-venster waarin de gebruiker zelf inlogt.

Chrome wordt normaal gestart (geen automatiseringsvlaggen, geen --no-sandbox),
met een apart profiel per winkel. De app kijkt enkel via de debugpoort mee
en bewaart elke seconde de sessie (cookies + localStorage) in
sessions/<site>.json. Venster sluiten = klaar. Het wachtwoord zelf wordt
nooit gelezen of bewaard.

Gebruik: python login.py <site>   (dentaldiscount, basiq, dentaladdict, hofmeester, denta, henryschein)
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Error, sync_playwright

from sites import SITES

ROOT = Path(__file__).parent
SESSIONS = ROOT / "sessions"
PROFILES = ROOT / "profiles"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

LOGIN_URLS = {k: v["login_url"] for k, v in SITES.items()}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def snapshot(browser, ctx):
    """Cookies + localStorage van de open tabbladen. Bewust niet
    ctx.storage_state(): die opent per website kort een extra (zichtbaar)
    tabblad om localStorage te lezen."""
    origins = {}
    for page in ctx.pages:
        try:
            origin = page.evaluate("location.origin")
            if not origin.startswith("http"):
                continue
            entries = page.evaluate("Object.entries(localStorage)")
        except Error:
            continue  # pagina is aan het laden
        origins[origin] = [{"name": k, "value": v} for k, v in entries]
    cdp = browser.new_browser_cdp_session()
    try:
        cookies = cdp.send("Storage.getCookies")["cookies"]
    finally:
        cdp.detach()
    return {
        "cookies": cookies,
        "origins": [{"origin": o, "localStorage": ls} for o, ls in origins.items()],
    }


def save(state, out):
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.chmod(tmp, 0o600)
    tmp.replace(out)


def main(site):
    SESSIONS.mkdir(exist_ok=True)
    PROFILES.mkdir(exist_ok=True)
    out = SESSIONS / f"{site}.json"
    port = free_port()

    chrome = subprocess.Popen([
        CHROME,
        f"--user-data-dir={PROFILES / site}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1100,850",
        LOGIN_URLS[site],
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        with sync_playwright() as p:
            browser = None
            for _ in range(60):  # wachten tot Chrome klaar is
                try:
                    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                    break
                except Error:
                    if chrome.poll() is not None:
                        return
                    time.sleep(0.5)
            if browser is None:
                return

            seen_page = False
            origins_seen = []
            while chrome.poll() is None and browser.is_connected():
                ctx = browser.contexts[0] if browser.contexts else None
                pages = ctx.pages if ctx else []
                if pages:
                    seen_page = True
                elif seen_page:
                    break  # laatste venster gesloten (Chrome blijft op Mac soms open)
                if ctx:
                    try:
                        state = snapshot(browser, ctx)
                    except Error:
                        state = None  # bv. tijdens een paginawissel: volgende keer opnieuw
                    if state:
                        # localStorage van eerder bezochte sites behouden
                        known = {o["origin"]: o for o in origins_seen}
                        known.update({o["origin"]: o for o in state["origins"]})
                        origins_seen[:] = known.values()
                        state["origins"] = origins_seen
                        save(state, out)
                time.sleep(2)
    finally:
        if chrome.poll() is None:
            chrome.terminate()
            try:
                chrome.wait(5)
            except subprocess.TimeoutExpired:
                chrome.kill()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in LOGIN_URLS:
        sys.exit(__doc__)
    main(sys.argv[1])
