# SCMM Online Health Check

Streamlit web app that runs a 60-90 second online presence audit on a home
care prospect at a trade show booth and produces a branded one-page PDF
scorecard.

This is the deployable slice of the
[`tradeshow-healthcheck-homecare`](https://github.com/) skill from the
internal Powerhouse repo. It contains only the health check code -- no
client data, no other skills.

## Run locally

```bash
cd my-skills/tradeshow-healthcheck-homecare/webapp
pip install -r requirements.txt

# On Mac/Linux:
export GOOGLE_API_KEY=...
export SCRAPINGBEE_API_KEY=...

# On Windows (PowerShell):
# $env:GOOGLE_API_KEY="..."
# $env:SCRAPINGBEE_API_KEY="..."

streamlit run app.py
```

Open <http://localhost:8501>.

## Deploy to Streamlit Cloud

1. Push this repo to GitHub (already done if you're reading this on GitHub).
2. Go to <https://share.streamlit.io> -> **Create app** -> **Deploy from GitHub**.
3. Settings:
   - **Repository:** `<your-username>/scmm-healthcheck`
   - **Branch:** `main`
   - **Main file path:** `my-skills/tradeshow-healthcheck-homecare/webapp/app.py`
   - **Python version:** 3.12
4. Open **Advanced settings** -> **Secrets** and paste:
   ```toml
   GOOGLE_API_KEY = "AIzaSy..."
   SCRAPINGBEE_API_KEY = "..."
   ```
5. Click **Deploy**. First build takes 2-4 minutes.

## What gets scanned

| Check | Source |
|-------|--------|
| Google Reviews | Google Places API |
| Google 3-Pack (per city) | Google Places API + UULE |
| Google SEO (per city) | ScrapingBee + UULE |
| Google Ads (per city) | Parsed from same SERP HTML |
| Website | requests + PageSpeed Insights API |
| Reviews snapshot | Google + Facebook + Yelp |

Each check produces a letter grade. Overall grade is the average.

## Repo layout

```
my-skills/
  tradeshow-healthcheck-homecare/
    scripts/
      health_check.py        # Orchestrator - runs all checks in parallel
      google_serp_rank.py    # Real Google SERP via ScrapingBee
      website_audit.py       # Homepage scrape + heuristics
      pdf_generator.py       # Branded SCMM one-page PDF
    webapp/
      app.py                 # Streamlit UI
      requirements.txt
      assets/
        scmm_logo.jpg
      README.md              # Webapp-specific notes
  quick-intel/
    scripts/
      google_intel.py        # Google Places lookup (target + competitors)
```

The directory layout is preserved from the source repo so
`health_check.py` finds `google_intel.py` via its relative path lookup
without any code changes.

## API keys you need

| Key | What it powers | Where to get it |
|-----|----------------|-----------------|
| `GOOGLE_API_KEY` | Google Places + Geocoding + PageSpeed Insights | Google Cloud Console |
| `SCRAPINGBEE_API_KEY` | Real Google SERP rendering | scrapingbee.com |

Both keys must be set in `os.environ` (locally) or in Streamlit Cloud
**Secrets** (deployed). The webapp mirrors `st.secrets` into `os.environ`
at startup.
