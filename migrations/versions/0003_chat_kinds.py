"""more kinds of merchant material: email and document

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25 03:00:00

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # /source-scope-answers takes whatever the IM has. Only the kind is kept, never the material.
    op.execute("ALTER TYPE chat_kind ADD VALUE IF NOT EXISTS 'email'")
    op.execute("ALTER TYPE chat_kind ADD VALUE IF NOT EXISTS 'document'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres can't remove a value from an enum type. The extra values are harmless, and
    # downgrading past 0001 drops the type altogether.
