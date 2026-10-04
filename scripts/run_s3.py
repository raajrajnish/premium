"""Run the pre-declared S3 trend-following test (docs/studies/2026-10-04_S3_trend_following.md).

  --index yahoo : Nifty/Bank Nifty from the Yahoo spot index minus a 5.5%/yr carry (futures ≈ spot − (rf − div)),
                  for the whole history (PROVISIONAL for P-recent).
  --index groww : as above before 2021, then the Groww back-adjusted monthly futures (rolled 3 trading days before
                  expiry) from their first day (the declared P-recent source).
Writes data/results/s3_<stamp>/ (summary.json, scorecards.csv, per_market.csv, crisis.csv).
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from premium.metrics import buy_and_hold, monthly_returns_pct, scorecard  # noqa: E402
from premium.s3 import RULES, Market, run  # noqa: E402

DB = ROOT / "data" / "s3.duckdb"
CAPITAL = 200_000.0
COMMODITIES = {"GOLD": "GC=F", "SILVER": "SI=F", "CRUDE": "CL=F", "COPPER": "HG=F", "NATGAS": "NG=F"}
INDICES = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}
COST_INDEX, COST_COMMODITY = 0.00035, 0.0006
CARRY = 0.055 / 252
PERIODS = {"P-old": ("2007-01-01", "2020-12-31"), "P-recent": ("2021-01-01", "2026-09-30")}
PASS = {"cagr": 0.0, "mdd": -25.0, "calmar": 0.3, "worst_month": -8.0, "sharpe": 0.4}


def yahoo(c: duckdb.DuckDBPyConnection, sym: str) -> pd.DataFrame:
    t = c.execute("SELECT d, open, high, low, close FROM yahoo_daily WHERE symbol=? ORDER BY d", [sym]).df()
    return t.set_index(pd.DatetimeIndex(t.pop("d")))


def bars_from(t: pd.DataFrame) -> pd.DataFrame:
    """r from closes; hi/lo clamped to contain open and close; non-positive prices give r = 0 (CL=F 2020-04-20/21)."""
    close = t["close"]
    prev = close.shift(1)
    r = (close / prev - 1.0).where((close > 0) & (prev > 0), 0.0).fillna(0.0)
    hi = t[["high", "open", "close"]].max(axis=1) / close
    lo = t[["low", "open", "close"]].min(axis=1) / close
    ok = close > 0
    return pd.DataFrame({"r": r, "hi": hi.where(ok, 1.0), "lo": lo.where(ok, 1.0)}).iloc[1:]


def zfilter(b: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Implementation of the declared roll filter (contract-change days unknown in Yahoo): |r| > 5 × σ60 → 0."""
    sd = b["r"].shift(1).rolling(60).std()
    hit = (b["r"].abs() > 5 * sd) & sd.notna()
    out = b.copy()
    out.loc[hit, "r"] = 0.0
    return out, int(hit.sum())


def groww_continuous(c: duckdb.DuckDBPyConnection, u: str) -> pd.DataFrame:
    """Back-adjusted (ratio) continuous monthly futures: hold the front contract until 3 trading days before expiry."""
    t = c.execute("SELECT expiry, d, open, high, low, close FROM fut_daily WHERE underlying=? ORDER BY expiry, d",
                  [u]).df()
    if t.empty:
        raise SystemExit(f"No Groww futures for {u} in {DB}; run scripts/fetch_s3.py --step groww")
    t["d"], t["expiry"] = pd.to_datetime(t["d"]), pd.to_datetime(t["expiry"])
    exps = sorted(t.expiry.unique())
    rows = []
    for i, e in enumerate(exps):
        cur = t[t.expiry == e].set_index("d").sort_index()
        roll = cur.index[-4] if len(cur) >= 4 else cur.index[-1]       # 3 trading days before expiry
        start = rows[-1].index[-1] if rows else cur.index[0] - pd.Timedelta(days=1)
        seg = cur[(cur.index > start) & (cur.index <= roll)] if i < len(exps) - 1 else cur[cur.index > start]
        if seg.empty:
            continue
        b = bars_from(pd.concat([cur[cur.index <= start].tail(1), seg]))  # first r uses the SAME contract's prev close
        rows.append(b)
    out = pd.concat(rows)
    return out[~out.index.duplicated(keep="first")]


def markets(index_src: str, filt: bool) -> tuple[list[Market], dict[str, int]]:
    c = duckdb.connect(str(DB), read_only=True)
    fx = yahoo(c, "INR=X")["close"]
    ms, flagged = [], {}
    for name, sym in COMMODITIES.items():
        t = yahoo(c, sym)
        b = bars_from(t)
        fxr = fx.reindex(fx.index.union(b.index)).ffill().reindex(b.index)
        b["r"] = (1 + b["r"]) * (fxr / fxr.shift(1)).fillna(1.0) - 1      # USD → INR, MCX ≈ global × USDINR
        if filt:
            b, flagged[name] = zfilter(b)
        ms.append(Market(name, b, COST_COMMODITY))
    for name, sym in INDICES.items():
        b = bars_from(yahoo(c, sym))
        b["r"] = b["r"] - CARRY
        if index_src == "groww":
            g = groww_continuous(c, name)
            b = pd.concat([b[b.index < g.index[0]], g])
        if filt:
            b, flagged[name] = zfilter(b)
        ms.append(Market(name, b, COST_INDEX))
    return ms, flagged


def card(daily: pd.Series, a: str, b: str) -> dict[str, object]:
    d = daily[(daily.index >= a) & (daily.index <= b)]
    return scorecard(d * CAPITAL, CAPITAL).as_dict()


