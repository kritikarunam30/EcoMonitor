from __future__ import annotations

import os

# Tests never touch live services.
os.environ["DATA_MODE"] = "fixture"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.main import app, probe_database  # noqa: E402
from app.settings import get_settings  # noqa: E402

get_settings.cache_clear()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("RUN_LIVE") == "1":
        return
    skip_live = pytest.mark.skip(reason="live test; set RUN_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[probe_database] = lambda: "ok"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def db_engine():
    """Engine on a separate `<database>_test` database, so tests never drop the tables of the dev database."""
    url = make_url(get_settings().database_url)
    test_url = url.set(database=f"{url.database}_test")
    admin = create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
    try:
        with admin.connect() as conn:
            exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": test_url.database})
            if not exists.scalar():
                conn.execute(text(f'CREATE DATABASE "{test_url.database}"'))
    except OperationalError:
        pytest.skip(f"no database at {url.render_as_string(hide_password=True)}")
    finally:
        admin.dispose()
    engine = create_engine(test_url)
    yield engine
    engine.dispose()
