"""
Trade Show Online Health Check - Home Care Edition

Fast (60-90 second) online presence audit for a home care prospect.
Designed for live use at a trade show booth: prints results to terminal
as each check completes, then generates a branded one-page PDF.

Runs all checks in parallel:
  1. Google Reviews + top competitor (Google Places API)
  2. Google 3-Pack from each user-supplied city (Places API + location bias)
  3. SEO organic ranking from each user-supplied city (real Google via UULE)
  4. Website audit (homepage scrape + heuristics)
  5. Reviews snapshot (Google from Places, FB/Yelp via search)
  6. Competitor ads check from each user-supplied city (parsed from SERP HTML)

Usage:
    python health_check.py "Comfort Keepers" "Tampa" "FL" "Plant City" "St Petersburg"

Required: business, home_city, state, second_city
Optional: third_city
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

# Force UTF-8 on stdout/stderr so SERP titles with em-dashes, smart quotes,
# or other non-cp1252 characters don't crash the terminal print on Windows.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Local
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import website_audit  # noqa: E402
import map_identity  # noqa: E402  (which map card is the prospect)
import organic_names  # noqa: E402  (real names in the organic Top 3)
import listing_confirm  # noqa: E402  (the rep confirms the business's own listing)
import ads_words  # noqa: E402  (what the sheet may say about their ads)
import ads_records  # noqa: E402  (Google's ad records for their website, Welton 2026-10-22)
import measured  # noqa: E402  (nothing may rest on a failed search or lookup)
import name_matcher  # noqa: E402


PLACES_API_URL = "https://places.googleapis.com/v1/places:searchText"
GEOCODE_API_URL = "https://maps.googleapis.com/maps/api/geocode/json"

PLACES_FIELD_MASK = (
    "places.displayName,"
    "places.formattedAddress,"
    "places.rating,"
    "places.userRatingCount,"
    "places.businessStatus,"
    "places.websiteUri,"
    "places.googleMapsUri"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ----------------------------- agency vs directory filter -----------------------------

# Domains that are directories, info hubs, government/medical sites, social
# networks, or job boards -- not real home care agency websites.
DIRECTORY_DOMAINS = {
    # Senior care directories
    "caring.com", "agingcare.com", "aplaceformom.com", "payingforseniorcare.com",
    "seniorliving.org", "seniorhomes.com", "senioradvisor.com", "helpadvisor.com",
    "seniorcare.com", "assistedliving.org", "aging.com",
    # Government and medical info
    "medicare.gov", "medicaid.gov", "nia.nih.gov", "nih.gov", "cdc.gov",
    "hhs.gov", "va.gov", "ahrq.gov",
    # Health information sites
    "healthline.com", "webmd.com", "mayoclinic.org", "verywellhealth.com",
    "everydayhealth.com", "health.com",
    # Advocacy / nonprofit info
    "aarp.org", "ncoa.org", "alz.org", "alzheimers.org", "thearc.org",
    # Review aggregators / business directories
    "yelp.com", "bbb.org", "yellowpages.com", "whitepages.com", "manta.com",
    "expertise.com", "threebestrated.com", "angi.com", "angieslist.com",
    "thumbtack.com", "homeadvisor.com", "consumeraffairs.com", "trustpilot.com",
    # Social and Q&A
    "facebook.com", "linkedin.com", "youtube.com", "instagram.com",
    "twitter.com", "x.com", "reddit.com", "quora.com", "nextdoor.com",
    "pinterest.com", "tiktok.com",
    # Job boards
    "indeed.com", "glassdoor.com", "ziprecruiter.com", "monster.com",
    "careerbuilder.com",
    # Reference / encyclopedia
    "wikipedia.org",
}

# Title patterns that indicate informational / blog / how-to content rather
# than an actual agency homepage.
INFO_TITLE_PATTERNS = [
    r"^how\s",
    r"^what\s",
    r"^why\s",
    r"^when\s",
    r"^where\s",
    r"^which\s",
    r"\bwhat is\b",
    r"\bwhat are\b",
    r"\bvs\.?\s",
    r"\s\bvs\b\s",
    r"\bcost of\b",
    r"\bcost in\b",
    r"\bhow much\b",
    r"\bguide to\b",
    r"\bguide\s*$",
    r"\bexplained\b",
    r"\bdifference between\b",
    r"\b\d{4}\s+(income|asset|guide|update|rates?)",
    r"\bchecklist\b",
    r"\bfaq\b",
    r"\bdefinition\b",
    r"\bbenefits of\b",
    r"\btypes of\b",
    r"\bsigns? (that|of|your)\b",
    # Listicle / "best 10" / "top 5" / "the best 10 home health care in..."
    r"\btop\s+\d+\b",
    r"\bbest\s+\d+\b",
    r"\b\d+\s+best\b",
    r"\bthe\s+best\s+\d+",
    r"^the\s+\d+\s+best\b",
    r"\bbest\s+\w+\s+(care|health)\s+in\b",
    r"\bbest of\b",
    r"\bbest\s+\w+\s+\w+\s+in\b",
    r"\breviews?\s+of\b",
    # "Top Home Care Agencies in Bamberg, SC" / "Best Senior Care in..."
    # patterns - directory/listicle pages, not real businesses.
    r"^top\s+(home|senior|in[\-\s]home|adult|family|elder)",
    r"^best\s+(home|senior|in[\-\s]home|adult|family|elder)",
    r"\b(home|senior|in[\-\s]home)\s+care\s+(agencies|providers)\s+in\b",
    r"\bagencies?\s+in\s+\w+",
]


# Words that, by themselves, do not identify a real agency. Used to detect
# titles that are just generic SEO bait ("Home Care", "Adult Family Home").
GENERIC_TITLE_WORDS = {
    "home", "care", "senior", "seniors", "adult", "family", "health",
    "services", "service", "agency", "agencies", "help", "support",
    "aide", "aides", "assistance", "caregiver", "caregivers", "medical",
    "nursing", "nurse", "in", "the", "of", "and", "for", "with", "best",
    "trusted", "your", "our", "professional", "quality",
    "wa", "ca", "az", "fl", "tx", "ny", "co", "nv",
}



# Debug tracing is OFF unless HEALTHCHECK_DEBUG=1.
#
# These prints go to stdout, and the webapp streams stdout LIVE into a progress
# box the prospect can read over the rep's shoulder while the scan runs. Raw
# domains, page titles and KEEP lines are our plumbing, and they have been on
# that screen since 2026-04-12. Off by default; still one env var away when
# something needs diagnosing.
DEBUG = os.environ.get("HEALTHCHECK_DEBUG") == "1"


def _debug(msg):
    """Print only when HEALTHCHECK_DEBUG=1."""
    if DEBUG:
        print(msg)


def _join_human(items):
    """['A','B','C'] -> 'A, B and C'. For a line a prospect reads."""
    items = [str(i) for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]

def is_generic_title(title):
    if not title:
        return True
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", title).lower()
    words = [w for w in cleaned.split() if w]
    if not words:
        return True
    non_generic = [w for w in words if w not in GENERIC_TITLE_WORDS and len(w) >= 3]
    return len(non_generic) == 0


# Atomic word dictionary for splitting concatenated domain names like
# 'ssmhealthathome' into 'ssm health at home'. Only atomic words (no
# compounds like 'homecare') so multi-word domains split fully.
_DOMAIN_WORD_SPLITS = sorted([
    "care", "home", "health", "senior", "family", "services", "service",
    "agency", "living", "helpers", "instead", "angels", "keepers",
    "brightstar", "visiting", "comfort", "always", "best", "caring",
    "support", "elderly", "adult", "nursing", "medical", "private",
    "duty", "personal", "quality", "trusted", "professional", "premier",
    "preferred", "golden", "blessed", "loving", "hearts", "heart",
    "hands", "touch", "right", "my", "your", "our", "at", "of", "for",
    "and", "the",
], key=len, reverse=True)

_SHORT_PARTICLES = {"at", "of", "my"}


def humanize_domain(domain):
    """Convert 'home-instead.com' -> 'Home Instead'. Also splits
    camelCase-ish concatenated domains like 'ssmhealthathome' using a
    greedy word dictionary so we get 'SSM Health At Home' rather than
    'Ssmhealthathome'."""
    if not domain:
        return ""
    domain = re.sub(r"^https?://", "", domain)
    domain = re.sub(r"^www\.", "", domain)
    host = domain.split("/")[0]
    parts = host.split(".")
    sld = parts[-2] if len(parts) >= 2 else parts[0]
    pieces = [p for p in re.split(r"[-_]", sld) if p]
    expanded = []
    for p in pieces:
        remaining = p.lower()
        found_any = True
        segments = []
        while remaining and found_any:
            found_any = False
            for word in _DOMAIN_WORD_SPLITS:
                if not remaining.endswith(word):
                    continue
                if len(remaining) < len(word):
                    continue
                stub_len = len(remaining) - len(word)
                if word in _SHORT_PARTICLES and stub_len > 0 and stub_len < 3:
                    continue
                segments.insert(0, word)
                remaining = remaining[: -len(word)]
                found_any = True
                break
        if remaining:
            segments.insert(0, remaining)
        expanded.extend(segments if segments else [p])
    return " ".join(p.capitalize() for p in expanded)


def display_name_from_result(result):
    """Return the humanized domain as the display name for an organic result.

    Page titles are unreliable (they contain city names, marketing copy, and
    "Costs and Financial Assistance" style listicles). The domain is the
    actual brand for home care agencies, so always derive the name from it.
    """
    domain = (result.get("domain") or "").strip()
    if domain:
        return humanize_domain(domain)
    return (result.get("title") or "").strip()


def is_real_agency_result(result):
    """Decide whether an organic SERP result looks like a real home care agency
    website (vs. directory, info article, government site, etc.)."""
    domain = (result.get("domain") or "").lower()
    title = (result.get("title") or "").lower()

    if not domain:
        return False

    for bad in DIRECTORY_DOMAINS:
        if bad == domain or domain.endswith("." + bad):
            return False

    for pat in INFO_TITLE_PATTERNS:
        if re.search(pat, title):
            return False

    return True


# ----------------------------- helpers -----------------------------


def get_google_api_key():
    key = os.environ.get("GOOGLE_API_KEY", "")
    if key:
        return key
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "[System.Environment]::GetEnvironmentVariable('GOOGLE_API_KEY', 'User')"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()
    except Exception:
        return ""


def fuzzy_name_match(a, b):
    if not a or not b:
        return False
    na = re.sub(r"[^a-z0-9 ]", "", a.lower()).strip()
    nb = re.sub(r"[^a-z0-9 ]", "", b.lower()).strip()
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    a_words = [w for w in na.split() if len(w) > 2]
    if a_words and all(w in nb for w in a_words):
        return True
    return False


# --- state-checked geocode: byte-identical in all five booth tools, enforced by
# tradeshow-healthcheck-homecare/scripts/test_geocode_state_guard.py ---
# A LOOKUP THAT CANNOT REFUSE A WRONG-STATE ANSWER IS THE DEFECT, whichever
# service it asks (Welton, 2026-10-13). Google fails less often than Nominatim;
# it does not tell you when it failed. When the request names a state, only an
# answer in that state is used.
_US_STATE_CODES = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())


def _requested_state(address):
    """The two-letter state the request names ('Orange, CT', 'Orange CT 06477',
    '..., CT 06477, USA'), or None when it names none."""
    m = re.search(r"\b([A-Za-z]{2})\b(?:\s+\d{5}(?:-\d{4})?)?(?:\s*,?\s*(?:USA|United States))?\s*$",
                  address or "")
    st = m.group(1).upper() if m else None
    return st if st in _US_STATE_CODES else None


def _result_in_state(result, state):
    return any("administrative_area_level_1" in (c.get("types") or []) and c.get("short_name") == state
               for c in result.get("address_components") or [])


# A TOWN IS NOT ITS COUNTY (Welton, 2026-10-14). A place lookup never returns
# a county-, state- or country-level answer; a street or town answer passes.
# Byte-identical in every Google lookup that carries it; enforced by
# ops/test_town_not_county.py.
_REGION_TYPES = {"administrative_area_level_1", "administrative_area_level_2", "country"}


def _not_a_region(results):
    kept = [r for r in results if not set(r.get("types") or ()) & _REGION_TYPES]
    if results and not kept:
        print("  WARNING: only a county- or state-level geocode came back; refusing it")
    return kept


def geocode(address, api_key):
    want = _requested_state(address)
    url = f"{GEOCODE_API_URL}?{urllib.parse.urlencode({'address': address, 'key': api_key})}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        results = _not_a_region(data.get("results") or [])
        for res in results:
            if want and not _result_in_state(res, want):
                continue
            loc = res["geometry"]["location"]
            return loc["lat"], loc["lng"]
        if want and results:
            print(f"WARNING: no in-state geocode for {address!r}; refusing out-of-state answers")
    except Exception:
        pass
    return None, None


def places_text_search(query, api_key, lat=None, lng=None, radius=15000, max_results=10):
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": PLACES_FIELD_MASK,
    }
    body = {"textQuery": query, "maxResultCount": max_results}
    if lat is not None and lng is not None:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": radius,
            }
        }
    body_bytes = json.dumps(body).encode("utf-8")
    try:
        req = urllib.request.Request(
            PLACES_API_URL, data=body_bytes, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def parse_places(data):
    out = []
    for p in data.get("places", []):
        out.append({
            "name": p.get("displayName", {}).get("text", ""),
            "address": p.get("formattedAddress", ""),
            "rating": p.get("rating"),
            "review_count": p.get("userRatingCount"),
            "status": p.get("businessStatus", ""),
            "website": p.get("websiteUri", ""),
            "maps_url": p.get("googleMapsUri", ""),
        })
    return out


# ----------------------------- check functions -----------------------------


def check_google_intel(business, city, state):
    """Wrap quick-intel/google_intel.py for target + competitor data."""
    repo_root = SCRIPT_DIR.parents[2]
    intel_script = repo_root / "my-skills" / "quick-intel" / "scripts" / "google_intel.py"
    try:
        result = subprocess.run(
            [
                sys.executable, str(intel_script),
                "--business", business,
                "--city", city,
                "--state", state,
                "--vertical", "home care",
            ],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip() or "google_intel failed"}
        return json.loads(result.stdout)
    except Exception as e:
        return {"error": str(e)}


def build_pack_from_seo(cities, seo_per_city):
    """Derive 3-Pack results from the local_pack data already parsed out of
    each city's Google SERP. No extra fetches; same SERP that gave us the
    organic rank also has the Local Map Pack section.

    Returns {"cities": [...], "results": {city: {rank, in_3_pack, top_3}}}.

    A city whose SERP fetch FAILED carries an "error" key instead. That
    distinction is load-bearing: without it a failed fetch collapses to
    in_3_pack=False, which renders identically to "we scanned and you are
    genuinely not in the 3-Pack" -- a false claim made to a prospect. The
    graders and the PDF estimators must exclude errored cities rather than
    count them as misses.
    """
    out = {"cities": list(cities), "results": {}}
    for c in cities:
        d = seo_per_city.get(c) or {}
        err = d.get("error")
        if err:
            out["results"][c] = {
                "rank": None, "in_3_pack": False, "top_3": [], "error": err,
            }
            continue
        lp = d.get("local_pack") or {}
        out["results"][c] = {
            "rank": lp.get("rank"),
            "in_3_pack": bool(lp.get("in_3_pack")),
            "top_3": lp.get("top_3") or [],
            "maybe_rank": lp.get("maybe_rank"),
            "no_id": lp.get("no_id"),
            # Carried so the renderers can tell a CONFIRMED absence of a map
            # pack from one nobody could confirm. Without it the two collapse
            # and print the same sentence.
            "confirmed_empty": bool(lp.get("confirmed_empty")),
            "pack_note": lp.get("pack_note"),
        }
    for key, row in out["results"].items():
        door = (seo_per_city.get(key) or {}).get("door")
        if door is None or door.get("error") == measured.NO_DOOR:
            row["door"] = {"error": measured.NO_DOOR}
        elif door.get("error"):
            row["door"] = {"rank": None, "in_3_pack": False, "top_3": [], "error": door["error"]}
        else:
            lp = door.get("local_pack") or {}
            row["door"] = {"rank": lp.get("rank"), "in_3_pack": bool(lp.get("in_3_pack")),
                           "top_3": lp.get("top_3") or [], "maybe_rank": lp.get("maybe_rank"),
                           "no_id": lp.get("no_id"), "confirmed_empty": bool(lp.get("confirmed_empty")),
                           "pack_note": lp.get("pack_note")}
    return out


def ddg_html_search(query):
    """DuckDuckGo HTML search; returns list of {title, url}."""
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        html = r.text
    except Exception:
        return None      # couldn't check: never an empty answer
    if r.status_code != 200 or ('result__a' not in html and 'No results' not in html):
        return None      # not a results page (a block or a challenge page): couldn't check
    results = []
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for m in pattern.finditer(html):
        href = m.group(1)
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if "uddg=" in href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            href = qs.get("uddg", [href])[0]
        results.append({"title": title, "url": href})
        if len(results) >= 15:
            break
    return results


def check_seo_per_city(business, website, cities, state, own_cids=(), listings=(), door=None):
    """For each city, run SERP rank script with one query 'home care {city} {state}'.

    Each city uses its own UULE so the result is geo-targeted to that city.
    Returns {city: {query, rank, top_3, ads, error?}}.
    """
    biz_domain = ""
    if website:
        try:
            biz_domain = urllib.parse.urlparse(
                website if website.startswith("http") else "https://" + website
            ).netloc.lower().replace("www.", "")
        except Exception:
            biz_domain = ""

    serp_script = SCRIPT_DIR / "google_serp_rank.py"

    def run_one(city, latlng=None):
        query = f"home care {city} {state}"
        try:
            result = subprocess.run(
                [
                    sys.executable, str(serp_script),
                    "--business", business,
                    "--domain", website or "",      # the whole listing website: a page on a company-wide site (W8)
                    "--city", f"{city} {state}",
                    "--queries", query,
                    "--cids", ",".join(own_cids),
                    *(["--latlng", "%s,%s" % tuple(latlng)] if latlng else []),
                ],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                return city, {
                    "query": query, "rank": None, "top_3": [], "ads": [],
                    "error": result.stderr.strip()[:200] or "serp script failed",
                }
            data = json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            return city, {
                "query": query, "rank": None, "top_3": [], "ads": [],
                "error": "timeout",
            }
        except Exception as e:
            return city, {
                "query": query, "rank": None, "top_3": [], "ads": [],
                "error": str(e),
            }

        match = next(
            (x for x in data.get("queries", []) if x.get("query") == query), None
        )
        if not match:
            return city, {
                "query": query, "rank": None, "top_3": [], "ads": [],
                "error": "no result",
            }
        if match.get("error"):
            return city, {
                "query": query, "rank": None, "top_3": [],
                "ads": match.get("ads") or [],
                "error": match["error"],
            }
        # DEBUG: print raw scraper output so we can trace why SEO names
        # sometimes come through as page titles instead of business names.
        raw_results = match.get("results") or []
        _debug(f"[DEBUG SEO {city}] raw results count: {len(raw_results)}")
        for i, r in enumerate(raw_results[:6]):
            _debug(
                f"[DEBUG SEO {city}] #{i+1}: "
                f"domain={r.get('domain')!r} "
                f"title={(r.get('title') or '')[:80]!r}"
            )
        sys.stdout.flush()

        # Real business names only, on their own sites; the prospect's own result
        # prints their name written properly (scripts/organic_names.py, Welton
        # 2026-10-20: "Mapquest", "Clarkcountynv" and "Lapaloma" on the La Paloma
        # sheet). The old directory filter stays as an extra skip only.
        top_3 = organic_names.top_names(
            raw_results, website, business,
            skip=lambda r: not is_real_agency_result(r), town=city, listings=listings)
        above = organic_names.above_names(raw_results, website, business, rank=match.get("rank"), listings=listings)
        sys.stdout.flush()

        raw_ads = match.get("ads") or []
        _debug(f"[DEBUG ADS {city}] raw ads count: {len(raw_ads)}")
        for i, a in enumerate(raw_ads[:8]):
            _debug(
                f"[DEBUG ADS {city}] #{i+1}: "
                f"name={a.get('name')!r} domain={a.get('domain')!r}"
            )
        sys.stdout.flush()

        return city, {
            "query": query,
            "rank": match.get("rank"),
            # No website to compare: no result can be called theirs (scripts/measured.py).
            "organic_error": match.get("organic_error"),
            "organic_maybe": match.get("organic_maybe"),
            "top_3": top_3,
            "above": [] if match.get("organic_error") or match.get("organic_maybe") else above,
            "ads": raw_ads,
            "local_pack": match.get("local_pack") or {
                "rank": None, "in_3_pack": False, "top_3": []
            },
        }

    # The same searches from the prospect's own address, alongside (Welton 2026-10-22). Each row keeps its
    # town-centre answer where every reader looks, and the office answer beside it as "door".
    door_pool = ThreadPoolExecutor(max_workers=max(1, len(cities))) if door else None
    door_futs = [door_pool.submit(run_one, k, door) for k in cities] if door else []
    out = {}
    with ThreadPoolExecutor(max_workers=max(1, len(cities))) as ex:
        futures = [ex.submit(run_one, c) for c in cities]
        for f in as_completed(futures):
            city, data = f.result()
            out[city] = data
            # They finish out of order, which is fine and worth showing: it is
            # the only sign the scan is alive now the debug noise is gone.
            print(f"  {city} ... done")
            sys.stdout.flush()
    for f in door_futs:
        key, data = f.result()
        if key in out:
            out[key]["door"] = data
    if door_pool:
        door_pool.shutdown()
    for key in out:
        out[key].setdefault("door", {"error": measured.NO_DOOR})
    return out


def check_website(website):
    if not website:
        return {
            "error": "no website on Google listing",
            "checks": {},
            "grade": None,
            "unverified": True,
            "unverified_reason": "No website listed on Google profile",
        }
    result = website_audit.audit(website)
    err = (result.get("error") or "").lower()
    is_blocked = (
        "403" in err
        or "timeout" in err
        or "fetch failed" in err
        or "ssl" in err
        or err.startswith("http 4")
        or err.startswith("http 5")
    )
    if is_blocked or (result.get("error") and not result.get("checks")):
        result["grade"] = None
        result["unverified"] = True
        refused = "403" in err or "429" in err or "blocked" in err or "captcha" in err
        result["unverified_reason"] = result.get("unverified_reason") or (
            "Website blocked our scan" if refused else "Couldn't check (the site did not load for us)")
    return result


def _snapshot_line(site, found, not_found):
    """Facebook / Yelp in the live log: found, not found, or couldn't check when the search failed."""
    site = site or {}
    if site.get("url"):
        return found
    return not_found if site.get("checked", True) else "Couldn't check"


