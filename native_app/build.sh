#!/bin/bash
# Builds Trading Desk.app from source, into native_app/build/. With --install, also
# puts it in ~/Applications, where it can be opened and kept in the Dock. With --icon,
# first redraws AppIcon.icns from icon.html, the icon's one source.
# The desk itself must be in ~/trading-desk (the app finds it there).
#   ./native_app/build.sh [--icon] [--install]
set -e
cd "$(dirname "$0")"

ICON=0
INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --icon) ICON=1 ;;
    --install) INSTALL=1 ;;
    *) echo "Usage: ./native_app/build.sh [--icon] [--install]" >&2; exit 2 ;;
  esac
done

# icon.html drawn by WebKit at 1024 pixels (render_icon.swift refuses a drawing without
# clear corners), scaled by sips to the ten sizes macOS asks for, packed by iconutil.
if [ "$ICON" = 1 ]; then
  SET="build/AppIcon.iconset"
  rm -rf "$SET"
  mkdir -p "$SET"
  echo "Drawing the icon..."
  swiftc -O render_icon.swift -o build/render_icon
  build/render_icon "$(pwd)/icon.html" build/icon_1024.png
  for size in 16 32 128 256 512; do
    sips -z $size $size build/icon_1024.png --out "$SET/icon_${size}x${size}.png" >/dev/null
    sips -z $((size * 2)) $((size * 2)) build/icon_1024.png --out "$SET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$SET" -o AppIcon.icns
  echo "Drawn: $(pwd)/AppIcon.icns"
fi

APP="build/Trading Desk.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

echo "Compiling..."
swiftc -O main.swift -o "$APP/Contents/MacOS/Trading Desk"
cp AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"

# NSAllowsLocalNetworking: without it macOS refuses plain http to 127.0.0.1 and the
# window stays on "Starting the desk".
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>Trading Desk</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleIdentifier</key>
  <string>local.tradingdesk.app</string>
  <key>CFBundleName</key>
  <string>Trading Desk</string>
  <key>CFBundleDisplayName</key>
  <string>Trading Desk</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key>
    <true/>
  </dict>
</dict>
</plist>
PLIST
codesign --force --sign - "$APP" >/dev/null 2>&1 || true    # an ad-hoc signature, for this Mac only
echo "Built: $(pwd)/$APP"

if [ "$INSTALL" = 1 ]; then
  mkdir -p "$HOME/Applications"
  rm -rf "$HOME/Applications/Trading Desk.app"
  cp -R "$APP" "$HOME/Applications/"
  echo "Installed: ~/Applications/Trading Desk.app"
fi
