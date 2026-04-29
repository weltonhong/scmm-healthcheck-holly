"""Shared name matcher for deathcare / senior-care SERP attribution.

Used in two places by every tradeshow-healthcheck skill:
- google_serp_rank.parse_local_pack_from_html: detect whether the
  prospect appears in their own city's 3-Pack
- health_check.build_ads_per_bucket: detect whether the prospect is
  running Google Ads (used as a name-based fallback when the SERP
  scraper returns no displayable ad domain)

Real-world variations the matcher handles:
- Suffix omission: "Holy Cross Catholic Cemetery" vs "Holy Cross Cemetery"
- Suffix addition: "Forest Lawn Memorial Park" vs "Forest Lawn"
- Religious qualifier dropped: "St. Mary's Catholic Cemetery" vs "St. Mary's"
- Punctuation / ampersand: "Smith & Sons" vs "Smith and Sons"
- Corporate suffix: "Smith Funeral Home, Inc." vs "Smith Funeral Home"
- Location appended: "Visiting Angels" vs "Visiting Angels of Tampa Bay"

Match path:
  1. Normalize both names (lowercase, drop punctuation, strip vertical
     and corporate suffix phrases, collapse whitespace).
  2. Substring match either direction -> True.
  3. Else rapidfuzz token_set_ratio >= 85 -> True.
  4. Single-token normalized matches require length >= 5 (e.g. "smith"
     alone is not enough to merge "Smith Cemetery" and "Smith Funeral
     Home" — but "campbell" alone is enough to merge "Frank E. Campbell"
     variants since the prospect side has multiple distinctive tokens).

This matcher trades some precision for recall vs the previous
substring-only approach. The tradeoff is intentional: false negatives on
documented cases (Holy Cross, Forest Lawn) were causing wrong grades on
real scorecards. The regression tests below pin both directions.

This file MUST stay byte-identical across all three skills:
  - my-skills/tradeshow-healthcheck-cemetery/scripts/name_matcher.py
  - my-skills/tradeshow-healthcheck-funeralhome/scripts/name_matcher.py
  - my-skills/tradeshow-healthcheck-homecare/scripts/name_matcher.py
"""

import re

try:
    from rapidfuzz import fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False


# Suffix phrases stripped during normalization. Order matters — longer
# phrases strip first so "Memorial Park" reduces as one phrase, not as
# "Memorial" then "Park" with a residual word in between.
_SUFFIX_PHRASES_RAW = [
    # ----- Cemetery vertical -----
    "memorial park", "memorial gardens", "memorial chapel",
    "memorial parks", "memorial gardens", "memorial chapels",
    "memorial", "memorials", "park", "parks", "gardens",
    "cemetery", "cemeteries", "mausoleum", "columbarium",
    "burial park", "burial grounds",
    # ----- Funeral home vertical -----
    "funeral home", "funeral homes", "funeral chapel", "funeral chapels",
    "the funeral chapel",
    "funeral", "funerals", "mortuary", "mortuaries",
    "chapel", "chapels", "cremation", "cremations", "crematory",
    "crematorium", "crematoriums",
    # ----- Senior care / home care vertical -----
    "home care", "home health", "senior care", "senior living",
    "in home care", "in-home care", "in home senior care",
    "hospice", "hospice care", "assisted living", "memory care",
    "skilled nursing", "personal care",
    # ----- Religious / cultural qualifiers -----
    "catholic", "jewish", "greek orthodox", "russian orthodox",
    "christian", "lutheran", "presbyterian", "methodist", "baptist",
    "pentecostal", "muslim", "buddhist", "hindu",
    "japanese", "chinese", "italian",
    # ----- Corporate suffixes -----
    "limited liability company", "incorporated", "corporation",
    "company", "limited",
    "llc", "l l c", "inc", "corp", "co", "ltd",
    # ----- Connectives -----
    "and", "the", "of", "for", "with",
]
_SUFFIX_PHRASES = sorted(set(_SUFFIX_PHRASES_RAW), key=len, reverse=True)


