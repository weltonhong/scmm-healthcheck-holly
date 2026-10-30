"""
Quick Intel - Google Places API lookup

Returns review count, rating, business status for the target business
AND top competitors in one shot. Two API calls total.

Vertical-aware: supports funeral_home, cemetery, home_care, hospice,
assisted_living, home_health. Each vertical has its own competitor
search query and a cross-vertical exclusion list so cemetery searches
don't leak funeral homes, home care, or hospice results.

Usage:
    python google_intel.py --business "Greenwood Cemetery" \
        --city "Brooklyn" --state "NY" --vertical cemetery

Output: JSON to stdout with target + competitor data.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error


PLACES_API_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = (
    "places.displayName,"
    "places.formattedAddress,"
    "places.rating,"
    "places.userRatingCount,"
    "places.businessStatus,"
    "places.googleMapsUri,"
    "places.websiteUri,"
    "places.primaryType,"
    "places.types,"
    # Who a listing is, beyond its name (standing ruling 3) and where it is (Welton 2026-10-22): the place id,
    # its phone, its map position, and the place Google says it sits inside (the Great Mausoleum is inside
    # Forest Lawn Glendale's own place).
    "places.id,"
    "places.nationalPhoneNumber,"
    "places.location,"
    "places.containingPlaces"
)


# ---------------------------------------------------------------------------
# Vertical configuration
#
# Each vertical defines:
#   query           - the Google Places search phrase for competitors
#   exclude_types   - Google Places primaryType / types values that indicate
#                     a result belongs to a DIFFERENT vertical and should be
#                     filtered out (prevents cemetery searches from leaking
#                     funeral homes, etc.)
#   exclude_words   - case-insensitive substrings in the place NAME that
#                     signal a cross-vertical leak even when types are empty
#   vertical_plural - used by the opening line template
#   outcome_qs      - three outcome-question options for Obs 1/2/3 openings
# ---------------------------------------------------------------------------

VERTICAL_CONFIG = {
    "funeral_home": {
        "query": "funeral home",
        # Opt-in: a result must match at least one of these Google Places
        # types OR contain at least one of these keywords in the name.
        "require_types": {"funeral_home"},
        "require_name_words": ["funeral home", "funeral chapel", "funeral service"],
        "vertical_plural": "funeral homes",
        "outcome_qs": [
            "that's affecting how many first calls you get?",
            "families who need you right now are actually finding you?",
            "families who find you online are getting a sense of who you actually are?",
        ],
    },
    "cemetery": {
        "query": "cemetery OR memorial park",
        "require_types": {"cemetery"},
        "require_name_words": [
            "cemetery", "memorial park", "memorial gardens",
            "burial", "mausoleum",
        ],
        "vertical_plural": "cemeteries",
        "outcome_qs": [
            "that's affecting how many families choose you for memorialization?",
            "families planning ahead are actually finding you when they start looking?",
            "families researching cemeteries online are getting a sense of who you are?",
        ],
    },
    "home_care": {
        "query": "home care agency",
        "require_types": {"home_health_care_service"},
        "require_name_words": [
            "home care", "homecare", "senior care", "in-home care",
            "in home care", "caregiver",
        ],
        "vertical_plural": "home care agencies",
        "outcome_qs": [
            "that's affecting how many inquiry calls you get?",
            "families in your area are finding you when they need home care?",
            "they can tell what makes your location different?",
        ],
    },
    "hospice": {
        "query": "hospice",
        "require_types": set(),  # Google Places has no "hospice" type
        "require_name_words": ["hospice", "palliative"],
        "vertical_plural": "hospice providers",
        "outcome_qs": [
            "that's affecting how many referrals you get?",
            "families are finding you when they need end-of-life care?",
            "families understand what makes your care different?",
        ],
    },
    "assisted_living": {
        "query": "assisted living facility",
        "require_types": {"assisted_living_facility"},
        "require_name_words": [
            "assisted living", "senior living", "retirement community",
            "memory care",
        ],
        "vertical_plural": "assisted living communities",
        "outcome_qs": [
            "that's affecting how many tours you book?",
            "families are finding you when they start their search?",
            "families get a real sense of daily life at your community?",
        ],
    },
    "home_health": {
        "query": "home health agency",
        "require_types": {"home_health_care_service"},
        "require_name_words": [
            "home health", "home healthcare", "visiting nurse",
        ],
        "vertical_plural": "home health agencies",
        "outcome_qs": [
            "that's affecting how many referrals you convert?",
            "patients discharged from the hospital are finding you?",
            "referral sources understand what makes your care different?",
        ],
    },
}


def resolve_vertical(vertical):
    """Map loose vertical strings to canonical keys."""
    if not vertical:
        return "funeral_home"
    v = vertical.lower().strip().replace(" ", "_").replace("-", "_")
    # Common aliases
    aliases = {
        "funeral": "funeral_home",
        "funeralhome": "funeral_home",
        "cemeteries": "cemetery",
        "memorial_park": "cemetery",
        "memorialpark": "cemetery",
        "homecare": "home_care",
        "home_care_agency": "home_care",
        "homehealth": "home_health",
        "home_health_agency": "home_health",
        "assistedliving": "assisted_living",
        "assisted_living_facility": "assisted_living",
    }
    return aliases.get(v, v if v in VERTICAL_CONFIG else "funeral_home")


def get_api_key():
    """Get Google API key from environment."""
    key = os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "[System.Environment]::GetEnvironmentVariable('GOOGLE_API_KEY', 'User')"],
                capture_output=True, text=True, timeout=5
            )
            key = result.stdout.strip()
        except Exception:
            pass
    return key


# Google's raw answers, kept while main() runs (Welton 2026-10-29: "Make the archive keep Google's raw answer, not just
# what the lookup kept from it"). Haven, Ozark MO: the live app's rival search came back without Amedisys while the
# same code here found it, and only the kept result was archived. main() turns recording on and prints the answers as
# "places_raw"; the booth saves that output in results.json. None outside main(): the booth app's own process calls
# places_search for "Is this your address?" on every scan, and must not keep a growing list.
_RAW = None


# WHERE A PLACES SEARCH IS PINNED (Welton 2026-10-29). A text search that sends only words is answered partly by where
# the REQUEST comes from, so the live booth app on its server and this PC got different listings for the same words
# (Haven, Ozark MO: the server's rival search had no Amedisys and the sheet lost its competitor section). Each of the
# booth's four Places searches (the "Is this your address?" lookup in scripts/state_check.py, and here their own
# listing, the rival search and the town) now sends the town's place as a locationBias circle: a bias, never a
# restriction, so a listing outside the circle can still come back. The same circle and the same record as pre-call's
# half (pre-call-audit/scripts/places_pin.py, which this file cannot import: the booth deploy repos do not carry it);
# test_booth_places_pin.py asserts the two agree whenever both are in the tree.
# No place available: the search goes out with words only, exactly as before, and the output records why. Which
# listing is theirs is still decided by phone or street (business_identity), so an unpinned search can confirm fewer
# listings, never a different business.
RADIUS_M = 50000.0      # the largest circle Places text search accepts for a locationBias (50 km)


def bias(at, radius_m=RADIUS_M):
    """The locationBias for a search pinned at `at` (lat, lng), or None when there is no place."""
    if not at:
        return None
    return {"circle": {"center": {"latitude": float(at[0]), "longitude": float(at[1])},
                       "radius": float(radius_m)}}


def pin_note(at, how):
    """What the output records about the pin: where from, or why there was none."""
    if at:
        return {"pinned": True, "at": [float(at[0]), float(at[1])], "radius_m": RADIUS_M, "from": how}
    return {"pinned": False, "at": None, "why": how or "no place available",
            "effect": "searched with words only, as before 2026-10-29"}


def places_search(query, api_key, max_results=5, at=None):
    """Run a Places API text search, pinned at `at` (lat, lng) when given. Returns list of place dicts."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    sent = {
        "textQuery": query,
        "maxResultCount": max_results,
    }
    if bias(at):
        sent["locationBias"] = bias(at)
    body = json.dumps(sent).encode("utf-8")

    try:
        req = urllib.request.Request(
            PLACES_API_URL, data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        if _RAW is not None:
            _RAW.append({"sent": sent, "error": str(e)})
        return {"error": str(e)}
    if _RAW is not None:
        _RAW.append({"sent": sent, "answer": data})

    results = []
    for place in data.get("places", []):
        results.append({
            "name": place.get("displayName", {}).get("text", ""),
            "address": place.get("formattedAddress", ""),
            "rating": place.get("rating"),
            "review_count": place.get("userRatingCount"),
            "status": place.get("businessStatus", ""),
            "maps_url": place.get("googleMapsUri", ""),
            "website": place.get("websiteUri", ""),
            "primary_type": place.get("primaryType", ""),
            "types": place.get("types", []) or [],
            "place_id": place.get("id", ""),
            "phone": place.get("nationalPhoneNumber", ""),
            "location": place.get("location") or {},
            "inside": [c.get("id") for c in place.get("containingPlaces") or [] if c.get("id")],
        })
    return results


# Types that definitely mean "not a real business in our verticals" --
# used to reject even if name-matching would pass.
_HARD_REJECT_TYPES = {
    "park", "tourist_attraction", "historical_landmark", "historical_place",
    "museum", "library", "church", "place_of_worship", "amusement_park",
    "zoo", "art_gallery", "stadium",
}


def matches_vertical(place, config):
    """Opt-in match: a result passes if its Google Places primary type
    is in require_types. For verticals where Google's type taxonomy is
    weak (e.g. hospice), also accept a name keyword match -- but only
    when the place isn't hard-rejected as a park/museum/landmark."""
    types = set(place.get("types") or [])
    primary = place.get("primary_type") or ""
    if primary:
        types.add(primary)

    # Hard reject parks, landmarks, museums even if name contains our keywords
    if types & _HARD_REJECT_TYPES and primary not in config["require_types"]:
        return False

    if types & config["require_types"]:
        return True
    # Name fallback for verticals without a clean Google type
    name_lower = (place.get("name") or "").lower()
    for kw in config["require_name_words"]:
        if kw in name_lower:
            return True
    return False


_TARGET_NORMALIZE_RE = re.compile(r"[^a-z0-9 ]+")


def normalize_name(name):
    """Lowercase, strip punctuation, collapse spaces, drop 'the' prefix."""
    if not name:
        return ""
    s = name.lower()
    s = _TARGET_NORMALIZE_RE.sub(" ", s)
    s = " ".join(s.split())
    if s.startswith("the "):
        s = s[4:]
    return s


def _compact(s):
    """Remove all whitespace so 'green wood' and 'greenwood' both become 'greenwood'."""
    return "".join(s.split())


def _same_place(a, b):
    """True when listing `a` is the business at listing `b`'s place, by evidence, never by name: the same place id,
    one inside the other's place (Google's containingPlaces: the Great Mausoleum inside Forest Lawn), the same
    phone, or the same street address (Welton 2026-10-22)."""
    def cid(u):
        m = re.search(r"[?&]cid=(\d+)", u or "")
        return m.group(1) if m else ""
    ca, cb = cid(a.get("maps_url")), cid(b.get("maps_url"))
    if ca and cb and ca == cb:
        return True
    pa, pb = a.get("place_id"), b.get("place_id")
    if pa and pb and (pa == pb or pb in (a.get("inside") or []) or pa in (b.get("inside") or [])):
        return True
    da, db = re.sub(r"\D", "", a.get("phone") or "")[-10:], re.sub(r"\D", "", b.get("phone") or "")[-10:]
    if len(da) == 10 and da == db:
        return True
    na = " ".join(re.findall(r"[a-z0-9]+", (a.get("address") or "").lower()))
    nb = " ".join(re.findall(r"[a-z0-9]+", (b.get("address") or "").lower()))
    return bool(na) and na == nb


NEARBY_MILES = 25


def _miles(a, b):
    """Great-circle miles between two Places locations, or None when either is missing."""
    import math
    la, lb = a.get("location") or {}, b.get("location") or {}
    if la.get("latitude") is None or lb.get("latitude") is None:
        return None
    p1, p2 = math.radians(la["latitude"]), math.radians(lb["latitude"])
    dp, dl = p2 - p1, math.radians(lb["longitude"] - la["longitude"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def _identity():
    """The shared identity rule (keap/card_queue/business_identity.py), loaded on first use: the booth tools load this
    file for its helpers from a folder that may not carry it."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "keap", "card_queue"))
    import business_identity
    return business_identity


def _town_point(city, state, api_key, at=None):
    """The town the rep typed, as a Places listing with a map position, or None. Only an answer that is the town
    itself (a locality) in the typed state counts; anything else is no answer, never a guess."""
    bi = _identity()
    res = places_search("%s, %s" % (city, state), api_key, max_results=3, **({"at": at} if at else {}))
    for p in res if isinstance(res, list) else []:
        types = set(p.get("types") or []) | {p.get("primary_type") or ""}
        if (types & {"locality", "sublocality", "administrative_area_level_3", "postal_town"}
                and bi.address_state(p.get("address")) == bi.state_code(state) and _miles(p, p) is not None):
            return p
    return None


def _could_be_them(business, name, state):
    """True when a listing's name shares a distinctive word with theirs, or is their name: without their listing
    confirmed, such a listing may be theirs, so it is never called a rival. A name sharing nothing is plainly a
    different business (Welton 2026-10-29)."""
    bi = _identity()
    ignore = bi.state_words(state)
    # name_relation "contained" is not used: it holds for two names that share only generic words ("Home Health"),
    # which is the residual-generic trap (.claude/rules/name-matching.md), not evidence they are the same.
    return bool(bi.shared_words(business, name, ignore)) or bi.name_relation(business, name, ignore=ignore) == "equal"


def is_same_business(target_name, candidate_name):
    """Fuzzy match for target-vs-competitor. Handles 'Greenwood' vs
    'Green-Wood' (hyphen becomes space), 'The X' vs 'X', and
    'Greenwood Cemetery' vs 'Greenwood Cemetery, Second Entrance'."""
    t = normalize_name(target_name)
    c = normalize_name(candidate_name)
    if not t or not c:
        return False
    if t == c or t in c or c in t:
        return True
    # Compact (drop all spaces) match: catches 'greenwood' vs 'green wood'
    tc = _compact(t)
    cc = _compact(c)
    if tc and (tc == cc or tc in cc or cc in tc):
        return True
    # Compact prefix match: 'greenwoodcemetery' is a prefix of
    # 'greenwoodentranceatprospectparkwest'? No. But the first 6+ chars
    # of the target are present at the start of the candidate? Yes.
    # This catches sub-location entries like 'Greenwood Entrance'.
    if tc and len(tc) >= 6 and cc.startswith(tc[:6]):
        # Also require the candidate to not be way longer (avoid false
        # positives on very different businesses that share a prefix)
        return True
    # Token overlap: if target has 2+ word tokens and ALL of them appear
    # in the candidate as substrings, treat as a match. Uses compact
    # candidate so tokens survive the hyphen-to-space boundary.
    tokens = [w for w in t.split() if len(w) > 2]
    if len(tokens) >= 2 and all(w in cc for w in tokens):
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="Quick Intel Google lookup")
    parser.add_argument("--business", required=True, help="Business name")
    parser.add_argument("--city", required=True, help="City")
    parser.add_argument("--state", required=True, help="State abbreviation")
    parser.add_argument(
        "--vertical", default="funeral_home",
        help="Vertical key (funeral_home, cemetery, home_care, hospice, "
             "assisted_living, home_health)",
    )
    parser.add_argument("--phone", default="", help="The contact's phone, to confirm their listing")
    parser.add_argument("--street", default="", help="The contact's street address, to confirm their listing")
    # The booth sets this (Welton 2026-10-29): when their listing cannot be confirmed, measure nearby from the town
    # and name only listings that are plainly not them. Without it (Quick Intel cards) nothing changes.
    parser.add_argument("--town-fallback", action="store_true",
                        help="unconfirmed listing: measure nearby from the town and keep only plainly different rivals")
    # The town's place, from the caller's own town lookup (the booth: state_check.town_pin), and where it came from
    # or why there is none. Without --latlng every search goes out with words only and "places_pin" says why.
    parser.add_argument("--latlng", default="", help="LAT,LNG: pin the Places searches here (50 km bias)")
    parser.add_argument("--pin-from", default="", help="where --latlng came from, or why there is no place")
    args = parser.parse_args()
    global _RAW
    _RAW = []          # every Places request this lookup sends and Google's whole answer, printed as "places_raw"

    vertical_key = resolve_vertical(args.vertical)
    config = VERTICAL_CONFIG[vertical_key]

    api_key = get_api_key()
    if not api_key:
        print(json.dumps({"error": "GOOGLE_API_KEY not found"}))
        sys.exit(1)

    at = None
    try:
        lat, lng = (float(x) for x in args.latlng.split(","))
        at = (lat, lng)
    except ValueError:
        pass
    pin = {"at": at} if at else {}
    places_pin = pin_note(at, args.pin_from if at or args.pin_from else
                          ("--latlng not readable: %r" % args.latlng if args.latlng else "no place given (no --latlng)"))

    # Search 1: Target business (exact name + location)
    target_query = f"{args.business} {args.city} {args.state}"
    target_results = places_search(target_query, api_key, max_results=3, **pin)

    # Search 2: Competitors (vertical-specific query + city)
    competitor_query = f"{config['query']} {args.city} {args.state}"
    competitor_results = places_search(competitor_query, api_key, max_results=10, **pin)

    # Identify target in results
    # The first result is not the business until the shared identity rule says so (Welton 2026-10-22, P20): the
    # same rule as the batch card (business_identity.match_business). Imported here, not at the top, because the booth
    # tools load this file for its helpers from a folder without keap/card_queue.
    target, target_check = None, "no listing came back"
    if isinstance(target_results, list) and target_results:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                                        "keap", "card_queue"))
        import business_identity
        for cand in target_results:
            ok, why = business_identity.match_business(
                args.business, cand.get("name") or "", cand.get("address") or "", args.city, args.state,
                keap_street=args.street, keap_phone=args.phone, google_phone=cand.get("phone") or "")
            if ok:
                target, target_check = cand, why
                break
            target_check = "no listing matched: " + why
    elif not isinstance(target_results, list):
        target_check = "the lookup failed"

    # Filter competitors: exclude target (fuzzy) + opt-in vertical match
    # + dedupe by normalized name so multiple entrances to the same
    # cemetery/hospital don't all count as separate competitors.
    competitors = []
    # NEARBY means measured on the map, never a shared word (Welton 2026-10-22: "Burd Home Health - Lake Ozark"
    # came back for "home health Ozark MO" from about 100 miles away). It is measured from their own listing.
    # When that listing cannot be confirmed (no phone or street matched one, as at a booth where the rep got no
    # phone), it is measured from the center of the town the rep typed (Welton 2026-10-29), and the rival list
    # takes only listings that are plainly NOT them: a listing sharing a distinctive word with their name could be
    # theirs, so it stays off as can't tell. Saying a listing is someone else needs less evidence than saying it
    # is them, and only this direction is used here.
    nearby, nearby_error, anchor, nearby_from, cant_tell = [], None, None, None, []
    if isinstance(target, dict) and _miles(target, target) is not None:
        anchor, nearby_from = target, "their listing"
    elif args.town_fallback and not target and isinstance(competitor_results, list) and isinstance(target_results, list):
        anchor = _town_point(args.city, args.state, api_key, **pin)
        nearby_from = "the center of %s" % args.city if anchor else None
    if isinstance(competitor_results, list):
        if anchor is None:
            nearby_error = ("their own listing has no map position, so nearby cannot be measured" if target
                            else "their listing could not be confirmed and the town could not be placed on the map,"
                                 " so nearby cannot be measured")
        else:
            nearby = [c for c in competitor_results if not _same_place(c, anchor)
                      and (_miles(c, anchor) or NEARBY_MILES + 1) <= NEARBY_MILES]
    # Unconfirmed: the places of every listing that could be theirs. A listing inside one of them (the Great Mausoleum
    # inside Forest Lawn, by Google's containingPlaces) is not plainly a different business either (Welton 2026-10-22:
    # never a building on their own grounds).
    maybe_theirs = set()
    if not target and nearby_from not in (None, "their listing"):
        for p in (target_results if isinstance(target_results, list) else []) + nearby:
            if p.get("place_id") and _could_be_them(args.business, p.get("name") or "", args.state):
                maybe_theirs.add(p["place_id"])
    if isinstance(competitor_results, list):
        for c in nearby:
            cname = c.get("name", "") or ""
            # The target itself, by its place (maps link) or street address, never by a shared name prefix:
            # "Smithfield" is not "Smith", "Guardian Angels" is not "Angels" (Welton 2026-10-21). The target is
            # never swapped for a same-name listing with more reviews.
            if target and _same_place(c, target):
                continue
            if not target and nearby_from != "their listing" and (
                    _could_be_them(args.business, cname, args.state) or set(c.get("inside") or []) & maybe_theirs):
                cant_tell.append(cname)
                continue
            if not matches_vertical(c, config):
                continue
            # A duplicate is the same PLACE (an entrance inside a cemetery is inside its place), never a shared name
            # (P20, 2026-10-22): "Smith Funeral Home" and "Smith Funeral Home of Lima" are two businesses.
            if any(_same_place(c, prev) for prev in competitors):
                continue
            competitors.append(c)

    output = {
        "target": target if isinstance(target, dict) else {"error": target_check},
        "target_check": target_check,
        "competitors": competitors[:5],
        "vertical": vertical_key,
        "vertical_plural": config["vertical_plural"],
        "outcome_questions": config["outcome_qs"],
        "query_target": target_query,
        "query_competitors": competitor_query,
        # The competitor lookup failed: "no competitors" would be a measured nothing (Welton 2026-10-21).
        "competitors_error": (competitor_results.get("error") if isinstance(competitor_results, dict)
                              else nearby_error),
        # Every nearby listing the lookup read, any trade: the only names the booth sheet's organic Top 3 may print
        # (my-skills/*/scripts/organic_names.py).
        "nearby_listings": nearby,
        # Where "nearby" was measured from, and the nearby listings left off the rival list because they share a
        # word with the name and their listing could not be confirmed (Welton 2026-10-29).
        "nearby_from": nearby_from,
        "cant_tell_listings": cant_tell,
        # What was sent to Google (the words, and the locationBias when pinned) and its whole answer, for each
        # Places search.
        "places_raw": _RAW,
        # Where the searches were pinned, or why they went out with words only (Welton 2026-10-29).
        "places_pin": places_pin,
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
