"""Read-only access to premium's OWN snapshot of the market database (copied nightly by scripts/snapshot.ps1).

Schema (from suzlon's MarketStore, copied 2026-10-04):
candles(symbol, interval, ts, open, high, low, close, volume, oi), contracts(symbol, underlying, kind, expiry, strike).
Symbols: "NSE-NIFTY", "NSE-NIFTY-06Oct26-22700-CE", ...
premium never opens suzlon's database file.
"""

from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "data" / "market.duckdb"


class Snapshot:
    def __init__(self, path: Path = SNAPSHOT) -> None:
        if not path.exists():
            raise FileNotFoundError(f"{path} missing — run scripts/snapshot.ps1 after suzlon's End of Day")
        self.con = duckdb.connect(str(path), read_only=True)

    def close(self) -> None:
        self.con.close()

    def candles(self, symbol: str, interval: str = "1minute", start: datetime | None = None,
                end: datetime | None = None) -> pd.DataFrame:
        q = "SELECT ts, open, high, low, close, volume, oi FROM candles WHERE symbol=? AND interval=?"
        args: list[object] = [symbol, interval]
        if start is not None:
            q += " AND ts >= ?"
            args.append(start)
        if end is not None:
            q += " AND ts <= ?"
            args.append(end)
        df: pd.DataFrame = self.con.execute(q + " ORDER BY ts", args).df()
        return df

    def expiries(self, underlying: str = "NIFTY") -> list[date]:
        rows = self.con.execute("SELECT DISTINCT expiry FROM contracts WHERE kind='CE' AND underlying=? "
                                "ORDER BY expiry", [underlying]).fetchall()
        return [r[0] for r in rows]

    def strikes(self, underlying: str, expiry: date) -> list[int]:
        rows = self.con.execute("SELECT DISTINCT strike FROM contracts WHERE underlying=? AND expiry=? AND kind='CE' "
                                "ORDER BY strike", [underlying, expiry]).fetchall()
        return [int(r[0]) for r in rows]


def option_symbol(underlying: str, expiry: date, strike: int, side: str) -> str:
    return f"NSE-{underlying}-{expiry:%d%b%y}-{strike}-{side}"
