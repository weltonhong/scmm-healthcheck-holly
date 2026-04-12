"""
PDF Generator - Trade Show Health Check (SCMM brand)

Builds a one-page branded PDF scorecard for the prospect, ready to hand off
at the trade show booth. Saves to OneDrive Desktop.
"""

import datetime
import io
import json as _json
import os
import urllib.request
from pathlib import Path

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
        bar_h = 1.45 * inch
        bar_y = 0.35 * inch
        margin = 0.6 * inch
        bar_w = page_w - 2 * margin

        # Background bar in SCMM logo blue
        self.setFillColor(SCMM_LOGO_BLUE)
        self.rect(margin, bar_y, bar_w, bar_h, fill=1, stroke=0)

        # QR sizing constants
        qr_size = 0.8 * inch
        qr_gap = 0.3 * inch
        qr_right_pad = 0.18 * inch
        text_left_pad = 0.25 * inch

        draw_qr = bool(with_qr and CTAFooterCanvas.qr_png_bytes)

        # Carve out the text area. With QR: leave a strict 0.3" gap to its
        # left edge. Without QR: keep text centered like always.
        if draw_qr:
            text_left = margin + text_left_pad
            text_right = margin + bar_w - qr_right_pad - qr_size - qr_gap
        else:
            text_left = margin + text_left_pad
            text_right = margin + bar_w - text_left_pad

        self.setFillColor(colors.white)

        # Same 4-line content on both layouts so the text never overflows the
        # bar at the long line. Page-with-QR is left-aligned in the narrowed
        # text area; page-without-QR is centered in the same text area
        # (matching the padding on the right so both pages look balanced).
        if draw_qr:
            line1 = ("Helvetica-Bold", 11,
                     "Every week these gaps stay open, your competitors get")
            line2 = ("Helvetica-Bold", 11,
                     "stronger and your phone stays quiet.")
            line3 = ("Helvetica", 10,
                     "We close these gaps for home care agencies like yours.")
            line4 = ("Helvetica-Bold", 13,
                     "Call today.  (888) 383-2848  |  www.SeniorCareMarketingMax.com")
        else:
            line1 = ("Helvetica-Bold", 11,
                     "Every week these gaps stay open, your competitors")
            line2 = ("Helvetica-Bold", 11,
                     "get stronger and your phone stays quiet.")
            line3 = ("Helvetica", 10,
                     "We close these gaps for home care agencies like yours.")
            line4 = ("Helvetica-Bold", 13,
                     "Call today.  (888) 383-2848  |  www.SeniorCareMarketingMax.com")

        lines = [
            (line1[0], line1[1], line1[2], bar_y + bar_h - 22),
            (line2[0], line2[1], line2[2], bar_y + bar_h - 38),
            (line3[0], line3[1], line3[2], bar_y + bar_h - 56),
            (line4[0], line4[1], line4[2], bar_y + 18),
        ]

        text_center_x = (text_left + text_right) / 2
        for font, size, text, y in lines:
            self.setFont(font, size)
            if draw_qr:
                self.drawString(text_left, y, text)
            else:
                self.drawCentredString(text_center_x, y, text)

        # QR code (last page only)
        if draw_qr:
            label_h = 0.22 * inch
            content_h = qr_size + label_h
            qr_x = margin + bar_w - qr_size - qr_right_pad
            qr_y = bar_y + (bar_h - content_h) / 2 + label_h
            try:
                img = ImageReader(io.BytesIO(CTAFooterCanvas.qr_png_bytes))
                self.drawImage(
                    img, qr_x, qr_y,
                    width=qr_size, height=qr_size, mask="auto",
                )
            except Exception:
                pass
            # Two-line label below the QR
            self.setFillColor(colors.white)
            self.setFont("Helvetica-Bold", 7)
            label_cx = qr_x + qr_size / 2
            self.drawCentredString(
                label_cx, qr_y - 9,
                "Scan to schedule your",
            )
            self.drawCentredString(
                label_cx, qr_y - 18,
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


def get_city_population(city, state_abbr):
    """Look up city population from the US Census Bureau (2020 Decennial).
    Free API, no key required. Returns int or None."""
    cache_key = (city.lower().strip(), state_abbr.upper())
    if cache_key in _census_cache:
        return _census_cache[cache_key]

    fips = STATE_FIPS.get(state_abbr.upper())
    if not fips:
        return None
    url = (
        f"https://api.census.gov/data/2020/dec/pl"
        f"?get=P1_001N,NAME&for=place:*&in=state:{fips}"
    )
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=10)
        data = _json.loads(resp.read())
        city_norm = _normalize_place(city)
        matches = []
        for row in data[1:]:
            place_name = row[1].split(",")[0].strip()
            bare = _normalize_place(place_name)
            for suffix in (" city", " town", " village", " cdp", " borough", " municipality"):
                if bare.endswith(suffix):
                    bare = bare[: -len(suffix)].strip()
                    break
            if bare == city_norm:
                matches.append(int(row[0]))
        result = max(matches) if matches else None
        _census_cache[cache_key] = result
        return result
    except Exception:
        return None


