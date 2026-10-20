"""Booth sheet archive: keep a copy of every sheet a booth app prints (Welton, 2026-10-20).

Why: the La Paloma sheet was measured in New York, and there was no way to
know how many other wrong sheets the team had handed out this year, because
the live apps kept nothing. Every sheet is now saved to the private GitHub
repo weltonhong/booth-sheets-archive, with what the scan found behind it:

    <app>/<YYYY-MM-DD>/<HHMMSS>Z_<business>/sheet.pdf      the sheet itself
                                            results.json   everything the scan recorded
                                            scan_log.txt   the live scan printout

<app> is the deploy repo the app runs from (scmm-healthcheck-brian, ...), so a
sheet can be traced to the rep's app.

What is NOT saved: the raw Google pages. results.json holds what the scan read
off them (map pack top three, page-one sites, advertisers), not the pages.

Saving must never cost the prospect a sheet. save_sheet never raises; it
returns (True, where) or (False, why) and the app shows the rep a short note
when it fails. The sheet downloads either way.

The app's GitHub token comes from the BOOTH_ARCHIVE_TOKEN secret (a
fine-grained token that can write to that one repo only). No token: nothing is
saved, and the rep is told.

Identical copies live in all five booth tools' scripts/ folders;
tradeshow-healthcheck-homecare/scripts/test_booth_sheet_archive.py fails if
they drift apart.
"""
import base64
import datetime
import json
import os
import re
import time
from pathlib import Path

import requests

ARCHIVE_REPO = "weltonhong/booth-sheets-archive"
API = "https://api.github.com/repos/%s/contents/%s"
TIMEOUT = 8
TOKEN_ENV = "BOOTH_ARCHIVE_TOKEN"

REP_NOTE = ("This sheet was not saved to the office copy (%s). "
            "It is fine to hand over. Let Welton know.")


def app_name():
    """The deploy repo this app runs from: on Streamlit Cloud /mount/src/<repo>/my-skills/..."""
    return Path(__file__).resolve().parents[3].name


def _slug(text):
    s = re.sub(r"[^A-Za-z0-9]+", "-", text or "").strip("-")
    return (s or "unnamed")[:60]


def folder_for(business, when=None, app=None):
    when = when or datetime.datetime.now(datetime.timezone.utc)
    return "%s/%s/%sZ_%s" % (app or app_name(), when.strftime("%Y-%m-%d"),
                             when.strftime("%H%M%S"), _slug(business))


def _put(path, content_bytes, message, token, session):
    """One file into the archive. Retries a 409 (another app saved at the same moment)."""
    url = API % (ARCHIVE_REPO, path)
    body = {"message": message, "content": base64.b64encode(content_bytes).decode("ascii")}
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    last = None
    for attempt in range(3):
        r = session.put(url, json=body, headers=headers, timeout=TIMEOUT)
        if r.status_code in (200, 201):
            return None
        last = "GitHub answered %s" % r.status_code
        if r.status_code not in (409, 500, 502, 503):
            break
        time.sleep(1 + attempt)
    return last


def save_sheet(pdf_bytes, results, log_text, business, token=None, session=None, when=None, app=None):
    """Save one printed sheet. Never raises. Returns (True, folder) or (False, reason)."""
    try:
        token = token if token is not None else os.environ.get(TOKEN_ENV, "")
        if not token:
            return False, "no archive token set"
        if not pdf_bytes:
            return False, "no sheet to save"
        session = session or requests
        folder = folder_for(business, when, app)
        message = "Booth sheet: %s (%s)" % (business, folder.split("/")[0])
        files = [
            ("sheet.pdf", pdf_bytes),
            ("results.json", json.dumps(results, indent=1, default=str).encode("utf-8")),
            ("scan_log.txt", (log_text or "").encode("utf-8")),
        ]
        for name, data in files:
            err = _put("%s/%s" % (folder, name), data, message, token, session)
            if err:
                return False, "%s on %s" % (err, name)
        return True, folder
    except Exception as e:                                    # noqa: BLE001
        return False, "could not reach GitHub: %s" % type(e).__name__
