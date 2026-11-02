#!/usr/bin/env python3
"""Open one saved issue (and its Geoinsight page) in the tool's Chrome and compare its fields with the results CSV.

Usage:
  python mp_review.py done_results.csv KEY [--chrome http://127.0.0.1:9222]

The first argument is a done log, which on its own holds everything needed. KEY is its `key` column (channel|brand code|date). Prints one `RESULT {json}` line at the end.
The issue and the Geoinsight page each get their own window, which are reused for every issue, so only two are open.
"""
import argparse
import json
import re
import struct
import sys
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import mp_upload as m

ISSUE_URL = "https://paritymanager.mylighthouse.com/admin/parity_manager/adminpromotionparityissue/{}/change/"
GEO_PREFIX = "https://app.mylighthouse.com/geoinsight"
FORM_READY = "[name=base_shop_rate]"

READ_JS = """() => {
  const val = n => { const e = document.querySelector(`[name="${n}"]`);
                     return e ? (e.type === 'checkbox' ? e.checked : e.value) : null; };
  const geo = [...document.querySelectorAll('a')].find(a => a.href.includes('/geoinsight'));
  const names = ['subscription_id', 'arrival_date', 'channel_id', 'base_shop_rate', 'channel_shop_rate',
                 'base_cancellation', 'channel_cancellation'];
  return { fields: Object.fromEntries(names.map(n => [n, val(n)])), geoinsight: geo ? geo.href : null };
}"""


def same_number(a, b):
    try:
        return abs(float(a) - float(b)) < 0.005
    except (TypeError, ValueError):
        return False


FIELD_NAMES = ["subscription_id", "arrival_date", "channel_id", "channel_platform", "base_shop_rate", "channel_shop_rate",
               "base_cancellation", "channel_cancellation"]
PLATFORM_LABELS = {"0": "Desktop", "1": "Mobile Web", "2": "Mobile App"}   # the form's Channel platform options


NOT_CHECKED = "not checked"   # shown as the expected value when the tool has nothing to compare against; the issue's own value still shows


def expected_checks(entry):
    """(label, form field, expected value, comparison) for each field of the issue, from a done-log entry.

    A field the done log has no value for (issues pulled from the dashboard, older done logs, a cancellation the tool left as
    pre-filled) still gets its row, with NOT_CHECKED as the expected value and no comparison, so the issue's own value is shown."""
    if str(entry.get("key", "")).startswith("dashboard|"):   # pulled from the dashboard: only the issue's own values, to be compared with the screenshots
        return [(label, field, NOT_CHECKED, None) for label, field in (
            ("Subscription id", "subscription_id"), ("Arrival date", "arrival_date"), ("Channel", "channel_id"),
            ("Channel platform", "channel_platform"), ("Base rate", "base_shop_rate"), ("Channel rate", "channel_shop_rate"),
            ("Base cancellation", "base_cancellation"), ("Channel cancellation", "channel_cancellation"))]

    def sure(value, known=True):
        return (value, True) if known else (NOT_CHECKED, False)

    platform, p_known = sure("Mobile App" if entry.get("platform") == "app" else "Mobile Web", entry.get("platform") != "?")
    # done files from before Mobile App issues existed are all Mobile Web; "?" = unknown, as for issues pulled from the dashboard
    has_rates = bool(entry.get("base_rate"))   # done logs from before the entered values were recorded may not have them
    checks = [
        ("Subscription id", "subscription_id", entry.get("subscription_id", ""), lambda e, a: str(e) == str(a)),
        ("Arrival date", "arrival_date", m.normalize_date(entry.get("from_date", "")), lambda e, a: e == m.normalize_date(a)),
        ("Channel", "channel_id", entry.get("OTA_name", ""), lambda e, a: str(e).lower() == str(a).lower()),
        ("Channel platform", "channel_platform", platform, (lambda e, a: e == a) if p_known else None),
    ]
    if entry.get("difference"):        # the dashboard's own figure should equal base rate minus channel rate on the issue
        checks.append(("Difference with base rate", "difference", entry["difference"], same_number))
    checks += [("Base rate", "base_shop_rate", entry["base_rate"] if has_rates else NOT_CHECKED, same_number if has_rates else None),
               ("Channel rate", "channel_shop_rate", entry.get("channel_rate", "") if has_rates else NOT_CHECKED,
                same_number if has_rates else None)]
    for label, field in (("Base cancellation", "base_cancellation"), ("Channel cancellation", "channel_cancellation")):
        text = entry.get(field, "")
        if text in ("ticked", "not ticked"):
            checks.append((label, field, text == "ticked", lambda e, a: bool(e) == bool(a)))
        else:      # "left as pre-filled" means nothing was set, so there is nothing to check, but the issue's value is shown
            checks.append((label, field, NOT_CHECKED, None))
    return checks


def compare(actual, entry):
    """List of {field, expected, actual, ok} for what the tool entered versus what the saved issue holds.
    ok is None for a field with nothing to compare against."""
    return [{"field": label, "expected": exp, "actual": actual.get(field),
             "ok": None if ok is None else actual.get(field) is not None and ok(exp, actual[field])}
            for label, field, exp, ok in expected_checks(entry)]


