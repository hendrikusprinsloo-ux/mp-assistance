# MP Assistance

Fills Parity Manager "Add Mobile Parity Issue" forms from the parity scraper `results_*.csv`, attaches the
screenshots, and lets you check and save each issue from the app. It also raises Mobile App issues (Choice) from your phone
screenshots, and has a QA tab to check what was saved. Version 1.9.0-nightly (see `VERSION`, also shown in the page header).

A results file made on another computer works too: its screenshot paths point at that computer, so the tool looks for the same
file names in the folder next to the CSV. Keep the CSV and its screenshots together.

## UI

Double-click `MP Assistance.app` (or `start.command`). It starts the server in Terminal and opens the tool's own Chrome with
two windows: the Parity Manager login and the tool's control window (no tabs or address bar), so you can put them on separate
screens. Closing the tool window stops the server again. Everything runs through `mp_upload.py` underneath.

To run the server without opening Chrome, use `.venv/bin/python server.py` and open http://127.0.0.1:8765 yourself.
Another copy can run beside it on a different port with `MP_PORT=8766 .venv/bin/python server.py`.

## Starting up

The app always opens on the **Upload** tab. First it waits for you to sign in to Parity Manager: the tool's Chrome opens on the
Parity Manager login, and the page checks every few seconds (without opening anything) and continues by itself once you are signed in.
**Skip for now** gets past it if needed. When a run starts, that sign-in window is closed again, since the run opens its own tab.
Dry runs leave it alone.

Then a popup asks **which chain you are working on** (Choice, Best Western or Wyndham; Choice is the default). It shows that chain's
**daily limit** and how many issues are confirmed today, and the limit can be changed there; the numbers follow the chain you pick.
Defaults: Choice 36 issues plus 2 Mobile App (1 Booking.com and 1 Expedia, 38 in all), Best Western 10, Wyndham 50. Limits are kept
in `settings.json`. The **Mobile App** tab only shows for Choice.

**The dashboard is the record of what is confirmed.** The count comes from the Mobile Parity Issues list in Parity Manager for the
chain and day, read through the tool's Chrome every few seconds, so it includes everyone's issues, not just this computer's.
The button in the top corner has two parts: the chain name (`Choice ▾`) reopens the popup, and the count (`34/38 ↗`) opens that chain's
dashboard for today (tooltip: "Open dashboard…"). If the dashboard cannot be read, the tool falls back to `issues_ledger.csv`, a note it
keeps of what this computer saved today, and says so. If more are confirmed than the limit allows, a red banner appears, the
count turns red, and runs and saves are refused. The room kept for Mobile App issues is not given to Upload runs.

**Decline:** each issue card has a **Decline** button (with an optional reason) in place of Skip. A declined issue is recorded in the done
file as `declined` with its note, and never comes back: not in later runs, not on the Mobile App tab, not in QA. A run loads every
remaining row of the results file rather than stopping at the daily limit (Save issue still enforces the limits), and ends with a
summary of how many were saved and declined. Screenshots start at the top for each new issue.

