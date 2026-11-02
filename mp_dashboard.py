#!/usr/bin/env python3
"""Read a day's Mobile Parity Issues list from Parity Manager: how many issues are confirmed, and which.

Usage:
  python mp_dashboard.py URL [--chrome http://127.0.0.1:9222]

URL is the dashboard address for one chain and day. It is fetched with the tool's Chrome session (no tab or window opens).
Prints one `RESULT {json}` line: {"signed_in", "count", "issues": [{"subscription_id", "channel", "issue_id", "extract_date", "difference"}]}.
"""
import argparse
import json
import re
import sys

COUNT_RE = re.compile(r"(\d[\d,]*)\s+results?\b")
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
ISSUE_RE = re.compile(r"/adminpromotionparityissue/(\d+)/change/")
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def list_date(text):
    """The list shows dates like 'Oct. 29, 2026' or 'Sept. 4, 2026'; return YYYY-MM-DD, or the text unchanged."""
    match = re.match(r"^([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{1,2}),\s+(\d{4})$", (text or "").strip())
    if not match or match.group(1).lower() not in MONTHS:
        return text or ""
    return f"{int(match.group(3)):04d}-{MONTHS[match.group(1).lower()]:02d}-{int(match.group(2)):02d}"


def cell(row, label):
    match = re.search(r'data-label="%s"[^>]*>(.*?)</(?:th|td)>' % re.escape(label), row, re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", match.group(1)).split()) if match else None


def parse_dashboard(html):
    """{"signed_in", "count" (the page's own results total), "issues"} from a Mobile Parity Issues list page."""
    signed_in = "/admin/logout/" in html
    count = COUNT_RE.search(re.sub(r"<[^>]+>", " ", html))
    issues = []
    for row in ROW_RE.findall(html):
        if 'data-label="subscription id"' not in row:
            continue
        link = ISSUE_RE.search(row)
        issues.append({"subscription_id": cell(row, "subscription id"), "channel": cell(row, "channel id"),
                       "issue_id": link.group(1) if link else "", "extract_date": list_date(cell(row, "extract date")),
                       "difference": cell(row, "Difference with Base Rate") or ""})
    return {"signed_in": signed_in, "count": int(count.group(1).replace(",", "")) if count else None, "issues": issues}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--chrome", default="http://127.0.0.1:9222")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.connect_over_cdp(args.chrome).contexts[0]
            data = parse_dashboard(ctx.request.get(args.url).text())
            if data["signed_in"] and data["count"] is not None and len(data["issues"]) < data["count"]:
                # a long list is split across pages: ask for all of it
                data = parse_dashboard(ctx.request.get(args.url + "&all=").text())
        except Exception as e:
            sys.exit(f"ERROR Could not read the dashboard: {str(e).splitlines()[0][:120]}")
    if not data["signed_in"]:
        sys.exit("ERROR Not signed in to Parity Manager in the tool's Chrome")
    print("RESULT " + json.dumps(data))


if __name__ == "__main__":
    main()
