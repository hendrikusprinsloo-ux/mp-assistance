#!/usr/bin/env python3
"""Fill Parity Manager "Add Mobile Parity Issue" forms from a parity scraper results CSV.

For every eligible CSV row the tool opens the row's `add_issue_to_pm` URL, then sets:
  base_shop_rate       <- branddotcom_parsed_rate
  channel_shop_rate    <- parsed_rate
  base_cancellation    <- branddotcom_cancellation_policy
  channel_cancellation <- channel_cancellation_policy
  base_screenshot      <- branddotcom_screenshot_path
  channel_screenshot   <- screenshot_path
and then waits for you to review the form and click Save yourself.

Mobile App issues (--platform app) use the same form with Channel platform set to Mobile App. Their channel screenshot and
channel rate come from --app-inputs, a JSON file {row key: {"shot": png path, "rate": "76"}}; the base screenshot and base rate
still come from the results row. Only Booking.com and Expedia rows that are lower than brand qualify.

Usage:
  python mp_upload.py results.csv [--dry-run] [--limit N] [--start N] [--platform app --app-inputs inputs.json]
"""
import argparse
import csv
import json
import queue
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

CHROME_URL = "http://127.0.0.1:9222"   # the tool's own Chrome, started with its debugging port
FORM_READY = "#id_base_shop_rate"
REFUNDABLE = {"fully refundable": True, "non-refundable": False}
APP_CANCELLATION = {"ticked": True, "not ticked": False}     # what the person picks for a Mobile App issue's channel cancellation
LOG_FIELDS = ["timestamp", "key", "OTA_name", "brand_code", "from_date", "subscription_id", "hotel_name", "outcome", "note",
              "client", "sheet_url", "issue_id", "base_rate", "channel_rate", "base_cancellation", "channel_cancellation",
              "platform", "difference"]
# base_rate to channel_cancellation record what was entered on the form, so a done file alone is enough for someone else to QA
# the run; platform says whether it was a web or a Mobile App issue (the client column holds the chain).
APP_CHANNELS = ("bookingdotcom", "expedia")   # the only channels a Mobile App issue can be raised for
PLATFORM_APP = "2"                            # the form's Channel platform value for Mobile App (Mobile Web is 1)

# Every saved issue is also noted in a ledger kept with the app, so daily limits and "already uploaded" can be worked out
# across the day's several results files.
LEDGER = Path(__file__).parent / "issues_ledger.csv"
LEDGER_FIELDS = ["date", "timestamp", "chain", "platform", "channel", "brand_code", "key", "issue_id", "results_file", "subscription_id"]


def today():
    return datetime.now().date().isoformat()


def ledger_read():
    if not LEDGER.is_file():
        return []
    with open(LEDGER, newline="") as f:
        return list(csv.DictReader(f))


def ledger_append(entry):
    new = not LEDGER.is_file() or LEDGER.stat().st_size == 0
    with open(LEDGER, "a", newline="") as f:
        w = csv.DictWriter(f, LEDGER_FIELDS)
        if new:
            w.writeheader()
        w.writerow(entry)


def load_rows(csv_path):
    """The scraper CSV starts with a `sep=,` hint line, which has to be skipped."""
    with open(csv_path, newline="", encoding="utf-8-sig") as f:  # the file starts with a BOM
        lines = f.readlines()
    if lines and lines[0].strip().lower().startswith("sep="):
        lines = lines[1:]
    rows = list(csv.DictReader(lines))
    folder = Path(csv_path).parent
    for r in rows:
        for column in SHOT_COLUMNS:
            r[column] = local_shot(r.get(column) or "", folder)
    return [(i + 3, r) for i, r in enumerate(rows)]  # i+3 = line number in the CSV file


SHOT_COLUMNS = ("screenshot_path", "branddotcom_screenshot_path")


def local_shot(path, folder):
    """A results file from another computer holds that computer's screenshot paths. The screenshots travel in the same folder
    as the CSV, so when the path is not a file here, use the file of the same name next to the CSV."""
    if not path or Path(path).is_file():
        return path
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return str(folder / name) if (folder / name).is_file() else path


def row_key(row):
    """A sheet row is identified by channel, brand code and from_date."""
    return "|".join((row["OTA_name"].strip().lower(), row["brand_code"].strip().lower(), row["from_date"].strip()))


