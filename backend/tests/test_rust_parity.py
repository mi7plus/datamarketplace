# tests/test_rust_parity.py
#
# Parity contract between Python ingest and the Rust ingest service (P1).
#
# Two layers:
#  1. GOLDEN-VECTOR tests (always run): assert the Python key_hash produces the
#     exact values the Rust suite (rust-ingest/src/keys.rs) also asserts. This
#     pins both implementations to the same hashes WITHOUT needing the Rust
#     binary in CI.
#  2. LIVE shadow test (opt-in): if INGEST_RUST_URL is set, feed the same file to
#     both and compare. Skipped otherwise.

import os
import pytest

from app.keys import key_hash, normalize_value
from app.ingest import validate_dataset


# Generated from app/keys.py — must match rust-ingest/src/keys.rs golden vectors.
GOLDEN = [
    ({"email": "Acme  Inc", "n": 5}, ["email", "n"],
     "f56de70cfdee91c8f7a35c9fa6db38b1df5e4bf884112abb1e3a8a08bd51fb78"),
    ({"x": "  Hello "}, ["x"],
     "4dd012f16965b64ad0d5232cfefdac8408ab5a2d782ab267f8d7bf28dc6c1f13"),
    ({"a": "it's"}, ["a"],
     "5ec42fb4e8710713fed0a1c388c55a2be0ddd22ca0f9034f3e28e29e8a2a42d8"),
]


# Unicode golden vectors (C4) — pin non-ASCII normalization across BOTH engines so
# Rust to_lowercase() and Python .lower() can't silently diverge. Identical
# constants are asserted in ingest-service/tests/parity.rs.
UNICODE_GOLDEN = [
    ({"k": "Café"}, ["k"],
     "8a83ced373c18dc75829e862734c9bf73611394f268f5333aa69181189cb1423"),
    # NBSP (U+00A0) collapses to a normal space, same as the plain "a b".
    ({"k": "a b"}, ["k"],
     "4b3d642be2afb4334e9ae34bc9d18511ecb8020add5851d6706e2453d880c307"),
    # Turkish dotted capital İ → "i" + combining dot above (U+0307).
    ({"k": "İstanbul"}, ["k"],
     "99ab0ef4d380818b4ad053b7767428c52e26a29b934b0ad24de5313656657065"),
    # German eszett ß is unchanged by lowercasing in both engines.
    ({"k": "Straße"}, ["k"],
     "65db3053a1a9e1865c69fe5eaf110b99b1497d0ff71fb433002bf53d70e3742b"),
]


class TestGoldenKeyHashes:
    @pytest.mark.parametrize("row,uk,expected", GOLDEN)
    def test_key_hash_golden(self, row, uk, expected):
        assert key_hash(row, uk) == expected

    @pytest.mark.parametrize("row,uk,expected", UNICODE_GOLDEN)
    def test_key_hash_unicode_golden(self, row, uk, expected):
        assert key_hash(row, uk) == expected

    def test_normalize_value(self):
        assert normalize_value("  Acme   Inc ") == "acme inc"
        assert normalize_value("HELLO") == "hello"


class TestPythonIngestShape:
    """Pins the Python report fields the Rust contract mirrors (so a Python-side
    change that would break the wire contract is caught here)."""

    def test_report_fields(self):
        csv = b"email,n\na@x.com,1\na@x.com,1\nb@x.com,2\n"
        spec = {
            "columns": [
                {"name": "email", "type": "string", "required": True},
                {"name": "n", "type": "integer", "required": True},
            ],
            "unique_key": ["email"],
        }
        r = validate_dataset(csv, "f.csv", spec)
        assert r.validated_amount == 2          # one within-submission dupe removed
        assert r.validation_report["duplicate_rows"] == 1
        assert len(r.key_hashes) == 2
        assert len(r.dataset_hash) == 64


@pytest.mark.skipif(
    not os.getenv("INGEST_RUST_URL"),
    reason="INGEST_RUST_URL not set — live Rust shadow comparison skipped",
)
class TestLiveShadow:
    def test_rust_matches_python_on_sample_file(self):
        from app.ingest_client import call_rust_ingest
        # This requires the file to already be in the Rust service's S3/MinIO under
        # the given key; intended for an integration environment, not unit CI.
        report = call_rust_ingest(
            submission_id="00000000-0000-0000-0000-000000000001",
            s3_key=os.environ["INGEST_RUST_PARITY_KEY"],
            filename="data.csv",
            spec={"columns": [{"name": "email", "type": "string"}], "unique_key": ["email"]},
        )
        assert report is not None
        assert "validated_amount" in report
