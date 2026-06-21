# tests/test_commission.py
# P7a: configurable platform take-rate per mode, recorded at settlement; the escrow
# ledger invariant is unaffected (commission only splits the released amount).

from decimal import Decimal
import pytest
from app.commission import commission_rate, compute_commission


class TestRates:
    def test_base_vs_catalog(self):
        assert commission_rate("request") == Decimal("0.15")
        assert commission_rate("collect") == Decimal("0.15")
        assert commission_rate("catalog") == Decimal("0.10")
        assert commission_rate(None) == Decimal("0.15")

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("COMMISSION_RATE_BASE", "0.20")
        monkeypatch.setenv("COMMISSION_RATE_CATALOG", "0.05")
        assert commission_rate("request") == Decimal("0.20")
        assert commission_rate("catalog") == Decimal("0.05")

    def test_compute(self):
        assert compute_commission(100, "request") == Decimal("15.00")
        assert compute_commission(100, "catalog") == Decimal("10.00")
        assert compute_commission("33.33", "request") == Decimal("5.00")   # 4.9995 → 5.00
        assert compute_commission(0, "request") == Decimal("0.00")
        assert compute_commission(None, "catalog") == Decimal("0.00")
