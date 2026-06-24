"""E3: add download_count to submissions (enforce download_limit)

Revision ID: b1f4e7a9c2d0
Revises: c1a2b3d4e5f6
Create Date: 2026-06-23

Adds a per-submission counter of issued download grants so the existing
download_limit column can actually be enforced (E3, presigned-URL hardening).

NOTE: down_revision was re-pointed from 73604f2fa775 to c1a2b3d4e5f6 to LINEARIZE a
branched migration graph. Two duplicate submission_key_staging migrations had forked
at 73604f2fa775 (c1a2b3d4e5f6 with id/ordinal/FK — applied & matching the code — and
c7d2a1f80e34 with a thinner schema — never applied). The duplicate c7d2a1f80e34 was
deleted and this migration now chains after the canonical staging migration, giving a
single head.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1f4e7a9c2d0'
down_revision: Union[str, Sequence[str], None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("submissions", "download_count")
