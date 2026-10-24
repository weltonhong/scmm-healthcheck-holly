"""
PDF Generator - Trade Show Health Check (SCMM brand)

Builds a one-page branded PDF scorecard for the prospect, ready to hand off
at the trade show booth. Saves to OneDrive Desktop.
"""

import datetime
import io
import os

from pathlib import Path

import headline
import listing_confirm
import ads_words
import ads_records
from xml.sax.saxutils import escape
import measured

import qrcode

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, Image
)
from reportlab.lib.utils import ImageReader


# SCMM brand colors (warm, healthcare-friendly)
SCMM_TEAL = colors.HexColor("#0E7C7B")
SCMM_DARK = colors.HexColor("#1D3557")
SCMM_GRAY = colors.HexColor("#6C757D")
SCMM_LIGHT = colors.HexColor("#F1F5F4")
SCMM_RED = colors.HexColor("#C73E3A")
SCMM_GREEN = colors.HexColor("#2E8B57")
SCMM_AMBER = colors.HexColor("#D89614")
# Brand blue pulled from the SCMM logo (the "SENIOR CARE" wordmark)
SCMM_LOGO_BLUE = colors.HexColor("#29ABE2")

SCMM_LOGO_PATH = (
    "D:/Ring Ring Marketing/Trade Shows - General/Speaking Topics/Logos/"
    "Senior Care Marketing Max Logo/Senior Care Marketing Max - Logo/"
    "JPEG/Low Res/Senior Care Marketing Max - Logo (Colored) - Low Res.jpg"
)

CALENDLY_URL = (
    "https://calendly.com/vickey-lopez/vickeylopezseniormarketingspecialist"
)

# Rep block printed on every page of the CTA footer. Each deploy repo
# overrides REP_NAME, REP_EMAIL, and CALENDLY_URL above to match its
# sales rep. BRAND_LINE stays the same across SCMM deploys.
REP_NAME = "Vickey Lopez"
REP_EMAIL = "Vickey.Lopez@RingRingMarketing.com"
BRAND_LINE = "Senior Care Marketing Max  |  (888) 383-2848"


