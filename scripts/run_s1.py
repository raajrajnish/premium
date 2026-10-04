"""Run S1 (spec: docs/studies/2026-10-04_S1_defined_risk_selling.md) on premium's snapshot. Read-only.
Usage: uv run python scripts/run_s1.py
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from premium.data import Snapshot  # noqa: E402
from premium.metrics import buy_and_hold, scorecard  # noqa: E402
from premium.s1 import eligible, simulate  # noqa: E402

CAPITAL = 200_000.0
START, END, SPLIT = date(2023, 12, 1), date(2026, 9, 30), date(2025, 6, 30)
OUT = Path(__file__).resolve().parents[1] / "data" / "results" / f"s1_{datetime.now():%Y%m%d_%H%M}"
OUT.mkdir(parents=True, exist_ok=True)


def boot_ci(v: np.ndarray, n: int = 5000) -> tuple[float, float]:
    rng = np.random.default_rng(7)
    means = rng.choice(v, size=(n, len(v)), replace=True).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


snap = Snapshot()
try:
    rows = [simulate(snap, s, d, e) for s, d, e in eligible(snap, START, END)]
    idx = snap.candles("NSE-NIFTY", "1minute", datetime(2023, 12, 1), datetime(2026, 9, 30, 23, 59))
finally:
    snap.close()
t = pd.DataFrame(rows)
t.to_csv(OUT / "positions.csv", index=False)
daily = idx.groupby(idx["ts"].dt.date)["close"].last()
day_move = (daily.pct_change().abs() * 100).rename("abs_day_move_pct")

report: dict[str, object] = {}
lines = []
for sid, g in t.groupby("structure"):
    ok = g[g["status"] == "OK"].copy()
    skip = g[g["status"] != "OK"]
    cov = len(ok) / len(g) * 100
    mv_ok = day_move.reindex(ok["expiry"]).mean()
    mv_skip = day_move.reindex(skip["expiry"]).mean() if len(skip) else float("nan")
    ok["exit_ts"] = pd.to_datetime(ok["exit_ts"])
    res: dict[str, object] = {"coverage_pct": round(cov, 1), "n_ok": len(ok), "n_skipped": len(skip),
                              "avg_abs_move_traded_days": round(float(mv_ok), 2),
                              "avg_abs_move_skipped_days": round(float(mv_skip), 2)}
    passes = []
    for half, sub in (("H-A", ok[ok["expiry"] <= SPLIT]), ("H-B", ok[ok["expiry"] > SPLIT])):
        pnl = pd.Series(sub["net_inr"].to_numpy(), index=sub["exit_ts"])
        sc = scorecard(pnl, CAPITAL)
        w, lo_ = sub[sub["net_inr"] > 0]["net_inr"].sum(), -sub[sub["net_inr"] <= 0]["net_inr"].sum()
        pf = w / lo_ if lo_ > 0 else float("inf")
        ok_half = bool(len(sub) >= 30 and sub["net_inr"].sum() > 0 and sub["net2_inr"].sum() > 0 and pf >= 1.2
                       and sc.worst_month_pct >= -6.0 and sc.max_drawdown_pct >= -15.0)
        passes.append(ok_half)
        res[half] = {"n": len(sub), "net_per_trade": round(float(sub["net_inr"].mean()), 1),
                     "net2_per_trade": round(float(sub["net2_inr"].mean()), 1), "pf": round(pf, 2),
                     "win%": round(float((sub["net_inr"] > 0).mean() * 100), 1),
                     "return_on_margin%_per_trade": round(float((sub["net_inr"] / sub["margin_inr"]).mean() * 100), 2),
                     "max_loss_per_trade_avg": round(float(sub["max_loss_inr"].mean()), 0),
                     "scorecard": sc.as_dict(), "PASS": ok_half}
    v = ok["net_inr"].to_numpy()
    lo, hi = boot_ci(v) if len(v) >= 10 else (float("nan"), float("nan"))
    ex5 = float(np.sort(v)[::-1][5:].mean()) if len(v) > 5 else float("nan")
    robust = bool(all(passes) and lo > 0 and ex5 > 0)
    full = scorecard(pd.Series(ok["net_inr"].to_numpy(), index=ok["exit_ts"]), CAPITAL)
    res |= {"all": full.as_dict(), "mean_ci95": [round(lo, 1), round(hi, 1)], "ex_top5_mean": round(ex5, 1),
            "PASS_both_halves": bool(all(passes)), "ROBUST": robust}
    stress = ok.assign(abs_move=ok["move_pct"].abs()).nlargest(10, "abs_move")[
        ["entry_day", "expiry", "move_pct", "strikes", "credit_pts", "max_loss_inr", "net_inr"]]
    res["stress_days"] = json.loads(stress.to_json(orient="records", date_format="iso"))
    report[sid] = res
    lines.append(f"{sid}: coverage {cov:.0f}% (n={len(ok)}, skipped {len(skip)}; avg |day move| traded "
                 f"{mv_ok:.2f}% vs skipped {mv_skip:.2f}%) | H-A {res['H-A']['net_per_trade']:+.0f}/trade "  # type: ignore[index]
                 f"PASS={passes[0]} | H-B {res['H-B']['net_per_trade']:+.0f}/trade PASS={passes[1]} | "  # type: ignore[index]
                 f"CI [{lo:.0f}, {hi:.0f}] ex-top5 {ex5:+.0f} | ROBUST={robust}")
bench = buy_and_hold(daily, CAPITAL)
report["nifty_buy_and_hold"] = bench.as_dict()
(OUT / "report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
print("\n".join(lines))
for sid in sorted(k for k in report if k.startswith("S1")):
    r = report[sid]
    print(f"\n=== {sid} ===")
    for half in ("H-A", "H-B"):
        h = r[half]  # type: ignore[index]
        sc = h["scorecard"]
        print(f" {half}: n={h['n']} net/trade {h['net_per_trade']:+.0f} (2x costs {h['net2_per_trade']:+.0f}) "
              f"PF {h['pf']} win {h['win%']}% | CAGR {sc['cagr_pct']}% maxDD {sc['max_drawdown_pct']}% "
              f"worst month {sc['worst_month_pct']}% worst trade {sc['worst_trade_pct']}% worst-5 "
              f"{sc['worst_5_consecutive_pct']}% | avg max loss ₹{h['max_loss_per_trade_avg']:.0f}, "
              f"return on margin {h['return_on_margin%_per_trade']}%/trade")
    print(" stress days (largest Nifty moves while in a position):")
    for s_ in r["stress_days"][:6]:  # type: ignore[index]
        print(f"   {s_['expiry'][:10]} move {s_['move_pct']:+.2f}% net ₹{s_['net_inr']:+,.0f} "
              f"(max loss ₹{s_['max_loss_inr']:,.0f}) {s_['strikes']}")
print(f"\nNifty buy-and-hold same period (₹{CAPITAL:,.0f}): CAGR {bench.cagr_pct}%, max DD {bench.max_drawdown_pct}%, "
      f"worst month {bench.worst_month_pct}%")
print(f"Written to {OUT}")
