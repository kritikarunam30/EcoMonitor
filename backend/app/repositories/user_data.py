"""Dump and restore user data (watchlists) so it survives `make resetdb ALL=1`."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Engine, func, select, text

from app.models import Watchlist

_PLAIN_COLUMNS = ("id", "email", "name", "species", "min_score", "confirm_token", "ip_hash")
_TIME_COLUMNS = ("created_at", "confirmed_at")


def dump_watchlists(engine: Engine) -> list[dict[str, Any]]:
    """All watchlists as JSON-ready dicts; `geom` is a GeoJSON geometry, datetimes are ISO strings."""
    columns = [getattr(Watchlist, c) for c in _PLAIN_COLUMNS + _TIME_COLUMNS]
    query = select(*columns, func.ST_AsGeoJSON(Watchlist.geom).label("geom")).order_by(Watchlist.id)
    with engine.connect() as conn:
        rows = conn.execute(query).mappings().all()
    out = []
    for row in rows:
        item = {c: row[c] for c in _PLAIN_COLUMNS}
        item |= {c: row[c].isoformat() if row[c] else None for c in _TIME_COLUMNS}
        item["geom"] = json.loads(row["geom"])
        out.append(item)
    return out


def restore_watchlists(engine: Engine, rows: list[dict[str, Any]]) -> int:
    """Insert dumped watchlists, keeping their ids. Rows whose id already exists are left alone.

    Returns the number of rows inserted.
    """
    insert = text(
        """
        INSERT INTO watchlists
            (id, email, name, geom, species, min_score, created_at, confirmed_at, confirm_token, ip_hash)
        VALUES
            (:id, :email, :name, ST_SetSRID(ST_GeomFromGeoJSON(CAST(:geom AS text)), 4326), :species, :min_score,
             CAST(:created_at AS timestamptz), CAST(:confirmed_at AS timestamptz), :confirm_token, :ip_hash)
        ON CONFLICT (id) DO NOTHING
        """
    )
    inserted = 0
    with engine.begin() as conn:
        for row in rows:
            inserted += conn.execute(insert, row | {"geom": json.dumps(row["geom"])}).rowcount
        # Keep the id sequence ahead of the restored ids.
        conn.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('watchlists', 'id'), "
                "GREATEST((SELECT COALESCE(MAX(id), 0) FROM watchlists), 1))"
            )
        )
    return inserted
