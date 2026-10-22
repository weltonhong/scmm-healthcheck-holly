"""Google's ad records for the prospect's own website (Welton 2026-10-22).

One look at a search shows what was on the page that second; it can never say whether a business advertises. On 10-22
our search source showed no ads on 50 of 53 recorded answers and DataForSEO none on 11 searches while Chrome showed
ads on 4 of them, so ads came off the booth sheet. Google's Ads Transparency Center answers the durable question: the
ads Google has shown in the US in the last 30 days that point to a website. Read through ScrapingBee, it agreed with
Chrome on all 7 businesses with a website of their own (ops/receipts/20261022T073038_ads-source-test.txt).

What it measures is ads pointing at THEIR WEBSITE'S DOMAIN, so that is all the sheet says (Welton: "Google's ad records
show no ads for their website in the last 30 days"). A business advertising to a landing page on another domain is
invisible to it. A website on a host many businesses share (a franchise's or Dignity Memorial's site, Facebook,
shared_hosts.py) gives records that are not theirs alone: "Couldn't tell". Not graded.

identical copies live in all five booth tools' scripts/ folders; test_booth_ads_records.py fails if any copy drifts.
"""
import os
import re
import urllib.parse

import requests

TRANSPARENCY = "https://adstransparency.google.com/?region=US&domain=%s&preset-date=Last+30+days"
SCRAPINGBEE = "https://app.scrapingbee.com/api/v1/"
COUNT = re.compile(r'class="ads-count[^"]*"[^>]*>\s*(~?)\s*([\d.,]+)\s*([KkM]?)\s+ads?\s*<')
READ, NONE_ON_RECORD, SHARED, NO_WEBSITE, FAILED = "read", "none", "shared", "no_website", "failed"


def domain_of(website):
    """'https://www.havenhome.us/contact' -> 'havenhome.us'; '' when there is no website."""
    s = (website or "").strip().lower()
    if not s:
        return ""
    host = urllib.parse.urlparse(s if "://" in s else "http://" + s).netloc.split(":")[0]
    return host[4:] if host.startswith("www.") else host


def shared(domain):
    from shared_hosts import SHARED_HOSTS
    return domain in SHARED_HOSTS or any(domain.endswith("." + h) for h in SHARED_HOSTS)


def read_count(html):
    """The number of ads the page lists, or None when the page does not say (a block, a changed layout)."""
    m = COUNT.search(html or "")
    if not m:
        return None
    n = float(m.group(2).replace(",", ""))
    return int(n * {"k": 1000, "m": 1000000}.get(m.group(3).lower(), 1))


def fetch(domain, api_key, timeout=150):
    """(http status, body). Google pages need ScrapingBee's custom_google mode (a 400 without it, recorded)."""
    params = {"api_key": api_key, "url": TRANSPARENCY % domain, "render_js": "true", "wait": "6000",
              "premium_proxy": "true", "country_code": "us", "custom_google": "true"}
    r = requests.get(SCRAPINGBEE, params=params, timeout=timeout)
    return r.status_code, r.text


def check(website, api_key=None, fetch=None):
    """{"domain", "status", "ads_30d", "error"}: what Google's ad records say about their website's domain."""
    domain = domain_of(website)
    rec = {"domain": domain, "status": FAILED, "ads_30d": None, "error": None}
    if not domain:
        rec["status"] = NO_WEBSITE
        return rec
    if shared(domain):
        rec["status"] = SHARED
        return rec
    key = api_key if api_key is not None else os.environ.get("SCRAPINGBEE_API_KEY", "")
    if not key:
        rec["error"] = "no ScrapingBee key"
        return rec
    try:
        status, body = (fetch or globals()["fetch"])(domain, key)
    except Exception as e:                                       # noqa: BLE001  a failed read is couldn't check
        rec["error"] = str(e)[:200]
        return rec
    n = read_count(body) if status == 200 else None
    if n is None:
        rec["error"] = "HTTP %s, %s" % (status, "no ad count on the page" if status == 200 else (body or "")[:160])
        return rec
    rec["ads_30d"] = n
    rec["status"] = READ if n > 0 else NONE_ON_RECORD
    return rec


def line(rec):
    """The one line the sheet, the screen and the live log print."""
    s = (rec or {}).get("status")
    if s == NONE_ON_RECORD:
        return "Google's ad records show no ads for their website in the last 30 days."
    if s == READ:
        return "Google's ad records show ads for their website in the last 30 days."
    if s == SHARED:
        return "Couldn't tell (their website is shared with other locations, so its ad records are not theirs alone)"
    if s == NO_WEBSITE:
        return "Couldn't check (no website on their Google listing)"
    return "Couldn't check Google's ad records"
