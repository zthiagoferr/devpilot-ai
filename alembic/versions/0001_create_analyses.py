"""Create the analyses table.

Revision ID: 0001_create_analyses
Revises:
Create Date: 2024-01-01 00:00:00.000000

The column types are database-neutral so the migration applies identically to
PostgreSQL (production) and SQLite (development / tests).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_create_analyses"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the analyses table and its indexes."""
    op.create_table(
        "analyses",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("task", sa.String(length=100), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("source_code", sa.Text(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'completed'"),
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

    op.create_index("ix_analyses_task", "analyses", ["task"])
    op.create_index("ix_analyses_project_name", "analyses", ["project_name"])
    op.create_index("ix_analyses_status", "analyses", ["status"])


def downgrade() -> None:
    """Remove the analyses table and its indexes."""
    op.drop_index("ix_analyses_status", table_name="analyses")
    op.drop_index("ix_analyses_project_name", table_name="analyses")
    op.drop_index("ix_analyses_task", table_name="analyses")
    op.drop_table("analyses")
