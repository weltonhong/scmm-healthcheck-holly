"""Is this Google result the same business as this Keap record?

A DIFFERENT QUESTION FROM serp_helpers.name_matches, and deliberately its own
module. That one asks "does this SERP card name our prospect", is tuned for
ranking cards, and `.claude/rules/name-matching.md` records that tightening one
of its failure modes loosens the other. Loosening it to suit this question
would change every ranking card. One importable definition, used by the card
queue and by the Quick Intel target check.

THE NAME RULE, loosened 2026-09-23 (Welton). Equal after normalising, or one
name's distinctive words contained in the other's:

    Journey Hospice              ==  Journey Hospice of Alabama     contained
    Watson Funeral Services      ==  Watson's Funeral Services      apostrophe
    Patrick S Piercy             ==  Piercy Patrick S               word order
    BrightStar Care              ==  BrightStar Care(R) S. S.F.V.   contained
    ComForCare Home Care         !=  Comfort Keepers Home Care      different

THE PLACE RULE, and why containment is held to a higher standard. A contained
name is how a chain names its branches, so "Home Instead" matches the Keap
record of every Home Instead in the country and only the town tells them
apart. An EQUAL name is strong on its own, so the state will do.

    contained name  ->  the address must carry the CONTACT'S CITY
    equal name      ->  the city, or failing that the state

That is what keeps First Choice of Orem from being verified against the Lehi
branch thirty minutes up the road, whose reviews are not theirs, while still
verifying Full Spectrum of Madison as NOT the Full Spectrum in Cincinnati.
"""
import json
import re
import sys
import time
from pathlib import Path

# Words that say what the business does rather than which business it is.
GENERIC = frozenset("""
    home homes care cares caring health healthcare hospice hospices funeral
    funerals service services agency agencies senior seniors living center
    centre centers crematory crematories cremation cremations chapel chapels
    mortuary memorial memorials cemetery cemeteries nursing group associates
    of the and a an at for in llc inc ltd co corp pc pllc company incorporated
    limited partners partnership dba
""".split())
_PUNCT = re.compile(r"[^a-z0-9]+")
_SYMBOLS = ("®", "™", "℠", "©")


# ABBREVIATIONS ARE NOT DIFFERENT NAMES. Mount Calvary is Mt Calvary, McKee is
# Mc Kee, LaVigne is La Vigne. Applied to names AND addresses so both sides are
# spelled the same way before anything is compared.
EXPAND = {"mt": "mount", "ste": "sainte", "ft": "fort", "st": "saint",
          # PERSONAL-NAME ABBREVIATIONS, added 2026-09-23 after "WM.  Murphy
          # Funeral Home, Inc" was refused against "William Murphy Funeral
          # Home Inc" at 349 Adams St in the contact's OWN town.
          #
          # Only what the book actually contains. An expansion can only make
          # two names MORE likely to agree, and agreeing wrongly is the
          # expensive direction here -- it is the whole failure this module
          # exists to stop -- so a speculative entry is not free.
          #
          # Scanned 8,668 company and Google names from the carded book plus
          # the live queue: "wm" (the case above) and "chas" (Chas E. Davis
          # Funeral Home) occur. "geo", "jas", "thos", "robt" and "jos" do
          # not, so they are left out until one turns up.
          #
          # "rich" was considered and REJECTED: it occurs twice, both times in
          # "Thoma/Rich, Lemler Funeral Home", where it is a surname and not
          # short for Richard. Expanding it would corrupt a real name.
          "wm": "william", "chas": "charles"}
PARTICLES = ("mc", "mac", "la", "le", "de", "du", "van", "von", "o")


def _fold_abbreviations(words):
    out = []
    for w in words:
        out.append(EXPAND.get(w, w))
    joined, i = [], 0
    while i < len(out):
        if out[i] in PARTICLES and i + 1 < len(out):
            joined.append(out[i] + out[i + 1])       # "mc kee" -> "mckee"
            i += 2
        else:
            joined.append(out[i])
            i += 1
    return joined


