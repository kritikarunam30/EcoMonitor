"""Database engine, sessions and schema creation.

The schema is defined once, in app/models.py. Tables are tagged `derived` (re-creatable from
fixtures or live sources) or `user` (watchlists, deliveries).

    python -m app.db                      create PostGIS and any missing tables
    python -m app.db --reset              drop and recreate derived tables; user tables are kept
    python -m app.db --reset --all        drop and recreate everything
    python -m app.db --dump-user FILE     write watchlists to a JSON file
    python -m app.db --restore-user FILE  load watchlists from a JSON file
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, Table, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    # Short connect timeout so /health and test probes fail fast when the DB is down.
    return create_engine(get_settings().database_url, pool_pre_ping=True, connect_args={"connect_timeout": 3})


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session."""
    with get_sessionmaker()() as session:
        yield session


def tables_of_kind(kind: str) -> list[Table]:
    from app import models  # noqa: F401  (registers tables on Base.metadata)

    return [t for t in Base.metadata.sorted_tables if t.info["kind"] == kind]


def init_db(engine: Engine | None = None) -> None:
    """Enable PostGIS and create all tables from app.models. Safe to run repeatedly."""
    from app import models  # noqa: F401

    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(engine)


def reset_db(engine: Engine | None = None, all: bool = False) -> None:  # noqa: A002  (name from the plan)
    """Drop and recreate derived tables. User tables are dropped too only when `all` is true.

    A derived-only reset keeps watchlists but clears `alert_deliveries`: its rows point at
    events and anomalies that no longer exist, and their ids will be reused.
    """
    from app.models import AlertDelivery

    engine = engine or get_engine()
    if all:
        Base.metadata.drop_all(engine)
    else:
        Base.metadata.drop_all(engine, tables=tables_of_kind("derived"))
        with engine.begin() as conn:
            if inspect(conn).has_table(AlertDelivery.__tablename__):
                conn.execute(AlertDelivery.__table__.delete())
    init_db(engine)


def main() -> None:
    from app.repositories.user_data import dump_watchlists, restore_watchlists

    parser = argparse.ArgumentParser(description="Create or reset the database schema; dump or restore user data.")
    parser.add_argument("--reset", action="store_true", help="drop and recreate derived tables")
    parser.add_argument("--all", action="store_true", help="with --reset: drop user tables too")
    parser.add_argument("--dump-user", metavar="FILE", help="write watchlists to a JSON file (repo-relative)")
    parser.add_argument("--restore-user", metavar="FILE", help="load watchlists from a JSON file (repo-relative)")
    args = parser.parse_args()

    if args.all and not args.reset:
        parser.error("--all only makes sense with --reset")
    if args.dump_user:
        path = get_settings().resolve(args.dump_user)
        rows = dump_watchlists(get_engine())
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"wrote {len(rows)} watchlists to {path}")
    elif args.restore_user:
        path = get_settings().resolve(args.restore_user)
        n = restore_watchlists(get_engine(), json.loads(path.read_text(encoding="utf-8")))
        print(f"restored {n} watchlists from {path}")
    elif args.reset:
        reset_db(all=args.all)
        print("database reset (" + ("all tables" if args.all else "derived tables; user tables kept") + ")")
    else:
        init_db()
        print("database ready")


if __name__ == "__main__":
    # Run the importable module, not this __main__ copy: models register on app.db.Base.
    from app.db import main as _main

    _main()
