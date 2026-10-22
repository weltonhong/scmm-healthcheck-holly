"""The booth sheet's headline, built only from what the scan measured (Welton, 2026-10-20).

Replaces two things:

1. The "lost calls" figure ("12-24 families searched ... and called your
   competitors instead of you"). It was a rule of thumb (5-10 families per map
   pack missed, 3-6 per ads gap) printed as a fact about last month. Welton's
   ruling: drop it, say what was measured: the searches they are missing
   from, and who shows up instead.
2. "You're winning in funeral home / Las Vegas", which counted a search as
   won on the regular results alone. On the 10-20 La Paloma sheet it said
   "winning" for a search whose map section, on the same page, said NOT FOUND,
   and never mentioned Henderson, also NOT FOUND on the map. It also printed
   the search label "funeral home / Las Vegas" as if it were a place.

The headline names every search where the prospect is missing from the map
(measured: a map pack came back and they are not in it), and who is on the map
for the first of them. It never calls a search won: a #1 in the regular
results sits under the map in the SEO section, where the sheet already says
so (the headline stayed short enough to keep the map section on page one). A
search that could not be checked is left out. With no measured gap there is
no headline.

Cremation never leads (.claude/rules/prospect-copy.md): cremation searches
are listed after the others, and when cremation searches are the only gap the
headline opens with what was measured for the other searches; if nothing was
measured for them, there is no headline.

Identical copies live in all five booth tools' scripts/ folders;
tradeshow-healthcheck-homecare/scripts/test_booth_headline.py fails if they
drift apart.
"""
from xml.sax.saxutils import escape

UNSCANNED = "UNSCANNED"
NO_PACK = "NO_PACK"
IN_PACK = "IN_PACK"
ABSENT_FROM_PACK = "ABSENT_FROM_PACK"
UNCONFIRMED = "UNCONFIRMED"

def map_status(row):
    """Same four states as each pdf_generator.pack_status (pinned by the test)."""
    row = row or {}
    if row.get("error"):
        return UNSCANNED
    if row.get("in_3_pack"):
        return IN_PACK
    if row.get("maybe_rank") or row.get("no_id"):
        # A card may be theirs but its place id did not confirm it
        # (scripts/map_identity.py): never a rank, never a miss.
        return UNCONFIRMED
    if not [t for t in (row.get("top_3") or []) if t]:
        return NO_PACK
    return ABSENT_FROM_PACK


def organic_rank(row):
    """Rank 1-10 on page one, 0 when measured and not on page one, None when not measured."""
    row = row or {}
    if row.get("error") or row.get("organic_error") or "rank" not in row:
        return None
    r = row.get("rank")
    return r if isinstance(r, int) and 1 <= r <= 10 else 0


def keyword_and_town(label, seo_row=None, state=""):
    """('funeral home', 'Las Vegas'): what the family typed, and the town it was measured in.

    Bucket tools label a search 'funeral home / Las Vegas'; the home care tools
    label it by town ('Tampa') and keep the query on the search row ('home care
    Tampa FL'). Returns (None, query) when the two cannot be told apart.
    """
    label = label or ""
    if "/" in label:
        kw, town = [" ".join(x.split()) for x in label.split("/", 1)]
        return kw, town
    words = ((seo_row or {}).get("query") or "").split()
    if words and state and words[-1].upper() == state.upper():
        words = words[:-1]
    town = " ".join(label.split())
    q = " ".join(words)
    if town and q.endswith(" " + town):
        return q[:-len(town)].strip(), town
    return None, q or town


def _is_cremation(label):
    return "cremation" in (label or "").lower()


def _join(items, word="and"):
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " %s " % word + items[-1]


def _phrase(labels, split, word="or"):
    """'"funeral home" in Las Vegas, Henderson or Boulder City, or "cremation" in Las Vegas'."""
    groups = []
    for l in labels:
        kw, town = split(l)
        key = kw if kw is not None else ("", town)
        for g in groups:
            if g[0] == key:
                g[1].append(town)
                break
        else:
            groups.append([key, [town]])
    towns_all = _distinct([t for _, ts in groups for t in ts])
    if len(groups) > 1 and len(towns_all) == 1 and not any(isinstance(k, tuple) for k, _ in groups):
        # one town, several searches: '"home health" or "home health agency" in Philadelphia'
        return "%s in %s" % (_join(["&quot;%s&quot;" % escape(k) for k, _ in groups], word), escape(towns_all[0]))
    parts = []
    for key, towns in groups:
        if isinstance(key, tuple):
            parts.append("&quot;%s&quot;" % escape(towns[0]))
        else:
            parts.append("&quot;%s&quot; in %s" % (escape(key), _join([escape(t) for t in towns], word)))
    if len(parts) > 1 and any("," in x or " %s " % word in x for x in parts):
        return ", ".join(parts[:-1]) + ", %s " % word + parts[-1]
    return _join(parts, word)


def _distinct(names):
    out = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out


def measured_headline(results, searchers="Families"):
    """The headline text (reportlab markup), or None when nothing measured is a gap."""
    pack = (results.get("3pack") or {}).get("results") or {}
    seo = results.get("seo") or {}
    labels = sorted(results.get("buckets") or list(pack.keys()), key=_is_cremation)
    state = results.get("state") or ""
    who = searchers.lower()

    def split(label):
        return keyword_and_town(label, seo.get(label), state)

    off_map = [l for l in labels if map_status(pack.get(l)) == ABSENT_FROM_PACK]
    if off_map:
        lines = []
        if all(_is_cremation(l) for l in off_map):
            # Cremation must not lead: open with what was measured for the rest.
            on_map = [l for l in labels if not _is_cremation(l) and map_status(pack.get(l)) == IN_PACK]
            if not on_map:
                return None
            lines.append("You're on the Google map for %s." % _phrase(on_map, split, "and"))
        lines.append("When %s search %s, you're not on the Google map." % (who, _phrase(off_map, split)))
        first = off_map[0]
        rivals = [escape(n) for n in _distinct((pack.get(first) or {}).get("top_3") or [])[:2]]
        if rivals:
            lines.append("%s %s the top map %s for %s." % (
                _join(rivals), "holds" if len(rivals) == 1 else "hold",
                "spot" if len(rivals) == 1 else "spots", _phrase([first], split)))
        return " ".join(lines)

    off_page_one = [l for l in labels if organic_rank(seo.get(l)) == 0]
    if off_page_one and not all(_is_cremation(l) for l in off_page_one):
        return "When %s search %s, you're not on page one of Google." % (who, _phrase(off_page_one, split))
    return None
