#!/bin/zsh
# Builds MLX-Audio.app: a real macOS app bundle whose own name and icon show in the Dock and
# menu bar, and which opens MLX-Audio in its own window (mlx_audio/app_window.py) instead of a
# browser tab. Closing the window (or Cmd+Q) quits the app and stops the server.
#
# The executable inside the bundle is a two-line shell script that hands over to the private
# Python environment. macOS keeps showing the bundle's name and icon after that hand-over
# (checked in a fresh VM: Dock icon and window title were right; the menu bar said "Python"
# until app_window.py renamed it from code, which it now does).
#
# Usage: make_app.sh <python-executable-in-venv> <port> <target-applications-dir> <server-log-dir>
# Optional env: MLXA_LOG_FILE (server output file), MLXA_ICON (path to an .icns file)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$1"
PORT="$2"
TARGET_DIR="$3"
SERVER_LOG_DIR="$4"

if [ -z "$VENV_PYTHON" ] || [ -z "$PORT" ] || [ -z "$TARGET_DIR" ] || [ -z "$SERVER_LOG_DIR" ]; then
  echo "Usage: make_app.sh <venv-python> <port> <target-dir> <server-log-dir>" >&2
  exit 1
fi

ICON="${MLXA_ICON:-$SCRIPT_DIR/MLX-Audio.icns}"
LOG_FILE="${MLXA_LOG_FILE:-$HOME/Library/Logs/MLX-Audio.log}"
APP="$TARGET_DIR/MLX-Audio.app"

mkdir -p "$TARGET_DIR" "$SERVER_LOG_DIR" "$(dirname "$LOG_FILE")"

# Clean up leftovers of the earlier two-icon design when this is an update: the separate Stop
# app, the launchd job that used to run the server, and its runner script.
launchctl remove "com.mlxaudio.server.$PORT" >/dev/null 2>&1 || true
rm -rf "$TARGET_DIR/Stop MLX-Audio.app"
rm -f "$(dirname "$SERVER_LOG_DIR")/run-server.sh"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

if [ -f "$ICON" ]; then
  cp "$ICON" "$APP/Contents/Resources/MLX-Audio.icns"
else
  echo "Note: no icon file at $ICON; the app will use a generic icon." >&2
fi

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key><string>MLX-Audio</string>
	<key>CFBundleDisplayName</key><string>MLX-Audio</string>
	<key>CFBundleIdentifier</key><string>com.mlxaudio.app</string>
	<key>CFBundleExecutable</key><string>MLX-Audio</string>
	<key>CFBundleIconFile</key><string>MLX-Audio</string>
	<key>CFBundlePackageType</key><string>APPL</string>
	<key>CFBundleShortVersionString</key><string>1.0</string>
	<key>LSMinimumSystemVersion</key><string>12.0</string>
	<key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
	<key>NSHighResolutionCapable</key><true/>
	<key>NSMicrophoneUsageDescription</key><string>MLX-Audio uses the microphone for live speech-to-text.</string>
</dict>
</plist>
PLIST

# %q shell-quotes each value, so paths with spaces, quotes or & are safe.
{
  echo '#!/bin/sh'
  printf 'exec %q -m mlx_audio.app_window --port %q --log-dir %q --log-file %q\n' \
    "$VENV_PYTHON" "$PORT" "$SERVER_LOG_DIR" "$LOG_FILE"
} > "$APP/Contents/MacOS/MLX-Audio"
chmod +x "$APP/Contents/MacOS/MLX-Audio"

# Ad-hoc signature (free, no developer account): keeps macOS from treating the bundle as damaged.
codesign --force --sign - "$APP" >/dev/null 2>&1 || echo "Note: could not sign the app; it may still work." >&2
touch "$APP"

echo "Installed 'MLX-Audio' to $TARGET_DIR"
