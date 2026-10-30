"""
Jeb Blount Fanatical Prospecting hook generator.

Each hook has 4 beats:
  1. Name + company intro
  2. "The reason I'm calling" because-statement (uses real data from scan)
  3. Why it matters in vertical industry language
  4. Assumptive close with alternative choice

Two hooks are generated per contact: one for 3-Pack, one for SEO.
"""

import re as _re_module


VERTICAL_BRAND = {
    "funeral home": "Ring Ring Marketing",
    "cemetery": "Ring Ring Marketing",
    "home care": "Senior Care Marketing Max",
    "home health": "Senior Care Marketing Max",
    "hospice": "Senior Care Marketing Max",
    "assisted living": "Senior Care Marketing Max",
}

VERTICAL_LABEL = {
    "funeral home": "funeral homes",
    "cemetery": "cemeteries",
    "home care": "home care agencies",
    "home health": "home health agencies",
    "hospice": "hospice agencies",
    "assisted living": "assisted living communities",
}

# Why-it-matters templates per vertical and surface (3-Pack vs SEO).
# Phrased in the vertical's own language so setters sound like insiders.
WHY_3PACK = {
    # What a setter may add after the counted sentence (Welton 2026-10-22). Gone: "roughly 60% of local clicks", "the
    # first listing on the map wins the first call", "{winner} is getting those tours / booking those billable hours",
    # and searches never run ("live-in, overnight, the whole book"): none was measured, and no statistic is on an
    # approved list (ruling 6). A vertical's plain context stays.
    "funeral home": "At-need decisions are same-day.",
    "cemetery": "When families tour, they tour what they find on the map first.",
    "home care": "",
    "home health": (
        "When a family leaves the hospital with a list of agencies, "
        "they look each one up before they call."
    ),
    "hospice": "Referral sources and families both check the map first.",
    "assisted living": "Adult children tour what they find on the map first.",
}

WHY_SEO = {
    # Gone (2026-10-22): "Page two gets less than 1% of clicks", "every family typing these terms is calling them
    # instead of you", "every pre-need family searching today is landing on them", "referral starts going somewhere
    # else", and "the searches families are actually typing" (no search volume was measured: "the searches I ran").
    "funeral home": (
        "When a family has just lost someone, they research before they "
        "call. {winner} is on page one for the searches I ran. You're not."
    ),
    "cemetery": "{winner} is on page one for the searches I ran. You're not.",
    "home care": "{winner} is on page one for the searches I ran. You're not.",
    "home health": (
        "Families pick fast after a discharge. {winner} is on page one. "
        "You aren't."
    ),
    "hospice": (
        "Referral sources Google fast. {winner} is on page one for the hospice "
        "searches I ran. You're not."
    ),
    "assisted living": (
        "Adult children shop online before they tour. {winner} is on page "
        "one for the searches I ran. You're not."
    ),
}

# Fallback "why it matters" when we have no top competitor to reference
# (e.g. neither prospect nor competitors rank in the 3-Pack).
WHY_3PACK_NO_WINNER = {
    # NO "NOBODY" LINE (Welton 2026-10-22, P13). It said "neither you nor your direct competitors are in the
    # three-pack" when no rival SURVIVED the filters (the state check, a Places error, the cap). Since 2026-10-21 a
    # search counts only when its map had cards on it, so somebody was always there. Empty: no line.
    v: "" for v in ("funeral home", "cemetery", "home care", "home health", "hospice", "assisted living")
}

WHY_SEO_NO_WINNER = {
    # NO "NOBODY" LINE (P13): a page one always has somebody on it; "nobody in your area" meant nobody survived the
    # filters. Empty: no line.
    v: "" for v in ("funeral home", "cemetery", "home care", "home health", "hospice", "assisted living")
}

# --------------------------------------------------------------------------- #
# A VERDICT REQUIRES A MEASUREMENT (Welton, 2026-09-21)
# --------------------------------------------------------------------------- #
#
# The NO_WINNER wording above says "nobody is in the map" / "your competitors
# aren't on page one either". Those are claims about the MARKET, and they are
# only true when searches actually ran and actually came back empty.
#
# Both hook builders used to reach them from a "total == 0" degenerate branch
# as well -- i.e. when EVERY search in the section had FAILED. So a vendor
# outage produced, verbatim, on a live card:
#
#   "...I wasn't able to capture the three-pack data across Cape Coral and the
#    two closest cities you serve. Right now nobody in your service area is in
#    the map at all."
#
# The first sentence admits we did not look. The second asserts what we would
# have seen. Twelve rows above it read UNAVAILABLE (scan failed). On 2026-09-20
# a ScrapingBee outage produced exactly that on a home health card AND on a
# funeral home card, so this is every vertical, not one.
#
# The rule now:
#   * a section with ZERO successful searches gets NO hook at all -- the
#     builders return None and format_card omits the heading;
#   * when BOTH sections have zero, no card is built and the queue tag stays
#     so the next run retries it (enforced by the callers, via scan_coverage);
#   * NO_WINNER fires only from the tiers, which are reached only when at
#     least one search in the section succeeded.
#
# One definition, imported by batch_ranking AND regenerate_cards, so the two
# card-making paths cannot disagree about what "failed" means.


class ScanCoverage:
    """How many searches in each section actually returned data."""

    __slots__ = ("tp_ok", "tp_total", "seo_ok", "seo_total")

    def __init__(self, tp_ok, tp_total, seo_ok, seo_total):
        self.tp_ok, self.tp_total = tp_ok, tp_total
        self.seo_ok, self.seo_total = seo_ok, seo_total

    @property
    def all_failed(self):
        """True only when NEITHER section has a single successful search."""
        return self.tp_ok == 0 and self.seo_ok == 0

    def reason(self):
        return ("all %d searches failed (3-Pack 0 of %d, SEO 0 of %d); no card "
                "built, queue tag left in place for the next run"
                % (max(self.tp_total, self.seo_total), self.tp_total,
                   self.seo_total))

    def __repr__(self):
        return ("<ScanCoverage 3pack %d/%d seo %d/%d>"
                % (self.tp_ok, self.tp_total, self.seo_ok, self.seo_total))


def map_read(row):
    """True when this 3-Pack row's search came back with a map we read, so the
    prospect can be in it or missing from it. A search with no map card (no
    map shown, or one we could not read) is neither, and is counted nowhere
    (Welton 2026-10-21, the pre-call and Where Are You rule). Rows saved before
    2026-10-21 carry no pack_present and keep the meaning they were built with
    (past cards are not corrected, Welton 2026-10-14)."""
    if row.get("error"):
        return False
    if row.get("maybe_rank"):
        # A card that may be theirs and could not be confirmed (A5): neither in the pack nor missing from it.
        return False
    if "pack_present" not in row and not [t for t in (row.get("top_3") or []) if t]:
        # Saved before 2026-10-21 with no map card at all (P14): a rebuilt card read this as "Not found".
        return False
    return row.get("pack_present", True) is True


def scan_coverage(three_pack_rows, seo_rows):
    """Count successful vs attempted searches per section.

    A row is a failure when it carries `error` (the fetch raised). A row with
    no rank and no error is a SUCCESSFUL search that found nothing -- a real
    answer, and exactly what NO_WINNER exists to describe. Those two must
    never be counted together.
    """
    tp = list(three_pack_rows or [])
    seo = list(seo_rows or [])
    return ScanCoverage(
        tp_ok=sum(1 for r in tp if not r.get("error")), tp_total=len(tp),
        seo_ok=sum(1 for r in seo if not r.get("error")), seo_total=len(seo),
    )


# --------------------------------------------------------------------------- #
# ONLY SAY WHAT WE COUNTED (Welton, 2026-09-22)
# --------------------------------------------------------------------------- #
#
# The competitor lines ("{winner} is showing up in more of them", "You're
# not", "You don't", "not even in the conversation") asserted that the named
# competitor beat the prospect. Nothing counted that: the named competitor is
# the most frequent name in the DISPLAYED lists (one keyword per city), and
# its count was never compared with the prospect's. Measured 2026-09-22 on
# 3,993 saved scans: when the prospect ranked in some searches, the named
# competitor was NOT ahead in 229 of 517 funeral cases, 289 of 395 at the
# "about half" tier, and in both home health cases (3 vs 3, 2 vs 2).
#
# The rule, per section (3-Pack, SEO), across ALL searches that worked:
#   a. prospect in none            -> sales line exactly as before
#   b. prospect in some, named
#      competitor truly in MORE    -> keep the counted summary sentence, drop
#                                     the denial sentence ("You're not" etc)
#   c. prospect in some, named
#      competitor NOT in more      -> no sales line for that section
# The named competitor is never the prospect itself (same site or same name).
# This only REMOVES sentences: no new wording is introduced anywhere.

_DENIALS = ("You're not", "You don't", "You aren't", "not even in the conversation")
_SENTENCE_SPLIT = _re_module.compile(r"(?<=[.!?])\s+")


def drop_denials(text):
    """Remove every sentence that denies the prospect is there. Nothing else
    in the text changes."""
    if not text:
        return text
    kept = [s for s in _SENTENCE_SPLIT.split(text.strip())
            if not any(d in s for d in _DENIALS)]
    return " ".join(kept)


def count_3pack_appearances(rows, name):
    """Searches (that worked) whose 3-Pack lists `name`, by brand key --
    across ALL rows, not just the displayed per-city lists."""
    k = _canonical_brand_key(name) if name else ""
    if not k:
        return 0
    return sum(1 for r in rows or [] if not r.get("error")
               and any(_canonical_brand_key(n) == k for n in (r.get("top_3") or [])))


def _norm_host(h):
    h = (h or "").strip().lower()
    return h[4:] if h.startswith("www.") else h


