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
import re
import urllib.parse
from xml.sax.saxutils import escape

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


# ------------------------------------------------ the prospect's own listing among competitors --
# Welton 2026-10-21: the self-filter dropped real rivals ("Guardian Angels Home Health" for "Angels Home
# Health", Smithfield for Smith), and a dropped rival can turn into telling an owner they lead their market.
# A competitor is the prospect's own listing only when it IS that listing: the same Google place id, or the
# same street address. With no listing to compare, only an identical name.


def _norm(s):
    return " ".join(re.findall(r"[a-z0-9]+", (s or "").lower()))


def same_listing(candidate, target, business=""):
    """True when a competitor from the lookup is the prospect's own listing."""
    import map_identity
    c, t = candidate or {}, target or {}
    cc, tc = map_identity.cid_of(c.get("maps_url")), map_identity.cid_of(t.get("maps_url"))
    if cc and tc:
        return cc == tc
    ca, ta = _norm(c.get("address")), _norm(t.get("address"))
    if ca and ta:
        return ca == ta
    return bool(_norm(c.get("name"))) and _norm(c.get("name")) in (_norm(business), _norm(t.get("name")))


# ------------------------------------------- when the searches ran (Welton 2026-10-22) ------
# Organic rank moved five places in forty minutes on our own re-run (Haven, "medicare home health Ozark MO": Rank 1,
# then 6), so a rank is what Google showed at one moment, not where a business stands. The sheet says that moment
# once: "All searches run at 9:42 am on 22 October. Google reshuffles these results through the day." The time is
# the searches' own start (results["searched_at"], UTC), shown in the same zone as the sheet's date (sheet_day).


def _search_moment(results):
    """(local datetime, zone name or "") of when the searches started; (None, "") when unknown."""
    from zoneinfo import ZoneInfo
    at = (results or {}).get("searched_at")
    try:
        t = datetime.datetime.fromisoformat(at) if at else None
    except ValueError:
        t = None
    if t is None or t.tzinfo is None:
        return None, ""
    # The zone is always named (Welton 2026-10-24): Engram's sheet said "7:07 am" in the rep's Pacific time and a
    # Virginia owner reads that as Eastern, three hours off. The rep's zone when it has a name we know, else the
    # prospect's state's zone (its name), else the zone's own short name; never a time with no zone.
    tz = (results or {}).get("browser_tz")
    if tz in ZONE_NAMES:
        return t.astimezone(ZoneInfo(tz)), ZONE_NAMES[tz]
    zone = STATE_ZONES.get(((results or {}).get("state") or "").strip().upper())
    if zone:
        return t.astimezone(ZoneInfo(zone)), ZONE_NAMES[zone]
    if tz:
        try:
            local = t.astimezone(ZoneInfo(tz))
            if local.strftime("%Z"):
                return local, local.strftime("%Z")
        except Exception:
            pass
    return None, ""


def searched_line(results):
    """'All searches run at 9:42 am on 22 October. Google reshuffles these results through the day.'"""
    t, zone = _search_moment(results)
    if t is None:
        return "Each search was run once. Google reshuffles these results through the day."
    clock = t.strftime("%I:%M %p").lstrip("0").lower()
    return "All searches run at %s%s on %d %s. Google reshuffles these results through the day." % (
        clock, (" " + zone) if zone else "", t.day, t.strftime("%B"))


def searched_when(results):
    """'this morning', 'this afternoon', 'this evening', or 'today' when the time is unknown."""
    t, _ = _search_moment(results)
    if t is None:
        return "today"
    return "this morning" if t.hour < 12 else "this afternoon" if t.hour < 17 else "this evening"


# The search-results row is not graded (Welton 2026-10-22). A bare "N/A" beside rows that were read looked like
# nothing was measured; Welton's words for it, 2026-10-24. Only where at least one row was read: with none read,
# N/A is the honest answer and stays.
SEO_NOT_GRADED = "Not graded: your position changes depending on where someone searches from."


def seo_not_graded(results, grade=None):
    """True when the search-results row has no grade AND at least one of its searches was read."""
    rows = ((results or {}).get("seo") or {}).values()
    return not grade and any(isinstance(r, dict) and not organic_failed(r) for r in rows)


def reviews_word(n):
    """'review' for exactly one, else 'reviews' (Welton 2026-10-24: Valley View's sheet said "1 reviews").
    n may be an int, a digit string, None or '-'; only a count of one is singular."""
    return "review" if str(n).strip() == "1" else "reviews"


def organic_row_text(d):
    """One organic row as printed: '#7' or 'not on page one', then who ranked above them (listing-backed)."""
    above = [n for n in (d.get("above") or []) if n]
    tail = " (ranked above you: %s)" % ", ".join(above) if above else ""
    return ("#%d" % d["rank"] if d.get("rank") else "not on page one") + tail


