# tests/test_server.py
import json
from unittest.mock import MagicMock, patch

import pytest

from server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@patch("server.get_camera")
def test_status_no_camera(mock_get_camera, client):
    mock_get_camera.return_value = None
    resp = client.get("/api/status")
    data = json.loads(resp.data)
    assert data["connected"] is False


@patch("server.get_camera")
def test_status_with_camera(mock_get_camera, client):
    mock_camera = MagicMock()
    mock_camera.get_summary.return_value = MagicMock(
        __str__=lambda self: "Model: Canon EOS 5D Mark II\nSerial Number: abc123\nVersion: 3-1.1.0\n"
    )
    mock_get_camera.return_value = mock_camera
    resp = client.get("/api/status")
    data = json.loads(resp.data)
    assert data["connected"] is True
    assert data["model"] == "Canon EOS 5D Mark II"


@patch("server.get_camera")
def test_camera_all_no_camera(mock_get_camera, client):
    mock_get_camera.return_value = None
    resp = client.get("/api/camera")
    assert resp.status_code == 404
    data = json.loads(resp.data)
    assert data["connected"] is False


@patch("server.get_camera")
def test_camera_all_with_data(mock_get_camera, client):
    mock_camera = MagicMock()
    mock_camera.get_summary.return_value = MagicMock(
        __str__=lambda self: "Model: Canon EOS 5D Mark II\nSerial Number: abc123\nVersion: 3-1.1.0\n"
    )

    def mock_get_single_config(key):
        values = {
            "/main/status/batterylevel": "100%",
            "/main/status/shuttercounter": "8360",
            "/main/settings/ownername": "Alex",
            "/main/settings/artist": "Alex V",
            "/main/settings/copyright": "(c) 2026",
        }
        mock_config = MagicMock()
        mock_config.get_value.return_value = values.get(key, "")
        return mock_config

    mock_camera.get_single_config = mock_get_single_config
    mock_get_camera.return_value = mock_camera

    resp = client.get("/api/camera")
    data = json.loads(resp.data)
    assert data["connected"] is True
    assert data["overview"]["model"] == "Canon EOS 5D Mark II"
    assert data["overview"]["battery"] == "100%"
    assert data["shutter"]["count"] == 8360
    assert data["shutter"]["ratedLifespan"] == 150000
    assert data["shutter"]["wearPercent"] == 5.6
    assert data["user"]["owner"] == "Alex"
    assert data["user"]["artist"] == "Alex V"
    assert data["user"]["copyright"] == "(c) 2026"


@patch("server.get_camera")
def test_post_user_writes_and_reads_back(mock_get_camera, client):
    mock_camera = MagicMock()
    written = {}

    def mock_get_single_config(key):
        mock_config = MagicMock()
        mock_config.get_value.return_value = written.get(key, "")
        def set_value(v):
            mock_config._pending_value = v
        mock_config.set_value = set_value
        return mock_config

    def mock_set_single_config(key, config):
        written[key] = config._pending_value

    mock_camera.get_single_config = mock_get_single_config
    mock_camera.set_single_config = mock_set_single_config
    mock_get_camera.return_value = mock_camera

    resp = client.post(
        "/api/camera/user",
        data=json.dumps({"owner": "New Owner", "artist": "New Artist"}),
        content_type="application/json",
    )
    data = json.loads(resp.data)
    assert data["owner"] == "New Owner"
    assert data["artist"] == "New Artist"
    assert data["copyright"] == ""


@patch("server.get_camera")
def test_post_user_no_body_returns_400(mock_get_camera, client):
    resp = client.post("/api/camera/user", content_type="application/json")
    assert resp.status_code == 400
