# Instructions for ChatGPT — Build the Pitch Excel Model

## Context you'll receive

I am pitching a 3-month expiry, 10-year underlying payer swaption spread on the USD SOFR swap curve as my Morgan Stanley Interest Rates summer analyst final pitch. Pitch date is Thursday, July 30, 2026.

Attached to this conversation:

1. **`RatesPitchNotes_ATM10_ATM50.pdf`** — full trade notes with macro thesis, Bloomberg SWPM screenshots, per-strike Greeks, alternative combos, P&L tables, Q&A drills. This is your primary source of truth for all trade parameters. **Do not deviate from the numbers in this PDF.**

2. **`vol_data.xlsx`** (name may differ) — my working spreadsheet with realized vol and implied vol (PX_LAST from Bloomberg) for 3m10y payer at strikes ATM+25, ATM+50, ATM+100, ATM+200. Use this data as-is for the vol richness analysis — do not overwrite or reconstruct it.

## What to build

A single Excel workbook — **`RatesPitchModel_ATM10_ATM50.xlsx`** — with the tabs specified below, in this order. Every number should be a formula that references either the Inputs tab or another cell, so that changing an input propagates through everything. Hardcoded numbers only on the Inputs tab and in the vol data I provide.

### Tab 1: `README`

- One-page description of the workbook: what each tab does, sign conventions used (Bloomberg convention: DV01 is per 1 bp DECLINE in underlying), model used (Normal / Bachelier), valuation date (07/27/2026).
- List of tabs with brief description.
- Data sources noted: SWPM for trade PVs and Greeks; VCUB for vol surface; user-provided sheet for realized vs implied history.

### Tab 2: `Inputs`

All hardcoded assumptions live here. Cells should be yellow-shaded so I can see they're editable. Fields:

- Valuation date: 07/27/2026
- Expiry date: 10/27/2026
- Swap start: 10/29/2026
- Swap end: 10/29/2036
- Time to expiry (years): =DAYS(expiry, valuation)/365 → should compute to ~0.25
- Currency: USD
- Model: Normal (Bachelier)
- ATM forward (10y swap fwd starting 3m): 4.234% (this is 4.235927% rounded)
- ATM normal vol (3m10y, from VCUB): 74.12 bps
- Annuity (derived from SWPM, see calc below): 8.12
- Notional per leg: 250,000,000
- Long strike: 4.336% (ATM+10)
- Short strike: 4.736% (ATM+50)

Include a small "annuity derivation" block showing:
- ATM Bachelier ATM PV (from Bloomberg): 1,200,232 on $100mm
- Formula: A = PV_ATM / (N × σ × √T × φ(0)) where φ(0) = 1/√(2π) ≈ 0.3989
- Result should compute to ~8.12

### Tab 3: `Bachelier_Pricer`

Full working Bachelier normal model pricer. For a payer swaption:

```
V = A × N × [(F − K) × Φ(d) + σ_N × √T × φ(d)]
where d = (F − K) / (σ_N × √T)
```

Inputs (referenced from Inputs tab or user-editable): F, K, σ_N (in decimal — i.e., 74.12 bps → 0.007412), T, A, N.

Outputs:
- d
- Φ(d) — use `NORM.S.DIST(d, TRUE)`
- φ(d) — use `NORM.S.DIST(d, FALSE)`
- Premium per unit = A × [(F−K) × Φ(d) + σ√T × φ(d)]
- Premium in bps of notional
- Premium in dollars

Greeks (analytical Bachelier):
- Delta = A × Φ(d) — sensitivity of premium (as fraction of notional) to unit change in F
- Vega = A × √T × φ(d)
- Theta = − (A × σ × φ(d)) / (2 × √T) — annualized, then divide by 365 for daily
- Gamma = (A × φ(d)) / (σ × √T)

Convert each to per-bp / per-day / per-vol-bp dollar terms on the specified notional.

