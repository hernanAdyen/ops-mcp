"""node.embedding takes any dimension

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # The embedding model is a setting (text-embedding-3-small now, qwen3-embedding-8b later), and
    # each model has its own size. The column takes any size; every node records which model made
    # its embedding, and a search only compares nodes made by the query's model. Searched exactly
    # (no index), which pgvector allows for a column without a fixed size.
    op.alter_column('node', 'embedding',
                    existing_type=pgvector.sqlalchemy.vector.VECTOR(dim=4096),
                    type_=pgvector.sqlalchemy.vector.VECTOR(),
                    postgresql_using='embedding::vector')


def downgrade() -> None:
    """Downgrade schema."""
    # Embeddings of another size can't go back into a vector(4096) column: they are cleared.
    op.execute(sa.text(
        "UPDATE node SET embedding = NULL, embedding_model = NULL, embedded_at = NULL "
        "WHERE embedding IS NOT NULL AND vector_dims(embedding) <> 4096"
    ))
    op.alter_column('node', 'embedding',
                    existing_type=pgvector.sqlalchemy.vector.VECTOR(),
                    type_=pgvector.sqlalchemy.vector.VECTOR(dim=4096),
                    postgresql_using='embedding::vector(4096)')