def check_reviews_snapshot(business, city, state, google_data):
    """Pull review counts from Google (already have it) + try FB and Yelp via search."""
    snapshot = {
        "google": {
            "count": (google_data.get("target") or {}).get("review_count"),
            "rating": (google_data.get("target") or {}).get("rating"),
        },
        "facebook": {"count": None, "rating": None, "url": ""},
        "yelp": {"count": None, "rating": None, "url": ""},
    }

    fb_results = ddg_html_search(f'"{business}" {city} {state} site:facebook.com')
    snapshot["facebook"]["checked"] = fb_results is not None and not (
        not snapshot["facebook"]["url"] and any("facebook.com" in r["url"] for r in (fb_results or [])))
    for r in (fb_results or [])[:5]:
        # Theirs only when the page's title carries their name; a page that does not is not "found", and
        # pages that came back unnamed make it couldn't check (Welton 2026-10-21).
        if "facebook.com" in r["url"] and "/pages" not in r["url"] and name_matcher.name_matches(r.get("title") or "", business):
            snapshot["facebook"]["url"] = r["url"]
            break

    yelp_results = ddg_html_search(f'"{business}" {city} {state} site:yelp.com')
    snapshot["yelp"]["checked"] = yelp_results is not None and not (
        not snapshot["yelp"]["url"] and any("yelp.com/biz" in r["url"] for r in (yelp_results or [])))
    for r in (yelp_results or [])[:5]:
        if "yelp.com/biz" in r["url"] and name_matcher.name_matches(r.get("title") or "", business):
            snapshot["yelp"]["url"] = r["url"]
            m = re.search(r"(\d+)\s+reviews?", r["title"], re.IGNORECASE)
            if m:
                snapshot["yelp"]["count"] = int(m.group(1))
            break

    return snapshot