def normalise(name):
    s = (name or "").lower()
    for ch in _SYMBOLS:
        s = s.replace(ch, " ")
    s = s.replace("&", " and ")
    # A POSSESSIVE IS NOT A DIFFERENT NAME. Dropping the apostrophe alone turns
    # "Watson's" into "watsons", which then does not equal "watson", so the
    # trailing s goes with it.
    s = re.sub(r"[’']s\b", "", s)
    s = s.replace("'", "").replace("’", "")
    return _fold_abbreviations([w for w in _PUNCT.sub(" ", s).split() if w])


US_STATES = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas", "ca": "california",
    "co": "colorado", "ct": "connecticut", "de": "delaware", "fl": "florida", "ga": "georgia",
    "hi": "hawaii", "id": "idaho", "il": "illinois", "in": "indiana", "ia": "iowa",
    "ks": "kansas", "ky": "kentucky", "la": "louisiana", "me": "maine", "md": "maryland",
    "ma": "massachusetts", "mi": "michigan", "mn": "minnesota", "ms": "mississippi",
    "mo": "missouri", "mt": "montana", "ne": "nebraska", "nv": "nevada", "nh": "new hampshire",
    "nj": "new jersey", "nm": "new mexico", "ny": "new york", "nc": "north carolina",
    "nd": "north dakota", "oh": "ohio", "ok": "oklahoma", "or": "oregon", "pa": "pennsylvania",
    "ri": "rhode island", "sc": "south carolina", "sd": "south dakota", "tn": "tennessee",
    "tx": "texas", "ut": "utah", "vt": "vermont", "va": "virginia", "wa": "washington",
    "wv": "west virginia", "wi": "wisconsin", "wy": "wyoming", "dc": "district of columbia",
}


def state_words(state):
    """A state written either way, as words to ignore inside a company name.

    "ComForCare Home Care (La Jolla, CA)" carries its own state, and Google's
    listing does not; without this the stray "ca" made the two names disagree.
    """
    s = (state or "").strip().lower()
    code = s if s in US_STATES else next((c for c, n in US_STATES.items() if n == s), None)
    if not code:
        return set()
    return {code} | set(US_STATES[code].split())


def distinctive(name, ignore=()):
    """The words that identify the business, in no particular order."""
    drop = GENERIC | set(ignore)
    return {w for w in normalise(name) if w not in drop and len(w) > 1}


def _one_edit_apart(a, b):
    """True when two words differ by a single character. Five letters or more,
    so short words cannot collide: Sorenson and Sorensen are the same funeral
    home, but "east" and "west" are not the same anything."""
    if a == b or min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        if len(diff) == 1:
            return True
        # A SWAPPED PAIR IS ONE TYPO TOO: "Caring Seinor Service" is Caring
        # Senior Service, typed in a hurry, not another company.
        if len(diff) == 2 and diff[1] == diff[0] + 1:
            i = diff[0]
            return a[i] == b[i + 1] and a[i + 1] == b[i]
        return False
    short, long = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(long)):                       # one insertion
        if long[:i] + long[i + 1:] == short:
            return True
    return False


def _align_one_typo(da, db):
    """Fold at most ONE pair of near-identical words together, so a single
    misspelling does not read as a different business. At most one: two
    differences are a different name, not a typo."""
    only_a, only_b = da - db, db - da
    for wa in sorted(only_a):
        for wb in sorted(only_b):
            if _one_edit_apart(wa, wb):
                return (da - {wa}) | {wb}, db
    return da, db


CORPORATE = frozenset("llc inc ltd co corp pc pllc company incorporated limited dba".split())


def _full(name):
    """Every word that is part of the name, corporate suffixes aside."""
    return {w for w in normalise(name) if w not in CORPORATE}


