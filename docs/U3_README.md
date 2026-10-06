# U3: research-based regime engine (Nifty options, PAPER ONLY)

The **single source of truth** for U3. Code follows this file. Changes are dated versions, approved by the owner.
Basis: `docs/research/2026-10-06_intraday_index_research.md` (proposals P1–P8).

| Version | Valid from | Summary |
|---|---|---|
| **v0.1** | **2026-10-07** (first session) | All of P1–P8 in MAIN. One "minus one" ablation variant per idea, so live data shows which ideas earn their place. Starting values below, not tuned. |

## 1. Principles
1. **Live data only.** Same feed as U1/U2 (the recorder's files, read-only). Previous live days are used only for "normal" levels (e.g. opening volume).
2. **Separate.**
   - Own code: `scripts/u3_core.py`, a copy of U2's core taken 2026-10-06 (so U1/U2 changes never affect U3), plus `u3_context.py` and `u3_watch.py`.
   - Own files: `data/u3/`. Own dashboard section.
   - It **reads U2's morning news card** (`data/u2/<day>_morning.json`, read-only) to avoid a second LLM call.
3. **Paper only. Explainable:** every decision logs its regime, context and reasons.
4. **Ablations:** MAIN uses every idea. Each "no-X" variant is MAIN with one idea switched off. An idea earns its place if MAIN beats its "no-X" variant over enough live days.

## 2. Context measured live (used by every strategy)

| Code | Context | How it's measured |
|---|---|---|
| **P2** | **Order-flow imbalance (OFI)** | From Nifty futures quotes (~10 s), Cont–Kukanov–Stoikov best-level OFI: bid side +q_bid if the bid rose or held, −q_bid(prev) if it fell; ask side mirrored. Summed over **60 s**, divided by the average top-of-book depth. Plus **depth imbalance** (top-5 buy − sell) ÷ (buy + sell). **Positive = buying pressure.** Its z-score against the last 30 min is used. |
| **P3** | **Dealer-gamma regime and walls** | From each option-chain snapshot (1 min): net gamma exposure proxy **GEX = Σ (Γ_CE × OI_CE − Γ_PE × OI_PE) × spot² × 0.01** (convention: dealers long calls, short puts). **GEX > 0 → "dampening"** (fades favoured, pinning); **GEX < 0 → "accelerating"** (trends favoured). Walls = the strike with the most CE OI above spot, the most PE OI below, and the strike with the highest total gamma × OI ("magnet"). |
| **P4** | **In-play day** | True if any of: \|opening gap\| ≥ **0.5%** (U2 news card + first price); event risk **high** (news card); futures volume 09:15–09:30 ≥ **1.5 ×** its average over the previous live recorded days. |
| — | **Initial balance (IB)** | Nifty high and low 09:15–10:15. |
| **P1** | **Day type** (from 10:15; before that UNKNOWN) | **TREND-UP:** price beyond the IB high by ≥ 25% of the IB range **and** futures above VWAP **and** (in-play **or** GEX < 0). **TREND-DOWN:** the mirror. **RANGE:** price inside the IB **and** GEX > 0. Otherwise **MIXED**. Re-evaluated every minute. |
| **P6** | **Time of day** | OPEN 09:15–10:15 · MID 10:15–11:30 · **LULL 11:30–13:30** · LATE 13:30–14:45 · CLOSE 14:45–15:10 |
| **P5** | **Option-cost gate** (+ implied move, logged) | The move a trade needs = (ATM option's decay over the hold H, from the chain's theta per day × H ÷ 375, + ₹1.5 charges + ₹0.5 spread) ÷ 0.5 delta, in Nifty points. The IV-based implied move (spot × IV × √(H ÷ (252 × 375))) is logged for reference. *Changed before the first run (2026-10-06): near expiry the chain's IV overstates the per-minute move (≈ 60 pts in 10 min on 6 Oct), so the IV gate would block every trade. The theta + costs gate measures what the option actually costs to hold.* |
| — | **Pendulum** | Live swing size and duration (6-pt turning points, last 30 min), as in U2. |

## 3. Strategies

### S-FADE (P1, range days): fade short-term extremes back toward the mean
- **Allowed:** day type **RANGE** (MIXED counts only if GEX > 0), from 10:15 to 14:30. Midday lull **allowed** (fades suit quiet markets).
- **Signal:** Nifty's distance from its 20-min mean is ≥ **2 ×** its 1-min standard deviation (an extreme) **and** OFI no longer pushes the extreme (OFI z against the extreme direction ≤ 0) → buy the option **against** the extreme (spike up → PUT; spike down → CALL).
- **Target:** back to the 20-min mean. **Stop:** a further extension of **one live swing**. **Time:** 10 min. Hard 15:10 (14:45 on expiry day).
- **P5 gate:** the distance to the mean must exceed the option-cost points for a 10-min hold. Otherwise skip ("move too small for the option's cost").

### S-TREND (P1, trend days): pullback in the day's direction, held 30–60 min
- **Allowed:** day type **TREND-UP / TREND-DOWN**, from 10:15 to 14:30, **not in the LULL** (P6). **P4:** in-play days only.
- **Signal:** a pullback toward the 1-min EMA 20 (a close within 0.25 swing of it, or crossing it) followed by a **resumption** (a 1-min close back beyond the previous candle's extreme in the trend direction) **with OFI z ≥ 0** (P2).
- **Exit:** a trail of **1.5 live swings** from the best price; regime change (day type no longer TREND that way) → exit; **max 60 min**; hard 15:10 / 14:45.
- **P5 gate:** the expected move (2 live swings) must exceed the option-cost points for a 30-min hold.

### S-LAST (P7): last-half-hour momentum
- **First-half-hour return** = Nifty at 09:45 vs the first price ≥ 09:15. If \|return\| ≥ **0.10%**, at **14:45** buy the ATM option in that direction; exit at **15:10** (14:45 on expiry day → skip that day).
- Logged with whether the day was volatile or in-play (the research says the effect is stronger then).

## 4. Common rules
- **Fills:** 1 lot (65) of the ATM option (nearest expiry), bought at the **ask**, sold at the **bid** (last price ± ₹0.5 if there's no fresh quote). Charges ₹1.5/unit.
- **One position per strategy** at a time. Strategies are independent of each other.
- **P8 risk layer, per strategy:**
  - **daily loss cap −₹2,000/lot**: no new entries that day after it's reached;
  - **max 6 trades/day**;
  - **3 losses in a row → 30-min pause**.
- **Safety exits (all strategies):** option −25% → exit; no live price for 60 s → exit at the last bid.

## 5. Variants (each runs as an independent paper engine on the same feed)

| Variant | Differs from MAIN |
|---|---|
| **MAIN** | all ideas on |
| noOFI | P2 off: no OFI conditions |
| noGAMMA | P3 off: day type ignores GEX (RANGE = inside IB; TREND needs in-play only) |
| noINPLAY | P4 off: S-TREND allowed on any day |
| noIV | P5 off: no implied-move gate |
| noTOD | P6 off: S-TREND allowed in the lull |
| noRISK | P8 off: no loss cap, trade limit or pause |

S-LAST has no ablation (it's a single rule).

## 6. Records (`premium/data/u3/`)
- `<day>_trades.csv`: every trade of every variant, with its strategy, regime, GEX, OFI z, in-play flag, time-of-day zone, implied move vs expected move, the exit reason, best/worst while open, and ₹.
- `<day>_decisions.csv`: every strategy signal and its outcome (ENTER, or SKIP with the gate that blocked it).
- `<day>_context.csv`: per minute, the day type, GEX, walls, OFI z, in-play flag and IB.
- `state.json`: for the dashboard.

## 7. Judgement
The same daily review (`/u1-daily-review`) covers U3:
- **per strategy**;
- **MAIN vs each ablation** (which idea helps);
- whether the regime calls were right (did RANGE days actually stay in range?).

Nothing in MAIN changes without live evidence and the owner's approval.

## 8. Daily operation
Start the **U3 watcher** ("premium U3 watch (paper)": `uv run python scripts/u3_watch.py`) alongside U1/U2 after Start Trading. It stops by itself at 15:12. The dashboard shows a U3 section.
