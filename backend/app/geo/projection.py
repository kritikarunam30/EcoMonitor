"""Local metric projection. All metric work (buffers, distances, cones) goes through here."""

from __future__ import annotations

from pyproj import CRS, Transformer

WGS84 = CRS.from_epsg(4326)


def local_aeqd(lon: float, lat: float) -> tuple[Transformer, Transformer]:
    """Transformers between WGS84 and an azimuthal-equidistant projection centred on (lon, lat).

    Returns ``(to_local, to_wgs84)``. Both take and return x/lon first: ``to_local.transform(lon, lat)``
    gives metres east and north of the centre; ``to_wgs84.transform(x, y)`` gives ``(lon, lat)``.
    Distances from the centre are exact, so no UTM zone is ever needed.
    """
    local = CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m +no_defs")
    to_local = Transformer.from_crs(WGS84, local, always_xy=True)
    to_wgs84 = Transformer.from_crs(local, WGS84, always_xy=True)
    return to_local, to_wgs84
