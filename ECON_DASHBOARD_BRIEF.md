# Econ Dashboard — Project Brief & Build Prompt

> Paste this file into the new repo (e.g. as `README.md` or `docs/BRIEF.md`) and use it
> to kick off the project with Cursor / Claude. It contains (1) what to build, (2) how I
> want you to behave before writing code, and (3) the full data model + source links.

---

## 0. Instructions to the AI building this (READ FIRST)

You are helping me build a **personal economics dashboard** — "all the numbers, plus some
intuitions." Think a much simpler, self-hosted Bloomberg/Trading-Economics for the handful
of indicators I actually track. It is for me, not a product.

**Before you write any code:**

1. **Ask me ALL your clarifying questions first.** Do not assume. Batch them, group them by
   topic, and wait for my answers before scaffolding anything. A starter list of questions I
   already expect is in §5 — answer those plus anything else you need.
2. **When you propose packages, frameworks, or architecture, always give me:**
   - a one-line description,
   - **2–4 brief pros**,
   - **2–4 brief cons**,
   - **your recommendation + one-sentence why.**
   Keep it skimmable (tables or tight bullets). I want to make informed choices, not read essays.
3. **Right-size it.** This is a simple single-user dashboard. Do not over-engineer (no
   microservices, no multi-tenant, no heavy job queues unless we agree we need them). Do not
   under-engineer either (I do want clean separation between *fetch → parse → normalize → store →
   display* so I can add indicators without rewriting everything).
4. **Keep it DRY and add indicators via config, not copy-paste.** Every indicator below shares
   the same shape (name, intuition, latest readings, source URL). Model that once.

---

## 1. What the dashboard does

- Shows a set of **economic indicators** grouped into sections (Demand, Income/Labor,
  Production, Inflation, Rates, Tariffs/Geopolitics).
- For each indicator: the **latest number(s)**, recent history, and a short **intuition / "what
  this means"** note.
- **Update workflow (important):** each indicator has a **source link at the bottom of its
  section**. My routine is: I open that link, the system scrapes/reads the latest release, and
  the dashboard updates. So the scraper must be **driven by these source URLs**, one per
  indicator. Some are HTML tables (Census, Treasury), some are press-release pages (BEA, BLS,
  Fed), some are PDF/press text (ISM). Plan for heterogeneous sources behind one interface.
- I want to be able to **trigger a refresh** (manual button or command) and optionally schedule it.

### Data shape (every indicator looks like this)
```
Indicator
  ├─ key                e.g. "cpi", "nonfarm_payroll"
  ├─ name               e.g. "Consumer Price Index (CPI-U)"
  ├─ section            "Inflation"
  ├─ cadence            monthly | quarterly | daily | irregular
  ├─ intuition          short note: what rising/falling means
  ├─ source_url         the link I open to get the latest release
  ├─ source_type        html_table | press_release | pdf | api
  └─ readings[]         { date, value(s), commentary }   ← time-ordered
```

---

## 2. The indicators (content to seed the DB/fixtures)

> Numbers below are what I've tracked so far — use them as seed/fixture data and as test cases
> for the scrapers. Dates are **release dates** unless noted. Some entries mix 2025 and 2026
> releases on purpose so you can see the history. Treat any internal inconsistency as a parsing
> target to confirm against the live source.

### SECTION A — DEMAND SIDE → GDP
Demand = Government + Consumption + Investment + Net Exports.

#### A1. GDP (real, annualized)
- **2026-04-30:** Q1 real GDP **+2.0%** annual rate; Q4 2025 was **+0.5%**.
- Advance/early read referenced Q1 **−0.3%** (confirm which estimate against source).
- **Intuition:** headline growth; watch the contribution split (consumption vs. net exports vs. investment).
- **Source:** https://www.bea.gov/  → GDP news release

#### A2. Trade Balance / Net Exports (Goods & Services Deficit)
- **2026-05-05 (March data):** goods & services deficit **$60.3B**, up $2.5B from $57.8B (Feb, revised).
  YTD deficit **−$211.2B (−55.0%)** vs. same period 2025. Exports **+$100.2B (+12.0%)**,
  Imports **−$111.0B (−9.1%)**.
- **2025-05-06 (March data):** deficit **$140.5B (+14.0%)**; Exports **$278.5B (+0.2%)**;
  Imports **$419.0B (+4.4%)** (up $17.3B from $123.2B Feb).
- **Intuition:** net exports component of GDP; widening deficit drags GDP; front-running tariffs distorts imports.
- **Source:** https://www.bea.gov/news/2025/us-international-trade-goods-and-services-march-2025

