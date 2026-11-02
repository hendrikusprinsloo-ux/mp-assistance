#!/usr/bin/env python3
"""Put the Mobile App phone screenshots into the Google Drive folder for the day, through the tool's Chrome.

Usage:
  python mp_drive.py --day YYYY-MM-DD [--dry-run] [--chrome http://127.0.0.1:9222] FILE [FILE ...]

The Drive folder is PARENT / <year> / <Month> / <D Month>, for example `2026 / October / 29 October`. Each level is found by
name and created when it is missing. The files are then uploaded into the day folder through Drive's own page, using the Google
sign-in of the tool's Chrome (no API keys). With --dry-run nothing is created or uploaded: it only reports what it found.
Prints one `RESULT {json}` line: {"folder_url", "created": [...], "uploaded": [...], "skipped": [...]}.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

PARENT_ID = "10JLWtYDCuxSXEPia_gZLNmVWDuQDW6N4"          # Choice Mobile APP screenshots
FOLDER_URL = "https://drive.google.com/drive/folders/{}"

# the entries of the folder on screen: Drive puts the file id on each row/tile and the name in its aria-label or tooltip
LIST_JS = """() => {
  const seen = new Map();
  for (const el of document.querySelectorAll('[data-id]')) {
    const id = el.getAttribute('data-id');
    if (!id || id.length < 15 || seen.has(id)) continue;
    const named = el.matches('[aria-label]') ? el : el.querySelector('[aria-label], [data-tooltip]');
    let name = '';
    const lab = el.getAttribute('aria-label') || (named && (named.getAttribute('aria-label') || named.getAttribute('data-tooltip'))) || '';
    name = lab;
    if (!name) { const t = el.querySelector('[data-tooltip]'); name = t ? t.getAttribute('data-tooltip') : ''; }
    const text = (el.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
    seen.set(id, {id, label: name, text: text.slice(0, 3)});
  }
  return [...seen.values()];
}"""


def day_names(day):
    """(year, month, day) folder names, in the format of the existing folders."""
    return str(day.year), day.strftime("%B"), f"{day.day} {day.strftime('%B')}"


def entry_matches(entry, name):
    """True when a listed entry is the folder or file called `name` (Drive's labels add the type, e.g. 'October Google Drive Folder')."""
    candidates = [entry.get("label", "")] + entry.get("text", [])
    for c in candidates:
        c = c.strip()
        if c == name or c.startswith(name + " ") and ("Folder" in c or "folder" in c or "Image" in c or "image" in c or "PNG" in c):
            return True
    return False


class DriveError(Exception):
    pass


class Drive:
    def __init__(self, page):
        self.page = page

    def open(self, folder_id):
        for attempt in range(3):                        # a new tab can still be loading its blank page and interrupt the first goto
            try:
                self.page.goto(FOLDER_URL.format(folder_id), wait_until="domcontentloaded")
                break
            except Exception as e:
                if attempt == 2 or "interrupted by another navigation" not in str(e):
                    raise
                self.page.wait_for_timeout(1000)
        self.page.wait_for_timeout(1500)
        if "accounts.google.com" in self.page.url or "ServiceLogin" in self.page.url:
            raise DriveError("Not signed in to Google in the tool's Chrome. Sign in to Google there and try again.")
        try:
            self.page.wait_for_selector("[data-id]", timeout=12000)
        except Exception:
            pass                                        # an empty folder has nothing to wait for
        self.page.wait_for_timeout(1000)
        if "Sorry, the file you have requested does not exist" in self.page.inner_text("body")[:2000]:
            raise DriveError("Drive says that folder does not exist or this Google account cannot open it.")

    def entries(self):
        return [e for e in self.page.evaluate(LIST_JS) if e["id"] != PARENT_ID]

    def find(self, name):
        for e in self.entries():
            if entry_matches(e, name):
                return e["id"]
        return None

    def current_id(self):
        m = re.search(r"/folders/([\w-]+)", self.page.url)
        return m.group(1) if m else ""

    def new_folder(self, name):
        """Create a folder in the folder that is open, and return its id."""
        before = {e["id"] for e in self.entries()}
        self.page.keyboard.press("Escape")
        self.page.get_by_role("button", name=re.compile(r"^New$")).first.click()
        self.page.get_by_role("menuitem", name=re.compile(r"^New folder")).first.click()
        dialog = self.page.get_by_role("dialog").filter(has=self.page.locator("input")).last   # the name box of the New folder dialog
        dialog.wait_for(timeout=10000)
        box = dialog.locator("input").first
        box.click()
        box.fill("")
        self.page.keyboard.type(name, delay=30)          # typed like a person, so the page registers the new name
        if box.input_value().strip() != name:
            raise DriveError(f"Could not type the folder name {name!r} into Drive's New folder box (it holds {box.input_value()!r}).")
        dialog.get_by_role("button", name=re.compile(r"^Create")).click()
        self.page.wait_for_timeout(2500)
        for _ in range(10):
            found = [e for e in self.entries() if e["id"] not in before and entry_matches(e, name)]
            if found:
                return found[0]["id"]
            self.page.wait_for_timeout(1000)
        listed = ", ".join(e["text"][0] for e in self.entries() if e["text"])
        raise DriveError(f"Created a folder for {name!r} but could not find it by that name afterwards. The folder shows: {listed}")

    def upload(self, path):
        with self.page.expect_file_chooser(timeout=15000) as chooser:
            self.page.get_by_role("button", name=re.compile(r"^New$")).first.click()
            self.page.get_by_role("menuitem", name=re.compile(r"^File upload")).first.click()
        chooser.value.set_files(str(path))
        for _ in range(60):                             # up to a minute for the upload to land in the list
            self.page.wait_for_timeout(1000)
            if self.find(Path(path).name):
                return True
        return False


def ensure_path(drive, day, create):
    """Walk (and create) PARENT / year / month / day. Returns (day folder id or None, names created)."""
    created, current = [], PARENT_ID
    for name in day_names(day):
        drive.open(current)
        found = drive.find(name)
        if found is None:
            if not create:
                return None, created
            drive.open(current)
            found = drive.new_folder(name)
            created.append(name)
        current = found
    return current, created


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--day", default=date.today().isoformat())
    ap.add_argument("--chrome", default="http://127.0.0.1:9222")
    ap.add_argument("--dry-run", action="store_true", help="only look: create and upload nothing")
    ap.add_argument("--probe", action="store_true", help="print what the parent folder shows on screen, for debugging")
    args = ap.parse_args()
    day = date.fromisoformat(args.day)
    files = [Path(f) for f in args.files]
    for f in files:
        if not f.is_file() or f.stat().st_size == 0:
            sys.exit(f"ERROR The file {f} is missing or empty")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.connect_over_cdp(args.chrome).contexts[0]
        except Exception:
            sys.exit("ERROR Could not reach the tool's Chrome. Start it from the app (Open Chrome for the tool) and try again.")
        page = ctx.new_page()
        try:
            drive = Drive(page)
            if args.probe:
                drive.open(PARENT_ID)
                print(json.dumps({"url": page.url, "title": page.title(), "entries": drive.entries()}, indent=1))
                return
            folder_id, created = ensure_path(drive, day, create=not args.dry_run)
            names = "/".join(day_names(day))
            if folder_id is None:
                print(f"Dry run: the folder {names} does not exist yet; it would be created.")
                print("RESULT " + json.dumps({"folder_url": None, "created": [], "uploaded": [], "skipped": [], "would_create": True}))
                return
            drive.open(folder_id)
            print(f"Drive folder {names}: {FOLDER_URL.format(folder_id)}" + (f" (created {', '.join(created)})" if created else ""))
            uploaded, skipped = [], []
            for f in files:
                if drive.find(f.name):
                    skipped.append(f.name)
                    print(f"  already there: {f.name}")
                elif args.dry_run:
                    print(f"  would upload: {f.name}")
                elif drive.upload(f):
                    uploaded.append(f.name)
                    print(f"  uploaded: {f.name}")
                else:
                    raise DriveError(f"{f.name} did not show up in the folder after uploading")
            print("RESULT " + json.dumps({"folder_url": FOLDER_URL.format(folder_id), "created": created,
                                          "uploaded": uploaded, "skipped": skipped}))
        except DriveError as e:
            sys.exit(f"ERROR {e}")
        finally:
            page.close()


if __name__ == "__main__":
    main()
