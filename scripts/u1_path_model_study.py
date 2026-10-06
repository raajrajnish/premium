"""U1 path model study (protocol: docs/studies/2026-10-06_U1_path_model.md). TRAIN Jul–Aug 2026, TEST Sep 2026.
Read-only on premium's snapshot. Usage: uv run python scripts/u1_path_model_study.py"""

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
c = duckdb.connect(str(ROOT / "data" / "market.duckdb"), read_only=True)
LOT, COST = 65, 2.5
SPLIT = date(2026, 9, 1)
EXPS = [r[0] for r in c.execute("select distinct expiry from contracts where underlying='NIFTY' and kind='CE' "
                                "and expiry >= '2026-07-01' order by 1").fetchall()]
MODELS = ("EC0", "EC1", "EC2", "EC2P")


def load(sym: str, a: str = "2026-07-01", b: str = "2026-10-02") -> pd.DataFrame:
    t = c.execute("select ts, open, high, low, close from candles where symbol=? and interval='1minute' "
                  "and ts >= ? and ts < ? order by ts", [sym, a, b]).df()
    t["ts"] = pd.to_datetime(t.ts).dt.tz_localize(None)
    return t.set_index("ts")


# ---------------------------------------------------------------- exits (identical to the exit study)
def shared(t, j, npk, el):
    noprog, mx = (5, 12) if t["near_exp"] else (8, 20)
    if t["tm"][j] >= time(15, 10):
        return "15:10"
    if el >= noprog and npk < 6:
        return "no progress"
    if el >= mx:
        return "max hold"
    return None


def ec0(t):
    d = t["dir"]
    for j in range(len(t["oc"])):
        if (t["nl"][j] < t["stop_c"]) if d > 0 else (t["nh"][j] > t["stop_c"]):
            return t["oc"][j]
        if d * (t["nc"][j] - t["ema9"][j]) < 0 or t["tm"][j] >= time(15, 10) or j + 1 >= 15:
            return t["oc"][j]
    return t["oc"][-1]


def ec1(t):
    d, e = t["dir"], t["e_nifty"]
    peak, spike = 0.0, False
    for j in range(len(t["oc"])):
        worst = (t["nl"][j] - e) if d > 0 else (e - t["nh"][j])
        best = (t["nh"][j] - e) if d > 0 else (e - t["nl"][j])
        if (t["ol"][j] - t["e_opt"] - COST) * LOT <= -600:
            return max(t["ol"][j], t["e_opt"] + COST - 600 / LOT)
        if worst <= (-12 if peak < 6 else 0):
            return t["oc"][j]
        peak = max(peak, best)
        spike = spike or (peak >= 15 and j + 1 <= 2)
        g = (t["nc"][j] - e) * d
        if (spike and g <= 0.75 * peak) or (peak >= 10 and g <= 0.5 * peak) or shared(t, j, peak, j + 1):
            return t["oc"][j]
    return t["oc"][-1]


def ec2x(t, plus):
    e, d = t["e_opt"], t["dir"]
    L = min(0.25, max(0.10, 3 * t["pre_vol"])) if plus and not np.isnan(t["pre_vol"]) else 0.20
    peak, floor, npk = 0.0, None, 0.0
    for j in range(len(t["oc"])):
        loss = L / 2 if (plus and j + 1 > 5 and peak < 0.08) else L
        lvl = (COST / e) if (plus and peak >= 0.08) else -loss
        chk = (t["oc"][j] if plus else t["ol"][j]) / e - 1
        if floor is not None and chk <= floor:
            return t["oc"][j] if plus else e * (1 + floor)
        if floor is None and chk <= lvl:
            return t["oc"][j] if plus else e * (1 + lvl)
        peak = max(peak, t["oh"][j] / e - 1)
        if peak >= 0.15:
            keep = (0.75 if peak < 0.40 else 0.80 if peak < 0.80 else 0.85) if plus else 0.75
            floor = max(0.15, peak * keep)
        npk = max(npk, (t["nh"][j] - t["e_nifty"]) if d > 0 else (t["e_nifty"] - t["nl"][j]))
        if shared(t, j, npk, j + 1):
            return t["oc"][j] if floor is None else max(t["oc"][j], e * (1 + floor))
    return t["oc"][-1]


