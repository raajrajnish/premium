# premium: design (v0, 2026-10-04)

## Purpose
Find trading approaches that earn a **steady premium with controlled, known-in-advance losses**, across any tradeable market (index options, stocks, futures, commodities), not only intraday option buying. **Paper only.** This system runs **completely separately** from **the Nifty system** (G1/G2, the forward tournament, the recorder and the dashboard), which it never modifies. (The Nifty system lives in the folder `trading/suzlon`; its GitHub repo is `nifty`.)

**Why this direction:** about 100 tested ideas in the Nifty system showed that predicting short-term direction with simple price rules does not beat costs. Retail traders make money mainly by collecting a **risk premium** (e.g. option buyers overpay on average) or by riding **long trends**, with losses capped by construction.

## Separation contract
1. **No writes outside `trading/premium`.** No imports of the Nifty system's code; small helpers are copied (with their origin noted) so neither system can break the other.
2. **Data:** after the Nifty system's End of Day finishes, `scripts/snapshot.ps1` copies its `data/market.duckdb` (folder `trading/suzlon`) to `premium/data/market.duckdb` (2.8 GB, a few seconds). premium reads **only its own copy**, so it can never lock or corrupt the original.
   - If a study needs data the Nifty system doesn't hold (e.g. far out-of-the-money strikes, futures, commodities), premium downloads it into **its own** database file, with the owner's approval first.
3. **Own repository** (GitHub: the owner creates `premium`; pushed only on the owner's say-so). Own config, docs and tests.
4. **Never reads or prints `.env`.** No order-placement code at all.

## Risk framework (percentages, never fixed rupees; owner's standing rule)
- **Defined risk only:** every position's **maximum loss is known before entry** (e.g. a credit spread's width minus the credit). No naked short options.
- **Per position:** max loss ≤ **2% of current equity**.
- **Open risk:** the sum of max losses of open positions ≤ **6% of equity**.
- **Monthly pause:** if the month's realised loss reaches **−6% of start-of-month equity**, no new positions that month.
- **Kill:** **−15% from peak equity**, which stops everything for an owner review.
- **Margin:** each study reports the margin needed (exchange span + exposure, with hedge benefit) and the return on that margin.
- These are defaults, to be confirmed by the owner before any paper trading starts.

## How every approach is judged (the same for all)
- **Return:** CAGR on capital, and return on margin used.
- **Risk:**
  - **max drawdown** and **worst month**;
  - the **worst single trade** and the **worst 5 consecutive trades**;
  - the share of months that were negative.
- **Quality:**
  - Calmar ratio (CAGR / max drawdown);
  - Sharpe on monthly returns;
  - **stress days** (e.g. 2024-06-04 election result, other big gap days) shown individually.
- **Benchmark:** Nifty buy-and-hold over the same period (Nifty 50 TRI where available), plus cash.
- **Discipline (as in the Nifty system):** rules pre-declared before any test; design vs one-shot test windows; costs = Groww charges + spreads; nothing tuned on the test window; paper trading before anything else.

## Roadmap (one study at a time, each pre-declared in `docs/studies/`)

| # | Approach | Data | Status |
|---|---|---|---|
| **S1** | **Defined-risk option selling on Nifty** (credit spreads / iron condors, weekly) | Nifty options in the snapshot (≈ ±3% of spot; far wings sometimes missing; see S1 for handling) | **FAILED** 2026-10-04 |
| S2 | **Covered calls** on Nifty (index proxy) / large stocks | snapshot (index, options, Nifty 50 daily) | planned |
| S3 | **Trend-following on futures** (Nifty/Bank Nifty futures; MCX gold/silver/crude if available) | Groww NSE futures 2021→; Yahoo global futures × USDINR as the MCX proxy | **FAILED** 2026-10-04 (provisional data; verdict final, see study) |
| S4 | **Monthly factor investing** (momentum / quality / low-volatility) in Nifty 50 | snapshot (Nifty 50 daily) | planned |
| (S5) | Cash-futures arbitrage (low return; for idle cash only) | futures data | maybe |

