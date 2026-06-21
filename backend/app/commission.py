# app/commission.py
#
# Platform take-rate (commission) on settled GMV, configurable per intake mode
# (business plan §7.1): base rate on requested/collected/cross-mode fills, a lower
# rate on plain catalog purchases. The platform keeps the commission; the supplier
# receives the net. Escrow accounting (the append-only ledger) is unchanged — the
# full amount still leaves escrow; commission only splits where the released money
# goes (platform vs supplier).

import os
from decimal import Decimal, ROUND_HALF_UP


def _rate(env: str, default: str) -> Decimal:
    try:
        return Decimal(os.getenv(env, default))
    except Exception:
        return Decimal(default)


def commission_rate(source: str | None) -> Decimal:
    """Fraction of a settled amount the platform keeps, by fill source."""
    if source == "catalog":
        return _rate("COMMISSION_RATE_CATALOG", "0.10")   # commodity catalog — thinner
    return _rate("COMMISSION_RATE_BASE", "0.15")          # request / collect / cross-mode


def compute_commission(amount, source: str | None) -> Decimal:
    amt = Decimal(str(amount or 0))
    return (amt * commission_rate(source)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
