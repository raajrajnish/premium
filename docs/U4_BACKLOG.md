# U4 backlog: what's still to build or refine

Status as of **2026-10-07** (U4 v0.1). Every item needs the owner's explicit go-ahead before it's built; any rule change becomes a new dated version in `docs/U4_README.md`. For each item: what it is, why, what it depends on, when to pick it up.

## A. Planned, not built yet

### A1. Real position sizing (Phase 3)
- **What:** trade 1–3 lots using quarter-Kelly × a volatility target, instead of a fixed 1 lot.
- **Now:** computed and logged as "would-be lots" only. The estimate uses live trades plus full-quality replays of recorded live days (`data/u4/replay/`). As of 2026-10-07: S-SPREAD 16 trades, quarter-Kelly ≈ 0.04 → 1 lot; S-FLOW 1 trade.
- **Depends on:** ≥ 30 trades per strategy (live + full-quality replays) and **owner approval**.
- **Notes:**
  - 1-minute history is **not** usable for the estimate (`docs/studies/2026-10-07_U4_spread_history.md`).
  - Keep the 3-lot cap and the drop to 1 lot when volatility is > 1.5× its daily median.
  - Recheck that the Kelly inputs (win rate, payoff) are stable across days before switching on.

### A2. Cross-engine judge (Phase 4): Deflated Sharpe Ratio and PBO
- **What:** across every variant of U1–U4 (about 25 configurations), compute the **Deflated Sharpe Ratio** (corrects for the number of variants tried) and the **Probability of Backtest Overfitting** (combinatorially symmetric cross-validation over live days). This separates skill from luck.
- **Why:** with this many variants, some will look good by chance. This is the main guard against fooling ourselves.
- **Depends on:** a few live days of results (meaningful from about 5+ days; better at 10–20).
- **Where:** a new section in the daily review, plus a dashboard table.

### A3. Sortino ratio and expectancy in the scorecards
- **What:** add expectancy (p × average win − (1 − p) × average loss) and the Sortino ratio to the dashboard and review for every engine and variant.
- **Effort:** small. **Depends on:** nothing.

### A4. Bai–Perron structural-break analysis (after the close)
- **What:** in the daily review, find where the day's regime changed (Nifty's mean and variance, and the Kalman spread's behaviour) without fixing the dates in advance.
- **Why:** shows whether U4's trades happened in stable stretches or across breaks, and checks the S-SPREAD thesis.
- **Depends on:** nothing (analysis only).

## B. Simplified in v0.1, to make fuller later

### B1. Formal CUSUM "thesis break" exits
- **Now:** fixed thresholds: order flow reversed for 20 s (z ≤ −1.5), an opposite Hawkes cascade, or the spread widening to \|z\| ≥ 3.5.
- **Fuller:** a **CUSUM test on recursive residuals** of the model behind the trade (the Kalman spread model for S-SPREAD; an order-flow → price regression for S-FLOW), with proper confidence bands.
- **Pick up when:** the review shows thesis-break exits firing too early or too late.

