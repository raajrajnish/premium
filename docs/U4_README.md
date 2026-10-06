# U4: microstructure and relative-value engine (Nifty options, PAPER ONLY)

The **single source of truth** for U4. Code follows this file. Changes are dated versions, approved by the owner.
Basis: the owner's research note "Architecting Mechanical Alpha" (2026-10-06) and the build plan agreed the same day.

| Version | Valid from | Summary |
|---|---|---|
| **v0.1** | **2026-10-07** (first session) | Phases 0–2: features (multi-level OFI, option-book pressure, micro-price lean, Hawkes intensity, Kalman Nifty-vs-heavyweights spread, Yang–Zhang volatility); strategies S-FLOW and S-SPREAD; thesis-break, Chandelier, half-life and loss-cut exits. **1 lot**: Kelly sizing is computed and logged only. |

## 1. Principles
1. **Live data only.** The recorder's files, read-only. Previous live days are used only to fit the Hawkes parameters (each evening).
2. **Separate.**
   - Own code: `scripts/u4_core.py` (a copy of U3's core, extended with option order-book depth), `u4_features.py`, `u4_watch.py`.
   - Own files: `data/u4/`; own dashboard section.
   - Nothing in U1–U3 or the Nifty system changes.
3. **One instrument:** trades **Nifty options only**. Bank Nifty, HDFC Bank and ICICI Bank are **signals only**.
4. **Paper only. Explainable:** every decision logs its feature values and the reason.
5. **Data limits (stated honestly):** quotes arrive about every 10 s (5 depth levels) and prices about every 2 s, with no trade-by-trade records. Order-flow and Hawkes signals are therefore **approximations**, used for minute-scale decisions.

## 2. Features (computed live; "+" = upward pressure on Nifty)

| Code | Feature | Definition |
|---|---|---|
| **F1** | **Multi-level OFI (futures)** | For each of the 5 depth levels, Cont–Kukanov–Stoikov event contribution e_l (bid level up or unchanged: +q; down: −q_prev; ask level down or unchanged: −q; up: +q_prev). MLOFI = Σ e_l, summed over **60 s**, ÷ the average total depth (30 min). **z-score vs the last 30 min.** |
| **F2** | **Option-book pressure** | Across ATM ± 2 strikes, each option's top-5 book imbalance (buy − sell) ÷ (buy + sell). Pressure = mean(CE imbalance) − mean(PE imbalance), smoothed over 60 s. **z vs the last 30 min.** |
| **F3** | **Micro-price lean (futures)** | I = bid_qty ÷ (bid_qty + ask_qty). Micro-price = ask·I + bid·(1 − I). Lean = (micro − mid) ÷ spread (from −0.5 to +0.5), averaged over 60 s. **z vs the last 30 min.** |
| **F4** | **Hawkes intensity (up / down)** | Events: Nifty up-ticks and down-ticks (\|change\| ≥ 0.5 pt between live prices). Per side, a univariate Hawkes model with an exponential kernel: λ(t) = μ + Σ α·e^(−β(t − tᵢ)). (μ, α, β) are fitted by **maximum likelihood (grid search)** on up to the **3 previous live days**, with stability α/β < 1 (grid: β 0.002–1.0 per s, branching n 0.05–0.98). Live: **cascade ratio** = λ_side ÷ λ̄_side, where λ̄ = μ ÷ (1 − n) is the long-run average rate, and **direction** log(λ_up ÷ λ_down). *Set before the first run: the fit showed strong clustering (n ≈ 0.9), so λ ÷ μ sat around 10–18 all the time; measuring against λ̄ makes "≥ 2" mean twice normal activity.* |
| **F5** | **Kalman spread (Nifty vs heavyweights)** | Every 10 s: y = ln(Nifty), x = [1, ln BankNifty, ln HDFC, ln ICICI]. The hedge ratios β follow a random walk (Kalman filter, **δ = 10⁻⁹**: slow adaptation; *set before the first run: on 5–6 Oct, faster settings (10⁻⁵ to 10⁻⁸) tracked Nifty so closely that the spread was noise with a half-life under a minute; at 10⁻⁹ the spread was 10–30 pts with a 1.5–3.5 min half-life*). Innovation z = prediction error ÷ √(its variance). **z > 0 = Nifty rich** relative to its heavyweights. Half-life = −ln 2 ÷ ln φ, from an AR(1) of the last 60 min of innovations. |
| **F6** | **Yang–Zhang volatility** | On 5-min Nifty bars over the last 60 min: σ²_YZ = σ²_o + k·σ²_c + (1 − k)·σ²_RS, with k = 0.34 ÷ (1.34 + (n + 1)/(n − 1)). Expressed as **σ per 1 min in Nifty points** (σ1m). |

## 3. Strategies (signals 09:45–14:30; one position per strategy)

### S-FLOW: enter when order flow, micro-price and trade intensity all agree
- **CALL** when: F1 z ≥ **+2.5** **and** F3 z ≥ +1 **and** F4 up-cascade ratio ≥ **2** with λ_up > λ_down **and** F2 z ≥ 0. **PUT:** the mirror.
- **Exits** (whichever comes first):
  - **thesis break:** F1 z × side ≤ −1.5 held for 20 s, **or** an opposite cascade (ratio ≥ 2 and λ_opp > λ_side);
  - **Chandelier:** Nifty retreats **3 × σ1m** from its best point since entry;
  - **loss cut:** Nifty moves against by **2 × σ1m × √5** (a 2-σ, 5-min move);
  - **time:** 10 min if not in profit (never while in profit);
  - safety and hard rules (§4).

### S-SPREAD: trade Nifty back toward fair value against its heavyweights
- **Entry:** \|F5 z\| ≥ **2.0** **and** half-life ≤ **15 min** **and** the model is stable (no thesis break in the last 5 min). Nifty rich (z ≥ +2) → **PUT**; Nifty cheap (z ≤ −2) → **CALL**.
- **Exits:**
  - **target:** \|z\| ≤ 0.5 (back to fair value);
  - **thesis break:** the dislocation keeps growing, \|z\| ≥ 3.5 in the same direction (the relationship has broken);
  - **time:** 2 × half-life (5–20 min);
  - **Chandelier** and **loss cut** as in S-FLOW;
  - safety and hard rules.

## 4. Common rules
- **Fills:** 1 lot (65) of the ATM option (nearest expiry), bought at the **ask**, sold at the **bid** (last price ± ₹0.5 without a fresh quote). Charges ₹1.5/unit. **Slippage logged:** the fill vs the option's micro-price at that moment.
- **Safety:** option −25% → exit; no live price for 60 s → exit at the last bid; hard exit 15:10 (14:45 on expiry day).
- **Risk, per strategy:** daily loss cap −₹2,000/lot; max 8 trades/day; 3 losses in a row → 30-min pause.
- **Sizing (Phase 3, logged only in v0.1):** quarter-Kelly f = 0.25 × (p − (1 − p) ÷ payoff), from that strategy's completed live trades, × a volatility target (today's σ1m vs its median). Shown as "would-be lots" (1–3). *The estimate uses live trades plus **full-quality replays of recorded live days** (same rules, same data; `data/u4/replay/`). It does **not** use 1-minute history: the 2026-10-07 study found that 1-min candles are too coarse to reproduce S-SPREAD (see `docs/studies/2026-10-07_U4_spread_history.md`).* **Real sizing switches on only after ≥ 30 trades per strategy, with the owner's approval.**

