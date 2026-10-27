"""project tracks on the opportunity

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-26 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # The project tracks a scope was split into (one tab each in the scope sheet), with each track's tags.
    op.add_column('opportunity', sa.Column('tracks', postgresql.JSONB(astext_type=sa.Text()),
                                           server_default=sa.text("'[]'::jsonb"), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('opportunity', 'tracks')