# ---------------------------------------------------------------- signals, features, labels
N = load("NSE-NIFTY")
X = {k: load(s)["close"] for k, s in (("bn", "NSE-BANKNIFTY"), ("hdfc", "NSE-HDFCBANK"), ("icici", "NSE-ICICIBANK"),
                                       ("vix", "NSE-INDIAVIX"))}
rows = []
for day, b in N.groupby(N.index.date):
    b = b[(b.index.time >= time(9, 15)) & (b.index.time <= time(15, 29))].copy()
    if len(b) < 200 or day > date(2026, 9, 29):
        continue
    for k, s in X.items():
        b[k] = s.reindex(b.index).ffill()
    cl = b.close
    mid, sd = cl.rolling(20).mean(), cl.rolling(20).std(ddof=0)
    b["mid"], b["bb_up"], b["bb_lo"], b["bw"] = mid, mid + 2 * sd, mid - 2 * sd, 4 * sd / mid
    d1 = cl.diff()
    up = d1.clip(lower=0).ewm(alpha=1 / 7, adjust=False).mean()
    dn = (-d1.clip(upper=0)).ewm(alpha=1 / 7, adjust=False).mean()
    b["rsi"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    macd = cl.ewm(span=12, adjust=False).mean() - cl.ewm(span=26, adjust=False).mean()
    b["macdh"] = macd - macd.ewm(span=9, adjust=False).mean()
    b["ema9"] = cl.ewm(span=9, adjust=False).mean()
    tr = pd.concat([b.high - b.low, (b.high - cl.shift()).abs(), (b.low - cl.shift()).abs()], axis=1).max(axis=1)
    b["atr"] = tr.rolling(14).mean()
    b["mabs30"] = d1.abs().rolling(30).mean()
    c3 = cl.resample("3min", origin="start_day", offset="9h15min").last().dropna()
    e9, e21 = c3.ewm(span=9, adjust=False).mean(), c3.ewm(span=21, adjust=False).mean()
    f3 = pd.DataFrame({"e9": e9.to_numpy(), "e21": e21.to_numpy(), "e9p": e9.shift(1).to_numpy()},
                      index=c3.index + timedelta(minutes=2))
    b = b.join(f3.reindex(b.index, method="ffill"))
    open0 = float(b.open.iloc[0])
    last = -99
    for i in range(30, len(b) - 1):
        if not (time(9, 45) <= b.index[i].time() <= time(14, 30)) or i - last < 5:
            continue
        r, p, p5, b3 = b.iloc[i], b.iloc[i - 1], b.iloc[i - 5], b.iloc[i - 3]
        for d in (1, -1):
            if not (d * (r.e9 - r.e21) > 0 and d * (r.e9 - r.e9p) > 0):
                continue
            band = bool(((r.close > r.bb_up) if d > 0 else (r.close < r.bb_lo)) and r.bw > p5.bw)
            brk = bool((r.close > b.high.iloc[i - 5:i].max()) if d > 0 else (r.close < b.low.iloc[i - 5:i].min()))
            if not (band or brk):
                continue
            st = bool((60 <= r.rsi <= 80 and r.macdh > 0 and r.macdh > p.macdh) if d > 0 else
                      (20 <= r.rsi <= 40 and r.macdh < 0 and r.macdh < p.macdh))
            hv = bool(sum(d * (r[k] - b3[k]) > 0 for k in ("bn", "hdfc", "icici")) >= 2)
            vx = bool((r.vix - b3.vix <= 0) if d > 0 else (r.vix - b3.vix >= 0))
            conf = int(st) + int(hv) + int(vx)
            if conf < 2:
                continue
            cls = "K1" if band and brk and conf == 3 else ("K3" if brk and hv and vx else "K4")
            hi, lo = b.high.iloc[:i + 1].max(), b.low.iloc[:i + 1].min()
            pos = (r.close - lo) / (hi - lo) if hi > lo else 0.5
            atr = float(r.atr) if r.atr > 0 else 1.0
            feat = {"band": band, "brk": brk, "strength": st, "heavy": hv, "vixok": vx, "conf": conf,
                    "K1": cls == "K1", "K3": cls == "K3", "K4": cls == "K4",
                    "atr": atr, "mabs30": float(r.mabs30),
                    "mom5": d * (r.close - b.close.iloc[i - 5]) / atr,
                    "mom15": d * (r.close - b.close.iloc[i - 15]) / atr,
                    "bn15": d * (r.bn / b.bn.iloc[i - 15] - 1) * 100,
                    "trend3": d * (r.e9 - r.e21) / atr, "dist_mid": d * (r.close - r.mid) / atr,
                    "range_pos": pos if d > 0 else 1 - pos, "from_open": d * (r.close / open0 - 1) * 100,
                    "tod": (b.index[i].hour - 9) * 60 + b.index[i].minute - 15, "vix": float(r.vix),
                    "vix3": -d * (r.vix - b3.vix), "rsi_d": r.rsi if d > 0 else 100 - r.rsi,
                    "macd_d": d * r.macdh / atr}
            rows.append({"day": day, "i": i, "t": b.index[i], "dir": d, "cls": cls,
                         "stop_c": float(r.low if d > 0 else r.high), "b": b, **feat})
            last = i
            break

trades = []
for s in rows:
    day, i, d, b = s["day"], s["i"], s["dir"], s["b"]
    exp = next((e for e in EXPS if e >= day), None)
    if exp is None:
        continue
    strike = int(round(b.close.iloc[i] / 50) * 50)
    sym = f"NSE-NIFTY-{exp:%d%b%y}-{strike}-{'CE' if d > 0 else 'PE'}"
    t0 = b.index[i + 1]
    pre = load(sym, str(t0 - timedelta(minutes=11)), str(t0))
    o = load(sym, str(t0), str(t0 + timedelta(minutes=31)))
    nb = b.iloc[i + 1:i + 31]
    o = o.reindex(nb.index)
    if o.empty or np.isnan(o.open.iloc[0]):
        continue
    o = o.ffill()
    t = {k: v for k, v in s.items() if k != "b"} | {
        "near_exp": (exp - day).days <= 1, "dte": (exp - day).days, "e_opt": float(o.open.iloc[0]),
        "e_nifty": float(nb.open.iloc[0]), "oh": o.high.to_numpy(), "ol": o.low.to_numpy(), "oc": o.close.to_numpy(),
        "nh": nb.high.to_numpy(), "nl": nb.low.to_numpy(), "nc": nb.close.to_numpy(), "ema9": nb.ema9.to_numpy(),
        "tm": [x.time() for x in nb.index],
        "pre_vol": float(pre.close.pct_change().abs().tail(10).mean()) if len(pre) >= 4 else np.nan}
    t["prem"] = t["e_opt"]
    # label GOOD: +15 before −12 within 15 min (minute highs/lows; cautious: a minute touching both = not good)
    good = False
    for j in range(min(15, len(t["nc"]))):
        fav = (t["nh"][j] - t["e_nifty"]) if d > 0 else (t["e_nifty"] - t["nl"][j])
        adv = (t["nl"][j] - t["e_nifty"]) if d > 0 else (t["e_nifty"] - t["nh"][j])
        if adv <= -12:
            break
        if fav >= 15:
            good = True
            break
    t["GOOD"] = good
    for m, px in (("EC0", ec0(t)), ("EC1", ec1(t)), ("EC2", ec2x(t, False)), ("EC2P", ec2x(t, True))):
        t[m] = (px - t["e_opt"] - COST) * LOT
    trades.append(t)

FEATS = ["band", "brk", "strength", "heavy", "vixok", "conf", "K1", "K3", "K4", "atr", "mabs30", "mom5", "mom15",
         "bn15", "trend3", "dist_mid", "range_pos", "from_open", "tod", "vix", "vix3", "rsi_d", "macd_d", "dte", "prem"]
df = pd.DataFrame([{k: t[k] for k in ["day", "t", "dir", "cls", "GOOD", *MODELS, *FEATS]} for t in trades])
df[FEATS] = df[FEATS].astype(float).fillna(0.0)
tr, te = df[df.day < SPLIT].reset_index(drop=True), df[df.day >= SPLIT].reset_index(drop=True)
mu, sg = tr[FEATS].mean(), tr[FEATS].std().replace(0, 1)
Ztr, Zte = ((tr[FEATS] - mu) / sg).to_numpy(), ((te[FEATS] - mu) / sg).to_numpy()
print(f"signals with option data: {len(df)} | TRAIN {len(tr)} ({tr.day.nunique()} days) | TEST {len(te)} "
      f"({te.day.nunique()} days) | GOOD rate train {tr.GOOD.mean():.0%}, test {te.GOOD.mean():.0%}")


# ---------------------------------------------------------------- model 1: k nearest neighbours (k = 50)
def knn_predict(Zq, qdays, Zref, ref, k=50, exclude_same_day=False):
    out = []
    for z, dday in zip(Zq, qdays, strict=True):
        dist = np.sqrt(((Zref - z) ** 2).sum(axis=1))
        if exclude_same_day:
            dist = np.where(ref.day.to_numpy() == dday, np.inf, dist)
        nn = np.argsort(dist)[:k]
        g = ref.iloc[nn]
        out.append({"p_good": g.GOOD.mean(), **{f"ev_{m}": g[m].mean() for m in MODELS},
                    "best_hint": None})
    return pd.DataFrame(out)


k_tr = knn_predict(Ztr, tr.day, Ztr, tr, exclude_same_day=True)
k_te = knn_predict(Zte, te.day, Ztr, tr)


# ---------------------------------------------------------------- model 2: logistic regression (L2), numpy
def logit_fit(Z, y, lam=1.0, it=3000, lr=0.1):
    Zb = np.c_[np.ones(len(Z)), Z]
    w = np.zeros(Zb.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-Zb @ w))
        g = Zb.T @ (p - y) / len(y) + lam * np.r_[0, w[1:]] / len(y)
        w -= lr * g
    return w


