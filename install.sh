#!/usr/bin/env bash
# Installs the Les Paul top carve macro into FreeCAD's user macro folder.
# Usage: ./install.sh [/path/to/FreeCAD.app]   (default: /Applications/FreeCAD.app)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="${1:-/Applications/FreeCAD.app}"
CMD="$APP/Contents/Resources/bin/freecadcmd"

if [[ ! -x "$CMD" ]]; then
  echo "error: FreeCAD command-line tool not found at: $CMD" >&2
  echo "pass the path to your FreeCAD.app as the first argument" >&2
  exit 1
fi

# Ask FreeCAD itself where its macro folder is (paths differ between versions).
TMP_OUT="$(mktemp)"
trap 'rm -f "$TMP_OUT"' EXIT
"$CMD" -c "import FreeCAD as App; open('$TMP_OUT','w').write(App.getUserMacroDir(True))" >/dev/null 2>&1 || true
MACRO_DIR="$(cat "$TMP_OUT" 2>/dev/null || true)"

if [[ -z "$MACRO_DIR" ]]; then
  echo "error: could not determine FreeCAD's macro folder" >&2
  exit 1
fi

LIB_DIR="$MACRO_DIR/LesPaulCarve_lib"
mkdir -p "$MACRO_DIR" "$LIB_DIR"
# Remove the library from the top-level macro folder (older installs put it there,
# where the Macros dialog lists it and running it does nothing).
rm -f "$MACRO_DIR/les_paul_carve.py"
cp "$HERE/les_paul_carve.py" "$LIB_DIR/"
cp "$HERE/LesPaulCarveTop.FCMacro" "$MACRO_DIR/"

echo "Installed to: $MACRO_DIR"
echo "  - LesPaulCarveTop.FCMacro   <- run THIS one from Macro > Macros..."
echo "  - LesPaulCarve_lib/les_paul_carve.py   (library; do not run directly)"
echo "Restart FreeCAD to be safe, then see Macro > Macros."