def _strict_name_match(target, candidate):
    """Strict business-name comparison for ad-vs-competitor matching."""
    def norm(s):
        s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
        s = re.sub(r"\s+", " ", s).strip()
        for suf in (" llc", " inc", " corp", " co", " ltd"):
            if s.endswith(suf):
                s = s[: -len(suf)]
        return s

    a = norm(target)
    b = norm(candidate)
    if not a or not b:
        return False
    if len(a) < 5 or len(b) < 5:
        return False
    return a in b or b in a


# Words that don't distinguish a local franchisee from its parent brand.
# When matching the prospect against an ad advertiser, we require the
# prospect's *distinctive* tokens (the words NOT in this list) to all
# appear in the candidate -- so "Visiting Angels Fredericksburg" only
# matches an ad whose advertiser name actually contains "Fredericksburg".
FRANCHISE_STOPWORDS = {
    # Generic vertical / care vocabulary
    "home", "homes", "care", "cares", "services", "service", "agency",
    "agencies", "senior", "seniors", "elder", "elderly", "adult", "family",
    "health", "healthcare", "nursing", "nurse", "support", "assistance",
    "caregiver", "caregivers", "personal", "private", "professional",
    "trusted", "reliable", "quality", "premier", "premium", "elite",
    "first", "live", "responsive",
    # Common franchise brand words (parent brand portion only)
    "visiting", "angels", "comfort", "keepers", "instead", "brightstar",
    "helpers", "right", "always", "best", "fathers", "heart", "amada",
    "synergy", "homewell", "homewatch", "interim", "addus", "griswold",
    "touching", "hearts", "bayada", "amedisys", "lhc", "lhcgroup",
    # Connectors and corporate suffixes
    "in", "of", "the", "and", "for", "to", "with", "at", "by", "on",
    "co", "inc", "llc", "corp", "ltd", "company", "limited", "group",
    # Direction qualifiers that are too common to be distinctive alone
    "north", "south", "east", "west", "central", "greater", "metro",
    "area", "region", "regional", "county",
}


