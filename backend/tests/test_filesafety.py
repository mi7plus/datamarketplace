# tests/test_filesafety.py
# S2: upload safety — text-vs-binary decided by content, not extension.

import pytest
from fastapi import HTTPException
from app.filesafety import assert_safe_text_upload


def _csv_bytes():
    return b"id,value\n1,a\n2,b\n"


class TestSafeTextUpload:
    def test_plain_csv_passes(self):
        assert_safe_text_upload(_csv_bytes(), "data.csv")  # no raise

    def test_jsonl_passes(self):
        assert_safe_text_upload(b'{"id": 1}\n{"id": 2}\n', "data.jsonl")

    def test_utf8_bom_csv_passes(self):
        assert_safe_text_upload(b"\xef\xbb\xbfid,value\n1,a\n", "data.csv")

    def test_empty_rejected(self):
        with pytest.raises(HTTPException) as e:
            assert_safe_text_upload(b"", "data.csv")
        assert e.value.status_code == 422

    @pytest.mark.parametrize("magic,label", [
        (b"MZ\x90\x00\x03", "exe"),
        (b"PK\x03\x04rest", "zip/xlsx"),
        (b"\x7fELF\x02\x01", "elf"),
        (b"%PDF-1.7", "pdf"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"\xff\xd8\xff\xe0", "jpeg"),
        (b"\x1f\x8b\x08", "gzip"),
        (b"Rar!\x1a\x07", "rar"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "legacy-office"),
    ])
    def test_binary_magic_rejected(self, magic, label):
        # e.g. an .exe renamed data.csv
        with pytest.raises(HTTPException) as e:
            assert_safe_text_upload(magic + b"\x00\x01\x02\x03", f"{label}.csv")
        assert e.value.status_code == 422

    def test_nul_bytes_rejected(self):
        # Binary with no known magic prefix but embedded NULs
        with pytest.raises(HTTPException) as e:
            assert_safe_text_upload(b"id,value\n1,\x00\x00binary\x00\n", "data.csv")
        assert e.value.status_code == 422