## 5. Variants (independent paper engines on the same feed)

| Variant | Differs from MAIN |
|---|---|
| **MAIN** | as above |
| FLOW-z2 / FLOW-z3 | S-FLOW's F1 threshold 2.0 / 3.0 |
| SPREAD-1.5 / SPREAD-2.5 | S-SPREAD's \|z\| entry 1.5 / 2.5 |

## 6. Records (`premium/data/u4/`)
- `<day>_trades.csv`: every trade of every variant, with the features at entry, exit reason, best/worst, slippage vs the micro-price, would-be Kelly lots, and ₹.
- `<day>_decisions.csv`: every signal and its outcome.
- `<day>_features.csv`: per minute, F1–F6, for the live factor scorecard (Q6).
- `<day>_hawkes.json`: the fitted Hawkes parameters used that day.
- `state.json`: for the dashboard.

## 7. Judgement and next phases
**Everything still to build or refine is listed in `docs/U4_BACKLOG.md`** (what, why, dependencies, suggested order).

- The daily review covers U4 (per strategy, per variant), and its features join the **live factor scorecard**.
- **Next (Phase 4, separate approval):** a cross-engine judge, Deflated Sharpe Ratio and PBO over all variants of U1–U4.
- **Later (Phase 3):** real Kelly sizing after ≥ 30 trades per strategy.
- **Possible later step (owner's decision):** a faster order-book recorder in premium.

## 8. Daily operation
Start the **U4 watcher** ("premium U4 watch (paper)": `uv run python scripts/u4_watch.py`) alongside U1–U3 after Start Trading. It stops by itself at 15:12.
