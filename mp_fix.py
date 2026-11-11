#!/usr/bin/env python3
"""Read, and correct, one saved issue in Parity Manager from the QA Fixes tab.

Usage:
  python mp_fix.py ISSUE_ID --read  [--chrome http://127.0.0.1:9222]
  python mp_fix.py ISSUE_ID --apply CHANGES.json [--chrome ...]
  python mp_fix.py ISSUE_ID --images OUTDIR --stem NAME [--chrome ...]

--images downloads the issue's Lighthouse screenshots (from its Geoinsight page) into OUTDIR and prints `RESULT {"images": [...]}`.

--read prints one `RESULT {json}` line with the issue's current values and which fields the form offers.
--apply opens the issue in the tool's Chrome, changes only the fields named in CHANGES.json, saves, reads the issue back and
prints `RESULT {json}` with what it now holds. CHANGES.json is {field: value}; the fields are:
  base_shop_rate, channel_shop_rate        a number (text)
  base_cancellation, channel_cancellation  true / false
  base_platform, channel_platform          "Desktop" | "Mobile Web" | "Mobile App"
  base_screenshot, channel_screenshot      a path to an image file
Anything not in the file is left exactly as it is.
"""
import argparse
import json
import sys
from pathlib import Path

import mp_review as r

NUMBER_FIELDS = ("base_shop_rate", "channel_shop_rate")
TOGGLE_FIELDS = ("base_cancellation", "channel_cancellation")
PLATFORM_FIELDS = ("base_platform", "channel_platform")
SHOT_FIELDS = ("base_screenshot", "channel_screenshot")
ALL_FIELDS = NUMBER_FIELDS + TOGGLE_FIELDS + PLATFORM_FIELDS + SHOT_FIELDS
PLATFORM_VALUES = {label: value for value, label in r.PLATFORM_LABELS.items()}   # "Mobile App" -> "2"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")

# what each field reads as on the saved issue's page, and what the form offers (a field the form lacks is reported, not guessed at)
READ_JS = """() => {
  const q = n => document.querySelector(`[name="${n}"]`);
  const val = n => { const e = q(n); return e ? (e.type === 'checkbox' ? e.checked : e.value) : null; };
  const chosen = n => { const e = q(n); return e && e.tagName === 'SELECT' ? e.value : null; };
  const has = n => !!q(n);
  const names = ['base_shop_rate', 'channel_shop_rate', 'base_cancellation', 'channel_cancellation',
                 'base_platform', 'channel_platform', 'base_screenshot', 'channel_screenshot'];
  const shot = n => { const e = q(n); return e ? { has_input: true, current: e.closest('div') ? (e.closest('div').querySelector('a') || {}).href || null : null } : { has_input: false, current: null }; };
  return { values: { base_shop_rate: val('base_shop_rate'), channel_shop_rate: val('channel_shop_rate'),
                     base_cancellation: val('base_cancellation'), channel_cancellation: val('channel_cancellation'),
                     base_platform: chosen('base_platform'), channel_platform: chosen('channel_platform') },
           offered: Object.fromEntries(names.map(n => [n, has(n)])),
           shots: { base_screenshot: shot('base_screenshot'), channel_screenshot: shot('channel_screenshot') } };
}"""


def validate(changes):
    """Check CHANGES.json before any page is touched. Returns a list of plain problems (empty means fine)."""
    problems = []
    for field, value in changes.items():
        if field not in ALL_FIELDS:
            problems.append(f"{field} is not a field that can be fixed")
        elif field in NUMBER_FIELDS:
            try:
                if float(str(value).replace(",", ".")) <= 0:
                    raise ValueError
            except ValueError:
                problems.append(f"{field} must be a number above 0, not {value!r}")
        elif field in TOGGLE_FIELDS:
            if not isinstance(value, bool):
                problems.append(f"{field} must be ticked or not ticked")
        elif field in PLATFORM_FIELDS:
            if value not in PLATFORM_VALUES:
                problems.append(f"{field} must be one of {', '.join(PLATFORM_VALUES)}")
        elif field in SHOT_FIELDS:
            path = Path(str(value))
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                problems.append(f"{field} must be a PNG or JPEG image")
            elif not path.is_file() or path.stat().st_size == 0:
                problems.append(f"{field}: the file {path.name!r} is missing or empty")
    return problems


def read_issue(page):
    data = page.evaluate(READ_JS)
    data["values"]["base_platform"] = r.PLATFORM_LABELS.get(data["values"]["base_platform"], data["values"]["base_platform"])
    data["values"]["channel_platform"] = r.PLATFORM_LABELS.get(data["values"]["channel_platform"], data["values"]["channel_platform"])
    return data


