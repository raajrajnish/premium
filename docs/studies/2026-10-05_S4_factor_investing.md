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
