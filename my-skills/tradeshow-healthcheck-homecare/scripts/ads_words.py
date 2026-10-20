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


def _searches(n):
    return "this search" if n == 1 else "these %d searches" % n


def summary(ads_per_search, labels):
    """The one line about the prospect's own ads."""
    rows = [(ads_per_search or {}).get(l) or {} for l in labels]
    measured = [r for r in rows if not r.get("error")]
    if not measured:
        return "Couldn't check any search for ads today"
    seen = sum(1 for r in measured if r.get("prospect_running_ads"))
    maybe = sum(1 for r in measured if not r.get("prospect_running_ads") and r.get("prospect_maybe_ad"))
    n = len(measured)
    if seen:
        return "Their ad was seen on %d of %s today" % (seen, _searches(n)) if n > 1 else \
            "Their ad was seen on this search today"
    if maybe:
        return ("An ad under their name was seen on %d of %s today (could not confirm it is theirs)"
                % (maybe, _searches(n))) if n > 1 else \
            "An ad under their name was seen on this search today (could not confirm it is theirs)"
    return "No ads seen on %s today" % _searches(n)


def none_seen(open_lane=False):
    """One search's line when its ad block was read and held no ads."""
    return "No ads seen" + (" (open lane)" if open_lane else "")
