"""Shared pytest fixtures for Realm of Villages tests."""

import os
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

DEFAULT_TEST_URL = "postgresql+psycopg://realm_test:realm_test@localhost:5433/realm_test"


def _test_url() -> str:
    """Return the test database URL from the environment (with a default)."""
    return os.environ.get("REALM_TEST_DATABASE_URL", DEFAULT_TEST_URL)


def _alembic_cfg(url: str) -> Any:
    """Build an alembic Config pointing at the repo alembic.ini and the given URL."""
    from pathlib import Path

    from alembic.config import Config

    ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def db_engine() -> Engine:
    """Session-scoped engine for the test DB; skips DB tests if unreachable."""
    url = _test_url()
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - depends on environment
        pytest.skip(
            f"Test database not reachable at {url}. "
            "Run `docker compose -f docker-compose.test.yml up -d` first."
        )
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    from alembic import command

    command.upgrade(_alembic_cfg(url), "head")
    yield engine
    engine.dispose()


@pytest.fixture()
def s(db_engine: Engine) -> Any:
    """A Session bound to an outer transaction that is rolled back after each test."""
    conn = db_engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


@pytest.fixture()
def cfg() -> Any:
    """The loaded game configuration."""
    from realm.core.config import load_config

    return load_config()


@pytest.fixture()
def t0() -> datetime:
    """A fixed timezone-aware UTC timestamp used as a test reference time."""
    return datetime(2026, 1, 1, tzinfo=UTC)
