# app/storage.py
#
# Storage abstraction for uploaded datasets.
# Phase 3: stores files on local disk under backend/uploads/.
# Phase 6: swap LocalStorage for MinioStorage behind the same interface
#           without touching call sites.

import os
from pathlib import Path
from abc import ABC, abstractmethod

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


class StorageBackend(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes) -> str:
        """Persist data and return a storage_location string."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...


class LocalStorage(StorageBackend):
    def save(self, key: str, data: bytes) -> str:
        path = UPLOAD_DIR / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def exists(self, key: str) -> bool:
        return (UPLOAD_DIR / key).exists()


# Singleton — swap this out in Phase 6
_backend: StorageBackend = LocalStorage()


def get_storage() -> StorageBackend:
    return _backend