def distinctive_tokens(name):
    """Return tokens that distinguish a local franchisee from its parent brand.

    For "Visiting Angels Senior Home Care Fredericksburg", returns
    {"fredericksburg"}. For "Always Best Care Of Madison", returns {"madison"}.
    For "Acti-Kare Responsive In-Home Care" (no location qualifier), falls
    back to brand-distinctive tokens like {"acti", "kare"}.
    """
    if not name:
        return set()
    tokens = re.findall(r"[a-z0-9]+", name.lower())
    distinctive = [t for t in tokens if t not in FRANCHISE_STOPWORDS and len(t) >= 3]
    if distinctive:
        return set(distinctive)
    # Fallback: any 4+ char token (handles brands with no location)
    return set(t for t in tokens if len(t) >= 4)


CONNECTOR_TOKENS = {
    "of", "the", "and", "for", "in", "to", "at", "by", "on",
    "a", "an", "with", "from", "or",
    "co", "inc", "llc", "corp", "ltd", "company", "limited", "group",
    "md", "wa", "ca", "az", "fl", "tx", "ny", "co", "nv", "wi", "va",
    "or", "il", "ga", "nc", "sc", "tn", "ky", "oh", "pa", "nj", "ma",
    "mn", "mi", "mo", "ks", "ne", "ia", "in", "ar", "la", "ms", "al",
}