def passes(s: dict[str, object], s2: dict[str, object]) -> bool:
    f = float
    return (f(s["cagr_pct"]) > PASS["cagr"] and f(s2["cagr_pct"]) > PASS["cagr"]  # type: ignore[arg-type]
            and f(s["max_drawdown_pct"]) >= PASS["mdd"]  # type: ignore[arg-type]
            and s["calmar"] is not None and f(s["calmar"]) >= PASS["calmar"]  # type: ignore[arg-type]
            and f(s["worst_month_pct"]) >= PASS["worst_month"]  # type: ignore[arg-type]
            and s["sharpe_monthly"] is not None and f(s["sharpe_monthly"]) >= PASS["sharpe"])  # type: ignore[arg-type]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", choices=["yahoo", "groww"], required=True)
    a = ap.parse_args()
    out = ROOT / "data" / "results" / f"s3_{a.index}_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    c = duckdb.connect(str(DB), read_only=True)
    nifty = yahoo(c, "^NSEI")["close"]
    nifty_m = {}
    for p, (s, e) in PERIODS.items():
        n = nifty[(nifty.index >= s) & (nifty.index <= e)]
        nifty_m[p] = monthly_returns_pct((n.diff().fillna(0) / n.iloc[0] * CAPITAL), CAPITAL)
    summary: dict[str, object] = {"index_source": a.index, "periods": PERIODS, "pass_bar": PASS,
                                  "benchmark_nifty_bh": {p: buy_and_hold(nifty[(nifty.index >= s) & (nifty.index <= e)],
                                                                         CAPITAL).as_dict()
                                                         for p, (s, e) in PERIODS.items()}}
    cards, per_market, crisis = [], [], []
    for variant, filt in (("z5", True), ("raw", False)):
        ms, flagged = markets(a.index, filt)
        summary[f"flagged_days_{variant}"] = flagged
        for rule in RULES:
            r1, r2 = run(rule, ms), run(rule, ms, cost_mult=2.0)
            for p, (s, e) in PERIODS.items():
                s1, s2 = card(r1.daily, s, e), card(r2.daily, s, e)
                sub = r1.daily[(r1.daily.index >= s) & (r1.daily.index <= e)]
                m = monthly_returns_pct(sub * CAPITAL, CAPITAL)
                nm = nifty_m[p].reindex(m.index)
                corr = float(m.corr(nm)) if nm.notna().sum() > 12 else None
                # standalone markets and ex-best market
                standalone = {}
                for mk in ms:
                    rr = run(rule, [mk]).daily
                    standalone[mk.name] = float(rr[(rr.index >= s) & (rr.index <= e)].sum() * 100)
                best = max(standalone, key=lambda k: standalone[k])
                ex = run(rule, [mk for mk in ms if mk.name != best]).daily
                ex_ret = float(ex[(ex.index >= s) & (ex.index <= e)].sum() * 100)
                pos_share = float(np.mean([v > 0 for v in standalone.values()]))
                cards.append({"variant": variant, "rule": rule, "period": p, **s1, "cagr_2x": s2["cagr_pct"],
                              "corr_nifty_monthly": None if corr is None else round(corr, 2),
                              "pass": passes(s1, s2), "markets_positive_share": round(pos_share, 2),
                              "best_market": best, "ex_best_total_pct": round(ex_ret, 2),
                              "entries": int(r1.entries.sum()),
                              "avg_gross_exposure": round(float(r1.weights.abs().sum(axis=1)[
                                  (r1.weights.index >= s) & (r1.weights.index <= e)].mean()), 3)})
                for k, v in standalone.items():
                    per_market.append({"variant": variant, "rule": rule, "period": p, "market": k,
                                       "total_pct_standalone": round(v, 2)})
                worst = nifty_m[p].nsmallest(5)
                for mon, v in worst.items():
                    crisis.append({"variant": variant, "rule": rule, "period": p, "month": str(mon),
                                   "nifty_pct": round(float(v), 2),
                                   "strategy_pct": round(float(m.get(mon, np.nan)), 2)})
    sc = pd.DataFrame(cards)
    robust = {}
    for rule in RULES:
        ok = True
        for variant in ("z5", "raw"):
            for p in PERIODS:
                row = sc[(sc.variant == variant) & (sc.rule == rule) & (sc.period == p)].iloc[0]
                ok &= bool(row["pass"]) and row["markets_positive_share"] >= 0.6 and row["ex_best_total_pct"] > 0
        robust[rule] = ok
    summary["robust"] = robust
    sc.to_csv(out / "scorecards.csv", index=False)
    pd.DataFrame(per_market).to_csv(out / "per_market.csv", index=False)
    pd.DataFrame(crisis).to_csv(out / "crisis.csv", index=False)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    cols = ["variant", "rule", "period", "cagr_pct", "cagr_2x", "max_drawdown_pct", "calmar", "worst_month_pct",
            "sharpe_monthly", "negative_months_pct", "corr_nifty_monthly", "markets_positive_share", "best_market",
            "ex_best_total_pct", "entries", "avg_gross_exposure", "pass"]
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(sc[cols].to_string(index=False))
        print("\nNifty buy-and-hold:", {p: (v["cagr_pct"], v["max_drawdown_pct"])  # type: ignore[index]
                                        for p, v in summary["benchmark_nifty_bh"].items()})  # type: ignore[attr-defined]
        print("flagged days:", summary["flagged_days_z5"])
        print("ROBUST:", robust)
        print(pd.DataFrame(per_market).pivot_table(index=["variant", "rule", "period"], columns="market",
                                                   values="total_pct_standalone").round(1).to_string())
        print(pd.DataFrame(crisis)[lambda x: x.variant == "z5"].to_string(index=False))
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    main()
