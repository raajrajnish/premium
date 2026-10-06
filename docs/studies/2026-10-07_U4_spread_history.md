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

## Result (run 2026-10-07; script committed before the run as `f1de14d`): LEAVE IT

| Period | Trades | Win % | Avg ₹ after costs | Avg ₹ before costs | Total ₹ | Payoff | PF | Worst day | Quarter-Kelly |
|---|---|---|---|---|---|---|---|---|---|
| All | 301 | 19% | −186 | −24 | −56,060 | 1.01 | 0.23 | −2,753 | −0.155 |
| Jul | 106 | 23% | −155 | +7 | −16,443 | 1.18 | 0.34 | −2,031 | −0.108 |
| Aug | 98 | 15% | −198 | −36 | −19,440 | 0.90 | 0.16 | −1,706 | −0.196 |
| Sep | 97 | 18% | −208 | −46 | −20,177 | 0.83 | 0.18 | −2,753 | −0.203 |

Exit reasons: Chandelier 234, loss cut 19, time 18, thesis break 15, target 15. About 4.8 trades/day over 63 days.

**Reading:**
1. **Fails every pre-declared condition** (negative after costs in all 3 months; PF 0.23). Under the rule, the history estimate is **not used** for U4 sizing.
2. **The 1-min version is not the same strategy as live U4.**
   - Here 234 of 301 trades exited on the Chandelier trail and only 15 reached fair value.
   - In the full-quality replays of recorded live days (5–6 Oct: 16 trades, +₹1,211, 38% wins, payoff 2.9), 9 of 16 reached fair value and 2 hit the Chandelier.
   - A 1-min candle's range (≈ 10–15 pts) is about the size of the 3σ trail, and the spread's 1–3 minute dislocations can't be resolved at 1-min steps.
   - **History can neither confirm nor reject S-SPREAD as it runs live.**
3. **Decision:** U4's would-be Kelly uses live trades plus full-quality replays of recorded live days only. S-SPREAD is judged live.
