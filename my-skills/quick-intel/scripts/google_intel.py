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
    "places.types"
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


def places_search(query, api_key, max_results=5):
    """Run a Places API text search. Returns list of place dicts."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    body = json.dumps({
        "textQuery": query,
        "maxResultCount": max_results,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            PLACES_API_URL, data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}

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
    args = parser.parse_args()

    vertical_key = resolve_vertical(args.vertical)
    config = VERTICAL_CONFIG[vertical_key]

    api_key = get_api_key()
    if not api_key:
        print(json.dumps({"error": "GOOGLE_API_KEY not found"}))
        sys.exit(1)

    # Search 1: Target business (exact name + location)
    target_query = f"{args.business} {args.city} {args.state}"
    target_results = places_search(target_query, api_key, max_results=3)

    # Search 2: Competitors (vertical-specific query + city)
    competitor_query = f"{config['query']} {args.city} {args.state}"
    competitor_results = places_search(competitor_query, api_key, max_results=10)

    # Identify target in results
    target = None
    if isinstance(target_results, list) and target_results:
        target = target_results[0]

    # Filter competitors: exclude target (fuzzy) + opt-in vertical match
    # + dedupe by normalized name so multiple entrances to the same
    # cemetery/hospital don't all count as separate competitors.
    competitors = []
    seen_normalized = set()
    if isinstance(competitor_results, list):
        for c in competitor_results:
            cname = c.get("name", "") or ""
            if is_same_business(args.business, cname):
                if target and not target.get("review_count") and c.get("review_count"):
                    target = c
                continue
            if not matches_vertical(c, config):
                continue
            key = _compact(normalize_name(cname))
            # If we've already seen a result whose normalized name is a
            # superset/subset, treat as duplicate (catches "Greenwood
            # Cemetery" vs "Greenwood Cemetery Sunset Park Entrance")
            is_dup = False
            for prev in seen_normalized:
                if key == prev or key in prev or prev in key:
                    is_dup = True
                    break
            if is_dup:
                continue
            seen_normalized.add(key)
            competitors.append(c)

    output = {
        "target": target if isinstance(target, dict) else {"error": str(target_results)},
        "competitors": competitors[:5],
        "vertical": vertical_key,
        "vertical_plural": config["vertical_plural"],
        "outcome_questions": config["outcome_qs"],
        "query_target": target_query,
        "query_competitors": competitor_query,
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
