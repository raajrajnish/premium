"""Groww option charges per order (values as in the Nifty system's config/costs.yaml, copied 2026-10-04).
STT 0.15% on the sell side is the post-2026-04-01 rate; applying it to earlier history is conservative."""

from dataclasses import dataclass

BROKERAGE = 20.0          # ₹ per executed order
STT_SELL = 0.0015         # on sell-side premium
EXCHANGE = 0.0003503      # NSE options, on premium turnover
SEBI_PER_CR = 10.0
GST = 0.18                # on brokerage + exchange + SEBI
STAMP_BUY = 0.00003       # on buy-side premium


@dataclass(frozen=True)
class OrderCost:
    side: str             # "BUY" | "SELL"
    value: float          # premium × qty (₹)

    @property
    def total(self) -> float:
        exch = self.value * EXCHANGE
        sebi = self.value * SEBI_PER_CR / 1e7
        tax = self.value * (STT_SELL if self.side == "SELL" else STAMP_BUY)
        return BROKERAGE + exch + sebi + tax + (BROKERAGE + exch + sebi) * GST


def order_cost(side: str, price: float, qty: int) -> float:
    return OrderCost(side, price * qty).total
