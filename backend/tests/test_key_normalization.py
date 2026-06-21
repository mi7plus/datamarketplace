# tests/test_key_normalization.py
# H1 (S5 dedup-evasion): keys are normalized before hashing, so case/whitespace/
# type near-dupes collapse and can't slip the exact-key dedup.

import io
import csv
from app.keys import normalize_value, normalized_key, key_hash
from app.ingest import validate_dataset

SPEC = {"columns": [{"name": "name", "type": "string", "required": True}],
        "unique_key": ["name"]}


class TestNormalize:
    def test_case_and_whitespace(self):
        assert normalize_value("  Acme   Inc ") == "acme inc"
        assert normalize_value("ACME INC") == "acme inc"
        assert normalize_value(None) == ""
        assert normalize_value(5) == "5"

    def test_near_dupes_same_hash(self):
        a = key_hash({"name": "Acme  Inc"}, ["name"])
        b = key_hash({"name": "acme inc"}, ["name"])
        c = key_hash({"name": " ACME INC "}, ["name"])
        assert a == b == c

    def test_distinct_keys_differ(self):
        assert key_hash({"name": "acme"}, ["name"]) != key_hash({"name": "beta"}, ["name"])

    def test_int_str_equivalence(self):
        assert key_hash({"id": 5}, ["id"]) == key_hash({"id": "5"}, ["id"])


class TestIngestCollapsesNearDupes:
    def test_within_file_dedup_normalizes(self):
        data = io.StringIO(); w = csv.writer(data); w.writerow(["name"])
        w.writerow(["Acme Inc"]); w.writerow(["acme  inc"]); w.writerow(["ACME INC"]); w.writerow(["Other"])
        res = validate_dataset(data.getvalue().encode(), "x.csv", SPEC)
        # 4 rows, but 3 are the same normalized key → 2 unique
        assert res.validated_amount == 2
        assert res.validation_report["duplicate_rows"] == 2
        assert len(set(res.key_hashes)) == 2
