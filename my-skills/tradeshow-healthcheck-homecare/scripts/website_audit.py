"""
Website Audit - Trade Show Health Check (Hard Mode)

Fetches a homepage and runs 7 hard checks designed to surface real issues
the prospect doesn't know about. These are intentionally strict so most
sites do not score an A.

Checks:
  1. Real team photos (no stock photo CDNs / generic alt text)
  2. PageSpeed mobile score >= 50 (Google PageSpeed Insights API)
  3. About/Team page exists with real staff signals (not just generic /about)
  4. Blog with a post from the last 6 months
  5. Intake form or scheduling widget (not just a phone number)
  6. LocalBusiness schema markup (or a relevant subtype)
  7. Google reviews widget embedded on the site

Grade: A (7/7), B (5-6), C (3-4), D (1-2), F (0)

Usage:
    python website_audit.py --url https://example.com
"""

import argparse
import datetime
import json
import os
import re
import threading
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ----------------------------- helpers -----------------------------


def get_google_api_key():
    key = os.environ.get("GOOGLE_API_KEY", "")
    if key:
        return key
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "[System.Environment]::GetEnvironmentVariable('GOOGLE_API_KEY', 'User')"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""



# ---- "Couldn't check", never "No" from a page nobody read (Welton, 2026-10-20) ----------------------
# A check used to answer No whenever a page it needed could not be read (blocked, rate-limited, server
# error, no connection), and when a site refused the address probes. Now every fetch and probe made
# while a check runs notes the pages it could not read, and measured() turns that check's No into None
# ("Couldn't check"). A Yes stands (it was seen); a page that is not there (404/410) is still a No.

# ---- A homepage that loads with almost nothing readable is built in the browser (Welton, 2026-10-20) ----
# Measured on 200 sites from the saved runs (ops/receipts/20261020T171217_script-built-homepages-measured.txt):
# 19 of 81 funeral home homepages came back with 18 to 65 readable characters (one platform: Tribute /
# FrontRunner / FuneralTech) and 1,000 to 8,000 once a browser ran their scripts; the thinnest real page
# had 415. The booth printed 2 to 4 "No"s on each, 13 of them provably false ("Pre-need form: No" beside
# a pre-planning link). Under MIN_READABLE_CHARS the website reads "Couldn't check", no grade.
MIN_READABLE_CHARS = 200
SCRIPT_BUILT_REASON = "Couldn't check (site loads its content in the browser)"


