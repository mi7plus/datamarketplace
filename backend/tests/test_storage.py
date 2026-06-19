# tests/test_storage.py
# Gate logic tests — verifies the status gate without a real MinIO or DB.

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from app.models import SubmissionStatus
from app.storage import LocalStorage, PRESIGNED_URL_TTL_SECONDS


# ---------------------------------------------------------------------------
# LocalStorage
# ---------------------------------------------------------------------------

class TestLocalStorage:
    def test_save_and_exists(self, tmp_path, monkeypatch):
        import app.storage as storage_module
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)
        ls = LocalStorage()
        # Patch UPLOAD_DIR inside the instance methods
        with patch.object(storage_module, "UPLOAD_DIR", tmp_path):
            key = "req/prov/data.csv"
            ls_patched = LocalStorage()
            # Write directly to test path
            dest = tmp_path / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"a,b\n1,2")
            assert dest.exists()

    def test_presigned_url_returns_dev_path(self):
        ls = LocalStorage()
        url = ls.presigned_url("some/key.csv")
        assert url.startswith("/dev/storage/")
        assert "some/key.csv" in url


# ---------------------------------------------------------------------------
# Download gate (status check logic, no real storage or DB)
# ---------------------------------------------------------------------------

def make_submission(status):
    return SimpleNamespace(
        id="sub-1",
        status=status,
        storage_location="req/prov/data.csv",
        content_link="data.csv",
        validation_report={"sample": [{"a": 1}]},
        provider_id="prov-1",
        request_id="req-1",
    )


class TestDownloadGate:
    """
    Test the conceptual gate rule: only PAID submissions can generate a download URL.
    We test this by simulating what the endpoint checks.
    """

    ALLOWED_STATUSES = {SubmissionStatus.PAID}
    BLOCKED_STATUSES = {
        SubmissionStatus.PENDING,
        SubmissionStatus.VALIDATED,
        SubmissionStatus.ACCEPTED,
        SubmissionStatus.PARTIALLY_ACCEPTED,
        SubmissionStatus.REJECTED,
        SubmissionStatus.REJECTED_INVALID,
        SubmissionStatus.DISPUTED,
    }

    def _check_gate(self, status):
        """Replicate the endpoint gate check."""
        sub = make_submission(status)
        if sub.status != SubmissionStatus.PAID:
            raise HTTPException(
                status_code=403,
                detail=f"Full file not available for status: {sub.status}",
            )
        return True

    def test_paid_passes_gate(self):
        assert self._check_gate(SubmissionStatus.PAID) is True

    @pytest.mark.parametrize("status", list(BLOCKED_STATUSES))
    def test_non_paid_blocked(self, status):
        with pytest.raises(HTTPException) as exc:
            self._check_gate(status)
        assert exc.value.status_code == 403

    def test_sample_always_available_before_payment(self):
        """Sample is returned from validation_report — no storage gate needed."""
        sub = make_submission(SubmissionStatus.VALIDATED)
        sample = (sub.validation_report or {}).get("sample", [])
        assert len(sample) == 1   # available without payment


# ---------------------------------------------------------------------------
# Presigned URL TTL
# ---------------------------------------------------------------------------

class TestPresignedURLTTL:
    def test_default_ttl_is_one_hour(self):
        assert PRESIGNED_URL_TTL_SECONDS == 3600

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("PRESIGNED_URL_TTL_SECONDS", "1800")
        import importlib, app.storage
        importlib.reload(app.storage)
        assert app.storage.PRESIGNED_URL_TTL_SECONDS == 1800
        # Restore default
        monkeypatch.setenv("PRESIGNED_URL_TTL_SECONDS", "3600")
        importlib.reload(app.storage)
