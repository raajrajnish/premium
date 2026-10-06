# U2: health-engine entry and exit (Nifty options, PAPER ONLY)

This file is the **single source of truth** for U2. Code follows this file. Any change is made here first, dated, and gets a new version. Only the owner changes rules.

| Version | Valid from | Summary |
|---|---|---|
| **v0.2** | **2026-10-07** (first session) | v0.1 plus the **news and events layer** (§10): a morning context card; MAIN only **logs** the news flags; a new shadow variant **NEWS** applies the rules. MAIN's decisions are identical to v0.1. |
| v0.1 | (built 2026-10-06; superseded by v0.2 before its first session) | Gate 1 = U1 v3 checklist (U2's own copy). Gate 2 + in-trade = live health engine with equal weights (no learned weights yet). Starting values as agreed on 2026-10-06. |

## 1. Principles (agreed with the owner, 2026-10-06)
1. **Live data only.** Decisions use the current day's live feed. Learned weights (later versions) come only from **previous live days** (the live factor scorecard), frozen during the day.
2. **Separate and independent from U1.**
   - Own code (`scripts/u2_core.py`, `u2_health.py`, `u2_watch.py`), with its own copy of the indicator code.
   - Own files (`data/u2/`), own rulebook (this file).
   - Shares only the recorder's live files (read-only) and the dashboard (its own U2 panel).
3. **Paper only.** No orders.
4. **Explainable.** Every decision records why: the health score, its state, and the top contributing factors.
5. **Shadow variants** of the key settings run alongside the main configuration. The owner chooses which settings become the next version, from live evidence.

## 2. Gate 1: "is there a setup?"
The U1 v3 checklist (see `docs/U1_README.md` §3–4, as of 2026-10-06), computed by U2's own copy:
- all **3 trend items** (futures above VWAP; EMA 9 vs 21 and EMA 9 slope on **3-min** candles);
- at least **1 of 2 triggers**;
- at least **3 of 5 confirmations**;
- only one side qualifying.

Evaluated at each 1-min close, for signals from **09:45 to 14:30**.

## 3. The health engine (computed on every live price, ~2 s)

**Raw factors.** Each is measured so "+" = good for a CALL; a PUT uses the negative.

| # | Factor | Speed | Raw value |
|---|---|---|---|
| 1 | Micro-momentum 30 s | ~2 s | Nifty now − 30 s ago |
| 2 | Micro-momentum 60 s | ~2 s | Nifty now − 60 s ago |
| 3 | Trend speed | ~2 s | Kalman-style (alpha–beta) filter velocity of Nifty, pts/min |
| 4 | Heavyweights | ~2 s | sum of Bank Nifty, HDFC Bank and ICICI Bank 60-s changes, in basis points |
| 5 | VIX | ~2 s | −(VIX now − 60 s ago) |
| 6 | Volume push | ~10 s | (futures volume in the last 60 s ÷ its 30-min average − 1) × direction of the 60-s move |
| 7 | Order book | ~10 s | log(futures total buy qty ÷ total sell qty), minus its 30-min average |
| 8 | Futures vs VWAP | ~10 s | change over 60 s of (futures − VWAP) |
| 9 | Options OI | 1 min | (ATM PE OI change − ATM CE OI change) over 5 min, in thousands |
| 10 | Trend structure | 1 min | (CALL trend boxes − PUT trend boxes) ÷ 3, from the last completed minute |
| 11 | Trigger | 1 min | +1 if a CALL trigger fired at the last completed minute, −1 if a PUT trigger, else 0 |

**Combining them:**
1. **Normalise:** factors 1–9 become z-scores against their own **last 30 minutes** (live, today), clipped to ±3.
2. **Weights (v0.1, equal):** 1 each for factors 1–9 and 11; **2 for trend structure** (factor 10, so a pause with the trend intact isn't read as failure). Health = weighted average.
3. **Smooth:** an exponential average with a 15-second half-life.
4. **States** (v0.1 starting values, to be calibrated from live data): **POSITIVE** ≥ +0.30; **NEGATIVE** ≤ −0.30; otherwise **NEUTRAL**.
5. **Persistence:** a state must hold continuously to count (§4 and §5).

**Pendulum (live swing):** turning points of Nifty ticks with a 6-pt threshold over the last 30 min, giving the average swing size (pts) and average swing time (s). An option swing ≈ 0.5 × the Nifty swing (ATM delta).

**CUSUM alarm (in trade):** adds up adverse Nifty tick moves beyond an allowance of 0.5σ (σ = the std of tick changes over the last 30 min). Alarm when the sum reaches **max(5σ, one live swing)**, so a normal swing against us never triggers it. Reset at entry.
  *Set before the first live run (2026-10-06): on a replay of 6 Oct, 5σ alone (≈ 8–10 pts) was smaller than a normal swing (10–15 pts) and closed 6 of 13 trades inside ordinary swings.*

## 4. Entry (the final gate)
When Gate 1 fires for side d (and U2 is flat), U2 goes into **WAIT** for that side:
- **ENTER** when health(d) has been **POSITIVE for ≥ 30 s** (main), **or** on a **re-confirmation** at a 1-min close (≥ 4 confirmations including the volume surge).
- **SKIP** if:
  - health(d) has been **NEGATIVE for ≥ 20 s**; or
  - at a 1-min close the trend boxes for d are no longer all green ("trend broke"); or
  - **5 minutes** have passed ("expired").
- A Gate-1 signal for the **opposite** side while waiting replaces the wait.
- Entries are allowed until 14:35.
- **Fill:** 1 lot (65) of the ATM option (strike nearest spot, nearest expiry), at the **ask** (last price + ₹0.5 if there's no fresh quote).
- One position at a time. A new signal can be taken at the next 1-min close after an exit.

## 5. Exit (checked on every live price; the first rule that applies wins)
P&L = (bid − entry fill − ₹1.5 charges) × 65. "In profit" = P&L > 0.

| Priority | Rule | Detail |
|---|---|---|
| 1 | **Safety** | option bid ≤ entry × (1 − **20%**) → "max loss"; 15:10 (14:45 on expiry day) → "hard"; no live price for 60 s → exit at the last bid ("feed") |
| 2 | **Opposite side** (at each 1-min close) | opposite checklist **fully valid** → exit. Opposite **EMA order + slope** turn green → exit, unless the option is > +10% (then lock: the floor rises to keep 75% of the peak gain). Opposite **trigger** fires → **tighten**: breathing 15%, and the floor is at least entry + charges once in profit |
| 3 | **Health against us** | health **NEGATIVE for ≥ 20 s** → exit; or the **CUSUM alarm** → exit |
| 4 | **Exhaustion** | in profit **and** health was POSITIVE within the last 2 min and is now below 0 **and**, at the last 1-min close, any of: RSI beyond 80 (CALL) / 20 (PUT), ≥ 2 of 3 heavyweights moving against over 3 min, volume ≥ 2.5× without a new 5-min extreme → take profit |
| 5 | **Profit trail** | active once the peak gain ≥ max(one option swing, ₹3). Floor = max(entry + charges, peak bid − max(one option swing, **25%** × peak gain)). Exit when the bid stays below the floor for 10 s |
| 6 | **Time** (only when **not** in profit) | no progress for **6 swing periods** (and the peak gain never reached one swing) → exit; 20 min without being in profit → exit. **No time exit ever applies while in profit.** |

## 6. Shadow variants (run in parallel; each is an independent paper engine on the same feed)

| Variant | Differs from main in |
|---|---|
| **MAIN** | — (enter 30 s, exit 20 s, breathing 25%) |
| E15 / E45 / E60 | entry persistence 15 / 45 / 60 s |
| X10 / X30 / X45 | exit persistence 10 / 30 / 45 s |
| B20 / B33 | breathing 20% / 33% |

## 7. Records (`premium/data/u2/`)
- `<day>_decisions.csv`: every Gate-1 signal and what the MAIN engine did with it (ENTER after how many seconds, or SKIP and why), with health at the signal.
- `<day>_trades.csv`: every trade of every variant, with the exit rule, best/worst while open, and health at entry and exit.
- `state.json`: the live gauge for the dashboard (health for CALL and PUT, state, held time, top factors, pendulum, the MAIN engine's status).

## 8. Comparison and refinement
- The dashboard shows U2 next to U1 (EC0–EC2+) for the same days.
- The daily review (`/u1-daily-review`) covers U2 too, and updates the **live factor scorecard** (Q6), which will supply learned weights in a later version once there is enough live evidence (≈ 30+ events per factor over ≥ 5 live days).
- Every change goes into this file as a new version, with the owner's approval.

## 9. Daily operation
1. **Start Trading** (Nifty system) starts the recorder.
2. Start the U1 watcher, the **U2 watcher** (window "premium U2 watch (paper)": `uv run python scripts/u2_watch.py`, stops by itself at 15:12) and the dashboard (http://127.0.0.1:8760; U2 has its own section below U1's).
3. After the close, run `/u1-daily-review`; it covers U1 and U2.

## 10. News and events (v0.2, owner 2026-10-06)

**Morning context card** (`scripts/u2_morning.py` → `data/u2/<day>_morning.json`). Built once in the background when the U2 watcher starts, then frozen for the day:
- **Events:** today's entries in the Nifty system's `config/event_calendar.yaml` (read-only) and premium's own `config/u2_events.yaml` (owner-maintained; put the time as "HH:MM IST"). Yesterday's US events marked "next session" are listed as overnight events.
- **Gap:** yesterday's close (from the recorder) vs today's first price at or after 09:15.
- **News read:** ONE headless Claude Code call (WebSearch only, owner's subscription, no API key) giving:
  - the news bias (positive / negative / mixed / unknown) and its confidence;
  - up to 5 headlines;
  - global cues (US close, Asia, crude, USD/INR, GIFT Nifty);
  - today's market-hours events with times;
  - the event risk (none / medium / high).
  If the call fails, the bias is "unknown" and the card records the error.
- **Event windows:** every event with a time during 09:15–15:30 → a no-entry window from **10 min before to 15 min after**.

**Rules.** MAIN logs them only. The **NEWS** variant applies them:

| Rule | NEWS variant |
|---|---|
| Event window | no new entries inside a window (an open wait continues, but can't enter until the window ends) |
| Before an event / VIX jump | an open trade is **tightened** within 2 min before an event time, or while the VIX guard is on (breathing 15%; the floor is at least entry + charges once in profit) |
| Large gap | if \|gap\| ≥ **0.5%**, signals before **10:00** are skipped ("large gap: before 10:00") |
| News bias | if the bias is positive or negative with confidence ≥ 0.5, trades **against** it need **45 s** of positive health instead of 30 s |
| VIX guard | if VIX's 60-s change is ≥ 3 standard units of its last 30 min (a sharp jump), no new entries for 5 min |

**Logged on every decision and trade, all variants** (`news_*` columns): whether it was inside an event window, the VIX guard, the gap %, whether the trade was with or against the gap, the bias, and whether the trade was with or against the bias. The daily review's **Q7** compares MAIN and NEWS and splits results by these flags. A rule moves into MAIN only with live evidence and the owner's approval.