def _squash(name, ignore=()):
    """The whole name with every space taken out, so spacing alone cannot make
    two names differ. Generic words are KEPT: dropping them would squash
    "Caring Senior Service" to "caring" and match far too much."""
    return "".join(w for w in normalise(name) if w not in set(ignore))


def name_relation(a, b, ignore=()):
    """'equal', 'contained' or None.

    EQUAL MEANS THE WHOLE NAME AGREES, not just the distinctive part. Judging
    equality on distinctive words alone made "A Caring Touch Home Health" equal
    to "Caring Touch Health Services Inc" -- the generic list had erased the
    difference -- and the equal rule then let the state stand in for the city,
    verifying a Rosemont prospect against a business in Chicago. Anything
    weaker than a whole-name match is 'contained', which must have the city.
    """
    ig = set(ignore)
    fa, fb = _full(a) - ig, _full(b) - ig
    if fa and fa == fb:
        return "equal"
    # SPACING IS NOT A DIFFERENT NAME. "Green-Wood" is "Greenwood", "CareTeam"
    # is "Care Team", "Hopehomecarellc" is "Hope Home Care LLC". Word sets
    # cannot see this: {green, wood} and {greenwood} share nothing. Absorbed
    # from batch_quick_intel._same_business_compact on 2026-09-24, which was a
    # second opinion about the same question and did not know about
    # abbreviations, so it listed a prospect as its own competitor.
    ca, cb = _squash(a, ig), _squash(b, ig)
    if ca and ca == cb:
        return "equal"
    da, db = distinctive(a, ig), distinctive(b, ig)
    if not da or not db:
        # NOTHING DISTINCTIVE LEFT ON ONE SIDE. "Caring Senior Service" is
        # every-word-generic, so giving up here called it a different business
        # from "Caring Senior Service of Long Beach" at the same address. Fall
        # back to the whole name, which still has to agree or be contained.
        if not fa or not fb:
            return None
        if fa == fb:
            return "equal"
        fa2, fb2 = _align_one_typo(fa, fb)
        if fa2 == fb2 or fa2 <= fb2 or fb2 <= fa2:
            return "contained"
        return None
    if da == db:
        # The distinctive words agree but the whole names do not, so the
        # generic list did the agreeing. Weaker than equal.
        return "contained"
    da, db = _align_one_typo(da, db)
    if da == db:
        return "equal"
    if da <= db or db <= da:
        return "contained"
    wa = [w for w in normalise(a) if w not in ig]
    wb = [w for w in normalise(b) if w not in ig]
    if ca and cb and (_squash_inside(wa, wb) or _squash_inside(wb, wa)):
        # One squashed name inside the other: a sub-location, the way
        # "Greenwood Entrance at Prospect Park" belongs to "Greenwood
        # Cemetery". Contained, so it still has to carry the city. ON WORD
        # BOUNDARIES (Welton 2026-10-22): as plain letters "Ark Health Services"
        # sat inside "Clark Health Services" and the two were one business.
        return "contained"
    return None


def _squash_inside(short_words, long_words):
    """The short name, spaces taken out, equals a run of whole words of the long one, spaces taken out."""
    target = "".join(short_words)
    if not target:
        return False
    for i in range(len(long_words)):
        acc = ""
        for w in long_words[i:]:
            acc += w
            if acc == target:
                return True
            if len(acc) >= len(target):
                break
    return False


def state_code(state):
    """'MO' for 'mo', 'MO' or 'Missouri'; None when it is not a state."""
    s = (state or "").strip().lower()
    code = s if s in US_STATES else next((c for c, n in US_STATES.items() if n == s), None)
    return code.upper() if code else None


