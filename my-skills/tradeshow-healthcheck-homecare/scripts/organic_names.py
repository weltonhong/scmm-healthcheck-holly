"""The names printed in a booth sheet's organic "Top 3": real business names, on their own sites (Welton, 2026-10-20).

The La Paloma sheet (Las Vegas, NV, 10-20) printed "Mapquest", "Clarkcountynv", "Andresfmc",
"Affordablecbs", "Wecarelv", "After" and "Bouldercityreview" as the businesses ranking on page one, and
the prospect itself as "Lapaloma Funeral Services". Every one was the web address turned into a name,
filtered by a fixed list of directory sites. Re-run on 10-20 (fixtures/la_paloma_serp_recorded.json),
the pages behind them were: a MapQuest listing and a Boulder City Review obituary page, both about
Boulder City Family Mortuary; the county's "Burials and Cremation" page; three after.com pages titled
"... Direct Cremation Services"; and real businesses whose names the address garbled.

THE RULE, on evidence, not a list (fix-hierarchy: prefer evidence over enumeration):
  1. The prospect's own site prints the prospect's name, written properly (pre-call's
     name_format.for_prospect). Never a name made from their web address.
  2. Anyone else's name comes from the page TITLE (Quick Intel's _extract_competitor_name), cut at a
     colon or bar ("Serenity Funeral Home: Funeral Provider"), never from the web address: a page whose title
     names no business ("TOP 10 BEST Funeral Homes in Las Vegas, NV" on yelp.com) gives no name.
  3. It must pass Quick Intel's is_real_seo_name (reads as a business name, and every distinctive word
     is in the site's address), hand-checked on 100 real names
     (quick-intel-ranking/tests/fixtures/seo_names_hand_checked_100.json).
  4. And the address must be THAT business's own: with the name's words, trade words and the searched
     town taken out of the site's main address, at most LEFTOVER_MAX letters may remain. "Boulder City Family Mortuary" on
     obituaries.bouldercityreview.com leaves "review": a newspaper, not the mortuary.
  The old fixed directory list stays as an extra skip (it can only remove a name, never let one in).
A result that fails prints nothing: the Top 3 gets shorter rather than wrong.

hook_generator.py and name_format.py are Quick Intel's and pre-call's own files, copied byte for byte;
identical copies of this file live in all five booth tools' scripts/ folders.
tradeshow-healthcheck-homecare/scripts/test_booth_organic_names.py fails if any copy drifts.
"""
import re

import hook_generator as hg
import measured
import name_format

LEFTOVER_MAX = 3


def _main_label(host):
    """'obituaries.bouldercityreview.com' -> 'bouldercityreview'."""
    labels = [x for x in hg._norm_host(host).split(".") if x]
    return re.sub(r"[^a-z0-9]", "", labels[-2] if len(labels) >= 2 else (labels[0] if labels else ""))


def _words(name):
    return [w.replace("'", "") for w in re.findall(r"[a-z0-9']+", (name or "").lower()) if w]


def leftover(name, host, town=""):
    """How many letters of the site's main address are NOT the name's words, trade words or the town.

    The address is split into words, the best split counted (not a greedy one: "funerals" must not eat
    the "s" of "davisfuneralservices"). A town in the address ("milesfuneralhomewinfield") is allowed.
    """
    stem = _main_label(host)
    vocab = {w for w in set(_words(name)) | set(hg._NAME_GENERIC) | set(_words(town)) if len(w) >= 2}
    best = [0] + [None] * len(stem)
    for i in range(1, len(stem) + 1):
        best[i] = best[i - 1] + 1
        for w in vocab:
            if i >= len(w) and stem[i - len(w):i] == w and best[i - len(w)] < best[i]:
                best[i] = best[i - len(w)]
    return best[len(stem)]


def title_name(title):
    """The business name a page title carries, or '' (never the web address)."""
    name = hg._extract_competitor_name(title or "", "")
    name = re.split(r"[:|]", name)[0]
    return hg._strip_brand_symbols(name).strip()


def competitor_name(title, host, town=""):
    """The name to print for someone else's page-one result, or None.

    The searched town's words are left out of Quick Intel's check (not out of the name printed):
    "Forest Lawn Glendale Cemetery" on forestlawn.com is the business's own page, and "Glendale" is
    the town, not a word its address has to carry.
    """
    name = title_name(title)
    if not name:
        return None
    check = name
    for w in _words(town):
        check = re.sub(r"(?i)\b%s\b" % re.escape(w), " ", check)
    check = " ".join(check.split())
    # A name that is only the town and trade words ("Las Vegas Cremations") is checked whole.
    real = hg.is_real_seo_name(check, host) or hg.is_real_seo_name(name, host)
    if real and leftover(name, host, town) <= LEFTOVER_MAX:
        return name
    return None


def top_names(results, prospect_site, prospect_name, k=3, skip=lambda r: False, town=""):
    """Up to k names, in page order: the prospect's own (properly written) and real competitors.

    `results` are page-one rows {title, domain, position}; `skip(row)` is the tool's old directory hint;
    `town` is the town searched.
    """
    out = []
    for r in results or []:
        pos = r.get("position")
        if pos is not None and pos > 10:
            continue
        host = re.sub(r"^https?://", "", (r.get("domain") or "")).split("/")[0]
        if not host:
            continue
        if prospect_site and measured.page_verdict(r.get("url") or host, prospect_site) == measured.THEM:
            name = name_format.for_prospect(prospect_name)
        elif skip(r):
            continue
        else:
            name = competitor_name(r.get("title"), host, town)
        if name and name.lower() not in [n.lower() for n in out]:
            out.append(name)
            if len(out) >= k:
                break
    return out
