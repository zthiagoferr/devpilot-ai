"""Create the analyses table.

Revision ID: 0001_create_analyses
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0001_create_analyses"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the analyses table and its indexes."""
    op.create_table(
        "analyses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "task_type",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_analyses_repository_id",
        "analyses",
        ["repository_id"],
    )
    op.create_index(
        "ix_analyses_status",
        "analyses",
        ["status"],
    )
    op.create_index(
        "ix_analyses_repository_id_status",
        "analyses",
        ["repository_id", "status"],
    )


def downgrade() -> None:
    """Remove the analyses table and all indexes created for it."""
    op.drop_index(
        "ix_analyses_repository_id_status",
        table_name="analyses",
    )
    op.drop_index(
        "ix_analyses_status",
        table_name="analyses",
    )
    op.drop_index(
        "ix_analyses_repository_id",
        table_name="analyses",
    )
    op.drop_table("analyses")
