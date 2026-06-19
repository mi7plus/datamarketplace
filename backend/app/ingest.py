# app/ingest.py
#
# Ingest-time validation for submitted datasets.
# Supports CSV and JSONL. Returns a ValidationResult consumed by submissions.py.
#
# Design:
#   - schema_check: required columns present, values type-parseable
#   - quantity: count conforming records → validated_amount
#   - key uniqueness: within-submission dupes excluded from validated_amount
#   - sample: first SAMPLE_ROWS conforming rows (preview for buyer)
#   - hash: SHA-256 of raw file bytes

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from typing import Any, Optional

SAMPLE_ROWS = 5

TYPE_PARSERS: dict[str, Any] = {
    "string":   str,
    "integer":  int,
    "float":    float,
    "boolean":  lambda v: v.strip().lower() in ("true", "1", "yes"),
    "date":     str,   # validated as non-empty string for MVP
    "datetime": str,
}


@dataclass
class ValidationResult:
    valid: bool
    validated_amount: int
    dataset_hash: str
    validation_report: dict
    sample: list[dict]
    key_hashes: list[str] = field(default_factory=list)  # per-record SHA-256 for dedup (populated when spec has unique_key)


def _parse_value(raw: str, col_type: str) -> tuple[bool, Any]:
    """Return (ok, parsed_value). ok=False means the cell failed type parsing."""
    try:
        parsed = TYPE_PARSERS[col_type](raw)
        return True, parsed
    except (ValueError, TypeError):
        return False, None


def _validate_row(
    row: dict[str, str],
    spec_columns: list[dict],
) -> tuple[bool, dict[str, Any], list[str]]:
    """
    Check a single row against the spec.
    Returns (conforms, parsed_row, errors).
    A row with missing required columns or unparseable required cells does not conform.
    Extra columns are allowed (superset).
    """
    parsed: dict[str, Any] = {}
    errors: list[str] = []

    for col in spec_columns:
        name = col["name"]
        col_type = col["type"]
        required = col.get("required", True)
        raw = row.get(name, "")

        if raw == "" or raw is None:
            if required:
                errors.append(f"missing required column '{name}'")
            continue

        ok, val = _parse_value(raw, col_type)
        if not ok:
            if required:
                errors.append(f"column '{name}' cannot be parsed as {col_type}: {raw!r}")
        else:
            parsed[name] = val

    conforms = len(errors) == 0
    return conforms, parsed, errors


def validate_dataset(
    file_bytes: bytes,
    filename: str,
    spec: Optional[dict],
) -> ValidationResult:
    """
    Main entry point. Validates file_bytes against spec (if provided).
    If no spec, every non-empty row counts as valid.
    """
    dataset_hash = hashlib.sha256(file_bytes).hexdigest()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    try:
        if ext == "jsonl":
            rows = _parse_jsonl(file_bytes)
        else:
            rows = _parse_csv(file_bytes)
    except Exception as exc:
        return ValidationResult(
            valid=False,
            validated_amount=0,
            dataset_hash=dataset_hash,
            validation_report={
                "error": f"Failed to parse file: {exc}",
                "total_rows": 0,
                "conforming_rows": 0,
                "rejected_rows": 0,
            },
            sample=[],
        )

    spec_columns: list[dict] = spec.get("columns", []) if spec else []
    unique_key: list[str] = spec.get("unique_key") or [] if spec else []

    total_rows = len(rows)
    conforming: list[dict] = []
    rejected_count = 0
    row_errors: list[dict] = []
    seen_keys: set = set()
    dupe_count = 0

    for i, row in enumerate(rows):
        conforms, parsed, errors = _validate_row(row, spec_columns)
        if not conforms:
            rejected_count += 1
            if len(row_errors) < 10:  # cap error examples in report
                row_errors.append({"row": i + 1, "errors": errors})
            continue

        # Key uniqueness check within this submission
        if unique_key:
            key_val = tuple(str(parsed.get(k, "")) for k in unique_key)
            if key_val in seen_keys:
                dupe_count += 1
                continue
            seen_keys.add(key_val)

        conforming.append(parsed)

    validated_amount = len(conforming)
    sample = conforming[:SAMPLE_ROWS]

    # Build per-record key hashes for cross-provider dedup (F3).
    # Each hash is SHA-256 of the canonical key-tuple string for that record.
    key_hashes: list[str] = []
    if unique_key:
        for parsed_row in conforming:
            key_val = tuple(str(parsed_row.get(k, "")) for k in unique_key)
            key_hashes.append(hashlib.sha256(repr(key_val).encode()).hexdigest())

    report = {
        "total_rows": total_rows,
        "conforming_rows": validated_amount,
        "rejected_rows": rejected_count,
        "duplicate_rows": dupe_count,
        "sample_rows": len(sample),
        "row_errors": row_errors,
    }
    if unique_key:
        report["unique_key"] = unique_key

    return ValidationResult(
        valid=validated_amount > 0,
        validated_amount=validated_amount,
        dataset_hash=dataset_hash,
        validation_report=report,
        sample=sample,
        key_hashes=key_hashes,
    )


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_csv(file_bytes: bytes) -> list[dict[str, str]]:
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _parse_jsonl(file_bytes: bytes) -> list[dict[str, str]]:
    rows = []
    for line in file_bytes.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        # Normalise all values to strings so _validate_row can parse them
        rows.append({k: str(v) for k, v in obj.items()})
    return rows