def readable_chars(html):
    t = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1>", " ", html or "")
    t = re.sub(r"(?s)<!--.*?-->", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&[a-z#0-9]+;", " ", t)
    return len(" ".join(t.split()))

_reads = threading.local()


def _note_unread(url, why):
    unread = getattr(_reads, "unread", None)
    if unread is not None:
        unread.append((url, why))


def measured(check, *args):
    """Run one check. Its No becomes None when a page it needed could not be read."""
    _reads.unread = []
    try:
        result = check(*args)
    finally:
        unread, _reads.unread = _reads.unread, None
    if not unread:
        return result
    if result is False or result is None:
        return None
    if isinstance(result, dict) and not result.get("pass"):
        return dict(result, **{"pass": None})
    if isinstance(result, tuple) and result and not result[0]:
        return (None,) + tuple(result[1:])
    return result


def fetch_page(url, timeout=15):
    if not url:
        return None, None, "no url"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code in (401, 403, 407, 429) or r.status_code >= 500:
            _note_unread(url, "HTTP %s" % r.status_code)
        return r.text, r.status_code, r.url
    except Exception as e:
        _note_unread(url, str(e)[:80])
        return None, None, str(e)


def base_origin(url):
    """Return scheme://host of a URL."""
    try:
        p = urllib.parse.urlparse(url)
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return ""


def find_internal_link(html, base_url, url_keywords):
    """Find first <a href> whose path contains any of the keywords.

    Returns absolute URL or None.
    """
    if not html or not base_url:
        return None
    # href="...", href='...' or href=... are all links (Welton 2026-10-21: a site whose links use single
    # quotes read "No" for a team page, blog, pre-need form, obituary page, gallery or livestream it has).
    pattern = re.compile(r"""<a[^>]+href\s*=\s*["']?([^"'\s>]+)""", re.IGNORECASE)
    for m in pattern.finditer(html):
        href = m.group(1).strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        href_low = href.lower()
        for kw in url_keywords:
            if kw in href_low:
                if href.startswith("http"):
                    return href
                if href.startswith("//"):
                    return "https:" + href
                if href.startswith("/"):
                    return base_url + href
                return urllib.parse.urljoin(base_url + "/", href)
    return None


# ----------------------------- 1. Real photos vs stock -----------------------------

STOCK_INDICATORS = [
    # Stock provider CDNs and URLs
    "shutterstock", "istockphoto", "gettyimages", "stock.adobe",
    "depositphotos", "dreamstime", "123rf.com", "alamy.com", "bigstock",
    "fotolia", "unsplash.com", "pexels.com", "pixabay.com",
    "stocksnap.io", "freepik.com", "canva.com/photos",
    # Common stock filename patterns
    "stock-photo", "stock_photo", "/stock/", "shutterstock_",
    "istock_", "gettyimages-",
]

GENERIC_ALT_PATTERNS = [
    r'alt="[^"]*happy senior',
    r'alt="[^"]*smiling elderly',
    r'alt="[^"]*caregiver and (?:patient|client|senior|elderly)',
    r'alt="[^"]*senior couple',
    r'alt="[^"]*elderly (?:woman|man|couple|person|lady|gentleman)',
    r'alt="[^"]*nurse (?:and|with) (?:patient|elderly|senior)',
    r'alt="[^"]*holding hands with (?:elderly|senior)',
]


def check_real_photos(html):
    """Return True if NO stock photo indicators found."""
    html_lower = html.lower()
    for hint in STOCK_INDICATORS:
        if hint in html_lower:
            return False
    generic_alt_hits = 0
    for pat in GENERIC_ALT_PATTERNS:
        if re.search(pat, html_lower):
            generic_alt_hits += 1
            if generic_alt_hits >= 2:
                return False
    return True


# ----------------------------- 2. PageSpeed Insights -----------------------------


PSI_RUNS = 5          # Google's speed test runs per scan, all at once
PSI_MIN_RUNS = 3      # fewer back than this is couldn't check


def check_pagespeed(url, api_key, timeout=90):
    """Google's mobile speed test, run PSI_RUNS times at once (Welton 2026-10-22).

    One run is not a measurement. Six fresh runs of one page within a minute scored 30 to 57 (Forest Lawn), 41 to 55
    (Veritas) and 40 to 62 (Haven); the sheets had printed one run each (26, 37, 52), and Veritas's "slow page" bullet
    fired on a page Google's own site scored 54. Each run gets its own address (a harmless rrm_psi tag): Google hands
    back its cached answer for an address it tested moments ago, so five runs of one address are one run.

    Returns the runs' low and high. score is the HIGH run and pass is high >= 50, so nothing calls a page slow unless
    every run said so: the owner can run the test himself, and one good run of his disproves a slow claim built on a
    bad run of ours. Fewer than PSI_MIN_RUNS runs back is couldn't check (score None), never a verdict.
    """
    if not api_key:
        sys.stderr.write("[pagespeed] no GOOGLE_API_KEY available\n")
        return {"score": None, "pass": None, "error": "no api key"}
    if not url:
        return {"score": None, "pass": None, "error": "no url"}

    def one(n):
        base, hash_, frag = url.partition("#")
        tagged = base + ("&" if "?" in base else "?") + "rrm_psi=%d" % n + hash_ + frag
        try:
            r = requests.get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed", timeout=timeout,
                             params={"url": tagged, "strategy": "mobile", "category": "performance", "key": api_key})
            if r.status_code != 200:
                return None, "HTTP %s: %s" % (r.status_code, r.text[:160])
            score = r.json().get("lighthouseResult", {}).get("categories", {}).get("performance", {}).get("score")
            return (None, "no score in response") if score is None else (round(score * 100), None)
        except Exception as e:
            return None, str(e)[:200]

    with ThreadPoolExecutor(max_workers=PSI_RUNS) as ex:
        runs = list(ex.map(one, range(1, PSI_RUNS + 1)))
    scores = sorted(s for s, _ in runs if s is not None)
    errors = [e for _, e in runs if e]
    for e in errors:
        sys.stderr.write("[pagespeed] a run failed for %s: %s\n" % (url, e))
    if len(scores) < PSI_MIN_RUNS:
        return {"score": None, "pass": None, "scores": scores,
                "error": "only %d of %d speed tests came back%s" % (len(scores), PSI_RUNS, (": " + errors[0]) if errors else "")}
    return {"score": scores[-1], "low": scores[0], "high": scores[-1], "scores": scores, "pass": scores[-1] >= 50}


# ----------------------------- 3. About/Team page -----------------------------

TEAM_URL_KEYWORDS = [
    "/team", "/our-team", "/our_team", "/staff", "/our-staff",
    "/meet-the-team", "/meet-our-team", "/leadership", "/our-people",
    "/who-we-are/team",
]
ABOUT_URL_KEYWORDS = ["/about", "/who-we-are", "/our-story"]
ROLE_KEYWORDS = [
    "founder", "co-founder", "owner", "co-owner", "director",
    "administrator", "ceo", "president", "vice president",
    "manager", "coordinator", "registered nurse", "rn,",
    "lpn", "caregiver", "care manager", "case manager",
]


def check_about_team(home_html, base_url):
    """Pass if a dedicated team page exists OR /about contains 3+ role hits."""
    # Try dedicated team URLs first - their existence alone is a pass
    team_url = find_internal_link(home_html, base_url, TEAM_URL_KEYWORDS)
    if team_url:
        page_html, status, _ = fetch_page(team_url, timeout=10)
        if page_html and status and 200 <= status < 300:
            text = re.sub(r"<[^>]+>", " ", page_html).lower()
            role_hits = sum(1 for kw in ROLE_KEYWORDS if kw in text)
            if role_hits >= 1:  # Even 1 role on a dedicated team page is enough
                return True

    # Fall back to /about with stricter role requirement
    about_url = find_internal_link(home_html, base_url, ABOUT_URL_KEYWORDS)
    if about_url:
        page_html, status, _ = fetch_page(about_url, timeout=10)
        if page_html and status and 200 <= status < 300:
            text = re.sub(r"<[^>]+>", " ", page_html).lower()
            role_hits = sum(1 for kw in ROLE_KEYWORDS if kw in text)
            if role_hits >= 3:
                return True
    return False


# ----------------------------- 4. Blog recency -----------------------------

BLOG_URL_KEYWORDS = ["/blog", "/news", "/articles", "/insights", "/resources"]

MONTH_NAMES = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?"
)
DATE_PATTERN_MONTH = re.compile(
    rf"({MONTH_NAMES})\s+(\d{{1,2}}),?\s+(20\d{{2}})",
    re.IGNORECASE,
)
DATE_PATTERN_ISO = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
DATE_PATTERN_META = re.compile(
    r'(?:datetime|datePublished|content)="(20\d{2}-\d{2}-\d{2})',
    re.IGNORECASE,
)

