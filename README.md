# Econ Dashboard + Risk Engine

A Streamlit app with two public-facing pages:

- **Econ Dashboard**: a compact US macro dashboard with live refresh controls.
- **Risk Engine**: a structured-finance presale parser and warehouse facility model.

The app is designed for local use and Streamlit Community Cloud deployment. It uses
SQLite locally by default and can use Neon/Postgres in production when a database
URL is provided through Streamlit secrets.

## Current App Surface

### Econ Dashboard

The dashboard tracks a focused set of macro indicators across:

- Demand to GDP
- Income / labor
- Production
- Inflation
- Rates

Features:

- Overlay and download any visible time series in the Data Explorer.
- Refresh all sources, refresh selected sources, or refresh one chart at a time.
- Track data revisions instead of silently overwriting prior releases.
- Add manual fallback readings for scraped sources when a public page is slow or
  changes layout.

Current source mix:

- **FRED** for stable quantitative data such as GDP, retail sales, payrolls,
  claims, CPI, PCE prices, and Treasury yields.
- **Pennsylvania WARN notices** from the Pennsylvania Department of Labor &
  Industry WARN notices page. The WARN adapter is explicitly Pennsylvania-only
  today because WARN disclosures are state-fragmented.
- **GDELT news aggregation** for selected news-pressure series.

ISM PMI and the older tariffs/geopolitics section are not currently exposed in
the production dashboard.

### Risk Engine

Risk Engine parses public structured-finance presales and turns the extracted
deal data into a warehouse facility model.

Workflow:

1. Upload a presale PDF.
2. Parse with Claude Sonnet 4.6 using `ANTHROPIC_API_KEY`.
3. Review extracted fields, parser flags, and dynamic headline metrics.
4. Adjust model assumptions such as CPR, CDR, severity, SOFR, spread, servicing
   fee, yield target, and advance rate.
5. Review the analysis layer, sensitivity tables, cashflow visuals, and Excel
   workbook preview.
6. Download the formula-linked Scenario A warehouse workbook.

Parser behavior:

- The parser discovers the subject deal from the document.
- It uses subject-deal table columns rather than benchmark/comparison columns.
- Tranche sizing uses credit-enhancement attachment gaps rather than summing
  exchangeable certificate amounts.
- Advance rate is seeded from the total modeled debt tranche thickness, excluding
  residual/equity/XS/R-style rows.
- Deal-specific headline metrics are dynamic. RMBS metrics such as FICO, CLTV,
  and DSCR can appear when present, but non-RMBS/ABS metrics such as YSOA, WA
  APR, WA LTV, remaining term, seasoning, product mix, or obligor concentration
  can also be surfaced.

If parser credits are exhausted, the app displays:

```text
Presale parsing failed: not enough parser credits. Please reach out to admin for more credits.
```

## Architecture

Clean `fetch -> parse/normalize -> store -> display` for the macro dashboard,
and `PDF text -> LLM extraction -> deterministic model -> workbook/report` for
Risk Engine.

| Layer | File | Job |
|---|---|---|
| App shell | `app.py` | Streamlit page navigation and Econ Dashboard UI |
| Econ config | `econ/indicators.py` | Visible macro indicator registry |
| Econ models | `econ/models.py` | `Indicator`, `SeriesSpec`, and `Reading` shapes |
| Econ sources | `econ/sources.py` | FRED, scrape, and news adapters |
| Econ store | `econ/store.py` | SQLite locally, Postgres/Neon when configured |
| Econ refresh | `econ/refresh.py` | Refresh orchestration |
| Risk parser | `rmbs/presale_parser.py` | PDF text extraction and structured LLM schema |
| Risk model | `rmbs/calculator.py` | Deterministic collateral, warehouse, and tranche math |
| Risk UI | `rmbs/warehouse_app.py` | Parser review, assumptions, analysis, and workbook download |
| Workbook logic | `rmbs/page.py` | Formula-linked Excel export and shared charts |

## Quickstart

```bash
pip install -r requirements.txt
python seed.py
streamlit run app.py
```

For live FRED refreshes and Risk Engine parsing, copy the example secrets file:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Then fill in the values you want to use.

## Streamlit Secrets

Local and deployed secrets should live in Streamlit secrets, not in source code.
The real `.streamlit/secrets.toml` file is gitignored.

Common settings:

```toml
FRED_API_KEY = "your_fred_key"
ANTHROPIC_API_KEY = "sk-ant-..."
DATABASE_URL = "postgresql://user:password@host/dbname?sslmode=require"
```

`DATABASE_URL` is optional locally. Without it, the app uses `econ.db`.

## Deploy to Streamlit Community Cloud

1. Push the repo to GitHub.
2. Create a new Streamlit app pointing at `app.py`.
3. Add the secrets you want in Streamlit Cloud settings.
4. Deploy.

For durable history and saved Risk Engine parse memory, configure a hosted
Postgres database such as Neon and set `DATABASE_URL`, `POSTGRES_URL`, or
`NEON_DATABASE_URL`.

## Local Data and Git Hygiene

The following local files are intentionally ignored:

- `.streamlit/secrets.toml`
- `econ.db`
- `.env`
- virtual environments and Python caches
- local notes in `notes/`

Do not commit real API keys, database URLs, uploaded presales, or local database
files.

## Tests

```bash
python3 -m unittest discover -s tests
```
