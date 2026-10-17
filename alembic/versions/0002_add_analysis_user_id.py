"""Add the optional analysis owner (``user_id``).

Revision ID: 0002_add_analysis_user_id
Revises: 0001_create_analyses
Create Date: 2024-01-02 00:00:00.000000

The column is nullable on purpose: analyses created before authentication
existed keep ``NULL`` and are never backfilled, so no record is silently
attributed to a user. The index supports the per-user history query.

The revision uses portable SQLAlchemy types and the standard
``ADD COLUMN``/``DROP COLUMN`` pair, which applies to both PostgreSQL and the
local SQLite development database.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_add_analysis_user_id"
down_revision = "0001_create_analyses"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_analyses_user_id"


def upgrade() -> None:
    """Add the nullable owner column and its index."""
    op.add_column(
        "analyses",
        sa.Column(
            "user_id",
            sa.String(length=128),
            nullable=True,
        ),
    )
    op.create_index(
        _INDEX_NAME,
        "analyses",
        ["user_id"],
    )


def downgrade() -> None:
    """Remove the owner index and column, restoring the 0001 schema."""
    op.drop_index(
        _INDEX_NAME,
        table_name="analyses",
    )
    op.drop_column("analyses", "user_id")
