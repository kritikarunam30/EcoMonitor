from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import require_admin
from app.main import app, probe_database
from app.settings import Settings, get_settings


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "ok", "data_mode": "fixture", "region": "singrauli", "database": "ok"}


def test_health_degraded_without_db(client):
    app.dependency_overrides[probe_database] = lambda: "unavailable"
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


def test_region_returns_configured_bbox(client):
    r = client.get("/region")
    assert r.status_code == 200
    assert r.json() == {"name": "singrauli", "bbox": [82.0, 23.6, 83.4, 24.8]}


def _admin_client(admin_token: str) -> TestClient:
    guarded = FastAPI()
    guarded.dependency_overrides[get_settings] = lambda: Settings(admin_token=admin_token)

    @guarded.post("/admin/ping", dependencies=[Depends(require_admin)])
    def ping() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(guarded)


def test_admin_requires_matching_token():
    c = _admin_client("s3cret")
    assert c.post("/admin/ping").status_code == 401
    assert c.post("/admin/ping", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert c.post("/admin/ping", headers={"X-Admin-Token": "s3cret"}).status_code == 200


def test_admin_refuses_everything_when_token_not_configured():
    c = _admin_client("")
    assert c.post("/admin/ping").status_code == 401
    assert c.post("/admin/ping", headers={"X-Admin-Token": ""}).status_code == 401
