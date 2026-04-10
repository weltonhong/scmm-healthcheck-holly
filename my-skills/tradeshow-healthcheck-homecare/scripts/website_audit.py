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


def fetch_page(url, timeout=15):
    if not url:
        return None, None, "no url"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        return r.text, r.status_code, r.url
    except Exception as e:
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
    pattern = re.compile(r'<a[^>]+href="([^"]+)"', re.IGNORECASE)
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


def check_pagespeed(url, api_key, timeout=90):
    """Returns dict with score (0-100) and pass (>=50). Retries once on failure
    so a single transient timeout does not silently kill the check. pass=None
    if both attempts fail. Errors are written to stderr so we can see them.
    """
    if not api_key:
        sys.stderr.write("[pagespeed] no GOOGLE_API_KEY available\n")
        return {"score": None, "pass": None, "error": "no api key"}
    if not url:
        return {"score": None, "pass": None, "error": "no url"}

    psi_url = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params = {
        "url": url,
        "strategy": "mobile",
        "category": "performance",
        "key": api_key,
    }

    last_error = None
    for attempt in (1, 2):
        try:
            r = requests.get(psi_url, params=params, timeout=timeout)
            if r.status_code != 200:
                last_error = f"HTTP {r.status_code}: {r.text[:160]}"
                sys.stderr.write(
                    f"[pagespeed] attempt {attempt} failed for {url}: {last_error}\n"
                )
                continue
            data = r.json()
            score = (
                data.get("lighthouseResult", {})
                .get("categories", {})
                .get("performance", {})
                .get("score")
            )
            if score is None:
                last_error = "no score in response"
                sys.stderr.write(
                    f"[pagespeed] attempt {attempt} returned no score for {url}\n"
                )
                continue
            score_pct = round(score * 100)
            return {"score": score_pct, "pass": score_pct >= 50}
        except Exception as e:
            last_error = str(e)[:200]
            sys.stderr.write(
                f"[pagespeed] attempt {attempt} exception for {url}: {last_error}\n"
            )

    return {"score": None, "pass": None, "error": last_error}


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
    if not real:
        return "F"
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

    base_url = base_origin(final_url)
    api_key = get_google_api_key()

    # Run slow/independent checks in parallel
    with ThreadPoolExecutor(max_workers=3) as ex:
        psi_future = ex.submit(check_pagespeed, final_url, api_key)
        team_future = ex.submit(check_about_team, html, base_url)
        blog_future = ex.submit(check_blog_recent, html, base_url)

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
