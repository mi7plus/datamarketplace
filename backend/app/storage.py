# app/storage.py
#
# Storage abstraction for uploaded datasets.
# LocalStorage: files on disk (dev / no-MinIO fallback).
# MinioStorage: private S3-compatible bucket with pre-signed URL generation.
#
# Call sites always use get_storage() — never import a concrete class directly.
# To activate MinIO set S3_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
# S3_BUCKET in the environment; LocalStorage is the default.

import os
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import boto3
from botocore.exceptions import ClientError

from app import crypto


def _safe_filename(name: str | None) -> str:
    """Sanitize a filename for a Content-Disposition header (no quotes, control
    chars, or path separators)."""
    base = os.path.basename(name or "dataset")
    base = re.sub(r'[\r\n"\\/]', "_", base).strip()
    return base or "dataset"

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# How long a pre-signed download URL stays valid. The presigned URL *is* the
# access/decrypt grant (E3), so it must be short — minutes, not hours. Default
# 300s (5 min); was 3600s in Phase 6. Override with PRESIGNED_URL_TTL_SECONDS but
# the value is clamped to PRESIGNED_URL_TTL_MAX so a misconfig can't hand out a
# long-lived grant.
PRESIGNED_URL_TTL_SECONDS = int(os.getenv("PRESIGNED_URL_TTL_SECONDS", "300"))
PRESIGNED_URL_TTL_MAX = int(os.getenv("PRESIGNED_URL_TTL_MAX", "900"))  # 15 min ceiling


def _clamp_ttl(ttl_seconds: int) -> int:
    return max(1, min(int(ttl_seconds), PRESIGNED_URL_TTL_MAX))


