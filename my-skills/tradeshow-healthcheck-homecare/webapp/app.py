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

# Now safe to import the scoring scripts
import health_check  # noqa: E402
import pdf_generator  # noqa: E402


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


def _run_in_thread(business, cities, state, q, result_box):
    writer = _QueueWriter(q)
    try:
        with redirect_stdout(writer), redirect_stderr(writer):
            results = health_check.run_health_check(business, cities, state)
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
    state = st.selectbox("State", US_STATES, index=US_STATES.index("FL"))
    second_city = st.text_input("Second City", placeholder="e.g., Plant City")
    third_city = st.text_input("Third City (optional)", placeholder="leave blank to skip")
    submitted = st.form_submit_button("Run Health Check", type="primary")


# Reset state when a new submission comes in
if submitted:
    st.session_state["scan_started"] = True
    st.session_state["scan_done"] = False
    st.session_state["results"] = None
    st.session_state["error"] = None
    st.session_state["log_text"] = ""
    st.session_state["form_values"] = {
        "business": business.strip(),
        "home_city": home_city.strip(),
        "state": state.strip(),
        "second_city": second_city.strip(),
        "third_city": third_city.strip(),
    }


def _validate(values):
    missing = []
    for label, key in [
        ("Business Name", "business"),
        ("Home City", "home_city"),
        ("State", "state"),
        ("Second City", "second_city"),
    ]:
        if not values.get(key):
            missing.append(label)
    return missing


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
    else:
        cities = [values["home_city"], values["second_city"]]
        if values["third_city"]:
            cities.append(values["third_city"])

        st.markdown("### Live scan")
        progress_box = st.empty()
        spinner_box = st.empty()

        q = queue.Queue()
        result_box = {}
        worker = threading.Thread(
            target=_run_in_thread,
            args=(values["business"], cities, values["state"], q, result_box),
            daemon=True,
        )
        worker.start()

        log_lines = []
        spinner_box.info("Scanning... reviews, 3-Pack, SEO, ads, website running in parallel.")

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

        overall = results.get("overall_grade", "F")
        st.markdown(
            f"<div class='scmm-card'>"
            f"<div style='font-size:0.9rem;color:{SCMM_GRAY};text-transform:uppercase;letter-spacing:0.05em;'>Overall Grade</div>"
            f"<div style='font-size:3rem;font-weight:800;color:{SCMM_DARK};line-height:1;'>{overall}</div>"
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
                "<span style='color:#6C757D;font-style:italic;'>N/A</span>"
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
            st.write(f"**Target:** {tgt.get('review_count', '-')} reviews, {tgt.get('rating', '-')} stars")
            if comp:
                st.write(
                    f"**Top competitor:** {comp.get('name', '?')} -- "
                    f"{comp.get('review_count', 0)} reviews, "
                    f"{comp.get('rating', '-')} stars"
                )
                gap = results.get("review_gap")
                if gap:
                    st.write(f"**Review gap:** {gap} reviews behind")

        with st.expander("Google 3-Pack", expanded=False):
            pack = results.get("3pack") or {}
            for c, d in (pack.get("results") or {}).items():
                top3 = ", ".join((d.get("top_3") or [])[:3]) or "—"
                if d.get("in_3_pack"):
                    st.write(f"**{c}:** Found at rank {d.get('rank')} (Top 3: {top3})")
                else:
                    st.write(f"**{c}:** Not found (Top 3: {top3})")

        with st.expander("Google SEO", expanded=False):
            for c, d in (results.get("seo") or {}).items():
                rank = d.get("rank")
                top3 = ", ".join((d.get("top_3") or [])[:3]) or "—"
                rank_txt = f"Rank {rank}" if rank else "Not in top 10"
                st.write(f"**{c}:** {rank_txt} (Top 3: {top3})")

        with st.expander("Google Ads", expanded=False):
            for c, d in (results.get("ads") or {}).items():
                advs = ", ".join(d.get("all_advertisers") or []) or "No ads detected"
                st.write(f"**{c}:** {advs}")
                if d.get("prospect_running_ads"):
                    st.write(f"&nbsp;&nbsp;↳ Prospect running ads in {c}")

        with st.expander("Website", expanded=False):
            web = results.get("website") or {}
            if web.get("unverified"):
                st.write(f"Unable to verify -- {web.get('unverified_reason', 'blocked')}")
            else:
                checks = web.get("checks") or {}
                psi = web.get("pagespeed_score")
                psi_txt = f"{psi}/100" if psi is not None else "Unable to test"
                st.write(f"- PageSpeed mobile: {psi_txt}")
                for k, label in [
                    ("real_photos", "Real team photos"),
                    ("about_team_page", "About / Team page"),
                    ("blog_recent", "Recent blog (6 mo)"),
                    ("intake_form", "Intake form"),
                    ("localbusiness_schema", "LocalBusiness schema"),
                    ("google_reviews_widget", "Google reviews widget"),
                ]:
                    v = checks.get(k)
                    mark = "✅" if v is True else ("❌" if v is False else "—")
                    st.write(f"- {label}: {mark}")

        # PDF download
        st.markdown("### PDF Report")
        pdf_bytes = st.session_state.get("pdf_bytes")
        if pdf_bytes is None:
            try:
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
