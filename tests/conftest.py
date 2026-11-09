"""Shared database fixtures for unit tests."""

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.session import create_database_engine, create_session_factory


@pytest.fixture
def database_session() -> Iterator[Session]:
    """Provide an isolated SQLite database with foreign keys enforced."""
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        yield session
        session.rollback()
    engine.dispose()