def same_site(a, b):
    """True when two hosts are the same site (www. and subdomains folded)."""
    a, b = _norm_host(a), _norm_host(b)
    return bool(a) and bool(b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def count_seo_appearances(rows, host):
    """Searches (that worked) where `host` is on page one (top 10). None when
    there is no host to count, which callers must treat as NOT counted."""
    if not _norm_host(host):
        return None
    n = 0
    for r in rows or []:
        if r.get("error"):
            continue
        results = r.get("results") or []
        page1 = [x for x in results if (x.get("position") or 99) <= 10] or results[:10]
        if any(same_site(x.get("domain"), host) for x in page1):
            n += 1
    return n



# REAL SEO NAMES ONLY (Welton, 2026-09-22). An SEO "competitor" is read out of
# a page title, so it can be a page title ("Cremation $1,285", "Providing
# Senior Home Care in Mobile") or a name that is not the site's own ("O'Boyle
# Funeral Home" on rosedalecemetery.org). A card may only name it when it is a
# real business name that belongs to the site it came from. The evidence is
# the web address, not a list of known businesses: every distinctive word of
# the name must appear in the site's address. Skipping is better than guessing,
# so a real name that fails (an acronym site, a franchise town suffix) is lost.
_NAME_GENERIC = frozenset("""
    home homes homecare care caregiver caregivers funeral funerals service services
    senior seniors health healthcare cremation cremations crematory crematories
    cemetery cemeteries chapel chapels mortuary mortuaries memorial memorials family
    families and of the in at for by with inc llc co ltd pc pllc corp company agency
    group center centre centers directors
""".split())
_NAME_PREPOSITIONS = frozenset("of in for near at serving".split())
_NAME_DANGLING_END = frozenset("of in for near at serving and the by to with pre".split())
_NAME_TITLE_CHARS = set(":|$()!?@")


def _host_stem(host):
    """'www.rosedalecemetery.org' -> 'rosedalecemetery'. Every label but the
    last, letters and digits only."""
    labels = _norm_host(host).split(".")
    return "".join(_re_module.sub(r"[^a-z0-9]", "", x) for x in labels[:-1])


def is_real_seo_name(name, host):
    """True only when `name` reads as a business name AND belongs to `host`.

    Fails on: any title character (: | $ ( ) ! ? @); a name ending on a
    dangling word ("... Funeral Home in"); a name that opens with a generic
    word and carries a place preposition ("Cemeteries of Bell County"); a name
    with no distinctive word at all ("Senior Home Care"); and any distinctive
    word (not generic, 2+ letters) missing from the site's address."""
    name = (name or "").strip()
    stem = _host_stem(host)
    if not name or not stem:
        return False
    if any(ch in _NAME_TITLE_CHARS for ch in name):
        return False
    words = [w.replace("'", "") for w in _re_module.findall(r"[a-z0-9']+", name.lower())]
    words = [w for w in words if w]
    if not words or words[-1] in _NAME_DANGLING_END:
        return False
    if words[0] in _NAME_GENERIC and any(w in _NAME_PREPOSITIONS for w in words):
        return False
    distinctive = [w for w in words if len(w) >= 2 and w not in _NAME_GENERIC]
    if not distinctive:
        return False
    return all(w in stem for w in distinctive)


# The SEO sentences that name the competitor, in the hook's own wording. When
# the name is not real they are removed, with the sentences that only make
# sense beside them (the "You're not" half, and "them" meaning the competitor).
_SEO_NAME_CLAUSES = (" {winner} did.", " {winner} is on page one for more of them.",
                     " {winner} is where families actually click.",
                     " {winner} is holding those top spots.")
_COMPETITOR_PRONOUNS = ("calling them instead of you", "landing on them")


def drop_named_competitor(reason, why_template, winner):
    """Return (reason, why) with every sentence about an unnamed competitor
    removed. Works on the TEMPLATE so a name containing a period cannot hide
    from the sentence split. Removal only."""
    for clause in _SEO_NAME_CLAUSES:
        reason = reason.replace(clause.format(winner=winner), "")
    keep = [x for x in _SENTENCE_SPLIT.split(why_template.strip())
            if "{winner}" not in x
            and not any(d in x for d in _DENIALS)
            and not any(p in x for p in _COMPETITOR_PRONOUNS)]
    return reason, " ".join(keep)

# Assumptive close -- used at the end of every hook.
# Quick Intel SKILL.md rule 5 wins: never "I'd love to show you" (Welton 2026-10-22, ruling 7).
CLOSE = (
    "Could I walk you through what I found? Tuesday at 10 or "
    "Wednesday at 2 -- which works better?"
)


# Phase 2.3: per-vertical wording for the "most" tier of the 3-Pack hook.
# Used when prospect is in the 3-Pack for most (68%+) of the scanned searches
# -- the pain story is about slippage on high-intent keywords rather than
# absence from the pack entirely.
SLIPPAGE_KEYWORD = {
    "funeral home": "'cremation'",
    "cemetery": "'burial plots'",
    "home care": "'live-in'",
    "home health": "'skilled nursing'",
}
SLIPPAGE_PAIN_NOUN = {
    "funeral home": "cases",
    "cemetery": "pre-need conversations",
    "home care": "billable hours",
    "home health": "referral starts",
}

# "Most" tier why-it-matters, vertical-specific. Used after the tiered
# summary sentence when the prospect is in the pack for 68%+ of searches.
WHY_3PACK_MOST = {
    # Gone (2026-10-22): "rank #1 gets the first call", "every search where you're not #1 is a case potentially going
    # to a competitor", "roughly 60% of local clicks", "slippage on live-in and overnight searches" (never run). The
    # most-tier summary names a real search where they are not first; nothing is added after it.
    v: "" for v in ("funeral home", "cemetery", "home care", "home health")
}


# Phase 2.5: national-guide / cost-content pattern detection.
#
# These are the informational articles that slip through the listicle
# filter because they don't start with Best/Top/What/Why/Which -- titles
# like "Cost of Cremation in California: 2026 Prices + Ways to Save" or
# "Funeral Costs in 2026: What to Expect". They're legitimate page titles
# on a real domain, but they're national guide content, not a local
# competitor to the prospect. Phase 2.5 only COUNTS these so we can see
# the residual rate; filtering comes in a later phase if the count is
# high enough to warrant it.
_NATIONAL_GUIDE_REGEX = _re_module.compile(
    r"\bcost\s+of\s+(cremation|funeral|burial)\b"
    r"|\b(cremation|funeral|burial)\s+costs?\b"
    r"|\bhow\s+much\s+does\s+(a\s+)?(cremation|funeral|burial)\b"
    r"|\b(price|pricing|cost)\s+guide\b"
    r"|\bbreakdown\s+by\s+state\b"
    r"|\bwhat\s+to\s+expect\b",
    _re_module.IGNORECASE,
)


def is_national_guide_title(title):
    """True when the title looks like a cost/how-to national article rather
    than a local competitor. Used for residual-issue counting only."""
    if not title:
        return False
    return bool(_NATIONAL_GUIDE_REGEX.search(title))


# Generic page-label / nav-text strings (lowercase, normalized). When the
# extracted "business name" matches one of these, it's almost certainly a
# page heading rather than an actual business name -- fall back to the
# next-best SEO candidate or to the humanized domain.
GENERIC_TITLE_SEGMENTS = {
    # Navigation
    "home", "homepage", "home page", "main menu", "menu", "navigation",
    "welcome", "welcome to our site", "locations", "directions",
    "find a location",
    # About section pages
    "about", "about us", "our story", "our history", "our mission",
    "our values", "our family", "our people", "our staff", "our team",
    "our locations",  # phase 2.10
    "staff", "team", "family", "history", "mission",
    # Contact pages
    "contact", "contact us",
    # Services-section generics (vertical-vocabulary only, no proper noun)
    "services", "our services", "funeral services", "cremation services",
    "home care services", "home health services", "senior care",
    "senior care services", "home health", "home care",
    "plan ahead", "preplan", "pre-planning", "pre planning",
    "burial", "cremation", "memorials", "memorial services",
    # Phase 2.14: bare-plural / bare-singular page titles that extract
    # verbatim when a SERP result has no proper-noun branding. 138
    # contacts surfaced "Funeral Homes" alone as a top competitor
    # because the source pages were generic directory landing pages.
    "funeral home", "funeral homes", "funeral service",
    "mortuary", "mortuaries", "crematory",
    "memorial chapel", "memorial chapels",
    # Obituary listings
    "obituaries", "obituary", "recent obituaries", "latest obituaries",
    "obituary listings",
    # Phase 2.9: FAQ / aid-content / directory-style exact matches
    "faq", "faqs", "cremation faqs", "funeral faqs", "cremation faq",
    "funeral faq", "frequently asked questions",
    "cremation for the indigent", "funeral for the indigent",
}


# Phase 2.9: regex-based generic-segment patterns. Runs alongside the
# exact-string set above. Each pattern matches a whole-segment class that
# isn't a real business name -- FAQ pages, listicle titles whose first
# segment wasn't caught by _listicle_verdict, "[City], [State]" bare
# directory headers, and "... for the indigent" aid-content pages.
_BUSINESS_WORDS_RE = _re_module.compile(
    r"\b(funeral|cremation|cremat|mortuary|chapel|memorial|cemetery|"
    r"services|home|directors?|burial|preplan)\b",
    _re_module.IGNORECASE,
)

_GENERIC_SEGMENT_PATTERNS = (
    # Listicle starts that slip through _listicle_verdict because the
    # carve-outs preserved the domain. The extracted name still shouldn't
    # quote the listicle title verbatim.
    _re_module.compile(r"^top\s+\d+\b", _re_module.IGNORECASE),
    _re_module.compile(r"^the\s+top\s+\d+\b", _re_module.IGNORECASE),
    _re_module.compile(r"^best\s+\d+\b", _re_module.IGNORECASE),
    # Phase 2.10: "[N] Best Funeral Homes in City" -- leading-digit variant
    # of the listicle pattern (e.g. "10 Best Funeral Homes in Penitas, TX").
    _re_module.compile(r"^\d+\s+best\b", _re_module.IGNORECASE),
    # Phase 2.10: "Best [vertical] near/in City" -- non-numeric listicle
    # titles preserved by Phase 2.2 Option-3 carve-outs. Display path only
    # (filter path still keeps the competitor domain counted); the segment
    # is treated as generic so extraction falls back to humanized domain.
    _re_module.compile(
        r"^best\s+(funeral|cremation|burial|mortuary|memorial|crematory|cemetery|direct)",
        _re_module.IGNORECASE,
    ),
    # Phase 2.10: "THE BEST 10 ..." variant. Existing ^best\s+\d+\b only
    # catches strings starting literally with "best"; uppercase SERP
    # titles like "THE BEST 10 CREMATION SERVICES in TROY, MI" start
    # with "THE" and slipped through.
    _re_module.compile(r"^the\s+best\s+\d+\b", _re_module.IGNORECASE),
    # Phase 2.10: "Find [the] [best] funeral homes near X" -- directory
    # / listicle finders with a vertical keyword.
    _re_module.compile(
        r"^find\s+(the\s+)?(best\s+)?(funeral|cremation|burial|mortuary)\b",
        _re_module.IGNORECASE,
    ),
    # Phase 2.10: obituary-index prefixes ("Most Recent Obituaries",
    # "Latest Obituary Listings"). Existing exact set only catches the
    # bare phrase without a "Most Recent" / "Latest" modifier.
    _re_module.compile(
        r"\b(most\s+recent|latest)\s+obituar",
        _re_module.IGNORECASE,
    ),
    # Phase 2.10: singular obituary-row labels and possessive forms.
    # "Obituary Listing" (singular), "Obituary for Mamie Sylvia...",
    # "Obituary of Carl Francis...", "Obituary Notifications".
    _re_module.compile(
        r"\bobituary\s+(listing|for|of|notification)\b",
        _re_module.IGNORECASE,
    ),
    # Phase 2.10: named-person obituary pages -- "Obituary for [Name]" /
    # "[Name] Obituary April 15, 2026" style page titles. Matches when
    # the segment starts with "Obituary for" followed by a capitalized
    # word (a name).
    _re_module.compile(r"^obituary\s+for\s+[A-Z]", _re_module.IGNORECASE),
    # FAQ-style page titles
    _re_module.compile(r"\bfaqs?\b", _re_module.IGNORECASE),
    # Aid-content
    _re_module.compile(r"\bfor the indigent\b", _re_module.IGNORECASE),
    # Phase 2.14: directory-style location titles. Mirror of the
    # _listicle_verdict Fix 2 rules, but applied at segment level so
    # extraction skips a segment like "Funeral Services in Adair" when
    # it appears after a title separator ("Something - Funeral Services
    # in Adair"). Listicle_verdict catches the raw title only when the
    # directory phrase starts at position 0.
    _re_module.compile(
        r"^funeral (homes?|services?) in\s+",
        _re_module.IGNORECASE,
    ),
    _re_module.compile(
        r"^cremation (services?|providers?) in\s+",
        _re_module.IGNORECASE,
    ),
)


def _is_bare_city_state(text):
    """True when text is exactly "[City name], [ST]" or "[City name] [ST]"
    with nothing else -- no funeral-industry words in the city portion.
    Catches bare directory headers like "Winston-Salem, NC" or
    "Pasadena CA" that get surfaced when Google's SERP title splits
    leave just a location label as a segment."""
    if not text:
        return False
    s = text.strip()
    # Comma form: "Pasadena, CA"
    m_comma = _re_module.match(
        r"^[a-z][\w\s\-\.']*,\s*[a-z]{2}\s*$",
        s, _re_module.IGNORECASE,
    )
    # Space form: "Pasadena CA" (no comma)
    m_space = _re_module.match(
        r"^[a-z][\w\-\.']+(?:\s+[a-z][\w\-\.']+)*\s+[a-z]{2}\s*$",
        s, _re_module.IGNORECASE,
    )
    if not m_comma and not m_space:
        return False
    if m_comma:
        before_loc = s.rsplit(",", 1)[0]
    else:
        before_loc = " ".join(s.split()[:-1])
    if _BUSINESS_WORDS_RE.search(before_loc):
        return False
    return True


def _decode_entities(s):
    """Decode the handful of HTML entities that show up in SERP titles."""
    if not s:
        return s
    return (
        s.replace("&amp;", "&")
         .replace("&#39;", "'")
         .replace("&quot;", '"')
         .replace("&#x27;", "'")
         .replace("&lt;", "<")
         .replace("&gt;", ">")
    )


# Bug 4: brand-symbol stripping for SEO-extracted competitor names.
# Mirror of serp_helpers.strip_brand_symbols -- duplicated here so this
# module stays self-contained (hook_generator is imported into
# regenerate_cards.py without serp_helpers). Both paths apply the same
# rules so a name extracted from a SERP title or pulled from a cached
# top_3 list ends up identical regardless of code path.
_BRAND_SYMBOL_CHARS = (
    "®", "™", "©", "℠",
    "�",  # U+FFFD replacement char from prior-batch mojibake
)
_BRAND_SYMBOL_ENTITIES = (
    "&reg;", "&trade;", "&copy;", "&sm;",
    "&#174;", "&#8482;", "&#169;", "&#8480;",
)
_BRAND_SYMBOL_WORDFORMS_RE = _re_module.compile(
    r":(?:registered|trademark|copyright|tm|sm|r|c):",
    _re_module.IGNORECASE,
)
_PAREN_BRAND_SYMBOL_RE = _re_module.compile(
    r"\s*\((?:r|tm|sm|c)\)",
    _re_module.IGNORECASE,
)


def _strip_brand_symbols(text):
    """Remove ®/™/©/℠ + HTML entities + ":registered:" / "(R)" forms
    + U+FFFD mojibake remnants from a string. Collapses whitespace."""
    if not text:
        return text
    s = text
    for ch in _BRAND_SYMBOL_CHARS:
        s = s.replace(ch, "")
    for ent in _BRAND_SYMBOL_ENTITIES:
        s = s.replace(ent, "")
    s = _BRAND_SYMBOL_WORDFORMS_RE.sub("", s)
    s = _PAREN_BRAND_SYMBOL_RE.sub("", s)
    s = _re_module.sub(r"\s+", " ", s).strip()
    return s


# Bug 2: page-title patterns that look like SEO landing pages rather
# than business names. When _extract_competitor_name pulls a segment
# matching one of these, we skip the segment and fall back to humanized
# domain. These are PHRASES that real businesses don't put as their
# brand-line in a page title, but that SEO-optimized landing pages
# stuff into <title> for keyword targeting.
#
# Examples observed on the home-care batch QA:
#   "Home Care for Elderly Adults in Decatur"
#   "24-Hour In-Home Care and Senior Care in Durham"
#   "Trusted Home Care in Durham"
#   "In-home Care in Stanwood"
#   "Live-in 24-Hour In-Home Care"
#   "Home Care in West Haven"
#
# Tuning principle: false negatives (a real brand misclassified as page
# title) cost us nothing -- humanized domain is always an OK fallback.
# False positives (a page title slipping through as a "competitor")
# break Diego's hook delivery on a live call. Lean toward over-matching.
_PAGE_TITLE_PATTERNS = (
    # "<vertical noun> in <City>" / "<vertical noun> for <something>"
    # / "<vertical noun> near <City>" -- segment is purely descriptive
    # location-targeting copy, not a brand.
    _re_module.compile(
        r"^(in[\s\-]?home\s+care|home\s+care|senior\s+care|"
        r"24[\s\-]?hour\s+(?:in[\s\-]?home\s+)?care|"
        r"24[\s\-]?hour\s+home\s+care|"
        r"home\s+health(?:\s+care)?|"
        r"funeral\s+(?:home|services)|"
        r"cremation(?:\s+services)?)\s+(?:in|near|for)\s+",
        _re_module.IGNORECASE,
    ),
    # "Trusted home care", "Affordable in-home care", "Best senior care"
    # Adjective-led copy that's never a real brand.
    _re_module.compile(
        r"^(trusted|affordable|reliable|quality|professional|expert|"
        r"caring|compassionate|dedicated|experienced|premier|"
        r"customized|personalized|personal|customised|elite)\s+"
        r"(in[\s\-]?home|home|senior|elderly|companion)\s+(care|health)\b",
        _re_module.IGNORECASE,
    ),
    # "Home care for elderly/seniors/adults" -- target-audience copy
    _re_module.compile(
        r"\bhome\s+care\s+for\s+(elderly|seniors|adults|"
        r"aging|the\s+elderly|the\s+aged)\b",
        _re_module.IGNORECASE,
    ),
    # "Live-in / 24-hour / overnight in-home care" -- service-modifier
    # copy that always reads as page title, never as a brand. The `+`
    # after the modifier group lets one or more modifiers stack so
    # "Live-in 24-Hour In-Home Care" matches alongside "Live-in
    # In-Home Care".
    _re_module.compile(
        r"^(?:(?:live[\s\-]?in|24[\s\-]?hour|round[\s\-]?the[\s\-]?clock|"
        r"overnight|hourly|daily|weekly|all[\s\-]?day)\s+)+"
        r"(?:(?:in[\s\-]?home|home|senior)\s+(?:care|health)|"
        r"(?:home|senior)\s+helpers)\b",
        _re_module.IGNORECASE,
    ),
    # "Senior care services in <City>" / "Home health services in <City>"
    _re_module.compile(
        r"^(home|senior|elderly)\s+(care|health)\s+"
        r"(services|agency|agencies|providers?)\s+(in|near|for)\b",
        _re_module.IGNORECASE,
    ),
    # "Best home care agencies" without a leading "Best" -- already
    # caught by listicle filter; pattern below catches descriptions
    # like "Top home care provider in <City>".
    _re_module.compile(
        r"^(top|leading)\s+(home|senior|in[\s\-]?home)\s+"
        r"(care|health)\s+(agency|agencies|provider|providers|"
        r"company|companies)\b",
        _re_module.IGNORECASE,
    ),
)


def _looks_like_page_title_segment(seg):
    """True when a title segment matches one of the SEO-page-title
    patterns above. Used by _extract_competitor_name as an additional
    skip-condition before _is_generic_segment."""
    if not seg:
        return False
    for pat in _PAGE_TITLE_PATTERNS:
        if pat.search(seg):
            return True
    return False


# Phase 2.14 Fix 1: trailing address stripping. SERP titles sometimes bake
# a full address into the first segment, e.g.
#   "Boies-Ortega Funeral Home, 115 E 5th St, Walsenburg, CO"
# which defeats downstream prospect-self-match (the compacted length gap
# blows past the 70% prefix threshold) and clutters the displayed
# competitor name with an address when read aloud.
#
# These patterns peel address components off the END of a title segment.
# Each is narrow enough that a business name can't plausibly match it
# (business names don't contain "STREET NUMBER + STREET NAME + ST" suffix).
_TRAIL_CITY_STATE_RE = _re_module.compile(
    r",\s*[A-Za-z][A-Za-z\.\'\- ]+,\s*[A-Za-z]{2}\s*$"
)
_TRAIL_STREET_RE = _re_module.compile(
    r",\s*\d+\s+[\w\.\'\&\-/ ]+?$",
    _re_module.IGNORECASE,
)
_TRAIL_BARE_STATE_RE = _re_module.compile(r",\s*[A-Za-z]{2}\s*$")


def _strip_trailing_address(text):
    """Peel trailing address components off a title segment. Handles
    stacked patterns like 'BIZ, 115 E 5th St, City, ST' in up to three
    passes so both the street portion and the ', City, ST' tail come off.
    Returns the cleaned segment."""
    if not text:
        return text
    s = text
    for _ in range(3):
        before = s
        s = _TRAIL_CITY_STATE_RE.sub("", s).rstrip()
        s = _TRAIL_STREET_RE.sub("", s).rstrip()
        s = _TRAIL_BARE_STATE_RE.sub("", s).rstrip()
        if s == before:
            break
    return s.rstrip(" ,")


def _clean_title_segment(seg):
    """Trim and strip common trailing boilerplate from a title segment."""
    import re as _re
    s = _decode_entities((seg or "").strip())
    # Bug 4: strip trademark/registered/copyright glyphs alongside HTML
    # entity decoding so they can never leak into a competitor name.
    s = _strip_brand_symbols(s)
    # Strip trailing suffixes that aren't part of the business name
    for suffix in (
        " - Home", " - Home Page", " - Homepage",
        " | Home", " | Home Page", " | Homepage",
        " - Official Site", " | Official Site",
        " - Official Website", " | Official Website",
    ):
        if s.lower().endswith(suffix.lower()):
            s = s[: -len(suffix)].strip()
    # Strip trailing ellipsis / truncation markers that upstream SERP
    # clipping leaves behind: " ...", " and ...", " | ..."
    s = _re.sub(r"\s*(?:and\s+)?\.{2,}\s*$", "", s).strip()
    s = _re.sub(r"\s*[\|\-–\u2014]\s*\.{2,}\s*$", "", s).strip()
    # Phase 2.14: strip trailing address components AFTER suffix + ellipsis
    # cleanup so "Biz, 115 E 5th St, City, ST ..." gets the ellipsis
    # removed first, then the street+city+state tail.
    s = _strip_trailing_address(s)
    # Collapse whitespace
    s = _re.sub(r"\s+", " ", s)
    return s


def _is_generic_segment(seg):
    """True when this title segment is navigation text, a listicle-style
    header, FAQ content, bare city+state, or aid content -- not a real
    business name. Callers (segment picker + cleanest-competitor cascade)
    skip to the next candidate when this returns True.

    Layered check: exact-string match against GENERIC_TITLE_SEGMENTS first,
    then regex-pattern match against _GENERIC_SEGMENT_PATTERNS, then the
    bare-city-state heuristic.
    """
    if not seg:
        return False
    cleaned = seg.lower().strip()
    if cleaned in GENERIC_TITLE_SEGMENTS:
        return True
    for pat in _GENERIC_SEGMENT_PATTERNS:
        if pat.search(seg):
            return True
    if _is_bare_city_state(seg):
        return True
    return False


def _extract_competitor_name(title, domain):
    """Turn a SERP result into a clean displayable competitor name.

    Preference order:
      1. First non-generic, non-page-title segment of the page title
         (split on |, -, em/en dash, ::) with at least 2 words
      2. Humanized domain ('kiesingerfuneralservices.com' -> 'Kiesinger Funeral Services'
         via the atomic-word dictionary)
      3. The raw title as-is (last resort)

    Bug 2: A title segment that matches a SEO page-title pattern
    (e.g. "Home Care in West Haven", "Trusted In-Home Care",
    "Home Care for Elderly Adults in Decatur") is skipped via
    _looks_like_page_title_segment so the next segment, or the
    humanized domain, is used instead. Reads as the brand the call-
    setter is looking at on Google rather than a marketing slug.
    """
    import re as _re
    if title:
        # Split on common title separators. en/em dashes render differently;
        # match the Unicode ones as well as ASCII hyphen. `:` is only a
        # separator when spaced (so we don't split inline ratios like "4.5:5").
        parts = _re.split(r"\s+\|\s+|\s+[\-–\u2014]\s+|\s+:{1,2}\s+", title)
        parts = [_clean_title_segment(p) for p in parts if p and p.strip()]
        for p in parts:
            if _is_generic_segment(p):
                continue
            # Bug 2: page-title style segments don't read as brand names.
            # Skip and let the cascade fall through to humanized domain.
            if _looks_like_page_title_segment(p):
                continue
            word_count = len(_re.findall(r"\w+", p))
            if word_count < 2:
                continue
            # Don't pick a segment that's itself a title suffix like "Serving X"
            if p.lower().startswith(("serving ", "proudly serving ")):
                continue
            return p

    humanized = _humanize_domain(domain)
    if humanized:
        return humanized
    return (title or "").strip() or domain


def _scan_phrase(cities):
    """Return the part of a hook that describes the cities scanned.

    - 3+: 'across [Home] and the two closest cities you serve'
    - 2:  'in [Home] and [City2]'
    - 1:  'in [Home]'
    """
    if not cities:
        return ""
    home = cities[0]
    if len(cities) >= 3:
        # Straight-line nearest towns, never "cities you serve": the service area was not measured (P27).
        return f"across {home} and the two closest towns"
    if len(cities) == 2:
        return f"in {home} and {cities[1]}"
    return f"in {home}"


def _normalize_brand(text):
    """Lowercase, & -> and, strip punctuation, collapse whitespace."""
    import re as _re
    t = (text or "").lower()
    t = t.replace("&", "and")
    t = _re.sub(r"[^\w\s]", "", t)
    t = _re.sub(r"\s+", " ", t).strip()
    return t


def _compact(text):
    """Drop all whitespace so 'green wood' and 'greenwood' both match."""
    return "".join((text or "").split())


def _same_business(prospect_name, candidate_name):
    """True when two names look like the same business after normalization.

    Catches cases like 'Mountain View Funeral Home & Cemetery- AZ' vs
    'Mountain View Funeral Home And Cemetery, LLC' that pure lowercase
    substring matching misses.
    """
    pn = _compact(_normalize_brand(prospect_name))
    cn = _compact(_normalize_brand(candidate_name))
    if not pn or not cn:
        return False
    if pn == cn or pn in cn or cn in pn:
        return True
    if len(pn) >= 6 and cn.startswith(pn[:6]):
        return True
    if len(cn) >= 6 and pn.startswith(cn[:6]):
        return True
    return False


# Phase 2.14 follow-up: funeral-industry suffix tokens stripped from both
# sides of a self-match comparison so a prospect named just "Boies Ortega"
# matches an extracted SERP title "Boies-Ortega Funeral Home" (which
# becomes "boiesortega" after the suffix strip). Longest-first order so
# "funeralhomes" wins over "funeral". Deliberately does NOT include
# "family" or generic brand words -- those would create false positives
# between genuinely different businesses.
_FUNERAL_SUFFIX_STRIP = (
    "funeralhomesandcremation",
    "funeralhomeandcremation",
    "mortuariesandcremation",
    "mortuaryandcremation",
    "funeralcremation",
    "funeralservices",
    "funeralservice",
    "memorialchapels",
    "funeralchapels",
    "memorialchapel",
    "memorialhomes",
    "funeralchapel",
    "funeralhomes",
    "memorialhome",
    "memorialpark",
    "funeralhome",
    "mortuaries",
    "cremations",
    "crematory",
    "cremation",
    "mortuary",
    "memorial",
    "chapels",
    "chapel",
    "funeral",
    "corporation",
    "company",
    "corp",
    "group",
    "inc",
    "llc",
    "co",
)


def _strip_funeral_brand_suffix(compacted):
    """Strip one longest-matching funeral-industry suffix from a
    compacted-normalized name. Returns the stripped brand portion, or
    the original string if no suffix matches."""
    if not compacted:
        return compacted
    for suf in _FUNERAL_SUFFIX_STRIP:
        if len(suf) < len(compacted) and compacted.endswith(suf):
            return compacted[: -len(suf)]
    return compacted


def _strip_prospect_dash_suffix(name):
    """Strip a trailing ' - <location>' qualifier from a prospect's Keap
    name so self-match can see past naming-convention suffixes. 99 of
    1236 funeral contacts carry a ' - <City>' tail (e.g. 'Luce Funeral
    Home - Gettysburg') where a SERP title extracts the bare brand
    without the city. Safe to apply because these suffixes follow a
    consistent ' - ' separator and the caller only uses the result as
    a fallback comparison, not a replacement for the original name.
    """
    if not name or " - " not in name:
        return name
    parts = name.rsplit(" - ", 1)
    if len(parts) == 2 and parts[0].strip():
        return parts[0].strip()
    return name


def _self_match_core(prospect_name, candidate_name):
    """Core comparison logic used by _is_prospect_self_match. Separated
    so the caller can run a second pass with a dash-stripped prospect
    name without duplicating the comparison rules."""
    pn = _compact(_normalize_brand(prospect_name))
    cn = _compact(_normalize_brand(candidate_name))
    if not pn or not cn:
        return False
    if pn == cn:
        return True
    pn_brand = _strip_funeral_brand_suffix(pn)
    cn_brand = _strip_funeral_brand_suffix(cn)
    if pn_brand and cn_brand and len(pn_brand) >= 7 and pn_brand == cn_brand:
        return True
    longer, shorter = (pn, cn) if len(pn) >= len(cn) else (cn, pn)
    if longer.startswith(shorter) and len(shorter) >= 0.7 * len(longer):
        return True
    return False


def _is_prospect_self_match(prospect_name, candidate_name):
    """Strict self-match check for Phase 2.12 competitor filtering.

    Unlike _same_business (which is lenient on purpose to keep the
    3-Pack prospect exclusion working even when names differ materially),
    this helper only returns True when one normalized name is a prefix of
    the other AND covers >=70% of the longer name's length. Catches the
    plural / punctuation / trailing-Inc variants this phase targets
    (`Salser & Dillard Funeral Chapels` matching `Salser & Dillard
    Funeral Chapel`) without firing on short common prefixes like
    `chapel` or `family` that would create false positives between
    genuinely different competitors.

    Phase 2.14: additionally, strip funeral-industry suffixes from both
    sides and compare brand-only. Catches cases where the prospect is
    listed in Keap by bare brand ("Boies Ortega") but the extracted SERP
    title carries the full name ("Boies-Ortega Funeral Home"). Without
    the suffix strip, the 70% threshold fails because "Funeral Home"
    doubles the compacted length.

    Phase 2.14 follow-up: second pass with prospect's trailing
    ' - <city>' stripped, so "Luce Funeral Home - Gettysburg" also
    matches "Luce Funeral Home" in a SERP result. 99/1236 funeral
    prospects carry a ' - ' location suffix.

    Bug 5 (2026-05-03): the prefix+70% rule misses prospect names
    where the city/state qualifier is a meaningful suffix. Example:
    "A Better Solution In Home Care of Washington" vs the SERP-
    extracted "A Better Solution In-Home Care" -- the candidate is a
    prefix of the prospect, but only 25/37 = 67.5% of the length.
    Token-set fallback below catches this: 80%+ overlap of non-stop-
    word tokens treats the names as the same business.
    """
    if _self_match_core(prospect_name, candidate_name):
        return True
    stripped = _strip_prospect_dash_suffix(prospect_name)
    if stripped != prospect_name and _self_match_core(stripped, candidate_name):
        return True
    # Bug 5: token-set ratio fallback. Catches partial qualifier
    # variants the prefix rule misses.
    if _token_set_ratio(prospect_name, candidate_name) >= 0.8:
        return True
    return False


# Bug 5: token-set ratio. Used for prospect-self matching when the
# prefix-based check misses a candidate that drops a city/state
# qualifier. Stop-word list deliberately includes geography-implying
# words ("of", "at", "in") plus filler ("the", "a", "and") plus
# entity-form suffixes ("inc", "llc", "co", "corp", "company") so two
# names representing the same business but listed with different
# legal-suffix style still match.
_TOKEN_SET_STOPWORDS = frozenset({
    "a", "an", "the", "of", "and", "in", "on", "at", "for", "to",
    "by", "with", "from",
    "inc", "llc", "co", "corp", "company", "ltd", "limited", "lp",
    "pllc", "pa", "p.a.", "incorporated", "corporation",
})


def _brand_tokens(name):
    """Tokenize a business name for set-overlap comparison.

    Differs from _normalize_brand: hyphens, apostrophes, and slashes
    are turned into spaces FIRST so 'In-Home' tokenizes as ('in',
    'home') and matches 'in home' in another name. Without that, the
    Jaccard ratio between "A Better Solution In-Home Care" and "A
    Better Solution In Home Care of Washington" would only be 0.5
    instead of the 0.8 needed to trigger the prospect-self filter
    (Bug 5)."""
    if not name:
        return set()
    s = (name or "").lower()
    s = s.replace("&", "and")
    # Treat token boundaries explicitly: hyphens, apostrophes, slashes,
    # periods, dots in initials -> space.
    s = _re_module.sub(r"[\-'/\\.]", " ", s)
    # Strip remaining punctuation
    s = _re_module.sub(r"[^\w\s]", "", s)
    s = _re_module.sub(r"\s+", " ", s).strip()
    tokens = [t for t in s.split() if t and t not in _TOKEN_SET_STOPWORDS]
    return set(tokens)


def _token_set_ratio(name_a, name_b):
    """Jaccard similarity between two brand-token sets (intersection /
    union). Returns 0.0 if either side is empty after stopword removal,
    1.0 when the two normalized token-sets are identical."""
    a = _brand_tokens(name_a)
    b = _brand_tokens(name_b)
    if not a or not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union) if union else 0.0


