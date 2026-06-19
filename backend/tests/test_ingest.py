# tests/test_ingest.py — ingest validation unit tests

import pytest
from app.ingest import validate_dataset

SPEC = {
    "columns": [
        {"name": "id", "type": "integer", "required": True},
        {"name": "name", "type": "string", "required": True},
        {"name": "score", "type": "float", "required": False},
    ],
    "unique_key": ["id"],
}


def csv_bytes(*rows: str) -> bytes:
    return "\n".join(rows).encode()


def jsonl_bytes(*rows: dict) -> bytes:
    import json
    return "\n".join(json.dumps(r) for r in rows).encode()


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

class TestCSVValidation:
    def test_all_conforming(self):
        data = csv_bytes(
            "id,name,score",
            "1,Alice,9.5",
            "2,Bob,8.0",
        )
        result = validate_dataset(data, "data.csv", SPEC)
        assert result.valid
        assert result.validated_amount == 2
        assert result.validation_report["conforming_rows"] == 2
        assert result.validation_report["rejected_rows"] == 0

    def test_missing_required_column_rejected(self):
        # 'name' is required but absent
        data = csv_bytes(
            "id,score",
            "1,9.5",
        )
        result = validate_dataset(data, "data.csv", SPEC)
        assert result.validated_amount == 0
        assert result.validation_report["rejected_rows"] == 1

    def test_wrong_type_required_rejected(self):
        data = csv_bytes(
            "id,name,score",
            "notanint,Alice,9.5",
        )
        result = validate_dataset(data, "data.csv", SPEC)
        assert result.validated_amount == 0

    def test_optional_column_missing_still_conforms(self):
        # score is optional
        data = csv_bytes(
            "id,name",
            "1,Alice",
        )
        result = validate_dataset(data, "data.csv", SPEC)
        assert result.validated_amount == 1

    def test_extra_columns_allowed(self):
        data = csv_bytes(
            "id,name,score,extra",
            "1,Alice,9.5,ignored",
        )
        result = validate_dataset(data, "data.csv", SPEC)
        assert result.validated_amount == 1

    def test_within_submission_dupes_excluded(self):
        data = csv_bytes(
            "id,name",
            "1,Alice",
            "1,Alice-duplicate",  # same key id=1
            "2,Bob",
        )
        result = validate_dataset(data, "data.csv", SPEC)
        # id=1 counted once, duplicate skipped
        assert result.validated_amount == 2
        assert result.validation_report["duplicate_rows"] == 1

    def test_no_spec_counts_all_non_empty_rows(self):
        data = csv_bytes(
            "col1,col2",
            "a,b",
            "c,d",
        )
        result = validate_dataset(data, "data.csv", spec=None)
        assert result.validated_amount == 2

    def test_sample_capped_at_five(self):
        rows = ["id,name"] + [f"{i},Name{i}" for i in range(1, 20)]
        data = csv_bytes(*rows)
        result = validate_dataset(data, "data.csv", SPEC)
        assert len(result.sample) == 5

    def test_dataset_hash_is_sha256(self):
        import hashlib
        raw = csv_bytes("id,name", "1,Alice")
        result = validate_dataset(raw, "data.csv", SPEC)
        expected = hashlib.sha256(raw).hexdigest()
        assert result.dataset_hash == expected

    def test_all_rows_rejected_returns_invalid(self):
        data = csv_bytes(
            "id,name",
            "bad,Alice",
            "alsoBad,Bob",
        )
        result = validate_dataset(data, "data.csv", SPEC)
        assert not result.valid
        assert result.validated_amount == 0


# ---------------------------------------------------------------------------
# JSONL
# ---------------------------------------------------------------------------

class TestJSONLValidation:
    def test_jsonl_conforming(self):
        data = jsonl_bytes(
            {"id": 1, "name": "Alice", "score": 9.5},
            {"id": 2, "name": "Bob"},
        )
        result = validate_dataset(data, "data.jsonl", SPEC)
        assert result.valid
        assert result.validated_amount == 2

    def test_jsonl_dedup(self):
        data = jsonl_bytes(
            {"id": 1, "name": "Alice"},
            {"id": 1, "name": "Duplicate"},
            {"id": 2, "name": "Bob"},
        )
        result = validate_dataset(data, "data.jsonl", SPEC)
        assert result.validated_amount == 2
        assert result.validation_report["duplicate_rows"] == 1


# ---------------------------------------------------------------------------
# Parse failures
# ---------------------------------------------------------------------------

class TestParseFailures:
    def test_unparseable_file_returns_invalid(self):
        result = validate_dataset(b"\x00\xff\xfe broken", "data.csv", SPEC)
        assert not result.valid
        assert result.validated_amount == 0