**Validation check** — build a small block that compares the Excel Bachelier output vs the actual Bloomberg SWPM output for the ATM+10 long leg (PV should be ~$856,724 on $100mm) and ATM+50 short leg (PV should be ~$213,619 on $100mm). Show the difference. Should be within 1-2% since Bloomberg uses the exact skewed vol per strike and I'm using flat ATM vol here.

### Tab 4: `Trade_Structure`

Two side-by-side columns for the two legs of the recommended trade:

Row-by-row (all cells reference Inputs and Bachelier_Pricer):

- Position (Long / Short)
- Strike (%, referenced from Inputs)
- Notional
- Direction sign (+1 long, −1 short)
- PV
- Premium in bps of notional
- DV01 in $/bp (Bloomberg convention: sign flipped for direction)
- Vega in $/bp of vol
- Gamma in $/bp
- Theta in $/day

Net column that sums the two legs.

Below this, a "**Bloomberg SWPM cross-check**" block with hardcoded SWPM numbers from the PDF for the same trade, and % difference vs Excel Bachelier. This is your validation — if the model matches SWPM within ~2%, you're good.

### Tab 5: `PnL_Scenarios`

Grid showing net P&L at expiry across 10y swap forward outcomes.

Column A: 10y swap fwd at expiry, from 3.90% to 5.20% in 5 bp increments.

Columns:
- Long payer intrinsic at expiry = MAX(0, (F − K_long) × A × N_long)
- Short payer intrinsic at expiry (from position perspective — negative) = − MAX(0, (F − K_short) × A × N_short)
- Gross intrinsic = sum of above
- Net P&L = Gross intrinsic − Net premium paid
- Return on premium = Net P&L / Net premium

Highlight rows for: ATM (4.234%), long strike (4.336%), breakeven (calculated), short strike (4.736%), +1σ (4.605%), +2σ (4.975%).

Below the grid, calculate:
- Breakeven fwd rate = K_long + (Net premium / (A × N))
- Distance from ATM to breakeven (bps)
- Distance from ATM to max gain (bps)
- Max gain
- Max loss (= net premium)
- R/R ratio

### Tab 6: `Probability_Analysis`

Using the VCUB Nvol as the market-implied distribution:

- 3m expected 1-sigma move = σ_ATM × √T (in bps)
- Should compute to ~37 bps
- 3m expected 2-sigma range around ATM

Table of key strikes with implied probabilities:

For each strike (ATM, breakeven, ATM+50, +1σ, +2σ, etc):
- Distance from ATM in bps
- Distance in sigmas (distance / σ√T)
- P(F ≥ strike at expiry) = `1 − NORM.S.DIST(distance/(σ√T), TRUE)`

Add columns for:
- Probability trade is above breakeven at expiry
- Probability trade hits max gain
- Probability trade expires worthless (F ≤ K_long)

Expected value calculation using a discretized integral:
- For each F outcome from 3.90% to 5.20% in 5 bp buckets, compute:
  - P(F outcome) = incremental normal PDF weight
  - Net P&L at that F outcome (referenced from PnL_Scenarios)
  - Contribution to EV = P × P&L
- Sum for expected value
- Compare EV to premium paid — if positive, trade is (statistically) fair-value-plus

### Tab 7: `Vol_Analysis` — INTEGRATION WITH USER-PROVIDED VOL DATA

**Import my vol_data.xlsx sheet's contents into this tab** (or reference from an external tab if easier).

The vol data I provided has implied vol (from PX_LAST) and realized vol for strikes ATM+25, ATM+50, ATM+100, ATM+200 on 3m10y payer.

Build the following analysis:

**Section A: Vol richness / cheapness**
- For each strike, compute (Implied vol − Realized vol) in bps
- Positive = market pricing vol richer than realized (implied premium)
- Negative = market pricing vol cheaper than realized (implied discount)

**Section B: Cross-strike skew**
- For each strike, show implied vol level
- Compute skew vs ATM (need my current ATM Nvol = 74.12)
- Compare to historical median skew if the data supports it