def _canonical_brand_key(name):
    """Build a dedup key for grouping competitor names that point at the
    same business. Used by Bug 5 (canonical SEO competitor dedup) and
    Bug 9 (3-Pack hook winner-by-frequency aggregation).

    Strategy: normalize -> compact -> strip funeral/care industry
    suffixes. Ensures 'Home Instead' and 'Home Instead, Inc' and
    'Home Instead Senior Care' all hash to the same key when used
    for frequency counting."""
    if not name:
        return ""
    s = _strip_brand_symbols(name or "")
    compacted = _compact(_normalize_brand(s))
    if not compacted:
        return ""
    stripped = _strip_funeral_brand_suffix(compacted)
    return stripped or compacted


def _first_name(owner_name, fallback="there"):
    if not owner_name or owner_name.upper() == "NOT FOUND":
        return fallback
    return owner_name.strip().split()[0]


def _setter_name():
    # Placeholder the setter fills in live. Kept as [Setter] so Diego
    # can swap in his own name when he dials.
    return "[Setter]"


def pick_3pack_winner_from_displayed(displayed_per_city, cities):
    """Bug 11 (2026-05-08): pick the 3-Pack hook winner from the same
    per-city competitor lists the card displays, so the hook and the
    'Top 3-Pack Competitors' table can never disagree on who's beating
    the prospect.

    displayed_per_city: dict {city: [name, name, name]} produced by
                        batch_ranking.compute_displayed_3pack_per_city.
                        Names are already prospect-filtered and
                        brand-symbol-stripped.
    cities:             ordered list of cities; controls tiebreak order.

    Selection rule: most-frequent name across all displayed cells.
    Ties broken by first appearance in (city order, position-in-city)
    sequence -- preserves the historical 'first city's first cell'
    semantics when every name appears once.
    """
    from collections import Counter
    counter = Counter()
    first_seen_idx = {}
    display_form = {}
    idx = 0
    for city in cities:
        for name in displayed_per_city.get(city, []) or []:
            if not name:
                continue
            key = _canonical_brand_key(name)
            if not key:
                continue
            counter[key] += 1
            if key not in first_seen_idx:
                first_seen_idx[key] = idx
                display_form[key] = name
            idx += 1
    if not counter:
        return None
    sorted_keys = sorted(
        counter.keys(),
        key=lambda k: (-counter[k], first_seen_idx[k]),
    )
    return _strip_internal_commas_for_hook(display_form[sorted_keys[0]])


