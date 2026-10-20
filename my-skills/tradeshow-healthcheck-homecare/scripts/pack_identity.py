"""Is this map pack card the prospect? By PHONE or STREET ADDRESS backed by
the name, the way Where Are You already decides it (Welton, 2026-10-14).

WHY THIS EXISTS. The pre-call map pack rank matched on the business name the
research step passed, and nothing else. Google lists Engram as "Engram Funeral
Hme Inc"; the 13:04 run passed "Engram Funeral Home Inc" and every map pack
read NOT FOUND while Engram sat in it. The rule that fixes this was already
written and tested in Where Are You (`.claude/rules/where-are-you-lessons.md`):
a listing is the business when the phone OR the street address matches AND the
names share a distinctive word, never on the address alone or the phone alone.

WHAT A MAP CARD CARRIES (measured 2026-10-14 on the 23 saved DataForSEO pages
in temp_floor_decor/screenshots, 56 non-sponsored cards): a phone number on 53,
a street address on 30, a readable website on NONE. The card's Website button
is a Google /goto link whose target is not readable from the page, so a website
match is not available on the map pack; the phone is the key.

THE COPY. Everything above `classify_pack` is copied from
`my-skills/where-are-you-homecare/scripts/serp_helpers.py`, because the pre-call
webapp deploy ships only pre-call-research and pre-call-audit and cannot import
that file. `my-skills/pre-call-audit/tests/test_pack_identity.py` asserts the
copy and the original give the same answer on every case it runs, and fails
when they drift. Pre-call adds only `PRECALL_MATCH_TOKENS` (deathcare and
hospice trade words, which Where Are You never needed) and `classify_pack`.
"""
import re

US_STATE_ABBREVS = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

# --- copied from serp_helpers: name tokens ---------------------------------

STOPWORDS = {"&", "and", "the", "of", "inc", "llc", "co", "corp", "company"}
_APOSTROPHES = "'’ʼ`´"


def _norm_name(s):
    s = (s or "").lower()
    for ch in _APOSTROPHES:
        s = s.replace(ch, "")
    s = re.sub(r"[.\-/,]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\b(?:([a-z]) )+(?=[a-z]\b)",
               lambda m: m.group(0).replace(" ", ""), s)
    return re.sub(r"\s+", " ", s).strip()


_PLURAL_FOLD = {
    "homes": "home", "services": "service", "directors": "director",
    "chapels": "chapel", "crematories": "crematory", "crematoriums": "crematorium",
    "mortuaries": "mortuary", "cemeteries": "cemetery", "gardens": "garden",
    "parlors": "parlor", "funerals": "funeral",
    "caregivers": "caregiver", "agencies": "agency", "seniors": "senior",
    "companions": "companion", "angels": "angel", "helpers": "helper",
    "nurses": "nurse", "solutions": "solution", "partners": "partner",
    "cares": "care",
}

_TRADE_ABBREV = {
    "htg": ["heating"], "hlg": ["heating"], "clg": ["cooling"],
    "cond": ["conditioning"], "condit": ["conditioning"],
    "svc": ["service"], "svcs": ["service"], "serv": ["service"],
    "ac": ["air", "conditioning"],
    "refrig": ["refrigeration"], "refrg": ["refrigeration"],
    "mech": ["mechanical"],
}


def _expand_abbrev(tok):
    if "&" in tok and any(p in _TRADE_ABBREV for p in tok.split("&")):
        out = []
        for part in tok.split("&"):
            if part:
                out.extend(_expand_abbrev(part))
        return out
    return _TRADE_ABBREV.get(tok, [tok])


def _tokens(s):
    out = []
    for w in re.split(r"\s+", _norm_name(s)):
        if not w or w in STOPWORDS:
            continue
        out.extend(_expand_abbrev(_PLURAL_FOLD.get(w, w)))
    return out


_GENERIC_NAME_TOKENS = {
    "in", "at", "of", "for", "the", "a", "home", "house", "care", "caring",
    "cares", "service", "senior", "elder", "elderly", "adult", "family",
    "provider", "caregiver", "agency", "nursing", "nurse", "health",
    "healthcare", "medical", "living", "life", "assist", "assisted",
    "assistance", "help", "helping", "support", "companion", "personal",
    "private", "duty", "quality", "best", "top", "trusted", "professional",
    "affordable", "premier", "preferred", "first", "1st", "247", "24",
    "hour", "hourly", "respite", "hospice", "comfort", "compassionate",
    "independent", "independence", "loving", "gentle", "angel", "angels",
    "america", "american", "national", "nationwide", "local", "community",
    "group", "llc", "inc", "co", "corp", "company", "services", "homes",
}