def subscription_id(row):
    marker = "subscription_id="
    url = row["add_issue_to_pm"]
    return url.split(marker, 1)[1].split("&", 1)[0] if marker in url else ""


ISSUE_ID_RE = re.compile(r"/adminpromotionparityissue/(\d+)/change/")


def find_issue_id(page):
    """Id of the issue that was just saved: from the URL, or the newest issue link on the list page."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        match = ISSUE_ID_RE.search(page.url)
        if match:
            return match.group(1)
        hrefs = page.eval_on_selector_all("a[href*='/change/']", "els => els.map(e => e.getAttribute('href'))")
    except Exception:
        return ""
    ids = [int(m.group(1)) for m in (ISSUE_ID_RE.search(h or "") for h in hrefs) if m]
    return str(max(ids)) if ids else ""


def normalize_date(text):
    """Dates arrive as 2026-10-29, 10/29/26, 29-10-2026 and so on; return YYYY-MM-DD, or the text unchanged if unreadable."""
    t = str(text).strip().replace("T", " ").split(" ")[0]
    match = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", t)
    if match:
        year, month, day = map(int, match.groups())
    else:
        match = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{2}|\d{4})$", t)
        if not match:
            return str(text)
        first, second, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        month, day = (second, first) if first > 12 else (first, second)   # US month/day unless the first number cannot be a month
        year += 2000 if year < 100 else 0
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return str(text)


def cancellation_text(value):
    return "left as pre-filled" if value is None else "ticked" if value else "not ticked"


def load_done_entries(done_path):
    """Saved issues of a done log, latest save per issue key, each with the values that were entered.

    Logs written before those values were recorded get them from the results CSV next to the log, when it is there."""
    entries = {}
    for entry in read_log(done_path):
        if entry.get("outcome") == "saved" and entry.get("key"):
            entries[entry["key"]] = entry
    name = Path(done_path).name
    results = Path(done_path).with_name(name[len("done_"):]) if name.startswith("done_") else None
    if results and results.is_file() and any(not e.get("base_rate") for e in entries.values()):
        rows = {row_key(r): r for _, r in load_rows(results)}
        for key, entry in entries.items():
            plan = plan_for(rows[key])[0] if key in rows else None
            if plan and not entry.get("base_rate"):
                entry.update(base_rate=plan["base_shop_rate"], channel_rate=plan["channel_shop_rate"],
                             base_cancellation=cancellation_text(plan["base_cancellation"]),
                             channel_cancellation=cancellation_text(plan["channel_cancellation"]))
    return entries


def read_log(log_path):
    """Rows of a done log; tolerates a missing header and an older header without the client/sheet columns."""
    with open(log_path, newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    names = rows[0] if rows[0][:1] == ["timestamp"] else None
    body = rows[1:] if names else rows
    names = names or LOG_FIELDS
    return [dict(zip(names, r)) for r in body if r]


def repair_log(log_path):
    """Rewrite the log with the current header when it is missing, or lacks the newer columns."""
    if not log_path.exists() or log_path.stat().st_size == 0:
        return
    with open(log_path, newline="") as f:
        first = next(csv.reader(f), [])
    rows = read_log(log_path)
    if first == LOG_FIELDS:
        return
    with open(log_path, "w", newline="") as f:
        w = csv.DictWriter(f, LOG_FIELDS)
        w.writeheader()
        w.writerows(rows)


def plan_for(row, platform="web", app_input=None):
    """Return (plan, problems). plan is None when the row cannot be processed.

    For platform "app", app_input is {"shot": png path, "rate": text, "cancellation": "ticked"|"not ticked"}: the phone screenshot, the rate typed
    from it and the channel cancellation chosen for it (the phone page can differ from the web page the results file was read from)."""
    problems = []
    if row.get("status") != "ok" or row.get("branddotcom_status") != "ok":
        return None, [f"status={row.get('status')!r} branddotcom_status={row.get('branddotcom_status')!r}"]
    if row.get("rate_comparison") != "lower_than_brand":
        return None, [f"rate_comparison={row.get('rate_comparison')!r}"]
    if not row.get("add_issue_to_pm", "").startswith("http"):
        return None, ["no add_issue_to_pm URL"]

    if platform == "app":
        if row.get("OTA_name", "").strip().lower() not in APP_CHANNELS:
            return None, [f"Mobile App issues are only for Booking.com and Expedia, not {row.get('OTA_name')!r}"]
        if not app_input or not app_input.get("shot") or not str(app_input.get("rate", "")).strip():
            return None, ["no phone screenshot and rate given yet"]
        if app_input.get("cancellation") not in APP_CANCELLATION:
            return None, ["no channel cancellation chosen yet"]

    plan = {
        "url": row["add_issue_to_pm"],
        "base_shop_rate": row["branddotcom_parsed_rate"],
        "channel_shop_rate": row["parsed_rate"],
        "channel_screenshot": row["screenshot_path"],
        "base_screenshot": row["branddotcom_screenshot_path"],
        "channel_platform": None,   # None leaves Mobile Web, which is what the issue URL pre-fills
    }
    if platform == "app":
        plan.update(channel_platform=PLATFORM_APP, channel_screenshot=app_input["shot"],
                    channel_shop_rate=str(app_input["rate"]).strip())
    for key in ("base_shop_rate", "channel_shop_rate"):
        try:
            float(plan[key])
        except ValueError:
            problems.append(f"{key} is not a number: {plan[key]!r}")
    for key in ("base_screenshot", "channel_screenshot"):
        shot = Path(plan[key])
        if not shot.is_file() or shot.stat().st_size == 0:
            problems.append(f"{key} file missing or empty: {plan[key]!r}")

    for form_field, column in (("base_cancellation", "branddotcom_cancellation_policy"),
                               ("channel_cancellation", "channel_cancellation_policy")):
        policy = row.get(column, "").strip().lower()
        if policy in REFUNDABLE:
            plan[form_field] = REFUNDABLE[policy]
        else:
            plan[form_field] = None  # leave whatever the URL pre-filled, flag it for review
            problems.append(f"{column} is {row.get(column)!r}: {form_field} left as pre-filled")
    if platform == "app":
        plan["channel_cancellation"] = APP_CANCELLATION[app_input["cancellation"]]    # chosen by the person, whatever the results file says
        problems[:] = [p for p in problems if not p.startswith("channel_cancellation_policy")]
    return plan, problems


def skip_reason(problems):
    """A short, plain reason for a row plan_for() refused (its first problem)."""
    text = problems[0] if problems else ""
    for start, reason in (("status=", "scrape status not ok"), ("rate_comparison=", "not lower than brand"),
                          ("no add_issue_to_pm", "no issue link"), ("Mobile App issues are only", "not Booking.com or Expedia"),
                          ("no phone screenshot", "no phone screenshot or rate yet")):
        if text.startswith(start):
            return reason
    return text or "not eligible"


def set_toggle(page, field, want):
    """Tick or untick one of the form's toggles. The page styles them as switches and now and then ignores a click, so when the click
    does not change the state the value is set directly and the page is told, then checked. A toggle that still will not hold the
    value raises a plain message (the app shows it) instead of a long traceback."""
    box = page.locator(f"#id_{field}")
    try:
        box.set_checked(want, force=True, timeout=5000)
        return
    except Exception:
        pass
    box.evaluate("""(el, want) => { if (el.checked !== want) { el.checked = want;
        el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); } }""", want)
    if box.is_checked() != want:
        raise RuntimeError(f"The form would not set {field.replace('_', ' ')} to {'ticked' if want else 'not ticked'}")


def fill_form(page, plan):
    page.goto(plan["url"])
    page.wait_for_selector(FORM_READY, timeout=0)  # blocks until you are logged in and the form shows
    if plan.get("channel_platform"):
        page.select_option("#id_channel_platform", plan["channel_platform"])
    page.fill("#id_base_shop_rate", plan["base_shop_rate"])
    page.fill("#id_channel_shop_rate", plan["channel_shop_rate"])
    for field in ("base_cancellation", "channel_cancellation"):
        if plan[field] is not None:
            set_toggle(page, field, plan[field])
    page.set_input_files("#id_base_screenshot", plan["base_screenshot"])
    page.set_input_files("#id_channel_screenshot", plan["channel_screenshot"])


COMMANDS = queue.Queue()   # lines typed to the tool (or sent by the app): save, s (skip), q (stop)


def start_command_reader():
    """One reader for the whole run. (A reader per issue let an old one swallow a command meant for the next issue.)"""
    def read():
        for line in sys.stdin:
            COMMANDS.put(line.strip().lower())
    threading.Thread(target=read, daemon=True).start()


def emit(info, phase, **extra):
    """Tell the app what the run is doing, as a line it picks up and keeps out of the log."""
    print("@@STATE " + json.dumps({**info, "phase": phase, **extra}), flush=True)


READ_BACK_JS = """() => {
  const q = s => document.querySelector(s);
  const chosen = s => { const e = q(s); return e && e.selectedOptions && e.selectedOptions[0] ? e.selectedOptions[0].textContent.trim() : null; };
  const file = s => { const e = q(s), f = e && e.files && e.files[0]; return f ? { name: f.name, size: f.size } : null; };
  return { base_rate: q('#id_base_shop_rate').value, channel_rate: q('#id_channel_shop_rate').value,
           base_cancellation: q('#id_base_cancellation').checked, channel_cancellation: q('#id_channel_cancellation').checked,
           channel: chosen('#id_channel_id'), platform: chosen('#id_channel_platform'),
           base_file: file('#id_base_screenshot'), channel_file: file('#id_channel_screenshot') };
}"""


def read_back(page):
    """What the form actually holds right now, as the page itself reports it."""
    try:
        return page.evaluate(READ_BACK_JS)
    except Exception:
        return None


def form_errors(page):
    try:
        return page.eval_on_selector_all(".errorlist li, .errornote",
                                         "els => [...new Set(els.map(e => e.innerText.trim()).filter(Boolean))]")
    except Exception:
        return []


def attach_files(page, plan):
    page.set_input_files("#id_base_screenshot", plan["base_screenshot"])
    page.set_input_files("#id_channel_screenshot", plan["channel_screenshot"])


LEFT_OUT_FIELDS = ["timestamp", "key", "OTA_name", "brand_code", "from_date", "subscription_id", "hotel_name", "client", "reason"]


def left_out_path(csv_path):
    """Where the rows a full channel left out are listed: left_out_<results name>.csv next to the results file. It is not a done file and does not start
    with results_, so Mobile App (which hides what a done file holds) and the results pickers never read it."""
    return Path(csv_path).with_name(f"left_out_{Path(csv_path).stem}.csv")


def record_left_out(csv_path, row, client, why):
    """Add one left-out row to that list, with a header the first time. This is a record for people only: nothing reads it back."""
    path = left_out_path(csv_path)
    new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
        w = csv.DictWriter(f, LEFT_OUT_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"timestamp": datetime.now().isoformat(timespec="seconds"), "key": row_key(row), "OTA_name": row["OTA_name"],
                    "brand_code": row["brand_code"], "from_date": row["from_date"], "subscription_id": subscription_id(row),
                    "hotel_name": row["hotel_name"], "client": client, "reason": why})


class ChannelRoom:
    """How many more issues each channel may take today. A save uses one up; a decline or a skip does not, so it frees the place for the next row.
    A channel with no limit set is never full. Rows of a full channel are left out of the run without being written to the done file, so they
    stay free for Mobile App."""

    def __init__(self, room):
        self.left = dict(room or {})
        self.left_out = {}

    def full(self, channel):
        return channel in self.left and self.left[channel] <= 0

    def leave_out(self, channel):
        self.left_out[channel] = self.left_out.get(channel, 0) + 1

    def saved(self, channel):
        if channel in self.left:
            self.left[channel] -= 1


def wait_for_review(page, info, plan):
    """Return 'saved' once the form is saved (by clicking Save in the browser, or by the save command), 's' to skip,
    ('declined', note) when the issue is declined, 'q' to stop."""
    while not COMMANDS.empty():
        COMMANDS.get_nowait()   # anything left over from an earlier issue
    phase, message, shown, passes = "ready", "", None, 0
    overrides = plan.setdefault("_overrides", set())      # cancellation toggles the person changed by hand, for the done file
    while True:
        try:
            if "/add/" not in page.url:
                return "saved"
        except Exception:
            return "q"  # browser window closed
        try:
            command = COMMANDS.get_nowait()
        except queue.Empty:
            page.wait_for_timeout(300)
            passes += 1
            if passes % 4 == 0:     # about once a second: if the form was changed in Chrome, show how it stands now
                now = read_back(page)
                if now is not None and now != shown:
                    if shown is not None:
                        emit(info, phase, values=now, message=message)
                    shown = now
            continue
        if command == "save":
            emit(info, "saving")
            try:
                page.click('button[name="_save"]')
                page.wait_for_load_state("domcontentloaded", timeout=20000)
            except Exception:
                pass
            if "/add/" not in page.url:
                return "saved"
            # the form came back: Parity Manager did not accept it. Say why, and put the screenshots back (a reload empties them).
            errors = form_errors(page)
            print("  not saved: " + ("; ".join(errors) if errors else "Parity Manager did not accept the form"))
            try:
                attach_files(page, plan)
            except Exception:
                pass
            phase = "error"
            message = "; ".join(errors) or "Parity Manager did not accept the form. Look at the Chrome window."
            shown = read_back(page)
            emit(info, phase, message=message, values=shown)
        elif command == "q":
            return "q"
        elif command.startswith("c:"):      # c:<field>:<1|0>: the person changed a cancellation toggle on the card
            try:
                _, field, value = command.split(":")
                if field in ("base_cancellation", "channel_cancellation") and value in ("0", "1"):
                    set_toggle(page, field, value == "1")
                    plan[field] = value == "1"            # what is saved and logged is what the form now holds
                    overrides.add(field)
                    shown = read_back(page)
                    emit(info, phase, values=shown, message=message)
            except Exception as e:
                print(f"  could not change {command}: {str(e).splitlines()[0][:120]}")
                emit(info, phase, values=read_back(page), message=f"Could not change that toggle: {str(e).splitlines()[0][:100]}")
        elif command.startswith("d:"):      # declined, with the person's note
            return ("declined", command[2:].strip())
        else:                       # "s", or just Enter, skips this issue
            return "s"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path, help="results CSV from the parity scraper")
    ap.add_argument("--dry-run", action="store_true", help="show what would be done, open no browser")
    ap.add_argument("--limit", type=int, help="process at most N eligible rows")
    ap.add_argument("--chrome", nargs="?", const=CHROME_URL, default=CHROME_URL, metavar="URL",
                    help=f"the tool's Chrome (started with --remote-debugging-port); default {CHROME_URL}")
    ap.add_argument("--client", default="", help="client name, recorded in the done log")
    ap.add_argument("--sheet", default="", help="daily Google Sheet link, recorded in the done log")
    ap.add_argument("--start", type=int, default=1, help="skip the first N-1 eligible rows")
    ap.add_argument("--existing", type=Path, help="JSON list of [subscription id, channel] pairs that already have an issue today; rows for them are skipped")
    ap.add_argument("--channel-room", help="JSON {channel: how many more issues it may take today}; rows past it are skipped")
    ap.add_argument("--extras-after", help="JSON {channel: n}: load only the rows past each channel's first n eligible rows (the extra issues beyond its limit)")
    ap.add_argument("--platform", choices=("web", "app"), default="web", help="web = Mobile Web issues (default), app = Mobile App")
    ap.add_argument("--app-inputs", type=Path, help="JSON file with each Mobile App row's phone screenshot and typed rate")
    args = ap.parse_args()

    app = args.platform == "app"
    app_inputs = json.loads(args.app_inputs.read_text()) if app and args.app_inputs else {}
    log_path = args.csv.with_name(f"done_{args.csv.stem}.csv")
    suffix = "|app" if app else ""            # a Mobile App issue is told apart from a web one for the same row
    already = set()
    if log_path.exists():
        already = {r["key"] for r in read_log(log_path) if r.get("outcome") in ("saved", "declined")}   # a declined row does not come back

    # Only one issue per channel per subscription can be saved. Rows are skipped when that pair already has an issue today:
    # on the dashboard (anyone's), saved from this computer today, or earlier in this same file.
    existing = {tuple(p) for p in json.loads(args.existing.read_text())} if args.existing else set()
    ledger_pairs = {(r.get("brand_code", "").strip().lower(), r.get("channel", "").strip().lower()) for r in ledger_read()
                    if r.get("date") == today() and r.get("chain") == args.client}
    todo, skipped, duplicates, seen = [], 0, 0, set()
    reasons = {}
    room = json.loads(args.channel_room) if args.channel_room and not app else {}
    taken_by_channel = {}
    extras_after = json.loads(args.extras_after) if args.extras_after and not app else {}
    position = {}
    for row_no, row in load_rows(args.csv):
        plan, problems = plan_for(row, args.platform, app_inputs.get(row_key(row)))
        if plan is not None and extras_after:       # extras only: the first n rows of a channel (done or not) are the ones within its limit
            ch = row["OTA_name"].strip().lower()
            position[ch] = position.get(ch, 0) + 1
            if ch not in extras_after or position[ch] <= extras_after[ch]:
                plan, problems = None, None
        if plan is None:
            why = skip_reason(problems) if problems is not None else "within the channel's limit (extras only)"
            reasons[why] = reasons.get(why, 0) + 1
        if plan is not None and row_key(row) + suffix not in already:
            channel = row["OTA_name"].strip().lower()
            pair = (subscription_id(row), channel)
            if pair in existing or (row["brand_code"].strip().lower(), channel) in ledger_pairs or pair in seen:
                duplicates += 1
                plan = None
            elif args.dry_run and channel in room and taken_by_channel.get(channel, 0) >= room[channel]:
                reasons[f"{channel} limit reached"] = reasons.get(f"{channel} limit reached", 0) + 1
                plan = None
            else:
                seen.add(pair)
                taken_by_channel[channel] = taken_by_channel.get(channel, 0) + 1
        if plan is None:
            skipped += 1
        elif row_key(row) + suffix not in already:
            todo.append((row_no, row, plan, problems))
    todo = todo[args.start - 1:][:args.limit]
    print(f"{len(todo)} rows to process, {skipped} not eligible, {len(already)} already saved (log: {log_path.name})")
    for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  not eligible: {n} x {why}")
    if log_path.exists():
        print(f"  note: {log_path.name} already exists; rows saved there are skipped")
    if duplicates:
        print(f"{duplicates} skipped because that hotel already has an issue for that channel today (one per channel per subscription)")

    if args.dry_run:
        for row_no, row, plan, problems in todo:
            print(f"\nrow {row_no}  {row['hotel_name']}  [{row['OTA_name']}]" + ("  (Mobile App)" if app else ""))
            print(f"  base {plan['base_shop_rate']}  channel {plan['channel_shop_rate']}  "
                  f"base_cancel={plan['base_cancellation']}  channel_cancel={plan['channel_cancellation']}")
            for p in problems:
                print(f"  ! {p}")
        return

    if not todo:      # nothing to fill: finish now instead of opening Chrome and leaving the app on "Running"
        print("Nothing to upload: no eligible rows are left (see the counts above).")
        return

    from playwright.sync_api import sync_playwright

    started = datetime.now().isoformat(timespec="seconds")
    repair_log(log_path)
    new_log = not log_path.exists() or log_path.stat().st_size == 0
    with sync_playwright() as pw, open(log_path, "a", newline="") as logf:
        log = csv.DictWriter(logf, LOG_FIELDS)
        if new_log:
            log.writeheader()
            logf.flush()  # a run that is stopped early must not leave a log without its header
        try:
            ctx = pw.chromium.connect_over_cdp(args.chrome).contexts[0]
        except Exception:
            sys.exit(f"Could not reach the tool's Chrome at {args.chrome}. Start it from the app (Open Chrome for the tool) and try again.")
        for stale in list(ctx.pages):  # blank pages left over from earlier automation
            if stale.url == "about:blank":
                stale.close()
        page = ctx.new_page()
        print("Using the tool's Chrome; the form opens in a new tab.")

        start_command_reader()
        channels = ChannelRoom({} if app else room)
        shown = 0
        for row_no, row, plan, problems in todo:
            channel_now = row["OTA_name"].strip().lower()
            if channels.full(channel_now):
                channels.leave_out(channel_now)                  # skipped, not declined: not in the done file, so it is still free for Mobile App
                record_left_out(args.csv, row, args.client, f"{channel_now} was full for today")      # but listed in left_out_<name>.csv, for people
                continue
            shown += 1
            n = shown
            print(f"\n[{n}/{len(todo)}] row {row_no}  {row['hotel_name']}  [{row['OTA_name']}]" + ("  (Mobile App)" if app else ""))
            issue_id = ""
            info = {"n": n, "total": max(len(todo) - sum(channels.left_out.values()), n), "hotel": row["hotel_name"], "channel": row["OTA_name"], "brand_code": row["brand_code"],
                    "subscription_id": subscription_id(row),
                    "platform": args.platform, "problems": problems,
                    "expected": {"base_rate": plan["base_shop_rate"], "channel_rate": plan["channel_shop_rate"],
                                 "base_cancellation": plan["base_cancellation"], "channel_cancellation": plan["channel_cancellation"],
                                 "platform": "Mobile App" if app else "Mobile Web"},
                    "shots": {"base": plan["base_screenshot"], "channel": plan["channel_screenshot"]}}
            emit(info, "filling")
            values = None
            for p in problems:
                print(f"  ! {p}")
            if any("missing" in p or "not a number" in p for p in problems):
                outcome, note = "skipped", "; ".join(problems)
                print("  skipped (blocking problem)")
                emit(info, "skipped", message="Skipped: " + note)
            else:
                fill_form(page, plan)
                values = read_back(page)
                emit(info, "ready", values=values)
                print("  filled. Check it in the app and click Save issue (or click Save in Chrome). 's' + Enter skips, 'q' + Enter stops.")
                outcome, note = wait_for_review(page, info, plan), "; ".join(problems)
                changed = sorted(plan.get("_overrides", ()))
                if changed:
                    note = (note + "; " if note else "") + "Changed by hand: " + ", ".join(f.replace("_", " ") for f in changed)
                if isinstance(outcome, tuple):
                    outcome, note = outcome[0], "Declined: " + (outcome[1] or "no note") + (note[note.index("Changed by hand"):].join([" (", ")"]) if "Changed by hand" in note else "")
                    print("  " + note)
                if outcome == "q":
                    break
                if outcome not in ("saved", "declined"):
                    outcome = "skipped"
                else:
                    issue_id = find_issue_id(page)
                emit(info, outcome, values=values)   # the last values stay on screen while the next issue loads
            if outcome == "saved":
                channels.saved(channel_now)
                ledger_append({"date": today(), "timestamp": datetime.now().isoformat(timespec="seconds"), "chain": args.client,
                               "platform": args.platform, "channel": row["OTA_name"], "brand_code": row["brand_code"],
                               "key": row_key(row) + suffix, "issue_id": issue_id, "results_file": args.csv.name,
                               "subscription_id": subscription_id(row)})
            log.writerow({"timestamp": datetime.now().isoformat(timespec="seconds"), "key": row_key(row) + suffix,
                          "OTA_name": row["OTA_name"], "brand_code": row["brand_code"], "from_date": row["from_date"],
                          "subscription_id": subscription_id(row), "hotel_name": row["hotel_name"],
                          "outcome": outcome, "note": note, "client": args.client, "sheet_url": args.sheet,
                          "issue_id": issue_id, "base_rate": plan["base_shop_rate"], "channel_rate": plan["channel_shop_rate"],
                          "base_cancellation": cancellation_text(plan["base_cancellation"]),
                          "channel_cancellation": cancellation_text(plan["channel_cancellation"]),
                          "platform": args.platform})
            logf.flush()
            print(f"  {outcome}")
        if len(ctx.pages) > 1:
            page.close()  # do not leave a tab behind for every run
    for ch, n in sorted(channels.left_out.items()):
        print(f"{n} {ch} row{'s' if n != 1 else ''} left out because {ch} is full for today; still available for Mobile App "
              f"(listed in {left_out_path(args.csv).name})")
    try:
        counts = {}
        for r in read_log(log_path):
            if r.get("timestamp", "") >= started:
                counts[r.get("outcome", "")] = counts.get(r.get("outcome", ""), 0) + 1
        print("Summary: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) if counts else "Summary: nothing was saved or declined")
    except OSError:
        pass


if __name__ == "__main__":
    main()
