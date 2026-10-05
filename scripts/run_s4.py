"""Run the pre-declared S4 factor test (docs/studies/2026-10-05_S4_factor_investing.md).
Writes data/results/s4_<stamp>/ (scorecards.csv, yearly.csv, holdings.csv, summary.json)."""

import json
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from premium.metrics import scorecard  # noqa: E402
from premium.s4 import simulate  # noqa: E402

DB, SNAP = ROOT / "data" / "s4.duckdb", ROOT / "data" / "market.duckdb"
CAPITAL = 200_000.0
PERIODS = {"P-old": ("2007-01-01", "2020-12-31"), "P-recent": ("2021-01-01", "2026-09-30")}
STRATS = ["F1", "F2", "F3", "F1R", "F2R", "F3R"]
DIV_YIELD = 0.012 / 252          # ^NSEI price → total return before NIFTYBEES exists (2007–2008)


def load() -> tuple[pd.DataFrame, pd.Series, pd.Series, dict[str, int]]:
    c = duckdb.connect(str(DB), read_only=True)
    t = c.execute("SELECT symbol, d, adjclose FROM daily WHERE d >= DATE '2005-08-01' AND d <= DATE '2026-09-30'"
                  ).df()
    px = t.pivot(index="d", columns="symbol", values="adjclose").sort_index()
    px.index = pd.DatetimeIndex(px.index)
    rets = px.pct_change(fill_method=None)
    # (b) snapshot overlap: |Yahoo − snapshot| > 10 pp → snapshot return
    s = duckdb.connect(str(SNAP), read_only=True).execute(
        "SELECT symbol, ts::date AS d, close FROM candles WHERE interval='1day' AND symbol LIKE 'NSE-%' "
        "AND close IS NOT NULL").df()
    s["symbol"] = s.symbol.str[4:] + ".NS"
    sp = s.pivot(index="d", columns="symbol", values="close").sort_index()
    sp.index = pd.DatetimeIndex(sp.index)
    sr = sp.pct_change(fill_method=None).reindex(index=rets.index, columns=rets.columns)
    fixes = {"snapshot": 0, "over35": 0}
    use_snap = ((rets - sr).abs() > 0.10) & sr.notna()
    fixes["snapshot"] = int(use_snap.sum().sum())
    rets = rets.mask(use_snap, sr)
    # (c) elsewhere |r| > 35% → 0 (unadjusted corporate action / bad print)
    big = rets.abs() > 0.35
    fixes["over35"] = int(big.sum().sum())
    rets = rets.mask(big, 0.0)
    nifty_px = px["^NSEI"].dropna()
    bees = rets["NIFTYBEES.NS"]
    nifty_r = rets["^NSEI"]
    bench = bees.where(bees.index >= bees.first_valid_index(), nifty_r + DIV_YIELD)
    stocks = rets.drop(columns=["^NSEI", "NIFTYBEES.NS"])
    stocks = stocks.loc[stocks.notna().any(axis=1)]
    regime = (nifty_px > nifty_px.rolling(200).mean()).reindex(stocks.index).ffill().fillna(False).astype(bool)
    return stocks, bench.reindex(stocks.index).fillna(0.0), regime, fixes


def period_card(eq: pd.Series, a: str, b: str) -> dict[str, object]:
    e = eq[(eq.index >= a) & (eq.index <= b)]
    base = eq[eq.index < a].iloc[-1] if (eq.index < a).any() else e.iloc[0]
    rel = e / base * CAPITAL
    pnl = rel.diff().fillna(rel.iloc[0] - CAPITAL)
    return scorecard(pnl, CAPITAL).as_dict()


def yearly(eq: pd.Series) -> pd.Series:
    y = eq.groupby(eq.index.year).last()
    prev = y.shift(1)
    prev.iloc[0] = eq.iloc[0]
    return y / prev - 1


