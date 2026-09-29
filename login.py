"""Opent een gewoon Chrome-venster waarin de gebruiker zelf inlogt.

Chrome wordt normaal gestart (geen automatiseringsvlaggen, geen --no-sandbox),
met een apart profiel per winkel. De app kijkt enkel via de debugpoort mee
en bewaart elke seconde de sessie (cookies + localStorage) in
sessions/<site>.json. Venster sluiten = klaar. Het wachtwoord zelf wordt
nooit gelezen of bewaard.

Gebruik: python login.py <site>   (zie SITES in sites.py)
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

from playwright.sync_api import Error, sync_playwright

from sites import SITES

from paths import PROFILES, SESSIONS


def find_browser():
    """Chrome, anders Edge (staat op elke Windows-pc). Beide ondersteunen de debugpoort."""
    if sys.platform == "darwin":
        candidates = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                      os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                      "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    elif sys.platform == "win32":
        env = os.environ
        dirs = [env.get("PROGRAMFILES", r"C:\Program Files"), env.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                env.get("LOCALAPPDATA", "")]
        candidates = [os.path.join(d, r"Google\Chrome\Application\chrome.exe") for d in dirs if d] + \
                     [os.path.join(d, r"Microsoft\Edge\Application\msedge.exe") for d in dirs if d]
    else:
        candidates = [shutil.which(n) or "" for n in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge")]
    if os.environ.get("PRIJSVERGELIJKER_BROWSER") == "edge":  # voor tests: Edge forceren
        candidates = [c for c in candidates if "edge" in c.lower()]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    sys.exit("Geen Chrome of Edge gevonden.")

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
    if not cookies:
        # Op Windows geeft de browserverbinding soms geen cookies terug: via het tabblad zelf
        for page in ctx.pages:
            try:
                s = ctx.new_cdp_session(page)
                try:
                    cookies = s.send("Network.getAllCookies")["cookies"]
                finally:
                    s.detach()
            except Error:
                continue
            if cookies:
                break
    return {
        "cookies": cookies,
        "origins": [{"origin": o, "localStorage": ls} for o, ls in origins.items()],
    }


COOKIE_KEYS = ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite")


def restore_cookies(browser, site):
    """Bewaarde cookies die Chrome niet (meer) heeft terugzetten, vóór de winkel laadt.
    Bijna elke winkel onthoudt de login in een sessiecookie (PHPSESSID, MSCSAuth, ...)
    die Chrome bij afsluiten weggooit; zonder dit begon het loginvenster altijd afgemeld."""
    try:
        saved = json.loads((SESSIONS / f"{site}.json").read_text()).get("cookies", [])
    except (OSError, ValueError):
        return 0
    cdp = browser.new_browser_cdp_session()
    try:
        have = {(c["name"], c["domain"], c["path"]) for c in cdp.send("Storage.getCookies")["cookies"]}
        now = time.time()
        todo = []
        for c in saved:
            if (c.get("name"), c.get("domain"), c.get("path")) in have or c.get("partitionKey"):
                continue
            exp = c.get("expires", -1)
            if not c.get("session") and exp > 0 and exp < now:
                continue  # verlopen
            param = {k: c[k] for k in COOKIE_KEYS if k in c}
            if not c.get("session") and exp > 0:
                param["expires"] = exp
            todo.append(param)
        if todo:
            cdp.send("Storage.setCookies", {"cookies": todo})
        return len(todo)
    finally:
        cdp.detach()


def open_tabs(port):
    """Aantal open tabbladen volgens Chrome zelf (betrouwbaarder dan bijhouden)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=3) as r:
            return sum(1 for t in json.load(r) if t.get("type") == "page")
    except Exception:
        return -1  # onbekend (bv. Chrome nog aan het opstarten)


