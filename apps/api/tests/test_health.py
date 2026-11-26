from fastapi.testclient import TestClient

from provenance.api.app import create_app
from provenance.core.config import Settings


def test_healthz_returns_ok_and_version() -> None:
    client = TestClient(create_app(Settings(_env_file=None)))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}
