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


def geocode(address, api_key):
    url = f"{GEOCODE_API_URL}?{urllib.parse.urlencode({'address': address, 'key': api_key})}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
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
    """
    out = {"cities": list(cities), "results": {}}
    for c in cities:
        d = seo_per_city.get(c) or {}
        lp = d.get("local_pack") or {}
        out["results"][c] = {
            "rank": lp.get("rank"),
            "in_3_pack": bool(lp.get("in_3_pack")),
            "top_3": lp.get("top_3") or [],
        }
    return out


def ddg_html_search(query):
    """DuckDuckGo HTML search; returns list of {title, url}."""
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        html = r.text
    except Exception:
        return []
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


def check_seo_per_city(business, website, cities, state):
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

    def run_one(city):
        query = f"home care {city} {state}"
        try:
            result = subprocess.run(
                [
                    sys.executable, str(serp_script),
                    "--business", business,
                    "--domain", biz_domain,
                    "--city", f"{city} {state}",
                    "--queries", query,
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
        print(f"[DEBUG SEO {city}] raw results count: {len(raw_results)}")
        for i, r in enumerate(raw_results[:6]):
            print(
                f"[DEBUG SEO {city}] #{i+1}: "
                f"domain={r.get('domain')!r} "
                f"title={(r.get('title') or '')[:80]!r}"
            )
        sys.stdout.flush()

        # Filter to real home care agency websites only -- skip directories,
        # info articles, and gov/medical sites. For each kept result, use the
        # branded title when present, else humanize the domain (so "Home Care"
        # generic titles fall back to e.g. "Acti Kare").
        top_3 = []
        for r in raw_results:
            if is_real_agency_result(r):
                name = display_name_from_result(r)
                print(
                    f"[DEBUG SEO {city}] KEEP domain={r.get('domain')!r} "
                    f"-> display_name={name!r}"
                )
                if name:
                    top_3.append(name)
                    if len(top_3) >= 3:
                        break
        sys.stdout.flush()

        raw_ads = match.get("ads") or []
        print(f"[DEBUG ADS {city}] raw ads count: {len(raw_ads)}")
        for i, a in enumerate(raw_ads[:8]):
            print(
                f"[DEBUG ADS {city}] #{i+1}: "
                f"name={a.get('name')!r} domain={a.get('domain')!r}"
            )
        sys.stdout.flush()

        return city, {
            "query": query,
            "rank": match.get("rank"),
            "top_3": top_3,
            "ads": raw_ads,
            "local_pack": match.get("local_pack") or {
                "rank": None, "in_3_pack": False, "top_3": []
            },
        }

    out = {}
    with ThreadPoolExecutor(max_workers=max(1, len(cities))) as ex:
        futures = [ex.submit(run_one, c) for c in cities]
        for f in as_completed(futures):
            city, data = f.result()
            out[city] = data
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
        result["unverified_reason"] = "Website blocked our scan"
    return result


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
    for r in fb_results[:5]:
        if "facebook.com" in r["url"] and "/pages" not in r["url"]:
            snapshot["facebook"]["url"] = r["url"]
            break

    yelp_results = ddg_html_search(f'"{business}" {city} {state} site:yelp.com')
    for r in yelp_results[:5]:
        if "yelp.com/biz" in r["url"]:
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
        names = []
        seen = set()
        for adv in ads_list:
            name = (adv or {}).get("name", "")
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(name)

        # Domain-only prospect detection. Walk the raw ads_list (not the
        # deduped names) so we can compare each ad's display domain against
        # the prospect's actual website.
        prospect_match = None
        if prospect_domain:
            for adv in ads_list:
                ad_domain = normalize_domain((adv or {}).get("domain", ""))
                if ad_domain and ad_domain == prospect_domain:
                    prospect_match = (adv or {}).get("name", ad_domain)
                    break

        # Competitors keep the loose name matcher -- false positives there
        # are less harmful (the rep just sees similar competitors).
        comp_hits = []
        seen_matches = set()
        for comp in (competitors or [])[:5]:
            comp_name = (comp.get("name") or "").strip()
            if not comp_name:
                continue
            for n in names:
                if _strict_name_match(comp_name, n) and n.lower() not in seen_matches:
                    comp_hits.append({"name": comp_name, "matched_as": n})
                    seen_matches.add(n.lower())
                    break

        out[city] = {
            "prospect_running_ads": bool(prospect_match),
            "prospect_match": prospect_match,
            "all_advertisers": names,
            "competitors_running_ads": comp_hits,
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
        return "F"
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
    total = len(cities)
    found = sum(1 for c in cities if (results.get(c) or {}).get("in_3_pack"))
    return grade_count_based(found, total)


def grade_seo_multi(seo_per_city):
    cities = list(seo_per_city.keys())
    total = len(cities)
    found = 0
    for c in cities:
        rank = (seo_per_city.get(c) or {}).get("rank")
        if rank is not None and rank <= 10:
            found += 1
    return grade_count_based(found, total)


def grade_ads_multi(ads_per_city):
    cities = list(ads_per_city.keys())
    total = len(cities)
    found = sum(
        1 for c in cities if (ads_per_city.get(c) or {}).get("prospect_running_ads")
    )
    return grade_count_based(found, total)


def overall_grade(grades):
    """Average of grades, ignoring None values (unverified checks)."""
    pts = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
    inv = {4: "A", 3: "B", 2: "C", 1: "D", 0: "F"}
    real = [g for g in grades if g in pts]
    if not real:
        return "F"
    avg = round(sum(pts[g] for g in real) / len(real))
    return inv.get(avg, "F")


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


def run_health_check(business, cities, state):
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
    results["google_intel"] = intel
    target = intel.get("target") or {}
    competitors = intel.get("competitors") or []
    website = target.get("website", "")

    target_count = target.get("review_count")
    target_rating = target.get("rating")
    print_section(
        "GOOGLE REVIEWS:",
        [
            f"{target_count if target_count is not None else 'NOT FOUND'} reviews"
            f", {target_rating if target_rating is not None else '-'} stars"
        ],
    )

    if competitors:
        top_comp = max(
            competitors,
            key=lambda c: (c.get("review_count") or 0),
        )
        print_section(
            "TOP COMPETITOR:",
            [
                f"{top_comp.get('name', '?')} -- "
                f"{top_comp.get('review_count') or 0} reviews, "
                f"{top_comp.get('rating') or '-'} stars"
            ],
        )
        results["top_competitor"] = top_comp
        gap = (top_comp.get("review_count") or 0) - (target_count or 0)
        if gap > 0:
            severity = "CRITICAL" if gap >= 100 else "SIGNIFICANT" if gap >= 30 else "MODERATE"
            print_section(
                "REVIEW GAP:",
                [f"{gap} reviews behind ({severity})"],
            )
            results["review_gap"] = gap

    # Parallel: SEO (per city, also yields 3-Pack via local_pack), Website, Reviews
    print(
        f"Running parallel scans (SEO+3-Pack, Website, Reviews) "
        f"across {len(cities)} cities: {', '.join(cities)}\n"
    )
    sys.stdout.flush()

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {
            ex.submit(check_seo_per_city, business, website, cities, state): "seo",
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
    results["3pack"] = build_pack_from_seo(cities, results.get("seo", {}))

    # Print 3-Pack
    pack = results.get("3pack", {})
    pack_results = pack.get("results", {})
    label_width = max(len(c) for c in cities) + 8

    def fmt_pack_line(city):
        d = pack_results.get(city) or {}
        label = f"From {city}:"
        if not d or "error" in d:
            return f"{label:<{label_width}} ERROR ({d.get('error', '?')})"
        top_3_list = d.get("top_3", []) or []
        if not top_3_list:
            return (
                f"{label:<{label_width}} No local map pack found "
                f"for this city"
            )
        top_3_str = ", ".join(top_3_list[:3])
        if d.get("in_3_pack"):
            return f"{label:<{label_width}} FOUND rank {d['rank']} (Top 3: {top_3_str})"
        return f"{label:<{label_width}} NOT FOUND (Top 3: {top_3_str})"

    pack_grade = grade_3pack_multi(pack)
    pack_lines = [fmt_pack_line(c) for c in cities]
    pack_lines.append(f"Grade: {pack_grade}")
    print_section("GOOGLE LOCAL MAP RANKINGS:", pack_lines)
    results["pack_grade"] = pack_grade

    # Print SEO
    seo = results.get("seo", {})
    seo_grade = grade_seo_multi(seo)
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
        if not cleaned:
            seo_lines.append(f"{c}: No organic results found for this city")
            continue
        top_3_str = ", ".join(cleaned)
        if rank is None:
            seo_lines.append(f"{c}: Not in top 10 (Top 3: {top_3_str})")
        else:
            seo_lines.append(f"{c}: Rank {rank} (Top 3: {top_3_str})")
    seo_lines.append(f"Grade: {seo_grade}")
    print_section("GOOGLE ORGANIC RANKINGS (SEO):", seo_lines)
    results["seo_grade"] = seo_grade

    # Build and print Google Ads per city (BEFORE Website per the new order)
    ads_per_city = build_ads_per_city(
        business, competitors, seo, prospect_website=website
    )
    results["ads"] = ads_per_city
    ads_grade = grade_ads_multi(ads_per_city)
    ads_lines = []
    business_running_anywhere = False
    for c in cities:
        d = ads_per_city.get(c) or {}
        if d.get("prospect_running_ads"):
            business_running_anywhere = True
        advs = d.get("all_advertisers") or []
        if advs:
            ads_lines.append(f"{c}: {', '.join(advs)}")
        else:
            ads_lines.append(f"{c}: No ads detected")
    ads_lines.append(
        f"{business}: {'Running' if business_running_anywhere else 'Not running'}"
    )
    ads_lines.append(f"Grade: {ads_grade}")
    print_section("GOOGLE ADS:", ads_lines)
    results["ads_grade"] = ads_grade

    # Print Website
    web = results.get("website", {})
    if web.get("unverified"):
        reason = web.get("unverified_reason") or web.get("error") or "blocked"
        print_section("WEBSITE:", [
            f"Unable to verify -- {reason}",
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
            return "?"

        psi_score = web.get("pagespeed_score")
        if psi_score is None:
            psi_display = "Unable to test"
        else:
            psi_display = f"{psi_score}/100 " + ("(PASS)" if psi_score >= 50 else "(FAIL)")

        blog_last = web.get("blog_last_post")
        blog_display = (
            f"Last post {blog_last}" if blog_last else "No blog or no recent posts"
        )

        web_lines = [
            f"Real team photos:        {yn(c.get('real_photos'), 'Yes', 'No (stock detected)')}",
            f"PageSpeed mobile:        {psi_display}",
            f"About/Team page:         {yn(c.get('about_team_page'), 'Yes', 'No (generic or missing)')}",
            f"Recent blog (6mo):       {yn(c.get('blog_recent'), 'Yes', 'No')} -- {blog_display}",
            f"Intake form/widget:      {yn(c.get('intake_form'), 'Yes', 'No (phone only)')}",
            f"LocalBusiness schema:    {yn(c.get('localbusiness_schema'), 'Yes', 'No')}",
            f"Google reviews widget:   {yn(c.get('google_reviews_widget'), 'Yes', 'No')}",
            f"Grade: {web.get('grade', 'F')}",
        ]
        print_section("WEBSITE:", web_lines)
        web_grade = web.get("grade", "F")
    results["website_grade"] = web_grade

    # Print Reviews snapshot
    rev = results.get("reviews", {})
    rev_lines = [
        f"Google:   {rev.get('google', {}).get('count', '-')} reviews, "
        f"{rev.get('google', {}).get('rating', '-')} stars",
        f"Facebook: {'Page found' if rev.get('facebook', {}).get('url') else 'Not found'}",
        f"Yelp:     {rev.get('yelp', {}).get('count') or '?'} reviews"
        f" {'(page found)' if rev.get('yelp', {}).get('url') else '(not found)'}",
    ]
    print_section("REVIEWS SNAPSHOT:", rev_lines)

    # Reviews grade is relative to the top competitor when we have one.
    top_comp_reviews = (results.get("top_competitor") or {}).get("review_count") or 0
    reviews_grade = grade_reviews(target_count, top_comp_reviews)

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
    print(f"OVERALL GRADE: {overall}    (scan time: {elapsed}s)")
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
