#!/bin/zsh
# Double-click this to install MLX-Audio. Safe to run again later (e.g. to update):
# it reinstalls into the same place rather than creating a second copy.
#
# Everything it touches:
#   ~/Library/Application Support/MLX-Audio/   (the app's own private copy of the code + a
#                                                private Python environment, unrelated to any
#                                                other Python on this Mac)
#   ~/Library/Application Support/MLX-Audio/logs (the server's own small log folder)
#   ~/.cache/huggingface/                       (the Kokoro voice model, about 340 MB, shared with
#                                                other tools; downloaded here so the first speech
#                                                isn't slow, and left alone by the uninstaller)
#   ~/Library/Logs/MLX-Audio.log                (server output, useful if something goes wrong)
#   /Applications/MLX-Audio.app                 (double-click to open MLX-Audio in its own window;
#                                                closing the window quits it and stops the server.
#                                                Falls back to ~/Applications if /Applications
#                                                isn't writable, as on non-admin Mac accounts)
#   ~/Library/Application Support/MLX-Audio/native-host.sh, plus a small registration file in
#     each installed Chrome/Brave/Edge/Arc/Chromium profile folder (NativeMessagingHosts/):
#                                               lets the Chrome extension start and stop the
#                                               server on its own
#   ~/Desktop/Uninstall MLX-Audio.command        (removes everything above)
#
# Advanced/testing: set MLXA_APP_SUPPORT, MLXA_APPS_DIR, MLXA_PORT, MLXA_DESKTOP,
# MLXA_LOG_FILE or MLXA_BROWSERS_ROOT to override the locations above (used to test this script without touching
# a real install). The fallback to ~/Applications only happens when MLXA_APPS_DIR is unset;
# if an override is set but not writable, the script stops instead.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="MLX-Audio"
APP_SUPPORT="${MLXA_APP_SUPPORT:-$HOME/Library/Application Support/$APP_NAME}"
APPS_DIR="${MLXA_APPS_DIR:-/Applications}"
PORT="${MLXA_PORT:-8000}"
DESKTOP="${MLXA_DESKTOP:-$HOME/Desktop}"
VENV="$APP_SUPPORT/venv"
APP_SRC="$APP_SUPPORT/app"

say() { echo "\n== $1 =="; }

say "Installing $APP_NAME"

# Standard (non-admin) Mac accounts can't write to /Applications. Find that out now, not
# after the multi-minute download.
mkdir -p "$APPS_DIR" 2>/dev/null || true
if [ ! -w "$APPS_DIR" ]; then
  if [ -n "${MLXA_APPS_DIR:-}" ]; then
    # An explicit override (used for testing) must never quietly turn into a write to the
    # real ~/Applications.
    echo "MLXA_APPS_DIR=$MLXA_APPS_DIR isn't writable; stopping instead of falling back to ~/Applications." >&2
    exit 1
  fi
  echo "Note: $APPS_DIR isn't writable for this account, so the app icons will go in ~/Applications instead."
  APPS_DIR="$HOME/Applications"
  mkdir -p "$APPS_DIR"
fi

if [ "$(uname -m)" != "arm64" ]; then
  echo "Sorry — MLX-Audio needs an Apple Silicon Mac (M1 or later). This Mac reports: $(uname -m)."
  exit 1
fi

