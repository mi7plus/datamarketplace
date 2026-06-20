# tests/test_download_disposition.py
# S2: downloads are served as attachments (never rendered inline), with a
# sanitized filename.

from unittest.mock import MagicMock
from app.storage import LocalStorage, MinioStorage, _safe_filename


class TestSafeFilename:
    def test_strips_path_and_control_chars(self):
        assert _safe_filename("../../etc/passwd") == "passwd"
        assert _safe_filename('a"b\nc.csv') == "a_b_c.csv"
        assert _safe_filename(None) == "dataset"
        assert _safe_filename("") == "dataset"


class TestMinioAttachment:
    def _storage(self):
        s = MinioStorage.__new__(MinioStorage)   # bypass __init__ (no real bucket)
        s._bucket = "b"
        s._client = MagicMock()
        s._client.generate_presigned_url.return_value = "https://minio/signed"
        return s

    def test_presigned_url_forces_attachment(self):
        s = self._storage()
        s.presigned_url("req/prov/data.csv", filename="data.csv")
        _, kwargs = s._client.generate_presigned_url.call_args
        params = kwargs["Params"]
        assert params["ResponseContentDisposition"].startswith('attachment; filename="data.csv"')
        assert params["ResponseContentType"] == "application/octet-stream"

    def test_filename_is_sanitized_in_header(self):
        s = self._storage()
        s.presigned_url("k", filename='../evil"\n.csv')
        params = s._client.generate_presigned_url.call_args[1]["Params"]
        cd = params["ResponseContentDisposition"]
        assert "\n" not in cd and '"evil' not in cd.replace('filename="', "")
        assert ".." not in cd


class TestLocalAttachment:
    def test_local_url_carries_download_name(self):
        url = LocalStorage().presigned_url("req/prov/data.csv", filename="data.csv")
        assert "download=data.csv" in url