def match_local_franchise(prospect, candidate):
    """True only if EVERY meaningful token of the prospect name appears in
    the candidate. Strict full-name match prevents national franchise ads
    from being attributed to local franchisees that just share a brand word
    (e.g., "Visiting Angels" national ad vs "Visiting Angels Fredericksburg"),
    AND prevents bleed-through where a competing brand mentions the same
    city name (e.g., "Senior Helpers of Stafford & Fredericksburg" should
    NOT match "Visiting Angels ... Fredericksburg").
    """
    if not prospect or not candidate:
        return False
    p_tokens = [
        t for t in re.findall(r"[a-z0-9]+", prospect.lower())
        if t not in CONNECTOR_TOKENS and len(t) >= 2
    ]
    if not p_tokens:
        return False
    c_text = re.sub(r"[^a-z0-9 ]", " ", (candidate or "").lower())
    return all(t in c_text for t in p_tokens)


def normalize_domain(d):
    """Strip protocol, www, and path; return lowercase host or empty."""
    if not d:
        return ""
    d = d.strip().lower()
    d = re.sub(r"^https?://", "", d)
    if d.startswith("www."):
        d = d[4:]
    d = d.split("/")[0].split("?")[0]
    return d


def build_ads_per_city(business, competitors, seo_per_city, prospect_website=""):
    """For each city, derive ads info from that city's SERP ad block.

    Prospect-as-running detection: ONLY match if the ad's display domain
    equals the prospect's actual website domain. Corporate franchise ads
    using the master domain (visitingangels.com, homeinstead.com, etc.) do
    NOT count as the local franchisee running ads, because the local owner
    is not paying for them.

    Returns {city: {prospect_running_ads, prospect_match, all_advertisers,
                    competitors_running_ads}}
    """
    prospect_domain = normalize_domain(prospect_website)

    out = {}
    for city, data in seo_per_city.items():
        ads_list = data.get("ads") or []

        # Build deduped list of advertiser names for display
        # An ad's headline is its copy, not its maker: an ad is named only by its link, and every
        # other ad is counted and named by nobody (scripts/ads_words.py, Welton 2026-10-21).
        names, unnamed, comp_names = ads_words.advertisers(ads_list, competitors, business, prospect_website)

        # 1) Domain-only prospect detection. Walk the raw ads_list (not the
        # deduped names) so we can compare each ad's display domain against
        # the prospect's actual website.
        prospect_match = None
        prospect_site_maybe = None
        # Theirs by its address (scripts/measured.py page_verdict, W8): their whole domain, or
        # their own page on a company-wide site. Elsewhere on that site: could not confirm.
        if prospect_domain:
            for adv in ads_list:
                v = measured.page_verdict((adv or {}).get("url") or (adv or {}).get("domain", ""),
                                          prospect_website)
                if v == measured.THEM:
                    prospect_match = (adv or {}).get("name") or (adv or {}).get("domain", "")
                    break
                if v == measured.CANT_TELL and prospect_site_maybe is None:
                    prospect_site_maybe = (adv or {}).get("domain", "")
        # 2) Name-based fallback: many SERP scrapers fail to extract the
        # advertiser's display domain, leaving the domain field empty.
        # Without a name fallback the scorecard prints "Not running"
        # even when the prospect's name is sitting in the ad block.
        # 2) A name alone is not proof (Welton 2026-10-20; prospect_identity's rule). An ad under their
        # name with no readable link, or when their own site is unknown, MAY be theirs: never "seen",
        # never "not seen" (scripts/ads_words.py). An ad whose link is known and is not theirs is not.
        prospect_maybe = None
        if not prospect_match and business:
            for adv in ads_list:
                adv_name = (adv or {}).get("name", "")
                if not adv_name:
                    continue
                if prospect_domain and normalize_domain((adv or {}).get("domain", "")):
                    continue
                if name_matcher.name_matches(business, adv_name):
                    prospect_maybe = adv_name
                    break

        # Competitors keep the loose name matcher -- false positives there
        # are less harmful (the rep just sees similar competitors).
        comp_hits = [{"name": n} for n in comp_names]
        prospect_maybe_site = bool(not prospect_match and not prospect_maybe and prospect_site_maybe)
        if prospect_maybe_site:
            prospect_maybe = prospect_site_maybe

        out[city] = {
            "prospect_running_ads": bool(prospect_match),
            "prospect_match": prospect_match,
            "prospect_maybe_ad": prospect_maybe,
            "all_advertisers": names,
            "ads_unnamed": unnamed,
            "competitors_running_ads": comp_hits,
            # No website: their ad cannot be recognized by its link (scripts/measured.py).
            "theirs_unknown": not prospect_domain,
            "prospect_maybe_site": prospect_maybe_site,
            # Derived from the SAME per-city SERP record, so it inherits that
            # record's failure. Without this the ads row reads a failed fetch
            # as an empty ad block and prints "No ads detected" -- a finding
            # nobody measured.
            "error": data.get("error"),
        }
    return out


