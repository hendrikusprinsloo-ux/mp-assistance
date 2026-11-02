#!/bin/bash
# Double-click to start the MP Assistance UI.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "First-time setup..."
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt || exit 1   # no browser download: it drives your own Chrome
fi
# a package added in a newer version (for example segno, for the QR codes) is installed on the next start
.venv/bin/python -c "import segno" 2>/dev/null || .venv/bin/pip install -q -r requirements.txt || echo "Could not install the packages: the QR codes need the internet once."
exec .venv/bin/python server.py --with-chrome
