# U1 path model: predicting a signal's likely path before entering (PRE-DECLARED 2026-10-06, before any model was fitted)

**Owner's idea (2026-10-06):** instead of trading every U1 signal, a second model looks at the situation and estimates how the trade is likely to play out: its likely best point, worst point and expected ₹. We enter only when that estimate is good enough.

**Owner's decision:** history may be used for this model. This is an exception to U1 principle 1 (live data only), for the path model only.

## Data
- **Signals:** every U1 checklist signal, 2026-07-01 → 2026-09-29 (Nifty 1-min data in premium's snapshot), as in the exit studies. That is the v3 checklist: 3-min trend, with the 7 of 10 items that exist in history (no futures VWAP, volume surge or minute-level OI). At most one signal per 5 minutes. Entries 09:45–14:30.
- **Trade:** buy the real ATM weekly option at the next minute's open. Exits as EC0, EC1, EC2 (owner's 20/15/25) and EC2+, exactly as in the exit study. Costs ₹2.5/unit.
- **Split:** **TRAIN = Jul–Aug**, **TEST = Sep**. Nothing about September is used to build, tune or choose anything.

## What the model sees at the signal (features; all known at that moment, sign-adjusted so "+" means "in the trade's direction")
- **Checklist:** band trigger, 5-min break, strength, heavyweights, VIX check (0/1); confirmations; class K1/K3/K4.
- **Volatility / pendulum:** ATR(14) on 1-min bars; mean |1-min change| over the last 30 min.
- **Momentum into the signal:** Nifty change over 5 and 15 min, in ATRs; Bank Nifty change over 15 min (%).
- **Trend strength:** (3-min EMA 9 − EMA 21) / ATR; distance from the 20-min mean (Bollinger mid), in ATRs.
- **Position in the day:** place in the day's high–low range (0–1, direction-adjusted); change since the open (%).
- **Context:** minutes since 09:15; VIX level; VIX 3-min change (direction-adjusted); RSI(7) (direction-adjusted); MACD histogram / ATR (direction-adjusted).
- **Option:** days to expiry; entry premium.

## What it predicts (labels)
- **GOOD** = Nifty goes **+15 pts** in the trade's direction **before −12 pts against**, within 15 min.
- **₹ after costs** under each exit model.

## Models (simple and transparent; numpy only)
1. **"Similar past signals" (k-nearest neighbours):**
   - features standardised on TRAIN;
   - k = 50 nearest TRAIN signals;
   - prediction = their GOOD rate and their average ₹ per exit model.
   - For TRAIN signals, neighbours from the **same day are excluded**, so the decision threshold isn't fitted on leaked data.
2. **Logistic regression** for GOOD (L2-regularised, fitted on TRAIN). Its standardised coefficients show which features matter.

## Decision rules (fixed now)
- **R1 (kNN):** ENTER if the neighbours' average ₹ under that exit model is > 0.
- **R2 (logistic):** ENTER if the predicted chance of GOOD is in the top 30% of TRAIN predictions (the threshold is fixed on TRAIN).

## Judged on TEST (September) only
For each rule × exit model:
- **ENTER vs SKIP groups:** number of trades, GOOD rate, average ₹/trade, total ₹, worst trade;
- compared with **taking every signal** (the current U1).

**Useful** = ENTER trades beat ALL trades by ≥ ₹50/trade on average **and** ENTER's average ₹ > 0 under at least one exit model, with ≥ 30 ENTER trades in September.
- Useful → shadow on live U1 signals (prediction shown on the dashboard, nothing blocked) for 1–2 weeks, then the owner decides whether it gates entries.
- Not useful → recorded as failed, with the reason.

## Result (run 2026-10-06 13:25, `data/results/u1_path_model_20261006_1325`; script committed before the run): NOT USEFUL

Signals: 1,096 (TRAIN 741 over 44 days; TEST 355 over 20 days). GOOD rate: TRAIN 31%, TEST 34%.

**Average ₹ per trade on TEST (September):**

| Rule | ENTER (n) | ENTER GOOD% | ENTER EC0 / EC1 / EC2 / EC2+ | ALL signals EC0 / EC1 / EC2 / EC2+ |
|---|---|---|---|---|
| R2 logistic top 30% | 100 | 34% | −153 / −152 / −227 / −169 | −133 / −135 / −177 / −158 |
| R1 kNN, EV > 0 under EC0 | 32 | 38% | −244 / −138 / −266 / −251 | same |
| R1 kNN, EV > 0 under EC1 | 29 | 38% | −210 / −120 / −165 / −154 | same |
| R1 kNN, EV > 0 under EC2 | 15 | 33% | −46 / −77 / −154 / **+119** | same |
| R1 kNN, EV > 0 under EC2+ | 36 | 33% | −152 / −27 / −215 / −185 | same |

**Reading:**
1. **It learned TRAIN, not the market.**
   - On TRAIN, the logistic top 30% looked clearly better: 41% GOOD vs 26% for the rest, about ₹80/trade better.
   - On TEST, the same rule picked trades that were **no better than the rest**: 34% vs 33% GOOD, and *worse* in ₹.
   - Ranked into quartiles by the model's prediction, TEST outcomes don't line up at all; the *lowest*-ranked quarter did best.
2. **No rule met the pre-declared bar:** ≥ ₹50/trade better than ALL, ENTER average > 0, at least 30 trades. The one positive cell (+₹119, kNN-EC2 rule scored under EC2+) has only 15 trades and is the rule's *mismatched* exit, so it's noise.
3. **The strongest-looking inputs** (distance from the Bollinger mid, VIX level, time of day) didn't carry over to September.

**Verdict:** with these features, a signal's path **can't be predicted** well enough to choose entries. This agrees with the earlier finding that U1's historical signals are close to chance. Two things could still change it, and they can only be measured live:
- the three live-only items (futures VWAP, volume surge, options OI);
- order-book information (bid/ask quantities, the 45-second follow-through check).

The live signal log keeps collecting them.