def _normalize(s):
    """Lowercase, drop punctuation, strip vertical/corporate suffix
    phrases, collapse whitespace. Returns possibly-empty string."""
    if not s:
        return ""
    s = s.lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    changed = True
    while changed:
        changed = False
        for phrase in _SUFFIX_PHRASES:
            new = re.sub(rf"\b{re.escape(phrase)}\b", " ", s)
            if new != s:
                s = re.sub(r"\s+", " ", new).strip()
                changed = True
                # Restart pass: stripping shortens the string and may
                # expose a longer phrase boundary that wasn't a word
                # boundary before.
                break
    return s


def name_matches(prospect, candidate, fuzzy_threshold=85):
    """Return True if prospect and candidate refer to the same business.

    Designed for SERP local-pack and Google Ads attribution. Symmetric:
    name_matches(a, b) == name_matches(b, a).
    """
    if not prospect or not candidate:
        return False
    np = _normalize(prospect)
    nc = _normalize(candidate)
    if not np or not nc:
        return False

    p_tokens = np.split()
    c_tokens = nc.split()

    if np in nc or nc in np:
        # Single-token guard: "smith" alone should not merge "Smith
        # Cemetery" and "Smith Funeral Home". Require >=2 tokens on at
        # least ONE side, OR a 6+ char single token on both sides
        # (rejects common short surnames like "smith"/"jones"/"brown",
        # accepts distinctive single-word brands like "campbell").
        if len(p_tokens) >= 2 or len(c_tokens) >= 2:
            return True
        if len(np) >= 6 and len(nc) >= 6:
            return True
        return False

    if _HAS_RAPIDFUZZ:
        ratio = fuzz.token_set_ratio(np, nc)
        return ratio >= fuzzy_threshold

    # Fallback when rapidfuzz isn't installed.
    p_set = set(p_tokens)
    c_set = set(c_tokens)
    shared = p_set & c_set
    if len(shared) >= 2 and (p_set.issubset(c_set) or c_set.issubset(p_set)):
        return True
    return False


# ---------- regression tests ----------

_CASES = [
    # Should MATCH (false negatives the previous matcher hit)
    ("Holy Cross Catholic Cemetery", "Holy Cross Cemetery", True),
    ("Holy Cross Catholic Cemetery", "Holy Cross Cathedral Cemetery", True),
    ("Forest Lawn Memorial Park", "Forest Lawn", True),
    ("Forest Lawn Memorial Park", "Forest Lawn Glendale", True),
    ("Visiting Angels", "Visiting Angels of Tampa Bay", True),
    ("Frank E. Campbell", "Frank E. Campbell, The Funeral Chapel", True),
    ("Smith & Sons Funeral Home", "Smith and Sons", True),
    ("St. Mary's Catholic Cemetery", "St. Mary's", True),
    ("Cypress Lawn Funeral Home & Memorial Park",
     "Cypress Lawn Funeral Home & Memorial Park", True),
    # Should NOT MATCH (false positive guards)
    ("Comfort Keepers", "Comfort Touch Home Care", False),
    ("Home Instead", "Home Helpers Senior Care", False),
    ("Riverside Memorial Chapel", "Riverdale Funeral Home", False),
    ("Smith Cemetery", "Smith Funeral Home", False),  # single 'smith' too generic
    ("BrightStar Care", "Bright Horizons Home Care", False),
]


def _run_self_test():
    failures = []
    for prospect, candidate, expected in _CASES:
        actual = name_matches(prospect, candidate)
        status = "OK  " if actual == expected else "FAIL"
        line = (
            f"[{status}] {prospect!r:60s} <-> {candidate!r:60s}  "
            f"expected={expected}, got={actual}"
        )
        print(line)
        if actual != expected:
            failures.append(line)
    return failures


if __name__ == "__main__":
    import sys
    print(f"rapidfuzz available: {_HAS_RAPIDFUZZ}")
    print()
    failures = _run_self_test()
    print()
    if failures:
        print(f"{len(failures)} FAILED")
        sys.exit(1)
    print(f"All {len(_CASES)} cases passed")