def _pop_multiplier(population):
    """Scale the lost-calls estimate by city population.
    Base tier (<100K) = 1.0x. Larger cities get proportionally more."""
    if population is None or population < 100_000:
        return 1.0
    if population < 300_000:
        return 1.5
    if population < 750_000:
        return 2.5
    return 4.0


# ----------------------------- impact estimators -----------------------------


def estimate_lost_calls(results):
    """Heuristic estimate of inquiry calls per month going to competitors,
    scaled by city population so larger markets show larger numbers.

    Base rates per city (scaled by population multiplier):
      - Missing from 3-Pack: +5 to +10 calls * multiplier
      - Competitors running ads, prospect is not: +3 to +6 * multiplier
      - Significant review gap (2x+): +20% on total

    Returns (low, high) integer tuple.
    """
    cities = results.get("cities") or []
    state = results.get("state") or ""
    pack_results = (results.get("3pack") or {}).get("results") or {}
    ads_per_city = results.get("ads") or {}

    low = 0.0
    high = 0.0
    for c in cities:
        pop = get_city_population(c, state)
        mult = _pop_multiplier(pop)
        if not (pack_results.get(c) or {}).get("in_3_pack"):
            low += 5 * mult
            high += 10 * mult
        d = ads_per_city.get(c) or {}
        comps = d.get("competitors_running_ads") or []
        if comps and not d.get("prospect_running_ads"):
            low += 3 * mult
            high += 6 * mult

    # Review gap multiplier
    target = (results.get("google_intel") or {}).get("target") or {}
    target_reviews = target.get("review_count") or 0
    top = results.get("top_competitor") or {}
    comp_reviews = top.get("review_count") or 0
    if comp_reviews >= max(30, target_reviews * 2):
        low *= 1.2
        high *= 1.2

    return int(round(low)), int(round(high))


def count_gaps(results):
    """Count specific actionable gaps for the CTA copy."""
    cities = results.get("cities") or []
    pack_results = (results.get("3pack") or {}).get("results") or {}
    seo = results.get("seo") or {}
    ads_per_city = results.get("ads") or {}

    n = 0
    for c in cities:
        if not (pack_results.get(c) or {}).get("in_3_pack"):
            n += 1
        rank = (seo.get(c) or {}).get("rank")
        if rank is None or rank > 10:
            n += 1
        d = ads_per_city.get(c) or {}
        comps = d.get("competitors_running_ads") or []
        if comps and not d.get("prospect_running_ads"):
            n += 1

    web_checks = (results.get("website") or {}).get("checks") or {}
    n += sum(1 for v in web_checks.values() if v is False)

    if (results.get("review_gap") or 0) >= 30:
        n += 1

    return n


