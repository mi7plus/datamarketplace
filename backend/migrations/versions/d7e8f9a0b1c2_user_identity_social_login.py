"""user_identity + nullable password_hash (social login Phase 2)

Revision ID: d7e8f9a0b1c2
Revises: b1f4e7a9c2d0
Create Date: 2026-07-02

Adds the linked-identities table and makes password_hash nullable so a social-only
account (Google/Microsoft) can exist without a password.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, Sequence[str], None] = 'b1f4e7a9c2d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_identity',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('provider_subject', sa.String(), nullable=False),
        sa.Column('email_at_link', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user_auth.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_subject', name='uq_identity_provider_subject'),
    )
    op.create_index('idx_identity_user', 'user_identity', ['user_id'], unique=False)

    op.alter_column('user_auth', 'password_hash', existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    op.alter_column('user_auth', 'password_hash', existing_type=sa.String(), nullable=False)
    op.drop_index('idx_identity_user', table_name='user_identity')
    op.drop_table('user_identity')