_FLOORING_TRADE_TOKENS = {
    "floor", "floors", "flooring", "carpet", "carpets", "tile", "tiles",
    "hardwood", "wood", "laminate", "vinyl", "plank", "linoleum", "lvp",
    "granite", "marble", "stone", "grout", "subfloor", "underlayment",
    "refinishing", "installation", "installers", "installer", "install",
    "covering", "coverings", "surfaces", "interiors", "design", "designs",
    "remodeling", "renovation", "decor", "gallery", "showroom", "outlet",
    "warehouse", "liquidators", "supply", "supplies", "depot", "center",
    "centre", "shop", "store", "stores", "solutions", "brothers", "sons",
}

_HVAC_TRADE_TOKENS = {
    "heating", "heat", "heater", "heaters", "cooling", "cool",
    "air", "aire", "airflow", "conditioning", "conditioner", "conditioners",
    "hvac", "furnace", "furnaces", "boiler", "boilers", "climate",
    "temperature", "temp", "thermal", "thermo", "mechanical", "refrigeration",
    "ventilation", "vent", "vents", "duct", "ducts", "ductwork",
    "plumbing", "plumber", "plumbers", "electric", "electrical",
    "energy", "geothermal", "chiller", "indoor", "breeze", "weather",
    "season", "seasons", "seasonal", "repair", "repairs", "install",
    "installation", "contractor", "contractors", "contracting", "systems",
    "system", "specialists", "specialist", "experts", "expert", "pros",
    "masters", "insulation", "filtration", "filter", "filters",
}

_WD_TRADE_TOKENS = {
    "window", "windows", "door", "doors", "entry", "patio", "sliding",
    "casement", "awning", "sash", "pane", "panes", "glass", "glazing",
    "storm", "screen", "screens", "frame", "frames", "shutter", "shutters",
    "skylight", "skylights", "replacement", "replace", "vinyl", "fiberglass",
    "clad", "impact", "hurricane", "insulated", "exteriors", "exterior",
    "siding", "sunroom", "sunrooms", "depot", "gallery", "showroom", "works",
}

MATCH_GENERIC_TOKENS = (_GENERIC_NAME_TOKENS | _FLOORING_TRADE_TOKENS
                        | _HVAC_TRADE_TOKENS | _WD_TRADE_TOKENS)

# PRE-CALL ONLY. Where Are You never mailed funeral homes, cemeteries or
# hospices, so its matching set has no deathcare words: there, "Smith Funeral
# Home" and "Jones Funeral Home" would agree on "funeral". These words carry no
# brand identity in the verticals pre-call serves.
_DEATHCARE_TRADE_TOKENS = {
    "funeral", "cremation", "cremations", "cremate", "crematory", "crematorium",
    "mortuary", "chapel", "memorial", "memorials", "cemetery", "burial",
    "burials", "director", "tribute", "tributes", "garden", "park", "lawn",
    "rest", "peace", "eternal", "heritage", "legacy", "son", "sons", "parlor",
    "palliative", "homecare", "homehealth", "hme",
}
PRECALL_MATCH_TOKENS = MATCH_GENERIC_TOKENS | _DEATHCARE_TRADE_TOKENS


def _is_distinctive(token, city="", state="", tokens=None):
    generic = _GENERIC_NAME_TOKENS if tokens is None else tokens
    t = (token or "").strip().lower()
    if not t or len(t) < 3:
        return False
    if t in generic:
        return False
    for part in _tokens(city):
        if t == part:
            return False
    st = (state or "").strip().lower()
    if st and (t == st or t == (US_STATE_ABBREVS.get(state.upper(), "")).lower()):
        return False
    return True


# --- copied from serp_helpers: card identity --------------------------------

_ADDR_WORDS = {"road": "rd", "street": "st", "avenue": "ave", "boulevard": "blvd",
               "drive": "dr", "lane": "ln", "court": "ct", "highway": "hwy",
               "parkway": "pkwy", "place": "pl", "circle": "cir", "terrace": "ter",
               "trail": "trl", "north": "n", "south": "s", "east": "e", "west": "w"}
_SUITE_RX = re.compile(r"(?:#|\bsuite\b|\bste\b|\bunit\b|\bapt\b)\s*([a-z0-9-]+)")


def _addr_norm(t):
    t = re.sub(r"[^a-z0-9# ]", " ", (t or "").lower())
    return " ".join(_ADDR_WORDS.get(w, w) for w in t.split())


def _street_key(address):
    a = _addr_norm(address)
    m = re.match(r"(\d+[a-z]?) ([a-z0-9]+)", a)
    if not m:
        return None
    s = _SUITE_RX.search(a)
    return m.group(1), m.group(2), (s.group(1) if s else None)