def address_state(address):
    """The state out of "1 Main St, Springfield, MO 65806, USA" ('MO'), or None.

    Read from the address's own state part, the last segment (Welton 2026-10-22, A3): a state code anywhere in the
    words read "Co Rd 5" as Colorado, and joined "Dover, DE 19901" into one word and missed Delaware."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    parts = [p for p in parts if p.upper() not in ("USA", "US", "UNITED STATES")]
    if not parts:
        return None
    tail = parts[-1].split()
    return state_code(tail[0]) if tail else None


def _city_in(address, city):
    """The contact's town is the ADDRESS'S town (A3): "500 Lincoln Ave, Omaha" is not in Lincoln."""
    if not city:
        return False
    town = address_city(address)
    return bool(town) and bool(set(normalise(city)) <= set(normalise(town)))


def _state_in(address, state):
    want = state_code(state)
    return bool(want) and address_state(address) == want


def _digits(phone):
    d = "".join(c for c in (phone or "") if c.isdigit())
    return d[-10:] if len(d) >= 10 else ""


def same_phone(a, b):
    """The same ten-digit number, punctuation and a leading 1 aside."""
    da, db = _digits(a), _digits(b)
    return bool(da) and da == db


# SIX MILES (Welton, 2026-09-23), and the number is load-bearing. The rule
# exists for a listing that sits just outside the town line, not for the next
# market along. At 6: Highland Village is 4 miles from Lewisville (same
# business, accepted), Lehi is 11 from Orem (a different branch with its own
# reviews, refused), Chicago is 15 from Rosemont (refused). At 12 the Lehi
# branch was accepted, which was the one thing the looser rule made worse.
NEIGHBOUR_MILES = 6


def address_city(address):
    """The town out of "1 Main St, Whitehall Township, PA 18052, USA"."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    parts = [p for p in parts if p.upper() not in ("USA", "US")]
    if len(parts) < 2:
        return ""
    tail = parts[-1].split()                      # "PA 18052"
    return parts[-2] if tail and len(tail[0]) <= 3 else parts[-1]


def _miles(a, b):
    import math
    R = 3958.8
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


# TOWNS WE HAVE PLACED BEFORE. A geocoder wobble is not evidence about a
# business, and on 2026-09-23 one cost a card: Sunset Haven Hospice of
# Lewisville TX was refused against its own listing in Highland Village,
# 4.4 miles away, because OSM did not answer for either town during the run.
# Both towns geocode fine on any other attempt.
_PLACED_PATH = Path(__file__).resolve().parent / "placed_towns.json"
_PLACED = None
_GEOCODE_ATTEMPTS = 2
_GEOCODE_RETRY_SLEEP = 1.0


def _placed():
    global _PLACED
    if _PLACED is None:
        try:
            _PLACED = json.loads(_PLACED_PATH.read_text(encoding="utf-8"))
        except Exception:
            _PLACED = {}
    return _PLACED


def _place_key(city, state):
    return "%s|%s" % ((city or "").strip().lower(), (state or "").strip().upper())


def _remember(city, state, coords):
    p = _placed()
    p[_place_key(city, state)] = list(coords)
    try:
        _PLACED_PATH.write_text(json.dumps(p, indent=0, sort_keys=True), encoding="utf-8")
    except Exception:
        pass                                  # a cache that cannot be saved is still a cache


# THE GEOCODER LIVES IN THE RANKING SKILL, and this module is imported from
# several places that do not have it on sys.path. Found 2026-09-23, and it is
# the more serious half of the Sunset Haven case: from inside
# batch_quick_intel, `import serp_helpers` raised ModuleNotFoundError, the bare
# `except Exception` turned that into None, and the caller read None as "that
# town cannot be placed". So the six-mile neighbour rule was not wobbling
# there, it had NEVER RUN, and every prospect whose Google listing sits in the
# next town over was refused with a message blaming the map.
#
# Two situations wearing one answer, which is the fallback defect in
# .claude/rules/fix-hierarchy.md: "we could not reach the geocoder" is a retry
# and "the geocoder is not installed here" is a configuration fault that must
# be visible. They are separated below.
_RANKING_SCRIPTS = (Path(__file__).resolve().parents[2]
                    / "my-skills" / "quick-intel-ranking" / "scripts")
GEOCODER_MISSING = "geocoder unavailable (serp_helpers not importable)"


