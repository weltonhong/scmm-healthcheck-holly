"""
Google SERP Rank Checker

Returns the prospect's organic rank for one or more queries from REAL Google
search results, with location targeting via UULE.

Two backends, in priority order:
  1. ScrapingBee (custom_google=true, premium_proxy, UULE) - fast, no CAPTCHA,
     ~25 credits per query. Same approach as pre-call-audit/serp_screenshot.py.
     Requires SCRAPINGBEE_API_KEY env var.
  2. Playwright fallback - free but can hit Google CAPTCHAs.

Usage:
    python google_serp_rank.py \
        --business "Comfort Keepers" \
        --domain "comfortkeepers.com" \
        --city "Tampa FL" \
        --queries "home care Tampa FL|home care near Tampa"

Output: JSON to stdout
    {
      "city": "Tampa FL",
      "backend": "scrapingbee" | "playwright",
      "queries": [
        {"query": "home care Tampa FL", "rank": 4, "results": [...]},
        {"query": "home care near Tampa", "rank": null, "results": [...]}
      ],
      "error": null
    }
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import requests


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Ensure the sibling name_matcher.py can be imported when this script
# runs as a subprocess.
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
SHARED_COOKIE_FILE = os.path.join(
    SCRIPT_DIR, "..", "..", "pre-call-audit", "scripts", ".google_cookies.json"
)
COOKIE_FILE = os.path.normpath(SHARED_COOKIE_FILE)


# ----------------------------- UULE -----------------------------

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


def canonicalize_city(city):
    """Convert 'Tampa FL' or 'Tampa, FL' to 'Tampa,Florida,United States'."""
    s = city.replace(",", " ").strip()
    parts = s.rsplit(None, 1)
    if len(parts) == 2:
        city_name, state_code = parts
        state_full = US_STATE_ABBREVS.get(state_code.upper())
        if state_full:
            return f"{city_name},{state_full},United States"
    return city


def generate_uule(city):
    canonical = canonicalize_city(city)
    secret = b"\x08\x02\x10\x02\x22"
    city_bytes = canonical.encode("utf-8")
    length_byte = bytes([len(city_bytes)])
    payload = secret + length_byte + city_bytes
    return f"w+{base64.b64encode(payload).decode('utf-8')}"


def get_scrapingbee_key():
    key = os.environ.get("SCRAPINGBEE_API_KEY", "")
    if key:
        return key
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "[System.Environment]::GetEnvironmentVariable('SCRAPINGBEE_API_KEY', 'User')"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""


# ----------------------------- name matching -----------------------------

# Delegate to the shared deathcare/senior-care normalized matcher so
# variants like "Visiting Angels" vs "Visiting Angels of Tampa Bay"
# resolve correctly in both the local-pack matcher and the Google Ads
# matcher.
import name_matcher  # noqa: E402  (sibling module on sys.path)


STOPWORDS = {"&", "and", "the", "of", "inc", "llc", "co", "corp", "company"}


def name_matches(text, business_name):
    """SERP entry / ad name matcher. Symmetric — accepts either order."""
    return name_matcher.name_matches(text, business_name)


# ----------------------------- ScrapingBee path -----------------------------


# A real render_js Google SERP is hundreds of KB. ScrapingBee returns HTTP 200
# with an empty or URL-echo stub body during an outage, so status alone cannot
# detect a failed fetch.
#
# Why this guard exists: on the 2026-07-24 tag-2615 batch, 219 of 500 fetches
# (44%) came back as stubs. The parsers extracted nothing and the result
# rendered as "Not found" / "not in the 3-Pack" -- indistinguishable from a
# genuine ranking absence, and read aloud to a prospect standing at the booth.
# A failed fetch must RAISE so the caller records an explicit error.
#
# Keep in sync with quick-intel-ranking/scripts/serp_helpers.py, which owns the
# original of this guard. These skills are deliberately self-contained (each
# deploys to its own clean-slice Streamlit repo), so the copy is intentional --
# test_serp_guard_parity.py asserts the copies agree.
MIN_SERP_BYTES = 100_000


def _validate_serp_body(html):
    """Return an error string if this body is not a usable SERP, else None."""
    if not html or not html.strip():
        return "empty body (0 bytes)"
    if len(html) < MIN_SERP_BYTES:
        return f"stub body ({len(html)} bytes < {MIN_SERP_BYTES})"
    return None


def fetch_serp_scrapingbee(query, city, api_key, timeout=120):
    """Fetch a Google SERP via ScrapingBee custom_google. Returns markdown body.

    Raises RuntimeError if the response is not a usable SERP, so the caller
    records an explicit error rather than treating an empty page as "no
    rankings found".
    """
    uule = generate_uule(city)
    is_near_me = "near me" in query.lower()
    search_url = (
        f"https://www.google.com/search?"
        f"q={urllib.parse.quote_plus(query)}&gl=us&hl=en&pws=0&nfpr=1&uule={uule}"
    )
    if is_near_me:
        search_url += f"&near={urllib.parse.quote_plus(city)}"

    params = {
        "api_key": api_key,
        "url": search_url,
        "custom_google": "true",
        "premium_proxy": "true",
        "country_code": "us",
        "return_page_source": "false",
        "render_js": "true",
        "wait": "2500",
    }

    r = requests.get(
        "https://app.scrapingbee.com/api/v1/",
        params=params,
        timeout=timeout,
    )
    if r.status_code != 200:
        raise RuntimeError(f"ScrapingBee HTTP {r.status_code}: {r.text[:200]}")
    bad = _validate_serp_body(r.text)
    if bad is not None:
        raise RuntimeError(f"ScrapingBee returned an unusable SERP: {bad}")
    return r.text


# Patterns to skip (knowledge panel, PAA, related searches, etc.)
SKIP_TITLE_PATTERNS = (
    "people also ask", "people also search", "related searches",
    "more businesses", "businesses", "places", "see results about",
    "more results", "discussions and forums", "see more",
)


def _humanize_domain(domain):
    """Convert 'home-instead.com' -> 'Home Instead'. Imperfect for compound
    words but always cleaner than an ad headline."""
    if not domain:
        return ""
    domain = re.sub(r"^https?://", "", domain).strip()
    domain = re.sub(r"^www\.", "", domain)
    host = domain.split("/")[0].split(" ")[0]
    parts = host.split(".")
    sld = parts[-2] if len(parts) >= 2 else parts[0]
    pieces = [p for p in re.split(r"[-_]", sld) if p]
    return " ".join(p.capitalize() for p in pieces)


def parse_ads_from_html(html):
    """
    Extract Google Ads (sponsored results) from a SERP HTML page.

    The advertiser's actual *business name* in modern Google Ads is NOT in the
    headline (which is sales copy like "In Home Health | Browse Rates and
    Availability"). It's in a separate sitename span -- typically class
    VuuXrf or qzEoUe -- or in the <cite> element showing the display URL.

    Resolution order per ad:
      1. Sitename span (VuuXrf / qzEoUe) - cleanest
      2. <cite> domain humanized - reliable fallback
      3. Heading text (first segment before |) - last resort

    Returns a list of {"name": advertiser display name} dicts, deduped.
    """
    advertisers = []

    tads_start = re.search(r'<div[^>]+id="tads"', html, flags=re.IGNORECASE)
    if not tads_start:
        tads_start = re.search(
            r'<div[^>]+id="bottomads"', html, flags=re.IGNORECASE
        )
        if not tads_start:
            return advertisers

    rso_match = re.search(
        r'<div[^>]+id="rso"', html[tads_start.start():], flags=re.IGNORECASE
    )
    if rso_match:
        end = tads_start.start() + rso_match.start()
    else:
        # No rso fallback: cap at 30KB so we don't bleed into AI Overview
        # or other unrelated SERP sections on small/rural-market pages.
        end = tads_start.start() + 30000
    block = html[tads_start.start():end]

    heading_pattern = re.compile(
        r'<div[^>]+role="heading"[^>]*>(.*?)</div>',
        re.IGNORECASE | re.DOTALL,
    )
    sitename_pattern = re.compile(
        r'<(?:span|div)[^>]+class="[^"]*\b(?:VuuXrf|qzEoUe|tjvcx)\b[^"]*"[^>]*>([^<]+)</(?:span|div)>',
        re.IGNORECASE,
    )
    cite_pattern = re.compile(
        r'<cite[^>]*>(.*?)</cite>', re.IGNORECASE | re.DOTALL
    )

    SKIP_LABELS = {
        # Google UI elements that sometimes get parsed as ad headings
        "ai overview", "share", "more", "see more", "see results",
        "more results", "results", "feedback", "translate", "tools",
        "search", "all", "news", "videos", "images", "shopping",
        "maps", "books", "flights", "finance",
        "people also ask", "people also search for", "related searches",
        "discussions and forums", "see more on",
        # Section headers
        "places", "businesses", "more businesses", "all businesses",
        # Ad-related labels (not advertisers)
        "sponsored", "ad", "ads", "ad center", "my ad center",
    }

    # Action verbs that indicate the text is an ad headline / ad copy
    # ("Find In Home Caregivers Near You") not an advertiser business name.
    ACTION_VERB_PREFIXES = {
        "find", "get", "discover", "search", "browse", "compare", "shop",
        "buy", "view", "see", "explore", "try", "looking", "want", "need",
        "looking", "hire", "book", "schedule", "request", "call", "click",
        "visit", "join", "save", "start",
    }

    # Vertical / generic vocabulary -- if a parsed name contains ONLY these
    # words and no proper noun, it's an ad headline, not a business.
    GENERIC_VERTICAL_WORDS = {
        "in", "home", "homes", "care", "cares", "service", "services",
        "senior", "seniors", "elder", "elderly", "adult", "family",
        "providers", "provider", "caregiver", "caregivers", "agency",
        "agencies", "company", "companies", "the", "and", "for", "of",
        "with", "your", "you", "to", "best", "top", "trusted", "quality",
        "professional", "expert", "private", "duty", "personal",
        "assistant", "assistance", "help", "support", "near", "me",
        "us", "about", "from", "by", "on", "at", "all", "any",
        "health", "healthcare", "nursing", "medical", "respite", "live",
        # Marketing / ad copy words
        "rates", "rate", "options", "option", "pricing", "prices", "price",
        "costs", "cost", "plans", "plan", "packages", "package", "free",
        "affordable", "cheap", "discount", "discounts", "deal", "deals",
        "quote", "quotes", "estimate", "estimates", "today", "now",
        "available", "availability", "information", "info", "details",
        "compare", "comparison", "reviews", "ratings", "offers", "offer",
        "solutions", "solution",
        # Generic adjectives commonly used in ad headlines
        "local", "nearby", "area", "nationwide", "national", "licensed",
        "insured", "certified", "bonded", "experienced", "reliable",
        "safe", "caring", "dedicated", "compassionate", "hourly",
        "overnight", "daily", "weekly", "monthly", "247", "24",
    }

    def is_generic_ad_text(text):
        if not text:
            return True
        nl = text.lower().strip()
        first_word = nl.split()[0] if nl else ""
        if first_word in ACTION_VERB_PREFIXES:
            return True
        words = re.findall(r"[a-z]+", nl)
        if not words:
            return True
        non_generic = [
            w for w in words
            if w not in GENERIC_VERTICAL_WORDS and len(w) >= 3
        ]
        return len(non_generic) == 0

    def decode(s):
        return (
            (s or "")
            .replace("&amp;", "&")
            .replace("&#39;", "'")
            .replace("&quot;", '"')
            .replace("&#x27;", "'")
        )

    def clean(s):
        s = re.sub(r"<[^>]+>", " ", s or "")
        return re.sub(r"\s+", " ", decode(s)).strip()

    seen = set()
    headings = list(heading_pattern.finditer(block))

    for hm in headings:
        # Window: 3000 chars before heading (sitename usually appears above)
        # to 200 chars after (covers same-line markup variants)
        win_start = max(0, hm.start() - 3000)
        win_end = min(len(block), hm.end() + 200)
        ad_window = block[win_start:win_end]
        heading_rel = hm.start() - win_start

        name = ""
        display_domain = ""

        # Always grab the closest cite element for domain matching, even
        # when we end up using a sitename for the display name.
        cite_matches = list(cite_pattern.finditer(ad_window))
        if cite_matches:
            best_cite = None
            for m in cite_matches:
                if m.end() <= heading_rel + 80:
                    best_cite = m
            if best_cite is None:
                best_cite = cite_matches[0]
            cite_text = clean(best_cite.group(1))
            # cite text often looks like "homeinstead.com › services"
            d = re.split(r"[\s\u203a/]", cite_text, maxsplit=1)[0]
            d = d.lower()
            if d.startswith("www."):
                d = d[4:]
            if "." in d and len(d) < 80:
                display_domain = d

        # 1) Sitename span -- pick the closest one before the heading
        sn_matches = list(sitename_pattern.finditer(ad_window))
        if sn_matches:
            best = None
            for m in sn_matches:
                if m.end() <= heading_rel + 80:
                    best = m
            if best is None:
                best = sn_matches[0]
            cand = clean(best.group(1))
            # Skip if it's just a URL/domain or marketing fragment
            if cand and not cand.startswith(("http", "www.")) and 2 < len(cand) < 80:
                name = cand

        # 2) Cite element domain humanized as the name
        if not name and display_domain:
            name = _humanize_domain(display_domain)

        # 3) Last resort: take the heading and trim sales copy
        if not name:
            heading_html = hm.group(1)
            inner = re.search(
                r'<span[^>]+class="[^"]*OSrXXb[^"]*"[^>]*>([^<]+)</span>',
                heading_html, re.IGNORECASE,
            )
            raw = inner.group(1) if inner else heading_html
            cand = clean(raw)
            # Take first segment before " | " or " - "
            cand = re.split(r"\s+\|\s+|\s+-\s+", cand, maxsplit=1)[0].strip()
            name = cand

        if not name or len(name) > 100:
            continue
        if name.lower() in SKIP_LABELS:
            continue
        if name.startswith('"') or name.endswith("."):
            continue
        if is_generic_ad_text(name):
            # Filters "Find In Home Senior Caregivers", "In Home Care Services",
            # "In-Home Elderly Care Providers", etc. -- ad copy, not business names.
            continue
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        # An advertiser with NO display domain is not an ad.
        #
        # Measured 2026-08-18 on two independently sourced SERPs of the same
        # query (DataForSEO and ScrapingBee), both containing ZERO occurrences
        # of "Sponsored" and zero paid results: this function returned the
        # three LOCAL PACK businesses as advertisers, each with domain="".
        # Downstream that becomes "competitors_running_ads", so a booth PDF
        # named three real competitors as advertisers when nobody was
        # advertising. A fabricated, named finding shown to a prospect.
        #
        # Every genuine Google ad renders a display URL, so requiring one
        # removes the phantoms. It can only ever UNDER-report (an ad whose
        # cite extraction fails is dropped), which is the correct direction:
        # skipping beats guessing on a sales-facing claim.
        if not display_domain:
            continue
        advertisers.append({"name": name, "domain": display_domain})

    return advertisers


def parse_local_pack_from_html(html, business_name):
    """
    Extract Google 3-Pack (Local Map Pack) listings from a SERP HTML page.

    Mirrors the selectors used in pre-call-audit/serp_screenshot.py:
      - Local pack container: div.ixix9e (with text-header fallback)
      - Business cards: div.VkpGBb (preferred) or div.cXedhc (fallback)
      - Card heading: div[role="heading"] or span.OSrXXb

    Returns:
        {"rank": 1-based position or None, "in_3_pack": bool, "top_3": [names]}
    """
    # Find all VkpGBb cards anywhere in the HTML. They only appear inside the
    # local pack container, so we don't need to scope to a parent first.
    card_pattern = re.compile(
        r'<div[^>]*class="[^"]*\bVkpGBb\b[^"]*"[^>]*>',
        re.IGNORECASE,
    )
    starts = [m.start() for m in card_pattern.finditer(html)]
    if not starts:
        # Fallback to cXedhc if VkpGBb is missing
        card_pattern = re.compile(
            r'<div[^>]*class="[^"]*\bcXedhc\b[^"]*"[^>]*>',
            re.IGNORECASE,
        )
        starts = [m.start() for m in card_pattern.finditer(html)]
        if not starts:
            return {"rank": None, "in_3_pack": False, "top_3": []}

    # Slice each card from its own start to the next card start (or +5KB cap
    # for the last one). This gives a workable HTML chunk per card.
    boundaries = starts + [len(html)]
    cards = []
    for i in range(len(starts)):
        end = min(boundaries[i + 1], starts[i] + 8000)
        block = html[starts[i]:end]

        # Skip sponsored cards inside the local pack
        if re.search(r"sponsored", block[:2000], re.IGNORECASE):
            # Only skip if the word appears prominently (not just any mention)
            if re.search(r">\s*sponsored\s*<", block[:2000], re.IGNORECASE):
                continue

        # Extract the business name from div[role="heading"] OR span.OSrXXb
        name = ""
        heading_match = re.search(
            r'<div[^>]+role="heading"[^>]*>(.*?)</div>',
            block, re.IGNORECASE | re.DOTALL,
        )
        if heading_match:
            raw = re.sub(r"<[^>]+>", " ", heading_match.group(1))
            name = re.sub(r"\s+", " ", raw).strip()
        if not name:
            span_match = re.search(
                r'<span[^>]+class="[^"]*\bOSrXXb\b[^"]*"[^>]*>([^<]+)</span>',
                block, re.IGNORECASE,
            )
            if span_match:
                name = re.sub(r"\s+", " ", span_match.group(1)).strip()

        if not name:
            continue
        # Decode common entities
        name = (
            name.replace("&amp;", "&")
                .replace("&#39;", "'")
                .replace("&quot;", '"')
                .replace("&#x27;", "'")
        )
        if len(name) > 120:
            continue
        cards.append(name)

    # Local pack is at most 3 cards
    cards = cards[:3]

    rank = None
    for i, name in enumerate(cards, 1):
        if name_matches(name, business_name):
            rank = i
            break

    return {
        "rank": rank,
        "in_3_pack": rank is not None,
        "top_3": cards,
    }


def parse_organic_rank_from_html(html, business_name, domain):
    """
    Parse Google SERP HTML for organic results and find the first match for
    business_name or domain. Returns (rank, results_list).

    Strategy: regex-extract <h3> headings (organic title text) and the
    surrounding link block. Skip 3-Pack / knowledge panel / PAA blocks.
    """
    domain = (domain or "").lower().strip()
    results = []

    # Strip script/style for cleaner text
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)

    # Each organic result has an <h3> with title and a parent <a> with href
    # Pattern: <a href="..."><br/.../h3>Title</h3>...
    pattern = re.compile(
        r'<a[^>]+href="(https?://[^"]+)"[^>]*>.*?<h3[^>]*>(.*?)</h3>',
        re.IGNORECASE | re.DOTALL,
    )

    seen_urls = set()
    rank = None
    position = 0

    for m in pattern.finditer(text):
        url = m.group(1)
        title_html = m.group(2)
        title = re.sub(r"<[^>]+>", " ", title_html)
        title = re.sub(r"\s+", " ", title).strip()

        # Filter: skip Google's own internal links
        if "google.com" in url and "/url?" not in url:
            continue
        # Skip duplicates
        if url in seen_urls:
            continue
        # Skip non-organic patterns
        lower = title.lower()
        if any(p in lower for p in SKIP_TITLE_PATTERNS):
            continue
        if not title:
            continue
        seen_urls.add(url)

        position += 1
        host = ""
        try:
            host = urllib.parse.urlparse(url).netloc.lower().replace("www.", "")
        except Exception:
            pass

        results.append({
            "position": position,
            "title": title,
            "url": url,
            "domain": host,
        })

        all_text = f"{title} {url}".lower()
        matched = False
        if domain and domain in host:
            matched = True
        elif name_matches(all_text, business_name):
            matched = True

        if matched and rank is None:
            rank = position

        if position >= 10:
            break

    return rank, results


# --------------------------- Google API path -------------------------------
#
# ScrapingBee's `custom_google` on /api/v1/ broke 2026-08-17: HTTP 500s, and
# billed 5.5KB URL-echo stubs returned as HTTP 200. The parameter is no longer
# documented anywhere. The documented replacement is /api/v1/google, which
# returns STRUCTURED JSON rather than SERP HTML, so the parse_*_from_html
# functions cannot read it.
#
# These adapters produce the SAME shapes those parsers produced, so everything
# downstream (health_check, pdf_generator) is untouched:
#   organic -> (rank, [{position,title,url,domain}])
#   local   -> {rank, in_3_pack, top_3}
#   ads     -> [{name, domain}]
#
# Geo targeting is by latitude/longitude. The endpoint REJECTS uule outright
# (allowed extra_params keys are filter, fpstate, locale, nfpr, safe,
# safe_search, tbm, tbs, udm). Verified 2026-08-18: Tampa and Portland returned
# entirely disjoint local packs on the same neutral query.
GOOGLE_API_URL = "https://app.scrapingbee.com/api/v1/google"


def fetch_serp_google_api(query, city, api_key, timeout=120):
    """Fetch one SERP as structured JSON. Returns the parsed dict.

    Raises RuntimeError rather than returning a partial result, so the caller
    records an explicit error. Two failure modes are fatal on purpose:

      1. Geocoding failed. Without coordinates the endpoint falls back to
         country-level results, which would then be attributed to a city we
         never targeted: an unmeasured city rendered as a measurement.
      2. No organic_results key at all. Structural failure, the JSON analogue
         of the URL-echo stub.
    """
    coords = geocode_city_osm(city)
    if not coords:
        raise RuntimeError(
            "geocode failed for %r; refusing to run an untargeted search "
            "and report it as a city result" % (city,))
    params = {
        "api_key": api_key,
        "search": query,
        "country_code": "us",
        "latitude": coords[0],
        "longitude": coords[1],
    }
    r = requests.get(GOOGLE_API_URL, params=params, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(
            "ScrapingBee google API HTTP %s: %s" % (r.status_code, r.text[:200]))
    try:
        d = r.json()
    except Exception as e:
        raise RuntimeError("ScrapingBee google API returned non-JSON: %s" % e)
    if not isinstance(d, dict) or "organic_results" not in d:
        raise RuntimeError("ScrapingBee google API response carries no "
                           "organic_results key (structural failure)")
    return d


def _host(v):
    return (v or "").lower().replace("www.", "").strip()


def organic_from_api(d, business_name, domain):
    """Mirror of parse_organic_rank_from_html, against JSON."""
    rank = None
    results = []
    for r in (d.get("organic_results") or []):
        pos = r.get("position")
        if pos is not None and pos > 10:
            continue
        title = r.get("title") or ""
        url = r.get("url") or ""
        host = _host(r.get("domain"))
        results.append({"position": pos, "title": title,
                        "url": url, "domain": host})
        all_text = ("%s %s" % (title, url)).lower()
        matched = False
        if domain and domain in host:
            matched = True
        elif name_matches(all_text, business_name):
            matched = True
        if matched and rank is None:
            rank = pos
    return rank, results


def local_pack_from_api(d, business_name):
    """Mirror of parse_local_pack_from_html, against JSON. Top 3 only."""
    cards = [(x.get("title") or "").strip()
             for x in (d.get("local_results") or [])]
    cards = [c for c in cards if c][:3]
    rank = None
    for i, name in enumerate(cards, 1):
        if name_matches(name, business_name):
            rank = i
            break
    return {"rank": rank, "in_3_pack": rank is not None, "top_3": cards}


def confirm_empty_pack(query, city, api_key, doc, business_name):
    """Second opinion on an empty local pack. Returns (local_pack, note).

    An empty pack from one backend is not evidence that Google serves no map
    pack for that search. Measured 2026-08-20, both backends on 27 real
    vertical/market queries: they agreed a pack was PRESENT 24 times and never
    once agreed it was absent, while disagreeing 3 times. So an unconfirmed
    empty is far more likely to be a measurement problem than a fact about the
    prospect's market, and it must not print as one.

    THE BAR for saying "Google shows no map pack for this search":

        meta_data.location populated    the endpoint states WHERE it searched.
                                        Null on the one measured JSON drop,
                                        populated on all 26 other rows.
        AND a second path agrees empty  an independent backend sees none too.

    Anything less is UNCONFIRMED and says so.

    RECONCILING TWO RULINGS. The endpoint ruling was to re-check only when the
    pack is empty AND location is null. Taken with the bar above, that would
    make "confirmed" unreachable, because confirmation needs a second path
    exactly when location IS populated. So the re-check runs on any empty
    pack. That is not the blanket dual-fetch the ruling was avoiding: empty
    packs were 1 of 27 rows measured, so it costs about one extra fetch per
    twenty-five, and only on rows that would otherwise print a claim we cannot
    support.
    """
    lp = local_pack_from_api(doc, business_name)
    if lp.get("top_3"):
        return lp, "populated"
    location = (doc.get("meta_data") or {}).get("location")
    try:
        html = fetch_serp_scrapingbee(query, city, api_key)
    except Exception as e:
        lp["confirmed_empty"] = False
        lp["pack_note"] = "second path unavailable: %s" % str(e)[:80]
        return lp, lp["pack_note"]
    second = parse_local_pack_from_html(html, business_name)
    if second.get("top_3"):
        # The pack exists and the first backend missed it. Recover it rather
        # than report an absence that is not there.
        second["confirmed_empty"] = False
        second["pack_note"] = "recovered from the second path"
        return second, second["pack_note"]
    lp["confirmed_empty"] = bool(location)
    lp["pack_note"] = ("both paths agree, location %r" % location if location
                       else "both paths empty but the endpoint did not "
                            "confirm where it searched")
    return lp, lp["pack_note"]


def ads_from_api(d):
    """Mirror of parse_ads_from_html, against JSON. Top and bottom ad blocks."""
    out = []
    seen = set()
    for block in ("top_ads", "bottom_ads"):
        for a in (d.get(block) or []):
            name = (a.get("title") or "").strip()
            dom = _host(a.get("domain") or a.get("visual_url"))
            key = (name.lower(), dom)
            if (name or dom) and key not in seen:
                seen.add(key)
                out.append({"name": name, "domain": dom})
    return out


def run_google_api(business, domain, city, queries, api_key):
    out = {
        "business": business,
        "domain": domain,
        "city": city,
        "backend": "google_api",
        "queries": [],
        "error": None,
    }
    for q in queries:
        try:
            d = fetch_serp_google_api(q, city, api_key)
            rank, results = organic_from_api(d, business, domain)
            out["queries"].append({
                "query": q,
                "rank": rank,
                "results": results,
                "ads": ads_from_api(d),
                # An empty pack gets a second opinion before anything is
                # said about it. See confirm_empty_pack.
                "local_pack": confirm_empty_pack(
                    q, city, api_key, d, business)[0],
                # Google's own view of where it searched from. Recorded so a
                # mis-targeted run is auditable after the fact.
                "resolved_location": (d.get("meta_data") or {}).get("location"),
            })
        except Exception as e:
            out["queries"].append({
                "query": q,
                "rank": None,
                "results": [],
                "ads": [],
                "local_pack": {"rank": None, "in_3_pack": False, "top_3": []},
                "error": str(e)[:200],
            })
    return out



def run_scrapingbee(business, domain, city, queries, api_key):
    out = {
        "business": business,
        "domain": domain,
        "city": city,
        "backend": "scrapingbee",
        "queries": [],
        "error": None,
    }
    for q in queries:
        try:
            html = fetch_serp_scrapingbee(q, city, api_key)
            rank, results = parse_organic_rank_from_html(html, business, domain)
            ads = parse_ads_from_html(html)
            local_pack = parse_local_pack_from_html(html, business)
            out["queries"].append({
                "query": q,
                "rank": rank,
                "results": results,
                "ads": ads,
                "local_pack": local_pack,
            })
        except Exception as e:
            out["queries"].append({
                "query": q,
                "rank": None,
                "results": [],
                "ads": [],
                "local_pack": {"rank": None, "in_3_pack": False, "top_3": []},
                "error": str(e)[:200],
            })
    return out


# ----------------------------- Playwright fallback -----------------------------


PLAYWRIGHT_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = { runtime: {} };
"""

CONSENT_SELECTORS = [
    "button#L2AGLb", "button[id='W0wltc']",
    "[aria-label='Accept all']", "[aria-label='Reject all']",
]


def geocode_city_osm(city):
    canonical = city.replace(",", " ")
    encoded = urllib.parse.quote(canonical)
    url = (
        f"https://nominatim.openstreetmap.org/search?"
        f"q={encoded}&format=json&limit=1&countrycodes=us"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "HealthCheckSERP/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None


def run_playwright(business, domain, city, queries):
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

    out = {
        "business": business,
        "domain": domain,
        "city": city,
        "backend": "playwright",
        "queries": [],
        "error": None,
    }

    coords = geocode_city_osm(city)
    uule = generate_uule(city)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                channel="chrome",
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions",
                ],
            )
        except Exception as e:
            out["error"] = f"chrome launch failed: {e}"
            return out

        ctx_opts = {
            "viewport": {"width": 1280, "height": 900},
            "locale": "en-US",
            "timezone_id": "America/New_York",
        }
        if coords:
            ctx_opts["geolocation"] = {"latitude": coords[0], "longitude": coords[1]}
            ctx_opts["permissions"] = ["geolocation"]
        if os.path.exists(COOKIE_FILE):
            ctx_opts["storage_state"] = COOKIE_FILE

        context = browser.new_context(**ctx_opts)
        page = context.new_page()
        page.add_init_script(PLAYWRIGHT_STEALTH_JS)

        try:
            page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=10000)
            for sel in CONSENT_SELECTORS:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(400)
                        break
                except Exception:
                    continue
        except Exception:
            pass

        for q in queries:
            is_near_me = "near me" in q.lower()
            search_url = (
                f"https://www.google.com/search?"
                f"q={urllib.parse.quote_plus(q)}&gl=us&hl=en&pws=0&nfpr=1&uule={uule}"
            )
            if is_near_me:
                search_url += f"&near={urllib.parse.quote_plus(city)}"

            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            except PlaywrightTimeout:
                pass
            try:
                page.wait_for_selector("div#search, div#rso", timeout=10000)
            except PlaywrightTimeout:
                pass
            page.wait_for_timeout(800)

            content = page.content()
            if any(s in content.lower() for s in
                   ("unusual traffic", "not a robot", "recaptcha")):
                out["queries"].append({"query": q, "error": "google_captcha", "rank": None})
                continue

            html = content
            rank, results = parse_organic_rank_from_html(html, business, domain)
            ads = parse_ads_from_html(html)
            local_pack = parse_local_pack_from_html(html, business)
            out["queries"].append({
                "query": q, "rank": rank, "results": results, "ads": ads,
                "local_pack": local_pack,
            })

        try:
            context.storage_state(path=COOKIE_FILE)
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass

    return out