#### A3. Consumption — drivers
Consumption is driven by **Income + Wealth + Borrowing cost**:
- **Income:** wages (and unemployment), card spending.
- **Wealth:** stock prices, housing prices (Case-Shiller).
- **Borrowing cost:** interest rates.
(The hard data lives in A4 Retail Sales and A5 PCE below; labor in Section B.)

#### A4. Retail Sales
- **2026-05-14 (April):** $757.1B, **+0.5% (±0.4) MoM**, **+4.9% (±0.5) YoY** (seasonally adj, not price adj).
  Feb→Mar revised from +1.7% to **+1.6%**.
- **2025-05-15:** **+0.1%**; March revised **+1.7%**.
- **2025-04-16 (March):** **+1.4%** ($735B) vs. Feb — consumption rising.
- **2025-02-17 (January):** **−0.9%** — possible cool-down.
- **Intuition:** fastest read on consumer demand; volatile, watch revisions.
- **Source:** https://www.census.gov/retail/sales.html

#### A5. Personal Income & Outlays (PCE)
- **2026 March:** Personal income **+$149.2B (+0.6%)**; DPI (income less taxes) **+$142.5B (+0.6%)**;
  **PCE +$195.4B (+0.9%)**; personal outlays **+$198.6B**; personal saving **$857.3B**;
  **saving rate 3.6%**. *(Note: confirm the income vs. PCE figures against the source — labels may need verifying.)*
- **2025-04-30:** PCE **+$134.5B (+0.7%)** for the month.
- **2025-03-28 (Feb):** PCE **+0.4%**.
- **2025 Feb (Jan data):** PCE **+0.7%**; PI & DPI **+0.4%** (consumption > income). Spending **−0.2%**
  for the month, **−0.5% real** — biggest monthly declines since Feb 2021.
- **Intuition:** PCE is the consumption backbone of GDP; saving rate shows cushion; spending > income = drawing down savings.
- **Source:** https://www.bea.gov/data/income-saving/personal-income → "Personal Income and Outlays" report

#### A6. Corporate Investment — Durable Goods Orders
Driven by **borrowing cost (interest rate) + profit.**
- **2026-04-26:** **+$2.6B (+0.8%) to $318.9B** (after a 1.2% Feb decrease, ending 3 monthly declines).
  Ex-transportation **+0.9%**; ex-defense **−0.3%**. Computers & electronics led: **+$1.0B (+3.7%) to $29.6B**
  (up 11 of last 12 months).
- **2025-04-24 (March):** **+9.2% to $315.7B** (Feb +0.9%), 3rd straight monthly gain — factory stocking ahead of trade war.
- **2025-02-27 (January):** **+$8.7B (+3.1%) to $286.0B** (ended two monthly declines).
- **2025-01-27 (Dec):** **−2.2%** from Nov (−2% from Nov prior) to **$276B** — slowing factory demand.
- **Intuition:** proxy for business investment/capex appetite; ex-transport & ex-defense are the cleaner signals.
- **Source:** https://www.census.gov/manufacturing/m3/adv/current/index.html

#### A7. Fiscal Deficit / Debt (context)
- Fiscal deficit ~**$840B** this period; total federal debt ~**$36T**; ~**$1.8T** last year.
- **Intuition:** government contribution to demand and long-run sustainability backdrop. *(Confirm a canonical
  source — Treasury Monthly Treasury Statement / FiscalData — when wiring this up.)*

---

### SECTION B — INCOME SIDE (Labor Market)
"Strong labor market" = income supports consumption.

#### B1. Employment Situation (Nonfarm Payroll + Unemployment)
- **2026-05-08 (April):** payrolls **+115,000**; unemployment **4.3%** (unchanged). Gains in health care,
  transportation/warehousing, retail; federal government employment still declining.
- **2025-05-02 (April):** **+177,000**; unemployment **4.2%** (unchanged) — foreign firms basing in US + import-driven demand.
- **2025-04-04 (March):** **+228K**; **4.2%**.
- **2025-02-07 (January):** **+143K**; **4.0%**.
- **Intuition:** payroll growth + low unemployment = income engine for consumption; watch sector mix and gov't drag.
- **Source:** https://www.bls.gov/news.release/empsit.nr0.htm

#### B2. Real Earnings (Real Average Hourly Earnings)
- **2026 April:** real avg hourly earnings **−0.5%** Mar→Apr (nominal **+0.2%**, CPI-U **+0.6%**).
- **2025-05-13:** unchanged (earnings +0.2%, CPI-U +0.2%).
- **2025-05-02:** real wage **+0.2%**.
- **2025-04-10:** wages **+0.3%** vs. Feb. (Trend ~+0.5%/mo nominal earlier in the year.)
- **Intuition:** nominal wages minus inflation = real purchasing power; negative real = inflation eating raises.
- **Source:** https://www.bls.gov/news.release/realer.nr0.htm

