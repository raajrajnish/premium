# S1: defined-risk option selling on Nifty weekly options (PRE-DECLARED 2026-10-04, before any code or result)

**Why:** in the Nifty system, the only consistently positive effect found was on the *selling* side. R6 (selling the ATM straddle at 13:30 on expiry day) made +₹237/trade over 147 trades, but with **unlimited** risk. S1 tests whether the premium survives when every position has a **maximum loss fixed at entry** (bought wings). Paper research only.

**Honest caveat:** the expiry-day straddle idea was already measured on this period (R6 / Fable P2). S1a is therefore not an untouched test; S1b and S1c are new. Both halves must pass, the rules are fixed and nothing is tuned.

## Structures (1 lot = 65; strikes rounded to the nearest 50; spot = the Nifty 1-min close before entry)

| Id | Structure | Entry | Short strikes | Wings (bought) | Exit |
|---|---|---|---|---|---|
| **S1a** | **Iron butterfly, expiry day** (the defined-risk R6) | **13:30** on expiry day | ATM call + ATM put | spot **± 1.0%** | **15:10** (no stop: max loss is capped) |
| **S1b** | **Iron condor, expiry day morning** (0 days to expiry) | **09:30** on expiry day | spot **± 0.75%** | spot **± 1.5%** | 15:10 |
| **S1c** | **Iron condor, 1 day to expiry** | **14:30** on the trading day before expiry | spot **± 1.0%** | spot **± 2.0%** | **15:10 on expiry day** (held overnight; the gap risk is part of the test) |

- All four legs open at the same minute's open price and close at the exit bar's close.
- **Max loss per position** = (wing distance − net credit) × 65, known at entry.
- **Margin**, as an approximation of SEBI hedged-position margin, = max loss × 1.1. Return on margin is reported.

## Costs (conservative for out-of-the-money and expiry-day options)
- **Groww charges:** 8 orders per position; STT on the sell side of each leg; exchange, SEBI, stamp duty and GST as in the Nifty system's `costs.yaml`.
- **Half-spread per leg per side:**
  - **max(0.25% of the leg's premium, ₹0.25)** on expiry day (S1a, S1b, and S1c's exit);
  - max(0.15%, ₹0.10) on other days (S1c's entry).
- **Robustness:** everything is also run at **2× costs** (2× spreads and 2× charges).

## Data rules
- Only strikes present in the snapshot are used. **If any of the 4 legs has no 1-min data at entry or exit, the trade is skipped** (never filled or interpolated).
- The coverage share (trades possible / days eligible) is reported per structure, plus whether skipped days were bigger-move days (a bias check).
- Expiry calendar: the snapshot's NIFTY contracts (Thursday expiries until Aug 2025, Tuesday after; holiday-shifted).

## Test
- **Two halves; both must pass:**
  - **H-A** = Dec 2023 – Jun 2025;
  - **H-B** = Jul 2025 – Sep 2026.
- **Capital** for the scorecard: ₹2,00,000, 1 lot per position (the premium scorecard, `metrics.scorecard`).
- **PASS in each half:**
  - n ≥ 30 positions;
  - total return > 0 after costs;
  - positive at **2× costs**;
  - profit factor ≥ 1.2;
  - **worst month ≥ −6% of capital** (the monthly-pause limit);
  - max drawdown ≥ −15% (the kill limit).
- **ROBUST:** PASS in both halves; mean P&L per position with a 95% bootstrap CI above 0 (both halves together); still positive without its 5 best positions.
- **Always reported:**
  - CAGR, max drawdown, Calmar, worst month, worst trade and worst 5 in a row, share of negative months;
  - return on margin;
  - **stress days:** the 10 largest absolute Nifty moves on S1 trade days, each shown;
  - **Nifty buy-and-hold** over the same dates.

**Multiple testing:** 3 structures × 2 halves. A pass in only one half is a lead.

**Outcome:**
- ROBUST → a **paper-trading candidate** in premium (live paper engine to be built), with the owner's approval and confirmed risk limits.
- Otherwise → recorded as failed, with the reason.
