"""U4 features (docs/U4_README.md §2): F1 multi-level OFI, F2 option-book pressure, F3 micro-price lean,
F4 Hawkes up/down intensity (MLE on previous live days), F5 Kalman Nifty-vs-heavyweights spread, F6 Yang–Zhang σ.
Pure functions over U4's own Feed; deterministic for a given recording."""

import bisect
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd
import u4_core as core

Z_WIN = "30min"
TICK_EVENT = 0.5                                     # pts: a Nifty move this big between live prices is an event
SESSION = (time(9, 15), time(15, 30))


def zscore(s: pd.Series, win: str = Z_WIN, minp: int = 10) -> pd.Series:
    m, sd = s.rolling(win, min_periods=minp).mean(), s.rolling(win, min_periods=minp).std()
    return ((s - m) / sd.replace(0, np.nan)).clip(-4, 4)


def asof(src: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    src = src[~src.index.duplicated(keep="last")].sort_index()
    if src.empty:
        return pd.Series(np.nan, index=idx)
    return src.reindex(src.index.union(idx)).ffill().reindex(idx)


# ------------------------------------------------------------------ F1 multi-level OFI
def mlofi(feed: core.Feed) -> pd.Series:
    if len(feed.futl) < 3:
        return pd.Series(dtype=float)
    rows, depth = [], []
    for k in range(1, len(feed.futl)):
        ts, b, a = feed.futl[k]
        _, pb, pa = feed.futl[k - 1]
        e = 0.0
        for lv in range(5):
            (bp, bq), (pbp, pbq) = b[lv], pb[lv]
            (ap, aq), (pap, paq) = a[lv], pa[lv]
            e += (bq if bp >= pbp else 0.0) - (pbq if bp <= pbp else 0.0)
            e += -(aq if ap <= pap else 0.0) + (paq if ap >= pap else 0.0)
        rows.append((ts, e))
        depth.append((ts, (sum(q for _, q in b) + sum(q for _, q in a)) / 2))
    e = pd.Series([r[1] for r in rows], index=pd.DatetimeIndex([r[0] for r in rows]))
    d = pd.Series([r[1] for r in depth], index=e.index)
    e = e[~e.index.duplicated(keep="last")]
    d = d[~d.index.duplicated(keep="last")]
    ofi = e.rolling("60s").sum() / d.rolling(Z_WIN, min_periods=5).mean().replace(0, np.nan)
    return zscore(ofi)


# ------------------------------------------------------------------ F2 option-book pressure
def option_pressure(feed: core.Feed, grid: pd.DatetimeIndex, spot: pd.Series) -> pd.Series:
    books = {k: ([x[0] for x in v], v) for k, v in feed.optbook.items()}
    by_strike: dict[tuple[int, str], list[str]] = {}
    for k in books:
        m = core.OPT.match(k)
        if m:
            by_strike.setdefault((int(m.group(2)), m.group(3)), []).append(k)
    out = []
    for t in grid:
        s = spot.get(t, np.nan)
        if s != s:
            out.append(np.nan)
            continue
        atm = int(round(s / 50) * 50)
        imb = {"CE": [], "PE": []}
        for strike in range(atm - 100, atm + 101, 50):
            for side in ("CE", "PE"):
                for key in sorted(by_strike.get((strike, side), []))[:1]:       # nearest expiry first
                    ts_l, vals = books[key]
                    i = bisect.bisect_right(ts_l, t) - 1
                    if i >= 0 and t - ts_l[i] <= timedelta(seconds=60):
                        _, b5, s5 = vals[i]
                        imb[side].append((b5 - s5) / (b5 + s5))
        out.append(np.mean(imb["CE"]) - np.mean(imb["PE"]) if imb["CE"] and imb["PE"] else np.nan)
    p = pd.Series(out, index=grid).rolling("60s", min_periods=1).mean()
    return zscore(p)


# ------------------------------------------------------------------ F3 micro-price lean
def micro_lean(feed: core.Feed) -> pd.Series:
    if len(feed.futq) < 3:
        return pd.Series(dtype=float)
    q = pd.DataFrame(feed.futq, columns=["ts", "bid", "bq", "ask", "aq", "b5", "s5"]).drop_duplicates("ts", keep="last")
    q = q.set_index("ts").sort_index()
    spread = (q.ask - q.bid).replace(0, np.nan)
    imb = q.bq / (q.bq + q.aq).replace(0, np.nan)
    micro = q.ask * imb + q.bid * (1 - imb)
    lean = (micro - (q.ask + q.bid) / 2) / spread
    return zscore(lean.rolling("60s", min_periods=1).mean())


def micro_price(bid: float, bq: float, ask: float, aq: float) -> float:
    i = bq / (bq + aq) if (bq + aq) > 0 else 0.5
    return ask * i + bid * (1 - i)


# ------------------------------------------------------------------ F4 Hawkes
def tick_events(day: date) -> tuple[list[float], list[float], float]:
    """Up/down event times (s from 09:15) from a recorded day's Nifty prices, and the session length."""
    f = core.RAW / f"date={day}" / "ltp.jsonl"
    ups, dns, last, t_end = [], [], None, 0.0
    if not f.exists():
        return ups, dns, 0.0
    t0 = datetime.combine(day, SESSION[0])
    with f.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                j = json.loads(line)
            except ValueError:
                continue
            n = (j.get("index") or {}).get("NSE_NIFTY")
            if not n:
                continue
            ts = datetime.fromisoformat(j["recv_ts"]).replace(tzinfo=None)
            if not (SESSION[0] <= ts.time() <= SESSION[1]):
                continue
            t = (ts - t0).total_seconds()
            if last is not None:
                if n - last >= TICK_EVENT:
                    ups.append(t)
                elif last - n >= TICK_EVENT:
                    dns.append(t)
            last, t_end = n, t
    return ups, dns, t_end


def hawkes_loglik(times: list[float], T: float, mu: float, alpha: float, beta: float) -> float:
    if mu <= 0 or T <= 0:
        return -math.inf
    ll, a_i, prev = 0.0, 0.0, None
    for t in times:
        if prev is not None:
            a_i = math.exp(-beta * (t - prev)) * (1 + a_i)
        ll += math.log(mu + alpha * a_i)
        prev = t
    comp = mu * T + (alpha / beta) * sum(1 - math.exp(-beta * (T - t)) for t in times)
    return ll - comp


def fit_hawkes(days: list[tuple[list[float], float]]) -> dict[str, float]:
    """Grid-search MLE over decay β and branching n = α/β < 1; μ = rate × (1 − n). Summed over days."""
    n_ev = sum(len(t) for t, _ in days)
    tot_t = sum(T for _, T in days)
    if n_ev < 50 or tot_t <= 0:
        mu0 = max(n_ev / tot_t, 1e-3) if tot_t else 0.01
        return {"mu": mu0, "alpha": 0.0, "beta": 0.1, "n": 0.0, "ll": float("nan")}
    rate = n_ev / tot_t
    best = {"ll": -math.inf}
    for beta in (0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0):
        for n in (0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 0.95, 0.98):
            mu, alpha = rate * (1 - n), n * beta
            ll = sum(hawkes_loglik(t, T, mu, alpha, beta) for t, T in days)
            if ll > best["ll"]:
                best = {"mu": mu, "alpha": alpha, "beta": beta, "n": n, "ll": ll}
    return best


def hawkes_params(day: date, out_dir: Any) -> dict[str, Any]:
    """Fit on up to 3 previous live days; cached in data/u4/<day>_hawkes.json (frozen for the day)."""
    f = out_dir / f"{day}_hawkes.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    prev = sorted(p.name[5:] for p in core.RAW.glob("date=*") if p.name[5:] < str(day))[-3:]
    up_days, dn_days = [], []
    for d in prev:
        u, dn, T = tick_events(date.fromisoformat(d))
        if T > 3600:
            up_days.append((u, T))
            dn_days.append((dn, T))
    res = {"days": prev, "up": fit_hawkes(up_days), "down": fit_hawkes(dn_days)}
    f.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def hawkes_live(ts_idx: pd.DatetimeIndex, nifty: np.ndarray, p_up: dict[str, float],
                p_dn: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    lam_u, lam_d = np.zeros(len(nifty)), np.zeros(len(nifty))
    au = ad = 0.0
    prev_t = None
    for k in range(len(nifty)):
        t = ts_idx[k].timestamp()
        if prev_t is not None:
            dt = t - prev_t
            au *= math.exp(-p_up["beta"] * dt)
            ad *= math.exp(-p_dn["beta"] * dt)
            ch = nifty[k] - nifty[k - 1]
            if ch >= TICK_EVENT:
                au += 1.0
            elif ch <= -TICK_EVENT:
                ad += 1.0
        lam_u[k] = p_up["mu"] + p_up["alpha"] * au
        lam_d[k] = p_dn["mu"] + p_dn["alpha"] * ad
        prev_t = t
    return lam_u, lam_d


# ------------------------------------------------------------------ F5 Kalman spread
def kalman_spread(grid_df: pd.DataFrame, delta: float = 1e-9) -> pd.DataFrame:
    """y = ln Nifty, x = [1, ln BN, ln HDFC, ln ICICI]; β random walk (W = δ/(1−δ)·I); adaptive measurement noise.
    Returns per grid time: fair value, spread (y − x·β_prior), z vs 60 min, AR(1) half-life (min)."""
    y = np.log(grid_df.nifty.to_numpy())
    X = np.column_stack([np.ones(len(grid_df)), np.log(grid_df.bn), np.log(grid_df.hdfc), np.log(grid_df.icici)])
    beta = np.zeros(4)
    P = np.eye(4) * 1.0
    W = delta / (1 - delta) * np.eye(4)
    V = 1e-6
    spread = np.full(len(y), np.nan)
    for k in range(len(y)):
        if np.isnan(X[k]).any() or np.isnan(y[k]):
            continue
        P = P + W
        x = X[k]
        e = y[k] - x @ beta                          # prediction error with yesterday's β (no look-ahead)
        S = x @ P @ x + V
        K = P @ x / S
        beta = beta + K * e
        P = P - np.outer(K, x) @ P
        V = 0.99 * V + 0.01 * e * e
        spread[k] = e if k > 90 else np.nan          # skip the first 15 min (10-s grid) while the filter settles
    sp = pd.Series(spread, index=grid_df.index)
    m, sd = sp.rolling("60min", min_periods=60).mean(), sp.rolling("60min", min_periods=60).std()
    z = ((sp - m) / sd.replace(0, np.nan)).clip(-6, 6)
    hl = []
    vals = sp.to_numpy()
    for k in range(len(vals)):
        w = vals[max(0, k - 360):k + 1]
        w = w[~np.isnan(w)]
        if len(w) < 60:
            hl.append(np.nan)
            continue
        a, b_ = w[:-1] - w[:-1].mean(), w[1:] - w[1:].mean()
        phi = float((a * b_).sum() / (a * a).sum()) if (a * a).sum() > 0 else 0.0
        hl.append(-math.log(2) / math.log(phi) * 10 / 60 if 0 < phi < 1 else np.nan)
    return pd.DataFrame({"spread": sp, "spread_z": z, "half_life": hl}, index=grid_df.index)


# ------------------------------------------------------------------ F6 Yang–Zhang
def yang_zhang_sigma1m(nifty: pd.Series, at: pd.Timestamp) -> float:
    w = nifty[(nifty.index > at - pd.Timedelta(minutes=60)) & (nifty.index <= at)].dropna()
    if len(w) < 20:
        return float("nan")
    bars = w.resample("5min").ohlc().dropna()
    n = len(bars)
    if n < 4:
        return float("nan")
    o, h, lo, c = (np.log(bars[x].to_numpy()) for x in ("open", "high", "low", "close"))
    ro = o[1:] - c[:-1]
    rc = c - o
    rs = (h - c) * (h - o) + (lo - c) * (lo - o)
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    var = np.var(ro, ddof=1) + k * np.var(rc, ddof=1) + (1 - k) * np.mean(rs)
    return float(math.sqrt(max(var, 0) / 5) * w.iloc[-1])


# ------------------------------------------------------------------ build
@dataclass
class Features:
    ticks: pd.DataFrame
    hawkes: dict[str, Any]


def build(feed: core.Feed) -> Features:
    t = pd.DataFrame([{"ts": ts, "nifty": i.get("NSE_NIFTY"), "bn": i.get("NSE_BANKNIFTY"),
                       "hdfc": i.get("NSE_HDFCBANK"), "icici": i.get("NSE_ICICIBANK")} for ts, i, _ in feed.ltp])
    t = t.drop_duplicates("ts", keep="last").set_index("ts").sort_index().ffill()
    idx = pd.DatetimeIndex(t.index)
    hk = hawkes_params(feed.day, core.OUT)
    lam_u, lam_d = hawkes_live(idx, t.nifty.to_numpy(), hk["up"], hk["down"])
    t["lam_up"], t["lam_dn"] = lam_u, lam_d
    # cascade = intensity vs the long-run average rate λ̄ = μ / (1 − n)
    bar_u = hk["up"]["mu"] / max(1 - hk["up"]["n"], 1e-6)
    bar_d = hk["down"]["mu"] / max(1 - hk["down"]["n"], 1e-6)
    t["casc_up"], t["casc_dn"] = lam_u / bar_u, lam_d / bar_d
    t["hawkes_dir"] = np.log(lam_u / lam_d)
    t["mlofi_z"] = asof(mlofi(feed), idx)
    t["lean_z"] = asof(micro_lean(feed), idx)
    grid = pd.date_range(idx[0].ceil("10s"), idx[-1].floor("10s"), freq="10s")
    g = t[["nifty", "bn", "hdfc", "icici"]].reindex(t.index.union(grid)).ffill().reindex(grid)
    t["book_z"] = asof(option_pressure(feed, grid, g.nifty), idx)
    ks = kalman_spread(g.dropna())
    for col in ("spread_z", "half_life"):
        t[col] = asof(ks[col], idx)
    sig = {m: yang_zhang_sigma1m(t.nifty, m) for m in pd.date_range(idx[0].ceil("1min"), idx[-1], freq="1min")}
    t["sigma1m"] = asof(pd.Series(sig), idx)
    return Features(ticks=t, hawkes=hk)
