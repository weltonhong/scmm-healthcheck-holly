"""Nothing on a booth sheet may rest on a measurement that failed (Welton, 2026-10-21).

THE RULE. Every search and lookup has three answers: found, genuinely absent, couldn't check. The
rows on the sheet already printed all three (2026-10-20). The headline, the grades, the summary
sentences and the bullets did not: they read a failed search as a measured negative. On a scan
where every search failed the sheet still printed OVERALL GRADE F, "your funeral home is not on
the first page", "This is an open lane" and "Your foundation is strong". One bug, not fifteen.

So no headline, grade, summary sentence or bullet is built on a search or lookup that failed. If
what it rests on was "couldn't check", it says so or it does not print. Every app asks this module
before it says anything about the prospect, so the rule lives in one place:

  failed(row)              a search or lookup that did not come back (no answer, or an error)
  organic_failed(row)      the organic half of a search cannot be read: the search failed, or
                           nothing tells which result is theirs (no website to compare)
  read(keys, table)        the searches that came back, the only ones a sentence may count
  overall_grade(grades)    the average of the grades that were measured; None when none were
  everything_read(...)     the only case a "nothing wrong" sentence may print
  answer(value, no_text)   Yes / No / Couldn't check, for a check that may not have been read
  on_their_site(url, site) a search result is theirs only when it is on their own website

A NAME IS NOT A MEASUREMENT OF RANK (the pre-call rule, prospect_identity.website, 2026-10-16).
A directory page that names them (Find a Grave, MapQuest, a county page) is somebody else's
result. Their result is one on their own website; with no website to compare, nothing can be
called theirs, and the row reads couldn't check.

Identical copies live in all five booth tools' scripts/ folders;
tradeshow-healthcheck-homecare/scripts/test_booth_nothing_from_a_failure.py fails if they drift
apart, and proves the rule on a scan where every search and lookup fails, in all five tools.
"""
import datetime
import urllib.parse

POINTS = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
LETTERS = {v: k for k, v in POINTS.items()}
NO_GRADE = "N/A"          # what prints where a grade would be, when nothing behind it was measured


def failed(row):
    """The search or lookup behind this row did not come back."""
    return not row or bool(row.get("error"))


def organic_failed(row):
    """The organic results of this search cannot say where they rank."""
    return failed(row) or bool((row or {}).get("organic_error"))


def read(keys, table, organic=False):
    """The keys whose search came back (organic=True: whose organic results can be read)."""
    test = organic_failed if organic else failed
    return [k for k in keys if not test((table or {}).get(k))]


def overall_grade(grades):
    """The average of the measured grades. None when nothing was measured: never an F."""
    real = [g for g in grades if g in POINTS]
    if not real:
        return None
    return LETTERS[round(sum(POINTS[g] for g in real) / len(real))]


def grade_text(grade):
    """A grade as printed: the letter, or N/A."""
    return grade if grade in POINTS else NO_GRADE


def everything_read(results, keys, listing_known, website_needed=True):
    """True only when every search and lookup the sheet rests on came back and could be read.

    The one case a "nothing is wrong" sentence ("Your foundation is strong...") may print: a
    sentence about everything needs everything measured. A map row with no cards, or a card
    that only may be theirs, is not a measurement of the map.
    """
    if not listing_known:
        return False
    pack = (results.get("3pack") or {}).get("results") or {}
    seo = results.get("seo") or {}
    ads = results.get("ads") or {}
    for k in keys:
        p = pack.get(k)
        if failed(p) or not [t for t in (p.get("top_3") or []) if t] or p.get("maybe_rank") \
                or p.get("no_id"):
            return False
        if organic_failed(seo.get(k)) or failed(ads.get(k)):
            return False
        a = ads.get(k) or {}
        if a.get("theirs_unknown") or (a.get("prospect_maybe_ad") and not a.get("prospect_running_ads")):
            return False
    if website_needed and results.get("website_grade") not in POINTS:
        return False
    return bool(keys)


def answer(value, no_text="No"):
    """Yes / the No text / "Couldn't check" (None: the page the check needed could not be read)."""
    if value is None:
        return "Couldn't check"
    return "Yes" if value else no_text


def _site(url_or_host):
    s = (url_or_host or "").strip().lower()
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    try:
        host = urllib.parse.urlparse(s).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def on_their_site(url_or_host, their_site):
    """A search result or ad is theirs when it is on their own website (or a subdomain of it)."""
    a, p = _site(url_or_host), _site(their_site)
    return bool(a and p) and (a == p or a.endswith("." + p))


