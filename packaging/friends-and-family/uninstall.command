#!/bin/zsh
# Double-click to remove MLX-Audio: stops the server if it's running, and deletes the
# app icons, its private Python environment, and its files. Does not touch anything
# else on this Mac (in particular, no other Python installation is affected).
set -e

APP_NAME="MLX-Audio"
APP_SUPPORT="${MLXA_APP_SUPPORT:-$HOME/Library/Application Support/$APP_NAME}"
APPS_DIR="${MLXA_APPS_DIR:-/Applications}"
PORT="${MLXA_PORT:-8000}"
LOG_FILE="${MLXA_LOG_FILE:-$HOME/Library/Logs/MLX-Audio.log}"
BROWSERS_ROOT="${MLXA_BROWSERS_ROOT:-$HOME/Library/Application Support}"

echo "This will remove MLX-Audio (the app, its Python environment, and its files)."
printf "Continue? [y/N] "
read -r REPLY
case "$REPLY" in
  y|Y|yes|YES) ;;
  *) echo "Cancelled."; exit 0 ;;
esac

echo "Closing MLX-Audio and stopping the server, if they're running…"
# the app window (it stops its own server too, but don't rely on that here)
pkill -f "mlx_audio.app_window" 2>/dev/null || true
# older versions ran the server as a launchd job (which restarts it if killed), so remove the job first
launchctl remove "com.mlxaudio.server.$PORT" >/dev/null 2>&1 || true
# listeners only: plain `lsof -ti:PORT` also returns processes merely connected to the port
# (e.g. a browser tab), and this must not kill those
kill $(lsof -ti tcp:"$PORT" -sTCP:LISTEN) 2>/dev/null || true

echo "Removing app icons…"
rm -rf "$APPS_DIR/MLX-Audio.app" "$APPS_DIR/Stop MLX-Audio.app"
rm -rf "$HOME/Applications/MLX-Audio.app" "$HOME/Applications/Stop MLX-Audio.app"

echo "Removing the Chrome extension helper…"
# (done by hand, not through Python, so it works even if the environment is already broken)
pkill -f "mlx_audio.native_host" 2>/dev/null || true
for d in "Google/Chrome" "Chromium" "BraveSoftware/Brave-Browser" "Microsoft Edge" "Arc/User Data"; do
  rm -f "$BROWSERS_ROOT/$d/NativeMessagingHosts/com.mlxaudio.host.json"
done

echo "Removing files…"
rm -rf "$APP_SUPPORT"
rm -f "$LOG_FILE"

echo "Done. MLX-Audio has been removed."
echo "(Voice models it downloaded are kept in ~/.cache/huggingface and may take several GB;"
echo " they are shared with other tools, so they were left alone. Delete that folder to reclaim the space.)"
echo "(You can delete this file too — it has done its job.)"