def readonly_value(html, label):
    """The text of a read-only field on the issue page, found by its label (e.g. 'Subscription name', 'Base rate')."""
    match = re.search(r">\s*%s\s*</label>.*?class=\"readonly[^\"]*\"[^>]*>\s*([^<]*?)\s*</div>" % re.escape(label), html, re.S)
    return unescape(match.group(1)) if match and match.group(1) not in ("", "-") else None   # the page stores & as &amp; and so on


class FormReader(HTMLParser):
    """Reads the field values and the Geoinsight link out of a saved issue's page source."""

    def __init__(self):
        super().__init__()
        self.fields, self.geoinsight, self._select = {}, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        name = a.get("name")
        if tag == "input" and name in FIELD_NAMES:
            self.fields[name] = ("checked" in a) if a.get("type") == "checkbox" else a.get("value", "")
        elif tag == "select" and name in FIELD_NAMES:
            self._select = name
            self.fields.setdefault(name, None)
        elif tag == "option" and self._select and "selected" in a:
            self.fields[self._select] = a.get("value")
        elif tag == "a" and self.geoinsight is None and "/geoinsight" in (a.get("href") or ""):
            self.geoinsight = a["href"]

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None


def parse_issue_html(html):
    reader = FormReader()
    reader.feed(html)
    fields = {n: reader.fields.get(n) for n in FIELD_NAMES}
    fields["channel_platform"] = PLATFORM_LABELS.get(fields["channel_platform"], fields["channel_platform"])
    fields["subscription_name"] = readonly_value(html, "Subscription name")
    # the rates as saved, converted to the subscription's currency, which is what the dashboard's difference is based on
    base = readonly_value(html, "Base rate") or fields["base_shop_rate"]
    channel = readonly_value(html, "Channel rate") or fields["channel_shop_rate"]
    try:
        fields["difference"] = round(float(base) - float(channel), 2)
    except (TypeError, ValueError):
        fields["difference"] = None
    return {"fields": fields, "geoinsight": reader.geoinsight,
            "signed_in": "base_shop_rate" in reader.fields}


def open_in_new_window(browser, ctx, url):
    """Open url in a window of its own (created with the url, never as a blank page to navigate afterwards)."""
    try:
        with ctx.expect_page(timeout=15000) as opened:
            browser.new_browser_cdp_session().send("Target.createTarget", {"url": url, "newWindow": True})
        return opened.value
    except Exception:
        return None  # it may still have opened; do not open a second window


def reuse_or_open(browser, ctx, match, url):
    for page in ctx.pages:
        if match(page.url):
            page.goto(url)
            return page
    return open_in_new_window(browser, ctx, url)


GEO_IMAGE_URL = "https://screenshots-v3.mylighthouse.com/?img={}"
GEO_IMG_JS = """() => [...document.querySelectorAll('img')]
  .filter(e => e.complete && e.naturalWidth > 300)
  .map(e => ({src: e.currentSrc || e.src, w: e.naturalWidth, h: e.naturalHeight}))"""


def geo_labels(geo_url):
    """Channel names in the order Geoinsight lists the screenshots (taken from the link itself)."""
    query = parse_qs(urlsplit(geo_url).query)
    for name in ("otasPn", "otas"):
        try:
            labels = json.loads(query.get(name, ["[]"])[0])
        except ValueError:
            labels = []
        if labels:
            return labels
    return []


def open_background_page(browser, ctx, url):
    """A tab that does not take focus, so reading Geoinsight does not flash a window at the user."""
    try:
        with ctx.expect_page(timeout=15000) as opened:   # waits while Playwright processes browser events
            browser.new_browser_cdp_session().send("Target.createTarget", {"url": url, "background": True})
        return opened.value
    except Exception:
        return None


def geo_iids(geo_url):
    """The screenshot ids carried by a Geoinsight link, in the order the page lists them."""
    try:
        ids = json.loads(parse_qs(urlsplit(geo_url).query).get("iid", ["[]"])[0])
    except ValueError:
        return []
    return [i for i in ids if isinstance(i, str) and i]


def png_size(body):
    if body[:8] == b"\x89PNG\r\n\x1a\n" and len(body) >= 24:
        return struct.unpack(">II", body[16:24])
    return 0, 0


def fetch_direct(ctx, geo_url, outdir, stem):
    """Geoinsight serves each screenshot at screenshots-v3.mylighthouse.com/?img=<id>.png, with the ids in the link,
    so the images can be downloaded without opening the page at all. None if that does not work."""
    iids, labels = geo_iids(geo_url), geo_labels(geo_url)
    found = []
    for n, iid in enumerate(iids):
        try:
            resp = ctx.request.get(GEO_IMAGE_URL.format(quote(iid + ".png", safe="")))
            body = resp.body()
        except Exception:
            return None
        if resp.status != 200 or not resp.headers.get("content-type", "").startswith("image/") or not body:
            return None
        name = f"{stem}_{n}.png"
        (Path(outdir) / name).write_bytes(body)
        w, h = png_size(body)
        found.append({"file": name, "label": labels[n] if n < len(labels) else f"Screenshot {n + 1}", "w": w, "h": h})
    return found or None