**QA:** the QA tab loads today's confirmed issues for the chosen chain as soon as it opens (no CSV QA in this version). The issues'
own values are shown for you to confirm against the Lighthouse screenshots. Every mark is also kept in `qa-cache_<name>.csv` next to the
done file (your computer's username, the time and your result per issue), with a **Download my QA cache** button. **Skip issues from a QA
cache…** takes someone else's cache file and leaves out the issues they marked OK.

**Limits per channel:** the popup also has a web limit for each of Priceline, Booking.com and Expedia, per chain (0 = no limit for
that channel). Choice starts at 12 each; Best Western and Wyndham start with none. A channel's count is the dashboard's count for
it less its Mobile App issues (this computer's count if the dashboard cannot be read). A run stops taking a channel once it is full
(the log says "<channel> limit reached"), and Save issue refuses an issue for a full channel. The limit line shows each channel's count.

**Ignore limits** (button in the top corner, off at every start): for a demo or an exception, runs and saves are no longer held to the
daily limits, and a red banner says so. One issue per channel per subscription still applies. It creates real issues in Parity Manager.

## Windows and theme

The page grows with the window: in full screen or on a big monitor the layout, the text and the screenshot boxes get bigger.
**Click any screenshot** (QA, or the run card on Upload and Mobile App) to open it in an in-app viewer. The arrows (or the left and
right keys) switch to the issue's other screenshot, **+**, **−**, **Fit** and **100%** zoom (keys `+`, `-`, `0`, `1`; clicking the image
flips between fit and actual size), **New window** opens the image on its own, and Esc closes the viewer.

When the app starts it puts the tool window on the left half of the screen and Parity Manager on the right half. **Arrange windows**
does it again at any time. The **Light mode / Dark mode** button in the top corner switches the theme and keeps the choice
in `settings.json`.

## Tabs

The page has three tabs (Upload, Mobile App for Choice, and QA).

**One issue per channel per subscription.** Parity Manager takes only one issue for a given hotel on a given channel, so the tool
skips any row whose hotel and channel already have an issue today: on the dashboard (anyone's), saved from this computer today, or
earlier in the same results file. The same hotel on a different channel is fine.

### Upload

Chrome, the results CSV, and the run.
- A run is held to the chain's remaining daily limit and refuses to start once it is used up (raise it with the top-corner button
  if more are needed); a dry run is not held to it. The limit line shows how much is used and where the count came from, and a
  list shows the issues confirmed on the dashboard today (subscription id, channel, issue id).
- **Run:** each issue appears as a card once its form is filled in Chrome: the values as the form holds them (rates, cancellation,
  channel, channel platform, the files attached) with a tick or cross against what was meant, and both screenshots. If you change
  something in Chrome, the card follows. **Save issue** clicks Parity Manager's own Save button; **Skip this issue** leaves it
  unsaved; **Stop run** stops after leaving the current one unsaved. You can also click Save in Chrome yourself.
- **Save checks the dashboard first.** Before saving it takes a fresh look at the dashboard and refuses, with the reason, if the
  save would take the chain over its limit, if the subscription already has an issue on that channel, or if the channel's Mobile
  App issue for the day is taken. If Parity Manager itself rejects the form, the reason is shown and the screenshots are put back
  (a reload empties them). A save made by clicking Save in Chrome cannot be checked.
- The **Log** block at the bottom has the tool's own output.
- When a run has saved issues, **Go to QA →** shows how many are saved and opens the QA tab on the file chosen on the Upload tab
  (the one you ran, not the latest file in a folder).

### Mobile App (Choice only)

The same form with Channel platform set to Mobile App. Choose a results CSV; the tab lists the Booking.com and Expedia rows that are
lower than brand and have no issue yet today for that hotel on that channel. For each issue you choose the **phone screenshot** in
Finder (JPEG or PNG from AirDrop; a copy is saved with a `.png` name in a `mobile_app` folder next to the results file, and the
original is left alone) and **type the rate** the screenshot shows. The base screenshot and base rate still come from the results
file. A row is ready once it has both. **Upload ready issues** fills the forms, and the run card, Save check and Log work as on Upload.
The Mobile App limit is one Booking.com and one Expedia issue a day (shared out evenly), and the day's total must still have room.
iPhone photos in HEIC format must be JPEG (when AirDropping, choose Options > Most Compatible). QA checks that these issues
really are Mobile App.

**Why rows are missing:** a "Left out" line under the summary counts the rows that were not listed and why (not lower than brand,
scrape status not ok, already on the dashboard, already saved today); Upload runs print the same in the log. If a `done_<name>.csv`
sits next to the results file, a banner says so, because rows saved there are skipped. A ⚠ next to a hotel means its base screenshot
file was not found.

**Send screenshots to Drive** puts the phone screenshots of the listed rows into the Google Drive folder for today's date:
`Choice Mobile APP screenshots / <year> / <Month> / <D Month>` (for example `2026 / October / 29 October`). Each level is found by
name and created if it is missing, so the day folder is made if the scraper has not made it yet. It works through the tool's Chrome,
so that Chrome must be signed in to Google (the same Google account that can open the folder). It needs no API keys. Files keep their
names (for example `ct138_expedia.png`) and one that is already in the folder is skipped, not duplicated. The parent folder's id is
`PARENT_ID` in `mp_drive.py`. `.venv/bin/python mp_drive.py --dry-run --day YYYY-MM-DD FILE` only looks, and changes nothing.

**Check all links** follows every row's redirect link and marks each *QR / link* button ✓ or ✗ (hover the ✗ for the reason).

**Phone link (QR):** each row has a *QR / link* button. It follows the row's Lighthouse redirect link (the `url` column) to the real
Expedia or Booking.com page and shows that page as a QR code to scan with the phone, with *Open page* and *Copy link*. It needs the
internet and the `segno` package (installed automatically by `start.command` on the next start when it is missing, which needs the internet once).

### QA

Checks issues one at a time and produces the QA results file.
- **Which issues:** from a **done file** (`done_<name>.csv`) alone, including one sent to you by someone else (**Choose done file…**; a
  results CSV also works if its done file is next to it), or **Load from the dashboard**, which pulls today's confirmed issues for the
  chosen chain (the subscription links carry the issue ids). QA keeps its own file, separate from the Upload tab's.
- **Fresh every time:** each file loaded into QA starts a fresh QA. Marks and results from an earlier QA of that file are set
  aside, renamed with a timestamp (nothing is deleted). Opening QA from the Upload tab on the file QA already holds does not restart it.
- **Comparison:** the expected values straight away, and the issue's own values as soon as the issue is selected (read in the
  background), with a tick or cross per field. Done files check subscription, date, channel, platform, rates and cancellation (older
  done files without the entered values are completed from the results CSV when it is next to them). Issues pulled from the
  dashboard are checked against the dashboard's own row: subscription, channel, date, and its difference with base rate, which
  should equal the base rate minus the channel rate on the issue; the hotel name is read from the issue. Every issue lists all its
  fields: where the tool has nothing to compare (dashboard issues have no entered rates, platform or cancellations; a cancellation
  the tool left as pre-filled) the expected column says "not checked" and the issue's own value is shown without a tick or cross.