def build_adaptive_hook(results, overall, low, high):
    """Pick the right hook copy based on the overall grade.

    D/F: aggressive lost-calls statement (current behavior).
    B/C: 'winning in home base but missing expansion cities' framing -- the
         pain is missed expansion, not total failure.
    A:   no hook (their grade is the message).
    """
    cities = results.get("cities") or []
    pack_results = (results.get("3pack") or {}).get("results") or {}
    seo = results.get("seo") or {}

    # D / F: aggressive
    if overall in ("D", "F"):
        if high <= 0:
            return None
        return (
            f"{low}-{high} families searched for home care in your service area "
            f"last month and called your competitors instead of you."
        )

    # B / C: winning + missing expansion
    if overall in ("B", "C"):
        winning = []
        losing = []
        for c in cities:
            in_pack = (pack_results.get(c) or {}).get("in_3_pack")
            seo_rank = (seo.get(c) or {}).get("rank")
            in_seo = seo_rank is not None and seo_rank <= 10
            if in_pack or in_seo:
                winning.append(c)
            else:
                losing.append(c)

        if winning and losing:
            win_city = winning[0]
            if len(losing) == 1:
                lose_str = losing[0]
            elif len(losing) == 2:
                lose_str = f"{losing[0]} and {losing[1]}"
            else:
                lose_str = ", ".join(losing[:-1]) + f", and {losing[-1]}"
            return (
                f"You're winning in {win_city}. But families searching in "
                f"{lose_str} are calling your competitors because they can't "
                f"find you there."
            )
        # No clear win/lose split: fall back to a softer aggressive line
        if high > 0:
            return (
                f"{low}-{high} families slipped through to your competitors "
                f"last month. The gaps are fixable."
            )
        return None

    # A: no hook needed -- the grade speaks for itself
    return None


def count_competing_agencies(results):
    """Count unique home care agencies that appeared anywhere in the scan
    (3-Pack lists, ad block advertisers, Places competitor list)."""
    seen = set()
    cities = results.get("cities") or []
    pack_results = (results.get("3pack") or {}).get("results") or {}
    ads_per_city = results.get("ads") or {}

    def norm(name):
        if not name:
            return ""
        return " ".join(name.lower().strip().split())

    for c in cities:
        for name in (pack_results.get(c) or {}).get("top_3", []) or []:
            key = norm(name)
            if key:
                seen.add(key)
        for name in (ads_per_city.get(c) or {}).get("all_advertisers", []) or []:
            key = norm(name)
            if key:
                seen.add(key)

    intel_comps = (results.get("google_intel") or {}).get("competitors") or []
    for c in intel_comps:
        key = norm(c.get("name") or "")
        if key:
            seen.add(key)

    return len(seen)


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
    missing_packs = [
        c for c in cities if not (pack_results.get(c) or {}).get("in_3_pack")
    ]
    if missing_packs:
        target_city = missing_packs[0]
        d = pack_results.get(target_city) or {}
        top_3 = [t for t in (d.get("top_3") or []) if t][:3]
        if top_3:
            comps = ", ".join(top_3)
            score = 100 + len(missing_packs) * 8
            candidates.append((score,
                f"<b>{comps}</b> own the Google Map Pack in {target_city}. When a family "
                f"searches \"home care {target_city}\", those agencies get the call. Your "
                f"name never appears. Every search is a family that picks up the phone and "
                f"dials your competitor instead of you."
            ))

    # ----- Reviews: name the competitor and the gap ---------------------
    rc = target.get("review_count") or 0
    comp_rc = top.get("review_count") or 0
    if comp_rc > 0 and (comp_rc - rc) >= 15:
        comp_name = top.get("name", "your top competitor")
        score = min(99, (comp_rc - rc))
        candidates.append((score,
            f"You have <b>{rc}</b> Google reviews. {comp_name} has <b>{comp_rc}</b>. When two "
            f"agencies show up side by side and one has 3x the proof, families call them "
            f"first and you hear nothing. Every week the gap widens, more inquiries pour into "
            f"their phone and not yours."
        ))

    # ----- Ads: name the advertisers in their home city ------------------
    for c in cities:
        d = ads_per_city.get(c) or {}
        comps = d.get("competitors_running_ads") or []
        if comps and not d.get("prospect_running_ads"):
            names = ", ".join(x["name"] for x in comps[:3])
            score = 75 + len(comps) * 3
            candidates.append((score,
                f"<b>{names}</b> are paying Google to put their phone number above everything "
                f"else when families search for home care in {c}. You are not in that "
                f"auction. Every click on a sponsored result is a family handing their "
                f"inquiry to your competitor before they ever see your name."
            ))
            break

    # ----- SEO Organic --------------------------------------------------
    not_ranking = [
        c for c in cities
        if (seo.get(c) or {}).get("rank") is None
        or ((seo.get(c) or {}).get("rank") or 99) > 10
    ]
    if not_ranking:
        cities_str = ", ".join(not_ranking)
        score = 50 + len(not_ranking) * 5
        candidates.append((score,
            f"Families researching home care in {cities_str} scroll the regular Google "
            f"results and your agency is not on the first page. Every researcher who never "
            f"finds you is a family that hires one of the agencies that does show up."
        ))

    # ----- Website: only the truly painful failures --------------------
    web_checks = web.get("checks") or {}
    psi = web.get("pagespeed_score")
    if psi is not None and psi < 40:
        score = 70
        candidates.append((score,
            f"Your homepage scores <b>{psi}/100</b> on mobile speed. Families on iPhones wait "
            f"five-plus seconds before they see anything and most of them bounce before the "
            f"page loads. Every bounce is an inquiry call you should have answered that you "
            f"never will."
        ))
    elif web_checks.get("google_reviews_widget") is False and rc >= 20:
        score = 45
        candidates.append((score,
            f"Your <b>{rc}</b> Google reviews are nowhere on your homepage. The proof you "
            f"already earned is invisible to every family who lands there, so they bounce to "
            f"the agency whose reviews are right on the screen."
        ))

    # Sort by score (highest first) and return top 2
    candidates.sort(key=lambda x: -x[0])
    if candidates:
        return [text for _, text in candidates[:2]]

    return [
        "Your foundation is strong across reviews, local visibility, and your website. "
        "The agencies in your service area are watching for any opening. Stay ahead by "
        "compounding what is already working before they catch up."
    ]


