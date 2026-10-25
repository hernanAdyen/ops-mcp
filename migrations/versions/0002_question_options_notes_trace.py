"""question options and notes, generation trace

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24 23:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Allowed answers for choice questions, in display order ("A | B | C" in the sheet).
    op.add_column('question', sa.Column('options', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False))
    # Guidance for the IM that used to sit inside the question text.
    op.add_column('question', sa.Column('notes', sa.Text(), nullable=True))
    # Only choice questions have options, and they always do.
    op.create_check_constraint(
        op.f('ck_question_options_match_type'),
        'question',
        "(type IN ('single_choice', 'multi_choice')) = (cardinality(options) > 0)",
    )
    # What a command run was asked and what it chose (never the IM's free text).
    op.add_column('generation', sa.Column('trace', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('generation', 'trace')
    op.drop_constraint(op.f('ck_question_options_match_type'), 'question', type_='check')
    op.drop_column('question', 'notes')
    op.drop_column('question', 'options')
