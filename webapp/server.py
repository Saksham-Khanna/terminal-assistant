"""
FastAPI backend for the Agentic IDE web UI.

Serves the static web app and exposes:
  - WebSocket /ws/chat        -> streaming agent conversations
  - GET /api/health           -> server status
  - GET /api/sessions         -> list saved sessions
  - GET /api/diff             -> workspace git diff
  - POST /api/index           -> trigger RAG indexing
  - GET /api/files            -> workspace file tree
  - GET /api/files/read       -> read a file from the workspace

Run with:
    agentic web [--port 8000] [--host 127.0.0.1]
"""

import asyncio
import os
import secrets
import string
import threading

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

load_dotenv()

from agent.checkpoint import CheckpointManager
from agent.config import get_config
from agent.core import Agent
from agent.session import SessionManager
from agent.tools import WORKSPACE_ROOT

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="Agentic IDE Web", version="0.1.0")

_bearer = HTTPBearer(auto_error=False)

# Ephemeral token used when auth is required but no token is configured.
_EPHEMERAL_TOKEN = {"value": ""}


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

def _configured_token() -> str:
    """Resolve the API token from config/env, or generate an ephemeral one."""
    cfg = get_config()
    explicit = cfg.web_token
    if explicit:
        return explicit
    if not cfg.web_require_auth:
        return ""
    if not _EPHEMERAL_TOKEN["value"]:
        alphabet = string.ascii_letters + string.digits
        _EPHEMERAL_TOKEN["value"] = "".join(secrets.choice(alphabet) for _ in range(32))
    return _EPHEMERAL_TOKEN["value"]


def auth_enabled() -> bool:
    """True if the web UI requires an API token."""
    return get_config().web_require_auth


def verify_token(provided: str) -> bool:
    """Validate a raw token string against the expected value."""
    if not auth_enabled():
        return True
    return bool(provided) and secrets.compare_digest(provided, _configured_token())