## Known data faults (inherited from the snapshot; learned in the Nifty system)
- **Groww DAILY candles are wrong from 2025:** "open" = previous close in 2025, NULL from Oct 2025; Nifty daily high/low are also wrong on many 2025–26 days. **Build daily bars from 1-min (or 15-min) data.**
- **2025-05-12, 10:32–10:34:** all stocks printed at ×100 → repair or exclude (see the Nifty system's `stock_study.clean_bad_prints`).
- **Stock splits/bonuses are not adjusted** (HDFC Bank, Reliance, BSE, Bajaj Finance…) → back-adjust before using multi-day prices.
- **Option strikes** are stored only around the money (median ≈ ±3% of spot at the start of each expiry week; as narrow as ±1.1%). Far out-of-the-money legs can be missing. Studies must report coverage and never fill gaps silently.

## Layout
```
premium/
  config/premium.yaml     risk defaults, paths
  docs/DESIGN.md          this file
  docs/studies/           one pre-declared study per file, results appended
  src/premium/            data access (read-only snapshot), metrics, strategies, simulator, cli
  scripts/snapshot.ps1    nightly data copy (after the Nifty system's End of Day)
  tests/                  unit tests (hand-checked values)
  data/                   snapshot DB + outputs (git-ignored)
```

## S3 data check (2026-10-04)
- **Groww's public instrument list** (`growwapi-assets.groww.in/instruments/instrument.csv`, no token) lists **MCX commodity futures**: 15,118 MCX rows, including crude oil, gold, silver, copper, natural gas, aluminium and zinc. It includes **mini lots** that suit ₹2 lakh: CRUDEOILM 10 bbl, GOLDM, SILVERM, NATGASMINI. It also lists NSE index futures (Nifty lot 65, Bank Nifty lot 30). There are no currency futures.
- The SDK supports `EXCHANGE_MCX` + `SEGMENT_COMMODITY` in `get_historical_candles` / `get_expiries`.
- **Open:** whether history for **expired** futures is served, and how far back (trend-following needs years). `scripts/probe_commodities.py` checks this with today's token (read-only calls only).
- **Token source:** the probe reads the token from the environment or, read-only, from the Nifty system's `.env` (where the morning window stores it). It never prints it, and never writes to the Nifty system.
- **Probe result (2026-10-04, read-only calls):**
  - **NSE index futures: history IS available.** Expired monthly Nifty and Bank Nifty futures returned about 58–64 daily candles each, for every March contract 2021–2025. A continuous back-adjusted series 2021→2026 can be built. (Note: `get_expiries` returns *option* expiries; futures use the monthly expiry. Daily requests are limited to 180 days per call.)
  - **MCX commodities: NO history via Groww's API.** Zero candles for currently listed contracts (crude, crude-mini, gold-mini) within the 180-day limit, for "continuous" symbols, and for just-expired crude. `get_expiries` also returns nothing for MCX. Commodity trend-following therefore needs **another data source**, e.g. MCX's official daily bhavcopy archive (public; not yet checked).
- **Follow-up checks (2026-10-04):**
  - **NSE commodity futures** (e.g. NSE-GOLD, NSE-CRUDEOIL) also returned 0 candles via Groww.
  - **MCX's website** returns HTTP 403 to scripts. We do not circumvent it.
  - **Yahoo Finance's public chart API** serves daily data from 2005 for gold (GC=F), silver (SI=F), crude (CL=F), copper (HG=F), natural gas (NG=F) and USD/INR (INR=X), and from 2007-09 for ^NSEI/^NSEBANK. Used as the **MCX proxy** (global price × USDINR), stored in `data/s3.duckdb` (`scripts/fetch_s3.py --step yahoo`).
  - **Yahoo faults:** CL=F went to −37.63 on 2020-04-20; the close sometimes falls outside the day's high/low (settlement prices); the front-month roll dates are unknown. See the S3 study, implementation notes 1–3.