def _phone10(p):
    d = re.sub(r"\D", "", p or "")
    return d[-10:] if len(d) >= 10 else ""


_SHORT_FORMS = {
    "ctr": "center", "cntr": "center", "bros": "brothers", "mfg": "manufacturing",
    "intl": "international", "natl": "national", "assoc": "associates",
    "mgmt": "management", "sys": "systems", "flr": "floor", "flrs": "floors",
    "flrg": "flooring", "crpt": "carpet", "hdwd": "hardwood", "hrdwd": "hardwood",
    "dist": "distributors", "whse": "warehouse",
}


def _agree_tokens(s):
    words = [w for w in re.split(r"[\s&]+", _norm_name(s)) if w and w not in STOPWORDS]
    merged, run = [], []
    for w in words + [None]:
        if w is not None and len(w) <= 2 and w.isalpha():
            run.append(w)
            continue
        if run:
            merged.append("".join(run))
            run = []
        if w is not None:
            merged.append(w)
    out = []
    for w in merged:
        w = _PLURAL_FOLD.get(w, w)
        out.extend(_expand_abbrev(_SHORT_FORMS.get(w, w)))
    return out


def names_agree(business, card_name, city="", state="", tokens=MATCH_GENERIC_TOKENS):
    full_a, full_b = set(_agree_tokens(business)), set(_agree_tokens(card_name))
    cw = set((city or "").lower().split())
    shared = {x for x in (full_a - cw) & (full_b - cw)
              if _is_distinctive(x, city, state, tokens=tokens)}
    contained = min(len(full_a), len(full_b)) >= 2 and (full_a <= full_b or full_b <= full_a)
    return bool(shared or contained)


def phone_on_card(card_text, phone):
    ph = _phone10(phone)
    return bool(ph and ph in re.sub(r"\D", "", card_text or ""))


def card_is_contact(card_text, card_name, business, address=None, phone=None,
                    city="", state="", tokens=MATCH_GENERIC_TOKENS):
    if phone_on_card(card_text, phone):
        return names_agree(business, card_name, city, state, tokens)
    key = _street_key(address)
    if not key:
        return False
    num, street, suite = key
    t = _addr_norm(card_text)
    m = re.search(r"\b%s %s\b(.{0,40})" % (re.escape(num), re.escape(street)), t)
    if not m:
        return False
    cs = _SUITE_RX.search(m.group(1))
    if suite and cs and cs.group(1) != suite:
        return False
    return names_agree(business, card_name, city, state, tokens)


def phone_conflict(card_text, card_name, business, phone=None, city="", state="",
                   tokens=MATCH_GENERIC_TOKENS):
    return phone_on_card(card_text, phone) and not names_agree(
        business, card_name, city, state, tokens)


# --- pre-call: the map pack verdict -----------------------------------------

_PHONE_RX = re.compile(r"\(?\b\d{3}\)?[\s.-]*\d{3}[\s.-]*\d{4}\b")
# A street address on a card, after _addr_norm: number, optional direction,
# one or more words, a street type. "2.8 mi" and "(40)" never match.
_CARD_STREET_RX = re.compile(
    r"\b\d{1,6}[a-z]? (?:[nsew] )?(?:[a-z0-9]+ ){1,3}"
    r"(?:st|rd|dr|ave|blvd|ln|ct|hwy|pkwy|pl|cir|ter|trl|way|pike|tpke|sq)\b")
# A card's distance ("10.8 mi") sits right before its street or its town, and
# "10.8 mi · Orange, CT" would read as the street "8 mi orange ct" (CT = Court).
_DISTANCE_RX = re.compile(r"\b\d+(?:\.\d+)?\s*mi\b", re.IGNORECASE)


def card_street(card_text):
    """The street address a card shows, normalised, or None.

    Only a field that STARTS with the street number counts. A card's fields are
    separated by "·" (and the directions link by commas); matching across them
    read "4.8(91) · Flooring store 10.8 mi · Orange, CT" as a street."""
    for field in re.split(r"[·|,\n/]", _DISTANCE_RX.sub(" ", card_text or "")):
        m = _CARD_STREET_RX.match(_addr_norm(field))
        if m:
            return m.group(0)
    return None


def legacy_name_match(text, business_name):
    """The pre-call rule before 2026-10-14, kept as one piece of NAME evidence:
    the whole name is in the card name, or its first three non-skip words are."""
    if not business_name:
        return False
    text = (text or "").lower()
    name = business_name.lower()
    words = [w for w in name.split() if w not in {'&', 'and', 'the', 'of', 'inc', 'llc', 'ltd'}]
    if name in text:
        return True
    return len(words) >= 3 and ' '.join(words[:3]) in text


