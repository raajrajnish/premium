# S3: multi-market trend-following (PRE-DECLARED 2026-10-04, before any price data was downloaded or viewed)

**Why:** time-series momentum (Moskowitz, Ooi & Pedersen 2012, "Time Series Momentum", JFE; Hurst, Ooi & Pedersen, "A Century of Evidence on Trend-Following") is the best-documented systematic trading edge. It earns from **multi-month trends**, has **few trades and low costs** (the opposite of everything that failed in the Nifty system), and **caps loss per position with stops and volatility-based sizing**. It works only when **diversified across markets**.

## Data (documented sources; downloaded into premium's own database)
- **Groww API, read-only:** expired monthly **Nifty and Bank Nifty futures**, 2021 → 2026, daily. Rolled to the next contract 3 trading days before expiry into a back-adjusted continuous series. Roll costs are charged.
- **Yahoo Finance daily, public, for personal research** (Groww serves no commodity history; MCX's website blocks scripts):
  - global front-month futures: **gold GC=F, silver SI=F, crude CL=F, copper HG=F, natural gas NG=F**;
  - **USD/INR INR=X**, to convert to ₹ (MCX prices ≈ global price × USD/INR, with a small basis);
  - **Nifty ^NSEI and Bank Nifty ^NSEBANK**, for years before 2021.
  - **Known flaw:** Yahoo's `=F` series is the *unadjusted* front month, so roll days create artificial jumps (e.g. crude contango). Mitigation: any daily return on a day the series' contract month changes with |return| > 5 × its 60-day stdev is set to 0, and the count of such days is reported.
- The **instrument list, costs and lot sizes** come from Groww's public instrument file (MCX mini contracts, NSE index futures).

## Rules (three classic families; parameters are the textbook ones, not tuned)

| Id | Rule | Signal | Exit |
|---|---|---|---|
| **T1** | Donchian breakout (Turtle-style) | Long when the close > the highest close of the prior **55** days; short when < the lowest of the prior 55 | Long exits when the close < the lowest close of the prior **20** days; short mirror |
| **T2** | Moving-average trend | Long when SMA **50** > SMA **200**; short when below. Re-evaluated daily | Flip on cross |
| **T3** | Time-series momentum | At each month-end: long if the 12-month return > 0, short if < 0 | Re-evaluated monthly |

- **Sizing (the loss control):** each market targets **10% annualised volatility** (60-day realised volatility), capped at 2× leverage per market.
- **Portfolio:** equal risk budget across the markets available on each date.
- **Hard stop per position:** exit if the position loses **2 × ATR(20)** from entry (T1 and T2; T3 has none, as in the literature).
- Fractional sizing in research; the capital needed for whole MCX mini / NSE lots is reported separately.

**Costs per trade (each side):**
- **Index futures:** Groww ₹20 + exchange/STT/stamp/GST at NSE futures rates, plus **0.02% slippage**.
- **Commodities:** Groww ₹20 + MCX charges (CTT 0.01% on sell for non-agricultural), plus **0.03% slippage**.
- **Rolls:** each roll costs one round trip.
- **2× costs** for robustness.

## Test
- **Periods (both must pass):**
  - **P-old** = 2007-01-01 → 2020-12-31 (index from Yahoo; commodities from Yahoo);
  - **P-recent** = 2021-01-01 → 2026-09-30 (Groww futures for the indices).
- **PASS per period (portfolio of all markets, each rule separately):**
  - CAGR > 0 after costs and > 0 at 2× costs;
  - **max drawdown ≥ −25%**;
  - Calmar ≥ 0.3;
  - worst month ≥ −8%;
  - Sharpe (monthly) ≥ 0.4.
- **ROBUST:** PASS in both periods, plus positive in ≥ 60% of individual markets, plus still positive without its best market.
- **Also reported:**
  - per market;
  - **correlation with Nifty buy-and-hold** (trend-following should be low or negative in crashes: 2008, 2020, 2022);
  - the crisis months, individually;
  - Nifty buy-and-hold over the same periods.
- **Multiple testing:** 3 rules × 2 periods. A rule must pass both. A single-period pass is a lead.

**Outcome:**
- ROBUST → paper-trading candidate in premium, at monthly or daily-close cadence, with the owner's approval of lot sizing and capital.
- Otherwise → failed, with the reason.

**Owner caveat (fixed now):** with ₹2 lakh, one Nifty futures lot (≈ ₹15 lakh notional) is far above a 10%-volatility position. Real trading might need MCX **mini** contracts, larger capital or ETFs. The study reports the minimum capital that lets each market be sized correctly.
