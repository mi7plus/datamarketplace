# tests/test_deploy_config.py
# Phase 2 (AWS): health endpoint for the ALB + storage backend selection.

from fastapi.testclient import TestClient
from app.main import app
import app.storage as storage
from app.storage import LocalStorage, MinioStorage

client = TestClient(app)


def test_health_is_shallow_and_ok():
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


class TestStorageSelection:
    def setup_method(self):
        storage._backend = None

    def teardown_method(self):
        storage._backend = None

    def test_default_is_local(self, monkeypatch):
        for k in ("S3_ENDPOINT_URL", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "USE_S3"):
            monkeypatch.delenv(k, raising=False)
        assert isinstance(storage.get_storage(), LocalStorage)

    def test_use_s3_selects_real_s3_no_bucket_management(self, monkeypatch):
        # Real AWS S3: no endpoint, no static keys (task role), don't manage the bucket.
        monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.setenv("USE_S3", "true")
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        monkeypatch.setenv("S3_BUCKET", "rowbound-data")
        s = storage.get_storage()
        assert isinstance(s, MinioStorage)
        assert s._manage_bucket is False          # Terraform owns the bucket
        assert s._bucket == "rowbound-data"
        # SigV4 + region are configured for correct presigning
        assert s._client.meta.config.signature_version == "s3v4"
        assert s._client.meta.region_name == "eu-west-1"
