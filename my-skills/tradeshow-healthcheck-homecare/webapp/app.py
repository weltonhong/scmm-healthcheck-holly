"""
Online Health Check - Streamlit Web App
Senior Care Marketing Max

Wraps the trade show health check (my-skills/tradeshow-healthcheck-homecare)
into a browser UI. The rep enters business + cities, clicks Run, and watches
the scan unfold live in the page. When the scan finishes, the full scorecard
renders with grades and a Download PDF button.

Reuses the existing scripts directly. The webapp imports run_health_check
from health_check.py and build_pdf from pdf_generator.py without rebuilding
any logic.

Run locally:
    streamlit run app.py

Required env vars (or Streamlit Cloud secrets):
    GOOGLE_API_KEY
    SCRAPINGBEE_API_KEY
"""

import io
import os
import queue
import sys
import tempfile
import threading
import time
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import streamlit as st


# ----------------------------------------------------------------------------
# Path wiring: make the sibling scripts folder importable
# ----------------------------------------------------------------------------

WEBAPP_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = WEBAPP_DIR.parent / "scripts"
ASSETS_DIR = WEBAPP_DIR / "assets"
LOGO_PATH = ASSETS_DIR / "scmm_logo.jpg"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


# ----------------------------------------------------------------------------
# Streamlit secrets -> environment variables
# Streamlit Cloud / Railway pass secrets in different ways. We mirror anything
# in st.secrets into os.environ so the underlying scripts (which read env
# vars directly) pick them up. This must run before importing health_check.
# ----------------------------------------------------------------------------

def _hydrate_env_from_secrets():
    try:
        for key in ("GOOGLE_API_KEY", "SCRAPINGBEE_API_KEY"):
            if not os.environ.get(key):
                val = st.secrets.get(key) if hasattr(st, "secrets") else None
                if val:
                    os.environ[key] = str(val)
    except Exception:
        pass


_hydrate_env_from_secrets()

# Now safe to import the scoring scripts.
# Every booth module is re-read whenever any booth code file changed. Streamlit Cloud puts a push's
# files on disk WITHOUT restarting the app, and Python keeps a module it has already imported. This
# block used to reload five modules, so the rest (the website check among them) ran old code until the
# app restarted: Welton's 4:25 pm La Paloma run, 2026-10-20, had the new address question and the old
# website check. Pinned by tradeshow-healthcheck-homecare/scripts/test_booth_code_reload.py.
import hashlib  # noqa: E402
import importlib  # noqa: E402

_INTEL_DIR = SCRIPTS_DIR.parents[1] / "quick-intel" / "scripts"
_BOOTH_MODULES = ("name_matcher", "pack_identity", "map_identity", "hook_generator", "name_format",
                  "organic_names", "site_reader", "website_audit", "google_intel", "headline", "ads_words", "ads_records", "listing_confirm",
                  "google_serp_rank", "state_check", "sheet_archive", "shared_hosts", "measured", "health_check", "pdf_generator")


