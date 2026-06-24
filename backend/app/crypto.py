# app/crypto.py
#
# Application-level envelope encryption for sensitive datasets (E5).
#
# The governing constraint (see rowbound-encryption-key-management.md): this is
# NOT zero-knowledge encryption. The processing/app roles deliberately retain
# kms:Decrypt so the ingest/dedup/media service can read plaintext in memory to
# do its job. The point of envelope encryption is narrower: a leaked S3 object or
# an over-broad bucket policy alone yields ciphertext, not data — decryption
# additionally requires KMS access scoped to named roles.
#
# Envelope scheme (matches the E5 acceptance criteria):
#   1. KMS GenerateDataKey -> (plaintext data key, KMS-wrapped data key).
#   2. AES-256-GCM encrypt the payload with the plaintext data key.
#   3. Store the wrapped data key + nonce ALONGSIDE the object; discard plaintext.
#   4. On read, KMS Decrypt unwraps the data key; decrypt in memory.
#
# Providers mirror the payments.py pattern: KmsKeyProvider for real AWS, and a
# LocalKeyProvider dev fallback (clearly NOT for production data — see warning).

import os
from abc import ABC, abstractmethod

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# A short header stamped on every envelope blob so read paths can detect format
# and version without guessing. v1 layout (all length-prefixed, big-endian u32):
#   MAGIC(4) | VERSION(1) | len(wrapped_key) | wrapped_key | nonce(12) | ciphertext
MAGIC = b"RBE1"
NONCE_LEN = 12


class DataKey:
    """A freshly generated data key: plaintext (for immediate use, then dropped)
    and the KMS-wrapped form (persisted alongside the ciphertext)."""

    __slots__ = ("plaintext", "wrapped")

    def __init__(self, plaintext: bytes, wrapped: bytes):
        self.plaintext = plaintext
        self.wrapped = wrapped


class KeyProvider(ABC):
    @abstractmethod
    def generate_data_key(self) -> DataKey:
        """Return a new 256-bit data key in both plaintext and wrapped form."""

    @abstractmethod
    def unwrap(self, wrapped: bytes) -> bytes:
        """Recover the plaintext data key from its wrapped form (KMS Decrypt)."""


# ---------------------------------------------------------------------------
# AWS KMS provider (production)
# ---------------------------------------------------------------------------

class KmsKeyProvider(KeyProvider):
    def __init__(self, key_id: str):
        import boto3  # imported lazily so dev/CI without AWS need not load it

        self._key_id = key_id
        self._kms = boto3.client("kms")

    def generate_data_key(self) -> DataKey:
        resp = self._kms.generate_data_key(KeyId=self._key_id, KeySpec="AES_256")
        return DataKey(plaintext=resp["Plaintext"], wrapped=resp["CiphertextBlob"])

    def unwrap(self, wrapped: bytes) -> bytes:
        # KMS infers the CMK from the ciphertext blob; KeyId is advisory.
        resp = self._kms.decrypt(CiphertextBlob=wrapped, KeyId=self._key_id)
        return resp["Plaintext"]


# ---------------------------------------------------------------------------
# Local dev provider (NOT for production data)
# ---------------------------------------------------------------------------

class LocalKeyProvider(KeyProvider):
    """Dev/CI fallback that 'wraps' data keys with a static local master key
    derived from ENVELOPE_LOCAL_MASTER_KEY (or an ephemeral per-process key).

    WARNING: the master key lives in the app process, so this gives you the
    envelope *mechanics* for testing — it is NOT the security property of real
    KMS (no per-access audit, no revocation, no HSM custody). Never run real
    personal/production data through this provider. Same posture as
    FakePaymentProvider: end-to-end-functional, deliberately not real.
    """

    def __init__(self, master_key: bytes | None = None):
        if master_key is None:
            seed = os.getenv("ENVELOPE_LOCAL_MASTER_KEY")
            master_key = (
                _derive_key(seed.encode()) if seed else AESGCM.generate_key(bit_length=256)
            )
        self._master = master_key

    def generate_data_key(self) -> DataKey:
        plaintext = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(NONCE_LEN)
        wrapped = nonce + AESGCM(self._master).encrypt(nonce, plaintext, b"rbe-dek")
        return DataKey(plaintext=plaintext, wrapped=wrapped)

    def unwrap(self, wrapped: bytes) -> bytes:
        nonce, ct = wrapped[:NONCE_LEN], wrapped[NONCE_LEN:]
        return AESGCM(self._master).decrypt(nonce, ct, b"rbe-dek")


def _derive_key(material: bytes) -> bytes:
    """Stretch arbitrary seed material to a stable 32-byte key (dev only)."""
    import hashlib

    return hashlib.sha256(material).digest()


# ---------------------------------------------------------------------------
# Envelope encode / decode
# ---------------------------------------------------------------------------

def encrypt(provider: KeyProvider, plaintext: bytes, aad: bytes = b"") -> bytes:
    """Envelope-encrypt `plaintext`. Returns a self-describing blob (see MAGIC)."""
    key = provider.generate_data_key()
    try:
        nonce = os.urandom(NONCE_LEN)
        ciphertext = AESGCM(key.plaintext).encrypt(nonce, plaintext, aad)
    finally:
        # Drop the plaintext data key reference as soon as we're done (E4 spirit).
        key.plaintext = b""
    wrapped = key.wrapped
    return (
        MAGIC
        + b"\x01"
        + len(wrapped).to_bytes(4, "big")
        + wrapped
        + nonce
        + ciphertext
    )


def decrypt(provider: KeyProvider, blob: bytes, aad: bytes = b"") -> bytes:
    """Reverse of `encrypt`. Unwraps the data key via the provider, then decrypts."""
    if not is_encrypted(blob):
        raise ValueError("not an envelope blob")
    pos = len(MAGIC) + 1  # skip MAGIC + version
    klen = int.from_bytes(blob[pos:pos + 4], "big")
    pos += 4
    wrapped = blob[pos:pos + klen]
    pos += klen
    nonce = blob[pos:pos + NONCE_LEN]
    pos += NONCE_LEN
    ciphertext = blob[pos:]
    data_key = provider.unwrap(wrapped)
    return AESGCM(data_key).decrypt(nonce, ciphertext, aad)


def is_encrypted(blob: bytes) -> bool:
    """True if `blob` carries the envelope header (cheap format sniff for read paths)."""
    return blob[:len(MAGIC)] == MAGIC


# ---------------------------------------------------------------------------
# Singleton factory — mirrors get_payment_provider() / get_storage()
# ---------------------------------------------------------------------------

_provider: KeyProvider | None = None


def get_key_provider() -> KeyProvider:
    """Return the configured KeyProvider. Uses KMS when ENVELOPE_KMS_KEY_ID is
    set, otherwise the LocalKeyProvider dev fallback."""
    global _provider
    if _provider is None:
        key_id = os.getenv("ENVELOPE_KMS_KEY_ID")
        if key_id:
            _provider = KmsKeyProvider(key_id)
        else:
            _provider = LocalKeyProvider()
    return _provider


def envelope_enabled() -> bool:
    """Whether sensitive datasets should be envelope-encrypted at rest. On by
    default once a KMS key is configured; can be forced on in dev for testing."""
    if os.getenv("ENVELOPE_ENCRYPTION_ENABLED", "").lower() in ("1", "true", "yes"):
        return True
    return bool(os.getenv("ENVELOPE_KMS_KEY_ID"))
