#!/usr/bin/env python3
"""Reading a rate from the text on a page, and deciding whether it is a parity issue.

Written from the Ops Core Mobile Parity Process page and checked against a real results file (run_2026-11-02_10-52-48, 240 rows):
only a channel rate MORE than MIN_DIFF below the brand.com rate is an issue. The labels match the results file.

  python mp_rates.py results.csv     re-reads every row and lists where this module and the file disagree
"""
import csv
import re
import sys

MIN_DIFF = 2          # in the currency shown on both pages: "more than $2 lower"
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# Currencies a price on a page can be shown in. The earlier scraper's list stopped at USD EUR GBP CAD INR AUD CHF JPY MXN ZAR, which leaves out
# riyals (SAR), ringgit, yuan, pesos and krone. Its brand.com reader still managed "﷼269", so this may not be why the Riyadh hotel in the
# 2 Nov Choice run found no channel price (not confirmed). Any three-letter code on the page is accepted, plus these symbols.
CURRENCY_SYMBOLS = "$€£¥₹₩₱₫₺₽₴₪₦﷼฿₡₲₵₭₮₸₼"
CURRENCY_RE = re.compile(r"[%s]|\b[A-Z]{2,3}\s?\$|\b[A-Z]{3}\b|\bRs\.?|\bRM\b|\bkr\.?\b" % re.escape(CURRENCY_SYMBOLS))

# A page that says there is nothing to book. Checked before waiting for a price: waiting 8 seconds three times on a sold-out page is wasted.
SOLD_OUT_RE = re.compile(
    r"sold out|no (?:rooms?|availability)|not available for (?:your|these) (?:dates|trip)|unavailable for (?:your|these) dates|"
    r"no longer available|fully booked|we have no rooms available|no properties? (?:found|available)", re.I)


def numbers(text):
    """Every number in a rate text, thousands commas removed ('Rs. 2,800' -> [2800.0])."""
    return [float(n) for n in NUMBER_RE.findall((text or "").replace(",", ""))]


def looks_like_price(text):
    """True for text that holds a number and a currency (symbol or code), e.g. '﷼269', 'SAR 269', 'RM 120', 'US$123'."""
    return bool(text) and bool(NUMBER_RE.search(text.replace(",", ""))) and bool(CURRENCY_RE.search(text))


def sold_out(page_text):
    """True when the page's own text says the room cannot be booked for these dates."""
    return bool(SOLD_OUT_RE.search(page_text or ""))


def parse_rate(text):
    """The rate in an OTA text such as '$161 nightly' or 'Per night $ 160 $ 160'. When a text lists several prices the lowest wins."""
    found = numbers(text)
    return min(found) if found else None


def parse_brand_rate(text):
    """The rate in a brand.com text. Brand pages print the cents as a separate small number: '$157 34' is 157.34, '96 90' is 96.90."""
    found = re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")
    if len(found) == 2 and re.fullmatch(r"\d{2}", found[1]) and "." not in found[0]:
        return float(found[0].replace(",", "")) + int(found[1]) / 100
    return parse_rate(text)


def compare(ota_rate, brand_rate, min_diff=MIN_DIFF):
    """(rate_diff, rate_diff_pct, label) with the results file's labels. rate_diff is channel minus brand, so cheaper is negative."""
    if brand_rate is None:
        return None, None, "brand_rate_missing"
    if ota_rate is None:
        return None, None, "ota_rate_missing"
    diff = round(ota_rate - brand_rate, 2)
    pct = round(diff / brand_rate * 100, 4) if brand_rate else None
    if diff < 0:
        return diff, pct, "lower_than_brand" if -diff > min_diff else "lower_than_brand_negligible"
    return diff, pct, "not_lower_than_brand"


def audit(path):
    """Compare this module with a results file: {'rows', 'same', 'changed': [(hotel, channel, old label, new label, old diff, new diff)]}."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    rows = list(csv.DictReader(lines[1:] if lines and lines[0].startswith("sep=") else lines))
    out = {"rows": 0, "same": 0, "changed": []}
    for r in rows:
        if r.get("status") != "ok" or not r.get("raw_rate_text"):
            continue
        out["rows"] += 1
        brand = parse_brand_rate(r.get("branddotcom_raw_rate_text", ""))
        if brand is None and r.get("brand_rate_source") == "csv":      # no live brand.com rate: the scraper falls back to the input's own
            brand = parse_rate(r.get("brand_rate", ""))
        diff, _, label = compare(parse_rate(r["raw_rate_text"]), brand)
        if label == r.get("rate_comparison"):
            out["same"] += 1
        else:
            out["changed"].append((r["hotel_name"], r["OTA_name"], r.get("rate_comparison"), label, r.get("rate_diff"), diff))
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    res = audit(sys.argv[1])
    print(f"{res['rows']} scraped rows: {res['same']} get the same label, {len(res['changed'])} change")
    for hotel, ch, old, new, od, nd in res["changed"]:
        print(f"  {hotel[:40]:40} {ch:9} {old} -> {new}   (diff {od} -> {nd})")
