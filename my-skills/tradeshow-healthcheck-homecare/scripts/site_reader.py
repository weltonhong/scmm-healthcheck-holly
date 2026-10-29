"""One site reader for all five booth tools (Welton 2026-10-29: "build the shared helper, but pin it").

Byte-identical copies live in each tool's scripts/ folder and in each deploy repo;
tradeshow-healthcheck-homecare/scripts/test_site_reader_pinned.py fails if any copy differs by a byte, and fails if
the TributeTech card rules below differ from Bellwether's (bellwether/monthly_update.py), which they are copied from.
Edit one copy, then copy it to the other four.

WHY. Two cemetery checks (property photos, offerings) printed false Nos because each read only the FIRST link that
matched and stopped; about twenty checks across the five tools call their own copy of a one-link finder. And one
obituary platform (TributeTech: "/obituaries/obituary-listings") loads its list in the browser, so a plain read finds
no dates and 10 of 52 readable funeral home sites read "couldn't check" (measured 2026-10-29).
"""
import datetime
import re
import urllib.parse

import requests


def same_site(url, base_url):
    """True when `url` is on the prospect's own site: the same host as `base_url` or one of its subdomains, "www."
    ignored. Another site's page says nothing about the prospect (Welton 2026-10-29: Masonic Home's link to cms.gov
    read as its own star rating; Everstory's network homepage read as Onslow Memorial Park's newest obituary)."""
    def host(u):
        return (urllib.parse.urlparse(u).hostname or "").lower().removeprefix("www.")
    a, b = host(url), host(base_url)
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


# The homepage landed on another site (Welton 2026-10-29): not audited, and said plainly, by name, what the address
# does. Not "couldn't check" (that buries it), not interpreted (a parent company's site or a lost domain, the owner
# says which in two seconds), and not "the address we have" (at a booth that says we hold a file on them).
MOVED = "%s no longer opens their website. It now goes to %s."          # the rep's screen and live log
MOVED_SHEET = "%s no longer opens your website. It now goes to %s."    # the prospect's sheet
MOVED_ASK = "Ask them: is your website still at that address?"


def site_name(url):
    """The site's name as a person types it: host, "www." dropped."""
    url = url if "://" in (url or "") else "http://" + (url or "")
    return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")


def landed_elsewhere(asked_url, final_url):
    """The other site's name when the address we were given ends up on a different site, else None. Priority
    Funeral's address landing on pryorityfuneral.com counts: it is a different site."""
    asked = asked_url if "://" in (asked_url or "") else "http://" + (asked_url or "")
    if not final_url or same_site(final_url, asked):
        return None
    return site_name(final_url) or None


def moved_note(web, sheet=False):
    """The moved sentence for a website result whose address landed elsewhere, or None. Only while the result's own
    reason is still the moved one: a later, stronger reason (an unconfirmed listing) is not overwritten."""
    web = web or {}
    if not web.get("moved_to") or web.get("unverified_reason") != MOVED % (web.get("moved_from"), web["moved_to"]):
        return None
    return (MOVED_SHEET if sheet else MOVED) % (web.get("moved_from"), web["moved_to"])


def links(html, base_url, keywords, limit=3, skipped=None):
    """The first `limit` distinct links on the page whose address holds one of `keywords`, in page order, on the
    prospect's own site only. A matching link to another site is left out and, when `skipped` is a list, added to it,
    so the caller can count it as a page it did not read."""
    out = []
    if not html or not base_url:
        return out
    pattern = re.compile(r"""<a[^>]+href\s*=\s*["']?([^"'\s>]+)""", re.IGNORECASE)
    for m in pattern.finditer(html):
        href = m.group(1).strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        low = href.lower()
        if not any(kw in low for kw in keywords):
            continue
        if href.startswith("http"):
            url = href
        elif href.startswith("//"):
            url = "https:" + href
        elif href.startswith("/"):
            url = base_url.rstrip("/") + href
        else:
            url = urllib.parse.urljoin(base_url.rstrip("/") + "/", href)
        if not same_site(url, base_url):
            if skipped is not None and url not in skipped:
                skipped.append(url)
            continue
        if url not in out:
            out.append(url)
            if len(out) >= limit:
                break
    return out


# ------------------------------------------------------------------ TributeTech obituary lists
# The list is not in the page: the page carries the site's id, and the cards come from one POST (Bellwether reads it
# the same way every month, bellwether/monthly_update.py fetch_tributetech).
_TT_DOMAIN_ID = [
    r'API\.domainId\s*=\s*["\']([a-f0-9-]{20,})["\']',
    r'window\.domain_id\s*=\s*["\']([a-f0-9-]{20,})["\']',
    r'ObDomainId["\s:=]+["\']([a-f0-9-]{20,})["\']',
    r'data-obdomainid=["\']([a-f0-9-]{20,})["\']',
]

_TT_DATE_PAT = (r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
                r'\s+\d{1,2},?\s+\d{4}')
_TT_DATES_DIV = re.compile(r'<div class="dates\b[^"]*">(.*?)</div>', re.S)


def tt_card_death(section):
    """The death date of the TributeTech listing card in `section` (one piece of a page split on obId), or None.

    Welton 2026-10-27: take the death date, never the first date found on the card. Each card has its own dates
    block, "birth - death" or the death date alone, so the death date is its LAST date. The old rule took the
    second date anywhere in the section, and on a card that shows only the death date that is the BIRTH date at
    the start of the obituary text under it (Beck: Nola Jo Phillips, "June 12, 2026" then "January 14, 1937
    June 12, 2026", read as dying in 1937, which also ended the walk at June). A section with no dates block (an
    older template) keeps the old rule."""
    m = _TT_DATES_DIV.search(section)
    if m:
        ds = re.findall(_TT_DATE_PAT, m.group(1))
        return ds[-1] if ds else None
    ds = re.findall(_TT_DATE_PAT, section)
    return ds[1] if len(ds) >= 2 else None


def tributetech_newest(page_html, page_url, headers, timeout=15):
    """For a TributeTech obituary page: {"newest": the latest death date on the first page of cards (a date) or None,
    "cards": how many cards were read}. None when the page is not TributeTech (no site id on it). Raises on a request
    that fails, so the caller can say it could not read the list."""
    dom = next((m.group(1) for p in _TT_DOMAIN_ID for m in [re.search(p, page_html or "", re.IGNORECASE)] if m), None)
    if not dom:
        return None
    base = re.match(r"https?://[^/]+", page_url).group(0)
    r = requests.post(base + "/ObituariesHelper/ObituariesListPagedItems",
                      data={"PageSize": 50, "FirstPageObituariesCount": 0, "ObDomainId": dom, "CurrentPage": 1,
                            "SearchText": "", "HasNextPage": "True"},
                      headers=dict(headers, **{"X-Requested-With": "XMLHttpRequest", "Referer": page_url}),
                      timeout=timeout)
    if r.status_code != 200:
        raise requests.RequestException("TributeTech list answered HTTP %s" % r.status_code)
    days = []
    for section in re.split(r'obId=\d+', r.text):
        d = tt_card_death(section)
        if d:
            d = re.sub(r"\s+", " ", d.replace(",", "")).strip()
            try:
                days.append(datetime.datetime.strptime(d, "%B %d %Y").date())
            except ValueError:
                pass
    return {"newest": max(days) if days else None, "cards": len(days)}
