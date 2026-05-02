"""add profile_picture to users

Revision ID: ae4138cabbde
Revises: 335ae7f63251
Create Date: 2026-05-02 13:28:17.801769

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ae4138cabbde'
down_revision: Union[str, Sequence[str], None] = '335ae7f63251'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('profile_picture', sa.String(500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'profile_picture')