def _top_competitor_for_3pack(three_pack_rows, business_name,
                              home_city=None):
    """Return the most-frequent non-prospect competitor across every
    3-Pack row's top_3 list.

    DEPRECATED for production use as of Bug 11 (2026-05-08). The
    primary card pipeline now picks the 3-Pack hook winner via
    pick_3pack_winner_from_displayed() so it's guaranteed to match
    the displayed Top 3-Pack Competitors list. This function is kept
    for: regression tests, ad-hoc diagnostics, and the
    _top_competitor_for_3pack legacy fallback inside build_3pack_hook
    when no winner override is supplied (e.g. unit tests).

    Bug 9 (2026-05-03): the previous implementation picked the first
    non-prospect entry it encountered (typically row 0's first slot,
    which is rank #1 for the home city's primary keyword). That worked
    by accident on cards where the home-city #1 also happened to be
    the most-frequent competitor across the scan, but failed when a
    different brand showed up in more cells.

    New behavior: count occurrences of each canonical brand (Bug 5
    canonical key, so 'Home Instead' and 'Home Instead Senior Care'
    aggregate as the same competitor), then pick the highest count.
    Tiebreaker: the candidate with the lowest (best) rank in the home
    city's rows. Returns the display form of the highest-count entry,
    or None if no non-prospect competitors exist anywhere in the scan.
    """
    from collections import Counter
    counter = Counter()
    display = {}      # canonical_key -> first display form seen
    home_rank = {}    # canonical_key -> best (lowest) rank in home city
    for row in three_pack_rows:
        city = row.get("city")
        for i, entry in enumerate(row.get("top_3", []) or [], 1):
            if not entry:
                continue
            if _is_prospect_self_match(business_name, entry):
                continue
            if _same_business(business_name, entry):
                continue
            key = _canonical_brand_key(entry)
            if not key:
                continue
            counter[key] += 1
            display.setdefault(key, _strip_brand_symbols(entry))
            if home_city and city == home_city:
                cur = home_rank.get(key, 99)
                if i < cur:
                    home_rank[key] = i
    if not counter:
        return None
    sorted_keys = sorted(
        counter.keys(),
        key=lambda k: (-counter[k], home_rank.get(k, 99)),
    )
    # Bug 6 small fix (v3): strip internal commas from the hook winner so
    # 'Home Instead, Home Care Services of Denver' reads naturally when
    # the setter quotes it on a live call.
    return _strip_internal_commas_for_hook(display[sorted_keys[0]])


def _pick_cleanest_competitor(counter, titles, max_candidates=10):
    """Iterate most_common candidates, skipping any whose extracted name
    is a generic page label (Our Staff, About Us, Contact, etc.). Return
    the first non-generic name, or None if no candidates qualify."""
    for host, _count in counter.most_common(max_candidates):
        title = titles.get(host, "")
        name = _extract_competitor_name(title, host)
        if name and not _is_generic_segment(name):
            return name
    return None


def _pick_top_seo_competitors_with_hosts(counter, titles, k=3, max_scan=20,
                                         prospect_city=None,
                                         prospect_state=None,
                                         places_api_key=None,
                                         contact_call_state=None,
                                         per_contact_cap=30):
    """Same as _pick_top_seo_competitors but returns [(name, host), ...]
    so callers (e.g. the SEO hook) can derive the winner's host without
    re-running the tally.

    Bug 11 (2026-05-08): seen_keys.add() is now deferred until the
    candidate has both passed pre-filters and (if applicable) survived
    Places validation. Earlier behavior added the pre-validation key
    immediately, which falsely rejected the candidate when Places'
    canonical name shared the same canonical brand key as the input
    (e.g. 'Crumpler Funeral Home' -> Places canonical 'Crumpler Funeral
    Home' -> key 'crumpler' -> already in seen_keys -> skip). That made
    the displayed top SEO list silently miss the rightful #1 host while
    the SEO hook (which doesn't dedupe) named it -- so card and hook
    disagreed.
    """
    seen_keys = set()
    out = []
    for host, _count in counter.most_common(max_scan):
        title = titles.get(host, "")
        name = _extract_competitor_name(title, host)
        if not name:
            continue
        if _is_generic_segment(name):
            continue
        if _looks_like_page_title_segment(name):
            continue
        key = _canonical_brand_key(name)
        if key in seen_keys:
            continue

        # v3: Places validation gate. When validation passes, prefer
        # Places' canonical displayName for the rendered name -- that
        # truncates page-title noise to the real brand.
        if places_api_key and prospect_state:
            valid, reason, canonical = _validate_seo_candidate_via_places(
                name, prospect_city, prospect_state, places_api_key,
                contact_call_state, per_contact_cap,
            )
            if not valid:
                if contact_call_state is not None:
                    contact_call_state.setdefault("rejected", []).append(
                        (name, host, reason),
                    )
                if reason == "per_contact_cap_reached":
                    break
                continue
            if canonical:
                name = canonical
                new_key = _canonical_brand_key(name)
                if new_key in seen_keys:
                    continue
                key = new_key

        seen_keys.add(key)
        out.append((name, host))
        if len(out) >= k:
            break
    return out


def _pick_top_seo_competitors(counter, titles, k=3, max_scan=20,
                              prospect_city=None, prospect_state=None,
                              places_api_key=None, contact_call_state=None,
                              per_contact_cap=30):
    """Backward-compatible name-only wrapper around
    _pick_top_seo_competitors_with_hosts. Returns up to k display
    names, deduplicated by canonical brand key.

    v3 (Bug 2 refactor, 2026-05-03 evening): each candidate that survives
    pre-filters is validated against Google Places.

    Bug 11 (2026-05-08): the dedupe-key add was moved out of this
    function into _pick_top_seo_competitors_with_hosts, fixing the
    false-skip when Places canonical name shared the input's key.
    """
    return [
        n for n, _h in _pick_top_seo_competitors_with_hosts(
            counter, titles, k=k, max_scan=max_scan,
            prospect_city=prospect_city, prospect_state=prospect_state,
            places_api_key=places_api_key,
            contact_call_state=contact_call_state,
            per_contact_cap=per_contact_cap,
        )
    ]


