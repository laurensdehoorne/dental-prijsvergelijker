"""Start de prijsvergelijker als Mac-app: server in de achtergrond en de
interface in een eigen venster (WebKit). Venster sluiten = app stoppen."""
import sys
import threading
from pathlib import Path

import webview

import app

ROOT = Path(__file__).parent
ICON = ROOT / "macapp" / "icon.png"


def mac_branding():
    """Naam en icoon in het Dock/menu (anders toont macOS 'Python')."""
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
