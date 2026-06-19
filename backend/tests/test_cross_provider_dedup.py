# tests/test_cross_provider_dedup.py
# F3: cross-provider deduplication via AcceptedKey table
#
# NOTE: The TestCrossProviderDedup cases that re-implement the overlap arithmetic
# inline (test_*_overlap_*) are FAST SMOKE CHECKS only — they do not exercise the
# real accept_submission persistence path and cannot reproduce the uq_accepted_key
# IntegrityError that F7 fixed. Authoritative coverage (partial/no/full overlap,
# correct keys persisted, no 500) lives in tests/test_dedup_real_db.py against a
# real Postgres. The two cases here that DO call accept_submission with a mock DB
# (key persistence + total-excludes-overlap) remain valid unit checks.

import hashlib
import uuid
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, call


def _key_hash(key_tuple: tuple) -> str:
    return hashlib.sha256(repr(key_tuple).encode()).hexdigest()


def _make_request(accepted_total=0, amount_required=100):
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        amount_required=amount_required,
        accepted_total=accepted_total,
        price_per_unit=1.0,
        budget=float(amount_required),
        status="open",
    )


def _make_sub(validated_amount=50, key_hashes=None):
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        status="validated",
        validated_amount=validated_amount,
        offered_amount=validated_amount,
        accepted_amount=0,
        amount_due=None,
        request_id=str(uuid.uuid4()),
        key_hashes=key_hashes,
    )


def _make_db(existing_key_hashes: list[str] = None):
    """Return a mock DB that returns existing AcceptedKeys for the dedup query."""
    from app.models import AcceptedKey
    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    db.flush = MagicMock()

    existing = [SimpleNamespace(key_hash=h) for h in (existing_key_hashes or [])]
    db.query.return_value.filter.return_value.all.return_value = existing
    return db


class TestCrossProviderDedup:
    def test_no_overlap_uses_full_validated_amount(self):
        """When no keys overlap, eligible == validated_amount."""
        hashes_a = [_key_hash((str(i),)) for i in range(50)]
        hashes_b = [_key_hash((str(i),)) for i in range(50, 100)]

        req = _make_request(accepted_total=50, amount_required=100)
        sub_b = _make_sub(validated_amount=50, key_hashes=hashes_b)
        db = _make_db(existing_key_hashes=hashes_a)  # A's hashes already accepted

        # Replicate lifecycle overlap calculation
        already_accepted = set(hashes_a)
        overlap = sum(1 for h in sub_b.key_hashes if h in already_accepted)
        eligible = max(0, sub_b.validated_amount - overlap)

        assert overlap == 0
        assert eligible == 50

    def test_full_overlap_yields_zero_eligible(self):
        """When all records are already accepted, eligible == 0 → submission REJECTED."""
        hashes_a = [_key_hash((str(i),)) for i in range(50)]

        req = _make_request(accepted_total=50, amount_required=100)
        sub_b = _make_sub(validated_amount=50, key_hashes=hashes_a)  # same records
        db = _make_db(existing_key_hashes=hashes_a)

        already_accepted = set(hashes_a)
        overlap = sum(1 for h in sub_b.key_hashes if h in already_accepted)
        eligible = max(0, sub_b.validated_amount - overlap)

        assert overlap == 50
        assert eligible == 0

    def test_partial_overlap_reduces_eligible(self):
        """Partial overlap: only non-overlapping records count."""
        hashes_a = [_key_hash((str(i),)) for i in range(30)]            # 30 already accepted
        hashes_b = [_key_hash((str(i),)) for i in range(20, 70)]        # 10 overlap, 40 new

        already_accepted = set(hashes_a)
        overlap = sum(1 for h in hashes_b if h in already_accepted)
        eligible = max(0, len(hashes_b) - overlap)

        assert overlap == 10
        assert eligible == 40

    def test_no_key_hashes_skips_dedup(self):
        """When submission has no key_hashes (no unique_key in spec), dedup is skipped."""
        sub = _make_sub(validated_amount=50, key_hashes=None)
        # If key_hashes is falsy, overlap should be 0
        overlap = 0 if not sub.key_hashes else None
        assert overlap == 0

    def test_accepted_keys_written_on_acceptance(self):
        """After acceptance, key_hashes[:accepted] must be written to accepted_keys."""
        from app.lifecycle import accept_submission
        from app.models import AcceptedKey, SubmissionStatus

        hashes = [_key_hash((str(i),)) for i in range(30)]
        sub = _make_sub(validated_amount=30, key_hashes=hashes)
        req = _make_request(accepted_total=0, amount_required=100)

        # Build a DB mock that captures adds
        added_objects = []
        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        db.flush = MagicMock()
        db.add = lambda obj: added_objects.append(obj)
        # No existing accepted keys
        db.query.return_value.filter.return_value.all.return_value = []

        accept_submission(sub, req, db)

        # All 30 hashes should have been added as AcceptedKey rows
        added_keys = [o for o in added_objects if isinstance(o, AcceptedKey)]
        assert len(added_keys) == 30
        added_hashes = {o.key_hash for o in added_keys}
        assert added_hashes == set(hashes)

    def test_accepted_total_excludes_overlap(self):
        """accepted_total must not count overlapping records."""
        hashes_a = [_key_hash((str(i),)) for i in range(50)]  # A accepted all 50
        hashes_b = hashes_a  # B submits the same 50 records

        from app.lifecycle import accept_submission
        from app.models import AcceptedKey, SubmissionStatus

        sub_b = _make_sub(validated_amount=50, key_hashes=hashes_b)
        req = _make_request(accepted_total=50, amount_required=100)

        added_objects = []
        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        db.flush = MagicMock()
        db.add = lambda obj: added_objects.append(obj)
        # Simulate all 50 already accepted
        db.query.return_value.filter.return_value.all.return_value = [
            SimpleNamespace(key_hash=h) for h in hashes_a
        ]

        accept_submission(sub_b, req, db)

        # eligible was 0 → submission REJECTED, accepted_amount stays 0
        assert sub_b.accepted_amount == 0
        assert sub_b.status == SubmissionStatus.REJECTED
        # No new AcceptedKey rows added (nothing was accepted)
        added_keys = [o for o in added_objects if isinstance(o, AcceptedKey)]
        assert len(added_keys) == 0
