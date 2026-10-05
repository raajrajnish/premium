# U1: the owner's multi-confirmation intraday setup (Nifty options, PAPER) — rules declared 2026-10-05

**Origin:** designed with the owner from the live chart on 2026-10-05: "a move must be confirmed by indicators, not only by candle direction".
- **Judged ONLY forward:** on live recorded days, starting from the first full minute after the watcher starts on 2026-10-05.
- **No backtest, no tuning on past data.**
- **Thresholds can be changed only by the owner.** Every change is dated here, and results before and after a change are kept separate.

## Data (live, read-only from the Nifty system's recorder files `suzlon/data/raw/date=<day>/`)
- `ltp.jsonl` (every ~2 s):
  - Nifty spot, India VIX, Bank Nifty, HDFC Bank, ICICI Bank;
  - option last prices.
- `quotes.jsonl` (every ~10 s per symbol):
  - **Nifty futures** price and cumulative volume;
  - option bid/ask for the ~26 strikes near the money.
- `chain.jsonl` (every minute): open interest (OI) per strike for the nearest expiry.
- 1-minute bars are built from Nifty spot. The index has no volume, so **volume and VWAP come from Nifty futures**, accumulated from the recorder's start (~09:17).

## Rules (CALL shown; PUT is the exact mirror)
Evaluated at the close of each completed minute, **09:45–14:30**.

**Layer 1 — trend (all three):**
- the futures price is above the futures VWAP;
- EMA 9 > EMA 21 (on spot 1-min closes);
- EMA 9 is rising (above its value one minute earlier).

**Layer 2 — trigger (either):**
- **(a)** the close is above the upper Bollinger Band (20, 2), **and** the band width is larger than 5 minutes ago (expansion);
- **(b)** the close is above the highest high of the previous 5 minutes.

**Layers 3–4 — confirmations (at least 3 of these 5):**
1. **Strength:** RSI(7) between 60 and 80, **and** MACD(12, 26, 9) histogram > 0 and rising. These two are built from the same price, so they count as one.
2. **Volume:** this minute's futures volume ≥ 1.5 × the average of the previous 20 minutes.
3. **Heavyweights:** at least 2 of Bank Nifty, HDFC Bank and ICICI Bank are higher than 3 minutes ago.
4. **VIX:** India VIX is not higher than 3 minutes ago.
5. **Options OI:** over the last 5 minutes, either the ATM CE's OI fell (call writers covering) **or** the ATM PE's OI rose (put writers adding).

**PUT mirror:**
- futures below VWAP, EMA 9 < EMA 21 and falling;
- lower band breakout with expansion, or a close below the lowest low of the previous 5 minutes;
- RSI 20–40 and histogram < 0 and falling;
- heavyweights lower;
- VIX not lower;
- PE OI fell, or CE OI rose.

**Entry:**
- buy **1 lot** of the **ATM option** (strike nearest spot, nearest expiry), CE for up and PE for down;
- at the **ask** at the first live tick after the signal minute (or last price + ₹0.5 if no fresh quote within 60 s).

**Exit, whichever comes first:**
- **Stop:** Nifty spot trades below the **low of the signal minute** (CALL) / above its high (PUT).
- **Trail:** a 1-minute close below EMA 9 (CALL) / above EMA 9 (PUT).
- **Time:** 15 minutes after entry.
- **Hard:** 15:10.
- Exits fill at the **bid** (or last price − ₹0.5).

**Limits:**
- one trade at a time;
- a 5-minute pause after each exit;
- at most **4 trades a day**.

**Costs:** the bid/ask spread is paid through the fills, plus **₹1.5 per unit** for charges (brokerage ₹20 × 2, STT, exchange, GST, stamp) ≈ ₹98 per lot round trip. Lot = 65.

## What is recorded every day (`premium/data/u1/`)
- `<day>_signals.csv`: **every** minute where layers 1 and 2 both held, with all five confirmations and whether a trade was taken. This lets us see later which confirmations actually mattered.
- `<day>_trades.csv`: each paper trade with its entry and exit times and prices, exit reason and ₹ per lot.

## How it will be judged (fixed now)
- **First look:** after 20 trades.
- **Verdict:** after **40 trades or 8 weeks**, whichever comes first.
- **To keep it:**
  - average ₹ per trade > 0 after costs;
  - profit factor ≥ 1.3;
  - worst losing streak ≤ ₹5,000 per lot.
- **Paper only.**
