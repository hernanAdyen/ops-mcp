"""question baseline and purpose

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-27 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A baseline question belongs in every scope, whatever the IM's tags (within their priorities
    # and subsections). The bank's `baseline` column (Y/N).
    op.add_column('question', sa.Column('baseline', sa.Boolean(), server_default=sa.false(), nullable=False))
    # What the answer accomplishes, in one line: shown to our model when it looks for answers.
    # The bank's `purpose` column.
    op.add_column('question', sa.Column('purpose', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('question', 'purpose')
    op.drop_column('question', 'baseline')