# v3 Bug 2 refactor (2026-05-03): Places-validation path for SEO
# competitor candidates. Mirrors the 3-Pack validation pattern in
# batch_ranking._validate_competitor_states, but operates on the
# already-extracted display name rather than a raw 3-Pack heading.
#
# Why Places validation is the right layer:
# - regex pre-filters (page-title patterns, generic segments) catch
#   maybe 70% of bad candidates. The other 30% are domain-humanized
#   off-vertical sites, bare vertical nouns, colon-split fragments, and
#   long-adjective titles that look like real brands until you check.
# - Places resolves "Visiting Angels" + "Denver" + "CO" to a real local
#   business and confirms its administrative_area_level_1. A bare
#   "Care" or "Pasadena Photos" returns no match -> drop.
# - cross-state hits are dropped (matches Bug 10 logic for 3-Pack).
def _validate_seo_candidate_via_places(name, prospect_city, prospect_state,
                                       places_api_key,
                                       contact_call_state=None,
                                       per_contact_cap=30):
    """Return (is_valid, reason, canonical_name).

    is_valid=True only when ALL three checks pass:
      1. Places returns a match in prospect_state
      2. Match's displayName has token containment >= 0.5 with the
         candidate (rejects in-state fallbacks like
         "Pasadena Photos" -> "Portrait Space")
      3. (Optional) primaryType / types signal a relevant vertical

    Reasons when False:
        "per_contact_cap_reached" - caller should break the scan loop
        "places_no_match"         - Places returned no business
        "cross-state:XX"          - Places returned a different state
        "weak_name_match:..."     - in-state fallback, name dissimilar
        "places_not_configured"   - missing api_key or state

    canonical_name is Places' displayName when validation passes
    (truncates page-title titles to the real brand: "University Home
    Care & Hospice Owned by a Registered" -> "University Home Care &
    Hospice"). Empty string when validation fails.

    contact_call_state mutates: 'calls' counts cache misses (actual
    API calls billed), used to enforce the per-contact cap. Caller
    seeds with {'calls': 0}.
    """
    if not places_api_key or not prospect_state:
        return False, "places_not_configured", ""

    if (
        contact_call_state is not None
        and contact_call_state.get("calls", 0) >= per_contact_cap
    ):
        return False, "per_contact_cap_reached", ""

    import importlib
    geo_helpers = importlib.import_module("geo_helpers")

    before = geo_helpers.get_places_call_count()
    info = geo_helpers.lookup_place_business(
        name, prospect_city, prospect_state, places_api_key,
        purpose="page_one_candidate")
    after = geo_helpers.get_places_call_count()

    if contact_call_state is not None and after > before:
        contact_call_state["calls"] = (
            contact_call_state.get("calls", 0) + 1
        )

    if info is None:
        return False, "places_no_match", ""

    # Geographic-entity rejection: Places sometimes returns a city,
    # neighborhood, street, or political area when the candidate looked
    # like a location label ("Pasadena CA", "Atlanta GA"). These have
    # types like 'locality', 'political', 'neighborhood' and never a
    # 'health' / 'point_of_interest' marker we'd care about. Drop them
    # outright -- they're not businesses.
    place_types = set(info.get("types") or [])
    geographic_types = {
        "locality", "political", "country",
        "administrative_area_level_1", "administrative_area_level_2",
        "administrative_area_level_3",
        "neighborhood", "sublocality", "sublocality_level_1",
        "natural_feature", "park", "premise", "street_address",
        "route", "intersection", "postal_code",
    }
    if place_types & geographic_types:
        return (
            False,
            f"places_returned_geographic_entity:{sorted(place_types & geographic_types)}",
            "",
        )

    found_state = info.get("state")
    if not found_state:
        return False, "places_no_state", ""
    if not geo_helpers.same_state(found_state, prospect_state):
        return False, f"cross-state:{found_state}", ""

    # Name similarity: containment ratio of intersection / smaller token
    # set. Catches "Pasadena Photos" -> "Portrait Space" (no overlap)
    # while keeping "In-Home Senior Care in Cleveland" -> "Cleveland
    # Home Care" (full overlap of the smaller name).
    display = info.get("displayName", "")
    if not display:
        return False, "no_display_name", ""
    cand_tokens = _brand_tokens(name)
    place_tokens = _brand_tokens(display)
    if not cand_tokens or not place_tokens:
        return False, "empty_tokens", ""
    intersection = cand_tokens & place_tokens
    smaller = min(len(cand_tokens), len(place_tokens))
    containment = len(intersection) / smaller if smaller else 0.0

    # Substring fallback for single-token candidates (typically domain-
    # humanized names that the splitter didn't break apart, e.g.
    # "Homewatchcaregivers" vs Places' "Homewatch CareGivers of
    # Southwest Denver"). If either compacted form contains the other,
    # treat as a match. This rescues franchise-domain extractions
    # without loosening the threshold for multi-token candidates.
    if containment < 0.5:
        cand_compact = _compact(_normalize_brand(name))
        place_compact = _compact(_normalize_brand(display))
        substring_match = (
            len(cand_compact) >= 8 and (
                cand_compact in place_compact
                or place_compact in cand_compact
            )
        )
        if not substring_match:
            return (
                False,
                f"weak_name_match:{display!r}({containment:.2f})",
                "",
            )

    return True, "ok", display


def _strip_internal_commas_for_hook(name):
    """For hook injection: collapse internal commas to spaces and tidy
    whitespace. 'Home Instead, Home Care Services of Denver' becomes
    'Home Instead Home Care Services of Denver'.

    Real "Inc.", "LLC" suffixes typically come in extracted names
    without leading commas. When commas DO appear, they're usually
    nested-clause artifacts ('Brand, Service Description of City')
    that read awkwardly when a setter quotes the name verbatim on a
    live call. Card display keeps the commas (with " | " separating
    competitors); hooks strip them so the spoken sentence flows.
    """
    if not name or "," not in name:
        return name
    s = name.replace(",", " ")
    s = _re_module.sub(r"\s+", " ", s).strip()
    return s


def _top_competitor_for_seo(seo_rows, business_name, domain="", cities=None,
                            prospect_city=None, prospect_state=None,
                            places_api_key=None, contact_call_state=None,
                            per_contact_cap=30):
    """Return a clean business-name string for the most frequent competitor
    domain across organic results. Skips candidates whose extracted name is
    generic (phase 2.4) before falling back to humanized domain.
    """
    name, _host = _top_competitor_for_seo_with_host(
        seo_rows, business_name, domain, cities,
        prospect_city=prospect_city, prospect_state=prospect_state,
        places_api_key=places_api_key,
        contact_call_state=contact_call_state,
        per_contact_cap=per_contact_cap,
    )
    return name


def _top_competitor_for_seo_with_host(seo_rows, business_name, domain="",
                                      cities=None,
                                      prospect_city=None,
                                      prospect_state=None,
                                      places_api_key=None,
                                      contact_call_state=None,
                                      per_contact_cap=30):
    """Same as _top_competitor_for_seo but returns (name, host_domain) so
    callers who need the domain (e.g. to compute rank on a specific
    keyword) don't have to re-run the tally.

    v3 Bug 2 refactor: each candidate is validated via Google Places
    before being returned as the winner. Without a valid match the
    function falls through to the next-most-frequent host.

    The returned name has internal commas stripped (Bug 6 small fix)
    so hook injection reads naturally on a live call.
    """
    counter, titles, _rej, _all = _tally_seo_competitors(
        seo_rows, business_name, domain, cities,
    )
    if not counter:
        return None, None
    for host, _count in counter.most_common(10):
        title = titles.get(host, "")
        name = _extract_competitor_name(title, host)
        if not name:
            continue
        if _is_generic_segment(name):
            continue
        if _looks_like_page_title_segment(name):
            continue
        # v3 Places validation gate -- mirrors _pick_top_seo_competitors
        if places_api_key and prospect_state:
            valid, reason, canonical = _validate_seo_candidate_via_places(
                name, prospect_city, prospect_state, places_api_key,
                contact_call_state, per_contact_cap,
            )
            if not valid:
                if contact_call_state is not None:
                    contact_call_state.setdefault("rejected", []).append(
                        (name, host, reason),
                    )
                if reason == "per_contact_cap_reached":
                    break
                continue
            if canonical:
                name = canonical
        cleaned = _strip_internal_commas_for_hook(_strip_brand_symbols(name))
        return cleaned, host
    return None, None


# --- Phase 2.7: funeral-vertical keyword picker ---------------------------
# The funeral SEO hook quotes one scanned keyword in the "things like X"
# slot of the opening line. Owners preferentially book burial cases and
# react poorly when the example search is cremation-forward, so we prefer
# burial/funeral-neutral phrasing and fall to cremation only as a last
# resort. Within a tier, pick the keyword with the widest prospect-vs-
# winner gap so the hook points at a real weakness.

_FUNERAL_HOOK_KW_TIERS = (
    ("funeral home", ),       # Tier 1: "funeral home [city]" / "...[state]"
    ("funeral services", ),   # Tier 2: "funeral services [city] [state]"
    ("cremation", "cremation services"),  # Tier 3: cremation variants
)


def _keyword_tier(keyword):
    """Classify a keyword into funeral-hook priority tier (0=best, 99=unknown)."""
    if not keyword:
        return 99
    low = keyword.lower().strip()
    for idx, prefixes in enumerate(_FUNERAL_HOOK_KW_TIERS):
        for pref in prefixes:
            if low.startswith(pref + " "):
                # Require whole-word prefix so "cremation services" beats
                # "cremation" when both would match the "cremation" tier
                if pref == "cremation" and "services" in low.split()[:2]:
                    continue
                return idx
    return 99


def _winner_rank_in_row(row, winner_host):
    """Return the winner's rank (1..10) on this SERP row, or None if
    their domain doesn't appear in the top-10 results."""
    if not winner_host:
        return None
    wh = winner_host.lower()
    for r in row.get("results") or []:
        host = (r.get("domain") or "").lower()
        if host and (wh in host or host in wh):
            return r.get("position")
    return None


def _strip_state_suffix(keyword, state):
    """Drop the trailing state abbreviation from a keyword for quoting
    in the hook (so 'funeral home Mesa AZ' reads as 'funeral home Mesa')."""
    if not keyword or not state:
        return keyword
    # Either form may be on the keyword: 'Mesa AZ' or 'Beaverton Oregon'.
    import importlib
    geo = importlib.import_module("geo_helpers")
    code = geo.normalize_state(state)
    forms = {state.strip(), code, geo.US_STATES.get(code, "")} - {""}
    for f in sorted(forms, key=len, reverse=True):
        pat = r"\s+" + _re_module.escape(f) + r"\s*$"
        new = _re_module.sub(pat, "", keyword, flags=_re_module.IGNORECASE).strip()
        if new != keyword.strip():
            return new
    return keyword.strip()


def pick_funeral_hook_keyword(seo_rows, winner_host, prospect_state=""):
    """Pick which scanned keyword to quote in the funeral SEO hook's
    'things like X' slot. See _FUNERAL_HOOK_KW_TIERS for tier order.
    Returns the full keyword string verbatim, or None if seo_rows is
    empty.

    Bug 1 (2026-05-03): the previous version stripped the trailing
    state suffix ("funeral home Mesa AZ" -> "funeral home Mesa") and
    in some non-funeral verticals truncated the vertical noun entirely
    ("home care Stanwood WA" -> "home Stanwood"). Both made hooks
    sound less like a real Google search. New behavior: return the
    keyword exactly as it was scanned.
    """
    if not seo_rows:
        return None

    # Score every row: (tier, gap). Gap = how far prospect is behind winner.
    # gap = (prospect_rank or 11) - (winner_rank or 11); larger = worse
    # for the prospect and better for the hook's "pick a weakness" goal.
    scored = []
    for row in seo_rows:
        if row.get("error"):
            continue  # never quote a keyword whose SERP we failed to fetch
        kw = row.get("keyword") or ""
        tier = _keyword_tier(kw)
        prospect_rank = row.get("rank") or 11
        winner_rank = _winner_rank_in_row(row, winner_host) or 11
        gap = prospect_rank - winner_rank
        scored.append((tier, gap, kw, row))

    # Iterate tiers in priority order. Pick widest gap in the first tier
    # that shows a competitor-beating gap (gap > 0). Fall through otherwise.
    for target in range(len(_FUNERAL_HOOK_KW_TIERS)):
        cands = [s for s in scored if s[0] == target]
        if not cands:
            continue
        cands.sort(key=lambda s: -s[1])  # descending gap
        best_tier, best_gap, best_kw, _ = cands[0]
        if best_gap > 0:
            return best_kw

    # No positive gap anywhere -- fall back to first tier-1 keyword.
    tier1 = [s for s in scored if s[0] == 0]
    if tier1:
        return tier1[0][2]
    # Final fallback: first row's keyword
    return scored[0][2] if scored else None


def pick_hook_example_keyword(seo_rows, winner_host, prospect_state="",
                              home_city="", vertical=""):
    """Bug 1 (2026-05-03): pick the keyword string to quote verbatim in
    the SEO hook for any vertical.

    Behavior:
      - For 'funeral home', delegate to pick_funeral_hook_keyword which
        prefers funeral > funeral services > cremation tier ordering and
        widest prospect-vs-winner gap inside that tier.
      - For other verticals, pick the row whose keyword scans against
        the home city AND has the widest prospect-vs-winner gap. Falls
        back to the first scanned keyword if no rows show a gap.
    """
    if not seo_rows:
        return ""
    if vertical == "funeral home":
        kw = pick_funeral_hook_keyword(seo_rows, winner_host, prospect_state)
        return kw or (seo_rows[0].get("keyword") or "")
    # Non-funeral verticals: prefer home-city rows, widest gap.
    home_lower = (home_city or "").strip().lower()
    home_rows = [
        r for r in seo_rows
        if (r.get("city") or "").strip().lower() == home_lower
    ]
    pool = home_rows if home_rows else seo_rows
    pool = [r for r in pool if not r.get("error")] or pool
    scored = []
    for row in pool:
        if row.get("error"):
            continue  # never quote a keyword whose SERP we failed to fetch
        kw = row.get("keyword") or ""
        prospect_rank = row.get("rank") or 11
        winner_rank = _winner_rank_in_row(row, winner_host) or 11
        gap = prospect_rank - winner_rank
        scored.append((gap, kw))
    scored.sort(key=lambda x: -x[0])
    if scored and scored[0][0] > 0:
        return scored[0][1]
    return pool[0].get("keyword") or seo_rows[0].get("keyword") or ""