> **Income decomposition (mental model):** Income = wages + wealth effect (housing ↑, dividends,
> AI-driven stock gains, interest) for households + taxes (government) + corporate profit (firms).

---

### SECTION C — PRODUCTION (Supply)

#### C1. Industrial Production & Capacity Utilization
- **2026-05-15 (April):** IP **+0.7%** (after −0.3% March). Manufacturing **+0.6%**, mining **−0.1%**,
  utilities **+1.9%**. Mfg ex-autos **+0.3%**. IP at **102.5%** of 2017 avg, **+1.4% YoY**.
  Capacity utilization **76.1%** — **3.3pp below** long-run (1972–2025) avg.
- **2025-05-15:** roughly March levels (mfg & mining decline offset by utilities).
- **2025-04-16 (March):** IP **−0.3%** but **+5.5%** annual; mfg & mining grew. Cap-util **77.8%** (1.8pp below long-run).
- **2025-02-14:** cap-util **77.8%**; IP **+0.5%** Jan (aircraft rebound); mfg **−0.1%** (matches durable-goods softness).
- **Intuition:** weak capacity utilization = slack in existing factories → less incentive to invest. Drill into
  industries (e.g. AI/data-center over-utilized vs. others slack).
- **Source:** https://www.federalreserve.gov/releases/g17/current/default.htm

#### C2. PMI — ISM Purchasing Managers' Index (>50 = expansion)
- **2026 early-May (April):** Manufacturing **52.7%** (same as March); Services **53.6%** (−0.4pp from 54.0%).
- **2025 May:** Manufacturing **48.7%** (−0.3pp, contraction); Services **53.7%** (−2.2pp);
  Hospital **55%** (+4pp, not very cycle-sensitive).
- **2025 Feb:** Manufacturing **50.9%**; Services **52.8%**; Hospital **53.5%**.
- **Intuition:** leading sentiment gauge; 50 is the expansion/contraction line; services dominates the US economy.
- **Source:** https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/

---

### SECTION D — INFLATION

#### D1. CPI / Core CPI
- **2026-05-12 (April):** CPI **+0.6% MoM (SA)**, **+3.8% YoY (NSA)**; shelter & gasoline up.
  Core (ex food & energy) **+0.4% MoM (SA)**, **+2.8% YoY (NSA)**.
- **2025-05-13:** core **+0.2%** April (food up, energy down).
- **2025-04-10 (March):** core **+0.1% (SA)**, **+2.8% YoY**.
- **2025-03-13:** CPI **−0.1%** (energy).
- **2025 Feb:** **3.0% YoY** before seasonal adj (+0.1% from Dec 2024); housing the main monthly driver.
- **Intuition:** core strips volatile food/energy; shelter is sticky; this gates Fed rate decisions.
- **Source:** https://www.bls.gov/cpi/

#### D2. PCE Price Index (the Fed's preferred gauge)
- **2025-04-30 (March):** PCE price index **+2.3% YoY** (down from 2.7% Feb) — disinflation.
- **2025-03-28 (Feb):** **+0.4% MoM**.
- **Intuition:** Fed's target gauge (2% goal); broader basket than CPI.
- **Source:** https://www.bea.gov/data/personal-consumption-expenditures-price-index

---

### SECTION E — RATES

#### E1. Treasury Yield Curve
- **Shape narrative:** flat → mildly inverted mid-term → upward sloping at the long end — signals
  near-term uncertainty but still a strong longer-run outlook.
- **2026-05-26:** ~**4.43%** (4-month) → **5.05%** (20/30-year).
- **2026-05-08:** ~**4.37%** (≈4.4% at 4-month) → **4.83%** (long end).
- **2025 Feb/Mar:** ~4.3% → 4.5% → 4.7%.
- **Intuition:** inversion = recession warning; steepening long end = growth/inflation expectations; pin Fed policy via short end.
- **Source:** https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve&field_tdr_date_value_month=202502

---

### SECTION F — TARIFFS / GEOPOLITICS (qualitative)
**Transmission logic:**
- Tariff → higher US import prices.
- **Short term:** exporters don't cut prices → US consumers bear it → inflation ↑ → Fed can't cut rates.
- **Long term:** disrupted supply chains → trade, production, consumption decline → growth declines (cf. IMF trade analysis).

- **2025-05-02:** imports strong ahead of tariffs; negotiations with allies — UK, Mexico, Canada, EU, Japan, China.
  - **UK:** exports beef, ethanol (9th biggest US trading partner; buys Boeing); imports cars, steel 10%; UK runs a
    surplus → ~baseline 10% with room to talk. China–Switzerland talks that weekend; EU talks soon.
