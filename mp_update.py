#!/usr/bin/env python3
"""Check GitHub for a newer release of the app and install it.

The release is a zip built by package.sh and attached to a GitHub release tagged v<version>; the release notes are the changelog.
Downloads are made by Python itself, which (unlike a browser) does not mark files as quarantined by macOS, so an update needs no
`xattr` step. Only code files are replaced: settings, the ledger, QA files and the virtual environment are never touched.
"""
import hashlib
import io
import json
import re
import shutil
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = "hendrikusprinsloo-ux/mp-assistance"        # "owner/name" of the public GitHub repository that holds the releases; empty switches the update check off
API = "https://api.github.com/repos/{}/releases/latest"
USER_AGENT = "MP-Assistance-updater"
MAX_ZIP = 50 * 1024 * 1024
KEEP = {".venv", ".browser-profile", ".claude", ".update_backup", "qa_from_dashboard", "settings.json", "issues_ledger.csv",
        "server.log", "package.sh", ".update_done.json", "tests", "test", "__pycache__"}   # never replaced by an update


def version_tuple(text):
    """'v1.10.2' -> (1, 10, 2); anything that is not a plain dotted number gives None."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    return tuple(int(n) for n in match.group(1).split(".")) if match else None


def newer(latest, current):
    a, b = version_tuple(latest), version_tuple(current)
    return bool(a and b and a > b)


def fetch(url, limit=MAX_ZIP):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        if not resp.geturl().startswith("https://"):
            raise ValueError("The update address is not secure (https)")
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("The download is larger than expected")
    return data


def expected_sha256(release, asset):
    """The checksum GitHub records for the zip, or one published next to it as <zip name>.sha256."""
    digest = (asset.get("digest") or "")
    if digest.startswith("sha256:"):
        return digest[len("sha256:"):].lower()
    for other in release.get("assets", []):
        if other.get("name") == asset["name"] + ".sha256":
            text = fetch(other["browser_download_url"], 4096).decode("utf-8", "replace").strip()
            if re.match(r"[0-9a-fA-F]{64}", text):
                return text[:64].lower()
    return None


def check(current, repo=None, opener=None):
    """What the latest release is: {current, latest, available, notes, url, name, release} or {error}."""
    repo = REPO if repo is None else repo
    opener = opener or fetch
    if not repo:
        return {"current": current, "available": False, "disabled": True}
    try:
        release = json.loads(opener(API.format(repo), 1024 * 1024))
    except Exception as e:
        return {"current": current, "available": False, "error": f"Could not check for updates: {str(e).splitlines()[0][:100]}"}
    latest = release.get("tag_name", "")
    zips = [a for a in release.get("assets", []) if a.get("name", "").lower().endswith(".zip")]
    out = {"current": current, "latest": latest.lstrip("v"), "notes": release.get("body") or "", "release": release}
    out["available"] = newer(latest, current) and bool(zips)
    if out["available"]:
        out["asset"] = zips[0]
    return out


def safe_members(zf):
    """(archive name, relative path inside the app folder) for each file of the zip; refuses paths that climb out of it."""
    names = [i for i in zf.infolist() if not i.is_dir()]
    roots = {i.filename.split("/")[0] for i in names}
    if len(roots) != 1:
        raise ValueError("The update zip does not have the expected layout")
    for info in names:
        rel = Path(*info.filename.split("/")[1:])
        if ".." in rel.parts or Path(info.filename).is_absolute() or not rel.parts:
            raise ValueError("The update zip holds an unsafe path")
        yield info, rel


def apply_zip(data, here, version, notes="", sha256=None):
    """Install the zip's files into the app folder. Returns the list of files replaced. Files it replaces are first copied to
    .update_backup/, and the notes are kept in .update_done.json so the next start can show what changed."""
    if sha256 is None:
        raise ValueError("The release has no checksum, so it was not installed")
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("The download does not match its checksum, so it was not installed")
    here = Path(here)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        members = [(i, rel) for i, rel in safe_members(zf) if rel.parts[0] not in KEEP and rel.name != ".DS_Store"]
        if not any(rel.name == "server.py" for _, rel in members):
            raise ValueError("The update zip does not look like this app")
        backup = here / ".update_backup" / time.strftime("%Y%m%d-%H%M%S")
        changed = []
        for info, rel in members:
            target = here / rel
            if target.is_file():
                (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup / rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
            if info.external_attr >> 16 & 0o111:
                target.chmod(target.stat().st_mode | 0o111)       # launchers stay runnable
            changed.append(str(rel))
    (here / ".update_done.json").write_text(json.dumps({"version": version, "notes": notes, "at": time.strftime("%Y-%m-%d %H:%M")}))
    return changed


def install(release_info, here, opener=None):
    opener = opener or fetch
    asset = release_info["asset"]
    data = opener(asset["browser_download_url"], MAX_ZIP)
    return apply_zip(data, here, release_info["latest"], release_info.get("notes", ""), expected_sha256(release_info["release"], asset))


def auto_update(here, current, quiet=False):
    """Run at launch, before the server starts: install a newer release if there is one, so the app opens on the new code.
    Anything that goes wrong (no internet, no release, a bad checksum) is reported in a line and the current version carries on."""
    say = (lambda *a: None) if quiet else print
    info = check(current)
    if info.get("disabled") or info.get("error"):
        say(info.get("error", ""))
        return False
    if not info["available"]:
        return False
    say(f"Updating MP Assistance {current} -> {info['latest']} ...")
    try:
        changed = install(info, here)
    except Exception as e:
        say(f"Update skipped, carrying on with {current}: {str(e).splitlines()[0][:160]}")
        return False
    say(f"Updated to {info['latest']} ({len(changed)} files).")
    return True


def main():
    here = Path(__file__).resolve().parent
    try:
        current = (here / "VERSION").read_text().strip()
    except OSError:
        return
    auto_update(here, current)


def pending_notes(here, current):
    """The changelog of an update that was installed and has now been restarted into, or None."""
    path = Path(here) / ".update_done.json"
    try:
        done = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return done if done.get("version") == current else None


def dismiss_notes(here):
    (Path(here) / ".update_done.json").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
