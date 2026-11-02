#!/usr/bin/env python3
"""Put the tool's window on the left half of a screen area and the Parity Manager windows on the right half.

Usage:
  python mp_arrange.py LEFT TOP WIDTH HEIGHT [--chrome http://127.0.0.1:9222]

The area is the available screen area as the tool's own window reports it (screen.availLeft/availTop/availWidth/availHeight).
"""
import argparse

UI_PREFIX = "http://127.0.0.1:8765"
PM_PREFIX = "https://paritymanager.mylighthouse.com"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("left", "top", "width", "height"):
        ap.add_argument(name, type=int)
    ap.add_argument("--chrome", default="http://127.0.0.1:9222")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    half = args.width // 2
    left = {"left": args.left, "top": args.top, "width": half, "height": args.height, "windowState": "normal"}
    right = {"left": args.left + half, "top": args.top, "width": args.width - half, "height": args.height,
             "windowState": "normal"}

    moved = 0
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.chrome)
        session = browser.new_browser_cdp_session()
        done = set()
        for target in session.send("Target.getTargets")["targetInfos"]:
            if target.get("type") != "page":
                continue
            url = target.get("url", "")
            bounds = left if url.startswith(UI_PREFIX) else right if url.startswith(PM_PREFIX) else None
            if bounds is None:
                continue
            window_id = session.send("Browser.getWindowForTarget", {"targetId": target["targetId"]})["windowId"]
            if window_id in done:  # several tabs of one window
                continue
            done.add(window_id)
            session.send("Browser.setWindowBounds", {"windowId": window_id, "bounds": bounds})
            moved += 1
    print(f"RESULT moved {moved} windows")


if __name__ == "__main__":
    main()
