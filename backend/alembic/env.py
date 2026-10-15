from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

import models  # noqa: F401
from database import Base, database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", database_url(sync=True))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            if connection.dialect.name == "postgresql":
                # A migration that waits for a lock (a busy table) fails after
                # 5 seconds instead of stalling every query queued behind it,
                # and the deploy's release step fails with it. A statement that
                # runs past 4 minutes fails before Fly's 5-minute release limit
                # kills the machine. SET LOCAL lasts for this transaction only.
                # A long backfill can raise its own (op.execute("SET LOCAL
                # statement_timeout = '20min'")) along with
                # release_command_timeout in fly.toml.
                connection.execute(text("SET LOCAL lock_timeout = '5s'"))
                connection.execute(text("SET LOCAL statement_timeout = '4min'"))
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