def main() -> None:
    out = ROOT / "data" / "results" / f"s4_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    rets, bench, regime, fixes = load()
    print("data fixes:", fixes, "| stocks:", rets.shape[1], "| days:", len(rets))
    bench_eq = (1 + bench).cumprod()
    res: dict[tuple[str, float], object] = {}
    for cm in (1.0, 2.0):
        res[("EW", cm)] = simulate(rets, "EW", cost_mult=cm)
        for s in STRATS:
            res[(s, cm)] = simulate(rets, s[:2], regime if s.endswith("R") else None, cost_mult=cm)
    rows, yrs = [], {}
    for p, (a, b) in PERIODS.items():
        bc = period_card(bench_eq, a, b)
        ew1, ew2 = period_card(res[("EW", 1.0)].equity, a, b), period_card(res[("EW", 2.0)].equity, a, b)  # type: ignore[attr-defined]
        rows.append({"strategy": "BENCH (Nifty TR)", "period": p, **bc})
        rows.append({"strategy": "EW", "period": p, **ew1, "cagr_2x": ew2["cagr_pct"],
                     "turnover": round(res[("EW", 1.0)].turnover, 3)})  # type: ignore[attr-defined]
        for s in STRATS:
            r1, r2 = res[(s, 1.0)], res[(s, 2.0)]
            c1, c2 = period_card(r1.equity, a, b), period_card(r2.equity, a, b)  # type: ignore[attr-defined]
            f = float
            ok = (f(c1["cagr_pct"]) > f(ew1["cagr_pct"]) and f(c2["cagr_pct"]) > f(ew2["cagr_pct"])  # type: ignore[arg-type]
                  and f(c1["cagr_pct"]) > f(bc["cagr_pct"])  # type: ignore[arg-type]
                  and (c1["sharpe_monthly"] or -9) > (ew1["sharpe_monthly"] or -9))  # type: ignore[operator]
            if s.endswith("R"):
                ok = ok and f(c1["max_drawdown_pct"]) >= -25 and f(c1["worst_month_pct"]) >= -10  # type: ignore[arg-type]
            rows.append({"strategy": s, "period": p, **c1, "cagr_2x": c2["cagr_pct"],
                         "turnover": round(r1.turnover, 3), "pass": ok})  # type: ignore[attr-defined]
    sc = pd.DataFrame(rows)
    ew_y = yearly(res[("EW", 1.0)].equity[res[("EW", 1.0)].equity.index >= "2007-01-01"])  # type: ignore[attr-defined]
    summary: dict[str, object] = {"fixes": fixes, "robust": {}}
    for s in STRATS:
        eq = res[(s, 1.0)].equity  # type: ignore[attr-defined]
        ex = (yearly(eq[eq.index >= "2007-01-01"]) - ew_y)
        yrs[s] = ex.round(4)
        share = float((ex > 0).mean())
        top3 = list(res[(s, 1.0)].contrib.nlargest(3).index)  # type: ignore[attr-defined]
        r_ex = rets.drop(columns=top3)
        s_ex = simulate(r_ex, s[:2], regime if s.endswith("R") else None)
        ew_ex = simulate(r_ex, "EW")
        ex_ok = all(float(period_card(s_ex.equity, a, b)["cagr_pct"])  # type: ignore[arg-type]
                    > float(period_card(ew_ex.equity, a, b)["cagr_pct"])  # type: ignore[arg-type]
                    for a, b in PERIODS.values())
        both = bool(sc[(sc.strategy == s)]["pass"].all())
        summary["robust"][s] = {"pass_both": both, "years_beating_ew": round(share, 2), "top3": top3,  # type: ignore[index]
                                "beats_ew_without_top3": ex_ok, "ROBUST": both and share >= 0.6 and ex_ok}
    holdings = [{"strategy": s, "date": str(d.date()), "names": " ".join(n)} for s in STRATS
                for d, n in res[(s, 1.0)].holdings.items()]  # type: ignore[attr-defined]
    sc.to_csv(out / "scorecards.csv", index=False)
    pd.DataFrame(yrs).to_csv(out / "yearly_excess_vs_ew.csv")
    pd.DataFrame(holdings).to_csv(out / "holdings.csv", index=False)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    cols = ["strategy", "period", "cagr_pct", "cagr_2x", "max_drawdown_pct", "calmar", "worst_month_pct",
            "sharpe_monthly", "negative_months_pct", "turnover", "pass"]
    with pd.option_context("display.width", 220, "display.max_columns", 20):
        print(sc[[c for c in cols if c in sc.columns]].to_string(index=False))
        print("\nYearly excess return vs EW (fraction):")
        print(pd.DataFrame(yrs).round(3).to_string())
        print("\nROBUST:", json.dumps(summary["robust"], indent=1))
        last = {s: res[(s, 1.0)].holdings[max(res[(s, 1.0)].holdings)] for s in STRATS}  # type: ignore[attr-defined]
        print("\nLatest holdings:", json.dumps(last, indent=1))
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    main()
