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

# Why the app carries its own copy of Python's executable: the process that really runs is
# Python.app from the Python installation, which belongs to the Python Software Foundation, is
# locked down with the hardened runtime and has no microphone permission. macOS then refuses the
# microphone silently: no prompt, and the app never appears under Privacy > Microphone (live
# transcription fails). A copy signed as MLX-Audio runs under this app's own identity and its
# NSMicrophoneUsageDescription, so macOS asks. If anything below does not work out, the app falls
# back to the old way (run the Python directly): everything works except the microphone.
PY_EXEC="$VENV_PYTHON"
if BASE_BIN="$("$VENV_PYTHON" -c 'import sys,os;print(os.path.join(sys.base_prefix,"Resources","Python.app","Contents","MacOS","Python"))' 2>/dev/null)" \
   && [ -x "$BASE_BIN" ]; then
  if cp "$BASE_BIN" "$APP/Contents/MacOS/MLX-Audio-python"; then
    PY_EXEC="$APP/Contents/MacOS/MLX-Audio-python"
    # In a virtual environment, tell the copy about it: a pyvenv.cfg next to the executable's
    # folder makes Python use <Contents>/lib/pythonX.Y/site-packages, which links to the real one.
    VENV_INFO="$("$VENV_PYTHON" -c 'import sys,site;print(sys.prefix!=sys.base_prefix);print(site.getsitepackages()[0]);print("%d.%d"%sys.version_info[:2]);print(sys.base_prefix+"/bin")' 2>/dev/null)" || VENV_INFO=""
    if [ "$(echo "$VENV_INFO" | sed -n 1p)" = "True" ]; then
      SITE_PKGS="$(echo "$VENV_INFO" | sed -n 2p)"
      PYVER="$(echo "$VENV_INFO" | sed -n 3p)"
      BASE_BIN_DIR="$(echo "$VENV_INFO" | sed -n 4p)"
      mkdir -p "$APP/Contents/lib/python$PYVER"
      ln -s "$SITE_PKGS" "$APP/Contents/lib/python$PYVER/site-packages"
      printf 'home = %s\ninclude-system-site-packages = false\nversion = %s\n' "$BASE_BIN_DIR" "$PYVER" > "$APP/Contents/pyvenv.cfg"
    fi
  else
    rm -f "$APP/Contents/MacOS/MLX-Audio-python"
  fi
else
  echo "Note: could not find Python's own executable; the microphone will not work in the app." >&2
fi

# %q shell-quotes each value, so paths with spaces, quotes or & are safe.
{
  echo '#!/bin/sh'
  printf 'exec %q -m mlx_audio.app_window --port %q --log-dir %q --log-file %q\n' \
    "$PY_EXEC" "$PORT" "$SERVER_LOG_DIR" "$LOG_FILE"
} > "$APP/Contents/MacOS/MLX-Audio"
chmod +x "$APP/Contents/MacOS/MLX-Audio"

# Ad-hoc signature (free, no developer account): keeps macOS from treating the bundle as damaged.
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || echo "Note: could not sign the app; it may still work." >&2
touch "$APP"

echo "Installed 'MLX-Audio' to $TARGET_DIR"
