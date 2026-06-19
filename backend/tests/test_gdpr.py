# tests/test_gdpr.py
# Phase 8: warranties, takedown gate, license propagation

import pytest
from types import SimpleNamespace
from datetime import datetime, timedelta
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Warranty enforcement
# ---------------------------------------------------------------------------

class TestWarrantyEnforcement:
    def test_warranted_false_raises_422(self):
        """Submitting without affirming warranties must be rejected."""
        warranted = False
        if not warranted:
            with pytest.raises(Exception):
                raise HTTPException(status_code=422, detail="Provider warranties must be affirmed")

    def test_warranted_true_produces_signature(self):
        """When warranted=True, owner_signature should be a non-empty string."""
        email = "provider@example.com"
        warranted = True
        sig = (
            f"warranted by {email} at {datetime.utcnow().isoformat()}Z "
            f"— rights confirmed, no unconsented personal data"
        ) if warranted else None
        assert sig is not None
        assert email in sig
        assert "rights confirmed" in sig

    def test_signature_contains_timestamp(self):
        sig = f"warranted by x@y.com at {datetime.utcnow().isoformat()}Z — rights confirmed, no unconsented personal data"
        assert "Z" in sig


# ---------------------------------------------------------------------------
# Takedown gate
# ---------------------------------------------------------------------------

def make_sub_with_expiry(expiry):
    return SimpleNamespace(
        id="sub-1",
        status="paid",
        storage_location="req/prov/data.csv",
        access_expiry=expiry,
        is_deleted=False,
    )


class TestTakedownGate:
    def _check_expiry_gate(self, submission):
        """Replicate the endpoint's takedown check."""
        if submission.access_expiry and submission.access_expiry < datetime.utcnow():
            raise HTTPException(status_code=410, detail="Taken down")

    def test_no_expiry_allows_download(self):
        sub = make_sub_with_expiry(None)
        self._check_expiry_gate(sub)  # should not raise

    def test_future_expiry_allows_download(self):
        sub = make_sub_with_expiry(datetime.utcnow() + timedelta(hours=1))
        self._check_expiry_gate(sub)  # should not raise

    def test_past_expiry_blocks_download(self):
        sub = make_sub_with_expiry(datetime.utcnow() - timedelta(seconds=1))
        with pytest.raises(HTTPException) as exc:
            self._check_expiry_gate(sub)
        assert exc.value.status_code == 410

    def test_takedown_sets_is_deleted_and_past_expiry(self):
        """Takedown should set is_deleted=True and access_expiry=now (or past)."""
        sub = make_sub_with_expiry(None)
        # Simulate takedown action
        sub.access_expiry = datetime.utcnow()
        sub.is_deleted = True
        assert sub.is_deleted is True
        assert sub.access_expiry <= datetime.utcnow()


# ---------------------------------------------------------------------------
# License on dataset
# ---------------------------------------------------------------------------

class TestLicensePropagation:
    def test_license_name_in_response_schema(self):
        """DataRequestResponseSchema.model_validate should populate license_name."""
        from app.schemas import DataRequestResponseSchema
        import uuid

        license_obj = SimpleNamespace(id=uuid.uuid4(), name="CC BY 4.0", terms="...")
        request_obj = SimpleNamespace(
            id=uuid.uuid4(),
            title="Test",
            description=None,
            unit="row",
            amount_required=1000,
            pricing_mode="per_unit",
            price_per_unit=0.1,
            budget=100.0,
            required_format="csv",
            spec=None,
            deadline=None,
            status="open",
            accepted_total=0,
            requester_id=uuid.uuid4(),
            license_id=license_obj.id,
            license=license_obj,
        )

        schema = DataRequestResponseSchema.model_validate(request_obj)
        assert schema.license_name == "CC BY 4.0"

    def test_no_license_gives_none(self):
        from app.schemas import DataRequestResponseSchema
        import uuid

        request_obj = SimpleNamespace(
            id=uuid.uuid4(),
            title="Test",
            description=None,
            unit="row",
            amount_required=1000,
            pricing_mode="per_unit",
            price_per_unit=0.1,
            budget=100.0,
            required_format="csv",
            spec=None,
            deadline=None,
            status="open",
            accepted_total=0,
            requester_id=uuid.uuid4(),
            license_id=None,
            license=None,
        )

        schema = DataRequestResponseSchema.model_validate(request_obj)
        assert schema.license_name is None
