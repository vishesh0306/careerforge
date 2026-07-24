"""add source, label, parent_resume_id to resumes

Revision ID: 8e9345df22b0
Revises: 9881d1ec34a8
Create Date: 2026-07-24 17:03:42.364516

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e9345df22b0'
down_revision: Union[str, None] = '9881d1ec34a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable first so existing rows don't violate NOT NULL, backfill them
    # as "uploaded" (the only source that existed before this migration), then
    # tighten the constraint.
    op.add_column('resumes', sa.Column('source', sa.String(length=20), nullable=True))
    op.execute("UPDATE resumes SET source = 'uploaded' WHERE source IS NULL")
    op.alter_column('resumes', 'source', nullable=False)

    op.add_column('resumes', sa.Column('label', sa.String(length=255), nullable=True))
    op.add_column('resumes', sa.Column('parent_resume_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_resumes_parent_resume_id', 'resumes', 'resumes', ['parent_resume_id'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_resumes_parent_resume_id', 'resumes', type_='foreignkey')
    op.drop_column('resumes', 'parent_resume_id')
    op.drop_column('resumes', 'label')
    op.drop_column('resumes', 'source')
