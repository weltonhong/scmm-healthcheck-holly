"""What the booth sheet may say about the prospect's own ads: what was seen, on which searches, today.

Welton, 2026-10-20: "'not running' ads when they are running them" is one of the three things an owner
spots instantly. The sheet said "<business>: Not running" from one look at each search page. A business
whose ads run on other searches, at other hours or with a daily budget that was spent, is still
advertising. What was measured is narrower, and it is what the sheet now says (Welton's wording):

    "No ads seen on these 4 searches today"
    "Their ad was seen on 2 of these 4 searches today"
    "An ad under their name was seen on 1 of these 4 searches today (could not confirm it is theirs)"
    "Couldn't check any search for ads today"

An ad is theirs when its link is their website (their confirmed listing's); an ad under their name with
no readable link, or when their website is unknown, MAY be theirs and is never "running" or "not
running" (prospect_identity's rule: the name alone is never enough). Searches that failed are left out.

Identical copies live in all five booth tools' scripts/ folders;
tradeshow-healthcheck-homecare/scripts/test_booth_ads_words.py fails if they drift apart.
"""


import urllib.parse

import measured


def _bare_site(url):
    """True when a website is a whole domain of its own (no page path), not a page on a shared site."""
    s = (url or "").strip()
    if not s:
        return False
    if "://" not in s:
        s = "http://" + s
    try:
        return (urllib.parse.urlparse(s).path or "/") == "/"
    except ValueError:
        return False


def advertisers(ads, competitors, business, their_site):
    """Who the ads seen on one search can be named as: (names, unnamed count, competitor names).

    An ad's headline is its copy, not its maker (Welton, 2026-10-21): "Cremation Plots For Sale" and
    "Direct Cremation $795.00" printed as companies "paying Google". An ad is named only by its link:
      - on the prospect's own website: the prospect, as the rep typed the name;
      - on the website of exactly one competitor from Google's listings, when that website is a whole
        domain of its own: that competitor. A page on a shared site (a Dignity Memorial or franchise
        page) does not name anyone, because the parent's own ads link to the same domain.
    Every other ad is counted and named by nobody ("an ad was seen").
    """
    names, comps, unnamed, seen = [], [], 0, set()
    for ad in ads or []:
        ad = ad or {}
        link = ad.get("domain") or ""
        key = measured._site(link) or (ad.get("name") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        who = None
        if their_site and measured.on_their_site(link, their_site):
            who = business
        else:
            owners = [(c.get("name") or "").strip() for c in (competitors or [])
                      if _bare_site(c.get("website")) and measured.on_their_site(link, c.get("website"))]
            owners = [o for o in owners if o]
            if len(set(owners)) == 1:
                who = owners[0]
                if who not in comps:
                    comps.append(who)
        if who:
            if who not in names:
                names.append(who)
        else:
            unnamed += 1
    return names, unnamed, comps


def row_text(names, unnamed, open_lane=False):
    """One search's ads line: the named advertisers, then how many ads nobody can be named for."""
    named = ", ".join((names or [])[:3])
    if named and unnamed:
        return "%s, plus %s" % (named, "1 more ad" if unnamed == 1 else "%d more ads" % unnamed)
    if named:
        return named
    if unnamed:
        return "An ad was seen" if unnamed == 1 else "%d ads were seen" % unnamed
    return none_seen(open_lane)


def _searches(n):
    return "this search" if n == 1 else "these %d searches" % n


def summary(ads_per_search, labels):
    """The one line about the prospect's own ads."""
    rows = [(ads_per_search or {}).get(l) or {} for l in labels]
    read = [r for r in rows if not r.get("error")]
    if not read:
        return "Couldn't check any search for ads today"
    seen = sum(1 for r in read if r.get("prospect_running_ads"))
    maybe = sum(1 for r in read if not r.get("prospect_running_ads") and r.get("prospect_maybe_ad"))
    n = len(read)
    if seen:
        return "Their ad was seen on %d of %s today" % (seen, _searches(n)) if n > 1 else \
            "Their ad was seen on this search today"
    if maybe:
        return ("An ad under their name was seen on %d of %s today (could not confirm it is theirs)"
                % (maybe, _searches(n))) if n > 1 else \
            "An ad under their name was seen on this search today (could not confirm it is theirs)"
    if all(r.get("theirs_unknown") for r in read):
        # Their ad is known only by its link to their website; with no website, nothing can say that
        # none of these ads was theirs (Welton 2026-10-21).
        return "Couldn't check for their ads today (no website to recognize them by)"
    return "No ads seen on %s today" % _searches(n)


def none_seen(open_lane=False):
    """One search's line when its ad block was read and held no ads."""
    return "No ads seen" + (" (open lane)" if open_lane else "")
