"""Command-line entry point for importing initial reference data."""

import argparse
import os
from pathlib import Path

from app.configuration.seeds import (
    load_seed_configuration,
    seed_reference_data,
)
from app.database.session import create_database_engine, create_session_factory

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_seed_file() -> Path:
    """Find the seed file in the working tree or installed project location."""
    working_tree_seed = Path.cwd() / "configs" / "seed.yaml"
    if working_tree_seed.is_file():
        return working_tree_seed
    return PROJECT_ROOT / "configs" / "seed.yaml"


def main() -> None:
    """Validate and import missing seed records into DATABASE_URL."""
    parser = argparse.ArgumentParser(
        description="Import initial eligiable visa-monitor reference data.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=_default_seed_file(),
        help="Path to the seed YAML file.",
    )
    arguments = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL must be set")

    seed_configuration = load_seed_configuration(arguments.file)
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        with session_factory.begin() as session:
            result = seed_reference_data(session, seed_configuration)
    finally:
        engine.dispose()

    for collection in ("origins", "countries", "providers"):
        print(
            f"{collection}: inserted={result.inserted[collection]} "
            f"skipped={result.skipped[collection]}",
        )
