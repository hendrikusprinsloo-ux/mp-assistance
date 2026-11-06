# MP Assistance: How To

A start-to-finish guide for raising Parity Manager issues from the scraper results, adding Mobile App issues from phone
screenshots, and checking what was saved. For the full detail see `README.md`.

**Contents**

- [Installing MP Assistance (first time)](#installing-mp-assistance-first-time)

1. [Before you start](#1-before-you-start)
2. [Opening the app and signing in](#2-opening-the-app-and-signing-in)
3. [Choosing the chain and the daily limits](#3-choosing-the-chain-and-the-daily-limits)
4. [Upload tab: raising web issues](#4-upload-tab-raising-web-issues)
5. [Mobile App tab: raising app issues from phone screenshots](#5-mobile-app-tab-raising-app-issues-from-phone-screenshots)
6. [QA tab: checking what was saved](#6-qa-tab-checking-what-was-saved)
7. [Good to know](#7-good-to-know)
   - [Installing and updating](#installing-and-updating)
   - [If the Mac will not open the app](#if-the-mac-will-not-open-the-app)
8. [If something goes wrong](#8-if-something-goes-wrong)

---

## Installing MP Assistance (first time)

You do this once per computer. It takes about two minutes and needs the internet. After it, the app updates itself.

**What you need:** a Mac, Google Chrome, and your Parity Manager and Lighthouse Google sign-ins. Python 3 comes with macOS's command line tools; if the Mac
offers to install them the first time you run the line below, click **Install** and run the line again afterwards.

1. Open **Terminal**: press **Cmd + Space**, type `Terminal` and press Return.
2. Copy this whole line, paste it into Terminal and press Return:

```
cd ~/Downloads && curl -L -o mp.zip "https://github.com/hendrikusprinsloo-ux/mp-assistance/releases/latest/download/MP-Assistance.zip" && unzip -qo mp.zip && open "MP Upload tool/MP Assistance.app"
```

3. Wait. The line downloads the app, unpacks it into your **Downloads** folder as `MP Upload tool`, and opens it. The first start sets itself up and
   takes about ten seconds longer than usual; a Terminal window opens and stays open while the app runs. Do not close it.
4. Two Chrome windows open: the Parity Manager login and the tool window. **First check Chrome's profile:** in the top-right corner of the Parity Manager
   window, make sure Chrome is signed in with your Lighthouse Google account (click the icon there and sign in if not). Then sign in to Parity Manager, check the
   Google account line under the message reads your Lighthouse address, and pick the chain. Section 2 below goes through this screen by screen.
5. From now on open the app from the same place: double-click **MP Assistance.app** inside the `MP Upload tool` folder. Each time it opens it checks for a newer
   version and installs it by itself, so there is nothing to download again.

**Choosing where it lives:** you can move the `MP Upload tool` folder somewhere else (for example Documents) **before the first time you open it**. If you move it
afterwards, delete the hidden `.venv` folder inside it first; the app rebuilds it on the next start. If the first open reports that macOS is not letting
Terminal use that folder, allow it under System Settings > Privacy & Security > Files and Folders.

**Running the line again:** it reinstalls the app code over the same folder and keeps your settings, daily record and sign-in, since those are not in the download.
It is also the fix if the app folder was deleted or damaged.

**If it does not work**
- **"curl: could not resolve host" or nothing downloads:** check the internet connection and run the line again.
- **The Mac says the app cannot be opened, is damaged, or nothing happens:** see [If the Mac will not open the app](#if-the-mac-will-not-open-the-app).
- **"command not found" for `unzip` or `curl`:** these are part of macOS, so check the line was pasted whole, on one line.
- **Anything else:** copy the last lines Terminal printed and send them to whoever looks after the app.

[Back to contents](#mp-assistance-how-to)

## 1. Before you start

- A Mac with Python 3 and Google Chrome, with the app installed as described in [Installing MP Assistance](#installing-mp-assistance-first-time) above. The app drives your own Chrome, so nothing else is downloaded.
- The scraper's results file (`results_YYYY-MM-DD_HH-MM-SS.csv`) **together with its screenshots in the same folder**. A results file
  from a colleague works too, because the tool finds the screenshots by file name next to the CSV.
- Your Parity Manager sign-in.
- The first launch needs the internet once to set itself up (about ten seconds). On a Mac the first open may need right-click, Open; if that does not work see [If the Mac will not open the app](#if-the-mac-will-not-open-the-app).

[Back to contents](#mp-assistance-how-to)

## 2. Opening the app and signing in

1. Double-click **MP Assistance.app** (or `start.command`).
2. Two Chrome windows open: the **Parity Manager login** and the **tool window** (no address bar). The windows are not moved on
   their own: click **Arrange windows** to put the tool window on the left half of the screen and Parity Manager on the right.
3. **Check you are signed into Chrome with your Lighthouse profile.** Look at the top-right corner of the **Parity Manager** window that opened:
   - If it shows your picture or initial and your Lighthouse (`mylighthouse.com`) Google account, you are set.
   - If it shows a different account, or a plain "Sign in" or person icon, click that icon, choose **Sign in** (or switch account) and sign in with your
     **Lighthouse Google account**, the same one you use for your Lighthouse logins. If Chrome asks whether to turn on sync, either answer works.
   - Do this first: the Lighthouse pages (such as the Geoinsight screenshots) only open properly from that profile. It is saved, so you normally only do it once per computer.
4. Sign in to Parity Manager in the same window. The tool window waits and carries on by itself once you are signed in. Under its message it shows
   **which Google account the tool's Chrome is signed into**, so you can confirm step 3 worked: it should read "Chrome is signed in as" your Lighthouse address.
   If it shows another address, or says no account, go back to step 3. The app only tells you; it does not stop you continuing.
5. Closing the tool window stops the app.

The header shows the version (for example `v1.9.2`). **Light mode / Dark mode** switches the theme.

**Folding sections:** click any section heading (or press Enter on it) to fold it up, and again to open it. The app remembers your choices. **1. Chrome**
and the **Log** boxes start folded, since they are rarely needed. The Chrome heading still shows "· running" or "· not running", so you can see
its state without opening it.

[Back to contents](#mp-assistance-how-to)

## 3. Choosing the chain and the daily limits

After sign-in a popup asks **which chain you are working on**: Choice (the default), Best Western or Wyndham.

- It shows the chain's daily limit and how many issues are confirmed today. You can change the numbers there.
  Defaults: Choice 36 web + 2 Mobile App (1 Booking.com, 1 Expedia), Best Western 10, Wyndham 50.
- The button in the top corner has two parts: the chain name (`Choice ▾`) reopens the popup, and the count (`34/38 ↗`) opens
  today's dashboard in Parity Manager. The count comes from the dashboard, so it includes everyone's issues.
- It also has a **web limit for each of Priceline, Booking.com and Expedia** for the chain (0 = no limit for that channel). Choice starts at 4 Priceline, 16 Booking.com and 16 Expedia;
  Best Western and Wyndham start with none. A channel that is full takes no more issues in a run (the Log says "<channel> limit reached"),
  and **Save issue** refuses one for it. The limit line under the header shows each channel's count, for example `Priceline 3/4`.
- Saving is refused once a limit is used up. A run still loads **every remaining row** of the results file, so you can carry on down it after declining
  an issue; **Save issue** is what enforces the limits.
- **Ignore limits** (top corner, off at every start): switches the limit checks off for a demo or an exception. A red banner shows
  while it is on. One issue per channel per subscription still applies, and it creates **real** issues.
- The **Mobile App** tab only appears for Choice.

[Back to contents](#mp-assistance-how-to)

## 4. Upload tab: raising web issues

The app always opens on this tab.

1. **1. Chrome:** the heading says "· running" when the tool's Chrome is open. If it says "not running", open the section and click
   **Open Chrome for the tool**.
2. **2. Results CSV:** the newest results file is usually loaded for you (see *Default runs folder* below). Otherwise click **Choose file…** and pick
   the results CSV. The app also remembers the file you last chose, so a page reload does not empty it.
3. Optional: tick **Dry run (preview only)** to see what would be processed without touching Parity Manager, or set **Limit rows** (left empty, it loads all the remaining rows).
4. Click **Start**. The page scrolls down smoothly to the **3. Run** card. For each eligible row the tool fills the Parity Manager form in Chrome and
   shows a **card** there with:
   - the values as the form holds them (rates, cancellations, channel, platform, files attached), each with a ✓ or ✗ against what was meant;
   - both screenshots.

   If the results file had a cancellation wrong, click **Untick** or **Tick** beside that row on the card. It changes the form in Chrome straight away.
   The done file notes "Changed by hand" for it.
5. Check the card, then click one of:
   - **Save issue**: clicks Parity Manager's Save. The tool first re-checks the dashboard and refuses, with a reason, if the save would
     go over the limit or double up an existing issue.
   - **Decline**: use it for an issue that should not be raised, for example one that cannot be confirmed. Type a reason in the box next to it
     first if you like. The issue is recorded in the done file as `declined` with your note, and it **does not come back**: not in later runs,
     not on the Mobile App tab and not in QA.
   - **Stop run**: stops after leaving the current issue unsaved.
6. When you are done, open the **QA** tab to check what was saved (see section 6).

Which rows are processed: `status` and `branddotcom_status` both `ok`, and the channel rate lower than brand. Rows are skipped if that
hotel and channel already have an issue today (on the dashboard, saved here, or earlier in the file). The **Log** at the bottom
says how many rows were skipped and why, for example "not lower than brand" or "already on the dashboard". When the run ends it prints a summary
of how many issues were saved and declined. Each new issue's screenshots start at the top.

**Default runs folder:** under *2. Results CSV*, click **Set default runs folder…** and pick the folder that holds your run folders (for example
`parity_scraper_screenshots`). Each time the app starts it loads the newest `results_….csv` in it, chosen by the time in the file name.
**Load latest results** does the same whenever you want, and **Choose file…** still lets you pick any CSV. If macOS says the app cannot look inside
the folder, open System Settings > Privacy & Security > Files and Folders (or Full Disk Access), switch it on for Terminal, and start the app again.

[Back to contents](#mp-assistance-how-to)

## 5. Mobile App tab: raising app issues from phone screenshots

Choice only. Booking.com and Expedia only, limit one of each per day.

1. **1. Results CSV:** **Use the Upload file** (the one chosen on the Upload tab) or **Choose file…**.
2. **2. Issues** lists the rows that are lower than brand and have no issue yet today for that hotel on that channel.
   - The **Left out** line counts the rows that were not listed and why.
   - ⚠ next to a hotel means its base screenshot file was not found next to the results file.
   - A note appears if a `done_…csv` next to the results file already holds saved issues (rows saved there are skipped).
3. For each row, on your phone:
   1. Click **QR / link**. A popup shows the Expedia or Booking.com page (the one the Lighthouse link redirects to) as a **QR code**.
      Scan it with the phone, or use **Open page** to open it on the computer, or **Copy link**.
   2. Take the phone screenshot of the page.
4. Back in the app, for each row:
   - **Choose phone screenshot…**: pick the JPEG or PNG (AirDrop works; choose *Options > Most Compatible* so iPhone photos are JPEG, not HEIC).
     A copy is saved with a `.png` name in a `mobile_app` folder next to the results file; your original is untouched.
   - Type the **App rate** shown on the phone screenshot.
   - Choose the **Channel cancellation** shown on the phone page (**Ticked** for refundable, **Not ticked** for non-refundable). It can differ from the
     web page, so it is never copied from the results file for a Mobile App issue.
   - The row shows ✓ once it has all three.
5. Optional: **Check all links** follows every row's link and marks each QR button ✓ or ✗ (hover a ✗ for the reason) before you head to your phone.
6. Click **Upload ready issues**. The forms are filled with Channel platform set to Mobile App, and the card, **Save issue**, **Decline**
   and Log work exactly as on the Upload tab, including the smooth scroll to the Run card and the **Tick / Untick** switch for cancellations.
   The table keeps your cursor and anything you have typed while the page refreshes in the background. Choosing a results file glides
   to the **2. Issues** list.

[Back to contents](#mp-assistance-how-to)

## 6. QA tab: checking what was saved

The QA tab checks that the values on the issues themselves match the Lighthouse screenshots. You confirm each one.

1. Open the **QA** tab. It loads **today's confirmed issues for the chosen chain** from the dashboard by itself. (**Load from the dashboard**
   reloads the list.)
2. Optional: if a colleague has already QAed some of them, click **Skip issues from a QA cache…** and choose their `qa-cache_….csv`
   (you can add several). Issues they marked **Looks right** are left out; ones marked **Problem** stay in. A line shows how many were skipped.
3. Step through the issues with **‹** and **›**; the page glides smoothly to the top of each issue's card. For each one:
   - The table lists the issue's own values, read from Parity Manager in the background: subscription id, arrival date, channel, platform,
     base and channel rate, and both cancellations.
   - The Lighthouse **screenshots** (Brand.com and the channel) load beside it. Check the values against them. Click the brand code to copy it.
   - **Open issue + Geoinsight** opens the issue and its Geoinsight page in the tool's Chrome if you want to look closer.
4. Mark each issue **Looks right** or **Problem**, with an optional note.
5. **Your QA cache:** every mark is also saved in `qa-cache_dashboard_<chain>_<date>.csv` (in the `qa_from_dashboard` folder). It holds
   your computer's username, the time, the issue and your result and note, and is updated with every mark. **Download my QA cache** gives
   you a copy to look at or to hand to the next person.
6. When every issue is marked, the page glides down to the QA report and **Download QA report** unlocks. The results file is kept as `qa_<name>.csv` while issues remain (unmarked ones
   show "Pending") and becomes `COMPLETED_qa_<name>.csv` when finished.

If you restart the app during QA, the tab loads the list again. Your marks are kept in the cache file; choose it under **Skip issues** to leave those out.

[Back to contents](#mp-assistance-how-to)

## 7. Good to know

- **One issue per channel per subscription.** Parity Manager takes only one for a hotel on a channel. The same hotel on a different channel is fine.
- **The dashboard is the record** of what is confirmed. If it cannot be read, the tool falls back to its own note of what this computer saved today
  and says so.
- **Nothing is deleted.** Skipped and saved rows are recorded in `done_<name>.csv`; a re-run skips rows already saved.
- **Updating:** the app checks for a newer version every time it opens; see [Installing and updating](#installing-and-updating) below.
  The QR codes need the `segno` package, which `start.command` installs by itself if it is missing (internet needed once).

[Back to contents](#mp-assistance-how-to)

### Installing and updating

**First install:** see [Installing MP Assistance](#installing-mp-assistance-first-time) at the top. A file downloaded in Terminal is not marked by macOS, which is why
that route avoids the "cannot be opened" warning; a zip from a browser, AirDrop or Mail needs the steps in [If the Mac will not open the app](#if-the-mac-will-not-open-the-app).

**Updating:** every time the app opens it first asks GitHub whether there is a newer version, installs it, and then starts, so you normally do nothing. (This needs the internet and version 1.8 or newer; an older install is offered the update once, as a banner.) If the app was left open for days, a screen offers it:

1. A screen in front of the page says **Version X is available**, with what changed. Click **Update now** (or **Later**).
2. The app downloads and checks the new version. Your settings, the daily record, QA files and sign-in are kept, and the files it replaces are copied to
   `.update_backup` first. It will not update while a run is in progress.
3. When it says the version is installed, close the tool window and open the app again.
4. The next start shows **Updated to vX** with what changed. Click **Got it**.

At start-up the update happens before the app opens, and Terminal prints "Updating MP Assistance … -> …". If there is no internet, or no newer version, nothing
is shown and the app works as usual.

**For whoever publishes versions:** the app's folder is `hendrikusprinsloo-ux/mp-assistance` on GitHub (public).
1. Raise `VERSION`, then run `./package.sh`. It writes `MP-Assistance-v<version>.zip`, a copy named `MP-Assistance.zip`, and a `.sha256` file.
2. On GitHub, create a **release** tagged `v<version>` and write the changes in its description: that is the text people see after updating.
3. Attach all three files. Without the checksum an update is refused.
4. Keep write access to the repository to yourself and use two-factor sign-in, because whoever can publish a release changes the app on every computer that updates.

[Back to contents](#mp-assistance-how-to)

### If the Mac will not open the app

A new copy of the app (from a zip, AirDrop or a download) can be blocked with a message such as "cannot be opened", "is damaged" or
"cannot be verified", or it does nothing when double-clicked. macOS marks downloaded files as quarantined. Remove the mark:

1. Put the unzipped **MP Upload tool** folder where you want to keep it (for example in Documents).
2. Open **Terminal** (Applications > Utilities).
3. Type `xattr -dr com.apple.quarantine ` (with a space at the end), then **drag the folder into the Terminal window** so its path is filled in, and press Return:

```
xattr -dr com.apple.quarantine "/Users/<you>/Documents/MP Upload tool"
```

   `-d` deletes the quarantine attribute and `-r` does it for everything inside the folder. Nothing is printed when it works.
4. Open **MP Assistance.app** again. If it still will not run, give the launcher permission to run, the same way:

```
chmod +x "/Users/<you>/Documents/MP Upload tool/start.command"
```

If macOS still blocks it, open **System Settings > Privacy & Security** and click **Open Anyway** next to the app's name.

[Back to contents](#mp-assistance-how-to)

## 8. If something goes wrong

| What you see | What to try |
| --- | --- |
| Stuck on **Running…** and nothing appears in Chrome | Look at the tool's Chrome window: is it on the sign-in page or an error page? Sign in, or click **Stop** and start again. The Log at the bottom of the tab shows what the tool is doing. |
| A row you expected is missing | Read the **Left out** line (Mobile App tab) or the Log (Upload tab). Common reasons: not lower than brand, already on the dashboard, already saved today, declined earlier. |
| ⚠ next to a hotel | The base screenshot is not in the same folder as the results CSV. Put the CSV and its screenshots together. |
| **Save issue** is refused | The message says why: over the limit, the subscription already has an issue on that channel, or the Mobile App slot for the day is taken. |
| QR popup says it could not reach the link | Check the internet connection, or click **Check all links** to see which rows fail. |
| QR popup says the QR package is missing | Restart the app so `start.command` can install it (internet needed once), or run `.venv/bin/pip install segno`. |
| The dashboard count looks wrong or is marked as this computer's count | The tool could not read the dashboard. Make sure you are signed in to Parity Manager in the tool's Chrome. |
| The Mac says the app cannot be opened, is damaged, or nothing happens | See [If the Mac will not open the app](#if-the-mac-will-not-open-the-app): run `xattr -dr com.apple.quarantine` on the folder. |
| The sign-in screen says Chrome is signed in as a non-Lighthouse address, or not signed in to a Google account | Click the profile icon in the top-right corner of the Parity Manager window, sign in with your **Lighthouse Google account** (or switch to it), then click **Check again** on the sign-in screen. Without it, Lighthouse pages such as the Geoinsight screenshots may not open. |
| An update does not seem to apply | Quit the app (close the tool window) and open it again. |

[Back to contents](#mp-assistance-how-to)
