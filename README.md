# 📊 Econ Dashboard

A personal, self-hosted US-macro dashboard — *all the numbers, plus some
intuitions*. A much simpler, single-user Trading-Economics for the handful of
indicators worth tracking, built from the original project brief (kept locally
in `notes/`).

## What it does

- 15 indicators across 5 sections (Demand → GDP, Income/Labor, Production,
  Inflation, Rates).
- For each: the latest number(s), recent history chart, a short "what this means"
  intuition, and the source link.
- A **Refresh now** button pulls the latest releases. Government revisions are
  tracked (shows *"revised from X to Y"*), never silently overwritten.
- Refresh can run all indicators, a selected subset, or a single indicator from
  its own chart section. This is useful when scrape/news sources are slow or
  rate-limited.

## Architecture

Clean `fetch → parse/normalize → store → display`. Add an indicator by adding a
row to [econ/indicators.py](econ/indicators.py) — no new code.

| Layer | File | Job |
|---|---|---|
| Config | `econ/indicators.py` | The indicator registry (DRY, config-driven) |
| Models | `econ/models.py` | `Indicator` / `SeriesSpec` / `Reading` shapes |
| Fetch | `econ/fetch.py` | Polite, retrying HTTP (per-host rate limit, backoff, block detection) |
| Sources | `econ/sources.py` | FRED API · scrapes · news aggregation · manual — behind one `collect()` |
| Store | `econ/store.py` | SQLite locally, Postgres/Neon on deploy + revision tracking |
| Orchestration | `econ/refresh.py` | `fetch → normalize → store` for all indicators |
| Display | `app.py` | Streamlit UI |

### Data sourcing (the hybrid)

- **FRED API** for quantitative series — one clean interface, server-side
  MoM/YoY transforms, rock-solid uptime. *(This is why the dashboard is reliable
  instead of scraping a dozen .gov pages that change layout.)*
- **Jobless claims** use FRED's seasonally adjusted initial and continuing claims
  series, scaled to thousands for display.
- **ISM PMI** is licensed and not on FRED — best-effort scraper with a seeded
  fallback.
- **WARN notices** are state-fragmented. The first adapter scrapes Pennsylvania's
  public WARN notice page into monthly affected-worker and notice-count readings,
  with manual entry available as a fallback. Add state adapters behind
  `collect_warn_notices()` rather than mixing page scraping into the UI.
- The previous Tariffs/Geopolitics section is parked for now; its data can be
  reintroduced later by adding indicators back to the registry.

### Adding a source type

Keep the contract as `fetch -> parse/normalize -> Reading -> store`. Use:

- `fred` for stable numeric series with clean IDs.
- `scrape` for public pages/files where no structured API exists; parsers should
  fail soft and return no readings rather than storing garbage.
- `news` for aggregate media indexes such as GDELT.
- `manual` for qualitative notes or fallback data that should be entered by an
  admin user.

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
   ADMIN_PASSWORD = "choose-a-strong-password"
   ```
4. Deploy. It's now reachable from your phone.

### Durable history with Neon Postgres

Streamlit Community Cloud has an ephemeral filesystem, so local `econ.db` resets
on redeploy. For durable history, create a Neon Postgres database and add its
connection string to Streamlit secrets:

```toml
DATABASE_URL = "postgresql://user:password@host/dbname?sslmode=require"
```

`econ/store.py` automatically uses Postgres when `DATABASE_URL`, `POSTGRES_URL`,
or `NEON_DATABASE_URL` is set. If none is set, it falls back to local SQLite.

On first deploy with Neon, the app creates the tables and seeds the starter data.
After that, click **Refresh now** to pull the latest live data into Neon.

## Adding an indicator

Add one `Indicator(...)` to `INDICATORS` in [econ/indicators.py](econ/indicators.py).
Find FRED series ids at [fred.stlouisfed.org](https://fred.stlouisfed.org). Pick a
transform: `lin` (level), `pch` (% MoM/QoQ), `pc1` (% YoY), `chg` (change),
`pca` (annualized, for GDP).

## Scheduling auto-refresh (optional)

The build ships with a manual button per your choice. To auto-refresh later,
either add a cron job running `python -m econ.refresh`, or add `APScheduler` and
kick it off at app start.
