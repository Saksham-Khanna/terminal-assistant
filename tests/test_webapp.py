"""Integration tests for the FastAPI web backend (non-LLM endpoints)."""

import os
import sys

# Add project root to path so `webapp` and `agent` can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from webapp.server import _build_file_tree, _serialize_chunk, app


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
