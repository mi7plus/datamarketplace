# tests/test_cutover_gate.py
# C1 (Rust cutover gate): unique_key columns must be parity-safe (string|integer).
# float/boolean/date/datetime stringify differently in Python vs Rust → would
# diverge from existing AcceptedKey rows at cutover → double-pay. Block at spec
# validation for requests, the collect form spec, AND listing creation.

import io
import csv
import json
import uuid

import pytest
from pydantic import ValidationError

from app.schemas import RequestSpec, CollectionSpec

UNSAFE = ["float", "boolean", "date", "datetime"]
SAFE = ["string", "integer"]


def _req_spec(key_type):
    return {
        "columns": [
            {"name": "k", "type": key_type, "required": True},
            {"name": "v", "type": "string", "required": True},
        ],
        "unique_key": ["k"],
    }


@pytest.mark.parametrize("t", UNSAFE)
def test_request_spec_rejects_unsafe_unique_key(t):
    with pytest.raises(ValidationError, match="string or integer"):
        RequestSpec(**_req_spec(t))


@pytest.mark.parametrize("t", SAFE)
def test_request_spec_accepts_safe_unique_key(t):
    spec = RequestSpec(**_req_spec(t))
    assert spec.unique_key == ["k"]


@pytest.mark.parametrize("t", UNSAFE)
def test_collection_spec_rejects_unsafe_unique_key(t):
    bad = {
        "fields": [
            {"name": "k", "type": t, "required": True},
            {"name": "v", "type": "string", "required": True},
        ],
        "unique_key": ["k"],
    }
    with pytest.raises(ValidationError, match="string or integer"):
        CollectionSpec(**bad)


def test_collection_spec_accepts_integer_key():
    ok = {
        "fields": [{"name": "k", "type": "integer", "required": True}],
        "unique_key": ["k"],
    }
    assert CollectionSpec(**ok).unique_key == ["k"]


# --- Listing creation goes through the API (spec was previously unvalidated) ---
from fastapi.testclient import TestClient
from app.main import app
from tests.test_allocation_race import DB_URL

client = TestClient(app)


@pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set")
def test_listing_creation_rejects_unsafe_unique_key():
    suffix = uuid.uuid4().hex[:8]
    client.post("/auth/register", json={"email": f"sup_{suffix}@t.io", "password": "pw123456", "role": "provider"})
    tok = client.post("/auth/login", json={"email": f"sup_{suffix}@t.io", "password": "pw123456"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}"}

    buf = io.StringIO(); w = csv.writer(buf); w.writerow(["k", "v"]); w.writerow(["1.5", "a"])
    spec = {"columns": [{"name": "k", "type": "float", "required": True},
                        {"name": "v", "type": "string", "required": True}],
            "unique_key": ["k"]}
    r = client.post("/listings/", headers=headers,
        files={"file": ("d.csv", buf.getvalue().encode(), "text/csv")},
        data={"title": "x", "price_per_unit": 1.0, "unit": "row",
              "provenance": "p", "spec": json.dumps(spec), "warranted": "true"})
    assert r.status_code == 422, r.text
