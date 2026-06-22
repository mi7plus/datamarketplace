"""submission_key_staging (Rust ingest P2 — staging anti-join dedup)

Revision ID: c1a2b3d4e5f6
Revises: 73604f2fa775
Create Date: 2026-06-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '73604f2fa775'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'submission_key_staging',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('submission_id', sa.UUID(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['submission_id'], ['submissions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_submission_key_staging_submission',
        'submission_key_staging',
        ['submission_id'],
    )


def downgrade() -> None:
    op.drop_index('idx_submission_key_staging_submission', table_name='submission_key_staging')
    op.drop_table('submission_key_staging')
