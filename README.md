# Agentic Coding Assistant (Terminal IDE)

A terminal-based coding agent built from scratch: an LLM agent loop with
tool-calling (file I/O, shell execution) plus a local RAG layer for
semantic codebase search. No agent frameworks (LangChain/etc.) — the loop,
tools, and retrieval pipeline are all hand-built to demonstrate how tools
like Claude Code / Cursor / Aider work under the hood.

Runs on Google's **Gemini API free tier** — no credit card, no cost.

## Architecture

```
cli.py                  Entry point (index / chat / sessions / undo / diff / run)
agent/
  core.py               The agent loop: LLM -> tool_use? -> execute -> repeat
  llm.py                Thin wrapper around Gemini & Groq APIs
  tools.py              Tool schemas + implementations (file I/O, regex, glob, shell exec, codebase search)
  diff.py               Diff/patch editing: edit_file tool + unified-diff previews
  summarizer.py         Conversation summarization for context-window management
  session.py            Session persistence (save/load conversations to .sessions/)
  checkpoint.py         Git workspace checkpointing & instant /undo rollback
rag/
  store.py              Embedding model + Chroma vector store setup
  indexer.py            Chunks files and embeds them into the vector store
  search.py             Semantic search used by the search_codebase tool
workspace/               Sandboxed directory the agent is allowed to read/write/run in
```

### How it works

1. **Agent loop** (`agent/core.py`): sends the conversation to Gemini / Groq with
   a list of available tools. If the model responds with a function-call
   request, the loop executes it locally and feeds the result back in,
   repeating until it replies with plain text (task done) or hits max iterations.
2. **Tools** (`agent/tools.py`): `read_file`, `read_file_range`, `write_file`,
   `edit_file`, `list_dir`, `grep_search`, `find_files_by_glob`, `run_shell_command`,
   `search_codebase`, `undo_last_change`. All file operations are jailed to `workspace/`.
   Auto-linting catches syntax errors after any file edit.
3. **Session Persistence & Checkpointing** (`agent/session.py`, `agent/checkpoint.py`):
   Conversations can be saved and resumed across restarts. The workspace is tracked
   via local shadow git commits before/after edits, enabling instant `/undo` rollbacks.
4. **RAG layer** (`rag/`): `python cli.py index` walks `workspace/`,
   splits files into AST-aware chunks (via Tree-sitter) or line windows, embeds them
   with `sentence-transformers`, and stores them in Chroma DB.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Add your GEMINI_API_KEY (or GROQ_API_KEY) to .env
```

## Usage

```bash
# Index the workspace for semantic search
python cli.py index

# Interactive session (with auto-resume or named sessions)
python cli.py chat
python cli.py chat --session my-feature
python cli.py chat --continue

# List saved sessions
python cli.py sessions

# Rollback or check diffs
python cli.py undo
python cli.py diff

# Run a single task
python cli.py run "Fix the divide-by-zero bug in sample.py"
```

### Interactive Slash Commands

Inside `python cli.py chat`:
- `/save [name]` — Save current session to disk
- `/load <id>` — Load a saved session
- `/sessions` — List all saved sessions
- `/undo` — Rollback the last file edit made by the agent
- `/diff` — Show current workspace git diff
- `/history` — View checkpoint commit history
- `/reset` — Clear conversation and start fresh
- `/model [gemini|groq]` — Switch LLM provider on the fly
- `/help` — Display available commands

## Roadmap & Backlog

- [x] Replace raw `write_file` overwrites with diff/patch-based editing (`edit_file` + unified diffs)
- [x] AST-aware chunking (split by function/class via `tree-sitter`)
- [x] Conversation summarization (context window budget management)
- [x] Session persistence (save/resume conversations to disk via `.sessions/`)
- [x] Git workspace checkpointing & `/undo` instant rollback
- [x] Fast regex search (`grep_search`), line-range reading (`read_file_range`), and glob search
- [x] Auto-linting / syntax validation loop on file edits
- [ ] Rich Terminal TUI with colored diffs, syntax highlighting, and live spinners
- [ ] Multi-language AST chunking (JS/TS, Go, Rust, Java)
- [ ] Hybrid Search (BM25 keyword + Vector embedding Reciprocal Rank Fusion)
- [ ] Multi-Agent Planner-Worker architecture
- [ ] Run `run_shell_command` inside a Docker container
- [ ] FastAPI Backend + Web UI / VS Code extension

## Why no framework?

This is intentionally built without LangChain/AutoGen/etc. so every piece
— the loop, the tool dispatch, the retrieval, and the session engine — is visible and easy to
reason about. That's also the point for a portfolio project: it shows you
understand the mechanics, not just how to import a library.