MONTH_TO_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_dates_from_html(html):
    """Extract all parseable dates from HTML, return list of date objects."""
    dates = []
    for m in DATE_PATTERN_META.finditer(html):
        try:
            dates.append(datetime.date.fromisoformat(m.group(1)))
        except Exception:
            pass
    for m in DATE_PATTERN_ISO.finditer(html):
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            dates.append(datetime.date(y, mo, d))
        except Exception:
            pass
    for m in DATE_PATTERN_MONTH.finditer(html):
        mname = m.group(1)[:3].lower()
        day = int(m.group(2))
        year = int(m.group(3))
        mo = MONTH_TO_NUM.get(mname)
        if mo:
            try:
                dates.append(datetime.date(year, mo, day))
            except Exception:
                pass
    return dates


def check_blog_recent(home_html, base_url):
    """Returns dict {pass, last_post}. Pass if blog page exists with a post
    from the last 6 months."""
    blog_url = find_internal_link(home_html, base_url, BLOG_URL_KEYWORDS)
    if not blog_url:
        return {"pass": False, "last_post": None, "blog_url": None}
    page_html, status, _ = fetch_page(blog_url, timeout=10)
    if not page_html or not status or status >= 400:
        return {"pass": False, "last_post": None, "blog_url": blog_url}
    dates = parse_dates_from_html(page_html)
    today = datetime.date.today()
    valid = [d for d in dates if d <= today and d.year >= 2015]
    if not valid:
        _note_unread(blog_url, "no dates readable on the page")
        return {"pass": False, "last_post": None, "blog_url": blog_url}
    most_recent = max(valid)
    cutoff = today - datetime.timedelta(days=183)  # ~6 months
    return {
        "pass": most_recent >= cutoff,
        "last_post": most_recent.isoformat(),
        "blog_url": blog_url,
    }


# ----------------------------- 5. Intake form / scheduling -----------------------------

SCHEDULING_HINTS = [
    "calendly.com", "acuityscheduling", "squareup.com/appointments",
    "jotform.com", "gravityforms", "wpforms", "wpcf7", "contact-form-7",
    "hubspot.com/forms", "hsforms.com", "typeform.com", "ninjaforms",
    "formstack", "fluentform", "wsform", "fluent-form", "gform_wrapper",
    "elfsight-app-form",
]


def check_intake_form(html):
    """Pass if a real intake form (3+ visible fields) or scheduling widget present."""
    html_lower = html.lower()
    for h in SCHEDULING_HINTS:
        if h in html_lower:
            return True
    forms = re.findall(r"<form\b[^>]*>(.*?)</form>", html, re.IGNORECASE | re.DOTALL)
    for form in forms:
        form_low = form.lower()
        # Skip search forms
        if 'role="search"' in form_low or 'type="search"' in form_low:
            continue
        if 'class="searchform' in form_low or 'id="searchform' in form_low:
            continue
        inputs = re.findall(
            r"<(input|textarea|select)\b[^>]*>", form, re.IGNORECASE
        )
        hidden = len(re.findall(
            r'<input[^>]+type=["\']hidden["\']', form, re.IGNORECASE
        ))
        submit = len(re.findall(
            r'<input[^>]+type=["\']submit["\']', form, re.IGNORECASE
        ))
        real_inputs = len(inputs) - hidden - submit
        if real_inputs >= 3:
            return True
    return False