def build_pdf(results):
    business = results.get("business", "Prospect")
    city = results.get("city", "")
    state = results.get("state", "")
    overall = results.get("overall_grade", "F")
    grades = results.get("all_grades", {})

    today = datetime.date.today().strftime("%B %d, %Y")
    desktop = get_desktop_path()
    desktop.mkdir(parents=True, exist_ok=True)
    fname = f"HealthCheck_{safe_filename(business)}_{datetime.date.today().isoformat()}.pdf"
    out_path = desktop / fname

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=LETTER,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.5 * inch,
        bottomMargin=1.95 * inch,  # leave room for the CTA footer bar (1.45in tall)
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
    )
    body = ParagraphStyle(
        "body", parent=styles["Normal"],
        fontName="Helvetica", fontSize=11, textColor=colors.black,
        leading=14, spaceAfter=6,
    )
    rec_style = ParagraphStyle(
        "rec", parent=body, leftIndent=10, bulletIndent=0, spaceAfter=8,
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
        f"{city}, {state}  |  Scanned {today}",
        h_meta,
    ))

    # THE HOOK -- adaptive based on overall grade.
    # D/F: aggressive "called your competitors instead"
    # B/C: "winning in home base, missing expansion cities"
    # A:   "your foundation is strong, stay ahead"
    low, high = estimate_lost_calls(results)
    hook_text = build_adaptive_hook(results, overall, low, high)
    hook_style = ParagraphStyle(
        "hook", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=16, textColor=SCMM_RED,
        leading=20, alignment=1, spaceAfter=8, spaceBefore=4,
    )
    if hook_text:
        story.append(Paragraph(hook_text, hook_style))

    # Market Snapshot - one-line competitive context above the grade
    competitor_count = count_competing_agencies(results)
    snapshot_style = ParagraphStyle(
        "snapshot", parent=styles["Normal"],
        fontName="Helvetica", fontSize=11, textColor=SCMM_DARK,
        leading=14, spaceAfter=10, alignment=1,
    )
    if competitor_count > 0:
        story.append(Paragraph(
            f"There are <b>{competitor_count}</b> home care agencies competing for "
            f"those families in your service area right now.",
            snapshot_style,
        ))

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
    story.append(Spacer(1, 12))

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
        f"<b>{rc if rc is not None else '-'}</b> reviews, "
        f"<b>{rating if rating is not None else '-'}</b> stars"
    )
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
        if c.get("name") and not _is_self(c.get("name", ""))
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
                    f"{name} ({count} reviews, {rating} stars)"
                )
            else:
                comp_strs.append(f"{name} ({count} reviews)")
        reviews_detail += "<br/><b>Competitors:</b> " + ", ".join(comp_strs)

    pack_results = pack.get("results") or {}

    def pack_status(d):
        if not d or "error" in d:
            return "ERROR"
        top_3 = d.get("top_3") or []
        if not top_3:
            return "No local map pack found for this city"
        top_3_str = ", ".join(top_3[:3])
        if d.get("in_3_pack"):
            return f"FOUND rank {d.get('rank')} (Top 3: {top_3_str})"
        return f"NOT FOUND (Top 3: {top_3_str})"

    pack_lines_html = [
        f"<b>{c}:</b> {pack_status(pack_results.get(c))}" for c in cities
    ]
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
        if not cleaned:
            seo_lines_html.append(
                f"<b>{c}:</b> No organic results found for this city"
            )
            continue
        top_3_str = ", ".join(cleaned)
        if rank is None:
            seo_lines_html.append(
                f"<b>{c}:</b> Not in top 10 (Top 3: {top_3_str})"
            )
        else:
            seo_lines_html.append(
                f"<b>{c}:</b> Rank {rank} (Top 3: {top_3_str})"
            )
    seo_detail = "<br/>".join(seo_lines_html) if seo_lines_html else "No data"

    if web.get("unverified"):
        reason = web.get("unverified_reason") or web.get("error") or "blocked"
        web_detail = f"Unable to verify -- {reason}"
        web_grade_display = "N/A"
    else:
        c = web.get("checks", {})
        psi_score = web.get("pagespeed_score")
        bits = []
        bits.append("Real photos: " + ("Yes" if c.get("real_photos") else "No (stock)"))
        if psi_score is not None:
            bits.append(f"PageSpeed: {psi_score}/100")
        else:
            bits.append("PageSpeed: ?")
        bits.append("Team page: " + ("Yes" if c.get("about_team_page") else "No"))
        bits.append("Blog (6mo): " + ("Yes" if c.get("blog_recent") else "No"))
        bits.append("Intake form: " + ("Yes" if c.get("intake_form") else "No"))
        bits.append("Schema: " + ("Yes" if c.get("localbusiness_schema") else "No"))
        bits.append("Reviews widget: " + ("Yes" if c.get("google_reviews_widget") else "No"))
        web_detail = "  |  ".join(bits)
        web_grade_display = grades.get("website") or "F"

    # ads is {city: {prospect_running_ads, all_advertisers, ...}}
    # Stack each city on its own line and always list ALL advertisers found.
    ads_lines = []
    business_running_anywhere = False
    for c in cities:
        d = ads.get(c) or {}
        if d.get("prospect_running_ads"):
            business_running_anywhere = True
        advs = (d.get("all_advertisers") or [])[:3]
        if advs:
            ads_lines.append(f"<b>{c}:</b> {', '.join(advs)}")
        else:
            ads_lines.append(f"<b>{c}:</b> No ads detected")
    ads_lines.append(
        f"<b>{business}:</b> "
        + ("Running" if business_running_anywhere else "Not running")
    )
    ads_detail = "<br/>".join(ads_lines)

    # Cell style: body text that wraps inside the table cell.
    cell_style = ParagraphStyle(
        "cell", parent=styles["Normal"],
        fontName="Helvetica", fontSize=11, leading=13,
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
        [area("Google Reviews"), grades.get("reviews", "F"), cell(reviews_detail)],
        [area("Google Local Map Rankings"), grades.get("3pack", "F"), cell(pack_detail)],
        [area("Google Organic Rankings (SEO)"), grades.get("seo", "F"), cell(seo_detail)],
        [area("Google Ads"), grades.get("ads", "F"), cell(ads_detail)],
        [area("Website"), web_grade_display, cell(web_detail)],
    ]

    sc = Table(
        rows,
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
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SCMM_LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]
    # Color the grade cells
    for i, row in enumerate(rows[1:], start=1):
        g = row[1]
        style.append(("TEXTCOLOR", (1, i), (1, i), GRADE_COLORS.get(g, SCMM_GRAY)))
    sc.setStyle(TableStyle(style))
    story.append(sc)
    story.append(Spacer(1, 14))

    # Recommendations
    story.append(Paragraph("WHERE YOUR INQUIRY CALLS ARE GOING", h_section))
    for rec in build_recommendations(results):
        story.append(Paragraph(f"&bull; {rec}", rec_style))
    story.append(Spacer(1, 10))

    # No body CTA -- the every-page CTAFooterCanvas carries the offer with
    # the same urgency copy on every page (one banner per page, not two).
    # The QR code is drawn on the LAST page only by the canvas itself.
    try:
        CTAFooterCanvas.qr_png_bytes = generate_qr_png_bytes(CALENDLY_URL)
    except Exception as e:
        print(f"QR generation failed: {e}")
        CTAFooterCanvas.qr_png_bytes = None

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