def split_city_state(city):
    """'Franklin VA' -> ('Franklin', 'VA'); 'Franklin, Virginia' -> ('Franklin', 'Virginia')."""
    c = (city or "").strip().rstrip(",")
    if "," in c:
        a, b = c.rsplit(",", 1)
        return a.strip(), b.strip()
    parts = c.split()
    if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isalpha():
        return " ".join(parts[:-1]), parts[-1].upper()
    return c, ""


THEM = "them"
CANT_TELL = "cant_tell"
NOT_THEM = "not_them"


def as_list(value):
    """A phone or address argument as a list: None, one value, a list, or
    "a|b" (a multi-location brand passes every location's, Welton 2026-10-15)."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [v for v in value if v]
    return [v.strip() for v in str(value).split("|") if v.strip()]


def card_verdict(card_text, card_name, business, phone=None, address=None, city=""):
    """(verdict, how) for one organic map card.

    THEM       phone or street address on the card matches, and the names agree.
    CANT_TELL  the name points at the prospect but something on the card says
               otherwise or nothing on it can confirm it: the phone matches but
               the names do not agree, or the names agree but the card shows a
               DIFFERENT phone or a DIFFERENT street address (same building,
               other suite: Guardian Care / Ablessing). Never "there", never
               "missing".
    NOT_THEM   nothing on the card points at the prospect.

    `phone` and `address` may each carry several values (as_list): a brand with
    three locations matches a card that carries ANY of its locations' phones
    or streets. One value behaves exactly as before.

    A card with no phone and no address of the prospect's to compare is judged
    by the name alone, the same as before this change: the old full-name rule
    still counts as THEM there, a looser shared-word agreement is CANT_TELL.
    """
    c, st = split_city_state(city)
    phones, addresses = as_list(phone), as_list(address)
    for ph in phones:
        if card_is_contact(card_text, card_name, business, None, ph, c, st,
                           tokens=PRECALL_MATCH_TOKENS):
            return THEM, "phone"
    for ad in addresses:
        if not any(phone_on_card(card_text, ph) for ph in phones) and \
                card_is_contact(card_text, card_name, business, ad, None, c, st,
                                tokens=PRECALL_MATCH_TOKENS):
            return THEM, "address"
    if any(phone_conflict(card_text, card_name, business, ph, c, st,
                          tokens=PRECALL_MATCH_TOKENS) for ph in phones):
        return CANT_TELL, "phone matches, name does not"
    by_name = legacy_name_match(card_name, business)
    agrees = names_agree(business, card_name, c, st, tokens=PRECALL_MATCH_TOKENS)
    if not (by_name or agrees):
        return NOT_THEM, ""
    card_phones = {_phone10(p) for p in _PHONE_RX.findall(card_text or "")} - {""}
    if any(_phone10(ph) for ph in phones) and card_phones:
        return CANT_TELL, "name matches, card phone is a different number"
    if any(_street_key(ad) for ad in addresses) and card_street(card_text):
        return CANT_TELL, "name matches, card street address is a different one"
    if by_name:
        return THEM, "name"
    return CANT_TELL, "name partly matches, nothing on the card to confirm"


def classify_pack(listings, business, phone=None, address=None, city=""):
    """The map pack cell for one search, from the cards the page carried.

    `listings` are dicts with position, name, and card_text (the card's full
    visible text plus its directions link). Each gets `match` and `match_how`.

    Returns "#N (3PK)" for the first card that is the prospect;
    "UNABLE TO VERIFY (#N may be them)" when no card is but one might be (read
    as unchecked by ranking_counts and assessment_guard, never as a miss);
    "NOT FOUND" only when cards were read and none points at the prospect.
    No cards at all is not a reading: "UNABLE TO VERIFY (no map cards to read)"
    (three_answers.py, Welton 2026-10-15).
    """
    if not listings:
        return "UNABLE TO VERIFY (no map cards to read)"
    # Which card is theirs is asked of prospect_identity, the one place that
    # decides it (Welton, 2026-10-16): a name with no phone or street to
    # confirm it is "can't tell", never a rank.
    import prospect_identity
    first_them = first_maybe = None
    for li in listings or []:
        v, how = prospect_identity.listing(li.get("card_text") or li.get("name") or "",
                                           li.get("name") or "", business, phone, address, city)
        li["match"], li["match_how"] = v, how
        if v == THEM and first_them is None:
            first_them = li.get("position")
        elif v == CANT_TELL and first_maybe is None:
            first_maybe = li.get("position")
    if first_them is not None:
        return "#%s (3PK)" % first_them
    if first_maybe is not None:
        return "UNABLE TO VERIFY (#%s may be them)" % first_maybe
    return "NOT FOUND"