# ----------------------------- grading -----------------------------


def grade_reviews(target_count, comp_count=0):
    """Grade is relative when we have a top competitor:
        A = more reviews than the top competitor, OR 100+ total
        B = 50-99 (and behind competitor)
        C = 20-49 (and behind competitor)
        D = 5-19
        F = 0-4

    Winning the head-to-head is always an A regardless of absolute count.
    """
    if target_count is None:
        return "F"
    if (comp_count and target_count > comp_count) or target_count >= 100:
        return "A"
    if target_count >= 50:
        return "B"
    if target_count >= 20:
        return "C"
    if target_count >= 5:
        return "D"
    return "F"


def grade_count_based(found, total):
    """Shared grader: A=found in all, B=found in most (>1 but not all),
    C=found in exactly 1, F=found in none.

    With 2 cities: 2->A, 1->C, 0->F (B never used).
    With 3 cities: 3->A, 2->B, 1->C, 0->F.
    """
    if total == 0:
        # NOTHING WAS MEASURED. Returning "F" here silently undoes the two
        # graders below, which go out of their way to drop unscanned cities
        # so that "we could not check 2 of 3" never renders as "you are
        # missing from 2 of 3" -- and then hand this function total=0 on a
        # total outage, the very case they exist for. overall_grade already
        # skips None as an unverified check; this is that value.
        return None
    if found == 0:
        return "F"
    if found == total:
        return "A"
    if found == 1:
        return "C"
    return "B"


def grade_3pack_multi(pack):
    results = pack.get("results") or {}
    cities = pack.get("cities") or list(results.keys())
    # A city we could not scan is not a city they are absent from. Counting it
    # in the denominator turns "we could not check 2 of 3" into a grade that
    # reads as "you are missing from 2 of 3", which is a fabricated finding.
    # A row with no map pack leaves the denominator whether or not the
    # absence was confirmed. You cannot grade a business on a channel
    # Google does not serve for that search, and an unconfirmed empty
    # is not a measurement at all. A zero denominator already returns
    # None rather than F.
    scanned = [c for c in cities
               if not (results.get(c) or {}).get("error")
               and (results.get(c) or {}).get("top_3")
               and not (results.get(c) or {}).get("maybe_rank")
               and not (results.get(c) or {}).get("no_id")]
    # Both points count (Welton 2026-10-22): found from their office and missing from the town's center is one
    # hit and one miss. The office rows pass the same test as the town rows.
    rows = [results.get(k) or {} for k in scanned]
    rows += [r for r in ((v or {}).get("door") for v in results.values())
             if r and not r.get("error") and r.get("top_3") and not r.get("maybe_rank") and not r.get("no_id")]
    return grade_count_based(sum(1 for r in rows if r.get("in_3_pack")), len(rows))


def grade_seo_multi(seo_per_city):
    # Same reasoning as grade_3pack_multi: an unscanned city is not evidence
    # of absence, so it leaves the denominator entirely.
    cities = [c for c in seo_per_city
              if not measured.organic_failed(seo_per_city.get(c))]
    total = len(cities)
    found = 0
    for c in cities:
        rank = (seo_per_city.get(c) or {}).get("rank")
        if rank is not None and rank <= 10:
            found += 1
    return grade_count_based(found, total)


def grade_ads_multi(ads_per_city):
    """Not graded (Welton 2026-10-21): one look per search shows what was seen, not whether they advertise.
    An F from one look was a claim nothing measured, and an A from one look is no stronger; the row reports
    what was seen (scripts/ads_words.py) and the overall grade is over the graded rows."""
    return None
    # Same reasoning as grade_3pack_multi and grade_seo_multi: one we
    # could not scan is not one they are absent from, so it leaves the
    # denominator entirely. This grader never had that filter.
    cities = [k for k in ads_per_city
              if not (ads_per_city.get(k) or {}).get("error")
              and not (ads_per_city.get(k) or {}).get("theirs_unknown")
              and not ((ads_per_city.get(k) or {}).get("prospect_maybe_ad")
                       and not (ads_per_city.get(k) or {}).get("prospect_running_ads"))]
    total = len(cities)
    found = sum(
        1 for c in cities if (ads_per_city.get(c) or {}).get("prospect_running_ads")
    )
    return grade_count_based(found, total)


def overall_grade(grades):
    """Average of the measured grades; None when nothing was measured, never an F (scripts/measured.py)."""
    return measured.overall_grade(grades)


# ----------------------------- printing -----------------------------


def print_header(business, city, state):
    title = f"ONLINE HEALTH CHECK | {business} {city}, {state}"
    bar = "=" * max(60, len(title) + 4)
    print()
    print(bar)
    print(title)
    print(bar)
    print()
    sys.stdout.flush()


def print_section(label, body):
    print(f"{label}")
    for line in body:
        print(f"  {line}")
    print()
    sys.stdout.flush()


# ----------------------------- main -----------------------------


