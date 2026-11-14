"""Initial schema (users + three transformation tables).

Idempotent: if the tables already exist (database created by an earlier version
through create_all), it does nothing. This makes it valid both for a new
database and for the existing production one.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _tables()

    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer, primary_key=True, index=True),
            sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
            sa.Column("name", sa.String(255)),
            sa.Column("picture", sa.String(500)),
            sa.Column("google_id", sa.String(255), nullable=False, unique=True, index=True),
            sa.Column("is_admin", sa.Boolean, default=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
        )

    if "transformaciones_enunciado" not in existing:
        op.create_table(
            "transformaciones_enunciado",
            sa.Column("id", sa.Integer, primary_key=True, index=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("enunciado_original", sa.Text, nullable=False),
            sa.Column("nivel", sa.String(50)),
            sa.Column("max_palabras", sa.Integer),
            sa.Column("enunciado_adaptado", sa.Text, nullable=False),
            sa.Column("indicaciones_docentes", sa.Text),
            sa.Column("tokens_entrada", sa.Integer),
            sa.Column("tokens_salida", sa.Integer),
            sa.Column("duracion_ms", sa.Integer),
            sa.Column("exito", sa.Boolean, default=True),
            sa.Column("error_mensaje", sa.Text),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
        )

    if "generacion_pictogramas" not in existing:
        op.create_table(
            "generacion_pictogramas",
            sa.Column("id", sa.Integer, primary_key=True, index=True),
            sa.Column("transformacion_id", sa.Integer, sa.ForeignKey("transformaciones_enunciado.id"),
                      nullable=False, unique=True, index=True),
            sa.Column("enunciado_entrada", sa.Text, nullable=False),
            sa.Column("imagen_pictogramas", sa.LargeBinary),
            sa.Column("imagen_mime_type", sa.String(50), default="image/png"),
            sa.Column("explicacion_habilidades", sa.Text),
            sa.Column("pasos_json", sa.JSON),
            sa.Column("tokens_entrada", sa.Integer),
            sa.Column("tokens_salida", sa.Integer),
            sa.Column("duracion_ms", sa.Integer),
            sa.Column("exito", sa.Boolean, default=True),
            sa.Column("error_mensaje", sa.Text),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
        )

    if "generacion_imagenes" not in existing:
        op.create_table(
            "generacion_imagenes",
            sa.Column("id", sa.Integer, primary_key=True, index=True),
            sa.Column("transformacion_id", sa.Integer, sa.ForeignKey("transformaciones_enunciado.id"),
                      nullable=False, index=True),
            sa.Column("imagen_data", sa.LargeBinary),
            sa.Column("imagen_mime_type", sa.String(50), default="image/png"),
            sa.Column("texto_explicativo", sa.Text),
            sa.Column("orden", sa.Integer, default=1),
            sa.Column("prompt_generacion", sa.Text),
            sa.Column("duracion_ms", sa.Integer),
            sa.Column("exito", sa.Boolean, default=True),
            sa.Column("error_mensaje", sa.Text),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
        )


def downgrade() -> None:
    # Production data is never dropped automatically.
    pass
