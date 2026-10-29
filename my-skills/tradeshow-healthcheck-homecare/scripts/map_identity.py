"""Which map card is the prospect: by Google's place id, never by the name alone (Welton, 2026-10-20).

Before this, a booth map card was the prospect only when its NAME matched
(name_matcher). Forest Lawn Memorial Park's own card reads "Forest Lawn", the
names did not match, and the sheet printed NOT FOUND for a search Forest Lawn
was on, then (once the 10-20 headline named who holds the top map spots) told
Forest Lawn it was losing to Forest Lawn.

WHAT A CARD CARRIES. The booth's search answer (ScrapingBee /api/v1/google,
local_results) gives each card a title, rating, review count, position and
`cid`, Google's place id. No phone, no street. The prospect's own Google
listing (quick-intel/scripts/google_intel.py, the Places lookup every scan
makes) carries the same id in its maps link (?cid=...). Measured 2026-10-20
on recorded real calls: Forest Lawn's listing cid 16065574039465269550 is the
"Forest Lawn" card on "cemetery Glendale CA" (#3) and "cemetery plots
Glendale CA" (#1); Home Instead Bellevue's listing cid is its #2 card on
"home care Bellevue WA" (fixtures/own_listings_recorded.json,
fixtures/booth_serp_recorded.json).

THE VERDICT, per card (the pre-call rule, pre-call-audit/scripts/pack_identity
.card_verdict, with the place id where pre-call has a phone or street):

  THEM       the card's cid is one of the prospect's own listings' cids
  CANT_TELL  the name points at the prospect but the id does not confirm it
             (another location, or another business with that name); or, with
             no listing id to compare, the names agree only loosely
  NOT_THEM   nothing on the card points at the prospect

With no listing id to compare (no listing confirmed), a name alone never says THEM and never says
NOT_THEM (Welton's standing ruling, 2026-10-21): judge_pack returns the row with no_id, the card the
name points at as "may be you", and the row reads "Couldn't confirm". A CANT_TELL card is never a
rank and never a miss: the map row reads "couldn't confirm (#N may be you)", leaves the grade, and
is not named as a competitor.

Name evidence is pre-call's own (pack_identity.py, copied byte for byte into
this folder): the full-name rule (legacy_name_match) and a shared distinctive
word. Not the booth's old fuzzy name_matches: with no id to compare it counted
"Forest Lawn Museum" as Forest Lawn Memorial Park, #1 on "cemetery Glendale
CA" (recorded), where the place id puts Forest Lawn at #3.

Identical copies of this file and of pack_identity.py live in all five booth
tools' scripts/ folders;
tradeshow-healthcheck-homecare/scripts/test_booth_map_identity.py fails if any
copy drifts, from each other or from pre-call.
"""
import re

import pack_identity

THEM = pack_identity.THEM
CANT_TELL = pack_identity.CANT_TELL
NOT_THEM = pack_identity.NOT_THEM

_CID = re.compile(r"[?&]cid=(\d+)")


def cid_of(maps_url):
    """The place id in a Google maps link ('...?cid=16065574039465269550&...'), or None."""
    m = _CID.search(maps_url or "")
    return m.group(1) if m else None


def share_a_distinctive_word(business, card_name):
    """True when the two names share a word that is not a trade or place word.

    Not pack_identity.names_agree itself: its "one name sits inside the other"
    clause also fires when the smaller name is ALL generic words, so "The Home
    Care Company" agreed with "Bayada Home Health Care" (recorded "home care
    Bellevue WA" card, 2026-10-20). Uses pack_identity's own tokens and
    distinctiveness test.
    """
    a = set(pack_identity._agree_tokens(business))
    b = set(pack_identity._agree_tokens(card_name))
    toks = pack_identity.PRECALL_MATCH_TOKENS
    return any(pack_identity._is_distinctive(w, tokens=toks) for w in a & b)


def verdict(card_name, card_cid, business, own_cids):
    """THEM, CANT_TELL or NOT_THEM for one map card."""
    loose = share_a_distinctive_word(business, card_name)
    strict = pack_identity.legacy_name_match(card_name, business)
    if own_cids and card_cid:
        if str(card_cid) in own_cids:
            return THEM
        return CANT_TELL if (strict or loose) else NOT_THEM
    if strict:
        return THEM
    return CANT_TELL if loose else NOT_THEM


def judge_pack(cards, business, own_cids):
    """The pack row from up to three cards [(name, cid)].

    {"rank": first THEM position or None, "in_3_pack": bool,
     "maybe_rank": first CANT_TELL position when no card is THEM, else None,
     "top_3": [names], "card_ids": [cids]}
    """
    own = {str(c) for c in (own_cids or ()) if c}
    cards = [(n, c) for n, c in cards if n][:3]
    rank = maybe = None
    for i, (name, cid) in enumerate(cards, 1):
        v = verdict(name, cid, business, own)
        if v == THEM and rank is None:
            rank = i
        elif v == CANT_TELL and maybe is None:
            maybe = i
    # A name prints once (Welton 2026-10-20): "Star Mortuary, Star Mortuary" on La Paloma's Boulder City
    # row was one business with two Google listings at 900 Nevada Way (star_mortuary_recorded.json).
    # Positions above still count every card, so a prospect behind both is #3.
    # Both listings count, and the name says so (Welton 2026-10-28): "Sunrise Cemetery (2 listings)". Google
    # showed Manhattan KS's "cemetery plots" top 3 as Sunrise, Sunset, Sunrise (two place ids), which printed
    # as two names (receipt 20261028T233500).
    names = []
    for n, _ in cards:
        if n not in names:
            names.append(n)
    count = {n: sum(1 for m, _ in cards if m == n) for n in names}
    names = [n if count[n] == 1 else "%s (%d listings)" % (n, count[n]) for n in names]
    if not own:
        # No confirmed listing id: a name alone never says found and never says not found (Welton's
        # standing ruling, 2026-10-21: never identify a business by name alone). The row reads
        # "Couldn't confirm"; a card the name points at keeps its position as "may be you".
        return {"rank": None, "in_3_pack": False, "maybe_rank": rank or maybe, "no_id": True,
                "top_3": names, "card_ids": [c for _, c in cards]}
    return {"rank": rank, "in_3_pack": rank is not None,
            "maybe_rank": None if rank is not None else maybe,
            "top_3": names, "card_ids": [c for _, c in cards]}


def own_cids(target, business):
    """The prospect's own listing place id, as a list, from the listing the sheet uses for them.

    Only when that listing's name agrees with the business (pre-call's name
    rules): the listing is Google's first answer for the name, which can be
    another business, and its id must not turn that business's card into the
    prospect's. Other same-name listings (another location, another franchise
    owner) are left out on purpose: their cards read CANT_TELL, never THEM.
    """
    target = target or {}
    name = target.get("name") or ""
    cid = cid_of(target.get("maps_url"))
    if cid and (pack_identity.legacy_name_match(name, business) or share_a_distinctive_word(business, name)):
        return [cid]
    return []