def speed_text(web):
    """Google's mobile speed score as printed: the range across the scan's runs ("30 to 57"), or one number when they
    agree (Welton 2026-10-22: one run swings about 25 points, so one number is a thing the owner can disprove).
    A sheet scanned before the runs were kept carries one score; it prints as that score. None: not measured."""
    low, high = web.get("pagespeed_low"), web.get("pagespeed_high")
    if low is not None and high is not None:
        return str(high) if low == high else "%d to %d" % (low, high)
    s = web.get("pagespeed_score")
    return None if s is None else str(s)


# ------------------------------------------------ two points: their office and the town's center --
# Welton 2026-10-22: the map is local. Measured on 33 searches, the same search from the prospect's own address and from
# the town's center put them in a different map spot on 14 (receipt ops/receipts/20261022T111500_map-gap-measured.txt),
# and the owner checks from his own desk. Every map and organic line names where it searched from; no map claim
# without a stated point. Organic says page one or not, never a number (a rank moved up to seven places between points).

NO_DOOR = "no confirmed address"     # the door row's error when the listing (and so its address) is not confirmed
OFFICE = "your office"


def door_point(target):
    """(lat, lng) of the prospect's own listing, or None. Only a confirmed listing has an address to search from."""
    loc = (target or {}).get("location") or {}
    la, lo = loc.get("latitude"), loc.get("longitude")
    return (la, lo) if la is not None and lo is not None else None


def center(town):
    return "the center of %s" % town


def no_door(row):
    return row is None or (row or {}).get("error") == NO_DOOR


def map_point(row):
    """("in" | "out" | "unconfirmed" | "nopack" | "unchecked", rank, top 3) for one point's map row."""
    row = row or {}
    if row.get("error"):
        return "unchecked", None, []
    top = [t for t in (row.get("top_3") or []) if t][:3]
    if row.get("in_3_pack"):
        return "in", row.get("rank"), top
    if row.get("maybe_rank") or row.get("no_id"):
        return "unconfirmed", row.get("maybe_rank"), top
    if not top:
        return "nopack", None, []
    return "out", None, top


def _map_phrase(row, where):
    st, rank, _ = map_point(row)
    if st == "in":
        return "#%s searched from %s" % (rank, where)
    if st == "out":
        return "not in the top 3 searched from %s" % where
    if st == "unconfirmed":
        return ("couldn't confirm which card is yours (#%s may be you), searched from %s" % (rank, where) if rank
                else "couldn't confirm which card is yours, searched from %s" % where)
    if st == "nopack":
        return ("Google showed no map, searched from %s" % where if (row or {}).get("confirmed_empty")
                else "map results unconfirmed, searched from %s" % where)
    return "couldn't check, searched from %s" % where


def map_line(town_row, door_row, town):
    """One map line naming both points (wording approved by Welton 2026-10-22)."""
    c = center(town)
    t_st, t_rank, t_top = map_point(town_row)
    there = " (top 3 there: %s)" % ", ".join(t_top) if t_top and t_st != "in" else ""
    if t_st == "unchecked" and (no_door(door_row) or map_point(door_row)[0] == "unchecked"):
        return "couldn't check, searched from %s" % c + ("" if no_door(door_row) else " or from your office")
    if no_door(door_row):
        return _map_phrase(town_row, c) + there      # the office: office_note, once under the lines
    d_st, d_rank, _ = map_point(door_row)
    if d_st == "in" and t_st == "in":
        return "#%s searched from your office, #%s searched from %s" % (d_rank, t_rank, c)
    if d_st == "in" and t_st == "out":
        return "#%s searched from your office; not in the top 3 searched from %s%s" % (d_rank, c, there)
    if d_st == "out" and t_st == "in":
        return "#%s searched from %s; not in the top 3 searched from your office" % (t_rank, c)
    if d_st == "out" and t_st == "out":
        return "not in the top 3, searched from your office or from %s (top 3 from the center: %s)" % (
            c, ", ".join(t_top))
    return "%s; %s%s" % (_map_phrase(door_row, OFFICE), _map_phrase(town_row, c), there)


def page_one(row):
    """True / False when the organic results were read, None when they could not say."""
    if organic_failed(row) or (row or {}).get("organic_maybe"):
        return None
    r = (row or {}).get("rank")
    return bool(r) and r <= 10