### B2. Micro-price for entry timing
- **Now:** only **slippage is logged** (fill vs the option's micro-price, from top-5 depth).
- **Fuller:** decide "buy now or wait a few seconds" from the option's micro-price and spread (e.g. wait when the micro-price is below the ask by more than a threshold, up to N seconds).
- **Pick up when:** the logged slippage shows money left on entries.

### B3. Bivariate Hawkes on real trade events
- **Now:** separate up and down models, fitted on a grid, using Nifty price ticks (≥ 0.5 pt moves) as events. The fit sits at the edge of the grid (branching ≈ 0.98, decay ≈ 100 s), meaning strong clustering.
- **Fuller:** a **two-way model** (buys exciting sells and vice versa) fitted on **actual trade events** by full maximum likelihood, with a finer grid or an optimiser.
- **Depends on:** event-level data (see C2) for the real version.

### B4. S-SPREAD: "gap closed by the heavyweights, not Nifty"
- **Seen on replays:** some trades reached fair value (z back to 0) **at a loss**, because the heavyweights moved rather than Nifty.
- **Possible refinements (to test, not decided):**
  - require that Nifty itself has moved toward fair value before counting the target;
  - weight the exit by the option's price, not only by z;
  - enter only when the heavyweights' recent move is stable (they led, Nifty lags).
- **Tracked daily** by the review line "SPREAD target reached at a loss".

### B5. S-FLOW fires rarely
- **Seen:** 1 trade over 2 recorded days. All three conditions together (MLOFI z ≥ 2.5, lean z ≥ 1, cascade ≥ 2) are rare.
- **Possible refinements (to test via variants, not decided):** require 2 of 3 conditions plus option-book pressure; or loosen the cascade to ≥ 1.5. Use the factor scorecard first to see which of the three features actually lead Nifty.

## C. Needs new data (owner's decision)

### C1. Cross-asset order flow (Bank Nifty futures leading Nifty)
- **Blocked:** the recorder doesn't capture Bank Nifty futures quotes.
- **Needs:** either a change to the Nifty system's recorder (not allowed without the owner), or a **separate premium recorder** (C2).

### C2. A faster, event-level order-book recorder (in premium)
- **What:** a separate recorder in premium capturing **every** order-book update (and trades) for Nifty futures, ATM options and Bank Nifty futures, instead of 10-second snapshots.
- **Why:** true order-flow imbalance and Hawkes models are defined on events. This would strengthen F1–F4 the most.
- **Costs:** uses the Groww token and API/websocket capacity; more disk; must never interfere with the Nifty system's recorder.
- **Pick up when:** U4's features show promise in the live factor scorecard on the current feed.

## D. Not worth building now

### D1. Almgren–Chriss optimal execution
- Splitting an exit into pieces is pointless at 1–3 lots of a liquid Nifty option. Revisit only at much larger size.

## E. Known facts to remember
- Only **5 and 6 Oct** (and later days) have all U4 inputs. Before 5 Oct the recorder had no heavyweights (Bank Nifty, HDFC Bank, ICICI Bank) prices.
- **Kalman δ = 10⁻⁹** per 10 s and the **cascade measured against λ̄** were set before the first run. The reasons are in `docs/U4_README.md`.
- **First scorecard reading (6 Oct, one day):** none of U4's features clearly led Nifty over 3 minutes; Hawkes direction leaned slightly the wrong way (ρ −0.14). Watch this over several days before changing anything.

### E2. What the published evidence implies for U4 (owner's note, 2026-10-07)
- **The methods work empirically, but only with institutional-grade data** (tick-by-tick order-book events) and strict statistical controls against overfitting.
- **OFI mostly explains the price change in the same interval.** The studies show a robust, linear link between OFI and the price change at the same time. Predictive power for the **next** move is much weaker and decays within seconds. A trading edge from OFI needs acting within seconds on event-level data. That fits U4's first scorecard reading (little 3-minute predictive power on 10-second snapshots).
- **The Hawkes results on NSE used tick data.** Our price-tick stand-in (about 2 s) is an approximation (see B3).
- **Overfitting is the main live-failure risk**, so the **DSR/PBO judge (A2) is required**, not optional: about 25 variants run across U1–U4.
- **CPCV** is designed for long histories. Under our live-data approach, its equivalent is purged cross-validation **across live days** once there are enough (part of A2).
- **Almgren–Chriss** impact holds up for large institutional orders. It is irrelevant at 1–3 lots (D1 stays parked).
- **Main implication:** our binding limit is **data resolution and cost**, not the formulas. If U4's features show any lead in the live factor scorecard, **C2 (an event-level recorder in premium)** is the highest-value upgrade. Institutional edge from these methods also relies on speed and low costs, which is why the U5 ideas focus on costs and the slower pendulum effect.

## Suggested order
1. **A3** (small, useful now).
2. **B2** (if slippage shows money left on the table).
3. **A2** (after 5+ live days).
4. **A4** and **B1**.
5. **B4** and **B5** (driven by daily-review evidence).
6. **A1** (at 30+ trades, with approval).
7. **C1/C2/B3** (only if U4's features show promise).
8. D1 stays parked.
