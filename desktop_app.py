"""Start de prijsvergelijker als desktop-app (Mac en Windows): server in de
achtergrond en de interface in een eigen venster (WebKit op Mac, Edge WebView2
op Windows). Venster sluiten = app stoppen."""
import sys
import threading

import webview

import app

import paths

ICON = paths.RES / "assets" / "icon.png"


def log_to_file():
    """Zonder console gaat print() nergens heen: naar een logbestand in de gegevensmap."""
    # ingepakte app (via Finder/Startmenu gestart) of Windows pythonw: geen console
    if not paths.FROZEN and sys.stdout is not None and sys.stderr is not None:
        return
    f = open(paths.DATA / "log.txt", "a", buffering=1, encoding="utf-8")
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
    if len(sys.argv) > 2 and sys.argv[1] == "--login":
        # ingepakte app: het loginvenster draait als tweede proces van dezelfde app
        import login
        login.main(sys.argv[2])
        return
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
    webview.start(private_mode=False, storage_path=str(paths.PROFILES / "webview"))
    if server:
        server.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    main()