def organic_line(town_row, door_row, town):
    """One organic line: page one or not, from both points, never a number (Welton 2026-10-22)."""
    c = center(town)
    say = lambda v: "page one" if v else "not on page one"
    t = page_one(town_row)
    above = [n for n in ((town_row or {}).get("above") or []) if n] if t is not None else []
    tail = " (ranked above you from the center: %s)" % ", ".join(above) if above else ""
    if t is None and (no_door(door_row) or page_one(door_row) is None):
        # Said once: neither point can give an answer.
        why = organic_text(town_row)
        return "%s, searched from %s%s" % ("Couldn't check" if why == "Couldn't check this search" else why, c,
                                           "" if no_door(door_row) else " or from your office")
    if no_door(door_row):
        head = ("%s, searched from %s" % (say(t), c)) if t is not None else "%s, searched from %s" % (organic_text(town_row), c)
        return head + tail                           # the office: office_note, once under the lines
    d = page_one(door_row)
    if t is None and d is None:
        return "%s, searched from your office and from %s" % (organic_text(town_row), c)
    if t is None:
        return "%s searched from your office; %s, searched from %s" % (say(d), organic_text(town_row), c)
    if d is None:
        return "%s searched from %s%s; couldn't check from your office" % (say(t), c, tail)
    if t == d:
        return ("page one, searched from your office and from %s%s" % (c, tail) if t
                else "not on page one, searched from your office or from %s%s" % (c, tail))
    return "%s from your office, %s from %s%s" % (say(d), say(t), c, tail)


def town_of(key):
    """The town a search row was measured in: 'funeral home / Depew' -> 'Depew'; a town-keyed row is the town."""
    return (key or "").split("/")[-1].strip()


def _names(names):
    names = ["<b>%s</b>" % escape(n) for n in names]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def map_bullet(items, who="Families"):
    """(score, text) for the map bullet, or None. items: (key, town row, office row, typed search) in sheet order.

    Wording approved by Welton 2026-10-22, with his change: say who Google shows, never what a family then does
    ("get those calls" was a claim nothing measured). Every sentence names the point it searched from.
    """
    picked, gaps = None, 0
    for key, town_row, door_row, typed in items:
        t_st, t_rank, t_top = map_point(town_row)
        d_st, d_rank, d_top = (None, None, []) if no_door(door_row) else map_point(door_row)
        q = "&quot;%s&quot;" % escape(typed)
        c = center(escape(town_of(key)))
        text = None
        # The point searched is named, never widened (Welton 2026-10-22, the footer check): the office line is the
        # listing's own pin, and half a mile away (OMNIACARE, Henderson) the map was different, so "from your own
        # neighborhood" was not true. `who` is kept for callers and no longer printed.
        if t_st == "out" and d_st == "in":
            text = ("Searched from your office, Google shows you at #%s for %s. Searched from %s, you're not in the top "
                    "3 on the map: Google shows %s instead." % (d_rank, q, c, _names(t_top)))
        elif t_st == "out" and d_st == "out":
            text = ("Searched from your office or from %s, you're not in the top 3 on the map for %s. From %s, Google "
                    "shows %s instead." % (c, q, c, _names(t_top)))
        elif t_st == "out":
            text = ("Searched from %s, you're not in the top 3 on the map for %s. Google shows %s instead."
                    % (c, q, _names(t_top)))
        elif t_st == "in" and d_st == "out" and d_top:
            text = ("Searched from %s, Google shows you at #%s for %s. Searched from your office, you're not in the "
                    "top 3: Google shows %s instead." % (c, t_rank, q, _names(d_top)))
        if text:
            gaps += 1
            picked = picked or text
    return (100 + gaps * 8, picked) if picked else None



def office_note(rows):
    """One line under a section when the office could not be searched (no confirmed address): said once, not per line."""
    return "From your office: couldn't check (no confirmed address)" if any(no_door(r) for r in rows) else None


# --------------------------------- a listing Google marks closed (Welton 2026-10-28, booth item 8) --
# Google's own businessStatus comes back on every Places lookup (google_intel.places_search keeps it as "status").
# When the prospect's confirmed listing is marked closed, the sheet says what Google shows, in Google's words, and does
# not grade that listing's reviews or map position; with those two out, no overall letter either (standing ruling 18).
# It says what Google shows, never what it means: for a cemetery a closed listing means the office or operator changed,
# never that the grounds closed (standing ruling 20). A rival Google marks closed is never named as one (open_rivals).
# Wording approved by Welton 2026-10-28, "temporarily closed" the same way with the word changed.

CLOSED_WORDS = {"CLOSED_PERMANENTLY": "permanently closed", "CLOSED_TEMPORARILY": "temporarily closed"}


def closed_word(place):
    """"permanently closed" / "temporarily closed" when Google's businessStatus says so; None otherwise (open, or not read)."""
    p = place or {}
    if not isinstance(p, dict) or p.get("error"):
        return None
    return CLOSED_WORDS.get(p.get("status") or "")


def listing_closed(results):
    """The closed word for the prospect's own listing in a scan's results, or None."""
    return closed_word(((results or {}).get("google_intel") or {}).get("target"))