def _geocoder():
    """The geocode function, or None if the ranking skill cannot be found.

    Resolved by PATH rather than by hoping the caller arranged sys.path, so the
    answer does not depend on which process imported this module.
    """
    try:
        import serp_helpers
        return serp_helpers.geocode_city_osm
    except Exception:
        pass
    if _RANKING_SCRIPTS.is_dir() and str(_RANKING_SCRIPTS) not in sys.path:
        sys.path.append(str(_RANKING_SCRIPTS))
    try:
        import serp_helpers
        return serp_helpers.geocode_city_osm
    except Exception:
        return None


def _geocode(city, state):
    """Coordinates for a town, or None.

    Order: a town we have placed before, then the geocoder, retried once. Only
    when all of those come back empty is the town genuinely unplaceable, and
    only then does the caller fail closed.
    """
    key = _place_key(city, state)
    hit = _placed().get(key)
    if hit:
        return tuple(hit)
    fn = _geocoder()
    if fn is None:
        return None
    for attempt in range(_GEOCODE_ATTEMPTS):
        try:
            got = fn(city, state)
        except Exception:
            got = None
        if got:
            _remember(city, state, got)
            return got
        if attempt + 1 < _GEOCODE_ATTEMPTS:
            time.sleep(_GEOCODE_RETRY_SLEEP)
    return None


def near_city(google_address, city, state, geocode=None, limit=NEIGHBOUR_MILES):
    """(True|False, detail). The NEXT TOWN OVER IS THE SAME MARKET and often
    the same business: Sunset Haven of Lewisville lists at Highland Village,
    four miles away. A town we cannot place is not near: unknown is not yes."""
    other = address_city(google_address)
    if not other or not city:
        return False, "no town to compare"
    # The listing's town is placed in the LISTING's state (Welton 2026-10-22, A2): Springfield MO for a contact in
    # Springfield IL was geocoded as Springfield IL, 0 miles away, and accepted. A listing in another state is never
    # the next town over.
    theirs = address_state(google_address)
    if theirs and state_code(state) and theirs != state_code(state):
        return False, "the listing is in %s, not %s" % (theirs, state_code(state))
    g = geocode or _geocode
    here, there = g(city, state), g(other, theirs or state)
    if not here or not there:
        # NAME THE CAUSE. "could not place Lewisville" reads as a fact about
        # the town; if the geocoder is not installed it is a fact about us, and
        # the two need different fixes.
        if geocode is None and _geocoder() is None:
            return False, GEOCODER_MISSING
        return False, "could not place %r or %r" % (city, other)
    d = _miles(here, there)
    return (d <= limit), "%s is %.0f miles from %s" % (other, d, city)


# ----------------------------------------------------------------------------
# SAME BRAND AT THE SAME STREET ADDRESS
#
# Welton, 2026-09-24, after four of a watched 25 were refused a card: a
# franchise whose Keap record and Google listing describe the same office with
# different territory wording. "Always Best Care of Northwest Chicago" against
# "Always Best Care Senior Services - Home Care Services in NW Chicago", both
# at 2017 W Irving Park Rd Ste 100. The word sets disagree (northwest / nw),
# so name_relation returns None and the address is never consulted.
#
# The loosening is deliberately narrow, and the STREET is the hard part of it:
# same brand at a different address still refuses, whatever the distance,
# because a neighbouring franchisee is a different business. An exact street
# match including the suite is a much stronger statement than "same town" --
# it is the one fact that cannot be true of two different offices.
#
# The name test is the secondary check, and it exists so that two unrelated
# businesses sharing a suite building cannot match: the LEADING distinctive
# word must agree, which is where a brand lives. "Visiting Angels" and
# "Visiting Nurses" at one address would pass that and are refused by
# requiring a second shared distinctive word whenever the leading one is a
# word that leads more than one brand in the book.
# ----------------------------------------------------------------------------

