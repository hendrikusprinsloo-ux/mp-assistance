#!/usr/bin/env python3
"""Local web UI for mp_upload.py. Standard library only.

  .venv/bin/python server.py        then open http://127.0.0.1:8765
"""
import csv
import getpass
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date, timedelta
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse, urlsplit

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import mp_review  # noqa: E402
import mp_update  # noqa: E402
import mp_upload  # noqa: E402  (its playwright import is lazy, so this is cheap)
HOST, PORT = "127.0.0.1", int(os.environ.get("MP_PORT", "8765"))   # MP_PORT can move the app to another port
RUNS_DIR = Path.home() / "Desktop" / "parity_scraper_screenshots"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_PROFILE = Path.home() / "chrome-mp-profile"
CHROME_URL = "http://127.0.0.1:9222"
LOGIN_URL = "https://paritymanager.mylighthouse.com/admin/"
ISSUE_URL = "https://paritymanager.mylighthouse.com/admin/parity_manager/adminpromotionparityissue/{}/change/"
UI_URL = f"http://{HOST}:{PORT}"
SETTINGS = HERE / "settings.json"

lock = threading.Lock()
log = []        # output lines of the current/last run
run_proc = None


def alive(proc):
    return proc is not None and proc.poll() is None


def add_log(line):
    with lock:
        log.append(line.rstrip("\n"))


run_chain = ""     # the chain the current run is for
run_state = None   # what the running issue is doing, as the upload tool last reported it (None when nothing is running)
STATE_PREFIX = "@@STATE "


def pump(proc):
    global run_state
    for line in proc.stdout:
        if line.startswith(STATE_PREFIX):      # a status report for the page, not something for the log
            try:
                run_state = json.loads(line[len(STATE_PREFIX):])
            except ValueError:
                pass
        else:
            add_log(line)
    proc.wait()
    run_state = None
    add_log(f"--- finished (exit code {proc.returncode}) ---")


def load_settings():
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def save_theme(opts):
    theme = opts.get("theme")
    if theme not in ("dark", "light"):
        return {"error": "Unknown theme"}, 400
    settings = load_settings()
    settings["theme"] = theme
    save_settings(settings)
    return {"ok": True}, 200


CSV_TYPES = '{"public.comma-separated-values-text", "csv"}'
PHOTO_TYPES = '{"public.jpeg", "public.png", "public.heic", "jpg", "jpeg", "png", "heic"}'
PICKS = {   # kind -> (prompt, file types, folder the dialog opens in)
    "results": ("Choose the results CSV", CSV_TYPES, None),
    "done": ("Choose the done file of a run (or its results CSV)", CSV_TYPES, None),
    "qacache": ("Choose a QA cache (qa-cache_….csv) of issues already QAed", CSV_TYPES, None),
    "photo": ("Choose the phone screenshot (JPEG or PNG)", PHOTO_TYPES, Path.home() / "Downloads"),   # AirDrop lands in Downloads
}


def pick_file(kind):
    """Native macOS file dialog (Finder-style). Blocks until the user chooses or cancels. Returns the chosen path or None."""
    prompt, types, folder = PICKS.get(kind, PICKS["results"])
    start = folder if folder and folder.exists() else RUNS_DIR if RUNS_DIR.exists() else Path.home() / "Desktop"
    script = (
        'tell current application to activate\n'
        f'set f to choose file with prompt "{prompt}" default location POSIX file "{start}" of type {types}\n'
        'POSIX path of f')
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return None, None
    path = res.stdout.strip()
    if res.returncode != 0 or not path:
        return None, (None if "-128" in res.stderr else (res.stderr.strip() or "File dialog failed"))   # -128 = cancelled
    return path, None


def pick_csv(opts):
    path, error = pick_file(opts.get("kind"))
    if error:
        return {"error": error}, 500
    if path is None:
        return {"cancelled": True}, 200
    if not path.lower().endswith(".csv"):
        return {"error": "Please choose a .csv file"}, 400
    return {"path": path}, 200


CHAINS = ["Choice", "Best Western", "Wyndham"]
# Salesforce account ids of the chains, as listed in Parity Manager's "By chain" filter on the Mobile Parity Issues page
SF_ACCOUNTS = {"Choice": "001Qu00000y9D5BIAU", "Best Western": "0010O00001wxQ9PQAU", "Wyndham": "0010O00001wxQ9zQAE"}
APP_CHAIN = "Choice"   # Mobile App screenshots are only taken for Choice
DEFAULT_CAPS = {"Choice": {"web": 36, "app": 2}, "Best Western": {"web": 10, "app": 0}, "Wyndham": {"web": 50, "app": 0}}
CHANNEL_NAMES = {"bookingdotcom": "Booking.com", "expedia": "Expedia"}
WEB_CHANNELS = {"priceline": "Priceline", "bookingdotcom": "Booking.com", "expedia": "Expedia"}   # the channels web issues are raised for
# per-channel web limits for each chain: Choice's scraper gives 12 of each; 0 means no limit for that channel
DEFAULT_CHANNEL_CAPS = {"Choice": {"priceline": 12, "bookingdotcom": 12, "expedia": 12},
                        "Best Western": {"priceline": 0, "bookingdotcom": 0, "expedia": 0},
                        "Wyndham": {"priceline": 0, "bookingdotcom": 0, "expedia": 0}}


def current_chain():
    chain = load_settings().get("chain")
    return chain if chain in CHAINS else CHAINS[0]


def save_settings(settings):
    SETTINGS.write_text(json.dumps(settings, indent=2))


def chain_caps(chain):
    saved = load_settings().get("caps", {}).get(chain, {})
    caps = {k: max(0, int(saved.get(k, DEFAULT_CAPS[chain][k]))) for k in ("web", "app")}
    mine = saved.get("channels", {})
    caps["channels"] = {c: max(0, int(mine.get(c, DEFAULT_CHANNEL_CAPS[chain][c]))) for c in WEB_CHANNELS}
    return caps


def usage(chain):
    """What this chain has saved today (from the ledger kept with the app): counts, and the brand codes already used."""
    used = {"web": 0, "app": 0, "app_by_channel": {}, "web_by_channel": {}}
    brands = set()
    for r in mp_upload.ledger_read():
        if r.get("date") != mp_upload.today() or r.get("chain") != chain:
            continue
        platform = "app" if r.get("platform") == "app" else "web"
        used[platform] += 1
        if platform == "web":
            used["web_by_channel"][r.get("channel", "")] = used["web_by_channel"].get(r.get("channel", ""), 0) + 1
        if platform == "app":
            used["app_by_channel"][r.get("channel", "")] = used["app_by_channel"].get(r.get("channel", ""), 0) + 1
        brands.add(r.get("brand_code", "").strip().lower())
    return used, brands


DASHBOARD = "https://paritymanager.mylighthouse.com/admin/parity_manager/adminpromotionparityissue/"
DASH_TTL = 15                       # seconds a reading of the dashboard stays fresh
dash = {}                           # chain -> latest reading {day, at, count, issues, error}
dash_busy = set()


def dashboard_url(chain, day=None):
    """Today's Mobile Parity Issues for one chain: extract date from today up to tomorrow, filtered to the chain's account."""
    day = day or date.today()
    return (f"{DASHBOARD}?extract_date__gte={day.isoformat()}&extract_date__lt={(day + timedelta(days=1)).isoformat()}"
            f"&salesforce_account_id={SF_ACCOUNTS[chain]}")


