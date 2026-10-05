# S4: monthly factor investing in Nifty 50 stocks (PRE-DECLARED 2026-10-05, before any stock price history was downloaded or viewed)

**Why:** the best-documented equity anomalies are **momentum** (Jegadeesh & Titman 1993; Asness, Moskowitz & Pedersen 2013) and **low volatility** (Ang et al. 2006; Frazzini & Pedersen 2014, "Betting Against Beta"). Indian evidence includes NSE's own Nifty200 Momentum 30 and Nifty100 Low Volatility 30 indices, and Raju & Chandrasekaran's work on Indian momentum.
- **Trades once a month:** costs are tiny compared with the intraday and option strategies that failed in the Nifty system.
- **Fits ₹2 lakh:** long-only, cash delivery, about 10 stocks.
- **Paper research only.**

## Data
- **Yahoo Finance daily (public chart API), adjusted close** (splits and dividends) for the **current Nifty 50 members** (the 52 stock symbols in premium's snapshot list), plus ^NSEI and **NIFTYBEES.NS** (Nifty ETF, total return incl. its fee), from 2005.
  - Stored in `data/s4.duckdb`.
  - Symbols with no Yahoo data are listed and skipped. TMPV, ETERNAL and JIOFIN have short histories by nature.
- **Sanity check before use:** Yahoo vs the snapshot's daily closes 2021–26, compared on day-to-day returns. A stock with > 1% of days differing by > 2 percentage points is reported and **excluded**.
- **Known bias (cannot be removed with free data):** **survivorship.** Today's members are, by construction, the past winners, so *any* long-only portfolio of them looks too good in the past. The test therefore judges each factor **against an equal-weight portfolio of the same universe**, which carries the same bias. Only the *excess* over it counts as evidence of a factor edge. Beating the Nifty is reported but is **not sufficient** on its own.
- **No fundamental data**, so **quality / value factors are not tested.**

## Rules (textbook definitions; nothing tuned)
- **Rebalance:** on the **last trading day of each month**, ranked on that day's close. Trades at the **next trading day's close** (one-day lag). Eligible = at least 273 trading days of history on the ranking day.

| Id | Factor | Ranking | Portfolio |
|---|---|---|---|
| **F1** | Momentum 12-1 | Return from 252 to 21 trading days ago (skips the last month) | Top **10**, equal weight |
| **F2** | Low volatility | Stdev of the last 252 daily returns, lowest first | Lowest **10**, equal weight |
| **F3** | Combination | Average of the F1 rank and the F2 rank | Top **10**, equal weight |

- **Regime-filtered variants F1R / F2R / F3R:** the same portfolios, but **100% cash** for the coming month when the Nifty's close on the ranking day is **below its 200-day SMA**. This is the classic drawdown control and serves the owner's "controlled loss" goal. Cash earns 0% (conservative).
- **Control EW:** equal weight of all eligible members, rebalanced monthly with the same costs.
- **Benchmarks:** NIFTYBEES buy-and-hold (total return), and ^NSEI buy-and-hold (price only).

## Costs (per side, as a fraction of traded value; Groww delivery, ~₹20k per position)
- **Buy 0.30%:** brokerage ₹20 ≈ 0.10%, stamp 0.015%, exchange and SEBI charges, GST, plus 0.05% slippage, plus STT 0.1%.
- **Sell 0.40%:** the same, plus DP charges (₹20 + GST per scrip).
- Charged only on weight actually traded at each rebalance.
- **Robustness:** 2× costs. Results are **pre-tax**. Monthly turnover means mostly short-term gains (20% STCG); the after-tax effect is estimated in the report.

## Test
- **Periods:**
  - **P-old** = 2007-01-01 → 2020-12-31;
  - **P-recent** = 2021-01-01 → 2026-09-30.
- **Equity:** compounds in each period from ₹2,00,000 (the premium scorecard is fed the daily change in equity).
- **PASS per period (each strategy):**
  - CAGR > **EW control** CAGR (the survivorship-neutral test), at 1× **and** 2× costs;
  - CAGR > NIFTYBEES buy-and-hold CAGR;
  - monthly Sharpe > EW's;
  - **for the R variants only** (the controlled-loss claim): max drawdown ≥ **−25%** and worst month ≥ **−10%**.
  - Base variants report their drawdown, but it isn't a pass criterion: a long-only portfolio without a filter can't stay within −25% in 2008.
- **ROBUST:**
  - PASS in both periods;
  - excess over EW positive in **≥ 60% of calendar years** across both periods;
  - still beats EW **without its 3 biggest contributing stocks** (they are removed from the universe and the strategy is rerun).
- **Multiple testing:** 6 strategies × 2 periods. A single-period pass is only a lead.

**Outcome:**
- ROBUST → a paper-portfolio candidate in premium (monthly rebalance; live paper tracking to be built), with the owner's approval.
- Otherwise → failed, with the reason.

## Implementation notes (committed with the code, 2026-10-05, BEFORE any result was run)

These come from the data-quality check only; no strategy output had been seen.

1. **Universe** = 49 stocks: the snapshot has 50 stock symbols, but **BSE is not a Nifty 50 member** (the Nifty system added it for its stock pilot), so it is dropped. The "52" in the rules above was a miscount.
2. **Cross-check against the snapshot (2021–26):** all 49 stocks have ≤ 0.83% of days differing by > 2 percentage points, under the 1% exclusion bar, so **none are excluded**.
3. **Yahoo faults found and the fixes, set before any result:**
   - a glitch on **2005-07-28/29** across ~15 stocks → **data before 2005-08-01 is dropped** (warm-up only);
   - **(b)** where the snapshot overlaps (Oct 2021 onward), a day on which Yahoo's return differs from the snapshot's by > 10 pp **takes the snapshot's return**. Example: TRENT on 2026-01-01 is −33% in Yahoo (a mis-applied adjustment) but +0.4% in the snapshot.
   - **(c)** elsewhere, any one-day |return| > **35%** → 0, as an unadjusted corporate action or bad print. Cases: the Bajaj Auto/Finserv demerger 2008, the Adani Enterprises demerger 2015, L&T 2006, Nestlé 2010, NIFTYBEES' 2019 split glitch, TMPV's demerger on 2025-10-14. Real 2008 moves (Hindalco +32%, JSW +34%) are below 35% and stay.
   - The counts of fixes are printed by the runner.
4. **Benchmark:** NIFTYBEES (total return) exists only from 2009-01-02. Before that: ^NSEI price return + 1.2%/yr dividend estimate.
5. **The regime signal** uses ^NSEI price (close vs its 200-day SMA) on the ranking day.
6. **Execution:** rank at month-end close i; trade at close i+1; weights drift between rebalances. Costs apply to traded weight: buy 0.30%, sell 0.40%, ×2 for robustness. Cash earns 0%.
7. **The ROBUST "without top 3" test:** the 3 stocks with the largest cumulative contribution (weight × return, 2005–26) are removed from the universe. Both the strategy and EW are rerun; the strategy must beat EW in both periods.

## Result (run 2026-10-05 09:29, `data/results/s4_20261005_0929`; code committed before the run as `c7e3361`): NONE ROBUST, with one single-period lead (F1R)

Data fixes applied: 14 days took the snapshot's return; 21 days with moves over 35% were set to 0.

| Strategy | P-old 2007–2020: CAGR (2×) / max DD / Sharpe | P-recent 2021–Sep 2026: CAGR (2×) / max DD / Sharpe | Pass old / recent |
|---|---|---|---|
| Nifty TR (benchmark) | 9.7% / −59.5% / 0.54 | 10.0% / −16.1% / 0.79 | n/a |
| **EW control** (same biased universe) | **19.6%** (19.3) / −56.4% / 0.89 | **19.7%** (19.4) / −17.3% / 1.32 | n/a |
| F1 momentum | 21.2% (**18.6** < EW) / −60.6% / 0.93 | 22.5% (19.9) / −22.5% / **1.23** < EW | ✗ / ✗ |
| F2 low-vol | 16.5% / −37.6% / 1.03 | 8.3% / −17.8% / 0.64 | ✗ / ✗ |
| F3 combo | 18.7% / −36.1% / 1.09 | 10.0% / −24.9% / 0.71 | ✗ / ✗ |
| **F1R** momentum + regime | **16.0%** < EW / **−24.9%** / 1.11 | **23.7%** (21.2) / **−16.0%** / **1.58** | ✗ / **✓** |
| F2R | 11.1% / −14.6% / 1.03 | 5.9% / −16.0% / 0.63 | ✗ / ✗ |
| F3R | 11.7% / −22.3% / 0.98 | 10.6% / −18.8% / 0.93 | ✗ / ✗ |

**ROBUST checks:**
- Years beating EW: F1 50%, F1R 45%, all others ≤ 30%.
- **No strategy beats EW once its 3 biggest contributors are removed.** For F1/F1R those are Adani Enterprises, Bajaj Finance and Eicher Motors.

**Reading:**
1. **The universe's own result is the warning.** Equal weight of *today's* Nifty 50 made ~19.6% a year, twice the Nifty's ~10%. That gap is mostly **survivorship**: today's members are yesterday's winners. A test that ignored it would have "found" a 20%/yr strategy in every row.
2. **Low volatility (F2, F2R) and the combination (F3, F3R) lose to EW in both periods.** Rejected.
3. **Momentum (F1) beats EW in raw CAGR in both periods, but not robustly.** In P-old it falls below EW at 2× costs (turnover ~24% a month), and its P-recent Sharpe is below EW's. Its edge depends on 3 stocks.
4. **F1R is the one interesting result:**
   - **P-recent PASS:** 23.7% CAGR, max DD −16%, worst month −9.8%, Sharpe 1.58.
   - **P-old FAIL on CAGR:** 16.0% vs EW 19.6%. But on risk it was far better: max DD **−24.9% vs −56.4%**, Calmar 0.64 vs 0.35, Sharpe 1.11 vs 0.89. The regime filter did its job in 2008 (+50 pp vs EW that year) and then cost a lot in the 2009 rebound (−72 pp).
   - It doesn't survive removing its top 3 stocks, and momentum is the factor *most* flattered by survivorship (it buys stocks during the rises that later put them in the index).
5. **Verdict:**
   - **S4 is not ROBUST.** The pre-declared rule makes it a **failure**, with **F1R recorded as a single-period lead**.
   - Its risk profile (about −25% worst drawdown in 2008, −16% since 2021) is the closest premium has come to the owner's "steady with controlled loss" goal, but its edge is unproven once survivorship is accounted for.
   - **Latest signal (Sep 2026 month-end):** Nifty is below its 200-day SMA, so **F1R is 100% cash.**

**What could legitimately settle F1R (not done; needs the owner's decision):**
- **(a)** Rebuild the *historical* Nifty 50 membership (NSE's index-change press releases since 2007) and rerun the same frozen rules without survivorship. This is the decisive test.
- **(b)** Forward paper-track F1R monthly. It is cheap (one rebalance a month), but slow: a year gives only 12 data points.
