#!/bin/zsh
# Run this yourself (not something to send to friends) to produce the zip you actually
# share. It builds the web UI, stages a clean copy of the source (no .git, no
# node_modules, no dev-only files), bundles the installer, and zips it to your Desktop.
set -e

PACKAGING_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$PACKAGING_DIR/../.." && pwd)"
PY="${PYTHON:-/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14}"

VERSION="$("$PY" -c 'import sys; sys.path.insert(0, "'"$REPO_ROOT"'"); import mlx_audio.version as v; print(v.__version__)' 2>/dev/null || true)"
if [ -z "$VERSION" ]; then
  echo "Warning: could not read the version using '$PY' (set PYTHON=/path/to/python3 to fix); naming the zip '-dev'." >&2
  VERSION=dev
fi
STAGE="$(mktemp -d)"
BUNDLE="MLX-Audio-Installer"
OUT_ZIP="$HOME/Desktop/MLX-Audio-Installer-$VERSION.zip"

echo "== Building the web UI =="
(cd "$REPO_ROOT/mlx_audio/ui" && npm run build)

echo "== Staging a clean copy of the source =="
mkdir -p "$STAGE/$BUNDLE/source"
rsync -a \
  --exclude ".git" \
  --exclude ".github" \
  --exclude "browser-extension" \
  --exclude "docs" \
  --exclude "CLAUDE.md" \
  --exclude ".scratch" \
  --exclude "packaging" \
  --exclude "tests" \
  --exclude "*.egg-info" \
  --exclude "build" \
  --exclude "dist" \
  --exclude "__pycache__" \
  --exclude "mlx_audio/ui/node_modules" \
  --exclude "mlx_audio/ui/.next" \
  "$REPO_ROOT/" "$STAGE/$BUNDLE/source/"

echo "== Adding the installer =="
cp "$PACKAGING_DIR/install.command" "$STAGE/$BUNDLE/"
cp "$PACKAGING_DIR/uninstall.command" "$STAGE/$BUNDLE/"
cp "$PACKAGING_DIR/make_launchers.sh" "$STAGE/$BUNDLE/"
cp "$PACKAGING_DIR/READ ME FIRST.txt" "$STAGE/$BUNDLE/"
chmod +x "$STAGE/$BUNDLE/install.command" "$STAGE/$BUNDLE/uninstall.command" "$STAGE/$BUNDLE/make_launchers.sh"

echo "== Zipping =="
rm -f "$OUT_ZIP"
(cd "$STAGE" && zip -r -q "$OUT_ZIP" "$BUNDLE")
rm -rf "$STAGE"

echo ""
echo "Done: $OUT_ZIP"
echo "Send this zip to your friends (AirDrop, Dropbox, email, etc)."
echo "They should unzip it and follow 'READ ME FIRST.txt'."