- **2025-02-28:** China **+10%**; Europe VAT (domestic only, rebated on exports); **25%** on Mexico & Canada;
  US sells to China → China levies VAT on US goods; note US sales-tax asymmetry.
- **Intuition:** the macro wildcard — feeds inflation, trade balance (A2), durable goods front-running (A6), and rate path.
- **Source:** news-driven (no single fixed feed). Suggest: tag manually or scrape a curated news query; ask me how I want this populated.

---

## 3. Section → source-link quick reference (the "scrape targets")

| Section | Indicator | Source URL | Type |
|---|---|---|---|
| A1 | GDP | bea.gov (GDP release) | press_release |
| A2 | Trade balance | bea.gov/news/.../us-international-trade-goods-and-services... | press_release |
| A4 | Retail sales | census.gov/retail/sales.html | html_table |
| A5 | PCE / Personal income | bea.gov/data/income-saving/personal-income | press_release |
| A6 | Durable goods | census.gov/manufacturing/m3/adv/current/index.html | html_table |
| B1 | Nonfarm payroll | bls.gov/news.release/empsit.nr0.htm | press_release |
| B2 | Real earnings | bls.gov/news.release/realer.nr0.htm | press_release |
| C1 | Industrial production | federalreserve.gov/releases/g17/current/default.htm | html_table |
| C2 | ISM PMI | ismworld.org/.../ism-report-on-business | pdf/press |
| D1 | CPI | bls.gov/cpi/ | press_release |
| D2 | PCE price index | bea.gov/data/personal-consumption-expenditures-price-index | press_release |
| E1 | Yield curve | home.treasury.gov/.../daily_treasury_yield_curve | html_table |
| F | Tariffs | news-driven | manual/news |

> Note: BEA, BLS, FRED, Treasury, and Census all publish machine-readable data too (FRED API,
> BLS API, Census API, Treasury FiscalData API). **Ask me** whether I prefer scraping the
> human pages I listed vs. pulling clean numbers from those APIs (or a hybrid). See §5.

---

## 4. Scraping notes (lessons worth reusing, no specific library mandated)

These are robustness patterns worth implementing simply — not a framework to copy:
- **One fetch interface, many source types.** Route by `source_type` (html_table / press_release / pdf / api).
- **Retry on transient failures** (HTTP 429/500/502/503/504) with backoff.
- **Be polite per host** (these are .gov sites): a small rate limit / delay per domain, a real
  User-Agent string with a contact email (some gov APIs *require* a contact email in the UA).
- **Detect "blocked" responses** (captcha/WAF markers) and fail loudly rather than store garbage.
- **Normalize before storing:** parse each release into the `reading` shape; keep the raw snippet
  for audit so I can verify the parse against the source.
- **Government data revises constantly** — store revisions, don't overwrite; show "revised from X to Y".

---

## 5. Clarifying questions I expect you to ask me (answer these + your own, before coding)

**Scope & UX**
1. Web app, desktop, or local-only? Do I need it accessible from my phone?
2. Single page with collapsible sections, or one page per section? Charts, tables, or both?
3. Do I want the "intuition" notes editable in-app, or hardcoded?

**Data sourcing**
4. Scrape the human pages I listed, or use official APIs (FRED/BLS/Census/Treasury) where available, or hybrid? (pros/cons please)
5. Manual "refresh now" only, or scheduled auto-refresh? How often?
6. How should the qualitative Tariffs section be populated — manual notes, or news scraping?

**Storage & history**
7. How much history do I want to keep / chart? Do I care about revisions tracking from day one?
8. SQLite vs. Postgres vs. flat files? (pros/cons please)

**Stack**
9. Language/framework preference (Python + FastAPI/Flask? Next.js? Streamlit?) — give me options with pros/cons.
10. Hosting: local, a small VPS, or a managed host? Any budget constraint?
11. Do I want LLM-assisted parsing of the press releases (more robust to format changes) or pure deterministic parsing (cheaper, predictable)?

**For every package/architecture choice above:** give a short pros/cons table + your recommendation.

---

## 6. Suggested first deliverable (after my answers)

1. Confirm stack + architecture (with pros/cons) and get my sign-off.
2. Scaffold: `indicators` config/model → `fetch` layer → `parse/normalize` → `store` → `display`.
3. Seed the DB with the data in §2 as fixtures.
4. Implement **two** scrapers end-to-end first (suggest one `html_table`, e.g. Census retail
   sales, and one `press_release`, e.g. BLS CPI) so we validate the pattern before doing all 12.
5. Then fill in the rest behind the same interface.

---

*Source codebase note: this brief was distilled from a separate, much larger multi-tenant
investment platform that has a heavy enterprise scraper. None of that proprietary code is
included here — only generic patterns (§4) and my own indicator data (§2). Build fresh.*
