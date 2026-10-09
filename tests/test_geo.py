import math

import pytest
from pyproj import Geod

from app.geo.projection import local_aeqd

WGS84_GEOD = Geod(ellps="WGS84")


@pytest.mark.parametrize(("lon", "lat"), [(82.6, 24.0), (77.2, 28.6)])  # Singrauli (UTM 44), Delhi (UTM 43)
def test_ten_km_east_is_ten_km(lon, lat):
    east_lon, east_lat, _ = WGS84_GEOD.fwd(lon, lat, 90, 10_000)
    to_local, _ = local_aeqd(lon, lat)
    x, y = to_local.transform(east_lon, east_lat)
    assert math.hypot(x, y) == pytest.approx(10_000, rel=0.005)
    assert x > 0
    assert abs(y) < 50  # due east, apart from the curvature of the parallel


def test_centre_maps_to_origin_and_roundtrips():
    to_local, to_wgs84 = local_aeqd(82.6, 24.0)
    assert to_local.transform(82.6, 24.0) == pytest.approx((0.0, 0.0), abs=1e-6)
    lon, lat = to_wgs84.transform(*to_local.transform(82.9, 24.3))
    assert (lon, lat) == pytest.approx((82.9, 24.3), abs=1e-9)