def bring_to_front(pid):
    """Op Mac opent het venster anders soms achter de app."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app:
            app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    except Exception:
        pass


def browser_env():
    """Omgeving voor Chrome/Edge zonder __COMPAT_LAYER. Staat die erin (op Windows
    soms geërfd van de app), dan herstart Edge zichzelf (--edge-skip-compat-layer-relaunch):
    het proces dat wij startten stopt meteen terwijl het venster gewoon open blijft."""
    env = os.environ.copy()
    env.pop("__COMPAT_LAYER", None)
    return env


def alive(chrome, port):
    """Draait de browser nog? Ook als hij zichzelf herstartte (ander proces, zelfde poort)."""
    return chrome.poll() is None or open_tabs(port) >= 0


_final_lock = threading.Lock()
_finalized = []


def finalize(site):
    """Na het loginvenster: de nieuwe sessie (<site>.pending.json) enkel in gebruik nemen als
    je daarmee ingelogd bent, of als de oude sessie ook niet meer werkte. Zo raak je niet
    afgemeld door het venster te openen terwijl je al ingelogd was (bv. Henry Schein: de
    logincookie is tijdelijk en verdwijnt als Chrome herstart)."""
    with _final_lock:
        if _finalized:
            return
        _finalized.append(True)
        cur, pend, old = (SESSIONS / f"{site}{ext}" for ext in (".json", ".pending.json", ".old.json"))
        if not pend.exists():
            return
        check = SITES[site]["logged_in"]
        if cur.exists():
            cur.replace(old)
        pend.replace(cur)
        try:
            new_ok = check()
        except Exception:
            new_ok = True  # geen internet o.i.d.: niet zomaar de nieuwe sessie weggooien
        if not new_ok and old.exists():
            cur.replace(pend)
            old.replace(cur)
            try:
                old_ok = check()
            except Exception:
                old_ok = False
            if old_ok:
                pend.unlink(missing_ok=True)
                print(f"[login {site}] niet (opnieuw) ingelogd: vorige sessie behouden", flush=True)
                return
            cur.replace(old)
            pend.replace(cur)
        old.unlink(missing_ok=True)
        print(f"[login {site}] sessie in gebruik genomen (ingelogd: {new_ok})", flush=True)


def watchdog(chrome, port, site):
    """Vangnet naast de hoofdlus: als het venster dicht is (of nooit opende), alles
    afsluiten, ook als Playwright ergens blijft wachten op een gesloten pagina."""
    started, seen = time.time(), False
    stop = SESSIONS / f"{site}.stop"
    while alive(chrome, port):
        time.sleep(2)
        tabs = open_tabs(port)
        seen = seen or tabs > 0
        if (seen and tabs == 0) or (not seen and time.time() - started > 25) or stop.exists():
            time.sleep(3)  # hoofdlus de kans geven om zelf netjes te stoppen
            if chrome.poll() is None:
                chrome.terminate()
            finalize(site)
            os._exit(0)


def save(state, out):
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.chmod(tmp, 0o600)
    tmp.replace(out)


def main(site):
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # zodat 'finally' Chrome ook sluit
    if hasattr(signal, "SIGUSR1"):  # diagnose: 'kill -USR1 <pid>' schrijft de stack naar het log
        import faulthandler
        faulthandler.register(signal.SIGUSR1)
    SESSIONS.mkdir(exist_ok=True)
    PROFILES.mkdir(exist_ok=True)
    out = SESSIONS / f"{site}.pending.json"  # pas bij sluiten in gebruik (zie finalize)
    stop = SESSIONS / f"{site}.stop"  # de app vraagt zo netjes te stoppen ('Opnieuw openen')
    stop.unlink(missing_ok=True)
    port = free_port()

    chrome = subprocess.Popen([
        find_browser(),
        f"--user-data-dir={PROFILES / site}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1100,850",
        "about:blank",  # winkel pas laden nadat de bewaarde cookies terug zijn (restore_cookies)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=browser_env())
    threading.Thread(target=watchdog, args=(chrome, port, site), daemon=True).start()

    try:
        with sync_playwright() as p:
            browser = None
            launched = time.time()
            for _ in range(60):  # wachten tot Chrome klaar is
                try:
                    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                    break
                except Error:
                    # bij een herstart van de browser is de poort even weg: niet te snel opgeven
                    if not alive(chrome, port) and time.time() - launched > 10:
                        return
                    time.sleep(0.5)
            if browser is None:
                return
            try:
                n = restore_cookies(browser, site)
                if n:
                    print(f"[login {site}] {n} bewaarde cookies teruggezet", flush=True)
            except Exception as e:
                print(f"[login {site}] cookies terugzetten mislukt: {e}", flush=True)
            opened = False

            started = time.time()
            seen_page = False
            origins_seen = []
            last_count = -1
            while browser.is_connected() and alive(chrome, port):
                tabs = open_tabs(port)
                if tabs > 0 and not opened and browser.contexts and browser.contexts[0].pages:
                    opened = True
                    try:
                        browser.contexts[0].pages[0].goto(LOGIN_URLS[site], wait_until="commit")
                    except Error:
                        pass
                if tabs > 0 and not seen_page:
                    seen_page = True
                    bring_to_front(chrome.pid)
                    if sys.platform == "win32" and browser.contexts and browser.contexts[0].pages:
                        try:  # Windows: tabblad (en daarmee het venster) naar voren
                            browser.contexts[0].pages[0].bring_to_front()
                        except Error:
                            pass
                if tabs == 0 and seen_page:
                    break  # venster gesloten (Chrome blijft op Mac soms draaien)
                if stop.exists():
                    break  # app opent een nieuw loginvenster: browser sluiten en sessie afwerken
                if not seen_page and time.time() - started > 20:
                    break  # Chrome opende geen venster: opgeven i.p.v. blijven hangen
                ctx = browser.contexts[0] if browser.contexts else None
                if ctx and seen_page:
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
                        n = len(state["cookies"])
                        if n != last_count:  # in het logbestand: helpt bij problemen
                            print(f"[login {site}] {n} cookies bewaard", flush=True)
                            last_count = n
                time.sleep(1.5)
    finally:
        if chrome.poll() is None:
            chrome.terminate()
            try:
                chrome.wait(5)
            except subprocess.TimeoutExpired:
                chrome.kill()
        finalize(site)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in LOGIN_URLS:
        sys.exit(__doc__)
    main(sys.argv[1])
