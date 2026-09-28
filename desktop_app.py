"""Start de prijsvergelijker als desktop-app (Mac en Windows): server in de
achtergrond en de interface in een eigen venster (WebKit op Mac, Edge WebView2
op Windows). Venster sluiten = app stoppen."""
import os
import sys
import threading
from pathlib import Path

import webview

import app

ROOT = Path(__file__).parent
ICON = ROOT / "assets" / "icon.png"


def log_to_file():
    """Zonder console (Windows pythonw) gaat print() nergens heen: naar een logbestand."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Prijsvergelijker"
    base.mkdir(parents=True, exist_ok=True)
    f = open(base / "log.txt", "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr = f


def mac_branding():
    """Naam en icoon in het Dock/menu (anders toont macOS 'Python')."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = "Prijsvergelijker"
        if ICON.exists():
            NSApplication.sharedApplication().setApplicationIconImage_(
                NSImage.alloc().initByReferencingFile_(str(ICON)))
    except Exception:
        pass


def main():
    log_to_file()
    try:
        server = app.make_server()
    except OSError:
        server = None  # poort bezet: er draait al een server (bv. start.command); die gebruiken
    if server:
        threading.Thread(target=server.serve_forever, daemon=True).start()

    mac_branding()
    webview.create_window("Dentale Prijsvergelijker", f"http://localhost:{app.PORT}",
                          width=1440, height=900, min_size=(800, 600))
    # private_mode=False: localStorage (weergave, filters) blijft bewaard
    webview.start(private_mode=False, storage_path=str(ROOT / "profiles" / "webview"))
    if server:
        server.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    main()
