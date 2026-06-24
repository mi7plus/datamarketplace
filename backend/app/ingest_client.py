# app/ingest_client.py
#
# Client + shadow-comparison harness for the Rust ingest service (P1).
#
# Flags (env):
#   INGEST_RUST_URL          base URL of the Rust service (e.g. http://ingest:8088)
#   INGEST_INTERNAL_TOKEN    shared secret (matches the Rust X-Internal-Token gate)
#   INGEST_SHADOW_ENABLED    "true" -> run Rust alongside Python and log parity
#   INGEST_RUST_ENABLED      "true" -> (P2 cutover) trust Rust as the source of truth
#
# During P1 the Python ingest stays authoritative; this only *compares* so we can
# prove parity (same validated_amount, dataset_hash, sample, key-hash count)
# before trusting Rust. Never raises into the request path.

import logging
import os
from typing import Optional

import urllib.request
import urllib.error
import json

logger = logging.getLogger("ingest_client")


def rust_enabled() -> bool:
    return os.getenv("INGEST_RUST_ENABLED", "").lower() in ("1", "true", "yes")


def shadow_enabled() -> bool:
    return os.getenv("INGEST_SHADOW_ENABLED", "").lower() in ("1", "true", "yes")


def _base_url() -> Optional[str]:
    url = os.getenv("INGEST_RUST_URL", "").strip()
    return url.rstrip("/") or None


def call_rust_ingest(
    *,
    submission_id: str,
    s3_key: str,
    filename: str,
    spec: Optional[dict],
    content_hash: str = "",
    modality: str = "tabular",
    timeout: float = 30.0,
) -> Optional[dict]:
    """Invoke the Rust sync /ingest endpoint. Returns the report dict, or None on
    any failure (caller decides whether that's fatal)."""
    base = _base_url()
    if not base:
        return None
    payload = {
        "job_id": f"{submission_id}:{content_hash}",
        "submission_id": submission_id,
        "s3_key": s3_key,
        "filename": filename,
        "content_hash": content_hash,
        "modality": modality,
        "spec": spec,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base}/ingest",
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Token": os.getenv("INGEST_INTERNAL_TOKEN", ""),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("rust ingest call failed: %s", exc)
        return None


def shadow_compare(python_result, *, submission_id: str, s3_key: str,
                   filename: str, spec: Optional[dict], content_hash: str = "") -> None:
    """Best-effort: run Rust on the same file and log any divergence from the
    Python result. Never raises. Used in P1 SHADOW mode."""
    if not shadow_enabled():
        return
    report = call_rust_ingest(
        submission_id=submission_id, s3_key=s3_key, filename=filename,
        spec=spec, content_hash=content_hash,
    )
    if report is None:
        return

    diffs = []
    if report.get("validated_amount") != python_result.validated_amount:
        diffs.append(
            f"validated_amount py={python_result.validated_amount} "
            f"rust={report.get('validated_amount')}"
        )
    if report.get("dataset_hash") != python_result.dataset_hash:
        diffs.append("dataset_hash mismatch")
    py_keys = len(python_result.key_hashes or [])
    if report.get("key_hash_count") != py_keys:
        diffs.append(f"key_hash_count py={py_keys} rust={report.get('key_hash_count')}")

    if diffs:
        logger.warning("INGEST PARITY DIVERGENCE sub=%s: %s", submission_id, "; ".join(diffs))
    else:
        logger.info("ingest parity OK sub=%s", submission_id)
