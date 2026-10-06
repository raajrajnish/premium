# U4 S-SPREAD on 1-minute history (PRE-DECLARED 2026-10-07, before running)

**Question (owner):** can history supply enough S-SPREAD trades (30+) to estimate win rate, payoff and a quarter-Kelly starting value, so sizing doesn't depend only on a few live trades? Use it only if it makes sense.

**Data:** premium's snapshot, 1-min candles, **2026-07-01 → 2026-09-29**: Nifty, Bank Nifty, HDFC Bank and ICICI Bank (the heavyweights end 2026-09-29), plus Nifty ATM weekly option candles. S-FLOW **cannot** be tested on history (no order book or ticks).

**Rules:** U4 v0.1's S-SPREAD exactly (`docs/U4_README.md` §3), adapted only for 1-minute steps:
- the Kalman filter runs on 1-min closes with **δ = 6 × 10⁻⁹** per step (the same random-walk variance per unit of time as U4's 10⁻⁹ per 10 s);
- the z-score is over the last 60 minutes;
- the AR(1) half-life is over the last 60 minutes, in minutes;
- Yang–Zhang σ comes from 5-min bars over 60 min.

**Simulation:**
- **Entry:** \|z\| ≥ 2.0 **and** half-life ≤ 15 min **and** no thesis break in the last 5 min, during 09:45–14:30 → buy the ATM option (rich → PUT, cheap → CALL) at the **next minute's open**.
- **Exits** (at 1-min steps; adverse checks use the minute's high/low first, the cautious order):
  - target \|z\| ≤ 0.5;
  - thesis break −side × z ≥ 3.5;
  - time 2 × half-life (5–20 min);
  - Chandelier 3σ1m from the best price;
  - loss cut 2σ1m√5;
  - option −25%;
  - hard 15:10 (14:45 on expiry day).
- **Fills:** at the option's candle prices. **Costs ₹2.5/unit** (₹1.5 charges + ₹1.0 spread/slippage), as in all earlier premium studies.
- **Risk:** daily loss cap −₹2,000; max 8 trades/day; a 30-min pause after 3 losses.

**Report:**
- trades, win %, average ₹, payoff (average win ÷ average loss), profit factor, worst day;
- **by month** (July, August, September separately) and before/after costs;
- quarter-Kelly f = 0.25 × (p − (1 − p) ÷ payoff).

**Decision rule (fixed now): "use it" only if all hold:**
- ≥ 30 trades;
- average ₹/trade > 0 after costs;
- **positive in at least 2 of the 3 months**;
- profit factor ≥ 1.2.

Then the historical win rate and payoff become the **starting estimate** for U4's would-be Kelly. They are blended with live trades by weight of trade count, with history counted at **half weight** (because of the 1-min coarseness and estimated fills). Real sizing still needs the owner's approval.

**Otherwise "leave it":** sizing waits for live trades only, and the result is recorded here.