# ----------------------------- entrypoint -----------------------------


def run(business, domain, city, queries):
    api_key = get_scrapingbee_key()
    if api_key:
        # /api/v1/google is the DOCUMENTED endpoint and the one that works.
        # custom_google (run_scrapingbee) broke 2026-08-17 and is no longer in
        # ScrapingBee's docs. It stays as a fallback only until support
        # confirms its status, then it should be deleted.
        try:
            return run_google_api(business, domain, city, queries, api_key)
        except Exception as e:
            print("Google API path failed: %s" % e, file=sys.stderr)
        try:
            return run_scrapingbee(business, domain, city, queries, api_key)
        except Exception as e:
            print("Legacy custom_google failed: %s" % e, file=sys.stderr)
    return run_playwright(business, domain, city, queries)


def main():
    parser = argparse.ArgumentParser(description="Google SERP rank checker")
    parser.add_argument("--business", required=True)
    parser.add_argument("--domain", default="")
    parser.add_argument("--city", required=True, help="e.g. 'Tampa FL'")
    parser.add_argument("--queries", required=True,
                        help="Pipe-separated list of queries")
    args = parser.parse_args()

    queries = [q.strip() for q in args.queries.split("|") if q.strip()]
    result = run(args.business, args.domain, args.city, queries)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
