#!/bin/bash
# Maakt Prijsvergelijker.app en zet die in ~/Applications.
# De app start de code uit déze map (dus na een 'git pull' meteen de nieuwe versie).
set -e
cd "$(dirname "$0")"
PROJECT="$(pwd)"
APP="$HOME/Applications/Prijsvergelijker.app"

if [ ! -x .venv/bin/python ]; then
  echo "Python-omgeving installeren..."
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp macapp/icon.icns "$APP/Contents/Resources/icon.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Prijsvergelijker</string>
  <key>CFBundleDisplayName</key><string>Prijsvergelijker</string>
  <key>CFBundleIdentifier</key><string>be.praktijk.prijsvergelijker</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Prijsvergelijker</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/Prijsvergelijker" <<LAUNCH
#!/bin/bash
cd "$PROJECT" || { osascript -e 'display alert "Prijsvergelijker" message "Projectmap niet gevonden: $PROJECT"'; exit 1; }
exec .venv/bin/python mac_app.py >> "\$HOME/Library/Logs/Prijsvergelijker.log" 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/Prijsvergelijker"
touch "$APP"
echo "Klaar: $APP"