# ---- find a usable Python (3.10+) -------------------------------------------------
find_python() {
  local candidates=("/opt/homebrew/bin/python3" "/usr/local/bin/python3")
  local v
  for v in 3.14 3.13 3.12 3.11 3.10; do
    candidates+=("/Library/Frameworks/Python.framework/Versions/$v/bin/python3")
  done
  candidates+=("python3")
  local c ver major minor
  for c in "${candidates[@]}"; do
    command -v "$c" >/dev/null 2>&1 || continue
    ver="$("$c" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" || continue
    major="${ver%%.*}"; minor="${ver##*.}"
    if [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

say "Checking for Python"
PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
  echo "MLX-Audio needs Python 3.10 or newer, which wasn't found on this Mac."
  echo "Opening the official download page — after installing it, run this installer again."
  open "https://www.python.org/downloads/macos/"
  exit 1
fi
echo "Using $PYTHON ($("$PYTHON" -c 'import platform; print(platform.python_version())'))"

# ---- stage a private copy of the source -------------------------------------------
say "Copying files"
mkdir -p "$APP_SUPPORT"
rm -rf "$APP_SRC"
cp -R "$SCRIPT_DIR/source" "$APP_SRC"

# ---- create (or reuse) a private virtual environment ------------------------------
if [ ! -x "$VENV/bin/python3" ]; then
  say "Setting up a private Python environment"
  echo "(This is separate from any other Python on your Mac — it won't affect anything else.)"
  "$PYTHON" -m venv "$VENV"
fi

# ---- install ------------------------------------------------------------------------
say "Installing MLX-Audio"
echo "This downloads its dependencies (a few hundred MB the first time) and can take"
echo "several minutes. Please be patient — it hasn't frozen."
"$VENV/bin/python3" -m pip install --upgrade pip wheel --quiet || echo "(Couldn't update pip itself; continuing with the version already there.)"
# NOTE: must be "${APP_SRC}[all,server]" not "$APP_SRC[all,server]" -- in zsh the
# latter is parsed as a subscript/slice on $APP_SRC (evaluating to an empty string)
# rather than literal text, which made this silently install nothing.
# "desktop" adds pywebview (the native window); "kokoro" adds the text processing the default
# Kokoro voice needs. Without it, generating speech fails with "Load failed" on a fresh install.
if ! "$VENV/bin/python3" -m pip install "${APP_SRC}[all,server,desktop,kokoro]"; then
  echo ""
  echo "Installation failed. The most common cause on a fresh Mac is missing Apple"
  echo "developer command-line tools. Try running this in Terminal:"
  echo ""
  echo "    xcode-select --install"
  echo ""
  echo "...then run this installer again."
  exit 1
fi

# ---- the English language model Kokoro's text processing uses ---------------------------------
# (It would download itself on the first speech request; doing it now surfaces problems early
# and makes the first request fast.)
say "Downloading the English language model"
if ! "$VENV/bin/python3" -m spacy download en_core_web_sm; then
  echo "(Couldn't download it now. The first time you generate speech it will try again, which needs internet.)"
fi

# ---- the Kokoro voice model itself (about 340 MB) --------------------------------------------
# The app window is a browser, and browsers give up on a request that stays silent for about a
# minute. Downloading the model on the first speech request took 76 s on a fast connection and
# would take minutes on a slow one, ending in "Load failed". So it is fetched here, once.
say "Downloading the Kokoro voice (about 340 MB)"
echo "(Done now so your first speech isn't slow. It only downloads once and is kept for next time.)"
if ! "$VENV/bin/python3" -c 'from huggingface_hub import snapshot_download; snapshot_download("mlx-community/Kokoro-82M-bf16")'; then
  echo "(Couldn't download it now. The first time you generate speech it will try again, which"
  echo " needs internet and can take a few minutes, so that first attempt may show an error; try again.)"
fi

# ---- launcher apps -------------------------------------------------------------------
say "Creating the app"
"$SCRIPT_DIR/make_app.sh" "$VENV/bin/python3" "$PORT" "$APPS_DIR" "$APP_SUPPORT/logs"

# ---- let the Chrome extension start and stop the server -----------------------------------
say "Setting up the Chrome extension helper"
helper_args=()
[ -n "${MLXA_BROWSERS_ROOT:-}" ] && helper_args=(--browsers-root "$MLXA_BROWSERS_ROOT")
if ! "$VENV/bin/python3" -m mlx_audio.native_host --register --python "$VENV/bin/python3" \
    --support-dir "$APP_SUPPORT" "${helper_args[@]}"; then
  echo "(Couldn't set that up. The MLX-Audio app still works; the Chrome extension will need the app open.)"
fi

# ---- a durable uninstaller, independent of where this download ends up ----------------
mkdir -p "$DESKTOP"
cp "$SCRIPT_DIR/uninstall.command" "$DESKTOP/Uninstall MLX-Audio.command"
chmod +x "$DESKTOP/Uninstall MLX-Audio.command"

say "Done"
echo "Open your Applications folder and double-click 'MLX-Audio' to start."
echo "Closing its window (or pressing Cmd+Q) quits it and frees up the memory."
echo "To remove everything later, use 'Uninstall MLX-Audio' on your Desktop."
