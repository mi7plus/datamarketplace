# tests/test_crypto.py
# Envelope-encryption primitives (E5). Uses the LocalKeyProvider so no AWS/KMS is
# needed — the same code path with KmsKeyProvider in prod.

import pytest

from app import crypto


@pytest.fixture
def provider():
    # Deterministic master key so wrap/unwrap is stable within the test.
    return crypto.LocalKeyProvider(master_key=b"\x01" * 32)


class TestEnvelopeRoundTrip:
    def test_encrypt_then_decrypt(self, provider):
        pt = b"the quick brown fox" * 100
        blob = crypto.encrypt(provider, pt)
        assert crypto.is_encrypted(blob)
        assert blob != pt
        assert crypto.decrypt(provider, blob) == pt

    def test_ciphertext_hides_plaintext(self, provider):
        pt = b"national-id=123-45-6789"
        blob = crypto.encrypt(provider, pt)
        assert b"123-45-6789" not in blob

    def test_aad_must_match(self, provider):
        blob = crypto.encrypt(provider, b"payload", aad=b"key-A")
        # Wrong AAD (e.g. object moved to a different key) fails authentication.
        with pytest.raises(Exception):
            crypto.decrypt(provider, blob, aad=b"key-B")

    def test_data_key_is_per_object(self, provider):
        # Two encryptions of the same plaintext produce different wrapped keys +
        # nonces, hence different ciphertext (no deterministic leakage).
        a = crypto.encrypt(provider, b"same")
        b = crypto.encrypt(provider, b"same")
        assert a != b

    def test_wrong_master_key_cannot_unwrap(self):
        p1 = crypto.LocalKeyProvider(master_key=b"\x01" * 32)
        p2 = crypto.LocalKeyProvider(master_key=b"\x02" * 32)
        blob = crypto.encrypt(p1, b"secret")
        # A raw object copy without the right key material is undecryptable (E5).
        with pytest.raises(Exception):
            crypto.decrypt(p2, blob)


class TestIsEncrypted:
    def test_plain_bytes_not_detected(self):
        assert crypto.is_encrypted(b"a,b,c\n1,2,3\n") is False

    def test_empty_bytes_safe(self):
        assert crypto.is_encrypted(b"") is False


class TestEnvelopeEnabled:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("ENVELOPE_ENCRYPTION_ENABLED", raising=False)
        monkeypatch.delenv("ENVELOPE_KMS_KEY_ID", raising=False)
        assert crypto.envelope_enabled() is False

    def test_enabled_by_flag(self, monkeypatch):
        monkeypatch.setenv("ENVELOPE_ENCRYPTION_ENABLED", "true")
        assert crypto.envelope_enabled() is True

    def test_enabled_by_kms_key(self, monkeypatch):
        monkeypatch.delenv("ENVELOPE_ENCRYPTION_ENABLED", raising=False)
        monkeypatch.setenv("ENVELOPE_KMS_KEY_ID", "arn:aws:kms:...:key/abc")
        assert crypto.envelope_enabled() is True
