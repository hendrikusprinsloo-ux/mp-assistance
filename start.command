#!/bin/bash
# Double-click to start the MP Assistance UI.
# Everything is inside one function that is called on the last line: bash reads the whole file before running any of it, so an update
# that replaces this very file while it runs cannot break it.
main() {
  cd "$(dirname "$0")"
  if [ ! -x .venv/bin/python ]; then
    echo "First-time setup..."
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt || exit 1   # no browser download: it drives your own Chrome
  fi
  # a package added in a newer version (for example segno, for the QR codes) is installed on the next start
  .venv/bin/python -c "import segno" 2>/dev/null || .venv/bin/pip install -q -r requirements.txt || echo "Could not install the packages: the QR codes need the internet once."
  # look for a newer version on GitHub and install it before the app starts (a few seconds; skipped quietly with no internet)
  .venv/bin/python mp_update.py || true
  exec .venv/bin/python server.py --with-chrome
}
main "$@"; exit $?
