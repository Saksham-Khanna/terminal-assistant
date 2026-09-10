# Agentic IDE — Terminal Coding Agent

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-green)
![Tests](https://img.shields.io/badge/tests-79%20passed-brightgreen)
![No Framework](https://img.shields.io/badge/built%20without-LangChain%20%2F%20AutoGen-orange)

> **Claude Code / Cursor / Aider jaise tools kaise kaam karte hain — ye project usko scratch se dikhata hai.** LLM agent loop + tool-calling + RAG, bina kisi agent framework ke. Terminal me direct use karo.

**No credit card, no cost — Google Gemini free tier + Groq free tier pe chalta hai.**

---

## Demo

> GIF / Screen recording yahan add karo — `agentic chat` me ek bug fix ka 20-sec demo

```bash
python cli.py chat
# you> Fix the divide-by-zero bug in workspace/sample.py
# agent> [read_file] [edit_file] [run_shell_command: pytest] -> Done
```

---

## Features

| Feature | Detail |
|---|---|
| **Agent Loop** | `LLM -> tool_use -> execute -> repeat` (`agent/core.py:189`), streaming support (`agent/core.py:239`), max 25 iterations |
| **Tools (10)** | `read_file`, `write_file`, `edit_file` (diff-based), `list_dir`, `grep_search`, `find_files_by_glob`, `read_file_range`, `run_shell_command`, `search_codebase`, `undo_last_change` (`agent/tools.py:42`) |
| **RAG Search** | AST-aware chunking (Tree-sitter) + `sentence-transformers` + Chroma vector store (`rag/indexer.py`, `rag/search.py`) |
| **Safety** | Workspace jail (`agent/tools.py:25`), path-traversal block, Docker sandbox (`agent/sandbox.py:116`), auto-lint after edits (`agent/tools.py:360`) |
| **Session & Undo** | Save/resume conversations (`agent/session.py`), git shadow commits + instant `/undo` / `/diff` (`agent/checkpoint.py:100`) |
| **Config** | `agentic.toml` + `.env` layered config, `agentic setup` wizard (`cli.py:92`), multi-provider (Gemini/Groq) (`agent/llm.py:141`) |
| **Cost Tracking** | Token + cost per call (`agent/cost.py`), `/stats` |

---

## Architecture

```
cli.py                  Entry point (index / chat / sessions / undo / diff / run)
agent/
  core.py               Agent loop: LLM -> tool_use? -> execute -> repeat
  llm.py                Thin wrapper around Gemini & Groq APIs
  tools.py              Tool schemas + implementations (file I/O, grep, glob, shell, RAG)
  diff.py               Diff/patch editing: edit_file tool + unified-diff previews
  summarizer.py         Context-window summarization
  session.py            Session persistence (.sessions/)
  checkpoint.py         Git workspace checkpointing & /undo rollback
  sandbox.py            Docker sandbox for shell commands (fallback to local)
rag/
  store.py              Embedding model + Chroma setup
  indexer.py            AST-aware chunking + embedding
  search.py             Semantic search for search_codebase tool
workspace/              Sandboxed directory — agent sirf yahin read/write/run kar sakta hai
tests/                  79 tests (pytest)
```

### How it works

1. **Agent loop** (`agent/core.py`): conversation ko Gemini/Groq pe bhejo with tool schemas. Model ne `function_call` manga toh local `execute_tool` chalao, result wapas feed karo — jab tak plain text reply na aaye.
2. **Tools** (`agent/tools.py`): saare file ops `WORKSPACE_ROOT` me jailed hain. `edit_file` surgical diff deta hai, `write_file` pura overwrite. Har Python edit pe `ast.parse` lint (`agent/tools.py:360`).
3. **RAG** (`rag/`): `python cli.py index` workspace ko Tree-sitter se chunk karta hai, embed karke Chroma me dalta hai. `search_codebase` tool semantic search deta hai.
4. **Checkpoint** (`agent/checkpoint.py`): har file change se pehle/after git commit — `/undo` se instant rollback, `/diff` se diff dekho.

---

## Tech Stack

| Layer | Tech |
|---|---|
| LLM | `google-genai` (Gemini 2.0 Flash), Groq API (`httpx` + `urllib`) |
| RAG | `chromadb`, `sentence-transformers`, `tree-sitter` (+ python/js/java/go/rust) |
| CLI | `click`, `rich` (tables, diffs, spinners) |
| Sandbox | `docker` (optional, auto-fallback to subprocess) |
| Config | `tomllib`, `python-dotenv` |
| Tests | `pytest` (79 passed), `ruff` |

---

## Setup

```bash
python -m venv venv
# Windows: venv\Scripts\activate | Linux/Mac: source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env me GEMINI_API_KEY ya GROQ_API_KEY dalo
# Free Gemini key: https://aistudio.google.com/apikey
# Free Groq key: https://console.groq.com
```

Or one-shot:

```bash
pip install -e .
agentic init      # workspace + sessions + .env + gitignore scaffold
agentic setup     # provider + API key wizard
```

---

## Usage

```bash
# 1. Index workspace for semantic search (first time / after big changes)
python cli.py index
# or
agentic index

# 2. Interactive chat
python cli.py chat
python cli.py chat --session my-feature
python cli.py chat --continue

# 3. Single task
python cli.py run "Fix the divide-by-zero bug in sample.py"

# 4. Helpers
python cli.py sessions   # list saved sessions
python cli.py undo       # undo last change
python cli.py diff       # show workspace git diff
```

### Slash Commands (inside `chat`)

| Command | Kaam |
|---|---|
| `/help` | help menu |
| `/save [name]` | session save |
| `/load <id>` | session load |
| `/sessions` | list sessions |
| `/undo` | last edit rollback |
| `/diff` | git diff dekho |
| `/history` | checkpoint history |
| `/reset` | conversation clear |
| `/model [gemini\|groq]` | provider switch |
| `/stats` | token/cost stats |
| `exit` | quit (auto-save) |

---

## Why No Framework?

Intentionally `LangChain / AutoGen` nahi use kiya — taaki har piece (loop, tool dispatch, retrieval, session) visible rahe. Portfolio ke liye yehi point hai: library import karna nahi, mechanics samajhna.

---

## Roadmap

- [x] Diff/patch editing (`edit_file` + unified diffs)
- [x] AST-aware chunking (Tree-sitter)
- [x] Conversation summarization (context budget)
- [x] Session persistence (`.sessions/`)
- [x] Git checkpointing & `/undo` rollback
- [x] Fast regex search (`grep_search`), `read_file_range`, `glob` search
- [x] Auto-lint / syntax validation loop
- [x] Docker sandbox for `run_shell_command`
- [x] Rich terminal UI (colored diffs, tables, spinners)
- [x] Cost/token tracking
- [ ] Hybrid Search (BM25 + Vector RRF)
- [ ] Multi-Agent Planner-Worker
- [ ] Multi-language AST chunking (JS/TS, Go, Rust, Java — partial done)

---

## Resume Bullet (copy-paste)

> **Agentic IDE — Terminal Coding Agent (like Claude Code)** — Built LLM agent loop from scratch without frameworks: tool-calling with 10 tools, streaming, AST-aware RAG (Chroma + sentence-transformers + Tree-sitter), session persistence & git checkpoint undo, Docker-sandboxed execution. Python, Gemini/Groq, 79 tests.

---

## License

MIT