def run_health_check(business, cities, state, listing=None):
    """cities: list of city names (1-3). First entry is the home city."""
    api_key = get_google_api_key()
    if not api_key:
        print("ERROR: GOOGLE_API_KEY not set in environment.")
        sys.exit(1)

    home_city = cities[0]
    print_header(business, home_city, state)
    started = time.time()

    results = {
        "business": business,
        "city": home_city,
        "cities": list(cities),
        "state": state,
        "scanned_at": datetime.datetime.now().isoformat(),
    }

    # Step 1: Google intel synchronously (everything else depends on the website)
    print(f"Pulling Google data for {home_city}, {state}...")
    sys.stdout.flush()
    intel = check_google_intel(business, home_city, state)
    if listing is not None:
        # The booth app asked the rep "Is this your address?" (scripts/listing_confirm.py).
        # Not confirmed: nothing is taken from Google's first answer for the name.
        intel = listing_confirm.apply(intel, listing)
    results["google_intel"] = intel
    target = intel.get("target") or {}
    # A listing we can stand behind; otherwise every number from it reads "Couldn't check"
    # (also when the lookup itself failed, which used to print "NOT FOUND" and a full gap).
    known = listing_confirm.known(target)
    competitors = intel.get("competitors") or []
    # The prospect's own listing's place id: how map cards are matched to
    # them (scripts/map_identity.py, Welton 2026-10-20).
    own_cids = map_identity.own_cids(target, business)
    website = target.get("website", "")

    target_count = (target.get("review_count") or 0) if known else None
    target_rating = target.get("rating")
    print_section(
        "GOOGLE REVIEWS:",
        [
            (f"{target_count} {measured.reviews_word(target_count)}, {target_rating if target_rating is not None else '-'} stars"
             if known else listing_confirm.reason(target))
        ],
    )

    competitors = [c for c in competitors if not measured.same_listing(c, target, business)]
    if competitors:
        top_comp = max(
            competitors,
            key=lambda c: (c.get("review_count") or 0),
        )
        print_section(
            "MOST-REVIEWED NEARBY LISTING:",
            [
                f"{top_comp.get('name', '?')}: "
                f"{top_comp.get('review_count') or 0} {measured.reviews_word(top_comp.get('review_count') or 0)}, "
                f"{top_comp.get('rating') or '-'} stars"
            ],
        )
        results["top_competitor"] = top_comp
        gap = ((top_comp.get("review_count") or 0) - target_count) if known else 0
        if gap > 0:
            print_section(
                "REVIEW GAP:",
                [f"{gap} {measured.reviews_word(gap)} behind"],
            )
            results["review_gap"] = gap

    # Parallel: SEO (per city, also yields 3-Pack via local_pack), Website, Reviews
    # Plain language on purpose: a prospect reads this over the rep's
    # shoulder, and "SEO+3-Pack" means nothing to them.
    # When the searches ran, for "All searches run at ..." (scripts/measured.py, Welton 2026-10-22).
    results["searched_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(
        f"Checking {_join_human(cities)}. Map results, search results, website and reviews.\n"
    )
    sys.stdout.flush()

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(ads_records.check, website): "ads_records",
            ex.submit(check_seo_per_city, business, website, cities, state, own_cids, intel.get("nearby_listings") or [], measured.door_point(target) if known else None): "seo",
            ex.submit(check_website, website): "website",
            ex.submit(check_reviews_snapshot, business, home_city, state, intel): "reviews",
        }
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                results[name] = fut.result()
            except Exception as e:
                results[name] = {"error": str(e)}

    # 3-Pack is derived from the same SERP data as the SEO check (one fetch
    # per city gives both organic rank and local pack presence).
    if not known and isinstance(results.get("website"), dict) and results["website"].get("unverified"):
        # The website comes from the listing; with none confirmed there is none to read.
        results["website"]["unverified_reason"] = listing_confirm.reason(target)

    results["3pack"] = build_pack_from_seo(cities, results.get("seo", {}))

    # Print 3-Pack
    pack = results.get("3pack", {})
    pack_results = pack.get("results", {})
    label_width = max(len(c) for c in cities) + 8

    def fmt_pack_line(city):
        d = pack_results.get(city) or {}
        label = f"From {city}:"
        if not d or "error" in d:
            return f"{label:<{label_width}} Couldn't check this search"
        top_3_list = d.get("top_3", []) or []
        if not top_3_list:
            if d.get("confirmed_empty"):
                return (f"{label:<{label_width}} Google shows no map "
                        f"pack for this search")
            # Not confirmed. Deliberately says nothing about the prospect: an
            # empty pack from one backend is usually a measurement problem,
            # and a rep reads this row out loud.
            return (f"{label:<{label_width}} Map results "
                    f"unconfirmed for this search")
        top_3_str = ", ".join(top_3_list[:3])
        if d.get("in_3_pack"):
            return f"{label:<{label_width}} FOUND rank {d['rank']} (Top 3: {top_3_str})"
        if d.get("maybe_rank"):
            return (f"{label:<{label_width}} Couldn't confirm: #{d['maybe_rank']} may be you "
                    f"(Top 3: {top_3_str})")
        if d.get("no_id"):
            return f"{label:<{label_width}} Couldn't confirm which card is theirs (Top 3: {top_3_str})"
        return f"{label:<{label_width}} NOT FOUND (Top 3: {top_3_str})"

    pack_grade = grade_3pack_multi(pack)
    pack_lines = [f"{c}: " + measured.map_line(pack_results.get(c), (pack_results.get(c) or {}).get("door"), measured.town_of(c)) for c in cities]
    pack_lines += [n for n in [measured.office_note([(pack_results.get(k) or {}).get("door") for k in cities])] if n]
    pack_lines.append(f"Grade: {measured.grade_text(pack_grade)}")
    print_section("GOOGLE LOCAL MAP RANKINGS:", pack_lines)
    results["pack_grade"] = pack_grade

    # Print SEO
    seo = results.get("seo", {})
    # Not graded (Welton 2026-10-22): organic rank moved five places in forty minutes on our own re-run, so a
    # letter built on one look is not a grade. The map pack and reviews held still; the overall grade rests on
    # those (and the website), never on organic rank.
    seo_grade = None
    def trim_title(t):
        # Decode common HTML entities first
        t = (t or "").replace("&amp;", "&").replace("&#39;", "'") \
                     .replace("&quot;", '"').replace("&#x27;", "'")
        # Split on " | ", " - ", " : ", or " * " (require spaces so "In-Home"
        # is not torn apart). Take the first segment as the brand portion.
        short = re.split(r"\s+[\|\u2022:]\s+|\s+-\s+|\s+\u2013\s+", t, maxsplit=1)[0].strip()
        return (short or t)[:60]

    seo_lines = []
    for c in cities:
        d = seo.get(c) or {}
        rank = d.get("rank")
        top_3 = d.get("top_3") or []
        cleaned = [trim_title(t) for t in top_3[:3] if t]
        if measured.organic_failed(d):
            # A failed fetch is not an absence. Printing "no organic results"
            # here tells a prospect they rank nowhere when nothing was measured,
            # the fabricated finding the 3-Pack row above already refuses.
            seo_lines.append(
                f"{c}: " + measured.organic_line(d, d.get("door"), measured.town_of(c)))
            # The row is decided. Without this the loop falls through and
            # appends a second, contradictory line for the same city.
            continue
        top_3_str = ", ".join(cleaned)
        # No names to list is not "no organic results" (Welton 2026-10-20): the page was read and the
        # rank stands; scripts/organic_names.py only names real businesses, so the list can be empty.
        top_3_part = f" (Top 3: {top_3_str})" if cleaned else ""
        seo_lines.append(f"{c}: " + measured.organic_line(d, d.get("door"), measured.town_of(c)))
    seo_lines += [n for n in [measured.office_note([(seo.get(k) or {}).get("door") for k in cities])] if n]
    seo_lines.append(measured.searched_line(results))
    seo_lines.append(measured.SEO_NOT_GRADED if measured.seo_not_graded(results, seo_grade)
                     else f"Grade: {measured.grade_text(seo_grade)}")
    print_section("GOOGLE ORGANIC RANKINGS (SEO):", seo_lines)
    results["seo_grade"] = seo_grade

    # Ads are off the booth sheet (Welton 2026-10-22): 50 of 53 recorded answers from our search source carried no
    # ads while Chrome showed them, so "No ads seen" meant we were blind, not that the market was empty. No row, no
    # summary, no live-log section, no "open lane", and no "couldn't check" in their place, until a source sees ads.
    ads_grade = None
    results["ads_grade"] = None
    # What Google's ad records show for their website, not graded (scripts/ads_records.py, Welton 2026-10-22).
    print_section("GOOGLE ADS:", [ads_records.line(results.get("ads_records"))])

    # Print Website
    web = results.get("website", {})
    if web.get("unverified"):
        reason = web.get("unverified_reason") or web.get("error") or "blocked"
        print_section("WEBSITE:", [
            reason if reason.startswith("Couldn't check") else f"Couldn't check: {reason}",
            "Grade: not counted in overall",
        ])
        web_grade = None
    else:
        c = web.get("checks", {})

        def yn(v, true_label="Yes", false_label="No"):
            if v is True:
                return true_label
            if v is False:
                return false_label
            return "Couldn't check"

        psi_score = web.get("pagespeed_score")
        if psi_score is None:
            psi_display = "Unable to test"
        else:
            psi_display = f"{measured.speed_text(web)}/100 " + ("(PASS)" if psi_score >= 50 else "(FAIL)")

        blog_last = web.get("blog_last_post")
        blog_display = (
            f"Last post {blog_last}" if blog_last else ("couldn't read the blog" if c.get("blog_recent") is None else "No blog or no recent posts")
        )

        web_lines = [
            f"Real team photos:        {yn(c.get('real_photos'), 'Yes', 'No (stock detected)')}",
            f"PageSpeed mobile:        {psi_display}",
            f"About/Team page:         {yn(c.get('about_team_page'), 'Yes', 'No (generic or missing)')}",
            f"Recent blog (6mo):       {yn(c.get('blog_recent'), 'Yes', 'No')}, {blog_display}",
            f"Intake form/widget:      {yn(c.get('intake_form'), 'Yes', 'Not on the homepage')}",
            f"LocalBusiness schema:    {yn(c.get('localbusiness_schema'), 'Yes', 'No')}",
            f"Google reviews widget:   {yn(c.get('google_reviews_widget'), 'Yes', 'No')}",
            f"Grade: {web.get('grade') or 'none (too little could be read)'}",
        ]
        print_section("WEBSITE:", web_lines)
        web_grade = web.get("grade")
    results["website_grade"] = web_grade

    # Print Reviews snapshot
    rev = results.get("reviews", {})
    rev_lines = [
        (f"Google:   {rev.get('google', {}).get('count', '-')} {measured.reviews_word(rev.get('google', {}).get('count', '-'))}, "
         f"{rev.get('google', {}).get('rating', '-')} stars")
         if known else "Google:   " + listing_confirm.reason(target),
        "Facebook: " + _snapshot_line(rev.get("facebook"), "Page found", "No page turned up in our search"),
        "Yelp:     " + _snapshot_line(
            rev.get("yelp"), ("%s %s (page found)" % (rev["yelp"]["count"], measured.reviews_word(rev["yelp"]["count"]))) if (rev.get("yelp") or {}).get("count")
            else "Page found (review count not read)", "No page turned up in our search"),
    ]
    print_section("REVIEWS SNAPSHOT:", rev_lines)

    # Reviews grade is relative to the top competitor when we have one.
    top_comp_reviews = (results.get("top_competitor") or {}).get("review_count") or 0
    reviews_grade = grade_reviews(target_count, top_comp_reviews) if known else None

    # Overall grade
    grades = [
        reviews_grade,
        pack_grade,
        seo_grade,
        web_grade,
        ads_grade,
    ]
    overall = overall_grade(grades)
    results["overall_grade"] = overall
    results["all_grades"] = {
        "reviews": reviews_grade,
        "3pack": pack_grade,
        "seo": seo_grade,
        "website": web_grade,
        "ads": ads_grade,
    }

    elapsed = round(time.time() - started, 1)
    bar = "=" * 60
    print(bar)
    print(f"OVERALL GRADE: {measured.grade_text(overall)}    (scan time: {elapsed}s)")
    print(bar)
    print()
    sys.stdout.flush()

    return results


