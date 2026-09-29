#!/bin/zsh
# Double-click to remove MLX-Audio: stops the server if it's running, and deletes the
# app icons, its private Python environment, and its files. Does not touch anything
# else on this Mac (in particular, no other Python installation is affected).
set -e

APP_NAME="MLX-Audio"
APP_SUPPORT="${MLXA_APP_SUPPORT:-$HOME/Library/Application Support/$APP_NAME}"
APPS_DIR="${MLXA_APPS_DIR:-/Applications}"
PORT="${MLXA_PORT:-8000}"

echo "This will remove MLX-Audio (the app, its Python environment, and its files)."
printf "Continue? [y/N] "
read -r REPLY
case "$REPLY" in
  y|Y|yes|YES) ;;
  *) echo "Cancelled."; exit 0 ;;
esac

echo "Stopping the server, if it's running…"
kill $(lsof -ti:"$PORT") 2>/dev/null || true

echo "Removing app icons…"
rm -rf "$APPS_DIR/MLX-Audio.app" "$APPS_DIR/Stop MLX-Audio.app"
rm -rf "$HOME/Applications/MLX-Audio.app" "$HOME/Applications/Stop MLX-Audio.app"

echo "Removing files…"
rm -rf "$APP_SUPPORT"
rm -f "$HOME/Library/Logs/MLX-Audio.log"

echo "Done. MLX-Audio has been removed."
echo "(You can delete this file too — it has done its job.)"
