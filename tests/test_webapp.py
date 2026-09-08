"""Integration tests for the FastAPI web backend (non-LLM endpoints)."""

import os
import sys

# Add project root to path so `webapp` and `agent` can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from webapp.server import (
    _build_file_tree,
    _serialize_chunk,
    app,
    auth_enabled,
    verify_token,
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_index_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_health_endpoint(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["workspace"]
    assert data["provider"] in ("gemini", "groq")


def test_files_endpoint_returns_tree(client):
    resp = client.get("/api/files")
    assert resp.status_code == 200
    data = resp.json()
    assert data["root"]
    assert isinstance(data["tree"], list)


def test_read_file_existing(client):
    from agent.tools import WORKSPACE_ROOT

    fname = ".test_tmp_webapp.txt"
    fpath = os.path.join(WORKSPACE_ROOT, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write("hello test")
    try:
        resp = client.get("/api/files/read", params={"path": fname})
        assert resp.status_code == 200
        body = resp.json()
        assert body["path"] == fname
        assert body["content"] == "hello test"
    finally:
        if os.path.exists(fpath):
            os.remove(fpath)


def test_read_file_rejects_path_traversal(client):
    resp = client.get("/api/files/read", params={"path": "../.env"})
    # Should not expose files outside the workspace
    assert resp.status_code in (400, 404)


def test_read_file_missing_returns_404(client):
    resp = client.get("/api/files/read", params={"path": "does_not_exist_123.py"})
    assert resp.status_code == 404


def test_sessions_endpoint(client):
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data
    assert isinstance(data["sessions"], list)


def test_diff_endpoint(client):
    resp = client.get("/api/diff")
    assert resp.status_code == 200


def test_serialize_text_chunk():
    msg = _serialize_chunk("hello")
    assert msg == {"type": "text", "data": "hello"}


def test_serialize_eval_chunk():
    class FakeResult:
        def to_dict(self):
            return {"score": 0.9}

    msg = _serialize_chunk(FakeResult())
    assert msg["type"] == "eval"
    assert msg["data"]["score"] == 0.9


def test_build_file_tree_skips_ignored_dirs(tmp_path):
    (tmp_path / "keep.py").write_text("x = 1")
    (tmp_path / ".git").mkdir()
    (tmp_path / "venv").mkdir()
    tree = _build_file_tree(str(tmp_path))
    names = {e["name"] for e in tree}
    assert "keep.py" in names
    assert ".git" not in names
    assert "venv" not in names


# ---------------------------------------------------------------------------
# API token auth (task: web UI security)
# ---------------------------------------------------------------------------

def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_auth_disabled_by_default(client):
    assert not auth_enabled()
    resp = client.get("/api/files")
    assert resp.status_code == 200


def test_auth_required_rejects_anonymous(monkeypatch, client):
    monkeypatch.setenv("AGENTIC_WEB_AUTH", "true")
    monkeypatch.setenv("AGENTIC_WEB_TOKEN", "test-token-123")
    assert auth_enabled()
    resp = client.get("/api/files")
    assert resp.status_code == 401
    resp = client.get("/api/health")
    assert resp.status_code == 401


def test_auth_required_rejects_wrong_token(monkeypatch, client):
    monkeypatch.setenv("AGENTIC_WEB_AUTH", "true")
    monkeypatch.setenv("AGENTIC_WEB_TOKEN", "test-token-123")
    resp = client.get("/api/files", headers=_auth_headers("wrong-token"))
    assert resp.status_code == 401


def test_auth_required_allows_valid_token(monkeypatch, client):
    monkeypatch.setenv("AGENTIC_WEB_AUTH", "true")
    monkeypatch.setenv("AGENTIC_WEB_TOKEN", "test-token-123")
    resp = client.get("/api/files", headers=_auth_headers("test-token-123"))
    assert resp.status_code == 200
    assert "tree" in resp.json()


def test_verify_token_without_auth(monkeypatch):
    monkeypatch.delenv("AGENTIC_WEB_AUTH", raising=False)
    monkeypatch.delenv("AGENTIC_WEB_TOKEN", raising=False)
    assert verify_token("") is True
    assert verify_token("anything") is True


def test_auth_ws_rejects_missing_token(monkeypatch, client):
    monkeypatch.setenv("AGENTIC_WEB_AUTH", "true")
    monkeypatch.setenv("AGENTIC_WEB_TOKEN", "test-token-123")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/chat"):
            pass
    assert exc_info.value.code == 4401


def test_auth_ws_rejects_wrong_token(monkeypatch, client):
    monkeypatch.setenv("AGENTIC_WEB_AUTH", "true")
    monkeypatch.setenv("AGENTIC_WEB_TOKEN", "test-token-123")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/chat?token=bogus"):
            pass
    assert exc_info.value.code == 4401


def test_auth_ws_accepts_valid_token(monkeypatch, client):
    monkeypatch.setenv("AGENTIC_WEB_AUTH", "true")
    monkeypatch.setenv("AGENTIC_WEB_TOKEN", "test-token-123")
    with client.websocket_connect("/ws/chat?token=test-token-123") as ws:
        ws.send_json({"type": "reset"})
        msg = ws.receive_json()
        assert msg["type"] == "status"


def test_config_web_properties(monkeypatch):
    from agent.config import Config

    monkeypatch.setenv("AGENTIC_WEB_AUTH", "true")
    monkeypatch.setenv("AGENTIC_WEB_TOKEN", "  abc-123  ")
    cfg = Config()
    assert cfg.web_require_auth is True
    assert cfg.web_token == "abc-123"

    monkeypatch.delenv("AGENTIC_WEB_AUTH")
    monkeypatch.delenv("AGENTIC_WEB_TOKEN")
    cfg2 = Config()
    assert cfg2.web_require_auth is False
    assert cfg2.web_token == ""
