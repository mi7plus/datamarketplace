# tests/test_ingest_quality.py
# S2: statistical/quality signals + sample formula-injection neutralization.

from app.ingest import validate_dataset, _neutralize_cell

SPEC = {
    "columns": [
        {"name": "id", "type": "integer", "required": True},
        {"name": "value", "type": "string", "required": True},
        {"name": "note", "type": "string", "required": False},
    ],
    "unique_key": ["id"],
}


def _csv(rows: str) -> bytes:
    return rows.encode()


class TestSampleNeutralization:
    def test_neutralize_formula_triggers(self):
        assert _neutralize_cell("=1+1") == "'=1+1"
        assert _neutralize_cell("+cmd") == "'+cmd"
        assert _neutralize_cell("-2") == "'-2"
        assert _neutralize_cell("@SUM") == "'@SUM"
        assert _neutralize_cell("\tx") == "'\tx"

    def test_leaves_plain_values(self):
        assert _neutralize_cell("hello") == "hello"
        assert _neutralize_cell("123abc") == "123abc"
        assert _neutralize_cell(5) == 5   # non-strings untouched

    def test_sample_is_neutralized_in_validation(self):
        # A cell that looks like a spreadsheet formula must be inert in the preview.
        data = _csv("id,value,note\n1,=cmd|'/c calc'!A1,ok\n2,safe,ok\n")
        res = validate_dataset(data, "x.csv", SPEC)
        # The malicious-looking value appears in the sample, but neutralized.
        cell = res.sample[0]["value"]
        assert cell.startswith("'="), f"sample cell not neutralized: {cell!r}"


class TestQualityStats:
    def test_clean_dataset_high_score(self):
        data = _csv("id,value,note\n1,a,x\n2,b,y\n3,c,z\n")
        res = validate_dataset(data, "x.csv", SPEC)
        stats = res.validation_report["stats"]
        assert stats["conformance_rate"] == 1.0
        assert stats["duplicate_density"] == 0.0
        assert stats["null_rate"] == 0.0
        assert res.quality_score == 1.0

    def test_duplicates_and_rejects_lower_score(self):
        # 1 bad row (missing required value), 1 within-submission duplicate id
        data = _csv("id,value,note\n1,a,x\n1,a,x\n2,,y\n3,c,\n")
        res = validate_dataset(data, "x.csv", SPEC)
        stats = res.validation_report["stats"]
        assert stats["duplicate_density"] > 0       # the repeated id=1
        assert stats["conformance_rate"] < 1.0       # the empty required value
        assert 0.0 <= res.quality_score < 1.0

    def test_null_rate_reflects_optional_gaps(self):
        # all rows valid, but optional 'note' empty in 2 of 2 rows
        data = _csv("id,value,note\n1,a,\n2,b,\n")
        res = validate_dataset(data, "x.csv", SPEC)
        assert res.validation_report["stats"]["null_rate"] == 1.0