**Section C: Chart** — implied vol vs realized vol, by strike, as a bar chart or line chart. Also include a chart showing skew (implied vol minus ATM implied vol) across the strike ladder.

**Section D: Interpretation table** — for each strike, a text row saying "OTM vol is cheap by X bps vs realized" or similar, so I can pull the story into the pitch.

### Tab 8: `Alternative_Combos`

The 5 combos priced in SWPM, as documented in the PDF, in a comparison table:

Columns: Combo #, Long strike, Short strike, Spread width, Net premium ($), Net DV01, Net Vega, Net Gamma, Net Theta, Max gain, R/R, Breakeven, Distance to breakeven (bps), Probability of breakeven, Probability of max gain.

Highlight the recommended row (Combo 1: ATM+10 / ATM+50).

Include a 2-column pro/con section for the top two candidates (ATM+10/+50 and ATM/+35) so I can articulate why I chose the former.

### Tab 9: `Greeks_Sensitivity`

Two-way data table showing net P&L today (mark-to-market, not at expiry) as a function of:
- Row: shift in 10y swap fwd (−30, −20, −10, 0, +10, +20, +30, +40, +50, +60, +75, +100 bps)
- Column: shift in 3m10y implied vol (−20, −10, 0, +10, +20 bps)

Use the Bachelier pricer to reprice the position at each combination. This shows how the trade behaves before expiry across joint rate/vol moves.

Also include:
- One-way delta sensitivity chart (P&L vs rate shift, holding vol constant)
- One-way vega sensitivity chart (P&L vs vol shift, holding rate constant)

### Tab 10: `Time_Decay`

Roll-forward table showing position value if nothing moves:

Rows: valuation date + 0, 5, 10, 15, 20, ... 90 days (until expiry)
Columns: PV of long leg, PV of short leg, Net PV, Cumulative theta bled

Chart: Net PV vs. days elapsed, showing the theta curve (accelerating decay into expiry).

### Tab 11: `Summary_for_Pitch`

Clean one-page summary suitable for screenshotting into a deck:

- Trade description (one line)
- Structure table (long/short strikes, notional)
- Key numbers: premium, max gain, R/R, breakeven, distance to breakeven
- Greeks table (DV01, gamma, vega, theta)
- Probabilities: P(breakeven), P(max gain)
- 3-row P&L scenario table (rally / unchanged / base / stretch)

All numbers formula-linked to Inputs.

## Style requirements

- Number formatting: currency with commas ($1,607,763), basis points as bps with one decimal (37.1 bps), percentages with 3 decimals for rates (4.336%), volatilities in bps.
- Colors: header rows navy background, white text. Alternating row shading light gray. Highlight recommended cells in soft yellow.
- Column widths auto-fit.
- Freeze top row on every table tab.
- Font: Calibri 10 throughout.
- Every tab has a title in row 1, bold, size 14.
- No merged cells unless purely for formatting section headers.

## Deliverable

Return the finished workbook `RatesPitchModel_ATM10_ATM50.xlsx`. Wait for my approval before making the pitch deck. If any of my numbers disagree with SWPM or if you notice math errors in the PDF, flag them explicitly at the top of the README tab so I can address them before I present.

## Constraints

- Do not use VBA / macros — pure formulas only.
- Do not reprice from scratch anywhere I've provided a Bloomberg number — reference the Bloomberg number as ground truth and validate Bachelier output against it.
- All ratios and probabilities must be formula-computed from the underlying inputs, not hardcoded.
- If any input changes (I bump vol, or change strikes, or notional), the entire workbook should reprice consistently.

Once done, tell me:
1. Which tab has the biggest analytical value-add beyond what's in the PDF
2. Any inconsistency you noticed between the SWPM output and the derived Bachelier math
3. Anything you would recommend I add to strengthen the pitch numerically that isn't in the current spec
