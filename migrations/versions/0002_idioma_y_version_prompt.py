"""Añade idioma y prompt_version a transformaciones_enunciado.

Ambas columnas son opcionales (nullable): las filas antiguas quedan con NULL,
que la aplicación interpreta como 'es'.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLE = "transformaciones_enunciado"


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def upgrade() -> None:
    cols = _columns()
    with op.batch_alter_table(TABLE) as batch:
        if "idioma" not in cols:
            batch.add_column(sa.Column("idioma", sa.String(10), nullable=True))
        if "prompt_version" not in cols:
            batch.add_column(sa.Column("prompt_version", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("prompt_version")
        batch.drop_column("idioma")
