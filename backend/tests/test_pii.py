# tests/test_pii.py
# S4: PII detection at ingest — flag emails/phones/national IDs/payment cards,
# auto-quarantine high-risk.

from app.pii import scan_pii_rows, _luhn_ok
from app.ingest import validate_dataset

SPEC = {
    "columns": [
        {"name": "id", "type": "integer", "required": True},
        {"name": "value", "type": "string", "required": True},
    ],
    "unique_key": ["id"],
}


class TestDetectors:
    def test_luhn(self):
        assert _luhn_ok("4242424242424242")    # Stripe test Visa
        assert not _luhn_ok("4242424242424241")

    def test_clean_rows_no_pii(self):
        rows = [{"id": 1, "value": "widget"}, {"id": 2, "value": "gadget"}]
        r = scan_pii_rows(rows)
        assert r["risk"] == "none"
        assert r["emails"] == r["phones"] == r["national_ids"] == r["payment_cards"] == 0

    def test_payment_card_is_high_risk(self):
        rows = [{"id": 1, "value": "card 4242 4242 4242 4242"}]
        r = scan_pii_rows(rows)
        assert r["payment_cards"] == 1
        assert r["risk"] == "high"

    def test_national_id_is_high_risk(self):
        rows = [{"id": 1, "value": "ssn 123-45-6789"}]
        r = scan_pii_rows(rows)
        assert r["national_ids"] == 1
        assert r["risk"] == "high"

    def test_sparse_emails_low_risk(self):
        rows = [{"id": i, "value": ("a@b.com" if i == 0 else "plain")} for i in range(10)]
        r = scan_pii_rows(rows)
        assert r["emails"] == 1
        assert r["risk"] == "low"

    def test_pervasive_contact_is_high_risk(self):
        rows = [{"id": i, "value": f"user{i}@x.com"} for i in range(10)]
        r = scan_pii_rows(rows)
        assert r["emails"] == 10
        assert r["risk"] == "high"


class TestIngestIntegration:
    def test_pii_report_in_validation(self):
        data = b"id,value\n1,john@example.com\n2,jane@example.com\n3,a@b.com\n4,c@d.com\n"
        res = validate_dataset(data, "x.csv", SPEC)
        assert res.pii_report["emails"] == 4
        assert res.validation_report["pii"]["risk"] == "high"

    def test_clean_dataset_no_quarantine_signal(self):
        data = b"id,value\n1,widget\n2,gadget\n"
        res = validate_dataset(data, "x.csv", SPEC)
        assert res.pii_report["risk"] == "none"