def read_dashboard(chain, day):
    """One reading of a chain's dashboard for one day, through the tool's Chrome: {count, issues, error}."""
    out = {"count": None, "issues": [], "error": ""}
    if not chrome_up():
        out["error"] = "The tool's Chrome is not running"
        return out
    try:
        res = subprocess.run([sys.executable, str(HERE / "mp_dashboard.py"), dashboard_url(chain, day), "--chrome", CHROME_URL],
                             cwd=HERE, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        out["error"] = "The dashboard took too long to answer"
        return out
    reply = next((l for l in res.stdout.splitlines() if l.startswith("RESULT ")), None)
    if reply:
        data = json.loads(reply[len("RESULT "):])
        out.update(count=data["count"], issues=data["issues"])
    else:
        out["error"] = next((l[len("ERROR "):] for l in reversed(res.stderr.splitlines()) if l.startswith("ERROR ")),
                            "The dashboard could not be read")
    return out


def fetch_dashboard(chain):
    """Today's confirmed issues for this chain, asked of Parity Manager and kept (the last good reading survives a failed refresh)."""
    today_text, previous = mp_upload.today(), dash.get(chain)
    snap = {"day": today_text, "at": time.time(), **read_dashboard(chain, date.today())}
    if snap["count"] is None and previous and previous["day"] == today_text and previous["count"] is not None:
        snap.update(count=previous["count"], issues=previous["issues"], at=previous["at"])
    dash[chain] = snap
    return snap


def dashboard_for(chain, wait=False):
    """The latest reading of the dashboard. Stale readings are refreshed in the background, or right now when wait is set."""
    snap = dash.get(chain)
    stale = snap is None or snap["day"] != mp_upload.today() or time.time() - snap["at"] > DASH_TTL
    if stale and wait:
        return fetch_dashboard(chain)
    if stale and chain not in dash_busy:
        dash_busy.add(chain)
        threading.Thread(target=lambda: (fetch_dashboard(chain), dash_busy.discard(chain)), daemon=True).start()
    return snap


def existing_pairs_file(chain, stem):
    """The (subscription id, channel) pairs the dashboard already shows for today, for the upload tool to skip."""
    snap = dashboard_for(chain, wait=True)
    path = GEO_DIR / f"existing_{stem}.json"
    path.write_text(json.dumps([[i["subscription_id"], i["channel"]] for i in (snap["issues"] if snap else [])]))
    return path


IGNORE_CAP = {"on": False}      # the "Ignore limits" button: kept in memory only, so every start begins with the limits on


def set_ignore_cap(opts):
    IGNORE_CAP["on"] = bool(opts.get("on"))
    return {"ok": True, "ignore_cap": IGNORE_CAP["on"]}, 200


def limits_for(chain, fresh=False):
    """Limits and today's use. The dashboard's confirmed count is the truth for the total (it sees everyone's issues);
    this computer's ledger fills in when the dashboard cannot be read, and tells Mobile App issues apart from the rest."""
    caps, (used, _) = chain_caps(chain), usage(chain)
    snap = dashboard_for(chain, wait=fresh)
    confirmed = snap["count"] if snap and snap["count"] is not None else None
    total_cap = caps["web"] + caps["app"]
    used_total = confirmed if confirmed is not None else used["web"] + used["app"]
    app_open = max(caps["app"] - used["app"], 0) if chain == APP_CHAIN else 0   # Mobile App slots still to be filled stay reserved
    web_used = max(used_total - used["app"], 0)
    on_dash = {}
    for i in (snap["issues"] if snap else []):
        on_dash[i["channel"]] = on_dash.get(i["channel"], 0) + 1
    channels = {}
    for ch, cap in caps["channels"].items():       # web issues per channel: the dashboard sees everyone's, less the Mobile App ones
        got = max(on_dash.get(ch, 0) - used["app_by_channel"].get(ch, 0), 0) if confirmed is not None else used["web_by_channel"].get(ch, 0)
        channels[ch] = {"name": WEB_CHANNELS[ch], "cap": cap, "used": got, "remaining": (cap - got) if cap else None}
    return {"chain": chain, "channels": channels, "caps": caps, "used": {**used, "web": web_used}, "app_per_channel": caps["app"] // len(mp_upload.APP_CHANNELS),
            "app_allowed": chain == APP_CHAIN and caps["app"] > 0, "total_cap": total_cap, "used_total": used_total,
            "web_remaining": total_cap - used_total - app_open, "app_total_remaining": total_cap - used_total,
            "over": used_total > total_cap, "ignore_cap": IGNORE_CAP["on"], "source": "dashboard" if confirmed is not None else "this computer",
            "checked_at": time.strftime("%H:%M", time.localtime(snap["at"])) if snap and confirmed is not None else "",
            "dashboard_error": snap["error"] if snap else "", "dashboard_url": dashboard_url(chain),
            "issues": snap["issues"] if snap else []}


def save_chain(opts):
    if opts.get("chain") not in CHAINS:
        return {"error": "Unknown chain"}, 400
    settings = load_settings()
    settings["chain"] = opts["chain"]
    save_settings(settings)
    return {"ok": True}, 200


def save_limits(opts):
    chain = opts.get("chain")
    if chain not in CHAINS:
        return {"error": "Unknown chain"}, 400
    settings = load_settings()
    mine = settings.setdefault("caps", {}).setdefault(chain, {})
    for key in ("web", "app"):
        if key in opts:
            try:
                value = int(opts[key])
            except (TypeError, ValueError):
                return {"error": "Limits must be whole numbers"}, 400
            if not 0 <= value <= 999:
                return {"error": "Limits must be between 0 and 999"}, 400
            mine[key] = value
    if isinstance(opts.get("channels"), dict):
        theirs = mine.setdefault("channels", {})
        for ch, value in opts["channels"].items():
            if ch not in WEB_CHANNELS:
                continue
            try:
                value = int(value)
            except (TypeError, ValueError):
                return {"error": "Limits must be whole numbers"}, 400
            if not 0 <= value <= 999:
                return {"error": "Limits must be between 0 and 999"}, 400
            theirs[ch] = value
    save_settings(settings)
    return limits_for(chain), 200


def qaed_issue_ids(paths):
    """Issue ids marked OK in the given qa-cache files (an issue marked Problem is left in, to be looked at again)."""
    ids = set()
    for p in paths:
        try:
            with open(p, newline="", encoding="utf-8-sig") as f:
                ids |= {r["issue_id"] for r in csv.DictReader(f) if r.get("issue_id") and r.get("qa_status") == "OK"}
        except (OSError, KeyError):
            raise ValueError(f"Could not read {Path(p).name} as a QA cache")
    return ids


def qa_dashboard(opts):
    """Pull a day's confirmed issues for a chain from the dashboard into a done-style file, so QA can review them."""
    chain = opts.get("chain")
    if chain not in CHAINS:
        return {"error": "Choose a chain first"}, 400
    try:
        day = date.fromisoformat(str(opts.get("day") or mp_upload.today()))
    except ValueError:
        return {"error": "Pick a valid date"}, 400
    got = read_dashboard(chain, day)
    if got["error"]:
        return {"error": got["error"]}, 502
    issues = [i for i in got["issues"] if i.get("issue_id")]   # the subscription id link is what carries the issue id
    try:
        qaed = qaed_issue_ids([str(p) for p in opts.get("skip") or []])
    except ValueError as e:
        return {"error": str(e)}, 400
    skipped = sum(1 for i in issues if i["issue_id"] in qaed)
    issues = [i for i in issues if i["issue_id"] not in qaed]
    if not issues and skipped:
        return {"error": f"All {skipped} confirmed issues for {chain} are already QAed in the cache file(s)."}, 404
    if not issues:
        return {"error": f"The dashboard shows no confirmed issues for {chain} on {day.isoformat()}."}, 404
    folder = HERE / "qa_from_dashboard"
    folder.mkdir(exist_ok=True)
    path = folder / f"done_dashboard_{re.sub(r'[^a-z0-9]+', '-', chain.lower()).strip('-')}_{day.isoformat()}.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, mp_upload.LOG_FIELDS)
        w.writeheader()
        for issue in issues:
            w.writerow({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "key": f"dashboard|{issue['issue_id']}",
                        "OTA_name": issue["channel"], "brand_code": issue["subscription_id"],
                        "from_date": issue.get("extract_date") or day.isoformat(), "subscription_id": issue["subscription_id"],
                        "outcome": "saved", "client": chain, "issue_id": issue["issue_id"], "platform": "?"})
    return {"path": str(path), "count": len(issues), "day": day.isoformat(), "confirmed": got["count"], "skipped": skipped}, 200


def resolve_done(arg):
    """The done log for what was chosen: a done file itself, or a results CSV whose done log sits next to it."""
    path = Path(arg)
    if path.suffix.lower() != ".csv" or not path.is_file():
        return None
    if path.name.startswith("done_"):
        return path
    done = path.with_name(f"done_{path.stem}.csv")
    return done if done.is_file() else None


def run_stem(done):
    return done.stem[len("done_"):] if done.stem.startswith("done_") else done.stem


def review_log_path(done):
    return done.with_name(f"review_{run_stem(done)}.csv")


REVIEW_FIELDS = ["timestamp", "key", "status", "note", "check", "hotel", "issue_values"]


def migrate_review_log(path):
    """Review logs written before the check column existed get it added, keeping their rows."""
    if not path.is_file() or path.stat().st_size == 0:
        return
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    if rows[0] == REVIEW_FIELDS:
        return
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(REVIEW_FIELDS)
        for r in rows[1:]:
            w.writerow((r + [""] * len(REVIEW_FIELDS))[:len(REVIEW_FIELDS)])


def review_marks(done):
    """Latest review mark per issue key."""
    path = review_log_path(done)
    if not path.is_file():
        return {}
    with open(path, newline="") as f:
        return {r["key"]: r for r in csv.DictReader(f) if r.get("key")}


def review_items(arg):
    """The saved issues of a run, with expected values and any QA mark, all from its done log."""
    done = resolve_done(arg)
    if done is None:
        return []
    marks = review_marks(done)
    items = []
    for key, entry in mp_upload.load_done_entries(done).items():
        mark = marks.get(key, {})
        items.append({
            "key": key, "hotel_name": entry.get("hotel_name", ""), "OTA_name": entry.get("OTA_name", ""),
            "brand_code": entry.get("brand_code", ""), "from_date": mp_upload.normalize_date(entry.get("from_date", "")),
            "issue_id": entry.get("issue_id", ""), "subscription_id": entry.get("subscription_id", ""),
            "review": mark.get("status", ""), "note": mark.get("note", ""),
            "expected": [{"field": label, "expected": exp} for label, _, exp, _ in mp_review.expected_checks(entry)]})
    return items


def qa_progress(arg):
    items = review_items(arg)
    return {"total": len(items), "reviewed": sum(1 for i in items if i["review"]),
            "pending": [i["brand_code"] for i in items if not i["review"]]}


QA_FIELDS = ["client", "brand_code", "hotel_name", "channel", "arrival_date", "subscription_id", "issue_id", "issue_url",
             "base_rate", "channel_rate", "base_cancellation", "channel_cancellation", "platform",
             "qa_status", "qa_note", "qa_field_check", "qa_at"]
CACHE_FIELDS = ["key", "qa_by", "qa_at", "client", "brand_code", "hotel_name", "channel", "arrival_date", "subscription_id", "issue_id",
                "issue_url", "qa_status", "qa_note", "qa_field_check"]


def qa_text(done):
    """(CSV text of every saved issue with its QA outcome, how many issues are still unmarked)."""
    marks = review_marks(done)
    pending = 0
    out = io.StringIO()
    w = csv.DictWriter(out, QA_FIELDS)
    w.writeheader()
    for key, entry in mp_upload.load_done_entries(done).items():
        mark = marks.get(key)
        pending += mark is None
        issue_id = entry.get("issue_id", "")
        try:
            seen = json.loads((mark or {}).get("issue_values") or "{}")      # read from the issue's own page when it was marked
        except ValueError:
            seen = {}
        w.writerow({
            "client": entry.get("client", ""), "brand_code": entry.get("brand_code", ""),
            "hotel_name": entry.get("hotel_name") or (mark or {}).get("hotel", ""), "channel": entry.get("OTA_name", ""),
            "arrival_date": mp_upload.normalize_date(entry.get("from_date", "")), "subscription_id": entry.get("subscription_id", ""),
            "issue_id": issue_id, "issue_url": ISSUE_URL.format(issue_id) if issue_id else "",
            "base_rate": entry.get("base_rate") or seen.get("base_rate", ""),
            "channel_rate": entry.get("channel_rate") or seen.get("channel_rate", ""),
            "base_cancellation": entry.get("base_cancellation") or seen.get("base_cancellation", ""),
            "channel_cancellation": entry.get("channel_cancellation") or seen.get("channel_cancellation", ""),
            "platform": {"app": "Mobile App", "web": "Mobile Web"}.get(entry.get("platform", ""), seen.get("platform", "")),
            "qa_status": "Pending" if mark is None else "OK" if mark["status"] == "ok" else "Problem",
            "qa_note": (mark or {}).get("note", ""), "qa_field_check": (mark or {}).get("check") or ("" if mark is None else "not checked"),
            "qa_at": (mark or {}).get("timestamp", "")})
    return out.getvalue(), pending


def qa_paths(done):
    stem = run_stem(done)
    return done.with_name(f"qa_{stem}.csv"), done.with_name(f"COMPLETED_qa_{stem}.csv")


def write_qa_results(done):
    """Keep the QA results file current: qa_<name>.csv while issues remain, COMPLETED_qa_<name>.csv once all are marked.
    Returns the COMPLETED file's path when the QA is complete."""
    text, pending = qa_text(done)
    partial, completed = qa_paths(done)
    try:
        if pending:
            partial.write_text(text, encoding="utf-8-sig")
            return None
        partial.unlink(missing_ok=True)
        completed.write_text(text, encoding="utf-8-sig")
        return completed
    except OSError:
        return None  # the report can still be downloaded, just not saved next to the done file


def qa_cache_path(done):
    """This person's record of the issues they QAed today, next to the other files of the run: qa-cache_<name>.csv."""
    return done.with_name(f"qa-cache_{run_stem(done)}.csv")


def write_qa_cache(done, key):
    """Record this QA mark in the person's cache file. It is kept across fresh starts of the same file (the review log is
    set aside then, the cache is not), with the latest mark per issue replacing an earlier one."""
    mark = review_marks(done).get(key)
    entry = mp_upload.load_done_entries(done).get(key)
    path = qa_cache_path(done)
    rows = {}
    if path.is_file():
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = {r["key"]: r for r in csv.DictReader(f) if r.get("key")}
    if mark and entry:
        issue_id = entry.get("issue_id", "")
        rows[key] = {"key": key, "qa_by": getpass.getuser(), "qa_at": mark["timestamp"], "client": entry.get("client", ""),
                     "brand_code": entry.get("brand_code", ""), "hotel_name": entry.get("hotel_name") or mark.get("hotel", ""),
                     "channel": entry.get("OTA_name", ""), "arrival_date": mp_upload.normalize_date(entry.get("from_date", "")),
                     "subscription_id": entry.get("subscription_id", ""), "issue_id": issue_id,
                     "issue_url": ISSUE_URL.format(issue_id) if issue_id else "",
                     "qa_status": "OK" if mark["status"] == "ok" else "Problem", "qa_note": mark.get("note", ""),
                     "qa_field_check": mark.get("check", "")}
    out = io.StringIO()
    w = csv.DictWriter(out, CACHE_FIELDS)
    w.writeheader()
    for row in sorted(rows.values(), key=lambda r: r["qa_at"]):
        w.writerow(row)
    try:
        path.write_text(out.getvalue(), encoding="utf-8-sig")
    except OSError:
        pass
    return out.getvalue()


def archive_file(path):
    """Set a file aside (renamed with a timestamp) instead of overwriting or deleting it."""
    if path.is_file():
        path.rename(path.with_name(f"{path.stem}.{time.strftime('%Y%m%d-%H%M%S')}{path.suffix}"))


def qa_start(opts):
    """Every file loaded into QA starts fresh: earlier marks and results for it are set aside, not reused."""
    done = resolve_done(str(opts.get("csv", "")))
    if done is None:
        return {"error": "Done file not found"}, 400
    partial, completed = qa_paths(done)
    try:
        archive_file(review_log_path(done))
        archive_file(completed)
        partial.unlink(missing_ok=True)
    except OSError as e:
        return {"error": f"Could not set the earlier QA aside: {e}"}, 500
    return {"ok": True}, 200


GEO_DIR = Path(tempfile.mkdtemp(prefix="mp_geo_"))   # Lighthouse screenshots of the issues being reviewed
GEO_KEEP = 3                                          # issues kept at once, to limit memory and disk use
geo_cache = {}                                        # cache id -> [{file, label, w, h}], oldest first


def geo_images(opts):
    """Lighthouse's own screenshots for one issue, read from its Geoinsight page."""
    key = str(opts.get("key", ""))
    done = resolve_done(str(opts.get("csv", "")))
    if done is None:
        return {"error": "Done file not found"}, 400
    cid = hashlib.sha1(f"{done}\0{key}".encode()).hexdigest()[:16]   # the same key can occur in two different runs
    if cid in geo_cache:
        geo_cache[cid] = geo_cache.pop(cid)           # most recently used goes last
    else:
        result, status = run_review(done, key, "--geo-images", str(GEO_DIR), "--stem", cid, timeout=150)
        if status != 200:
            return result, status
        geo_cache[cid] = result["images"]
        while len(geo_cache) > GEO_KEEP:
            for old in geo_cache.pop(next(iter(geo_cache))):
                (GEO_DIR / old["file"]).unlink(missing_ok=True)
    return {"images": [{"label": i["label"], "w": i["w"], "h": i["h"], "url": f"/api/geo-image?id={cid}&i={n}"}
                       for n, i in enumerate(geo_cache[cid])]}, 200


def review_open(opts, check_only=False):
    done = resolve_done(str(opts.get("csv", "")))
    if done is None:
        return {"error": "Done file not found"}, 400
    return run_review(done, str(opts.get("key", "")), *(["--check-only"] if check_only else []))


def run_review(done_path, key, *flags, timeout=120):
    cmd = [sys.executable, str(HERE / "mp_review.py"), str(done_path), key, "--chrome", CHROME_URL, *flags]
    try:
        res = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": "The issue took too long to read"}, 504
    lines = res.stdout.strip().splitlines()
    result = [l for l in lines if l.startswith("RESULT ")]
    if result:
        return json.loads(result[-1][len("RESULT "):]), 200
    tail = (lines + res.stderr.strip().splitlines())
    error = next((l[len("ERROR "):] for l in reversed(tail) if l.startswith("ERROR ")), None)
    return {"error": error or (tail[-1] if tail else "Review failed")}, 500


def review_mark(opts):
    done = resolve_done(str(opts.get("csv", "")))
    key, status = str(opts.get("key", "")), opts.get("status")
    if done is None or status not in ("ok", "problem") or key not in {i["key"] for i in review_items(str(done))}:
        return {"error": "Bad review mark"}, 400
    path = review_log_path(done)
    migrate_review_log(path)
    new = not path.is_file() or path.stat().st_size == 0
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(REVIEW_FIELDS)
        values = opts.get("values") if isinstance(opts.get("values"), dict) else {}
        w.writerow([time.strftime("%Y-%m-%dT%H:%M:%S"), key, status, str(opts.get("note", ""))[:300],
                    str(opts.get("check", ""))[:400], str(opts.get("hotel", ""))[:120],
                    json.dumps({k: str(v)[:60] for k, v in values.items()})])   # what the issue's own page held when it was marked
    completed = write_qa_results(done)
    write_qa_cache(done, key)
    return {"ok": True, "cache_path": str(qa_cache_path(done)), "completed_path": str(completed) if completed else ""}, 200


def launch_run(cmd, dry_run):
    """Start mp_upload.py as the current run, its output streaming into the log."""
    global run_proc, run_state, run_chain
    if alive(run_proc):
        return {"error": "A run is already in progress"}, 409
    cmd += ["--chrome", CHROME_URL]
    if not dry_run:
        close_login_pages()
    run_state = None
    run_chain = cmd[cmd.index("--client") + 1] if "--client" in cmd else ""
    with lock:
        log.clear()
    add_log("$ " + " ".join(cmd[2:]))
    run_proc = subprocess.Popen(cmd, cwd=HERE, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
    threading.Thread(target=pump, args=(run_proc,), daemon=True).start()
    return {"ok": True}, 200


def start_run(opts):
    csv_path = Path(opts.get("csv", ""))
    if csv_path.suffix.lower() != ".csv" or not csv_path.is_file():
        return {"error": f"CSV not found: {csv_path}"}, 400
    chain = opts.get("chain")
    if chain not in CHAINS:
        return {"error": "Choose a chain first"}, 400
    cmd = [sys.executable, "-u", str(HERE / "mp_upload.py"), str(csv_path), "--client", chain]
    dry_run = bool(opts.get("dry_run"))
    if dry_run:
        cmd.append("--dry-run")
    limit = str(opts.get("limit") or "").strip()
    limit = int(limit) if limit.isdigit() and int(limit) > 0 else None
    if not dry_run and not IGNORE_CAP["on"]:   # a preview is not held to the limit, a real run is (unless the limits are ignored)
        lim = limits_for(chain, fresh=True)       # asks the dashboard now, so other people's issues count too
        if lim["over"]:
            return {"error": f"{chain} already has {lim['used_total']} confirmed issues today, over the limit of {lim['total_cap']}. "
                             "Check the dashboard before adding more."}, 409
        if lim["web_remaining"] <= 0:
            return {"error": f"{chain} has reached today's limit: {lim['used_total']} of {lim['total_cap']} issues confirmed"
                             f"{' (the rest is kept for Mobile App issues)' if lim['caps']['app'] and lim['used_total'] < lim['total_cap'] else ''}. "
                             "Raise the limit under the chain button if more are needed."}, 409
        # every remaining row is loaded, not just as many as the limit leaves room for: an issue can be declined, which frees its place.
        # Save issue still refuses anything that would go over the daily or channel limits.
    if limit:
        cmd += ["--limit", str(limit)]
    cmd += ["--existing", str(existing_pairs_file(chain, csv_path.stem))]
    return launch_run(cmd, dry_run)


# ---------- Mobile App issues (Choice only): the same form with Channel platform = Mobile App
def app_dir(csv_path):
    return csv_path.with_name("mobile_app")   # the converted phone screenshots and the typed rates live beside the results CSV


def app_inputs_path(csv_path):
    return app_dir(csv_path) / f"app_inputs_{csv_path.stem}.json"


def load_app_inputs(csv_path):
    try:
        return json.loads(app_inputs_path(csv_path).read_text())
    except (OSError, ValueError):
        return {}


def save_app_inputs(csv_path, inputs):
    app_dir(csv_path).mkdir(exist_ok=True)
    app_inputs_path(csv_path).write_text(json.dumps(inputs, indent=2))


update_cache = {}


def update_check():
    """The latest release on GitHub against this version (asked once per start; the install uses that same answer)."""
    update_cache["info"] = mp_update.check(version())
    info = update_cache["info"]
    return {k: v for k, v in info.items() if k not in ("release", "asset")}, 200


def update_install():
    info = update_cache.get("info")
    if not info or not info.get("available"):
        return {"error": "There is no update to install. Check for updates first."}, 409
    if alive(run_proc):
        return {"error": "A run is in progress. Stop it before updating."}, 409
    try:
        changed = mp_update.install(info, HERE)
    except Exception as e:
        return {"error": f"The update was not installed: {str(e).splitlines()[0][:160]}"}, 502
    return {"ok": True, "version": info["latest"], "files": len(changed)}, 200



def version():
    try:
        return (HERE / "VERSION").read_text().strip()
    except OSError:
        return ""


def results_csv(arg):
    path = Path(arg)
    return path if path.suffix.lower() == ".csv" and path.is_file() and not path.name.startswith("done_") else None


def app_eligible(csv_path, chain):
    """Rows a Mobile App issue can be raised for: Booking.com or Expedia, lower than brand, and the hotel (brand code)
    has no issue yet today, neither saved for this chain today nor in this file's done file."""
    if chain != APP_CHAIN:
        return {"allowed": False, "message": f"Mobile App issues are only taken for {APP_CHAIN}.", "rows": []}
    # one issue per channel per subscription: a pair is taken if it was saved from this computer today, is in this file's
    # done file, or is on the dashboard (anyone's issue)
    taken = {(r.get("brand_code", "").strip().lower(), r.get("channel", "").strip().lower()) for r in mp_upload.ledger_read()
             if r.get("date") == mp_upload.today() and r.get("chain") == chain}
    done = csv_path.with_name(f"done_{csv_path.stem}.csv")
    if done.is_file():
        try:
            taken |= {(e.get("brand_code", "").strip().lower(), e.get("OTA_name", "").strip().lower())
                      for e in mp_upload.load_done_entries(done).values()}
        except OSError as e:
            return {"allowed": False, "message": f"Could not read {done.name} next to the results file ({e.strerror}). "
                                                 "Check that the app is allowed to read that folder.", "rows": []}
    declined = set()
    if done.is_file():
        declined = {r["key"].split("|app")[0] for r in mp_upload.read_log(done) if r.get("outcome") == "declined"}
    snap = dashboard_for(chain)
    on_dashboard = {(i["subscription_id"], i["channel"]) for i in snap["issues"]} if snap else set()
    inputs, rows, skipped = load_app_inputs(csv_path), [], {}

    def skip(why):
        skipped[why] = skipped.get(why, 0) + 1
    for _, row in mp_upload.load_rows(csv_path):
        if row.get("OTA_name", "").strip().lower() not in mp_upload.APP_CHANNELS:
            continue
        plan, problems = mp_upload.plan_for(row)       # status ok, lower than brand, has its issue link
        channel = row["OTA_name"].strip().lower()
        pair = (row["brand_code"].strip().lower(), channel)
        if plan is None:
            skip(mp_upload.skip_reason(problems))
            continue
        if (mp_upload.subscription_id(row), channel) in on_dashboard:
            skip("already on the dashboard today")
            continue
        if pair in taken:
            skip("already saved today (this computer or this file's done file)")
            continue
        key, saved = mp_upload.row_key(row), inputs.get(mp_upload.row_key(row), {})
        if key in declined:
            skip("declined on the Upload tab")
            continue
        rows.append({"key": key, "hotel_name": row["hotel_name"], "OTA_name": row["OTA_name"].strip().lower(),
                     "brand_code": row["brand_code"], "from_date": mp_upload.normalize_date(row["from_date"]),
                     "base_rate": plan["base_shop_rate"], "web_rate": plan["channel_shop_rate"],
                     "base_shot_missing": not Path(plan["base_screenshot"]).is_file(),
                     "shot": saved.get("shot", ""), "shot_name": saved.get("source", ""), "rate": saved.get("rate", "")})
    done_info = {"name": done.name, "count": len(mp_upload.load_done_entries(done))} if done.is_file() else None
    return {"allowed": True, "rows": rows, "skipped": skipped, "done_file": done_info, **limits_for(chain)}


def app_row(opts):
    """(csv path, eligible row) for a request about one Mobile App row, or an error reply."""
    csv_path = results_csv(str(opts.get("csv", "")))
    if csv_path is None:
        return None, ({"error": "Results CSV not found"}, 400)
    rows = {r["key"]: r for r in app_eligible(csv_path, opts.get("chain", APP_CHAIN))["rows"]}
    row = rows.get(str(opts.get("key", "")))
    if row is None:
        return None, ({"error": "That issue is not available for a Mobile App issue"}, 400)
    return (csv_path, row), None


def app_shot(opts):
    found, error = app_row(opts)
    if error:
        return error
    csv_path, row = found
    path, problem = pick_file("photo")
    if problem:
        return {"error": problem}, 500
    if path is None:
        return {"cancelled": True}, 200
    source = Path(path)
    if source.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        return {"error": "iPhone photos in HEIC format need to be JPEG first. When AirDropping, choose Options > Most Compatible."}, 400
    # the file only needs the .png name: copy it under that name and leave the original alone
    dest = app_dir(csv_path) / f"{row['brand_code'].lower()}_{row['OTA_name']}.png"
    app_dir(csv_path).mkdir(exist_ok=True)
    shutil.copyfile(source, dest)
    inputs = load_app_inputs(csv_path)
    inputs[row["key"]] = {**inputs.get(row["key"], {}), "shot": str(dest), "source": source.name}
    save_app_inputs(csv_path, inputs)
    return {"ok": True, "shot_name": source.name}, 200


def app_rate(opts):
    found, error = app_row(opts)
    if error:
        return error
    csv_path, row = found
    text = str(opts.get("rate", "")).strip().replace(",", ".")
    if text:
        try:
            if float(text) <= 0:
                raise ValueError
        except ValueError:
            return {"error": "Type the rate as a number, for example 76 or 76.50"}, 400
    inputs = load_app_inputs(csv_path)
    inputs[row["key"]] = {**inputs.get(row["key"], {}), "rate": text}
    save_app_inputs(csv_path, inputs)
    return {"ok": True}, 200


LINK_CACHE = {}          # redirect link -> (time, final url); the redirect target does not change within minutes
LINK_TTL = 300


def resolve_redirect(url, hops=5):
    """Follow the Lighthouse redirect link without following it into the OTA site: returns (final url, "") or ("", problem).
    Plain https, no cookies and no Chrome needed."""
    import http.client
    for _ in range(hops):
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return "", "The link in the results file is not a web address."
        conn_class = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        try:
            conn = conn_class(parts.hostname, parts.port, timeout=15)
            try:
                conn.request("GET", (parts.path or "/") + (f"?{parts.query}" if parts.query else ""),
                             headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
                resp = conn.getresponse()
                status, location = resp.status, resp.getheader("Location")
            finally:
                conn.close()
        except (OSError, http.client.HTTPException) as e:
            return "", f"Could not reach the redirect link ({e.__class__.__name__}). Check the internet connection."
        if status not in (301, 302, 303, 307, 308) or not location:
            return "", f"The redirect link did not redirect (answer {status}). Open it in Chrome to see why."
        url = urljoin(url, location)
        if "mylighthouse.com" not in (urlsplit(url).hostname or ""):
            return url, ""
    return "", "The redirect link kept redirecting inside Lighthouse."


def app_link(opts):
    """The page the row's redirect link lands on, and a QR code (SVG) of it, for scanning with a phone."""
    found, error = app_row(opts)
    if error:
        return error
    csv_path, row = found
    source = source_link(csv_path, row["key"])
    if not source:
        return {"error": "This row has no link (url column) in the results file."}, 400
    final, problem = resolve_cached(source)
    if problem:
        return {"error": problem}, 502
    try:
        return {"url": final, "svg": qr_svg(final)}, 200
    except RuntimeError as e:
        return {"error": str(e)}, 500


def source_link(csv_path, key):
    return next((r.get("url", "").strip() for _, r in mp_upload.load_rows(csv_path) if mp_upload.row_key(r) == key), "")


def resolve_cached(source):
    """(final url, problem) with the short cache."""
    cached = LINK_CACHE.get(source)
    if cached and time.time() - cached[0] < LINK_TTL:
        return cached[1], ""
    final, problem = resolve_redirect(source)
    if not problem:
        LINK_CACHE[source] = (time.time(), final)
    return final, problem


def app_links(opts):
    """Checks the redirect link of every listed Mobile App row at once: {key: {"ok": bool, "url" or "error"}}."""
    from concurrent.futures import ThreadPoolExecutor
    csv_path = results_csv(str(opts.get("csv", "")))
    if csv_path is None:
        return {"error": "Results CSV not found"}, 400
    keys = [r["key"] for r in app_eligible(csv_path, opts.get("chain", APP_CHAIN))["rows"]]
    sources = {r_key: source_link(csv_path, r_key) for r_key in keys}

    def check(key):
        if not sources[key]:
            return key, {"ok": False, "error": "no link (url column) in the results file"}
        final, problem = resolve_cached(sources[key])
        return key, ({"ok": False, "error": problem} if problem else {"ok": True, "url": final})
    with ThreadPoolExecutor(max_workers=4) as pool:
        return {"links": dict(pool.map(check, keys))}, 200


def qr_svg(text):
    try:
        import segno
    except ImportError:
        raise RuntimeError("The QR code package is missing. Run: .venv/bin/pip install segno") from None
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=6, border=2, xmldecl=False, svgns=True, nl=False)
    svg = buf.getvalue().decode()
    # segno gives a fixed width and height and no viewBox, so the page cannot scale it: a longer link makes a bigger code
    # and the box crops it. A viewBox lets the code shrink to fit whole.
    return re.sub(r'width="(\d+)" height="(\d+)"', r'viewBox="0 0 \1 \2"', svg, count=1)


def app_drive(opts):
    """Put the phone screenshots of the listed Mobile App rows into today's Google Drive folder (found or created by date)."""
    csv_path = results_csv(str(opts.get("csv", "")))
    if csv_path is None:
        return {"error": "Results CSV not found"}, 400
    if not chrome_up():
        return {"error": "The tool's Chrome is not running. Open it from the Upload tab first."}, 409
    files = sorted({r["shot"] for r in app_eligible(csv_path, opts.get("chain", APP_CHAIN))["rows"]
                    if r["shot"] and Path(r["shot"]).is_file()})
    if not files:
        return {"error": "No phone screenshots to send yet. Choose a phone screenshot for at least one issue first."}, 409
    cmd = [sys.executable, str(HERE / "mp_drive.py"), "--day", mp_upload.today(), *files]
    try:
        res = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"error": "Sending to Google Drive took too long. Check the folder in Drive, then try again."}, 504
    lines = res.stdout.strip().splitlines()
    result = [l for l in lines if l.startswith("RESULT ")]
    if result:
        return json.loads(result[-1][len("RESULT "):]), 200
    tail = lines + res.stderr.strip().splitlines()
    error = next((l[len("ERROR "):] for l in reversed(tail) if l.startswith("ERROR ")), None)
    return {"error": error or (tail[-1] if tail else "Sending to Google Drive failed")}, 500


def app_run(opts):
    csv_path = results_csv(str(opts.get("csv", "")))
    chain = opts.get("chain")
    if csv_path is None:
        return {"error": "Results CSV not found"}, 400
    if chain != APP_CHAIN:
        return {"error": f"Mobile App issues are only taken for {APP_CHAIN}."}, 400
    data = app_eligible(csv_path, chain)
    ready = [r for r in data["rows"] if r["shot"] and r["rate"]]
    if not ready:
        return {"error": "Add a phone screenshot and the rate to at least one issue first."}, 409
    lim = limits_for(chain, fresh=True)       # the dashboard's total, with everyone's issues in it
    if not IGNORE_CAP["on"] and (lim["over"] or lim["app_total_remaining"] < len(ready)):
        return {"error": f"{chain} has {lim['used_total']} of {lim['total_cap']} issues confirmed today, which leaves room for "
                         f"{max(lim['app_total_remaining'], 0)} more but {len(ready)} are ready. Check the dashboard."}, 409
    for channel in ([] if IGNORE_CAP["on"] else mp_upload.APP_CHANNELS):    # the per-channel limit, less what is already saved today
        allowed = data["app_per_channel"] - data["used"]["app_by_channel"].get(channel, 0)
        count = sum(1 for r in ready if r["OTA_name"] == channel)
        if count > max(allowed, 0):
            return {"error": f"{CHANNEL_NAMES[channel]} allows {max(allowed, 0)} more Mobile App issue(s) today, "
                             f"but {count} are ready. Clear the extra ones."}, 409
    inputs = load_app_inputs(csv_path)
    run_file = app_dir(csv_path) / f"run_inputs_{csv_path.stem}.json"
    run_file.write_text(json.dumps({r["key"]: inputs[r["key"]] for r in ready}, indent=2))
    cmd = [sys.executable, "-u", str(HERE / "mp_upload.py"), str(csv_path), "--client", chain,
           "--platform", "app", "--app-inputs", str(run_file), "--existing", str(existing_pairs_file(chain, csv_path.stem))]
    return launch_run(cmd, False)


chrome_state = {"up": False, "misses": 0}


def chrome_probe():
    """One check of Chrome's debugging port. A busy Chrome can be slow to answer, so this waits a while."""
    try:
        urllib.request.urlopen(f"{CHROME_URL}/json/version", timeout=3).close()
        return True
    except OSError:
        return False


def chrome_up():
    """Whether the tool's Chrome is running, as last seen by watch_chrome (so asking is instant and steady)."""
    return chrome_state["up"]


def watch_chrome():
    """Keep chrome_state current. It turns 'not running' only after three failed checks in a row,
    so a Chrome that is busy loading or processing does not flicker the status."""
    while True:
        if chrome_probe():
            chrome_state["up"], chrome_state["misses"] = True, 0
        else:
            chrome_state["misses"] += 1
            if chrome_state["misses"] >= 3:
                chrome_state["up"] = False
        time.sleep(1.5)


def chrome_targets():
    """The pages open in the tool's Chrome, or None when Chrome could not be asked (closed, or too busy to answer)."""
    try:
        with urllib.request.urlopen(f"{CHROME_URL}/json/list", timeout=3) as r:
            return json.load(r)
    except (OSError, ValueError):
        return None


def ui_window_open(targets):
    return any(t.get("type") == "page" and t.get("url", "").startswith(UI_URL) for t in targets or [])


def launch_chrome(*extra):
    # Same profile folder every time: a running tool Chrome takes the arguments over instead of starting another.
    subprocess.Popen([CHROME, "--remote-debugging-port=9222", f"--user-data-dir={CHROME_PROFILE}",
                      "--no-first-run", "--no-default-browser-check", *extra],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_windows():
    """Parity Manager login window plus the tool's own window (an app-style window without tabs or address bar)."""
    launch_chrome("--new-window", LOGIN_URL)
    for _ in range(30):
        if chrome_up():
            break
        time.sleep(0.5)
    targets = chrome_targets()
    if targets is not None and not ui_window_open(targets):   # unknown (Chrome too busy to answer) is not "no window"
        launch_chrome(f"--app={UI_URL}")


def watch_window():
    """Stop the server once the tool's window has been closed (or Chrome has quit)."""
    seen, misses, unreachable = False, 0, 0
    deadline = time.time() + 90
    while True:
        time.sleep(2)
        if not seen and time.time() > deadline:
            print("Tool window never appeared; leaving the server running (Ctrl+C to stop).")
            return
        targets = chrome_targets()
        if targets is None:
            # Chrome could not be asked: it may just be busy. Only a long silence counts as Chrome having quit.
            unreachable += 1
            if seen and unreachable >= 10:  # ~20 s
                print("Chrome is gone, stopping.")
                quit_app()
                return
            continue
        unreachable = 0
        if ui_window_open(targets):
            seen, misses = True, 0
        elif seen:
            misses += 1
            if misses >= 4:  # ~8 s with Chrome answering and no tool window, so a page reload does not count
                print("Tool window closed, stopping.")
                quit_app()
                return


arranged = False


def arrange_windows(opts):
    """Tool window left, Parity Manager right, within the screen area the page reported."""
    global arranged
    if opts.get("auto") and arranged:  # the automatic arrange only happens once per server run
        return {"ok": True, "skipped": True}, 200
    try:
        area = [int(opts[k]) for k in ("left", "top", "width", "height")]
    except (KeyError, TypeError, ValueError):
        return {"error": "Bad screen area"}, 400
    if area[2] < 400 or area[3] < 300:
        return {"error": "Screen area too small"}, 400
    arranged = True
    try:
        res = subprocess.run([sys.executable, str(HERE / "mp_arrange.py"), *map(str, area), "--chrome", CHROME_URL],
                             cwd=HERE, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return {"error": "Arranging the windows timed out"}, 504
    if res.returncode != 0:
        return {"error": (res.stderr.strip().splitlines() or ["Could not arrange the windows"])[-1]}, 500
    return {"ok": True}, 200


def pm_status():
    """Is the tool's Chrome open, and signed in to Parity Manager?"""
    if not chrome_up():
        return {"chrome": False, "signed_in": False}, 200
    try:
        res = subprocess.run([sys.executable, str(HERE / "mp_session.py"), "--chrome", CHROME_URL],
                             cwd=HERE, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return {"chrome": True, "signed_in": False, "error": "The sign-in check timed out"}, 200
    for line in res.stdout.splitlines():
        if line.startswith("RESULT "):
            return {"chrome": True, **json.loads(line[len("RESULT "):])}, 200
    error = next((l[len("ERROR "):] for l in reversed(res.stderr.splitlines()) if l.startswith("ERROR ")), "Sign-in check failed")
    return {"chrome": True, "signed_in": False, "error": error}, 200


def is_login_target(target):
    """The Parity Manager window opened for signing in: the admin home or login page (not an issue or form)."""
    if target.get("type") != "page":
        return False
    url = urlsplit(target.get("url", ""))
    return url.netloc == "paritymanager.mylighthouse.com" and url.path.rstrip("/") in ("/admin", "/admin/login")


def close_login_pages():
    """Close the sign-in window once a run starts; the run opens its own tab. Signing in is not undone by this."""
    for target in chrome_targets() or []:
        if is_login_target(target):
            try:
                urllib.request.urlopen(f"{CHROME_URL}/json/close/{target['id']}", timeout=3).close()
            except OSError:
                pass


def start_chrome():
    if not Path(CHROME).exists():
        return {"error": "Google Chrome not found in /Applications"}, 400
    launch_chrome("--new-window", LOGIN_URL)
    return {"ok": True}, 200


def open_tool_windows():
    if not Path(CHROME).exists():
        return {"error": "Google Chrome not found in /Applications"}, 400
    threading.Thread(target=open_windows, daemon=True).start()
    return {"ok": True}, 200


def send_to_run(text):
    if not (text in ("save", "s", "q") or text.startswith("d:")):   # only what the upload tool understands: save, skip, decline (with a note), stop
        text = None
    if text is None:
        return {"error": "Unknown command"}, 400
    if not alive(run_proc):
        return {"error": "Nothing is running"}, 409
    try:
        run_proc.stdin.write(text + "\n")
        run_proc.stdin.flush()
    except OSError:
        return {"error": "Run already ended"}, 409
    return {"ok": True}, 200


def save_issue():
    """The Save issue button. It asks the dashboard first, so a save can never take a chain over its limit or double up an issue."""
    state = run_state
    if not alive(run_proc) or not state or state.get("phase") not in ("ready", "error"):
        return {"error": "There is no issue ready to save."}, 409
    chain = run_chain
    if chain not in CHAINS:                       # a run from the command line has no chain to check
        return send_to_run("save")
    lim = limits_for(chain, fresh=True)           # a fresh look at the dashboard, not the last reading
    channel = state.get("channel", "").strip().lower()
    note = "" if lim["source"] == "dashboard" else " (the dashboard could not be read, so this is this computer's count)"
    if (state.get("subscription_id", ""), channel) in {(i["subscription_id"], i["channel"]) for i in lim["issues"]}:
        return {"error": f"The dashboard already shows an issue for subscription {state.get('subscription_id')} on "
                         f"{CHANNEL_NAMES.get(channel, channel)}. Only one per channel per subscription can be saved, so this one was "
                         "not saved. Skip it."}, 409
    app = state.get("platform") == "app"
    room = lim["app_total_remaining"] if app else lim["web_remaining"]
    if not IGNORE_CAP["on"] and (lim["over"] or room <= 0):
        if not app and not lim["over"] and lim["used_total"] < lim["total_cap"]:   # the room that is left is for Mobile App issues
            return {"error": f"{chain} has no more room for web issues today: {lim['used_total']} of {lim['total_cap']} are confirmed{note} "
                             "and the rest is kept for Mobile App issues. It was not saved."}, 409
        return {"error": f"Saving this would take {chain} over today's limit: {lim['used_total']} of {lim['total_cap']} issues "
                         f"are confirmed{note}. It was not saved."}, 409
    channel_left = lim["channels"].get(channel, {}).get("remaining")
    if not app and not IGNORE_CAP["on"] and channel_left is not None and channel_left <= 0:
        c = lim["channels"][channel]
        return {"error": f"{c['name']} has reached its limit for {chain}: {c['used']} of {c['cap']} web issues today. It was not saved."}, 409
    if app and not IGNORE_CAP["on"] and lim["used"]["app_by_channel"].get(channel, 0) >= lim["app_per_channel"]:
        return {"error": f"{CHANNEL_NAMES.get(channel, channel)} already has its Mobile App issue for today. It was not saved."}, 409
    return send_to_run("save")


def stop_run():
    if alive(run_proc):
        run_proc.terminate()
    return {"ok": True}, 200


def quit_app():
    stop_run()
    shutil.rmtree(GEO_DIR, ignore_errors=True)
    threading.Thread(target=lambda: (time.sleep(0.3), os._exit(0)), daemon=True).start()
    return {"ok": True}, 200


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, body, status=200, ctype="application/json", headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def local_only(self):
        """Refuse requests from other sites in the browser (DNS rebinding / cross-site POSTs)."""
        host_ok = self.headers.get("Host", "") in (f"{HOST}:{PORT}", f"localhost:{PORT}")
        origin = self.headers.get("Origin")
        origin_ok = origin is None or origin in (f"http://{HOST}:{PORT}", f"http://localhost:{PORT}")
        return host_ok and origin_ok

    def do_GET(self):
        if not self.local_only():
            return self.reply({"error": "forbidden"}, 403)
        url = urlparse(self.path)
        if url.path == "/":
            return self.reply((HERE / "ui.html").read_bytes(), ctype="text/html; charset=utf-8")
        if url.path == "/api/settings":
            return self.reply({"theme": "dark", **load_settings(), "app_mode": "--with-chrome" in sys.argv, "chains": CHAINS, "chain": current_chain(), "app_chain": APP_CHAIN, "sf_accounts": SF_ACCOUNTS, "today": time.strftime("%Y-%m-%d"), "version": version()})
        if url.path == "/api/status":
            since = int(parse_qs(url.query).get("since", ["0"])[0])
            with lock:
                lines, total = log[since:], len(log)
            return self.reply({"running": alive(run_proc), "chrome": chrome_up(), "lines": lines, "total": total, "state": run_state})
        if url.path == "/api/run/image":           # the screenshot of the issue being checked, one of the two files the run uploads
            which = parse_qs(url.query).get("which", [""])[0]
            shot = Path((run_state or {}).get("shots", {}).get(which, "")) if which in ("base", "channel") else None
            if not shot or not shot.is_file() or shot.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                return self.reply({"error": "not found"}, 404)
            return self.reply(shot.read_bytes(), ctype="image/png" if shot.suffix.lower() == ".png" else "image/jpeg",
                              headers={"Cache-Control": "no-store"})
        if url.path == "/api/limits":
            chain = parse_qs(url.query).get("chain", [""])[0]
            return self.reply(limits_for(chain if chain in CHAINS else current_chain(), fresh="fresh" in parse_qs(url.query)))
        if url.path == "/api/app/eligible":
            q = parse_qs(url.query)
            csv_path = results_csv(q.get("csv", [""])[0])
            chain = q.get("chain", [current_chain()])[0]
            if csv_path is None or chain not in CHAINS:
                return self.reply({"allowed": False, "message": "Choose a results CSV first.", "rows": []})
            return self.reply(app_eligible(csv_path, chain))
        if url.path == "/api/pm/status":
            body, status = pm_status()
            return self.reply(body, status)
        if url.path == "/api/review/items":
            return self.reply({"items": review_items(parse_qs(url.query).get("csv", [""])[0])})
        if url.path == "/api/update/check":
            body, status = update_check()
            return self.reply(body, status)
        if url.path == "/api/update/notes":
            return self.reply(mp_update.pending_notes(HERE, version()) or {})
        if url.path == "/api/qa/cache":
            done = resolve_done(parse_qs(url.query).get("csv", [""])[0])
            if done is None or not qa_cache_path(done).is_file():
                return self.reply({"error": "Nothing has been QAed yet"}, 409)
            return self.reply(qa_cache_path(done).read_bytes(), ctype="text/csv; charset=utf-8",
                              headers={"X-Report-Name": qa_cache_path(done).name})
        if url.path == "/api/qa/export":
            arg = parse_qs(url.query).get("csv", [""])[0]
            done = resolve_done(arg)
            text, pending = qa_text(done) if done else ("", 1)
            progress = qa_progress(arg)
            if done is None or not progress["total"] or pending:
                msg = (f"{len(progress['pending'])} of {progress['total']} issues still need QA"
                       if progress["total"] else "There are no saved issues to report on")
                return self.reply({"error": msg}, 409)
            saved = write_qa_results(done)
            return self.reply(("\ufeff" + text).encode("utf-8"), ctype="text/csv; charset=utf-8",
                              headers={"X-Report-Path": str(saved) if saved else "",
                                       "X-Report-Name": qa_paths(done)[1].name})
        if url.path == "/api/geo-image":
            q = parse_qs(url.query)
            try:
                entry = geo_cache[q.get("id", [""])[0]][int(q.get("i", ["0"])[0])]
                return self.reply((GEO_DIR / entry["file"]).read_bytes(), ctype="image/png")
            except (KeyError, IndexError, ValueError, OSError):
                return self.reply({"error": "not found"}, 404)
        self.reply({"error": "not found"}, 404)

    def do_POST(self):
        if not self.local_only() or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.reply({"error": "forbidden"}, 403)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            opts = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self.reply({"error": "bad json"}, 400)
        routes = {
            "/api/run": lambda: start_run(opts),
            "/api/chrome": start_chrome,
            "/api/theme": lambda: save_theme(opts),
            "/api/open": open_tool_windows,
            "/api/arrange": lambda: arrange_windows(opts),
            "/api/pick": lambda: pick_csv(opts),
            "/api/review/open": lambda: review_open(opts),
            "/api/review/check": lambda: review_open(opts, check_only=True),
            "/api/review/geo": lambda: geo_images(opts),
            "/api/review/mark": lambda: review_mark(opts),
            "/api/qa/start": lambda: qa_start(opts),
            "/api/update/install": update_install,
            "/api/update/dismiss": lambda: (mp_update.dismiss_notes(HERE) or ({"ok": True}, 200)),
            "/api/run/save": save_issue,
            "/api/qa/dashboard": lambda: qa_dashboard(opts),
            "/api/chain": lambda: save_chain(opts),
            "/api/limits": lambda: save_limits(opts),
            "/api/ignore-cap": lambda: set_ignore_cap(opts),
            "/api/app/shot": lambda: app_shot(opts),
            "/api/app/rate": lambda: app_rate(opts),
            "/api/app/run": lambda: app_run(opts),
            "/api/app/drive": lambda: app_drive(opts),
            "/api/app/link": lambda: app_link(opts),
            "/api/app/links": lambda: app_links(opts),
            "/api/send": lambda: send_to_run(str(opts.get("text", ""))),
            "/api/stop": stop_run,
            "/api/quit": quit_app,
        }
        handler = routes.get(urlparse(self.path).path)
        if handler is None:
            return self.reply({"error": "not found"}, 404)
        body, status = handler()
        self.reply(body, status)


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"MP Assistance UI: {UI_URL}  (Ctrl+C to stop)")
    chrome_state["up"] = chrome_probe()          # so the very first status is right
    threading.Thread(target=watch_chrome, daemon=True).start()
    if "--with-chrome" in sys.argv:  # app mode: open the tool's Chrome windows, quit when the tool window closes
        threading.Thread(target=open_windows, daemon=True).start()
        threading.Thread(target=watch_window, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop_run()
        shutil.rmtree(GEO_DIR, ignore_errors=True)