# Street-type abbreviations, so "2205 Central Avenue" is "2205 Central Ave".
_STREET_WORDS = {
    "avenue": "ave", "street": "st", "road": "rd", "drive": "dr", "boulevard": "blvd",
    "lane": "ln", "court": "ct", "place": "pl", "parkway": "pkwy", "highway": "hwy",
    "circle": "cir", "terrace": "ter", "square": "sq", "trail": "trl", "route": "rte",
    "suite": "ste", "unit": "ste", "apartment": "ste", "apt": "ste", "number": "ste",
    "building": "bldg", "floor": "fl", "north": "n", "south": "s", "east": "e", "west": "w",
    "northeast": "ne", "northwest": "nw", "southeast": "se", "southwest": "sw",
}


def normalise_street(text):
    """A street line reduced to comparable words.

    "370 Crenshaw Blvd., Suite E-106" -> "370 crenshaw blvd ste e106"
    "2205 Central Avenue"             -> "2205 central ave"
    """
    s = (text or "").lower().replace("#", " ste ")
    s = _PUNCT.sub(" ", s)
    out = []
    for w in s.split():
        out.append(_STREET_WORDS.get(w, w))
    # "ste e 106" is "ste e106": a split unit designator is not a different one
    joined = []
    for w in out:
        if (joined and len(joined[-1]) == 1 and joined[-1].isalpha()
                and len(joined) >= 2 and joined[-2] == "ste" and w.isdigit()):
            joined[-1] = joined[-1] + w
        else:
            joined.append(w)
    return " ".join(joined)


def street_of(address):
    """The street line out of "2017 W Irving Park Rd Ste 100, Chicago, IL ..."."""
    first = (address or "").split(",")[0]
    return normalise_street(first)


def same_street(keap_street, google_address):
    """Exact, after normalising. Not a prefix, not a containment: a suite
    number is part of the address and two suites are two offices."""
    a, b = normalise_street(keap_street), street_of(google_address)
    return bool(a) and bool(b) and a == b


def _leading_distinctive(name, ignore=()):
    drop = GENERIC | set(ignore)
    for w in normalise(name):
        if w not in drop and len(w) > 1:
            return w
    return ""


# Words that LEAD more than one brand in this book, so agreeing on one of them
# says nothing. Kept short and evidenced rather than imagined: each of these
# begins at least two distinct national brands we hold contacts for.
AMBIGUOUS_LEADS = frozenset({
    "visiting",      # Visiting Angels, Visiting Nurses
    "comfort",       # Comfort Keepers, ComForCare
    "home",          # Home Instead, Home Helpers, Home Care Assistance
    "senior",        # Senior Helpers, Seniors Helping Seniors, Senior Care
    "caring",        # Caring Senior Service, A Caring Touch
    "right",         # Right at Home, Right Choice
    "best",          # Always Best Care, Best Care
    "always",        # Always Best Care, Always There
    "american",      # several
})
# Not listed, and deliberately: "firstlight", "griswold", "interim", "amada"
# and the like lead exactly one brand, so agreeing on one of them is already
# a strong statement and a second shared word is not required.


def brand_agrees(a, b, ignore=(), place=()):
    """The leading distinctive word agrees, and says something.

    TWO DIFFERENT EXCLUSION SETS, and collapsing them breaks one case or the
    other:

      `ignore`  the state's words, used to find the LEADING word. The town is
                NOT excluded here, because a business is often named after its
                town -- "Springfields Memorial Garden" against "Springfield
                Memorial Gardens" at 4005 Memorial Blvd -- and excluding it
                left the lead as "gardens" on one side and "springfields" on
                the other.

      `place`   the state's words AND the town's, used for the SECOND shared
                word that an ambiguous lead requires. Without the town,
                "Visiting Angels of Springfield" and "Visiting Nurses of
                Springfield" share "springfield" and a place stands in for a
                brand.

    The leading words may differ by one character, the same tolerance
    name_relation applies to the word sets, so a plural is not a new brand.
    """
    la, lb = _leading_distinctive(a, ignore), _leading_distinctive(b, ignore)
    if not la or not lb:
        return False
    if la != lb and not _one_edit_apart(la, lb):
        return False
    if la not in AMBIGUOUS_LEADS:
        return True
    p = set(place) or set(ignore)
    shared = (distinctive(a, p) & distinctive(b, p)) - {la, lb}
    return bool(shared)