# ----------------------------- 6. LocalBusiness schema -----------------------------

SCHEMA_TARGET_TYPES = [
    "LocalBusiness", "HomeAndConstructionBusiness", "MedicalBusiness",
    "MedicalOrganization", "MedicalClinic", "Physician", "HealthAndBeautyBusiness",
    "ProfessionalService", "EmergencyService", "HomeHealthAgency",
]


def check_local_business_schema(html):
    """Look for application/ld+json blocks containing LocalBusiness or subtype."""
    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    for m in pattern.finditer(html):
        block = m.group(1)
        for t in SCHEMA_TARGET_TYPES:
            if f'"{t}"' in block or f"'{t}'" in block:
                return True
    return False


# ----------------------------- 7. Google reviews widget -----------------------------

REVIEWS_WIDGET_HINTS = [
    "elfsight.com", "elfsight-app",
    "trustindex.io", "trustindex",
    "sociablekit",
    "reviewsonmywebsite.com",
    "embedreviews", "embedsocial",
    "tagembed.com", "widget-tagembed",
    "shapo.io",
    "famewall",
    "google-reviews-widget", "googlereviewswidget",
    "g-reviews-widget",
    "widget.reviewsforce",
    "rwgmaps",
    "trustpulse",
    "reputationmanager", "reviewbuilder",
]


def check_google_reviews_widget(html):
    html_lower = html.lower()
    for h in REVIEWS_WIDGET_HINTS:
        if h in html_lower:
            return True
    return False


# ----------------------------- grading -----------------------------


def grade_website(checks):
    """A=7/7, B=5-6, C=3-4, D=1-2, F=0. None values are excluded and the
    threshold is scaled proportionally."""
    real = [(k, v) for k, v in checks.items() if v is not None]
    if not real or len(real) * 2 < len(checks):
        return None   # too little measured to grade (most checks could not read their page)
    passed = sum(1 for _, v in real if v)
    total = len(real)
    # Scale to 7
    scaled = round(passed * 7 / total)
    if scaled >= 7:
        return "A"
    if scaled >= 5:
        return "B"
    if scaled >= 3:
        return "C"
    if scaled >= 1:
        return "D"
    return "F"


# ----------------------------- main entry -----------------------------


def audit(url):
    if not url:
        return {
            "url": "",
            "error": "no url provided",
            "checks": {},
            "grade": "F",
        }

    html, status, final_url = fetch_page(url)
    if html is None:
        return {
            "url": url,
            "error": f"fetch failed: {final_url}",
            "checks": {},
            "grade": "F",
        }
    if status and status >= 400:
        return {
            "url": url,
            "error": f"HTTP {status}",
            "checks": {},
            "grade": "F",
        }

    if readable_chars(html) < MIN_READABLE_CHARS:
        return {
            "url": final_url,
            "status": status,
            "error": "site loads its content in the browser",
            "checks": {},
            "grade": None,
            "unverified": True,
            "unverified_reason": SCRIPT_BUILT_REASON,
        }

    base_url = base_origin(final_url)
    api_key = get_google_api_key()

    # Run slow/independent checks in parallel
    with ThreadPoolExecutor(max_workers=3) as ex:
        psi_future = ex.submit(check_pagespeed, final_url, api_key)
        team_future = ex.submit(measured, check_about_team, html, base_url)
        blog_future = ex.submit(measured, check_blog_recent, html, base_url)

        psi = psi_future.result()
        about_team_pass = team_future.result()
        blog = blog_future.result()

    checks = {
        "real_photos": check_real_photos(html),
        "pagespeed_mobile": psi.get("pass"),
        "about_team_page": about_team_pass,
        "blog_recent": blog.get("pass"),
        "intake_form": check_intake_form(html),
        "localbusiness_schema": check_local_business_schema(html),
        "google_reviews_widget": check_google_reviews_widget(html),
    }

    return {
        "url": final_url,
        "status": status,
        "checks": checks,
        "pagespeed_score": psi.get("score"),
        "pagespeed_low": psi.get("low"),
        "pagespeed_high": psi.get("high"),
        "pagespeed_runs": psi.get("scores"),
        "pagespeed_error": psi.get("error"),
        "blog_last_post": blog.get("last_post"),
        "blog_url": blog.get("blog_url"),
        "grade": grade_website(checks),
    }


def main():
    parser = argparse.ArgumentParser(description="Website audit (hard mode)")
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.url), indent=2))


if __name__ == "__main__":
    main()