def _tally_seo_competitors(seo_rows, business_name, domain="", cities=None):
    """Build the SEO competitor frequency counter. Returns 4-tuple:
        (Counter, titles_by_host, rejected, now_allowed)

    rejected -- list of (title, host, reason) for every result dropped.
    now_allowed -- list of (title, host, url) for results that pass through
                  but would have been rejected under the phase-2.1 broad
                  rules (any Best / Top[N] / What/How/Why/Which start).
                  Used by dry-run QA output to show which titles the
                  carve-outs now let through.
    """
    from collections import Counter
    biz_lower = (business_name or "").lower().strip()
    dom_lower = (domain or "").lower().strip()
    counter = Counter()
    titles = {}  # domain -> first title seen for that domain
    rejected = []
    now_allowed = []
    for row in seo_rows:
        for r in row.get("results", []) or []:
            host = (r.get("domain") or "").lower()
            title = r.get("title") or ""
            url = r.get("url") or ""
            if not host:
                continue
            if dom_lower and dom_lower in host:
                continue
            # Phase 2.12 Fix 1a: HTML-decode the title before the substring
            # check. `Gonzales Funerals &amp; Cremations` used to bypass the
            # prospect-exclusion because `&amp;` vs `&` compared unequal.
            if biz_lower and biz_lower in _decode_entities(title).lower():
                continue
            if _is_foreign_tld(host):
                rejected.append((title, host, "foreign TLD (UK)"))
                continue
            if host in DIRECTORY_DOMAINS:
                rejected.append((title, host, "aggregator domain"))
                continue
            if _is_aggregator_subdomain(host):
                rejected.append((title, host, "news/obituary aggregator subdomain"))
                continue
            if _is_infrastructure_host(host):
                rejected.append((title, host, "infrastructure subdomain"))
                continue
            should_filter, reason = _listicle_verdict(title, url, host, cities)
            if should_filter:
                rejected.append((title, host, reason))
                continue
            # Phase 2.12 Fix 1b: run the extracted competitor name through
            # _is_prospect_self_match() to catch plural / punctuation /
            # abbreviation variants that slip past the title substring
            # check. Stricter than _same_business -- requires one name to
            # be a ~70%+ prefix of the other, so "Salser & Dillard Funeral
            # Chapels" matches "Salser & Dillard Funeral Chapel" but
            # "Chapel Family Funeral Home" does NOT match "Chapel of the
            # Chimes" despite sharing a short common prefix.
            if business_name:
                extracted = _extract_competitor_name(title, host)
                if extracted and _is_prospect_self_match(business_name, extracted):
                    rejected.append(
                        (title, host, "prospect self-match (fuzzy)"),
                    )
                    continue
            # Passes through. Record if it would have been rejected under
            # the phase-2.1 broad rules (Best / Top[N] / question-word prefix).
            if _OLD_BROAD_PATTERN.match(title):
                now_allowed.append((title, host, url))
            counter[host] += 1
            titles.setdefault(host, title)
    return counter, titles, rejected, now_allowed


DIRECTORY_DOMAINS = {
    "yelp.com", "m.yelp.com",
    "bbb.org", "yellowpages.com", "whitepages.com", "manta.com",
    "expertise.com", "threebestrated.com", "angi.com", "angieslist.com",
    "thumbtack.com", "homeadvisor.com", "consumeraffairs.com", "trustpilot.com",
    "care.com", "caring.com", "agingcare.com", "aplaceformom.com", "seniorliving.org",
    "seniorhomes.com", "senioradvisor.com", "helpadvisor.com", "aging.com",
    "medicare.gov", "medicaid.gov", "nih.gov", "hhs.gov", "va.gov",
    "yahoo.com", "mapquest.com", "wikipedia.org", "quora.com",
    "facebook.com", "linkedin.com", "youtube.com", "instagram.com",
    "nextdoor.com", "tripadvisor.com", "foursquare.com",
    # Funeral / cremation aggregators and obituary sites (phase 2.1 additions)
    "legacy.com", "dignitymemorial.com", "everloved.com", "tributearchive.com",
    "ever-loved.com", "forever.com", "funeralocity.com",
    # Phase 2.2 additions -- caught leaking through the question-word /
    # Best-Top[N] carve-outs in the 10-contact QA run:
    #   parting.com / dfsmemorials.com = funeral aggregators
    #   choicemutual.com / onemainfinancial.com = insurance / finance
    #   cremation.green = cremation-info publisher (not a funeral home)
    "parting.com", "dfsmemorials.com", "cremation.green",
    "choicemutual.com", "onemainfinancial.com",
    # Phase 2.10 additions -- obituary/news aggregators surfaced in the
    # 640-contact cache audit. See also _is_aggregator_subdomain() below
    # for subdomain-pattern coverage.
    "tributes.com", "obituary.com", "obits.com",
    # Phase 2.12 addition -- funeralus.com is a "Best 30 Funeral Directors
    # in <City>" directory aggregator. 89 hits across the full cache at
    # Phase 2.11 audit. Not a real competitor.
    "funeralus.com",
    # Phase 2.14 additions -- surfaced on Luce Funeral Home's Gettysburg,
    # SD card after the directory-title filter cleanup. Tiny rural market
    # with thin local competition exposed these two aggregator domains
    # that had been quietly leaking as "competitors":
    #   us-funerals.com (different from funeralus.com) -- national
    #     directory; 163 hits already rejected via national-guide regex
    #     but the plain "Funeral Home Directory" style titles slipped.
    #   selectedfuneralhomes.org -- 87 hits across cache; a paid-
    #     placement funeral-home directory.
    "us-funerals.com", "selectedfuneralhomes.org",
}


# Phase 2.10: news/obituary aggregator subdomain patterns. The cache audit
# found 502 SERP hits across 71 unique `obituaries.<newssite>.com` hosts
# (eagletribune, theadvocate, bangordailynews, etc.) plus a smaller
# `obits.<site>.com` pattern. Treating the prefix alone as aggregator is
# safe -- obituary content on a local funeral home's own subdomain isn't
# why they're a competitor either, and the funeral home's apex domain
# will still be counted via other SERP rows.
def _is_aggregator_subdomain(host):
    """True if the hostname is a newspaper-style or funeral-industry
    obituary aggregator subdomain rather than a funeral home."""
    if not host:
        return False
    h = host.lower()
    if h.startswith("obituaries.") or h.startswith("obits."):
        return True
    return False


# Phase 2.10: infrastructure / DNS-record / CDN hostnames that leak into
# SERP extraction. Example: `_dc-mx.73d6cfb9d0be.coppersix.com` (a DMARC
# subdomain) surfaced as a "competitor" on two cards in the resume run.
# Never a real website, should never be counted or displayed.
_HEX_LABEL_RE = _re_module.compile(r"^[0-9a-f]{10,}$", _re_module.IGNORECASE)


def _is_infrastructure_host(host):
    """True if the hostname looks like DNS-record / CDN / verification
    infrastructure rather than a real website."""
    if not host:
        return False
    h = host.lower()
    labels = h.split(".")
    for lbl in labels:
        if lbl.startswith("_"):
            return True
        if _HEX_LABEL_RE.match(lbl):
            return True
    if h.startswith(("verification.", "static.", "assets.", "cdn.")):
        return True
    if ".cdn." in h:
        return True
    return False


# Foreign TLDs we filter by rule -- this skill serves US prospects only,
# so UK publishers like nafd.org.uk and distinctcremations.co.uk can't be
# a real competitor regardless of title or domain-specific listing.
_FOREIGN_TLD_SUFFIXES = (".co.uk", ".org.uk")


def _is_foreign_tld(host):
    """True if the host sits on a TLD that can't be a US competitor."""
    if not host:
        return False
    h = host.lower()
    return any(h == sfx[1:] or h.endswith(sfx) for sfx in _FOREIGN_TLD_SUFFIXES)


# Listicle / directory / how-to title patterns. If a page title matches any
# of these, the result is usually dropped from the SEO competitor pool
# because the page isn't a real business homepage. Phase 2.2 adds two
# carve-outs (see _listicle_verdict):
#   - Best / Top[N]: pass through if the domain is a real business site
#     and the title mentions one of the prospect's scanned cities. Captures
#     the case where a funeral home publishes its own "Top 10" listicle
#     that still positions them as a competitor in the local market.
#   - Question-word (What/How/Why/Which): only filter if the URL path
#     looks like an article page (/blog/, /articles/, /guides/) or the
#     title is > 60 chars. Short question-style homepage titles on real
#     funeral home domains pass through.
# (_re_module imported at top of file)


def _looks_like_article_page(url):
    """True when the URL path matches a standard article-publisher marker."""
    if not url:
        return False
    u = url.lower()
    return any(m in u for m in ("/blog/", "/articles/", "/guides/"))


def _title_mentions_city(title_lower, cities):
    """True when the title contains one of the scanned city names."""
    if not cities:
        return False
    for c in cities:
        if c and c.lower() in title_lower:
            return True
    return False


def _listicle_verdict(title, url="", host="", cities=None):
    """Return (should_filter: bool, reason: str) for this SERP result.

    Conservative: a title that matches no pattern always passes through.
    """
    if not title:
        return (False, "")
    t = title.lower()

    # Phase 2.13 Fix 1: reject national-guide cost-content titles regardless
    # of URL path or domain. _NATIONAL_GUIDE_REGEX (defined above) already
    # detects "Cost of Cremation in CA", "Cremation Costs near X", etc. for
    # residual counting. Bunch-Roberts Funeral Home's card surfaced
    # "Cremation Costs near Guymon, OK" in a top-3 competitor slot -- not
    # a competitor, a price-shopping article that reads as nonsense when
    # Diego calls it out as a competitor.
    if _NATIONAL_GUIDE_REGEX.search(title):
        return (True, "national-guide cost article")

    # Phase 2.14 Fix 2: directory-location page titles like "Funeral Homes
    # in Gettysburg, South Dakota" -- these are legacy.com / aggregator
    # listing-page titles extracted verbatim when no other generic-segment
    # pattern matches. Luce Funeral Home's card surfaced this as the top
    # competitor. Reject entirely (not just hidden from display) so it
    # doesn't count toward competitor frequency either.
    #
    # Phase 2.14 broaden: state suffix is optional. "Funeral Services in
    # Gettysburg" (no state) is still a directory title -- 20+ contacts
    # had the shorter variant filling a top-3 slot after the state-
    # suffixed variant got filtered. The trailing match is permissive
    # (any word/punct run) because city names can include hyphens,
    # apostrophes, slashes ("California/Greenfield"), and multi-word
    # names ("South Dakota").
    if _re_module.match(
        r"^funeral (homes?|services?) in\s+[\w\-\.\s\'/,]+$",
        t,
    ):
        return (True, "directory page: 'Funeral Homes/Services in [City]'")
    if _re_module.match(
        r"^cremation (services?|providers?) in\s+[\w\-\.\s\'/,]+$",
        t,
    ):
        return (True, "directory page: 'Cremation Services in [City]'")

    # Best / Top[N] -- Option 3 carve-out. Preserve when the domain is a
    # real business site (not in the aggregator list) AND the title names
    # one of the prospect's scanned cities. That catches local funeral
    # homes publishing their own listicle articles.
    if _re_module.match(r"^best\s", t):
        if host and host not in DIRECTORY_DOMAINS and _title_mentions_city(t, cities):
            return (False, "")
        return (True, "starts with 'Best'")
    if _re_module.match(r"^top\s+\d+\b", t):
        if host and host not in DIRECTORY_DOMAINS and _title_mentions_city(t, cities):
            return (False, "")
        return (True, "starts with 'Top [number]'")

    # Question word -- Option 2 carve-out. Only filter when the URL path
    # points to an article/blog/guides page, OR the title is unusually
    # long (>60 chars -- standard homepage titles are shorter).
    if _re_module.match(r"^(what|how|why|which)\b", t):
        # Phase 2.12 Fix 2: cost-guide / "why have a funeral" content
        # articles on real funeral domains slip past the URL-path and
        # 60-char guards. These are always article content regardless
        # of path and regardless of length, so reject unconditionally
        # when the title matches one of these patterns.
        if _re_module.match(
            r"^how much does (a\s+)?(cremation|funeral|burial)(\s+cost)?\b",
            t,
        ):
            return (True, "cost-guide article: 'how much does X cost'")
        if _re_module.match(r"^what you need to know about\b", t):
            return (True, "content article: 'what you need to know about'")
        if _re_module.match(r"^why (we )?have a (funeral|cremation|burial)\b", t):
            return (True, "content article: 'why have a funeral'")
        if _looks_like_article_page(url):
            return (True, "question-word title on article-path URL")
        if len(title) > 60:
            return (True, "question-word title > 60 chars")
        return (False, "")

    # Remaining patterns -- always filter when matched
    if _re_module.search(r"\bnear\s+me\b", t):
        return (True, "contains 'near me'")
    if _re_module.search(r"\bnear\s+you\b", t):
        return (True, "contains 'near you'")
    if _re_module.search(r"\breviews?\s+of\b", t):
        return (True, "contains 'reviews of'")
    if _re_module.search(r"\bcompare\b", t):
        return (True, "contains 'compare'")
    if _re_module.match(r"^find\s+a\s", t):
        return (True, "starts with 'Find a'")
    if _re_module.match(r"^directory\s+of\b", t):
        return (True, "starts with 'Directory of'")
    if _re_module.match(r"^guide\s+to\b", t):
        return (True, "starts with 'Guide to'")

    return (False, "")


