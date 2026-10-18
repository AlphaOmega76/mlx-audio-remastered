#!/bin/zsh
# Builds the zip you upload to the Chrome Web Store: the extension with the dev-only "key" removed
# (the store refuses it; the ID is kept instead by pasting the same public key into the dashboard,
# Package tab -> "Add public key"). Output defaults to ~/Desktop; set OUT_ZIP to put it elsewhere.
set -e
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_ZIP="${OUT_ZIP:-$HOME/Desktop/MLX-Audio-Reader-store.zip}"
STAGE="$(mktemp -d)"

rsync -a --exclude README.md "$REPO_ROOT/browser-extension/" "$STAGE/"
python3 - "$STAGE/manifest.json" <<'PY'
import json, sys
p = sys.argv[1]
m = json.load(open(p))
m.pop("key", None)
assert "file:///*" not in m.get("host_permissions", []), "file access must not ship in the store build"
json.dump(m, open(p, "w"), indent=2)
PY

rm -f "$OUT_ZIP"
(cd "$STAGE" && zip -r -q "$OUT_ZIP" . -x '.DS_Store')
rm -rf "$STAGE"
echo "Done: $OUT_ZIP"
echo "Public key to paste in the dashboard (Package tab):"
python3 -c "import json;print(json.load(open('$REPO_ROOT/browser-extension/manifest.json'))['key'])"
