import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db import Base, init_db, reset_db, tables_of_kind
from app.models import AlertDelivery, Watchlist, WatchUnit
from app.repositories.user_data import dump_watchlists, restore_watchlists

DERIVED_TABLES = {
    "facilities",
    "watch_units",
    "detections",
    "events",
    "emission_estimates",
    "baseline_predictions",
    "anomalies",
    "exposures",
    "layer_cache",
}
USER_TABLES = {"watchlists", "alert_deliveries"}
SQUARE = "SRID=4326;POLYGON((82.5 24.0, 82.7 24.0, 82.7 24.2, 82.5 24.2, 82.5 24.0))"


def test_models_define_expected_tables_with_kinds():
    assert {t.name for t in tables_of_kind("derived")} == DERIVED_TABLES
    assert {t.name for t in tables_of_kind("user")} == USER_TABLES
    assert set(Base.metadata.tables) == DERIVED_TABLES | USER_TABLES


def test_user_tables_do_not_depend_on_derived_tables():
    """Otherwise a derived-only reset could not drop the derived tables."""
    for table in tables_of_kind("user"):
        for fk in table.foreign_keys:
            assert fk.column.table.name in USER_TABLES, f"{table.name}.{fk.parent.name} -> {fk.column.table.name}"


def test_schema_compiles_for_postgresql():
    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        assert str(CreateTable(table).compile(dialect=dialect))
        for index in table.indexes:
            assert str(CreateIndex(index).compile(dialect=dialect))


def _add_watchlist(engine) -> int:
    with Session(engine) as session:
        row = Watchlist(email="judge@example.org", name="test area", geom=SQUARE, species=["NO2"], min_score=0.4)
        session.add(row)
        session.commit()
        return row.id


def _count(engine, model) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model))


@pytest.mark.db
def test_init_db_creates_schema_on_postgis(db_engine):
    reset_db(db_engine, all=True)
    init_db(db_engine)  # second run is a no-op

    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT postgis_version()")).scalar()
        assert set(inspect(conn).get_table_names()) >= DERIVED_TABLES | USER_TABLES


@pytest.mark.db
def test_reset_keeps_watchlists_unless_all(db_engine):
    reset_db(db_engine, all=True)
    watchlist_id = _add_watchlist(db_engine)
    with Session(db_engine) as session:
        session.add(WatchUnit(kind="facility", name="unit", geom="SRID=4326;POINT(82.6 24.1)", member_ids=[]))
        session.add(AlertDelivery(watchlist_id=watchlist_id, event_id=1, email="judge@example.org"))
        session.commit()

    reset_db(db_engine)
    assert _count(db_engine, Watchlist) == 1
    assert _count(db_engine, WatchUnit) == 0
    assert _count(db_engine, AlertDelivery) == 0  # its event no longer exists

    reset_db(db_engine, all=True)
    assert _count(db_engine, Watchlist) == 0


@pytest.mark.db
def test_watchlists_survive_a_full_reset_through_dump_and_restore(db_engine):
    reset_db(db_engine, all=True)
    watchlist_id = _add_watchlist(db_engine)
    dumped = dump_watchlists(db_engine)
    assert [row["id"] for row in dumped] == [watchlist_id]
    assert dumped[0]["geom"]["type"] == "Polygon"

    reset_db(db_engine, all=True)
    assert restore_watchlists(db_engine, dumped) == 1
    assert restore_watchlists(db_engine, dumped) == 0  # already there
    assert dump_watchlists(db_engine) == dumped
    assert _add_watchlist(db_engine) > watchlist_id  # the id sequence moved past the restored row