# Server-side encryption for S3 puts (E2). When S3_SSE_KMS_KEY_ID is set, objects
# are written under a customer-managed KMS key (aws:kms) instead of SSE-S3/none.
# bucket_key_enabled cuts KMS request cost. MinIO ignores these params, so dev is
# unaffected. This is the bucket-default SSE; envelope encryption (E5) is layered
# on top for `sensitive` datasets.
S3_SSE_KMS_KEY_ID = os.getenv("S3_SSE_KMS_KEY_ID", "")


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class StorageBackend(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes, encrypt: bool = False) -> str:
        """Persist data; return a storage_location string (used to generate URLs
        later). When encrypt=True (and envelope encryption is enabled), the bytes
        are envelope-encrypted (E5) before they touch storage, so a leaked object
        is ciphertext. Transparent to callers: read() reverses it."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def read(self, key: str) -> bytes:
        """Read raw bytes back, transparently decrypting an envelope-encrypted
        object (E5). Used by server-side processing (ingest/dedup/media) and to
        slice a purchased portion of a listing — they always see plaintext."""

    def is_encrypted_at_rest(self, key: str) -> bool:
        """True if the stored object is envelope-encrypted (E5). Delivery paths
        use this to decrypt-and-stream instead of handing out a ciphertext URL."""
        return False

    @abstractmethod
    def presigned_url(
        self,
        key: str,
        ttl_seconds: int = PRESIGNED_URL_TTL_SECONDS,
        filename: str | None = None,
    ) -> str:
        """Return a time-limited URL for direct download, forcing attachment download
        (never inline render). Gate on submission status before calling."""


# ---------------------------------------------------------------------------
# Local storage (dev / fallback)
# ---------------------------------------------------------------------------

class LocalStorage(StorageBackend):
    def save(self, key: str, data: bytes, encrypt: bool = False) -> str:
        if encrypt and crypto.envelope_enabled():
            data = crypto.encrypt(crypto.get_key_provider(), data, aad=key.encode())
        path = UPLOAD_DIR / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key  # store the relative key, not the absolute path

    def exists(self, key: str) -> bool:
        return (UPLOAD_DIR / key).exists()

    def read(self, key: str) -> bytes:
        raw = (UPLOAD_DIR / key).read_bytes()
        if crypto.is_encrypted(raw):
            return crypto.decrypt(crypto.get_key_provider(), raw, aad=key.encode())
        return raw

    def is_encrypted_at_rest(self, key: str) -> bool:
        path = UPLOAD_DIR / key
        if not path.exists():
            return False
        with path.open("rb") as fh:
            return crypto.is_encrypted(fh.read(len(crypto.MAGIC)))

    def presigned_url(
        self,
        key: str,
        ttl_seconds: int = PRESIGNED_URL_TTL_SECONDS,
        filename: str | None = None,
    ) -> str:
        # Dev mode: return a local file URL — not truly gated, but functional for testing.
        # In production this path is never reached (MinIO replaces LocalStorage).
        fn = _safe_filename(filename or os.path.basename(key))
        return f"/dev/storage/{key}?download={fn}"


# ---------------------------------------------------------------------------
# MinIO / S3 storage
# ---------------------------------------------------------------------------

class MinioStorage(StorageBackend):
    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket: str):
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)
            # Block all public access — objects are private by default in MinIO
            self._client.put_public_access_block(
                Bucket=self._bucket,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                },
            )

    def save(self, key: str, data: bytes, encrypt: bool = False) -> str:
        if encrypt and crypto.envelope_enabled():
            data = crypto.encrypt(crypto.get_key_provider(), data, aad=key.encode())
        put_kwargs = dict(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType="application/octet-stream",
        )
        # Bucket-default SSE-KMS (E2). Belt-and-braces alongside the bucket policy:
        # naming the key on the put guarantees the object lands under the CMK even
        # if the default config drifts. Skipped for MinIO (no KMS).
        if S3_SSE_KMS_KEY_ID:
            put_kwargs["ServerSideEncryption"] = "aws:kms"
            put_kwargs["SSEKMSKeyId"] = S3_SSE_KMS_KEY_ID
            put_kwargs["BucketKeyEnabled"] = True
        self._client.put_object(**put_kwargs)
        return key  # store just the key; generate URLs on demand

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False

    def read(self, key: str) -> bytes:
        obj = self._client.get_object(Bucket=self._bucket, Key=key)
        raw = obj["Body"].read()
        if crypto.is_encrypted(raw):
            return crypto.decrypt(crypto.get_key_provider(), raw, aad=key.encode())
        return raw

    def is_encrypted_at_rest(self, key: str) -> bool:
        try:
            # Range-read just the header bytes rather than pulling the whole object.
            obj = self._client.get_object(
                Bucket=self._bucket, Key=key, Range=f"bytes=0-{len(crypto.MAGIC) - 1}"
            )
            return crypto.is_encrypted(obj["Body"].read())
        except ClientError:
            return False

    def presigned_url(
        self,
        key: str,
        ttl_seconds: int = PRESIGNED_URL_TTL_SECONDS,
        filename: str | None = None,
    ) -> str:
        fn = _safe_filename(filename or os.path.basename(key))
        url = self._client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                # Force a download with a safe type so the browser never renders
                # uploaded data inline (S2). Overrides any stored object headers.
                "ResponseContentDisposition": f'attachment; filename="{fn}"',
                "ResponseContentType": "application/octet-stream",
            },
            ExpiresIn=_clamp_ttl(ttl_seconds),  # E3: minutes, not hours
        )
        # E3: the presigned URL is the access grant — it must be HTTPS so the
        # object (and the grant itself) never crosses the wire in plaintext.
        # Real S3/ALB is https; only a misconfigured http endpoint trips this.
        # PRESIGNED_ALLOW_HTTP=true is the dev escape hatch for local MinIO.
        if urlsplit(url).scheme != "https" and \
                os.getenv("PRESIGNED_ALLOW_HTTP", "").lower() not in ("1", "true", "yes"):
            raise RuntimeError(
                "Refusing to issue a non-HTTPS presigned URL (E3). Set "
                "PRESIGNED_ALLOW_HTTP=true for local/dev MinIO over http."
            )
        return url


# ---------------------------------------------------------------------------
# Singleton factory — reads env vars once at startup
# ---------------------------------------------------------------------------

_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _backend
    if _backend is None:
        endpoint = os.getenv("S3_ENDPOINT_URL", "")
        access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
        bucket = os.getenv("S3_BUCKET", "datamarketplace")
        if endpoint and access_key and secret_key:
            _backend = MinioStorage(endpoint, access_key, secret_key, bucket)
        else:
            _backend = LocalStorage()
    return _backend
