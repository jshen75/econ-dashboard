# 📊 Econ Dashboard

A personal, self-hosted US-macro dashboard — *all the numbers, plus some
intuitions*. A much simpler, single-user Trading-Economics for the handful of
indicators worth tracking, built from the original project brief (kept locally
in `notes/`).

## What it does

- 14 indicators across 6 sections (Demand → GDP, Income/Labor, Production,
  Inflation, Rates, Tariffs/Geopolitics).
- For each: the latest number(s), recent history chart, a short "what this means"
  intuition, and the source link.
- A **Refresh now** button pulls the latest releases. Government revisions are
  tracked (shows *"revised from X to Y"*), never silently overwritten.

## Architecture

Clean `fetch → parse/normalize → store → display`. Add an indicator by adding a
row to [econ/indicators.py](econ/indicators.py) — no new code.

| Layer | File | Job |
|---|---|---|
| Config | `econ/indicators.py` | The indicator registry (DRY, config-driven) |
| Models | `econ/models.py` | `Indicator` / `SeriesSpec` / `Reading` shapes |
| Fetch | `econ/fetch.py` | Polite, retrying HTTP (per-host rate limit, backoff, block detection) |
| Sources | `econ/sources.py` | FRED API · ISM scrape · manual — behind one `collect()` |
| Store | `econ/store.py` | SQLite + revision tracking |
| Orchestration | `econ/refresh.py` | `fetch → normalize → store` for all indicators |
| Display | `app.py` | Streamlit UI |

### Data sourcing (the hybrid)

- **FRED API** for the 11 quantitative series — one clean interface, server-side
  MoM/YoY transforms, rock-solid uptime. *(This is why the dashboard is reliable
  instead of scraping a dozen .gov pages that change layout.)*
- **ISM PMI** is licensed and not on FRED — best-effort scraper with a seeded
  fallback.
- **Tariffs/Geopolitics** is qualitative — hand-entered notes (see `seed.py`).

## Quickstart

```bash
# 1. Install
pip install -r requirements.txt

# 2. Seed the brief's §2 data so the dashboard isn't empty
python seed.py

# 3. (Recommended) add a free FRED key for live data
#    Get one: https://fredaccount.stlouisfed.org/apikeys
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
#    …then edit it and paste your key.

# 4. Run
streamlit run app.py
```

Then click **🔄 Refresh now** in the sidebar to pull live FRED data. You can also
refresh from the CLI:

```bash
python -m econ.refresh
```

## Deploy to Streamlit Community Cloud (free)

1. Push this repo to GitHub (`.gitignore` already excludes your secret + DB).
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app** → point it
   at this repo and `app.py`.
3. In the app's **Settings → Secrets**, paste:
   ```toml
   FRED_API_KEY = "your_key_here"
   ```
4. Deploy. It's now reachable from your phone.

> Note: Community Cloud has an ephemeral filesystem, so `econ.db` resets on
> redeploy. The app re-seeds/refreshes on demand. If you want durable history
> there, swap `econ/store.py`'s SQLite path for a hosted Postgres (e.g. Neon/
> Supabase free tier) — the store interface stays the same.

## Adding an indicator

Add one `Indicator(...)` to `INDICATORS` in [econ/indicators.py](econ/indicators.py).
Find FRED series ids at [fred.stlouisfed.org](https://fred.stlouisfed.org). Pick a
transform: `lin` (level), `pch` (% MoM/QoQ), `pc1` (% YoY), `chg` (change),
`pca` (annualized, for GDP).

## Scheduling auto-refresh (optional)

The build ships with a manual button per your choice. To auto-refresh later,
either add a cron job running `python -m econ.refresh`, or add `APScheduler` and
kick it off at app start.