def require_auth(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    """FastAPI dependency that rejects unauthenticated REST calls when auth is on."""
    if not auth_enabled():
        return
    if credentials is None or not verify_token(credentials.credentials):
        raise HTTPException(status_code=401, detail="Missing or invalid API token")


def _setup_cors() -> None:
    """Add CORS middleware only when allow_origins is explicitly configured."""
    origins = get_config().web_allow_origins
    if not origins:
        return
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _ensure_token_printed() -> None:
    """If auth is required and only an ephemeral token is available, print it."""
    if not get_config().web_require_auth:
        return
    if not get_config().web_token:
        print(f"\n  [security] API token protection enabled. Token: {_configured_token()}\n")


_setup_cors()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_chunk(chunk) -> dict | None:
    """Convert an agent stream chunk into a JSON-serializable message."""
    if isinstance(chunk, str):
        return {"type": "text", "data": chunk}
    # EvaluationResult
    return {"type": "eval", "data": chunk.to_dict()}


def _build_file_tree(root: str) -> list[dict]:
    """Build a nested file tree of the workspace (ignoring heavy dirs)."""
    skip_dirs = {".git", "__pycache__", "node_modules", "venv", ".sessions", ".pytest_cache", ".chroma", "rag_db"}

    def walk(dirpath: str, rel: str) -> list[dict]:
        entries = []
        try:
            names = sorted(os.listdir(dirpath), key=str.lower)
        except (FileNotFoundError, PermissionError):
            return entries
        for name in names:
            full = os.path.join(dirpath, name)
            rel_path = name if not rel else f"{rel}/{name}"
            if os.path.isdir(full):
                if name in skip_dirs:
                    continue
                entries.append({
                    "name": name,
                    "path": rel_path,
                    "type": "dir",
                    "children": walk(full, rel_path),
                })
            else:
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                entries.append({
                    "name": name,
                    "path": rel_path,
                    "type": "file",
                    "size": size,
                })
        return entries

    return walk(root, "")


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/health", dependencies=[Depends(require_auth)])
async def health():
    config = get_config()
    return {
        "status": "ok",
        "provider": config.provider,
        "workspace": WORKSPACE_ROOT,
        "model": config.gemini_model if config.provider == "gemini" else config.groq_model,
    }


@app.get("/api/sessions", dependencies=[Depends(require_auth)])
async def list_sessions():
    mgr = SessionManager()
    return {"sessions": mgr.list_sessions()}


@app.get("/api/diff", dependencies=[Depends(require_auth)])
async def diff():
    mgr = CheckpointManager()
    return {"diff": mgr.get_workspace_diff()}


@app.post("/api/index", dependencies=[Depends(require_auth)])
async def index_workspace():
    try:
        from rag.indexer import index_directory
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Indexing unavailable: {e}"})

    result: dict = {}
    def _do_index():
        try:
            count = index_directory(WORKSPACE_ROOT)
            result["count"] = count
            result["error"] = None
        except Exception as e:
            result["count"] = 0
            result["error"] = str(e)

    thread = threading.Thread(target=_do_index, daemon=True)
    thread.start()
    thread.join(timeout=180)
    if result.get("error"):
        return JSONResponse(status_code=500, content={"error": result["error"]})
    return {"count": result.get("count", 0)}


@app.get("/api/files", dependencies=[Depends(require_auth)])
async def files():
    return {"root": WORKSPACE_ROOT, "tree": _build_file_tree(WORKSPACE_ROOT)}


@app.get("/api/files/read", dependencies=[Depends(require_auth)])
async def read_file(path: str):
    from agent.tools import _resolve
    try:
        full = _resolve(path)
        if not os.path.exists(full) or os.path.isdir(full):
            return JSONResponse(status_code=404, content={"error": f"File not found: {path}"})
        with open(full, encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"path": path, "content": content}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/api/files/write", dependencies=[Depends(require_auth)])
async def write_file(data: dict):
    """Write file content to workspace. Reuses agent's _write_file for path safety."""
    from agent.tools import _write_file
    path = data.get("path", "")
    content = data.get("content", "")
    if not path:
        return JSONResponse(status_code=400, content={"error": "path is required"})
    try:
        result = _write_file(path, content)
        return {"path": path, "result": result}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


# ---------------------------------------------------------------------------
# WebSocket - streaming chat
# ---------------------------------------------------------------------------


def _agent_stream(agent: Agent, message: str, queue: asyncio.Queue):
    """Run the agent in a background thread and push chunks to the queue."""
    def _on_tool(name, args):
        try:
            queue.put_nowait(("tool", {"name": name, "args": args}))
        except Exception:
            pass
    agent.tool_observers.append(_on_tool)
    try:
        for chunk in agent.run_stream(message):
            queue.put_nowait(("chunk", chunk))
    except Exception as e:
        queue.put_nowait(("error", str(e)))
    finally:
        try:
            agent.tool_observers.remove(_on_tool)
        except ValueError:
            pass
        try:
            queue.put_nowait(("usage", agent.get_usage_summary()))
        except Exception:
            queue.put_nowait(("usage", ""))
        queue.put_nowait(("done", None))


@app.websocket("/ws/chat")
async def chat(ws: WebSocket):
    token = ws.query_params.get("token", "")
    if not verify_token(token):
        await ws.close(code=4401, reason="unauthorized")
        return
    await ws.accept()
    agent = Agent(enable_evaluation=True)
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "chat")

            if msg_type == "chat":
                message = data.get("message", "")
                if not message.strip():
                    continue

                await ws.send_json({"type": "status", "data": "thinking"})
                queue: asyncio.Queue = asyncio.Queue()
                thread = threading.Thread(
                    target=_agent_stream,
                    args=(agent, message, queue),
                    daemon=True,
                )
                thread.start()

                while True:
                    kind, payload = await queue.get()
                    if kind == "chunk":
                        msg = _serialize_chunk(payload)
                        if msg:
                            await ws.send_json(msg)
                    elif kind == "tool":
                        await ws.send_json({"type": "tool", "data": payload})
                    elif kind == "error":
                        await ws.send_json({"type": "error", "data": payload})
                    elif kind == "usage":
                        await ws.send_json({"type": "usage", "data": payload})
                    elif kind == "done":
                        await ws.send_json({"type": "done"})
                        break

            elif msg_type == "reset":
                if agent.session_id:
                    try:
                        agent.save_session(agent.session_id)
                    except Exception:
                        pass
                agent.reset()
                await ws.send_json({"type": "status", "data": "reset"})

            elif msg_type == "load_session":
                session_id = data.get("session_id")
                if session_id and agent.load_session(session_id):
                    await ws.send_json({"type": "status", "data": f"loaded:{session_id}"})
                else:
                    await ws.send_json({"type": "error", "data": f"Session '{session_id}' not found"})

            elif msg_type == "save_session":
                name = data.get("name")
                saved_id = agent.save_session(session_id=name if name else None)
                await ws.send_json({"type": "status", "data": f"saved:{saved_id}"})

    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def run_server(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
    """Launch the uvicorn dev server."""
    import uvicorn
    _ensure_token_printed()
    uvicorn.run("webapp.server:app", host=host, port=port, reload=reload, log_level="info")


if __name__ == "__main__":
    run_server()
