"""create schedule table

迁移 ID: a044fb7fd863
父迁移: 
创建时间: 2024-07-27 11:59:38.831207

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'a044fb7fd863'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ('russian_ban',)
depends_on: str | Sequence[str] | None = None


def upgrade(name: str = "") -> None:
    if name:
        return
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('russian_ban_schedulebanjob',
    sa.Column('job_id', sa.String(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('period', sa.Integer(), nullable=False),
    sa.Column('start_hour', sa.Integer(), nullable=False),
    sa.Column('start_minute', sa.Integer(), nullable=False),
    sa.Column('once', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('job_id', name=op.f('pk_russian_ban_schedulebanjob')),
    info={'bind_key': 'russian_ban'}
    )
    with op.batch_alter_table('russian_ban_schedulebanjob', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_russian_ban_schedulebanjob_group_id'), ['group_id'], unique=False)

    # ### end Alembic commands ###


def downgrade(name: str = "") -> None:
    if name:
        return
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('russian_ban_schedulebanjob', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_russian_ban_schedulebanjob_group_id'))

    op.drop_table('russian_ban_schedulebanjob')
    # ### end Alembic commands ###