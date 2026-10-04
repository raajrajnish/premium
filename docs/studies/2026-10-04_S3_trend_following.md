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

## Implementation notes (committed with the code, 2026-10-04, BEFORE any result was run)

Data was downloaded and quality-checked (no strategy output had been seen). These choices follow from that check, and from details the declaration left open:

1. **Roll filter.** Yahoo does not say when the front-month contract changes, so the declared filter can't be applied exactly.
   - Variant **z5**: any day with |return| > 5 × the prior 60-day stdev is set to 0. This is a superset of the declared filter; it also removes some genuine shocks.
   - Variant **raw**: no filter.
   - **A rule must pass in BOTH variants.** Flagged-day counts are reported.
2. **Crude oil went to −$37.63 on 2020-04-20.** Percentage returns are undefined around non-positive prices, so the 2020-04-20 and 04-21 returns are set to 0. MCX longs really lost that day; a trend follower was short going in, so zero is conservative.
3. **Yahoo high/low** sometimes exclude the close (settlement prices; ~200–300 bars each in GC, SI, HG and INR). High and low are clamped to contain the open and close (affects ATR only).
4. **Indices before futures data:** Yahoo spot ^NSEI/^NSEBANK minus **5.5%/yr carry** (futures ≈ spot − (risk-free − dividend)), with the same roll costs. Index data starts 2007-09-17; the indices join once warmed up (≥ 260 days).
5. **P-recent index source.**
   - The declared source is Groww futures.
   - The Groww token in the Nifty system's `.env` was expired on 2026-10-04, so a **provisional** run uses Yahoo spot minus carry (`--index yahoo`).
   - The **official** P-recent verdict for the indices is the `--index groww` run, made once a valid token is available. Its continuous series rolls 3 trading days before expiry, back-adjusted by ratio.
   - Rules and parameters are identical in both runs.
6. **Commodities in ₹:** daily r_INR = (1 + r_USD)(1 + r_USDINR) − 1, with USDINR forward-filled to the commodity's dates.
7. **Execution:** direction decided at close t, traded at close t+1, so the position earns from t+2. On a stop, the position stays flat until a *fresh* signal (T1: a new 55-day breakout; T2: a new SMA cross). T2 takes the prevailing trend on its first warm day.
8. **Sizing:** weight = direction × min(0.10/σ60_annual, 2) / N, where N = markets warmed up that day. This is the literal "10% per market, equal risk split", so portfolio volatility will be below 10%; realised average gross exposure is reported.
9. **Costs, per side, as a fraction of notional:**
   - index futures **0.035%** (STT 0.02% sell + exchange + stamp + GST + ₹20 brokerage + 0.02% slippage, averaged across sides);
   - commodities **0.06%** (CTT 0.01% sell + MCX charges + ₹20 brokerage on mini-lot notional + 0.03% slippage);
   - plus a roll round trip on each market's first trading day of every month.
10. **Scorecard:** daily P&L = portfolio return × ₹2,00,000, with no compounding (the premium scorecard).
    - "Positive in ≥ 60% of markets" = each market run alone, total return in the period > 0.
    - "Without its best market" = the portfolio rerun without the best standalone market, total > 0.
    - **Crisis months** = Nifty's 5 worst months in each period, showing the strategy's return in those months.

## Result (run 2026-10-04 13:53, `data/results/s3_yahoo_20261004_1353`; code committed before the run as `8cd3b87`): NONE PASS

Indices use Yahoo spot minus carry (the provisional source); commodities come from Yahoo, converted to ₹. Costs are 1×, with CAGR at 2× costs alongside.

| Variant | Rule | P-old (2007–2020): CAGR / max DD / Calmar / Sharpe | P-recent (2021–Sep 2026): CAGR / max DD / Calmar / Sharpe | Markets positive (old / recent) |
|---|---|---|---|---|
| z5 | **T1** Donchian 55/20 | +0.7% / −13.2% / 0.05 / 0.22 | +0.2% / −12.2% / 0.01 / 0.06 (−0.5% at 2×) | 71% / 57% |
| z5 | **T2** SMA 50/200 | −0.1% / −16.6% / — / −0.01 | +2.1% / −10.7% / 0.20 / **0.67** | 43% / 57% |
| z5 | **T3** 12-month TSMOM | +0.2% / −18.8% / 0.01 / 0.06 | +2.5% / −11.3% / 0.22 / 0.54 | 43% / 71% |
| raw | T1 | +1.0% / −11.1% / 0.09 / 0.28 | −0.9% / −14.1% / — / −0.22 | 71% / 14% |
| raw | T2 | −0.2% / −15.5% / — / −0.04 | +1.4% / −9.7% / 0.15 / 0.45 | 43% / 71% |
| raw | T3 | −1.4% / −27.2% / — / −0.25 | +0.2% / −14.2% / 0.01 / 0.07 | 29% / 57% |

**Benchmark:** Nifty buy-and-hold had CAGR **8.9%** (max DD −59.9%) in P-old and **8.7%** (max DD −17.2%) in P-recent.

**Verdict: S3 failed.**
1. **No rule passes P-old in either variant.** Every Calmar there is ≤ 0.09 and every Sharpe ≤ 0.28. A ROBUST pass needs both periods, so the official Groww-futures run for the P-recent indices **cannot change the verdict** and is not needed.
2. **Two P-recent leads** (T2 and T3 with z5) have positive returns and Sharpe 0.54–0.67, but fail Calmar (0.20–0.22 against the 0.3 bar). Their returns come mostly from **gold**: without it, T2 makes +6% and T3 +5% total over 5.7 years. Gold's 2022–26 bull run is one trend, not a repeatable edge.
3. **By market:**
   - **Gold** is the only market positive in all 12 rule/period/variant cells.
   - **Bank Nifty and natural gas** lose in almost every cell; Nifty is mixed. Indian index trends are too choppy for these rules after costs, which is consistent with the Nifty system's failed breakout ideas.
4. **What did work, as theory predicts:** the crisis behaviour. In Nifty's worst months (2008-10 −26%, 2008-06, 2008-01) every rule was **positive** (+0.2% to +2.8%), and monthly correlation with Nifty was about 0. In 2020-03 it was mixed (−1.7% to +2.1%). So trend-following is a hedge but, on this universe, **not a profit source**.
5. **Caveats (they do not rescue it):**
   - Sizing was the literal 10%/N, so average gross exposure was only 0.2–0.5× capital. Sharpe and Calmar barely depend on scale, and those are what failed.
   - The `entries` column in `scorecards.csv` is the whole-history count, not per period (a reporting slip with no effect on the pass/fail metrics).
   - With 7 markets this is far narrower than the 50–60 markets in the published evidence. The literature's edge comes from breadth that ₹2 lakh can't buy on MCX/NSE.
