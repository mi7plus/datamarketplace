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

import boto3
from botocore.exceptions import ClientError


def _safe_filename(name: str | None) -> str:
    """Sanitize a filename for a Content-Disposition header (no quotes, control
    chars, or path separators)."""
    base = os.path.basename(name or "dataset")
    base = re.sub(r'[\r\n"\\/]', "_", base).strip()
    return base or "dataset"

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# How long a pre-signed download URL stays valid (Phase 6 default)
PRESIGNED_URL_TTL_SECONDS = int(os.getenv("PRESIGNED_URL_TTL_SECONDS", "3600"))


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class StorageBackend(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes) -> str:
        """Persist data; return a storage_location string (used to generate URLs later)."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def read(self, key: str) -> bytes:
        """Read raw bytes back (used to slice a purchased portion of a listing)."""

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
    def save(self, key: str, data: bytes) -> str:
        path = UPLOAD_DIR / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key  # store the relative key, not the absolute path

    def exists(self, key: str) -> bool:
        return (UPLOAD_DIR / key).exists()

    def read(self, key: str) -> bytes:
        return (UPLOAD_DIR / key).read_bytes()

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

    def save(self, key: str, data: bytes) -> str:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType="application/octet-stream",
        )
        return key  # store just the key; generate URLs on demand

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False

    def read(self, key: str) -> bytes:
        obj = self._client.get_object(Bucket=self._bucket, Key=key)
        return obj["Body"].read()

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
            ExpiresIn=ttl_seconds,
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
