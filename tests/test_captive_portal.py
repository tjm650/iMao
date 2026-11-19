from fastapi.testclient import TestClient

from backend.app import main


def test_android_probe_redirects_unauthorized_client(monkeypatch):
    monkeypatch.setattr(main, "client_is_authorized", lambda _ip: False)
    with TestClient(main.app) as client:
        response = client.get("/generate_204", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    assert response.headers["cache-control"] == "no-store, private"


def test_android_probe_returns_204_for_authorized_client(monkeypatch):
    monkeypatch.setattr(main, "client_is_authorized", lambda _ip: True)
    with TestClient(main.app) as client:
        response = client.get("/generate_204")
    assert response.status_code == 204
    assert response.content == b""


def test_apple_and_windows_probes_return_expected_online_payloads(monkeypatch):
    monkeypatch.setattr(main, "client_is_authorized", lambda _ip: True)
    with TestClient(main.app) as client:
        apple = client.get("/hotspot-detect.html")
        windows = client.get("/connecttest.txt")
        legacy = client.get("/ncsi.txt")
    assert apple.status_code == 200 and "Success" in apple.text
    assert windows.text == "Microsoft Connect Test"
    assert legacy.text == "Microsoft NCSI"


def test_captive_portal_api_uses_rfc8908_media_type(monkeypatch):
    monkeypatch.setattr(main, "client_is_authorized", lambda _ip: False)
    with TestClient(main.app) as client:
        response = client.get("/api/captive-portal")
    assert response.status_code == 200
    assert response.json() == {"captive": True}
    assert response.headers["content-type"].startswith("application/captive+json")
    assert response.headers["cache-control"] == "no-store, private"
