#!/bin/bash
# Builds a zip of the app to share, leaving out anything private or specific to this Mac.
#   ./package.sh [output.zip]      (default: MP-Assistance-v<version>.zip next to the app folder, version from VERSION)
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="$(basename "$HERE")"
VERSION="$(head -n 1 "$HERE/VERSION" 2>/dev/null | tr -d '[:space:]')"
OUT="${1:-$(dirname "$HERE")/MP-Assistance-v${VERSION:-0}.zip}"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac
rm -f "$OUT"
cd "$(dirname "$HERE")" || exit 1
zip -rq "$OUT" "$NAME" \
  -x "$NAME/.git/*" "$NAME/.gitignore" "$NAME/docs/archive/*" "$NAME/.venv/*" "$NAME/.browser-profile/*" "$NAME/.claude/*" "$NAME/settings.json" "$NAME/issues_ledger.csv" \
     "$NAME/qa_from_dashboard/*" \
     "$NAME/server.log" "$NAME/package.sh" "*/__pycache__/*" "*.DS_Store" \
  && echo "Created $OUT (version ${VERSION:-unknown})" \
  && cp "$OUT" "$(dirname "$OUT")/MP-Assistance.zip" \
  && (cd "$(dirname "$OUT")" && shasum -a 256 "$(basename "$OUT")" | cut -d' ' -f1 > "$(basename "$OUT").sha256") \
  && echo "Also wrote MP-Assistance.zip (same file, fixed name for the install line) and $(basename "$OUT").sha256 (attach all three to the GitHub release)"
