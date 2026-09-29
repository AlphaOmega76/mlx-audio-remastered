#!/bin/zsh
# Run this yourself (not something to send to friends) to zip up the Chrome extension for
# manual installation ("Load unpacked" — see "EXTENSION - READ ME FIRST.txt" in this folder).
set -e

PACKAGING_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$PACKAGING_DIR/../.." && pwd)"
OUT_ZIP="$HOME/Desktop/MLX-Audio-Reader-Extension.zip"
STAGE="$(mktemp -d)"

mkdir -p "$STAGE/MLX-Audio-Reader"
rsync -a "$REPO_ROOT/browser-extension/" "$STAGE/MLX-Audio-Reader/browser-extension/"
cp "$PACKAGING_DIR/EXTENSION - READ ME FIRST.txt" "$STAGE/MLX-Audio-Reader/"

rm -f "$OUT_ZIP"
(cd "$STAGE" && zip -r -q "$OUT_ZIP" "MLX-Audio-Reader")
rm -rf "$STAGE"

echo "Done: $OUT_ZIP"
echo "Send this zip to your friends alongside the app installer."
echo "They should unzip it and follow 'EXTENSION - READ ME FIRST.txt'."