- **Screenshots:** Lighthouse's own screenshots for the issue (Brand.com and the channel), downloaded directly with no Geoinsight
  window or tab opening (the images live at `screenshots-v3.mylighthouse.com/?img=<id>.png`, and the ids are in the issue's Geoinsight
  link; if Lighthouse changes that, the tool falls back to reading the page in a background tab). The last three issues are
  kept so stepping back is instant. Click the brand code to copy it.
- **Open issue + Geoinsight** opens the issue and its Geoinsight page in two windows of the tool's Chrome (reused for every issue).
- Mark each issue **Looks right** or **Problem**, with an optional note. Marks go in `review_<name>.csv`. Marking **Looks right**
  on an issue that has not been read, or whose check has ✗ fields, asks you to confirm first.
- The QA report also holds the issue's own values (platform, rates, cancellations) as read from its page, in the columns the tool
  has no entered values for (issues from the dashboard); `values_source` says whether they were entered by the tool or read from the issue.
- **QA results file:** kept up to date next to the done file (for the dashboard, in `qa_from_dashboard/`) as `qa_<name>.csv` while
  issues remain (unmarked ones show "Pending"), and it becomes `COMPLETED_qa_<name>.csv` once every issue is marked. **Download QA
  report** unlocks at that point. Each row has the entered values, the issue link, the field check, your result and note.
- Issues saved before issue ids were recorded can be marked, but not opened or have screenshots loaded.

## Nightly (branch `nightly`): scraper rebuild, untested

This branch is a work-in-progress of bringing the Mobile Parity Automation scraper (the tool that produces the results file) into this
app. Its source was not available, so only its structure was recovered; **nothing from its bundle, including the Google Drive key,
is copied here**. Treat everything in this section as untested against the live sites.

- `mp_rates.py`: reads a rate from page text and labels it as the results file does (a channel rate more than 2 below brand is
  `lower_than_brand`). Keeps the cents on brand.com rates, takes the lowest of several OTA prices, falls back to the input's brand rate when
  there is no live one, recognises more currencies and spots sold-out wording. Checked against two real results files.
- **Upload tab warning:** choosing a results file lists rows the file calls "not an issue" that are more than 2 below brand once the cents
  are counted (`/api/rates/check`). A warning only: runs follow the file's own labels.
- `mp_pricelines.py`: a first single-site reader for Priceline. It opens one results row's link in the tool's Chrome and prints the rate it
  reads (`python mp_pricelines.py results.csv [--row N] [--save-page FOLDER]`). **It has not yet completed a run on the live page**; its first
  trial crashed on empty page elements (fixed) and the next result was not seen. Expedia, Booking.com and the brand.com sites are not built.
- Tests: `.venv/bin/python -m unittest discover -s tests` (no network or Chrome needed).
- `VERSION` is `1.9.0-nightly`, which the updater does not read as a release number, so a nightly install is never offered an update and a
  stable install is never switched to a nightly.

## Installing and updating

**First install (no `xattr` step):** a download made with `curl` is not quarantined by macOS, so users run one line in Terminal. Set the
address from the repository's latest release (the zip named `MP-Assistance-v<version>.zip`):

```
cd ~/Downloads && curl -L -o mp.zip "https://github.com/hendrikusprinsloo-ux/mp-assistance/releases/latest/download/MP-Assistance.zip" && unzip -qo mp.zip && open "MP Upload tool/MP Assistance.app"
```