def apply_changes(page, changes):
    """Set each named field on the open issue form. Returns the fields it set; raises RuntimeError naming a field the form does not offer."""
    offered = page.evaluate(READ_JS)["offered"]
    missing = [f for f in changes if not offered.get(f)]
    if missing:
        raise RuntimeError("The issue form has no field for: " + ", ".join(m.replace("_", " ") for m in missing))
    done = []
    for field, value in changes.items():
        if field in NUMBER_FIELDS:
            page.fill(f"#id_{field}", str(value).replace(",", "."))
        elif field in TOGGLE_FIELDS:
            import mp_upload
            mp_upload.set_toggle(page, field, value)
        elif field in PLATFORM_FIELDS:
            page.select_option(f"#id_{field}", PLATFORM_VALUES[value])
        elif field in SHOT_FIELDS:
            page.set_input_files(f"#id_{field}", str(value))
        done.append(field)
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("issue_id")
    ap.add_argument("--chrome", default="http://127.0.0.1:9222")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--read", action="store_true")
    mode.add_argument("--apply", type=Path, metavar="CHANGES.json")
    mode.add_argument("--images", metavar="OUTDIR")
    ap.add_argument("--stem", default="fix")
    args = ap.parse_args()
    if not args.issue_id.isdigit():
        sys.exit("ERROR That is not an issue id")

    changes = {}
    if args.apply:
        try:
            changes = json.loads(args.apply.read_text())
        except (OSError, ValueError):
            sys.exit("ERROR The changes file could not be read")
        if not changes:
            sys.exit("ERROR There is nothing to change")
        problems = validate(changes)
        if problems:
            sys.exit("ERROR " + "; ".join(problems))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.chrome)
        ctx = browser.contexts[0]
        url = r.ISSUE_URL.format(args.issue_id)
        if args.images:
            parsed = r.parse_issue_html(ctx.request.get(url).text())
            if not parsed["signed_in"]:
                sys.exit("ERROR Could not read the issue. Are you signed in to Parity Manager in the tool's Chrome?")
            if not parsed["geoinsight"]:
                sys.exit("ERROR This issue has no Geoinsight link")
            print("RESULT " + json.dumps({"images": r.fetch_geo_images(browser, ctx, parsed["geoinsight"], args.images, args.stem)}))
            return
        if args.read:                       # the page's own source: no window, tab or click
            html = ctx.request.get(url).text()
            parsed = r.parse_issue_html(html)
            if not parsed["signed_in"]:
                sys.exit("ERROR Could not read the issue. Are you signed in to Parity Manager in the tool's Chrome?")
            f = parsed["fields"]
            print("RESULT " + json.dumps({"issue_id": args.issue_id, "geoinsight": parsed["geoinsight"], "values": {
                "base_shop_rate": f.get("base_shop_rate"), "channel_shop_rate": f.get("channel_shop_rate"),
                "base_cancellation": f.get("base_cancellation"), "channel_cancellation": f.get("channel_cancellation"),
                "channel_platform": f.get("channel_platform")}}))
            return
        page = ctx.new_page()
        try:
            page.goto(url)
            try:
                page.wait_for_selector(r.FORM_READY, timeout=20000)
            except Exception:
                sys.exit("ERROR The issue page did not load. Are you signed in to Parity Manager in the tool's Chrome?")
            try:
                done = apply_changes(page, changes)
            except RuntimeError as e:
                sys.exit(f"ERROR {e}")
            page.click('button[name="_save"], input[name="_save"]')
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            errors = [t for t in page.eval_on_selector_all(".errorlist li, .errornote",
                      "els => [...new Set(els.map(e => e.innerText.trim()).filter(Boolean))]")]
            if errors:
                sys.exit("ERROR Parity Manager did not accept it: " + "; ".join(errors)[:300])
            back = ctx.request.get(url).text()                      # read it back: what the issue now holds, not what was sent
            f = r.parse_issue_html(back)["fields"]
            print("RESULT " + json.dumps({"issue_id": args.issue_id, "changed": done, "now": {
                "base_shop_rate": f.get("base_shop_rate"), "channel_shop_rate": f.get("channel_shop_rate"),
                "base_cancellation": f.get("base_cancellation"), "channel_cancellation": f.get("channel_cancellation"),
                "channel_platform": f.get("channel_platform")}}))
        finally:
            try:
                page.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
