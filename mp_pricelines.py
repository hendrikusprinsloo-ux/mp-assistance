#!/usr/bin/env python3
"""Open one results row's Priceline link in the tool's Chrome and read the rate on the page. Read-only: nothing is saved or clicked
except what is needed to reach the price.

Usage:
  python mp_pricelines.py results.csv [--row N] [--save-page FOLDER] [--chrome http://127.0.0.1:9222]

Reads the n-th Priceline row of the file (default: the first), follows its Lighthouse `url` link, forces the row's currency with
`?cur=XXX` as the Ops Core Mobile Parity Process page describes, waits for the room prices, and prints one `RESULT {json}` line:
the lowest public price text found, the number read from it, whether the page said sold out, and the page's address.

This is a first, single-site piece of the scraper rebuild. It uses the price location found in the earlier scraper (the price text under
the "Room Options" heading). Whether Priceline serves the page to an automated Chrome is exactly what running it will show.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import mp_rates
import mp_upload as m

# the room prices on a Priceline hotel page: text holding a price, below "Room Options", not a total, an offer or a "people also liked" tile
PRICE_XPATH = ("//*[({hint}) and not(contains(., 'Total')) and not(contains(., 'Off')) and string-length(normalize-space(.)) <= 25 "
               "and preceding::*[normalize-space(text())='Room Options'] "
               "and not(preceding::*[normalize-space(text())='People also liked'])]")
MEMBER_RE = re.compile(r"member|rewards|vip|genius|sign in|log in|exclusive", re.I)
WAITS = (8, 8, 8)           # seconds to wait for the prices, up to three times


def with_currency(url, currency):
    """Priceline takes the displayed currency from `cur=` in the URL."""
    if not currency:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query["cur"] = currency.upper()
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def price_xpath(currency_symbols="$"):
    hint = " or ".join(f"contains(., '{s}')" for s in currency_symbols)
    return PRICE_XPATH.format(hint=hint)


def pick_lowest(texts):
    """(rate, text) of the lowest public price among rate-card texts; member-only wording is left out."""
    best = None
    for text in texts:
        if not text or MEMBER_RE.search(text) or not mp_rates.looks_like_price(text):
            continue
        rate = mp_rates.parse_rate(text)
        if rate is not None and (best is None or rate < best[0]):
            best = (rate, text.strip())
    return best


def read_row(row, ctx, save_to=None):
    """Read one row's page. Prices are looked for first; a page only counts as sold out when the waits are used up with no price on it
    and its text says so (a phrase like "sold out" can sit elsewhere on a page that has rooms). Everything seen is returned."""
    url = with_currency(row["url"], row.get("currency", ""))
    page = ctx.new_page()
    out = {"hotel": row.get("hotel_name", ""), "currency": row.get("currency", ""), "from_date": row.get("from_date", ""), "url": url}
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        out["landed_on"] = page.url
        symbols = "$€£¥₹" if not row.get("currency") else "$€£¥₹﷼" + row["currency"]
        found, body = [], ""
        for attempt, wait in enumerate(WAITS, 1):
            page.wait_for_timeout(wait * 1000)
            body = page.evaluate("document.body ? document.body.innerText : ''")
            found = [t for t in page.locator("xpath=" + price_xpath(symbols)).all_inner_texts() if t and t.strip()]   # icons and other non-text elements give None
            out["attempts"] = attempt
            if pick_lowest(found):
                break
        match = mp_rates.SOLD_OUT_RE.search(body)
        out["sold_out_wording"] = match.group(0) if match else ""
        out["texts_seen"] = found[:12]
        best = pick_lowest(found)
        out["rate"], out["rate_text"] = (best if best else (None, ""))
        out["status"] = "ok" if best else ("sold_out" if match else "selector_not_found")
        out["page_text_chars"] = len(body)
        if save_to:
            folder = Path(save_to)
            folder.mkdir(parents=True, exist_ok=True)
            stem = re.sub(r"[^a-z0-9]+", "-", out["hotel"].lower()).strip("-")[:50] or "page"
            (folder / f"{stem}.txt").write_text(body, encoding="utf-8")
            try:
                page.screenshot(path=str(folder / f"{stem}.png"), full_page=True)
            except Exception:
                pass
            out["saved_to"] = str(folder / f"{stem}.txt")
    finally:
        page.close()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--row", type=int, default=1, help="which Priceline row of the file to read (1 = the first)")
    ap.add_argument("--chrome", default="http://127.0.0.1:9222")
    ap.add_argument("--save-page", metavar="FOLDER", help="also save the page's text and a screenshot in FOLDER, to see what the page held")
    args = ap.parse_args()
    rows = [r for _, r in m.load_rows(args.csv) if r.get("OTA_name", "").strip().lower() == "priceline"]
    if not 1 <= args.row <= len(rows):
        sys.exit(f"ERROR The file has {len(rows)} Priceline rows; --row must be 1 to {len(rows)}")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.connect_over_cdp(args.chrome).contexts[0]
        except Exception as e:
            sys.exit(f"ERROR Could not reach the tool's Chrome at {args.chrome}: {str(e).splitlines()[0][:120]}")
        print("RESULT " + json.dumps(read_row(rows[args.row - 1], ctx, args.save_page), ensure_ascii=False))


if __name__ == "__main__":
    main()
