# U1: the owner's live checklist setup (Nifty options, PAPER ONLY)

This file is the **single source of truth** for U1. Code follows this file. Any change is made here first, dated, and gets a new rule version.

| Version | Valid from | Summary |
|---|---|---|
| v1 | 2026-10-05 09:45 | First version. Trend on 1-min candles; one exit for all trades. Rules: `docs/studies/2026-10-05_U1_multi_confirmation.md`. |
| **v2** | **2026-10-06** (next trading day) | Trend on **3-min** candles; **entry classes K1–K4** recorded on every trade; **safety checks** logged (not blocking). The exit is unchanged until the per-class exits are agreed. |

| **testing phase** | **2026-10-05 11:25** | Owner: **no daily trade cap** and **no pass/fail thresholds** while testing, to collect as many trades as possible. The pause, one-at-a-time and per-trade stop are unchanged. |

Results of different versions are **never mixed**; the dashboard shows them separately.

---

## 1. Principles (agreed with the owner)
1. **Live feed only.** U1 decides from the current day's live data. It uses no history, nothing from G1/G2, and no backtested parameters. Indicators start fresh every morning.
2. **Separate.** U1 has its own watcher, its own files (`premium/data/u1/`) and its own dashboard (http://127.0.0.1:8760). It never touches the Nifty system's code, and reads the recorder's files read-only.
3. **Paper only.** No orders are ever placed.
4. **Only the owner changes rules.** Every change is recorded in the version table above.

## 2. The data U1 reads (live, from the Nifty system's recorder)

| Feed | Every | Used for |
|---|---|---|
| Nifty spot | ~2 s | candles, indicators, stop |
| Nifty futures price + cumulative volume | ~10 s | VWAP, volume surge |
| Bank Nifty, HDFC Bank, ICICI Bank | ~2 s | heavyweights |
| India VIX | ~2 s | VIX check |
| Option chain OI per strike | 1 min | options OI, room to move |
| Option bid/ask (≈26 strikes near ATM) | ~10 s | fills, spread check |

## 3. The checklist: 10 items in 3 groups (CALL shown; PUT is the mirror)

| Group | Item | Timeframe | CALL is green when |
|---|---|---|---|
| **Trend** | Above VWAP | day so far (futures) | futures price > futures VWAP |
| | EMA 9 vs 21 | **3-min candles** (v2) | EMA 9 > EMA 21 |
| | EMA 9 slope | **3-min candles** (v2) | EMA 9 > its value one 3-min candle earlier |
| **Trigger** | Band breakout | 1-min | close > upper Bollinger (20, 2) **and** band width > 5 minutes ago |
| | 5-min break | 1-min | close > highest high of the previous five 1-min candles |
| **Confirmations** | Strength | 1-min | RSI(7) 60–80 **and** MACD(12,26,9) histogram > 0 and rising |
| | Volume surge | 1-min (futures) | this minute's volume ≥ 1.5 × average of the previous 20 minutes |
| | Heavyweights | now vs 3 min ago | ≥ 2 of Bank Nifty, HDFC Bank, ICICI Bank higher |
| | VIX | now vs 3 min ago | VIX not higher |
| | Options OI | last 5 min | ATM CE OI fell **or** ATM PE OI rose |

**3-min candles:** fixed blocks from 09:15 (09:15–09:17, 09:18–09:20, …). Only **completed** 3-min candles are used. They are built from the same live Nifty prices.

**Why the trend is on 3-min (owner decision, 2026-10-05):** on 1-min candles the EMA trend flipped about 16 times a day (median 14 min per side). On 3-min it flips about 5.6 times a day (median 33 min per side), steadier without being as slow as 5-min (about 3.4 flips/day). Measured on Jul–Sep 2026 Nifty 1-min data.

## 4. When a trade becomes active (minimum = 7 ticks, in the right groups)
- **Trend:** all **3** green.
- **Trigger:** at least **1 of 2** green.
- **Confirmations:** at least **3 of 5** green.
- **Only one side** may qualify in that minute; if both qualify, it is ignored as mixed.
- **Checked once a minute**, at each 1-min candle close, **09:45–14:30**.
- **Limits:** one trade at a time, with a **5-minute pause** after each exit. The cap of 4 trades/day is **OFF during the testing phase** (from 2026-10-05 11:25). There is no daily loss limit.

## 5. Entry
- Buy **1 lot (65)** of the **ATM option** (strike nearest spot, nearest expiry): CE for CALL, PE for PUT.
- Price = the **ask** at the first live price after the signal (or last price + ₹0.5 if there's no quote in the last 60 s).

## 6. Entry classes (v2), fixed at the moment of entry
Checked in this order; the first match wins:

| Class | Checklist at entry | Meaning |
|---|---|---|
| **K1 Full house** | **both** triggers + **≥ 4** confirmations | the whole market pushing the same way |
| **K2 Volatility burst** | band breakout + volume surge | a sudden expansion: fast, often short |
| **K3 Market-backed break** | 5-min break + heavyweights + VIX | a broad move led by the big banks |
| **K4 Standard** | any other qualifying entry | the weakest or least specific |

## 7. Exit
**Current (v1 and v2) — the same for all classes until the per-class exits are agreed.** Whichever comes first:
- **Stop:** Nifty spot passes the signal candle's low (CALL) or high (PUT). Checked on every live price.
- **Trend exit:** a 1-min close past EMA 9 (1-min). Checked at each candle close.
- **Time:** 15 minutes after entry.
- **Hard:** 15:10.
- **Fill:** at the bid (or last price − ₹0.5).

**Per-class exits — PENDING.**
- Each class gets its own exit, set from that class's own measured behaviour: best favourable move, worst adverse move, time to peak, and how often it reaches +25 pts.
- Measured on Jul–Sep 2026 under 1/3/5-min trends, with **7 of 10 items** (history has no futures volume, VWAP or minute-by-minute OI).
- Then confirmed on live data.
- The owner approves the exits before they're coded (that will be v3).

## 8. Safety checks (v2: logged on every signal, never blocking)

| Check | Meaning | OK when |
|---|---|---|
| **Room to move** | distance to the biggest OI "wall" (CALL: the strike with the most CE OI within 300 pts above spot; PUT: the most PE OI below) | ≥ 25 pts |
| **Spread** | the chosen option's ask − bid at entry | ≤ ₹1.0 |

After a few weeks, compare trades with and without each check. They become blocking rules only if the live data shows they help, and only with the owner's approval.

## 9. Costs and P&L
- P&L per lot = (exit fill − entry fill − **₹1.5 charges**) × 65.
- The spread is paid through the bid/ask fills. ₹1.5/unit covers brokerage ₹20 × 2, STT, exchange charges, GST and stamp duty.

## 10. Daily operation
1. **Start Trading** (Nifty system) starts the recorder.
2. Start the **U1 watcher**: window "premium U1 watch (paper)", `uv run python scripts/u1_watch.py`. It stops by itself at 15:12.
3. Start the **U1 dashboard**: window "premium U1 dashboard", `uv run python scripts/u1_ui.py`, then open http://127.0.0.1:8760.
4. **Files** (`premium/data/u1/`):
   - `<date>_signals.csv`: every minute where trend + trigger held, with all 10 items, the class, the safety checks, and whether a trade was taken (and why not);
   - `<date>_trades.csv`: every paper trade, with version and class;
   - `state.json`: live state for the dashboard.

## 11. How U1 is judged
**Testing phase (owner, 2026-10-05): no pass/fail thresholds.** Every trade is recorded, per version and per class, for analysis.

The criteria below are *suspended* until the owner ends the testing phase:
- ~~First look after 20 trades; verdict after 40 trades or 8 weeks.~~
- ~~To keep it: average ₹/trade > 0 after costs; profit factor ≥ 1.3; worst losing streak no worse than −₹5,000/lot.~~
