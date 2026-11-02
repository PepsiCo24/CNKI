"""capture sessions

Revision ID: b1c2d3e4f5a6
Revises: de955d910552
Create Date: 2026-11-02 15:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "de955d910552"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "capture_sessions",
        sa.Column("task_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("import_job_id", sa.String(length=32), nullable=True),
        sa.Column("background_job_id", sa.String(length=32), nullable=True),
        sa.Column("wait_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["search_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("capture_sessions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_capture_sessions_background_job_id"), ["background_job_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_capture_sessions_import_job_id"), ["import_job_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_capture_sessions_stage"), ["stage"], unique=False)
        batch_op.create_index(batch_op.f("ix_capture_sessions_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_capture_sessions_task_id"), ["task_id"], unique=False)
        batch_op.create_index("ix_capture_task_status", ["task_id", "status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("capture_sessions", schema=None) as batch_op:
        batch_op.drop_index("ix_capture_task_status")
        batch_op.drop_index(batch_op.f("ix_capture_sessions_task_id"))
        batch_op.drop_index(batch_op.f("ix_capture_sessions_status"))
        batch_op.drop_index(batch_op.f("ix_capture_sessions_stage"))
        batch_op.drop_index(batch_op.f("ix_capture_sessions_import_job_id"))
        batch_op.drop_index(batch_op.f("ix_capture_sessions_background_job_id"))

    op.drop_table("capture_sessions")