def shared_words(a, b, ignore=()):
    """The distinctive words two names share, one typo forgiven (the same tolerance name_relation applies)."""
    da, db = _align_one_typo(distinctive(a, ignore), distinctive(b, ignore))
    return da & db


# A SHARED PLACE NAME IS WHERE THEY ARE, NOT WHO THEY ARE (Welton 2026-10-29). "North Shore Healthcare" and
# "North Shore Family Services" share two words and both are the place. A shared run of words is a place when it is a
# US town, a county or a state (gads/geo_guard gazetteer), or is made only of place words; ONE word is a place only
# when it is the contact's own town, county or state (asymmetric-geo-inference: "Jackson" is a town somewhere and a
# surname here). Measured before the change: 232 matches / 133 prospects rested on a shared place of 2+ words, 51 of
# them a different business (receipt ops/receipts/20261029T074500_shared-place-measure.txt).
PLACE_WORDS = frozenset("""north south east west northern southern eastern western central greater upper lower mid tri
    coast coastal shore shores valley valleys bay bays hills hill county counties area region regional metro
    metropolitan lakes lake mountain mountains river rivers harbor gulf inland peninsula delta plains highlands
    lowcountry island islands beach beaches canyon desert prairie park heights springs falls""".split())
_GAZ = None


def _places():
    """(town names, county names, state names, gazetteer) from the bundled gazetteer, loaded once; None when this copy
    has no gazetteer beside it.

    None is safe because the places decide no match (Welton 2026-10-29, every match needs the phone or the street):
    they only word a refusal ("only the place name 'North Shore'"). Without them the refusal is worded plainly ("the
    name", "only the word 'north'") and every verdict is the same. The booth apps run this file without the 52 MB of
    place data (Welton 2026-10-29: "leave the data out and accept plainer wording").
    Pinned by test_business_identity.py::test_without_the_gazetteer_every_verdict_is_the_same_only_plainer."""
    global _GAZ
    if _GAZ is None:
        here = Path(__file__).resolve().parents[2] / "gads" / "geo_guard"
        if not (here / "gazetteer.py").is_file():
            _GAZ = False
        else:
            sys.path.insert(0, str(here))
            import gazetteer as G                                        # noqa: E402
            g = G.Gazetteer()
            counties = {line.split("	")[2].strip().lower()
                        for line in (G.GAZ / "counties_us.tsv").read_text(encoding="utf-8").splitlines()}
            _GAZ = (frozenset(g.by_name), frozenset(counties), frozenset(n.lower() for n in g.code_to_state.values()),
                    g)
    return _GAZ or None


def _is_place(run, local):
    towns, counties, states, _ = _places()
    s = " ".join(run)
    if len(run) == 1:
        return s in local or s in states
    return (s in towns or s in counties or s in states or all(w in PLACE_WORDS for w in run)
            or (run[0] in PLACE_WORDS and " ".join(run[1:]) in (towns | counties | states | local)))


def evidence_words(a, b, city, state, ignore=()):
    """(shared words that say WHO, shared words that only say WHERE). A run of the contact's name made of shared
    words (place words may join it) that is a place goes to the second set; the rest is the evidence."""
    shared = shared_words(a, b, ignore)
    if _places() is None:                   # no place data in this copy: nothing is set aside as a place
        return shared, set()
    _, _, _, g = _places()
    code = state_code(state) or state
    local = set(normalise(city)) | {" ".join(normalise(city))} | set(g.county_of(" ".join(normalise(city)), code))
    wa = [w for w in normalise(a) if w not in set(ignore)]
    wb = set(normalise(b))
    place, i = set(), 0
    while i < len(wa):
        for j in range(len(wa), i, -1):
            run = wa[i:j]
            if all(w in shared or (w in PLACE_WORDS and w in wb) for w in run) and any(w in shared for w in run)                     and _is_place(run, local):
                place |= set(run) & shared
                i = j
                break
        else:
            i += 1
    return shared - place, place


