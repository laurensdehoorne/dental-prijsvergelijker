# PyInstaller-bouwbestand voor Mac en Windows.
# Bouwen:  pyinstaller prijsvergelijker.spec
# Resultaat: dist/Prijsvergelijker.app (Mac) of dist/Prijsvergelijker/ (Windows)
import sys

from PyInstaller.utils.hooks import collect_all

datas = [("static", "static"), ("assets", "assets")]
binaries = []
hiddenimports = ["login"]  # wordt pas geladen bij '--login'
for pkg in ("playwright", "webview"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

icon = "assets/icon.icns" if sys.platform == "darwin" else "assets/icon.ico"

a = Analysis(["desktop_app.py"], datas=datas, binaries=binaries, hiddenimports=hiddenimports)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Prijsvergelijker",
          console=False, icon=icon, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Prijsvergelijker", upx=False)

if sys.platform == "darwin":
    import re
    version = re.search(r'VERSION = "([^"]+)"', open("paths.py").read()).group(1)
    app = BUNDLE(coll, name="Prijsvergelijker.app", icon=icon,
                 bundle_identifier="be.praktijk.prijsvergelijker",
                 info_plist={"CFBundleShortVersionString": version,
                             "CFBundleVersion": version,
                             "NSHighResolutionCapable": True,
                             "LSMinimumSystemVersion": "12.0"})
