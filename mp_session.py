#!/usr/bin/env python3
"""Say whether the tool's Chrome is signed in to Parity Manager.

Usage:
  python mp_session.py [--chrome http://127.0.0.1:9222]

Asks Parity Manager for its home page with the Chrome session's cookies (no tab or window is opened).
Prints one `RESULT {"signed_in": true|false}` line.
"""
import argparse
import json
import sys

HOME_URL = "https://paritymanager.mylighthouse.com/admin/"


def is_signed_in(html):
    """A signed-in admin page carries a logout form; the login page does not."""
    return "/admin/logout/" in html


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chrome", default="http://127.0.0.1:9222")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.connect_over_cdp(args.chrome).contexts[0]
            html = ctx.request.get(HOME_URL).text()
        except Exception as e:
            sys.exit(f"ERROR Could not check the sign-in: {str(e).splitlines()[0][:120]}")
    print("RESULT " + json.dumps({"signed_in": is_signed_in(html)}))


if __name__ == "__main__":
    main()