def generate_qr_png_bytes(url):
    """Build a high-error-correction QR PNG and return its raw bytes."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


GRADE_COLORS = {
    "A": SCMM_GREEN,
    "B": SCMM_GREEN,
    "C": SCMM_AMBER,
    "D": SCMM_RED,
    "F": SCMM_RED,
}


def get_desktop_path():
    """OneDrive Desktop is the real Desktop on this machine."""
    onedrive = Path.home() / "OneDrive" / "Desktop"
    if onedrive.exists():
        return onedrive
    return Path.home() / "Desktop"


def safe_filename(name):
    keep = "-_ "
    cleaned = "".join(c if c.isalnum() or c in keep else "_" for c in name)
    return cleaned.strip().replace(" ", "_")


class CTAFooterCanvas(pdfcanvas.Canvas):
    """Custom canvas that draws a 'Call today' bar across the bottom of every
    page. On the LAST page only, also draws a QR code that links to the
    Calendly scheduling page. Gary Halbert rule: never make them search for
    the offer."""

    qr_png_bytes = None  # populated by build_pdf() before doc.build()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_pages = []

    def showPage(self):
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_pages)
        for idx, page_state in enumerate(self._saved_pages):
            self.__dict__.update(page_state)
            self._draw_footer(with_qr=(idx == total - 1))
            super().showPage()
        super().save()

    def _draw_footer(self, with_qr=False):
        page_w, _ = self._pagesize
        bar_h = 1.85 * inch
        bar_y = 0.35 * inch
        margin = 0.6 * inch
        bar_w = page_w - 2 * margin

        # Background bar in SCMM logo blue
        self.setFillColor(SCMM_LOGO_BLUE)
        self.rect(margin, bar_y, bar_w, bar_h, fill=1, stroke=0)

        qr_size = 0.85 * inch
        qr_gap = 0.3 * inch
        qr_right_pad = 0.2 * inch
        text_left_pad = 0.25 * inch

        draw_qr = bool(with_qr and CTAFooterCanvas.qr_png_bytes)

        if draw_qr:
            text_left = margin + text_left_pad
            text_right = margin + bar_w - qr_right_pad - qr_size - qr_gap
        else:
            text_left = margin + text_left_pad
            text_right = margin + bar_w - text_left_pad

        self.setFillColor(colors.white)

        # 3 tagline lines on top + 3 contact lines on bottom. Same content
        # on both pages so the rep block (name, email, brand) renders on
        # page 1 AND page 2; only the QR is conditional.
        tagline = [
            ("Helvetica-Bold", 11,
             "Every week these gaps stay open, your competitors get"),
            ("Helvetica-Bold", 11,
             "stronger and your phone stays quiet."),
            ("Helvetica", 10,
             "We close these gaps for home care agencies like yours.  Call today."),
        ]
        contact = [
            ("Helvetica-Bold", 11.5, f"{REP_NAME}, Sales Consultant"),
            ("Helvetica", 10, REP_EMAIL),
            ("Helvetica-Bold", 11.5, BRAND_LINE),
        ]

        positions = [
            bar_y + bar_h - 20,   # tagline 1
            bar_y + bar_h - 35,   # tagline 2
            bar_y + bar_h - 51,   # tagline 3
            bar_y + 52,           # contact 1
            bar_y + 35,           # contact 2
            bar_y + 18,           # contact 3
        ]

        all_lines = tagline + contact
        if not getattr(CTAFooterCanvas, "gaps_measured", True):
            # "Every week these gaps stay open" only beside a gap the sheet measured (Welton 2026-10-21).
            all_lines = [(f, z, "") for f, z, _ in tagline[:2]] + all_lines[2:]
        text_center_x = (text_left + text_right) / 2
        for (font, size, text), y in zip(all_lines, positions):
            self.setFont(font, size)
            if draw_qr:
                self.drawString(text_left, y, text)
            else:
                self.drawCentredString(text_center_x, y, text)

        # QR code (last page only). Top-aligned in the right region so it
        # doesn't collide with the contact block on the bottom-left.
        if draw_qr:
            qr_x = margin + bar_w - qr_size - qr_right_pad
            qr_y = bar_y + bar_h - qr_size - 0.18 * inch
            try:
                img = ImageReader(io.BytesIO(CTAFooterCanvas.qr_png_bytes))
                self.drawImage(
                    img, qr_x, qr_y,
                    width=qr_size, height=qr_size, mask="auto",
                )
            except Exception:
                pass
            self.setFillColor(colors.white)
            self.setFont("Helvetica-Bold", 7.5)
            label_cx = qr_x + qr_size / 2
            self.drawCentredString(
                label_cx, qr_y - 10,
                "Scan to schedule your",
            )
            self.drawCentredString(
                label_cx, qr_y - 19,
                "free strategy session",
            )


# ----------------------------- population lookup -----------------------------

STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56",
}

_census_cache = {}


def _normalize_place(s):
    return s.lower().replace(".", "").replace("saint ", "st ").replace("ft ", "fort ").strip()


# ----------------------------- impact estimators -----------------------------


def count_gaps(results):
    """Count specific actionable gaps for the CTA copy."""
    cities = results.get("cities") or []
    pack_results = (results.get("3pack") or {}).get("results") or {}
    seo = results.get("seo") or {}
    ads_per_city = results.get("ads") or {}

    n = 0
    for c in cities:
        pack_c = pack_results.get(c) or {}
        seo_c = seo.get(c) or {}
        # An unscanned city is not a gap.
        if not pack_c.get("error") and not pack_c.get("in_3_pack"):
            n += 1
        if not seo_c.get("error"):
            rank = seo_c.get("rank")
            if rank is None or rank > 10:
                n += 1
        d = ads_per_city.get(c) or {}
        comps = d.get("competitors_running_ads") or []
        if comps and not d.get("prospect_running_ads") and not d.get("prospect_maybe_ad") and not d.get("theirs_unknown"):
            n += 1

    web_checks = (results.get("website") or {}).get("checks") or {}
    n += sum(1 for v in web_checks.values() if v is False)

    if (results.get("review_gap") or 0) >= 30:
        n += 1

    return n


# Map-pack rows carry THREE states, not two, and the difference decides
# whether anything may be said about the prospect.
#
#   UNSCANNED          the fetch failed. Neither a finding nor a non-finding.
#   NO_PACK            Google served no local pack for that search at all.
#                      There is nothing to be absent from, so it is not a gap
#                      and no competitor "owns the map" there.
#   IN_PACK            the prospect is in it.
#   ABSENT_FROM_PACK   a pack exists and the prospect is not in it. The only
#                      one of the four that is a finding about the prospect.
#
# `in_3_pack` alone cannot tell NO_PACK from ABSENT_FROM_PACK: it is False for
# both. Every selector below keys on this function instead.
UNSCANNED = "UNSCANNED"
NO_PACK = "NO_PACK"
IN_PACK = "IN_PACK"
ABSENT_FROM_PACK = "ABSENT_FROM_PACK"
UNCONFIRMED = "UNCONFIRMED"


def pack_status(pack_row):
    """Which of the four states this map-pack row is in."""
    row = pack_row or {}
    if row.get("error"):
        return UNSCANNED
    if row.get("in_3_pack"):
        return IN_PACK
    if row.get("maybe_rank") or row.get("no_id"):
        # A card may be theirs but its place id did not confirm it
        # (scripts/map_identity.py): never a rank, never a miss.
        return UNCONFIRMED
    if not [t for t in (row.get("top_3") or []) if t]:
        # No pack was served. Measured 2026-08-20 across 27 real
        # vertical/market queries: a genuinely packless search did not occur
        # once, so this state is almost always a measurement problem rather
        # than a fact about the market. Either way it is not a gap.
        return NO_PACK
    return ABSENT_FROM_PACK


def build_recommendations(results):
    """Build the 'Where Your Inquiry Calls Are Going' bullets.

    Direct-response style, Gary Halbert rules:
      - No advice, no 'get into the 3-Pack'. Just twist the knife with specifics.
      - Every sentence ends with a consequence about lost calls or revenue.
      - Top 2 pain points only. One message, one action.
      - Score each candidate by punch strength and return the best 2.
    """
    return _build_recommendations_top2(results)


def _build_recommendations_top2(results):
    cities = results.get("cities") or []
    pack_results = (results.get("3pack") or {}).get("results") or {}
    seo = results.get("seo") or {}
    ads_per_city = results.get("ads") or {}
    target = (results.get("google_intel") or {}).get("target") or {}
    top = results.get("top_competitor") or {}
    web = results.get("website") or {}

    # Each candidate is (score, text). Higher score = more painful = more
    # likely to be picked for the final top 2.
    candidates = []

    # ----- 3-Pack: name the competitors that own the map ------------------
    # Unscanned cities are excluded: naming a competitor as owning the map in
    # a city whose SERP never came back is a fabricated finding, and it also
    # inflates the score below.
    # ABSENT_FROM_PACK only, which means every entry is guaranteed to
    # have a top_3 to name. The old list also admitted rows where no
    # pack existed; because the consumer below took [0] and gave up if
    # it had no top_3, a single packless home city SUPPRESSED the whole
    # bullet -- and with it two genuine, nameable gaps in other cities.
    # Both points named; who Google shows, never what a family then does (Welton 2026-10-22).
    mb = measured.map_bullet([(k, pack_results.get(k), (pack_results.get(k) or {}).get("door"),
                               (seo.get(k) or {}).get("query") or "home care %s" % k) for k in cities], 'Families')
    if mb:
        candidates.append(mb)

    # ----- Reviews: name the competitor and the gap ---------------------
    rc = target.get("review_count") or 0
    comp_rc = top.get("review_count") or 0
    if listing_confirm.known(target) and comp_rc > 0 and (comp_rc - rc) >= 15:
        comp_name = top.get("name", "your top competitor")
        score = min(99, (comp_rc - rc))
        candidates.append((score,
            f"You have <b>{rc}</b> Google {measured.reviews_word(rc)}. {comp_name} has <b>{comp_rc}</b>. When two "
            f"agencies show up side by side and one has {comp_rc} {measured.reviews_word(comp_rc)} to your {rc}, families call them "
            f"first and you hear nothing."
        ))

    # Ads are off the sheet (Welton 2026-10-22): no ads bullet and no "open lane".
    # ----- SEO Organic --------------------------------------------------
    not_ranking, points = measured.organic_gaps(cities, seo)
    if not_ranking:
        cities_str = ", ".join(not_ranking)
        score = 50 + len(not_ranking) * 5
        candidates.append((score,
            f"When we searched for home care in {cities_str} {measured.searched_when(results)}, {points}, your agency "
            f"was not on the first page of the regular results."
        ))

    # ----- Website: only the truly painful failures --------------------
    web_checks = web.get("checks") or {}
    psi = web.get("pagespeed_score")
    if psi is not None and psi < 40:
        score = 70
        candidates.append((score,
            f"Google's mobile speed test scored your homepage <b>{measured.speed_text(web)} out of 100</b>. Families on iPhones are left waiting on a page Google scores as slow, and a slow page loses them before it loads."
        ))
    elif web_checks.get("google_reviews_widget") is False and rc >= 20:
        score = 45
        candidates.append((score,
            f"Your <b>{rc}</b> Google {measured.reviews_word(rc)} {'is' if measured.reviews_word(rc) == 'review' else 'are'} nowhere on your homepage. The proof you "
            f"already earned is invisible to every family who lands there, so they bounce to "
            f"the agency whose reviews are right on the screen."
        ))

    # Sort by score (highest first) and return top 2
    candidates.sort(key=lambda x: -x[0])
    if candidates:
        return [text for _, text in candidates[:2]]

    # A sentence about everything needs everything measured; otherwise nothing prints
    # (scripts/measured.py, Welton 2026-10-21).
    if not measured.everything_read(results, cities, listing_confirm.known(target), website_needed=True):
        return []
    return [
        "Your foundation is strong across reviews, local visibility, and your website. "
        "The agencies in your service area are watching for any opening. Stay ahead by "
        "compounding what is already working before they catch up."
    ]


def _web_answer(value, no_text):
    """Yes / the No text / "Couldn't check" (None: the page the check needed could not be read)."""
    if value is None:
        return "Couldn't check"
    return "Yes" if value else no_text


def build_pdf(results):
    business = results.get("business", "Prospect")
    city = results.get("city", "")
    state = results.get("state", "")
    overall = measured.grade_text(results.get("overall_grade"))
    grades = results.get("all_grades", {})

    today = measured.sheet_date_text(results)   # the rep's day, never the server's UTC day
    desktop = get_desktop_path()
    desktop.mkdir(parents=True, exist_ok=True)
    fname = f"HealthCheck_{safe_filename(business)}_{measured.sheet_day(results)[0] or 'undated'}.pdf"
    out_path = desktop / fname

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=LETTER,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.5 * inch,
        bottomMargin=2.2 * inch,  # the 1.85in CTA footer + a 0.35in gap (2.35 until 2026-10-22: one-page sheets spilled onto a second)
        title=f"Online Health Check - {business}",
        author="Senior Care Marketing Max",
    )

    styles = getSampleStyleSheet()
    h_brand = ParagraphStyle(
        "brand", parent=styles["Heading1"],
        fontName="Helvetica-Bold", fontSize=18, textColor=SCMM_TEAL,
        spaceAfter=2,
    )
    h_sub = ParagraphStyle(
        "sub", parent=styles["Normal"],
        fontName="Helvetica", fontSize=10, textColor=SCMM_GRAY,
        spaceAfter=10,
    )
    h_title = ParagraphStyle(
        "title", parent=styles["Heading1"],
        fontName="Helvetica-Bold", fontSize=16, textColor=SCMM_DARK,
        spaceAfter=2,
    )
    h_meta = ParagraphStyle(
        "meta", parent=styles["Normal"],
        fontName="Helvetica", fontSize=9, textColor=SCMM_GRAY,
        spaceAfter=10,
    )
    h_section = ParagraphStyle(
        "section", parent=styles["Heading2"],
        fontName="Helvetica-Bold", fontSize=12, textColor=SCMM_DARK,
        spaceAfter=6, spaceBefore=4,
        keepWithNext=1,  # never left alone at the foot of a page (Welton 2026-10-22: Haven, Home Instead)
    )
    body = ParagraphStyle(
        "body", parent=styles["Normal"],
        fontName="Helvetica", fontSize=11, textColor=colors.black,
        leading=14, spaceAfter=6,
    )
    rec_style = ParagraphStyle(
        "rec", parent=body, leftIndent=10, bulletIndent=0, spaceAfter=8, allowWidows=0,
    )
    cta_style = ParagraphStyle(
        "cta", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=11, textColor=colors.white,
        alignment=1, leading=14,
    )

    story = []

    # SCMM logo above the brand header
    if os.path.exists(SCMM_LOGO_PATH):
        try:
            reader = ImageReader(SCMM_LOGO_PATH)
            iw, ih = reader.getSize()
            target_w = 2.5 * inch
            target_h = target_w * (ih / iw)
            logo = Image(SCMM_LOGO_PATH, width=target_w, height=target_h)
            logo.hAlign = "CENTER"
            story.append(logo)
            story.append(Spacer(1, 6))
        except Exception:
            pass

    # Title block (logo above provides the SCMM branding)
    story.append(Paragraph(f"Online Health Check: {business}", h_title))
    story.append(Paragraph(
        f"{city}, {state}" + (f"  |  Scanned {today}" if today else ""),
        h_meta,
    ))

    # THE HOOK: only what the scan measured (scripts/headline.py; Welton
    # 2026-10-20 dropped the lost-calls estimate, which was not measured).
    hook_text = headline.measured_headline(results, 'Families')
    hook_style = ParagraphStyle(
        "hook", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=16, textColor=SCMM_RED,
        leading=20, alignment=1, spaceAfter=8, spaceBefore=4,
    )
    if hook_text:
        story.append(Paragraph(hook_text, hook_style))

    # Market Snapshot - one-line competitive context above the grade
    # No "There are N ... competing" line (Welton 2026-10-20): the count merged map,
    # ads and Google lists, counted one business spelled two ways twice, and
    # nothing on the sheet showed where it came from (10 on La Paloma's NY run, 11 on NV).

    # Overall grade banner - single full-width cell with label and letter
    # both centered on the page.
    overall_color = GRADE_COLORS.get(overall, SCMM_GRAY)
    banner_label_style = ParagraphStyle(
        "bannerLabel", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=12, textColor=colors.white,
        alignment=1, leading=14, spaceAfter=2,
    )
    banner_letter_style = ParagraphStyle(
        "bannerLetter", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=36, textColor=colors.white,
        alignment=1, leading=38,
    )
    overall_table = Table(
        [[[
            Paragraph("OVERALL GRADE", banner_label_style),
            Paragraph(overall, banner_letter_style),
        ]]],
        colWidths=[7.0 * inch],
    )
    overall_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), overall_color),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(overall_table)
    story.append(Spacer(1, 6))

    # Scorecard table
    target = (results.get("google_intel") or {}).get("target") or {}
    top = results.get("top_competitor") or {}
    pack = results.get("3pack") or {}
    seo = results.get("seo") or {}
    web = results.get("website") or {}
    ads = results.get("ads") or {}
    cities = results.get("cities") or [city]

    rc = target.get("review_count")
    rating = target.get("rating")
    maps_url = target.get("maps_url") or ""
    reviews_detail = (
        f"<b>{rc if rc is not None else 0}</b> {measured.reviews_word(rc if rc is not None else 0)}, "
        f"<b>{rating if rating is not None else '-'}</b> stars"
    ) if listing_confirm.known(target) else listing_confirm.reason(target)
    if maps_url:
        reviews_detail += (
            f'  <a href="{maps_url}" color="#29ABE2">'
            f'<u>View Reviews</u></a>'
        )

    # Show top 3 competitors with review counts, not just top 1.
    intel_comps = (results.get("google_intel") or {}).get("competitors") or []

    def _is_self(name):
        if not name or not business:
            return False
        return (business.lower() in name.lower()
                or name.lower() in business.lower())

    filtered_comps = [
        c for c in intel_comps
        if c.get("name") and not measured.same_listing(c, (results.get("google_intel") or {}).get("target"), business)
    ]
    top_3_comps = sorted(
        filtered_comps,
        key=lambda c: c.get("review_count") or 0,
        reverse=True,
    )[:3]
    if top_3_comps:
        comp_strs = []
        for c in top_3_comps:
            name = c.get("name", "?")
            count = c.get("review_count") or 0
            rating = c.get("rating")
            if rating is not None:
                comp_strs.append(
                    f"{name} ({count} {measured.reviews_word(count)}, {rating} stars)"
                )
            else:
                comp_strs.append(f"{name} ({count} {measured.reviews_word(count)})")
        reviews_detail += "<br/><b>Competitors:</b> " + ", ".join(comp_strs)

    pack_results = pack.get("results") or {}

    def pack_cell(d):
        """The display string for one map-pack row.

        NOT the module-level pack_status, which returns a STATE. Two
        functions of one name in one file, returning different kinds of
        thing, is a trap for the next reader; this one is the renderer.
        """
        if not d or "error" in d:
            return "Couldn't check this search"
        top_3 = d.get("top_3") or []
        if not top_3:
            if d.get("confirmed_empty"):
                return "Google shows no map pack for this search"
            # Not confirmed. Deliberately says nothing about the prospect:
            # a rep reads this row out loud to them.
            return "Map results unconfirmed for this search"
        top_3_str = ", ".join(top_3[:3])
        if d.get("in_3_pack"):
            return f"FOUND rank {d.get('rank')} (Top 3: {top_3_str})"
        if d.get("maybe_rank"):
            return f"Couldn't confirm: #{d.get('maybe_rank')} may be you (Top 3: {top_3_str})"
        if d.get("no_id"):
            return f"Couldn't confirm which card is theirs (Top 3: {top_3_str})"
        return f"NOT FOUND (Top 3: {top_3_str})"

    pack_lines_html = [
        f"<b>{c}:</b> " + escape(measured.map_line(pack_results.get(c), (pack_results.get(c) or {}).get("door"), measured.town_of(c))) for c in cities
    ]
    pack_lines_html += [n for n in [measured.office_note([(pack_results.get(k) or {}).get("door") for k in cities])] if n]
    pack_detail = "<br/>".join(pack_lines_html)

    import re as _re
    def trim_title(t):
        # Decode common HTML entities, then take the brand portion before the
        # first " | ", " - ", " : ", or " * " separator. Require spaces so
        # "In-Home Care" is not torn apart.
        t = (t or "").replace("&amp;", "&").replace("&#39;", "'") \
                     .replace("&quot;", '"').replace("&#x27;", "'")
        short = _re.split(
            r"\s+[\|\u2022:]\s+|\s+-\s+|\s+\u2013\s+", t, maxsplit=1
        )[0].strip()
        return (short or t)[:60]

    seo_lines_html = []
    for c in cities:
        d = seo.get(c) or {}
        rank = d.get("rank")
        top_3 = d.get("top_3") or []
        cleaned = [trim_title(t) for t in top_3[:3] if t]
        if measured.organic_failed(d):
            # The prospect is handed this PDF. A failed fetch must not appear
            # on it as a finding about their rankings.
            seo_lines_html.append(
                f"<b>{c}:</b> " + escape(measured.organic_line(d, d.get("door"), measured.town_of(c))))
            continue
        top_3_str = ", ".join(cleaned)
        # No names to list is not "no organic results" (Welton 2026-10-20): the page was read and the
        # rank stands; scripts/organic_names.py only names real businesses, so the list can be empty.
        top_3_part = f" (Top 3: {top_3_str})" if cleaned else ""
        seo_lines_html.append(f"<b>{c}:</b> " + escape(measured.organic_line(d, d.get("door"), measured.town_of(c))))
    seo_lines_html += [n for n in [measured.office_note([(seo.get(k) or {}).get("door") for k in cities])] if n]
    seo_detail = "<br/>".join(seo_lines_html) if seo_lines_html else "No data"
    # Beside rows that were read, the blank grade is explained in Welton's words (2026-10-24), never a bare N/A.
    seo_not_graded = measured.seo_not_graded(results, grades.get("seo"))
    if seo_not_graded:
        seo_detail = '<font size="8"><i>%s</i></font><br/>%s' % (escape(measured.SEO_NOT_GRADED), seo_detail)

    if web.get("unverified"):
        reason = web.get("unverified_reason") or web.get("error") or "blocked"
        web_detail = reason if reason.startswith("Couldn't check") else f"Couldn't check: {reason}"
        web_grade_display = "N/A"
    else:
        c = web.get("checks", {})
        psi_score = web.get("pagespeed_score")
        bits = []
        bits.append("Real photos: " + _web_answer(c.get("real_photos"), "No (stock)"))
        if psi_score is not None:
            bits.append(f"PageSpeed: {measured.speed_text(web)}/100"
                        + (f" ({len(web['pagespeed_runs'])} tests today)" if web.get("pagespeed_runs") else ""))
        else:
            bits.append("PageSpeed: Couldn't check")
        bits.append("Team page: " + _web_answer(c.get("about_team_page"), "No"))
        bits.append("Blog (6mo): " + _web_answer(c.get("blog_recent"), "No"))
        bits.append("Intake form on homepage: " + _web_answer(c.get("intake_form"), "No"))
        bits.append("Schema: " + _web_answer(c.get("localbusiness_schema"), "No"))
        bits.append("Reviews widget: " + _web_answer(c.get("google_reviews_widget"), "No"))
        web_detail = "  |  ".join(bits)
        web_grade_display = grades.get("website") or "N/A"


    # Cell style: body text that wraps inside the table cell.
    cell_style = ParagraphStyle(
        "cell", parent=styles["Normal"],
        fontName="Helvetica", fontSize=10, leading=12,
        textColor=colors.black,
    )
    area_style = ParagraphStyle(
        "area", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=12, leading=14,
        textColor=colors.black,
    )

    def cell(text):
        return Paragraph(text, cell_style)

    def area(text):
        return Paragraph(text, area_style)

    rows = [
        ["AREA", "GRADE", "DETAILS"],
        [area("Google Reviews"), grades.get("reviews") or "N/A", cell(reviews_detail)],
        [area("Google Local Map Rankings"), measured.grade_text(grades.get("3pack")), cell(pack_detail)],
        [area("Google Organic Rankings (SEO)"), "" if seo_not_graded else measured.grade_text(grades.get("seo")),
         cell(seo_detail)],
        [area("Website"), web_grade_display, cell(web_detail)],
    ]

    # One table row per search line, so a tall section breaks between two searches and the table never breaks
    # after its first row (Welton 2026-10-22: Pacer's page 1 held only Google Reviews, the map row moved whole to
    # page 2). The lines of one section share its background and have no rule between them, so it reads as one row.
    line_rows, section_of = [rows[0]], [0]
    for n, r in enumerate(rows[1:], start=1):
        lines = ({2: pack_detail, 3: seo_detail}.get(n) or "").split("<br/>")
        # The first row carries two searches: beside one, a two-line area name ("Google Organic Rankings (SEO)")
        # opened a gap. A span would fix it too, but a table will not split inside a span.
        lines = ["<br/>".join(lines[:2])] + lines[2:]
        if len(lines) > 1:
            line_rows.append([r[0], r[1], cell(lines[0])])
            line_rows += [["", "", cell(x)] for x in lines[1:]]
        else:
            line_rows.append(r)
        section_of += [n] * (len(line_rows) - len(section_of))
    rows = line_rows

    sc = Table(
        rows,
        repeatRows=1,
        colWidths=[2.0 * inch, 0.7 * inch, 4.3 * inch],
    )
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), SCMM_LOGO_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 11),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("VALIGN", (0, 1), (-1, -1), "TOP"),
        # Grade letters: plain string cells styled by FONTSIZE here.
        ("FONTNAME", (1, 1), (1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (1, 1), (1, -1), 12),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    # Color the grade cells
    for i, row in enumerate(rows[1:], start=1):
        g = row[1]
        style.append(("TEXTCOLOR", (1, i), (1, i), GRADE_COLORS.get(g, SCMM_GRAY)))
    for i in range(1, len(rows)):
        bg = [colors.white, SCMM_LIGHT][(section_of[i] - 1) % 2]
        style.append(("BACKGROUND", (0, i), (-1, i), bg))
        if section_of[i] == section_of[i - 1]:
            style += [("TOPPADDING", (0, i), (-1, i), 0), ("BOTTOMPADDING", (0, i - 1), (-1, i - 1), 0)]
        else:
            style.append(("LINEABOVE", (0, i), (-1, i), 0.5, colors.lightgrey))
    sc.setStyle(TableStyle(style))
    story.append(sc)
    # When the searches ran, once under the table (Welton 2026-10-22).
    story.append(Spacer(1, 3))
    # Google's ad records for their website, one ungraded line in the same note (scripts/ads_records.py,
    # Welton 2026-10-22): a table row pushed one-page sheets onto a second page.
    story.append(Paragraph(escape(measured.searched_line(results)) + "<br/>Google Ads: "
                           + escape(ads_records.line(results.get("ads_records"))), ParagraphStyle(
        "searched", parent=styles["Normal"], fontName="Helvetica-Oblique", fontSize=9, leading=11,
        textColor=colors.black)))
    story.append(Spacer(1, 8))

    # Recommendations
    # Nothing measured to say: no section at all, never a sentence built on a failed search.
    recs = build_recommendations(results)
    CTAFooterCanvas.gaps_measured = bool(recs)
    for i, rec in enumerate(recs):
        # A bullet never splits across two pages, and the heading travels with the first one (Welton 2026-10-22:
        # a line and a half of a bullet sat alone on page 3; the heading alone ended a page).
        story.append(KeepTogether(([Paragraph("WHERE YOUR INQUIRY CALLS ARE GOING", h_section)] if i == 0 else [])
                                  + [Paragraph(f"&bull; {rec}", rec_style)]))
    story.append(Spacer(1, 10))

    # No body CTA -- the every-page CTAFooterCanvas carries the offer with
    # the same urgency copy on every page (one banner per page, not two).
    # The QR code is drawn on the LAST page only by the canvas itself.
    try:
        CTAFooterCanvas.qr_png_bytes = generate_qr_png_bytes(CALENDLY_URL)
    except Exception as e:
        print(f"QR generation failed: {e}")
        CTAFooterCanvas.qr_png_bytes = None

    # A trailing Spacer that does not fit at the foot of the last page starts a page of its own, which then
    # carries only the footer bar (the La Paloma sheet, 2026-10-20: "Page 3 is blank except the footer").
    while story and isinstance(story[-1], Spacer):
        story.pop()
    doc.build(story, canvasmaker=CTAFooterCanvas)
    return str(out_path)


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        print("Usage: python pdf_generator.py <results.json>")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
    print(build_pdf(data))
