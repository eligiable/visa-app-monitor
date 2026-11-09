"""Database engine and session-factory construction."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def create_database_engine(
    database_url: str,
    *,
    engine_options: Mapping[str, Any] | None = None,
) -> Engine:
    """Create an engine and enable SQLite foreign-key enforcement."""
    url = make_url(database_url)
    options = dict(engine_options or {})

    if url.drivername.startswith("sqlite"):
        options.setdefault("connect_args", {"check_same_thread": False})

    engine = create_engine(url, **options)

    if url.drivername.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(
            connection: Any,
            _connection_record: Any,
        ) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory that leaves transaction ownership explicit."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
