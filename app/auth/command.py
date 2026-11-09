"""Secure one-time initial administrator provisioning command."""

import getpass
import os

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.router import create_initial_administrator
from app.config import Settings
from app.database.models import Administrator
from app.database.session import create_database_engine, create_session_factory


def main() -> None:
    """Provision one administrator without accepting a password in argv."""
    settings = Settings()
    username = os.environ.get("INITIAL_ADMIN_USERNAME", "").strip()
    password = os.environ.get("INITIAL_ADMIN_PASSWORD")
    if not username:
        username = input("Initial administrator username: ").strip()
    if password is None:
        password = getpass.getpass("Initial administrator password: ")
        repeated_password = getpass.getpass("Confirm administrator password: ")
        if password != repeated_password:
            raise SystemExit("Passwords do not match")
    if len(password) < 12:
        raise SystemExit("Administrator password must contain at least 12 characters")

    engine = create_database_engine(settings.database_url.get_secret_value())
    session_factory = create_session_factory(engine)
    try:
        with session_factory.begin() as session:
            if session.scalar(select(Administrator.id).limit(1)) is not None:
                raise SystemExit(
                    "An administrator already exists; bootstrap is disabled",
                )
            create_initial_administrator(session, username, password)
    except IntegrityError as error:
        raise SystemExit("Could not provision administrator; check username") from error
    finally:
        engine.dispose()

    print(
        "Initial administrator provisioned. Remove bootstrap credentials from the environment."
    )