def open_rivals(places):
    """The rivals Google does not mark closed: a closed listing is never named as a rival."""
    return [p for p in (places or []) if not closed_word(p)]


def closed_not_graded(word):
    """The note beside a blank grade (reviews, map)."""
    return "Not graded: Google shows this listing as %s." % word


def closed_overall(word):
    """Where the overall letter would be."""
    return "Not graded: Google shows your listing as %s." % word


def closed_confirm(word):
    """The rep's line at "Is this your address?"."""
    return "Google shows this listing as %s." % word


def _stars(rating):
    try:
        return "%.1f" % float(rating)
    except (TypeError, ValueError):
        return "-"


def closed_reviews_detail(target, word):
    """The sheet's reviews line: what Google shows, and what that listing shows, ungraded."""
    t = target or {}
    street = (t.get("address") or "").split(",")[0].strip()
    n = t.get("review_count") or 0
    return "Google shows your listing%s as %s. That listing shows %s %s, %s stars." % (
        " at %s" % street if street else "", word, n, reviews_word(n), _stars(t.get("rating")))


def closed_log_reviews(target, word):
    """The rep's live log, GOOGLE REVIEWS."""
    t = target or {}
    n = t.get("review_count") or 0
    return "%s %s, %s stars. %s Not graded." % (n, reviews_word(n), _stars(t.get("rating")), closed_confirm(word))


def closed_log_map_grade(word):
    """The rep's live log, the map section's grade line."""
    return "Grade: not graded (Google shows their listing as %s)" % word


def closed_map_line(town_row, door_row, town, word):
    """One map line for a closed listing: who Google showed, from each point searched (every map line names its point,
    Welton 2026-10-22), and no position for their listing."""
    parts = []
    for row, where in ((None if no_door(door_row) else door_row, OFFICE), (town_row, center(town))):
        if row is not None:
            top = map_point(row)[2]
            parts.append("top 3 searched from %s: %s" % (where, ", ".join(top)) if top else _map_phrase(row, where))
    head = "; ".join(parts)
    return "%s. Your listing: Google shows it as %s." % (head[:1].upper() + head[1:], word)

# ---------------------------------------------------------------- the double-read --
# Every search runs twice, from the town's center and from the office alike (office searches added by Welton
# 2026-10-28: "a single read can be wrong wherever it's searched from"); agreement prints. If the two reads disagree, one tiebreak read runs
# and the row prints only when two of the three agree; otherwise it is couldn't check, so "not on page one" never
# prints from a split result (Welton 2026-10-28). Why: the coordinate search sometimes comes back as a page that
# was not searched from the town (Valley View, Manhattan KS, 2026-10-28: 1 of 4 reads, plus the 11:50 run), and
# Google's answer says "Manhattan, KS" either way (receipt 20261028T233500).
SPLIT_READS = "couldn't check: %d reads of this search from the town's center did not agree"
SPLIT_READS_OFFICE = "couldn't check: %d reads of this search from your office did not agree"


def read_answer(row):
    """What the sheet prints from one read of a search, or None when the read failed. Ads are left out: they
    rotate between reads of the same page."""
    if failed(row):
        return None
    lp = row.get("local_pack") or {}
    return (row.get("rank"), bool(row.get("organic_error")), row.get("organic_maybe"),
            tuple(row.get("top_3") or ()), tuple(row.get("above") or ()),
            lp.get("rank"), lp.get("maybe_rank"), bool(lp.get("no_id")), bool(lp.get("confirmed_empty")),
            tuple((lp.get("card_ids") or [])[:3]), tuple(lp.get("top_3") or ()))


def agreed(rows):
    """The first row whose answer at least two of the reads share, else None."""
    keys = [read_answer(r) for r in rows]
    for row, key in zip(rows, keys):
        if key is not None and keys.count(key) >= 2:
            return row
    return None


def double_read(run_one, key, *point, split=SPLIT_READS):
    """(label, row) for one search, read as Welton ruled. run_one(key, *point) -> (label, row) is one read; `point`
    is the office's (lat, lng) for an office search, nothing for the town's center, and `split` names that point in
    the couldn't-check text. Both reads failed: the first read's own failure, as before. The row records how many
    reads it took."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = [f.result() for f in [pool.submit(run_one, key, *point) for _ in range(2)]]
    label, rows = first[0][0], [r for _, r in first]
    if all(failed(r) for r in rows):
        return label, rows[0]
    row = agreed(rows)
    if row is None:
        rows.append(run_one(key, *point)[1])
        row = agreed(rows)
    if row is None:
        return label, {"query": next((r.get("query") for r in rows if r and r.get("query")), None),
                       "rank": None, "top_3": [], "ads": [], "error": split % len(rows), "reads": len(rows)}
    return label, dict(row, reads=len(rows))