# The refusal starts with these words so every caller can tell "we could not confirm which listing is theirs" from
# "Google returned a different business", and say so to the rep (Welton 2026-10-29: never silent).
ONE_WORD_CANT_TELL = "CAN'T TELL which listing is theirs"


def match_business(keap_name, google_name, google_address, city, state,
                   geocode=None, keap_street="", keap_phone="", google_phone=""):
    """(True|False, reason). The reason goes in the receipt and the report.

    ONE SHARED WORD NEVER MAKES A MATCH (Welton 2026-10-29, standing ruling 3). When the two names share one
    distinctive word or none, the phone or the street must agree, whatever the town says: no exception for a
    franchise name ("Home Instead" names hundreds of offices) or a surname ("Smith Funeral Home"). Measured on
    4,259 saved ranking pages before the change: 1,167 matches rested on one shared word, 203 of them plainly a
    different business ("Caring Touch Inc." = "Touch Companies Wellness Center & Day Spa"); receipt
    ops/receipts/20261029T062000_one-word-match-measure.txt."""
    ignore = state_words(state)          # a state inside the company name is not a name
    rel = name_relation(keap_name, google_name, ignore=ignore)
    if rel is None:
        # THE ONE LOOSENING (Welton, 2026-09-24). A franchise whose territory
        # is worded differently on each side is still the same office when the
        # street address is identical, suite and all. Nothing weaker than an
        # exact street match reaches here, and the leading brand word still
        # has to agree.
        place = set(ignore) | set(normalise(city))
        if keap_street and same_street(keap_street, google_address)                 and brand_agrees(keap_name, google_name, ignore, place):
            return True, "same business, same street address (%s)" % street_of(google_address)
        return False, "a different business (%r is not %r)" % (google_name, keap_name)
    # EVERY MATCH NEEDS THE PHONE OR THE STREET (Welton 2026-10-29, standing ruling 3: a name alone never identifies
    # a business). The names agreeing is where the question starts, never the answer. Measured before the change:
    # of 2,205 prospects the old matcher matched on saved ranking pages, 1,858 keep a match on the phone or the street
    # (receipt ops/receipts/20261029T080000_place-rule-and-evidence-for-all.txt).
    if same_phone(keap_phone, google_phone):
        return True, "same business, same phone (%s)" % _digits(google_phone)
    if keap_street and same_street(keap_street, google_address) and (
            _city_in(google_address, city) or near_city(google_address, city, state, geocode=geocode)[0]):
        # The street counts only in the contact's own town or the next one: "1 Main St" is in every town.
        return True, "same business, same street address (%s)" % street_of(google_address)
    if not _state_in(google_address, state) and address_state(google_address):
        return False, "same name but %s is not in %s" % (google_address or "unknown", state or "?")
    # The reason names what the names share, so a setter reads "only the place name North Shore" rather than a
    # vaguer line (Welton 2026-10-29): the place detection now serves the wording only.
    who, where = evidence_words(keap_name, google_name, city, state, ignore)
    sw = sorted(who)
    if len(sw) > 1:
        said = "the name"
    else:
        said = "only the word %r" % sw[0] if sw else "no distinctive word"
        if where:
            pl = " ".join(w for w in normalise(keap_name) if w in where)
            said = ("only the place name %r" % pl) if not sw else (said + " and the place name %r" % pl)
    return False, ("%s: %r and %r share %s, and neither the phone nor the street agrees"
                   % (ONE_WORD_CANT_TELL, keap_name, google_name, said))