(Attach the zip to each release under the fixed name `MP-Assistance.zip` as well as its versioned name, so this address never changes.)
If a zip was downloaded in a browser instead, remove the mark first: `xattr -dr com.apple.quarantine "MP Upload tool"`.

**Updating:** every time the app is opened, `start.command` first runs `mp_update.py`, which asks GitHub for the latest release and, if it is newer,
installs it before the app starts (skipped with no internet). The page also opens on a **Checking for updates…** screen: if a newer version is out it shows what changed with **Update now** / **Later**, otherwise it clears by itself. Before 1.8
only the banner existed, so a 1.7 install updates once with the banner and from then on at launch. The zip is downloaded by Python
(so it is not quarantined), checked against its SHA-256 checksum, and only code files are replaced; settings, the ledger, QA files and `.venv`
are kept, and replaced files are copied to `.update_backup/` first. Restart the app to use it; the next start shows the release notes.
It needs the internet; without it the app carries on as normal.

**Making a release** (repository `hendrikusprinsloo-ux/mp-assistance`, public):
1. Raise `VERSION`, change the code in the testing copy first, then copy it to the main folder, and run `./package.sh`.
2. On GitHub, create a release tagged `v<version>` (for example `v1.7`). Write the changes in the description: they are the changelog users see.
3. Attach the zip, and a copy of it named `MP-Assistance.zip`. GitHub records a SHA-256 checksum for each file; if it does not, also attach
   `MP-Assistance-v<version>.zip.sha256` (the output of `shasum -a 256` on the zip). An update without a checksum is refused.
4. Keep write access to the repository to yourself and turn on two-factor sign-in: anyone who can publish a release changes the code on every machine.

## Sharing the app

`./package.sh` builds `MP-Assistance-v<version>.zip` next to the app folder (the number comes from `VERSION`, which goes into the
zip), leaving out everything private or specific to this Mac (`.venv`, `settings.json`, `issues_ledger.csv`, `qa_from_dashboard`,
logs, caches). Raise the number in `VERSION` for each new release. The other person unzips it, double-clicks `MP Assistance.app`
(or `start.command`), and the first launch sets itself up in about ten seconds: it needs Python 3, Google Chrome and an internet
connection once to install the tool's one dependency (it drives your own Chrome, so no browser is downloaded). They sign in to
Parity Manager when the app asks. On a Mac, the first open may need right-click > Open, and Terminal may ask for access to the
folders the results files are in.

## One-time setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

(`start.command` does this by itself on first launch.)

## Command line

The app is the normal way to work, but the upload tool runs on its own too. It drives the tool's Chrome, which the app starts with
its debugging port (`--chrome URL`, default `http://127.0.0.1:9222`):

```bash
.venv/bin/python mp_upload.py "/path/to/results_YYYY-MM-DD_HH-MM-SS.csv" --dry-run   # preview
.venv/bin/python mp_upload.py "/path/to/results_YYYY-MM-DD_HH-MM-SS.csv" --client Choice
```

Options: `--limit N` (stop after N rows), `--start N` (skip the first N-1 eligible rows), `--client CHAIN` (recorded as the chain),
`--existing pairs.json` (subscription and channel pairs to skip), and for Mobile App `--platform app --app-inputs inputs.json`.
For each row the form is filled, then it waits for a save from the app or Chrome; typing `save`, `s` (skip) or `q` (stop) in the terminal
works too. Saved and skipped rows are recorded in `done_<csv name>.csv` next to the results CSV (with the values entered, so the file
alone is enough to QA the run), and rows already saved there are skipped on a re-run.

## Field mapping

| Form field | CSV column |
| --- | --- |
| `base_shop_rate` | `branddotcom_parsed_rate` |
| `channel_shop_rate` | `parsed_rate` (Mobile App: the rate you type) |
| `base_cancellation` | `branddotcom_cancellation_policy` (Fully refundable = on, Non-Refundable = off) |
| `channel_cancellation` | `channel_cancellation_policy` (same) |
| `base_screenshot` | `branddotcom_screenshot_path` |
| `channel_screenshot` | `screenshot_path` (Mobile App: your phone screenshot) |
| `channel_platform` | left as the link pre-fills it, Mobile Web (Mobile App: Mobile App) |

Only rows with `status` and `branddotcom_status` both `ok` and `rate_comparison` = `lower_than_brand` are processed. When a cancellation policy is empty in the CSV,
that checkbox is left as the URL pre-filled it and the row is flagged in the log.