_OLD_BROAD_PATTERN = _re_module.compile(
    r"^(best\s|top\s+\d+\b|what\b|how\b|why\b|which\b)",
    _re_module.IGNORECASE,
)


# Atomic words for greedy splitting of concatenated domain names like
# 'angelscremationandburial' -> 'Angels Cremation And Burial'. Only atomic
# words so we don't accidentally split on compounds.
_DOMAIN_WORD_SPLITS = sorted([
    # Funeral / cemetery vocabulary
    "funeral", "home", "homes", "cremation", "burial", "cemetery", "memorial",
    "mortuary", "chapel", "chapels", "crematory", "services", "service",
    "park", "gardens", "niches", "columbarium", "plots",
    # Senior care vocabulary
    "care", "senior", "seniors", "health", "healthcare", "nursing", "hospice",
    "agency", "agencies", "assisted", "living", "helpers", "instead", "angels",
    "keepers", "visiting", "comfort", "always", "family", "caring",
    # Generic connectors
    "at", "of", "for", "and", "the", "my", "your", "our",
], key=len, reverse=True)

_SHORT_PARTICLES = {"at", "of", "my"}


def _greedy_split(token):
    """Split a concatenated lowercase token using the word dictionary. Falls
    back to the original token if no clean split exists."""
    token = (token or "").lower()
    if not token:
        return []
    pieces = []
    i = 0
    n = len(token)
    while i < n:
        matched = None
        for w in _DOMAIN_WORD_SPLITS:
            if w in _SHORT_PARTICLES and (i == 0 or i + len(w) == n):
                # Don't let 'at', 'of', 'my' match at the very start or end
                # unless the rest of the token is a clean split
                continue
            if token.startswith(w, i):
                matched = w
                break
        if matched:
            pieces.append(matched)
            i += len(matched)
        else:
            # No dict word fits here -- bail on splitting this token
            return [token]
    return pieces


# Phase 2.11: right-to-left suffix dictionary for humanizing run-on domain
# SLDs like 'kreidlerfuneralhome' -> 'Kreidler Funeral Home'. The existing
# left-to-right _greedy_split bails when the leading brand word isn't in
# the dictionary, which produced awkward read-aloud names like
# 'Casperfuneralservices' that broke Diego's Jeb Blount flow mid-hook.
#
# Each entry is (suffix_token, display_words). Suffix_token is matched
# greedily against the end of the SLD; display_words is how that suffix
# renders after the split. Sorted by suffix length desc at module init so
# the greedy RTL pass picks the longest match first.
_RTL_SUFFIX_DICT_RAW = (
    # Composite funeral-industry suffixes (user-requested)
    ("familyfuneralservices", ("family", "funeral", "services")),
    ("familyfuneralhomes",    ("family", "funeral", "homes")),
    ("familyfuneralhome",     ("family", "funeral", "home")),
    ("familyfuneral",         ("family", "funeral")),
    ("cremationservices",     ("cremation", "services")),
    ("cremationservice",      ("cremation", "service")),
    ("funeralservices",       ("funeral", "services")),
    ("funeralservice",        ("funeral", "service")),
    ("memorialchapels",       ("memorial", "chapels")),
    ("memorialchapel",        ("memorial", "chapel")),
    ("memorialpark",          ("memorial", "park")),
    ("memorialgardens",       ("memorial", "gardens")),
    ("funeralhomes",          ("funeral", "homes")),
    ("funeralhome",           ("funeral", "home")),
    # Atomic vertical words
    ("mortuaries",            ("mortuaries",)),
    ("cremations",            ("cremations",)),
    ("crematory",             ("crematory",)),
    ("cremation",             ("cremation",)),
    ("mortuary",              ("mortuary",)),
    ("memorial",              ("memorial",)),
    ("services",              ("services",)),
    ("chapels",               ("chapels",)),
    ("funeral",               ("funeral",)),
    ("service",               ("service",)),
    ("chapel",                ("chapel",)),
    ("family",                ("family",)),
    # Generic entity suffixes
    ("corporation",           ("corporation",)),
    ("company",               ("company",)),
    ("group",                 ("group",)),
    ("corp",                  ("corp",)),
    ("inc",                   ("inc",)),
    ("llc",                   ("llc",)),
    ("co",                    ("co",)),
)

_RTL_SUFFIX_DICT = sorted(_RTL_SUFFIX_DICT_RAW, key=lambda e: -len(e[0]))


def _rtl_greedy_split(token):
    """Right-to-left greedy suffix split. Returns a list of word pieces
    (brand first, then split suffix components) or None when no suffix
    in _RTL_SUFFIX_DICT matched. Safeguards:
      - Never consumes the entire token (the brand must have at least
        one character left over) -- otherwise 'funeralhome.com' would
        collapse to no brand at all.
      - Terminates when the remaining brand no longer ends in any dict
        suffix.
    """
    if not token:
        return None
    t = token.lower()
    matched_words = []
    matched_any = False
    while t:
        picked = None
        for suf, words in _RTL_SUFFIX_DICT:
            if len(suf) >= len(t):
                continue  # must leave brand room
            if t.endswith(suf):
                picked = (suf, words)
                break
        if picked is None:
            break
        suf, words = picked
        matched_words = list(words) + matched_words
        t = t[: -len(suf)]
        matched_any = True
    if not matched_any:
        return None
    pieces = []
    if t:
        pieces.append(t)
    pieces.extend(matched_words)
    return pieces


def _humanize_domain(domain):
    import re
    if not domain:
        return ""
    domain = re.sub(r"^https?://", "", domain).strip()
    domain = re.sub(r"^www\.", "", domain)
    host = domain.split("/")[0].split(" ")[0]
    parts = host.split(".")
    sld = parts[-2] if len(parts) >= 2 else parts[0]
    raw_pieces = [p for p in re.split(r"[-_]", sld) if p]
    # Expand each hyphen-delimited piece. Phase 2.11: try RTL suffix split
    # first so brand+funeral-industry-suffix combinations ('kreidler' +
    # 'funeralhome') render cleanly. Fall back to the existing LTR
    # greedy split when RTL finds no known suffix.
    expanded = []
    for p in raw_pieces:
        rtl = _rtl_greedy_split(p)
        if rtl:
            expanded.extend(rtl)
            continue
        expanded.extend(_greedy_split(p) or [p])
    return " ".join(w.capitalize() for w in expanded)


def build_3pack_hook(owner_name, company, vertical, home_city, state,
                    three_pack_rows, cities=None, winner=None):
    """Generate the 3-Pack hook with tiered language (phase 2.3).

    three_pack_rows is now one row per (city, keyword) -- length 4 / 8 / 12
    depending on scan depth. The tier boundaries scale with row count so
    rural home-only scans get "X of 4" phrasing, 2-city gets "X of 8",
    and full 3-city scans get "X of 12".

    winner: when provided, used verbatim as the named competitor in the
            hook. The card pipeline supplies this from
            pick_3pack_winner_from_displayed() so the hook always quotes
            the same #1 entity that the displayed Top 3-Pack Competitors
            table shows (Bug 11, 2026-05-08). When None, falls back to
            the legacy cross-row frequency picker (used by ad-hoc tests
            that don't pre-compute a displayed list).

    Tier logic:
      in_pack == 0                -> "zero"  (any of the N)
      1 <= in_pack, pct < 0.34   -> "few"   (only X of N)
      0.34 <= pct < 0.68          -> "half"  (about half)
      pct >= 0.68                 -> "most"  (most of N, slippage costs Y)
    """
    first = _first_name(owner_name)
    setter = _setter_name()
    brand = VERTICAL_BRAND.get(vertical, "Senior Care Marketing Max")
    vlabel = VERTICAL_LABEL.get(vertical, "care providers")

    if cities is None:
        # Dedupe while preserving order
        seen = set()
        cities = []
        for r in three_pack_rows:
            c = r.get("city")
            if c and c not in seen:
                seen.add(c)
                cities.append(c)

    # Only searches we actually retrieved can be counted. A failed fetch has
    # no rank, so counting it would inflate the denominator and turn "we
    # couldn't scan 6 of 12" into "you rank in none of 12" -- a false claim
    # the setter reads to the prospect as fact.
    # Nor can a search that came back with no map (map_read): nobody can be
    # missing from a map we did not read (Welton 2026-10-21).
    scored_rows = [r for r in three_pack_rows if map_read(r)]
    total = len(scored_rows)
    in_pack = sum(1 for r in scored_rows if r.get("rank"))
    pct = (in_pack / total) if total > 0 else 0.0

    n_cities = len(cities)
    phrase = _scan_phrase(cities)
    family_phrase = (
        "families in your service area" if n_cities > 1
        else f"families in {home_city}"
    )

    if winner is None:
        # Legacy fallback path -- only hit when caller doesn't supply a
        # displayed-list-derived winner (ad-hoc tests, regression rigs).
        # Production callers (batch_ranking.process_contact and
        # regenerate_cards.regenerate_one) always pass winner.
        winner = _top_competitor_for_3pack(
            three_pack_rows, company, home_city=home_city,
        )

    # --- Tiered summary (the "because" statement for the hook) ------------
    if total == 0:
        # Every 3-Pack search in this section FAILED or read no map. We have no
        # measurement, so we make no claim: no hook at all. This used to fall through to
        # WHY_3PACK_NO_WINNER and tell the prospect nobody was in the map.
        return None

    if in_pack == 0:
        # Zero tier
        base = f"you're not in the three-pack for any of the {total} searches I ran"
        if winner:
            # The count, never "showing up in those packs" off one pack of twelve (P23).
            summary = (f"{base}. {winner} is in {n_win} of them"
                       if (n_win := count_3pack_appearances(scored_rows, winner)) else base)
            why = WHY_3PACK.get(vertical, WHY_3PACK["home care"]).format(winner=winner)
        else:
            summary = base
            why = WHY_3PACK_NO_WINNER.get(vertical, WHY_3PACK_NO_WINNER["home care"])
    elif pct < 0.34:
        # Few tier
        base = f"you're only in the three-pack for {in_pack} of {total} searches"
        if winner:
            summary = (f"{base}. {winner} is in {n_win} of them"
                       if (n_win := count_3pack_appearances(scored_rows, winner)) else base)
            why = WHY_3PACK.get(vertical, WHY_3PACK["home care"]).format(winner=winner)
        else:
            summary = base
            why = WHY_3PACK_NO_WINNER.get(vertical, WHY_3PACK_NO_WINNER["home care"])
    elif pct < 0.68:
        # Half tier -- Bug 6: state numerator/denominator literally
        # rather than rounding to "about half" / "the other half".
        missed = total - in_pack
        base = (
            f"you're in the three-pack for {in_pack} of the {total} "
            f"searches I ran, but missing on the other {missed}"
        )
        if winner:
            summary = (f"{base}. {winner} is in {n_win} of them"
                       if (n_win := count_3pack_appearances(scored_rows, winner)) else base)
            why = WHY_3PACK.get(vertical, WHY_3PACK["home care"]).format(winner=winner)
        else:
            summary = base
            why = WHY_3PACK_NO_WINNER.get(vertical, WHY_3PACK_NO_WINNER["home care"])
    else:
        # Most tier (pct >= 0.68). Slippage framing regardless of winner.
        # Bug 6: replace "most of the {total}" with literal {in_pack} of
        # {total} so setters quote real numbers on the call.
        # Name a search we RAN where they are not first, or no line (P21, P22): the old line quoted a keyword
        # never searched ("'live-in'") and claimed slippage without checking a rank below #1. A funeral home's line
        # never leads with cremation when another search will do (rules/prospect-copy.md).
        not_first = [r for r in scored_rows if not r.get("rank") or r["rank"] > 1]
        if not not_first:
            return None
        not_first.sort(key=lambda r: "cremation" in (r.get("keyword") or "").lower())
        r0 = not_first[0]
        where = (f"#{r0['rank']}" if r0.get("rank") else "not in the three-pack")
        summary = (
            f"you're in the three-pack for {in_pack} of the {total} searches I ran, "
            f"but for '{r0['keyword']}' you're {where}"
        )
        why = WHY_3PACK_MOST.get(vertical, "")

    # NEVER SAY NOBODY WHEN THE PROSPECT RANKS (Welton, 2026-09-21). The
    # NO_WINNER line says nobody is in the map. It was also reached when the
    # prospect WAS in the pack but no competitor got named, so a card read
    # "you're in the three-pack for 2 of 7 searches. Right now nobody in your
    # service area is in the map at all." No existing wording fits "you rank,
    # no rival named", so the section gets no hook. One guard here, after
    # every tier, so no branch -- present or future -- can reach it.
    if in_pack >= 1 and not winner and pct < 0.68:
        # (Tested on the rival itself, not on the line's text, since 2026-10-22: several lines are now empty.)
        return None

    # ONLY SAY WHAT WE COUNTED (2026-09-22). Rule 2 first: the named
    # competitor is never the prospect itself.
    if winner and _is_prospect_self_match(company, winner):
        return None
    # The few / about-half tiers name a competitor and claim it is ahead.
    # Count it across every search that worked. The most tier (>= 68%) names
    # no competitor -- it describes the prospect's own position -- and the
    # zero tier (prospect in none) is case a, both left exactly as they were.
    if winner and in_pack >= 1 and pct < 0.68:
        if count_3pack_appearances(scored_rows, winner) > in_pack:
            why = drop_denials(why)          # case b: keep summary, drop denial
        else:
            return None                      # case c: tie or prospect ahead

    reason = (
        f"The reason I'm calling is that I looked at Google's local map "
        f"results for {vlabel} {phrase}, and {summary}."
    )
    intro = f"Hi {first}, this is {setter} with {brand}."
    return " ".join(x for x in (intro, reason, why, CLOSE) if x)


