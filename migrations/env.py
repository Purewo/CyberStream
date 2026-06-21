from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from backend.app import create_app
from backend.app.extensions import db
import backend.app.models  # noqa: F401 - registers models for metadata


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

app = create_app({"DATABASE_AUTO_CREATE_SCHEMA": False})
target_metadata = db.metadata


def get_url():
    return app.config["SQLALCHEMY_DATABASE_URI"]


def run_migrations_offline():
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with app.app_context():
        connectable = db.engine
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
