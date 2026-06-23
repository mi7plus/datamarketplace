"""P2: submission_key_staging for Rust ingest dedup anti-join

Revision ID: c7d2a1f80e34
Revises: b1f4e7a9c2d0
Create Date: 2026-06-23

The Rust ingest service bulk-writes normalized per-record key hashes here (via
COPY); Python's allocation step then computes overlap as a SQL anti-join inside
its existing locked transaction:

    creditable = submission_key_staging  EXCEPT  (accepted_keys for this request)

This is a STAGING table only — never money/lifecycle state. The Rust service's DB
grant is scoped to this table (see RUST_INGEST_DEPLOY.md). Python remains the
single writer to the core schema.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c7d2a1f80e34'
down_revision: Union[str, Sequence[str], None] = 'b1f4e7a9c2d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "submission_key_staging",
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
    )
    # Anti-join filters by submission_id then compares key_hash; this index serves
    # both the per-submission delete-then-COPY refresh and the EXCEPT.
    op.create_index(
        "idx_key_staging_submission",
        "submission_key_staging",
        ["submission_id", "key_hash"],
    )


def downgrade() -> None:
    op.drop_index("idx_key_staging_submission", table_name="submission_key_staging")
    op.drop_table("submission_key_staging")