def build_seo_hook(owner_name, company, vertical, home_city, state,
                  seo_rows, domain="", cities=None,
                  places_api_key=None, contact_call_state=None,
                  per_contact_cap=30,
                  winner=None, winner_host=None):
    """Generate the SEO hook. seo_rows is a list of dicts with keys
    {city, keyword, rank, results}. cities is the [home, ...neighbors]
    list used for the scan phrase.

    v3 (2026-05-03): places_api_key + contact_call_state enable Places
    validation of the SEO winner. Same per-contact cap as the SEO
    competitor list to share the per-contact Places budget.

    Bug 11 (2026-05-08): winner + winner_host let the card pipeline
    supply the same #1 host the displayed Top SEO Competitors table
    shows. When provided, the hook quotes 'winner' verbatim and uses
    'winner_host' to pick which scanned keyword to feature (via
    pick_hook_example_keyword). When None, falls back to the legacy
    internal selector (which was the source of the card/hook
    disagreement when the displayed list's dedupe step skipped the
    rightful #1).
    """
    first = _first_name(owner_name)
    setter = _setter_name()
    brand = VERTICAL_BRAND.get(vertical, "Senior Care Marketing Max")
    vlabel = VERTICAL_LABEL.get(vertical, "care providers")

    if cities is None:
        # Dedupe while preserving order
        seen = set()
        cities = []
        for r in seo_rows:
            c = r.get("city")
            if c and c not in seen:
                seen.add(c)
                cities.append(c)

    # Same rule as the 3-Pack hook: a failed fetch is not evidence of absence,
    # so it must not sit in the denominator.
    scored_seo = [r for r in seo_rows if not r.get("error")]
    total = len(scored_seo)
    if total == 0:
        # Every SEO search in this section FAILED. No measurement, no claim:
        # no hook at all. Returned before the winner fallback below so an
        # all-failed section also spends nothing on Places validation. This
        # used to reach the "empty" tier and tell the prospect their
        # competitors weren't on page one either.
        return None
    top3_count = sum(1 for r in scored_seo if r.get("rank") and r["rank"] <= 3)
    page1_count = sum(1 for r in scored_seo if r.get("rank") and r["rank"] <= 10)
    top3_ratio = (top3_count / total) if total else 0.0
    page1_ratio = (page1_count / total) if total else 0.0

    if winner is None:
        # Legacy fallback path -- only hit when caller doesn't supply a
        # displayed-list-derived winner (ad-hoc tests, regression rigs).
        # Production callers always pass winner + winner_host derived
        # from the same compute step that builds the displayed Top SEO
        # Competitors list.
        winner, winner_host = _top_competitor_for_seo_with_host(
            seo_rows, company, domain, cities=cities,
            prospect_city=home_city, prospect_state=state,
            places_api_key=places_api_key,
            contact_call_state=contact_call_state,
            per_contact_cap=per_contact_cap,
        )

    n_cities = len(cities)
    phrase = _scan_phrase(cities)

    # Bug 1 (2026-05-03): always quote the actual scanned keyword
    # verbatim in the hook (e.g. "home care Stanwood WA" rather than
    # the previous truncated "home Stanwood"). Funeral picks by gap +
    # tier; other verticals pick by gap inside the home city.
    example = pick_hook_example_keyword(
        seo_rows, winner_host, prospect_state=state,
        home_city=home_city, vertical=vertical,
    ) or f"{vlabel.split()[0] if vlabel else 'care'} {home_city}"

    # "I ran searches like X", never "the terms families are actually typing": no search volume is measured (P26).
    if n_cities == 1:
        typing_phrase = f"I ran searches like '{example}' in {home_city}"
    else:
        typing_phrase = f"I ran searches like '{example}' {phrase}"
    family_phrase = (
        "families in your service area" if n_cities > 1
        else f"families in {home_city}"
    )

    # Weakest page-1 result by rank (highest rank number) -- used by
    # Dominating tier to name the "gap" search worth defending.
    page1_rows = [r for r in seo_rows if r.get("rank") and r["rank"] <= 10]
    weakest = max(page1_rows, key=lambda r: r["rank"]) if page1_rows else None

    # Phase 2.13 Fix 2: detect the "defending #1 on every keyword" case.
    # Distinct from plain "dominating" because the old dominating-tier
    # wording produced "softest spot at rank 1 -- worth nudging back to
    # #1" when every keyword was already rank 1, which is logical
    # nonsense. When every scanned keyword is rank 1, pivot the hook
    # from "fix what's broken" to "protect what's working + expand".
    all_rank_1 = (
        total > 0
        and all(r.get("rank") == 1 for r in seo_rows)
    )

    # --- Tier classification (phase 2.4) --------------------------------
    if total == 0:
        tier = "empty"
    elif all_rank_1:
        tier = "defending_all_rank_1"
    elif top3_ratio >= 0.68:
        tier = "dominating"
    elif top3_count >= 1 and page1_ratio >= 0.68:
        tier = "mixed"
    elif page1_ratio >= 0.34 and top3_count == 0:
        tier = "weak_page1"
    else:
        tier = "not_page1"

    # --- Tier-specific reason + why-it-matters --------------------------
    if tier == "defending_all_rank_1":
        # Phase 2.13 Fix 2: bespoke hook body -- replaces the standard
        # reason/why/CLOSE seam. Pivot from "fix the gap" to "defend +
        # expand". Names the top competitor so the prospect hears who
        # would pick up the phone if they slip.
        # ONLY SAY WHAT WE COUNTED (2026-09-22): "whoever shows up next ...
        # that's {winner}" names a runner-up nobody counted. The prospect is
        # #1 on every search, so no competitor is ahead (case c for the
        # competitor claim). The rest of this hook only describes the
        # prospect's own measured position and stays. Dropping the clause
        # leaves the existing no-competitor form of the sentence.
        competitor_clause = ""
        # Gone (P28): "at-need calls shift to whoever shows up next" and "the paid and at-need side", said on every
        # vertical and measured on none.
        reason = (
            f"The reason I'm calling is that {typing_phrase}. {company} "
            f"is ranked #1 on every single one of them{competitor_clause}."
        )
        close_variant = (
            "Quick conversation about what you're doing to keep it there? "
            "Tuesday at 10 or Wednesday at 2 -- which works better?"
        )
        intro = f"Hi {first}, this is {setter} with {brand}."
        return f"{intro} {reason} {close_variant}"
    if tier == "dominating":
        if weakest and weakest["rank"] > 3:
            gap = (
                f" The gap is '{weakest['keyword']}', where you're rank "
                f"{weakest['rank']}. That's the one worth defending."
            )
        elif weakest:
            # At least one rank > 1 inside the top 3 -- "softest spot"
            # language is honest here because there's a real slip to
            # name (e.g. rank 3 worth nudging back to 1). When every
            # keyword is rank 1, tier=defending_all_rank_1 fired above.
            gap = (
                f" The softest spot is '{weakest['keyword']}' at rank "
                f"{weakest['rank']} -- still in the pack, but worth "
                f"nudging back to #1."
            )
        else:
            gap = ""
        # Bug 6: name the actual top-3 count rather than "most of"
        # Gone (P29): "this is strong", "ranks 1 through 3 capture the vast majority of clicks", "where the cases
        # quietly walk to a competitor".
        reason = (
            f"The reason I'm calling is that {typing_phrase}. {company} is "
            f"ranked in the top 3 for {top3_count} of the {total} searches I ran.{gap}"
        )
        why = ""
    elif tier == "mixed":
        # "Across the board" at 68% and "rank 4-10 gets a fraction of the clicks" / "where families actually click"
        # are gone (P25, ruling 6): the counts are said as counts.
        reason = (
            f"The reason I'm calling is that {typing_phrase}. {company} is on "
            f"page one for {page1_count} of {total}, but only ranked in the top 3 for "
            f"{top3_count} of {total}."
        )
        why = (
            WHY_SEO.get(vertical, WHY_SEO["home care"]).format(winner=winner)
            if winner else WHY_SEO_NO_WINNER.get(vertical, WHY_SEO_NO_WINNER["home care"])
        )
    elif tier == "weak_page1":
        reason = (
            f"The reason I'm calling is that {typing_phrase}. {company} is on "
            f"page one for {page1_count} of {total} searches, but you're not "
            f"ranked in the top 3 for any of them."
        )
        why = (
            WHY_SEO.get(vertical, WHY_SEO["home care"]).format(winner=winner)
            if winner else WHY_SEO_NO_WINNER.get(vertical, WHY_SEO_NO_WINNER["home care"])
        )
    elif tier == "not_page1":
        if page1_count == 0:
            if winner:
                reason = (
                    f"The reason I'm calling is that {typing_phrase}. {company} "
                    f"didn't appear on page one in any of them. {winner} did."
                )
                why = WHY_SEO.get(vertical, WHY_SEO["home care"]).format(winner=winner)
            else:
                reason = (
                    f"The reason I'm calling is that {typing_phrase}. {company} "
                    f"isn't on page one for any of them."
                )
                why = WHY_SEO_NO_WINNER.get(vertical, WHY_SEO_NO_WINNER["home care"])
        else:
            winner_clause = (
                f" {winner} is on page one for more of them." if winner else ""
            )
            reason = (
                f"The reason I'm calling is that {typing_phrase}. {company} "
                f"only hit page one for {page1_count} of {total} of those "
                f"searches.{winner_clause}"
            )
            why = (
                WHY_SEO.get(vertical, WHY_SEO["home care"]).format(winner=winner)
                if winner else WHY_SEO_NO_WINNER.get(vertical, WHY_SEO_NO_WINNER["home care"])
            )
    else:
        # "empty" is unreachable: total == 0 returns None at the top of this
        # function. This branch used to assert "nobody is on page one" off a
        # section where every search had failed. Raise rather than let any
        # future change route back into a claim we never measured.
        raise AssertionError(
            "build_seo_hook reached the 'empty' tier with total=%d; an "
            "all-failed section must return None before tiering" % total)

    # NEVER SAY NOBODY WHEN THE PROSPECT RANKS (Welton, 2026-09-21). The
    # NO_WINNER line says nobody is on page one. The mixed, weak_page1 and
    # not_page1 tiers all reached it with the prospect ON page one and no
    # rival named. No existing wording fits, so the section gets no hook.
    if page1_count >= 1 and not winner and tier not in ("dominating", "defending_all_rank_1"):
        # (Tested on the rival itself since 2026-10-22, not on the line's text: several lines are now empty.)
        return None

    # ONLY SAY WHAT WE COUNTED (2026-09-22). Rule 2: never name the prospect
    # as its own competitor -- same business name OR same website.
    if winner and (_is_prospect_self_match(company, winner)
                   or (winner_host and domain and same_site(winner_host, domain))):
        return None
    # mixed / weak_page1 / not_page1-with-page-one name a competitor while the
    # prospect IS on page one. Count the competitor's page-one searches across
    # every search that worked. Dominating names no competitor and is left.
    if winner and page1_count >= 1 and tier in ("mixed", "weak_page1", "not_page1"):
        wc = count_seo_appearances(scored_seo, winner_host)
        if wc is not None and wc > page1_count:
            # case b. Keep the counted sentence ("is on page one for more of
            # them"). The mixed / weak_page1 competitor sentences claim
            # something we did NOT count (who holds the top spots, where the
            # clicks go), so they are removed rather than kept.
            for clause in (f" {winner} is where families actually click.",
                           f" {winner} is holding those top spots."):
                reason = reason.replace(clause, "")
            why = drop_denials(why)
        else:
            return None                      # case c: tie, prospect ahead, or uncountable

    # REAL SEO NAMES ONLY (2026-09-22): a page title or a name that is not the
    # site's own is never named. Drop the sentences that name it; the
    # prospect's own count stays.
    if winner and tier in ("mixed", "weak_page1", "not_page1")             and not is_real_seo_name(winner, winner_host):
        reason, why = drop_named_competitor(
            reason, WHY_SEO.get(vertical, WHY_SEO["home care"]), winner)

    intro = f"Hi {first}, this is {setter} with {brand}."
    return " ".join(x for x in (intro, reason, why, CLOSE) if x)