w = logit_fit(Ztr, tr.GOOD.to_numpy().astype(float))
p_tr = 1 / (1 + np.exp(-np.c_[np.ones(len(Ztr)), Ztr] @ w))
p_te = 1 / (1 + np.exp(-np.c_[np.ones(len(Zte)), Zte] @ w))
thr = float(np.quantile(p_tr, 0.70))


def judge(name, enter, data):
    res = {}
    for grp, mask in (("ENTER", enter), ("SKIP", ~enter), ("ALL", np.ones(len(data), bool))):
        g = data[mask]
        res[grp] = {"n": int(len(g)), "good%": round(100 * g.GOOD.mean()) if len(g) else None,
                    **{m: round(g[m].mean()) if len(g) else None for m in MODELS}}
    return res


out = {"R2 logistic top-30% (threshold from TRAIN)": {"TRAIN": judge("", p_tr >= thr, tr),
                                                       "TEST": judge("", p_te >= thr, te)}}
for m in MODELS:
    out[f"R1 kNN EV>0 under {m}"] = {"TRAIN": judge("", k_tr[f"ev_{m}"].to_numpy() > 0, tr),
                                    "TEST": judge("", k_te[f"ev_{m}"].to_numpy() > 0, te)}
pd.set_option("display.width", 250)
for rule, r in out.items():
    print(f"\n=== {rule} ===")
    for per in ("TRAIN", "TEST"):
        tab = pd.DataFrame(r[per]).T
        print(f"[{per}]\n{tab.to_string()}")
coef = pd.Series(w[1:], index=FEATS).sort_values()
print("\nlogistic coefficients (standardised; + = more likely GOOD):")
print(coef.round(2).to_string())
# calibration on TEST: do higher predictions mean better outcomes?
te2 = te.assign(p=p_te, knn=k_te.p_good.to_numpy())
te2["p_bin"] = pd.qcut(te2.p, 4, labels=["lowest 25%", "2nd", "3rd", "highest 25%"])
print("\nTEST by logistic prediction quartile:")
print(te2.groupby("p_bin", observed=True).agg(n=("GOOD", "size"), good=("GOOD", "mean"),
                                              **{m: (m, "mean") for m in MODELS}).round(2).to_string())
res_dir = ROOT / "data" / "results" / f"u1_path_model_{datetime.now():%Y%m%d_%H%M}"
res_dir.mkdir(parents=True, exist_ok=True)
(res_dir / "summary.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
df.to_csv(res_dir / "signals.csv", index=False)
print(f"\nWritten to {res_dir}")
