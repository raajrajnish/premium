"""S3 data probe: does Groww serve HISTORY for expired MCX commodity and NSE index futures, and how far back?
READ-ONLY market-data calls only (expiry lists + daily candles); no orders; the token is never printed.

Token: GROWW_ACCESS_TOKEN from the environment, else read (read-only) from the Nifty system's .env
(../suzlon/.env), where the morning window stores today's token.
Usage (needs today's token):  uv run --extra broker python scripts/probe_commodities.py
"""

import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "meta" / f"probe_commodities_{datetime.now():%Y%m%d_%H%M}.csv"
MCX = ["CRUDEOILM", "GOLDM", "SILVERM", "NATGASMINI", "COPPER", "CRUDEOIL", "GOLD", "SILVER", "NATURALGAS"]
NSE = ["NIFTY", "BANKNIFTY"]
YEARS = [2021, 2022, 2023, 2024, 2025]


def token() -> str:
    t = os.environ.get("GROWW_ACCESS_TOKEN")
    if not t:
        from dotenv import dotenv_values
        t = dotenv_values(ROOT.parent / "suzlon" / ".env").get("GROWW_ACCESS_TOKEN")
    if not t:
        sys.exit("No Groww token found (run the Nifty system's Start Trading first).")
    return str(t)


def main() -> None:
    from growwapi import GrowwAPI
    g = GrowwAPI(token())
    rows = []
    for exch, seg, names in ((g.EXCHANGE_MCX, g.SEGMENT_COMMODITY, MCX), (g.EXCHANGE_NSE, g.SEGMENT_FNO, NSE)):
        for u in names:
            for y in YEARS:
                exps: list[str] = []
                for m in (3, 9):                                  # two sample months per year
                    try:
                        exps += (g.get_expiries(exchange=exch, underlying_symbol=u, year=y, month=m) or {}).get(
                            "expiries") or []
                    except Exception as e:  # report, keep going
                        rows.append({"exchange": exch, "underlying": u, "year": y, "error": f"expiries: {e}"[:160]})
                    time.sleep(0.3)
                if not exps:
                    rows.append({"exchange": exch, "underlying": u, "year": y, "expiries_found": 0})
                    continue
                exp = date.fromisoformat(sorted(exps)[0])
                sym = f"{exch}-{u}-{exp:%d%b%y}-FUT"
                start = datetime.combine(exp - timedelta(days=150), datetime.min.time())
                try:
                    r = g.get_historical_candles(exchange=exch, segment=seg, groww_symbol=sym,
                                                 start_time=start.strftime("%Y-%m-%d %H:%M:%S"),
                                                 end_time=datetime.combine(exp, datetime.max.time()).strftime(
                                                     "%Y-%m-%d %H:%M:%S"),
                                                 candle_interval=g.CANDLE_INTERVAL_DAY, timeout=30)
                    c = (r or {}).get("candles") or []
                    rows.append({"exchange": exch, "underlying": u, "year": y, "expiries_found": len(exps),
                                 "probe_symbol": sym, "daily_candles": len(c),
                                 "first": str(c[0][0])[:10] if c else None, "last": str(c[-1][0])[:10] if c else None})
                except Exception as e:
                    rows.append({"exchange": exch, "underlying": u, "year": y, "expiries_found": len(exps),
                                 "probe_symbol": sym, "error": f"candles: {type(e).__name__}: {e}"[:160]})
                time.sleep(0.3)
    t = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    t.to_csv(OUT, index=False)
    with pd.option_context("display.width", 220, "display.max_rows", 200, "display.max_colwidth", 70):
        print(t.to_string(index=False))
    print(f"\nWritten to {OUT}")


if __name__ == "__main__":
    main()