def fetch_geo_images(browser, ctx, geo_url, outdir, stem):
    direct = fetch_direct(ctx, geo_url, outdir, stem)   # no window, tab or page involved
    if direct:
        return direct
    return fetch_geo_images_from_page(browser, ctx, geo_url, outdir, stem)   # fallback if Lighthouse changes the pattern


def fetch_geo_images_from_page(browser, ctx, geo_url, outdir, stem):
    """Download the screenshots shown on a Geoinsight page, using the signed-in session of the tool's Chrome."""
    labels = geo_labels(geo_url)
    wanted = len(labels) or 2
    page = open_background_page(browser, ctx, geo_url)
    if page is None:
        sys.exit("ERROR Could not open the Geoinsight page in the tool's Chrome")
    try:
        imgs = []
        for _ in range(45):  # up to ~45 s for the (large) screenshots to finish loading
            imgs = page.evaluate(GEO_IMG_JS)
            if len(imgs) >= wanted:
                break
            page.wait_for_timeout(1000)
    finally:
        page.close()
    if not imgs:
        sys.exit("ERROR Geoinsight showed no screenshots. Are you signed in to Lighthouse in the tool's Chrome?")
    found = []
    for n, img in enumerate(imgs[:wanted]):
        body = ctx.request.get(img["src"]).body()
        name = f"{stem}_{n}.png"
        (Path(outdir) / name).write_bytes(body)
        found.append({"file": name, "label": labels[n] if n < len(labels) else f"Screenshot {n + 1}",
                      "w": img["w"], "h": img["h"]})
    return found


def close_blank_pages(ctx):
    """about:blank pages only come from automation, so leftovers can safely go."""
    for page in list(ctx.pages):
        if page.url == "about:blank":
            try:
                page.close()
            except Exception:
                pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("done", type=Path, help="the done log of a run")
    ap.add_argument("key")
    ap.add_argument("--chrome", default="http://127.0.0.1:9222")
    ap.add_argument("--check-only", action="store_true", help="read the issue in the background, open no windows")
    ap.add_argument("--geo-images", metavar="OUTDIR", help="download the issue's Geoinsight screenshots into OUTDIR")
    ap.add_argument("--stem", default="shot", help="file name prefix for --geo-images")
    args = ap.parse_args()

    entry = m.load_done_entries(args.done).get(args.key)
    if entry is None:
        sys.exit("ERROR That issue is not saved in this done file")
    if not entry.get("issue_id"):
        sys.exit("ERROR No issue id was recorded for this row (it was saved before reviews existed). Open it in Parity Manager by hand")
    saved = entry

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.chrome)
        ctx = browser.contexts[0]
        if args.geo_images:
            data = parse_issue_html(ctx.request.get(ISSUE_URL.format(saved["issue_id"])).text())
            if not data["signed_in"]:
                sys.exit("ERROR Could not read the issue. Are you signed in to Parity Manager in the tool's Chrome?")
            if not data["geoinsight"]:
                sys.exit("ERROR This issue has no Geoinsight link")
            print("RESULT " + json.dumps({"images": fetch_geo_images(browser, ctx, data["geoinsight"], args.geo_images, args.stem)}))
            return
        if args.check_only:  # uses the signed-in session's cookies, so no tab or window is opened
            data = parse_issue_html(ctx.request.get(ISSUE_URL.format(saved["issue_id"])).text())
            if not data["signed_in"]:
                sys.exit("ERROR Could not read the issue. Are you signed in to Parity Manager in the tool's Chrome?")
            checks = compare(data["fields"], entry)
            print("RESULT " + json.dumps({"issue_id": saved["issue_id"], "checks": checks, "geoinsight": data["geoinsight"], "hotel_name": data["fields"].get("subscription_name") or "",
                                          "all_ok": all(c["ok"] is not False for c in checks)}))
            return
        close_blank_pages(ctx)
        issue_page = reuse_or_open(browser, ctx, lambda u: "/adminpromotionparityissue/" in u and "/change/" in u,
                                   ISSUE_URL.format(saved["issue_id"]))
        if issue_page is None:
            sys.exit("ERROR The issue window opened but could not be controlled. Close it and try again")
        try:
            issue_page.wait_for_selector(FORM_READY, timeout=20000)
        except Exception:
            sys.exit("ERROR The issue page did not load. Are you signed in to Parity Manager in the tool's Chrome?")
        data = issue_page.evaluate(READ_JS)
        checks = compare(data["fields"], entry)
        if data["geoinsight"]:
            reuse_or_open(browser, ctx, lambda u: u.startswith(GEO_PREFIX), data["geoinsight"])
        issue_page.bring_to_front()
        print("RESULT " + json.dumps({"issue_id": saved["issue_id"], "checks": checks,
                                      "geoinsight": data["geoinsight"], "hotel_name": data["fields"].get("subscription_name") or "", "all_ok": all(c["ok"] is not False for c in checks)}))


if __name__ == "__main__":
    main()
