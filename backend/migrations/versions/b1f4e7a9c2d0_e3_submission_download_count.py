"""E3: add download_count to submissions (enforce download_limit)

Revision ID: b1f4e7a9c2d0
Revises: 73604f2fa775
Create Date: 2026-06-23

Adds a per-submission counter of issued download grants so the existing
download_limit column can actually be enforced (E3, presigned-URL hardening).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1f4e7a9c2d0'
down_revision: Union[str, Sequence[str], None] = '73604f2fa775'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("submissions", "download_count")
