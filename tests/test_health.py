from fastapi.testclient import TestClient

from backend.app import main


def test_health_is_liveness_probe():
    with TestClient(main.app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "wimao"}


def test_readiness_checks_database_schema():
    with TestClient(main.app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "wimao"}


def test_readiness_returns_503_when_database_is_unavailable(monkeypatch):
    def broken_connect():
        raise OSError("database unavailable")

    monkeypatch.setattr(main, "connect", broken_connect)
    with TestClient(main.app) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "service": "wimao"}