def main():
    parser = argparse.ArgumentParser(description="Trade show health check")
    parser.add_argument("business", nargs="?")
    parser.add_argument("city1", nargs="?", help="Home city")
    parser.add_argument("state", nargs="?")
    parser.add_argument("city2", nargs="?", help="Second city to scan from")
    parser.add_argument("city3", nargs="?", help="Third city to scan from (optional)")
    parser.add_argument("--no-pdf", action="store_true", help="Skip PDF generation")
    args = parser.parse_args()

    business = args.business
    city1 = args.city1
    state = args.state
    city2 = args.city2
    city3 = args.city3

    if not (business and city1 and state and city2):
        print(
            "Usage: python health_check.py "
            "'Business Name' 'HomeCity' 'STATE' 'SecondCity' ['ThirdCity']"
        )
        sys.exit(1)

    cities = [city1, city2]
    if city3:
        cities.append(city3)

    results = run_health_check(business, cities, state)

    out_json = SCRIPT_DIR / "temp_health_check.json"
    out_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Raw data saved: {out_json}")

    if not args.no_pdf:
        try:
            import pdf_generator
            pdf_path = pdf_generator.build_pdf(results)
            print(f"PDF generated: {pdf_path}")
        except Exception as e:
            print(f"PDF generation failed: {e}")


if __name__ == "__main__":
    main()