# ----------------------------------------------------------------- the date on the sheet --
# "Scanned <date>" is a claim too (Welton, 2026-10-21): the app's server runs on UTC, so a scan after
# 5 pm Pacific printed tomorrow's date. The date is the rep's own day, from the rep's browser (the app
# passes it as results["browser_tz"]). Without it, the day where the prospect is, from their state,
# with the time zone named beside it. The server's UTC day is never used.
STATE_ZONES = {
    "CT": "America/New_York", "DE": "America/New_York", "DC": "America/New_York", "FL": "America/New_York",
    "GA": "America/New_York", "IN": "America/Indiana/Indianapolis", "KY": "America/New_York",
    "ME": "America/New_York", "MD": "America/New_York", "MA": "America/New_York", "MI": "America/Detroit",
    "NH": "America/New_York", "NJ": "America/New_York", "NY": "America/New_York", "NC": "America/New_York",
    "OH": "America/New_York", "PA": "America/New_York", "RI": "America/New_York", "SC": "America/New_York",
    "VT": "America/New_York", "VA": "America/New_York", "WV": "America/New_York",
    "AL": "America/Chicago", "AR": "America/Chicago", "IL": "America/Chicago", "IA": "America/Chicago",
    "KS": "America/Chicago", "LA": "America/Chicago", "MN": "America/Chicago", "MS": "America/Chicago",
    "MO": "America/Chicago", "NE": "America/Chicago", "ND": "America/Chicago", "OK": "America/Chicago",
    "SD": "America/Chicago", "TN": "America/Chicago", "TX": "America/Chicago", "WI": "America/Chicago",
    "CO": "America/Denver", "ID": "America/Boise", "MT": "America/Denver", "NM": "America/Denver",
    "UT": "America/Denver", "WY": "America/Denver", "AZ": "America/Phoenix",
    "CA": "America/Los_Angeles", "NV": "America/Los_Angeles", "OR": "America/Los_Angeles",
    "WA": "America/Los_Angeles", "AK": "America/Anchorage", "HI": "Pacific/Honolulu",
}
ZONE_NAMES = {
    "America/New_York": "Eastern Time", "America/Indiana/Indianapolis": "Eastern Time",
    "America/Detroit": "Eastern Time", "America/Chicago": "Central Time", "America/Denver": "Mountain Time",
    "America/Boise": "Mountain Time", "America/Phoenix": "Arizona Time", "America/Los_Angeles": "Pacific Time",
    "America/Anchorage": "Alaska Time", "Pacific/Honolulu": "Hawaii Time",
}


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def sheet_day(results):
    """(date, zone name or "") for "Scanned <date>"; (None, "") when neither the rep's browser nor the
    prospect's state gives a time zone. A state that spans two zones uses the zone most of it keeps,
    and the sheet names that zone."""
    from zoneinfo import ZoneInfo
    now = _now()
    tz = (results or {}).get("browser_tz")
    if tz:
        try:
            return now.astimezone(ZoneInfo(tz)).date(), ""
        except Exception:
            pass
    zone = STATE_ZONES.get(((results or {}).get("state") or "").strip().upper())
    if zone:
        return now.astimezone(ZoneInfo(zone)).date(), ZONE_NAMES[zone]
    return None, ""


def sheet_date_text(results):
    """'October 21, 2026', 'October 21, 2026 (Pacific Time)', or '' when no time zone is known."""
    day, zone = sheet_day(results)
    if day is None:
        return ""
    text = day.strftime("%B %d, %Y")
    return "%s (%s)" % (text, zone) if zone else text


# ------------------------------------------- W8: a page on a company-wide website ------------
# Welton, 2026-10-21: a prospect whose Google listing points at a page on a company-wide site
# (Dignity Memorial, a franchise brand, a family firm's chapel pages) was credited with everything on
# that domain: Dignity Memorial's corporate ad printed as "Frank E. Campbell: Their ad was seen", and
# any other location's page counted as their rank. The pre-call rule of 10-16: a shared site is
# "could not confirm", never yes or no. And "a business genuinely running its own ads on its own page
# should still be credited": a result or ad on their own page (or under it) is theirs.
# Which hosts are company-wide is measured, not guessed: shared_hosts.py (built from 28,260 real
# listing websites by ops/build_shared_hosts.py). Any other host keeps the whole-domain rule.
THEM, CANT_TELL, NOT_THEM = "them", "cant_tell", "not_them"


def _url_path(u):
    s = (u or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    try:
        return urllib.parse.urlparse(s).path.rstrip("/").lower()
    except ValueError:
        return ""


def company_wide(their_site):
    """Their website is a page on a host that several businesses' listings share."""
    from shared_hosts import SHARED_HOSTS
    h = _site(their_site)
    return bool(_url_path(their_site)) and (h in SHARED_HOSTS or any(h.endswith("." + s) for s in SHARED_HOSTS))


def page_verdict(url_or_host, their_site):
    """THEM, CANT_TELL or NOT_THEM for one search result or ad, by its address."""
    if not on_their_site(url_or_host, their_site):
        return NOT_THEM
    if not company_wide(their_site):
        return THEM
    mine, other = _url_path(their_site), _url_path(url_or_host)
    if other == mine or other.startswith(mine + "/"):
        return THEM
    return CANT_TELL


def organic_text(row):
    """What an organic row says when it cannot give a rank."""
    maybe = (row or {}).get("organic_maybe")
    if maybe and not failed(row):
        return "Couldn't confirm: #%s is a page on their company's website" % maybe
    return "Couldn't check this search"


def organic_unread(rank, results, their_site):
    """{"organic_error", "organic_maybe"} for one search's organic results."""
    if not _site(their_site):
        return {"organic_error": "no website for the business to compare results with", "organic_maybe": None}
    if rank:
        return {"organic_error": None, "organic_maybe": None}
    maybe = next((r.get("position") for r in results or []
                  if page_verdict(r.get("url") or r.get("domain"), their_site) == CANT_TELL), None)
    return {"organic_error": ("a page on their company's website ranks; could not confirm it is theirs"
                              if maybe else None), "organic_maybe": maybe}
