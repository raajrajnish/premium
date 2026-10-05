# U1: the owner's live checklist setup (Nifty options, PAPER ONLY)

This file is the **single source of truth** for U1. Code follows this file. Any change is made here first, dated, and gets a new rule version.

| Version | Valid from | Summary |
|---|---|---|
| v1 | 2026-10-05 09:45 | First version. Trend on 1-min candles; one exit for all trades. Rules: `docs/studies/2026-10-05_U1_multi_confirmation.md`. |
| v2 | (planned 2026-10-06; never ran live) | Trend on 3-min candles; classes K1–K4; safety checks logged. **Superseded by v3 before it ran.** |
| **testing phase**  | **2026-10-05 11:25** | Owner: **no daily trade cap** and **no pass/fail thresholds** while testing, to collect as many trades as possible. The pause, one-at-a-time and per-trade stop are unchanged. |
| **v3** | **2026-10-06** (next trading day) | Everything in v2 (3-min trend, classes K1–K4, safety checks logged), **plus four challenger exits (EC0, EC1, EC2, EC2+) run on every entry** (§7), **plus a signal-quality score** on every signal (§8). |

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
| | EMA 9 vs 21 | **3-min candles** (v3) | EMA 9 > EMA 21 |
| | EMA 9 slope | **3-min candles** (v3) | EMA 9 > its value one 3-min candle earlier |
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
- **Limits:** one trade at a time (v3: the next entry waits until **all four** challenger exits have closed, so every model trades exactly the same entries), with a **5-minute pause** after the last exit. The cap of 4 trades/day is **OFF during the testing phase** (from 2026-10-05 11:25). There is no daily loss limit.

## 5. Entry
- Buy **1 lot (65)** of the **ATM option** (strike nearest spot, nearest expiry): CE for CALL, PE for PUT.
- Price = the **ask** at the first live price after the signal (or last price + ₹0.5 if there's no quote in the last 60 s).

## 6. Entry classes (v3), fixed at the moment of entry
Checked in this order; the first match wins:

| Class | Checklist at entry | Meaning |
|---|---|---|
| **K1 Full house** | **both** triggers + **≥ 4** confirmations | the whole market pushing the same way |
| **K2 Volatility burst** | band breakout + volume surge | a sudden expansion: fast, often short |
| **K3 Market-backed break** | 5-min break + heavyweights + VIX | a broad move led by the big banks |
| **K4 Standard** | any other qualifying entry | the weakest or least specific |

## 7. Exit: four challengers on every entry (v3)
Every entry opens one paper position **in each model at the same price**. Each model exits by its own rules; all are recorded on the same trade row. v1 (2026-10-05) ran EC0 only.

All models fill exits at the **bid** (or last price − ₹0.5), checked on every live price (~2 s).
- "Nifty points" are measured from Nifty's price at entry.
- "%" is the option's bid relative to the entry fill, in % of the premium paid.
- **Expiry rules:**
  - near expiry = expiry day or the day before;
  - the hard exit is 14:45 on expiry day (15:10 otherwise) for EC1, EC2 and EC2+.

### EC0: Champion (the v1 exit)
- **Stop:** Nifty passes the signal candle's low (CALL) / high (PUT).
- **Trend exit:** a 1-min close past the 1-min EMA 9.
- **Time:** 15 minutes.
- **Hard:** 15:10.

### EC1: Nifty-points rulebook (proposed by Claude, 2026-10-05)

| Rule | Condition |
|---|---|
| A Stop | Nifty −12 pts |
| B Max loss | option P&L ≤ −₹600/lot |
| C Breakeven | once Nifty +6, the stop moves to the entry price |
| D Protect | once Nifty +10, exit if the gain falls below 50% of the best |
| E Spike lock | +15 pts within 2 min → exit if the gain falls below 75% of the best |
| F No progress | never reached +6 within 8 min (5 near expiry) |
| G Max hold | 20 min (12 near expiry) |
| H Option lag | Nifty ≥ +6 but the option bid ≤ the entry fill for 2 min |
| I Reversal | the opposite side's checklist becomes fully valid (at a 1-min close) |
| J Hard | 15:10 (14:45 on expiry day) |
| K Feed | no Nifty price for 60 s → exit at the last bid, flagged |

### EC2: owner's premium-% trail (owner, 2026-10-05)
- **Loss limit:** the option is down **20%**.
- **Lock-in:** once the option is up **+15%**, the minimum exit is +15%.
- **Breathing:** the minimum then rises to **75% of the best profit seen** (25% breathing, measured as a share of the peak). Exit when the option falls below the minimum.
- **Shared safety rules** (owner: yes): F, G, I, J and K from EC1.

### EC2+: EC2 plus five additions (Claude's proposal; owner: test them)
1. **Breakeven:** once +8%, the loss limit moves to entry + charges (₹1.5/unit).
2. **Volatility-adjusted loss limit:** 3 × the option's average absolute 1-min % change over the 10 minutes before entry, kept between 10% and 25% (20% if there's too little data).
3. **Confirmation:** a loss-limit, breakeven or trail exit fires only after the price has stayed past the level for **10 seconds**.
4. **Tiered breathing:** keep 75% of the best profit below +40%, 80% from +40% to +80%, 85% above +80%.
5. **Shrinking loss limit:** if the trade hasn't reached +8% after 5 minutes, the loss limit halves.
- Plus the shared safety rules F, G, I, J and K.

**What history says (owner informed, 2026-10-05):**
- On 1,096 checklist signals (Jul–Sep 2026, real option prices, 7 of the 10 items), every model lost about the ₹162/trade cost. Average per trade: EC0 −147, EC1 −153, EC2 −170, EC2+ −158.
- Before costs, all were close to zero.
- The exits change the shape of the losses, not the outcome; profit must come from entries.
- The live test answers whether the full 10-item checklist (VWAP, volume and OI included) changes this.

## 8. Safety checks and signal quality (logged on every signal, never blocking)

| Check | Meaning | OK when |
|---|---|---|
| **Room to move** | distance to the biggest OI "wall" (CALL: the strike with the most CE OI within 300 pts above spot; PUT: the most PE OI below) | ≥ 25 pts |
| **Spread** | the chosen option's ask − bid at entry | ≤ ₹1.0 |

**Signal-quality score (v3):**
- `green_items` = how many of the 10 checklist items are green (7–10 for a qualifying signal);
- `quality` = `green_items` + 1 if room-to-move is OK + 1 if the spread is OK (0–12).

The question for the testing phase: **are the top 10–20% of signals by quality profitable, even if the average signal is not?**

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
   - `<date>_trades.csv`: every paper trade, with version, class, quality, and each challenger's exit time, price, reason and ₹ (`EC0_*`, `EC1_*`, `EC2_*`, `EC2P_*`). `pnl_lot` = EC0;
   - `state.json`: live state for the dashboard.

## 11. How U1 is judged
**Testing phase (owner, 2026-10-05): no pass/fail thresholds.** Every trade is recorded, per version and per class, for analysis.

The criteria below are *suspended* until the owner ends the testing phase:
- ~~First look after 20 trades; verdict after 40 trades or 8 weeks.~~
- ~~To keep it: average ₹/trade > 0 after costs; profit factor ≥ 1.3; worst losing streak no worse than −₹5,000/lot.~~