def _code_version():
    """A short fingerprint of every booth code file this app runs (shown at the foot of the page)."""
    h = hashlib.sha256()
    for p in sorted(SCRIPTS_DIR.glob("*.py")) + sorted(_INTEL_DIR.glob("google_intel.py")):
        h.update(p.name.encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest()[:8]


CODE_VERSION = _code_version()
import health_check  # noqa: E402
import pdf_generator  # noqa: E402
import state_check  # noqa: E402
import sheet_archive  # noqa: E402
import listing_confirm  # noqa: E402
import site_reader  # noqa: E402  (the moved-address warning, by attribute: reload-safe)
import ads_words  # noqa: E402
import ads_records  # noqa: E402
import measured  # noqa: E402  (organic rows and the search time, by attribute: reload-safe)
if getattr(health_check, "_booth_code_version", None) != CODE_VERSION:
    for _name in _BOOTH_MODULES:
        if _name in sys.modules:
            importlib.reload(sys.modules[_name])
    health_check._booth_code_version = CODE_VERSION


# ----------------------------------------------------------------------------
# PDF generator overrides
# The packaged pdf_generator points SCMM_LOGO_PATH at a Windows-only D:\
# share, and saves to OneDrive Desktop. Both fail in cloud environments.
# Patch them at import time to use the bundled webapp/assets logo and a
# tempdir output path.
# ----------------------------------------------------------------------------

if LOGO_PATH.exists():
    pdf_generator.SCMM_LOGO_PATH = str(LOGO_PATH)

_PDF_TMP_DIR = Path(tempfile.gettempdir()) / "scmm_healthcheck_pdfs"
_PDF_TMP_DIR.mkdir(parents=True, exist_ok=True)
pdf_generator.get_desktop_path = lambda: _PDF_TMP_DIR


# ----------------------------------------------------------------------------
# Live stdout streaming
# health_check.run_health_check writes progress to stdout via print(). We
# want those lines to appear in the page as they happen. Run the scan in a
# background thread, redirect stdout to a tee that pushes lines onto a
# queue, and poll the queue from the main Streamlit thread.
# ----------------------------------------------------------------------------

class _QueueWriter(io.TextIOBase):
    """File-like object that forwards writes onto a thread-safe queue."""

    def __init__(self, q):
        self._q = q
        self._buf = ""

    def write(self, s):
        if not s:
            return 0
        self._buf += s
        # Flush complete lines to the queue immediately so the UI updates
        # as soon as a print() call completes.
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._q.put(line + "\n")
        return len(s)

    def flush(self):
        if self._buf:
            self._q.put(self._buf)
            self._buf = ""


def _run_in_thread(business, cities, state, q, result_box, listing=None, phone="", pin=None):
    writer = _QueueWriter(q)
    try:
        with redirect_stdout(writer), redirect_stderr(writer):
            results = health_check.run_health_check(business, cities, state, listing=listing, phone=phone, pin=pin)
        writer.flush()
        result_box["results"] = results
    except Exception as e:
        writer.flush()
        result_box["error"] = str(e)
    finally:
        q.put(None)  # sentinel


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------

SCMM_TEAL = "#0E7C7B"
SCMM_BLUE = "#29ABE2"
SCMM_DARK = "#1D3557"
SCMM_GRAY = "#6C757D"
SCMM_LIGHT = "#F1F5F4"

st.set_page_config(
    page_title="Online Health Check | Senior Care Marketing Max",
    page_icon="🩺",
    layout="centered",
)

# Brand CSS to match the PDF palette
st.markdown(
    f"""
    <style>
      .block-container {{ padding-top: 2rem; max-width: 880px; }}
      h1.scmm-title {{
        color: {SCMM_DARK};
        font-weight: 700;
        font-size: 2.1rem;
        margin: 0.6rem 0 0.2rem 0;
        text-align: center;
      }}
      .scmm-sub {{
        color: {SCMM_GRAY};
        text-align: center;
        margin-bottom: 1.5rem;
      }}
      .stButton > button[kind="primary"] {{
        background-color: {SCMM_TEAL};
        border-color: {SCMM_TEAL};
        color: white;
        font-weight: 700;
        font-size: 1.05rem;
        padding: 0.65rem 1.5rem;
      }}
      .stButton > button[kind="primary"]:hover {{
        background-color: {SCMM_BLUE};
        border-color: {SCMM_BLUE};
      }}
      .scmm-card {{
        background: {SCMM_LIGHT};
        border-left: 5px solid {SCMM_TEAL};
        padding: 1rem 1.2rem;
        border-radius: 6px;
        margin: 0.6rem 0;
      }}
      .grade-badge {{
        display: inline-block;
        padding: 0.15rem 0.6rem;
        border-radius: 4px;
        color: white;
        font-weight: 700;
        font-size: 0.95rem;
      }}
      .g-A, .g-B {{ background: #2E8B57; }}
      .g-C {{ background: #D89614; }}
      .g-D, .g-F {{ background: #C73E3A; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# Logo + header
if LOGO_PATH.exists():
    cols = st.columns([1, 2, 1])
    with cols[1]:
        st.image(str(LOGO_PATH), use_container_width=True)

st.markdown("<h1 class='scmm-title'>Online Health Check</h1>", unsafe_allow_html=True)
st.markdown(
    "<div class='scmm-sub'>A 60-second snapshot of how the prospect shows up online.</div>",
    unsafe_allow_html=True,
)

# US states for dropdown
US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
]

with st.form("health_check_form", clear_on_submit=False):
    business = st.text_input("Business Name", placeholder="e.g., Comfort Keepers")
    home_city = st.text_input("Home City", placeholder="e.g., Tampa")
    state = st.selectbox("State", US_STATES, index=None, placeholder="Choose the business's state")
    second_city = st.text_input("Second City (optional)", placeholder="leave blank to skip")
    third_city = st.text_input("Third City (optional)", placeholder="leave blank to skip")
    # Ask them for it (Welton 2026-10-29): it confirms their own Google listing, which the review gap needs.
    phone = st.text_input("Their Phone (ask them)", placeholder="e.g., 417-581-1234")
    submitted = st.form_submit_button("Run Health Check", type="primary")


# Reset state when a new submission comes in
if submitted:
    st.session_state["scan_started"] = True
    st.session_state["scan_done"] = False
    st.session_state["results"] = None
    st.session_state["error"] = None
    st.session_state["log_text"] = ""
    st.session_state["pdf_bytes"] = None  # never hand the next prospect the last sheet
    st.session_state["archive_done"] = False
    st.session_state["archive_note"] = None
    st.session_state["listing_lookup"] = None   # one Google lookup per scan
    st.session_state["listing_pin"] = None      # where that lookup was pinned (scripts/state_check.py town_pin)
    st.session_state["listing_answer"] = None   # "Is this your address?" not asked yet
    st.session_state["form_values"] = {
        "business": business.strip(),
        "home_city": home_city.strip(),
        "state": (state or "").strip(),
        "second_city": second_city.strip(),
        "third_city": third_city.strip(),
        "phone": phone.strip(),
    }


def _validate(values):
    missing = []
    for label, key in [
        ("Business Name", "business"),
        ("Home City", "home_city"),
        ("State", "state"),
    ]:
        if not values.get(key):
            missing.append(label)
    return missing


def _listing_lookup(values):
    """The business's own Google listings, looked up once per scan (the state check and the question share it)."""
    if st.session_state.get("listing_lookup") is None:
        # Pinned to the town the rep typed (Welton 2026-10-29: words alone are answered by where the server is);
        # the scan reuses the same pin, carried in st.session_state["listing_pin"].
        pin = {}
        st.session_state["listing_lookup"] = state_check.check_listing_state(
            values["business"], values["home_city"], values["state"],
            os.environ.get("GOOGLE_API_KEY"), locate=state_check.town_lookup, pin_out=pin)
        st.session_state["listing_pin"] = pin
    return st.session_state["listing_lookup"]


def _state_refusal(values):
    """The refusal text when the chosen state contradicts the business's own Google listing.

    See scripts/state_check.py (Welton, 2026-10-20: the La Paloma sheet was
    measured in New York because the dropdown came preset). None means scan.
    """
    verdict, listings = _listing_lookup(values)
    if verdict == state_check.STATE_MISMATCH:
        return state_check.mismatch_message(values["business"], values["state"], listings)
    return None


def _listing_answer(values):
    """Ask "Is this your address?" and return the listing to scan with (scripts/listing_confirm.py).

    Welton, 2026-10-20: the rep turns and asks the owner. No, None of these, or no answer
    within the wait all mean the same: nothing is taken from Google's guess.
    """
    answer = st.session_state.get("listing_answer")
    if answer is not None:
        return answer
    verdict, listings = _listing_lookup(values)
    found = [l for l in listings if l.get("state") == values["state"]] if verdict == state_check.STATE_OK else []
    if not found:
        st.session_state["listing_answer"] = listing_confirm.not_confirmed(listing_confirm.NOT_FOUND)
        return st.session_state["listing_answer"]

    holder = st.empty()
    picked = None
    with holder.container(border=True):
        if len(found) == 1:
            st.markdown("### Is this your address?")
            st.markdown("**%s**" % found[0].get("address", ""))
            st.caption("Google lists %s there." % found[0].get("name", values["business"]))
            if measured.closed_word(found[0]):   # Google's own flag, in Google's words (Welton 2026-10-28)
                st.markdown("**%s**" % measured.closed_confirm(measured.closed_word(found[0])))
            yes, no = st.columns(2)
            if yes.button("Yes", key="listing_pick_0", type="primary", use_container_width=True):
                picked = found[0]
            if no.button("No", key="listing_none", use_container_width=True):
                picked = listing_confirm.not_confirmed(listing_confirm.SAID_NO)
        else:
            st.markdown("### Which one is your address?")
            for i, l in enumerate(found):
                closed = measured.closed_word(l)
                label = l.get("address", "") + (" (%s)" % measured.closed_confirm(closed)[:-1] if closed else "")
                if st.button(label, key="listing_pick_%d" % i, use_container_width=True):
                    picked = l
            if st.button("None of these", key="listing_none", use_container_width=True):
                picked = listing_confirm.not_confirmed(listing_confirm.SAID_NO)
        clock = st.empty()
    if picked is None:
        if listing_confirm.wait_seconds() == 0:
            st.stop()   # screen tests only: wait for the click, no timer
        for left in range(listing_confirm.wait_seconds(), 0, -1):
            clock.caption("Ask the owner. The scan starts in %d seconds either way." % left)
            time.sleep(1)
        picked = listing_confirm.not_confirmed(listing_confirm.NO_ANSWER)
    holder.empty()
    st.session_state["listing_answer"] = picked
    return picked


# ----------------------------------------------------------------------------
# Run the scan (synchronous from Streamlit's POV but with live polling)
# ----------------------------------------------------------------------------

if st.session_state.get("scan_started") and not st.session_state.get("scan_done"):
    values = st.session_state["form_values"]
    missing = _validate(values)
    if missing:
        st.error("Missing required field(s): " + ", ".join(missing))
        st.session_state["scan_started"] = False
    elif not os.environ.get("GOOGLE_API_KEY"):
        st.error(
            "GOOGLE_API_KEY is not set. Add it to Streamlit Cloud secrets or "
            "your environment and reload."
        )
        st.session_state["scan_started"] = False
    elif (refusal := _state_refusal(values)):
        st.error(refusal)
        st.session_state["scan_started"] = False
    else:
        listing = _listing_answer(values)
        cities = [values["home_city"]]
        if values["second_city"]:
            cities.append(values["second_city"])
        if values["third_city"]:
            cities.append(values["third_city"])

        st.markdown("### Live scan")
        progress_box = st.empty()
        spinner_box = st.empty()

        q = queue.Queue()
        result_box = {}
        worker = threading.Thread(
            target=_run_in_thread,
            args=(values["business"], cities, values["state"], q, result_box, listing, values.get("phone", ""),
                  st.session_state.get("listing_pin")),
            daemon=True,
        )
        worker.start()

        log_lines = []
        spinner_box.info("Scanning... reviews, 3-Pack, SEO, website running in parallel.")

        while True:
            try:
                item = q.get(timeout=0.4)
            except queue.Empty:
                if not worker.is_alive():
                    break
                continue
            if item is None:
                break
            log_lines.append(item.rstrip("\n"))
            progress_box.code("\n".join(log_lines), language="text")

        worker.join(timeout=2)
        spinner_box.empty()

        st.session_state["log_text"] = "\n".join(log_lines)
        st.session_state["results"] = result_box.get("results")
        st.session_state["error"] = result_box.get("error")
        st.session_state["scan_done"] = True


# ----------------------------------------------------------------------------
# Render the scorecard + PDF download once the scan is done
# ----------------------------------------------------------------------------

if st.session_state.get("scan_done"):
    err = st.session_state.get("error")
    if err:
        st.error(f"Scan failed: {err}")

    results = st.session_state.get("results")
    if results:
        # Why the reviews read "couldn't check", for the rep (a timeout is worth a re-run).
        note = listing_confirm.rep_note((results.get("google_intel") or {}).get("target"))
        if note:
            st.warning(note)
        if not st.session_state.get("error"):
            # Re-render the captured terminal log so the user can scroll it
            with st.expander("Live scan log", expanded=False):
                st.code(st.session_state.get("log_text", ""), language="text")

        st.markdown("---")
        st.markdown("## Scorecard")

        biz = results.get("business", "")
        cities_run = results.get("cities", [])
        state_run = results.get("state", "")
        st.markdown(
            f"**{biz}** &nbsp;|&nbsp; {', '.join(cities_run)}, {state_run}"
            if biz else "",
            unsafe_allow_html=True,
        )

        overall = results.get("overall_grade") or "N/A"
        closed = measured.listing_closed(results)   # no letter for a listing Google marks closed
        if closed:
            overall = measured.closed_overall(closed)
        st.markdown(
            f"<div class='scmm-card'>"
            f"<div style='font-size:0.9rem;color:{SCMM_GRAY};text-transform:uppercase;letter-spacing:0.05em;'>Overall Grade</div>"
            f"<div style='font-size:{'1.2rem' if closed else '3rem'};font-weight:800;color:{SCMM_DARK};line-height:{'1.2' if closed else '1'};'>{overall}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        grades = results.get("all_grades", {})
        labels = {
            "reviews": "Google Reviews",
            "3pack": "Google 3-Pack",
            "seo": "Google SEO",
            "ads": "Google Ads",
            "website": "Website",
        }
        rows_html = []
        for key in ("reviews", "3pack", "seo", "ads", "website"):
            g = grades.get(key)
            badge = (
                f"<span class='grade-badge g-{g}'>{g}</span>"
                if g else
                "<span style='color:#6C757D;font-style:italic;'>%s</span>" % (
                    measured.closed_not_graded(measured.listing_closed(results))
                    if key in ("reviews", "3pack") and measured.listing_closed(results)
                    else measured.SEO_NOT_GRADED if key == "seo" and measured.seo_not_graded(results, g) else "N/A")
            )
            rows_html.append(
                f"<tr><td style='padding:0.5rem 0.9rem;border-bottom:1px solid #e6e6e6;'>{labels[key]}</td>"
                f"<td style='padding:0.5rem 0.9rem;border-bottom:1px solid #e6e6e6;text-align:right;'>{badge}</td></tr>"
            )
        st.markdown(
            "<table style='width:100%;border-collapse:collapse;margin-top:0.5rem;'>"
            + "".join(rows_html)
            + "</table>",
            unsafe_allow_html=True,
        )

        # Per-section detail
        with st.expander("Reviews", expanded=False):
            tgt = (results.get("google_intel") or {}).get("target") or {}
            comp = results.get("top_competitor") or {}
            st.write(f"**Target:** {tgt.get('review_count') or 0} {measured.reviews_word(tgt.get('review_count') or 0)}, {tgt.get('rating', '-')} stars"
                     if listing_confirm.known(tgt) and not measured.closed_word(tgt) else "**Target:** " + (
                         measured.closed_reviews_detail(tgt, measured.closed_word(tgt)) if measured.closed_word(tgt)
                         else listing_confirm.reason(tgt)))
            if comp:
                st.write(
                    f"**Most-reviewed nearby listing:** {comp.get('name', '?')}: "
                    f"{comp.get('review_count', 0)} {measured.reviews_word(comp.get('review_count', 0))}, "
                    f"{comp.get('rating', '-')} stars"
                )
                gap = results.get("review_gap")
                if gap:
                    st.write(f"**Review gap:** {gap} {measured.reviews_word(gap)} behind")
            else:
                st.write("**Most-reviewed nearby listing:** " + measured.no_rival_line(results.get("google_intel")))

        with st.expander("Google 3-Pack", expanded=False):
            # Both points named, the same lines as the PDF (measured.map_line, Welton 2026-10-22).
            pack_rows = (results.get("3pack") or {}).get("results") or {}
            for key, d in pack_rows.items():
                closed = measured.listing_closed(results)
                st.write(f"**{key}:** " + (measured.closed_map_line(d, (d or {}).get("door"), measured.town_of(key), closed)
                                           if closed else measured.map_line(d, (d or {}).get("door"), measured.town_of(key))))
            note = measured.office_note([(d or {}).get("door") for d in pack_rows.values()])
            if note:
                st.write(note)

        with st.expander("Google SEO", expanded=False):
            # Page one or not, from both points, never a number (measured.organic_line, Welton 2026-10-22).
            seo_rows = results.get("seo") or {}
            for key, d in seo_rows.items():
                st.write(f"**{key}:** " + measured.organic_line(d, (d or {}).get("door"), measured.town_of(key)))
            note = measured.office_note([(d or {}).get("door") for d in seo_rows.values()])
            if note:
                st.write(note)
            st.caption(measured.searched_line(results))

        with st.expander("Google Ads", expanded=False):
            st.write(ads_records.line(results.get("ads_records")))

        with st.expander("Website", expanded=False):
            web = results.get("website") or {}
            if web.get("unverified") and site_reader.moved_note(web):
                st.warning("%s %s" % (site_reader.moved_note(web), site_reader.MOVED_ASK))
            elif web.get("unverified"):
                st.write(web.get('unverified_reason') if str(web.get('unverified_reason', '')).startswith("Couldn't check") else f"Couldn't check: {web.get('unverified_reason', 'blocked')}")
            else:
                checks = web.get("checks") or {}
                psi = web.get("pagespeed_score")
                psi_txt = f"{measured.speed_text(web)}/100" if psi is not None else "Unable to test"
                st.write(f"- PageSpeed mobile: {psi_txt}")
                for k, label in [
                    ("real_photos", "Real team photos"),
                    ("about_team_page", "About / Team page"),
                    ("blog_recent", "Recent blog (6 mo)"),
                    ("intake_form", "Intake form on homepage"),
                    ("localbusiness_schema", "LocalBusiness schema"),
                    ("google_reviews_widget", "Google reviews widget"),
                ]:
                    v = checks.get(k)
                    mark = "✅" if v is True else ("❌" if v is False else "Couldn't check")
                    st.write(f"- {label}: {mark}")

        # PDF download
        st.markdown("### PDF Report")
        pdf_bytes = st.session_state.get("pdf_bytes")
        if pdf_bytes is None:
            try:
                # The date on the sheet is the rep's own day, from their browser (Welton 2026-10-21);
                # scripts/measured.py sheet_day falls back to the prospect's state, never the server's UTC day.
                try:
                    results["browser_tz"] = st.context.timezone
                except Exception:
                    results["browser_tz"] = None
                pdf_path = pdf_generator.build_pdf(results)
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()
                st.session_state["pdf_bytes"] = pdf_bytes
                st.session_state["pdf_filename"] = Path(pdf_path).name
            except Exception as e:
                st.error(f"PDF generation failed: {e}")

        if pdf_bytes:
            st.download_button(
                label="📄 Download PDF",
                data=pdf_bytes,
                file_name=st.session_state.get("pdf_filename", "HealthCheck.pdf"),
                mime="application/pdf",
                type="primary",
            )

        # Keep a copy of every sheet for the office (scripts/sheet_archive.py,
        # Welton 2026-10-20). After the download button, so the rep never waits
        # on it; a failed save is a note to the rep, never a missing sheet.
        if pdf_bytes and not st.session_state.get("archive_done"):
            st.session_state["archive_done"] = True
            saved, where = sheet_archive.save_sheet(
                pdf_bytes, results, st.session_state.get("log_text", ""),
                st.session_state.get("form_values", {}).get("business", ""))
            st.session_state["archive_note"] = None if saved else sheet_archive.REP_NOTE % where
        if st.session_state.get("archive_note"):
            st.warning(st.session_state["archive_note"])


# The code version, so anyone can see this app runs the latest booth code (Welton 2026-10-20).
st.caption("Booth code %s" % CODE_VERSION)
