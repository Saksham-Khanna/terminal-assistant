"""
Tools the agent is allowed to call.

Each tool has two parts:
  1. A JSON schema (what Claude sees) describing name/description/inputs.
  2. A Python function (what actually runs on your machine).

The model NEVER executes anything itself — it only requests a tool call.
Your code (execute_tool below) is the gatekeeper that decides whether to
actually run it, and is the right place to add safety checks/sandboxing
later.
"""

import ast
import glob
import os
import re

from agent.config import get_config

# All file operations are jailed to this directory so the agent can't
# wander outside the project it's working on. Swap this for a real
# sandbox (e.g. a Docker container) before trusting it with anything
# important.
WORKSPACE_ROOT = os.path.abspath(
    get_config().workspace_root
)


def _resolve(path: str) -> str:
    """Resolve a path safely inside WORKSPACE_ROOT, blocking path traversal."""
    full = os.path.abspath(os.path.join(WORKSPACE_ROOT, path))
    if not full.startswith(WORKSPACE_ROOT):
        raise ValueError(f"Path '{path}' escapes the workspace — blocked.")
    return full


# ---------------------------------------------------------------------------
# Tool schemas — this is the "menu" the model sees
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "read_file",
        "description": "Read the full contents of a text file inside the project/workspace root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write (create or overwrite) a text file inside the project root. "
            "Every overwrite outputs a diff so changes are reviewable. "
            "For small surgical changes to an existing file, use edit_file instead. "
            "Blocked when AGENT_READ_ONLY=true."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file"},
                "content": {"type": "string", "description": "Full content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Make a surgical, reviewable edit to an existing file by replacing "
            "an exact block of text (old_string) with new text (new_string). "
            "Outputs a unified diff. old_string must be unique in the file unless "
            "replace_all is set to true. Prefer this over write_file for small "
            "targeted changes — it's safer and produces reviewable diffs. "
            "Blocked when AGENT_READ_ONLY=true."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file"},
                "old_string": {
                    "type": "string",
                    "description": "Exact text to find and replace (whitespace/indentation matters)",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "If true, replace every occurrence; if false (default), require a unique match",
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_dir",
        "description": "List files and folders inside a directory in the project root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the directory (use '.' for root)",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_shell_command",
        "description": (
            "Run a shell command inside the project root. "
            "Use for running tests, installing packages, etc. "
            "Destructive or unclear commands will ask for confirmation. "
            "Blocked when AGENT_READ_ONLY=true (except safe read-only commands like ls/cat/git status)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "search_codebase",
        "description": (
            "Semantic search over the indexed codebase. Returns the most relevant "
            "code chunks for a natural-language query. Use this instead of reading "
            "every file when you're not sure where something lives."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What you're looking for"},
                "top_k": {"type": "integer", "description": "How many results to return (default 5)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "grep_search",
        "description": (
            "Fast regex/keyword search across files. Use for finding exact variable names, "
            "function names, or pattern matching. Faster than RAG for precise searches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "path": {"type": "string", "description": "Directory to search in (default: workspace root)"},
                "include": {"type": "string", "description": "File pattern to include (e.g., '*.py', '*.js')"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "read_file_range",
        "description": (
            "Read specific line range from a file. More efficient than reading entire file "
            "for large files. Saves tokens and improves response time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file"},
                "start_line": {"type": "integer", "description": "Start line number (1-indexed)"},
                "end_line": {"type": "integer", "description": "End line number (inclusive)"},
            },
            "required": ["path", "start_line", "end_line"],
        },
    },
    {
        "name": "find_files_by_glob",
        "description": (
            "Find files using glob patterns like **/*.py, src/**/*.tsx, etc. "
            "Useful for finding all files of a type or matching a pattern."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g., '**/*.py', 'src/**/*.tsx')"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "undo_last_change",
        "description": (
            "Roll back the workspace to the previous checkpoint/commit. "
            "Use this if a recent edit or change broke something and you need to revert."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations — what actually runs
# ---------------------------------------------------------------------------

_checkpoint_mgr = None

def get_checkpoint_mgr():
    global _checkpoint_mgr
    if _checkpoint_mgr is None:
        from agent.checkpoint import CheckpointManager
        _checkpoint_mgr = CheckpointManager()
    return _checkpoint_mgr


def _read_file(path: str) -> str:
    full = _resolve(path)
    if not os.path.exists(full):
        return f"Error: file not found: {path}"
    with open(full, "r", errors="replace") as f:
        return f.read()


def _write_file(path: str, content: str) -> str:
    get_checkpoint_mgr().create_checkpoint(f"Before write_file: {path}")
    from agent.diff import rewrite_file
    result = rewrite_file(path, content)
    get_checkpoint_mgr().create_checkpoint(f"Applied write_file: {path}")
    return result


def _edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    get_checkpoint_mgr().create_checkpoint(f"Before edit_file: {path}")
    from agent.diff import edit_file
    result = edit_file(
        path,
        old_string,
        new_string,
        replace_all=replace_all,
    )
    if not result.startswith("Error:"):
        get_checkpoint_mgr().create_checkpoint(f"Applied edit_file: {path}")
    return result


def _list_dir(path: str) -> str:
    full = _resolve(path)
    if not os.path.exists(full):
        return f"Error: directory not found: {path}"
    entries = sorted(os.listdir(full))
    return "\n".join(entries) if entries else "(empty directory)"


# Commands that are always safe to auto-run without confirmation.
SAFE_COMMAND_PREFIXES = (
    "ls", "cat", "pytest", "python -m pytest", "pip list",
    "git status", "git diff", "git log", "python", "python3",
    "dir", "type", "where", "pip show", "pip freeze", "echo"
)


def _run_shell_command(command: str, auto_confirm: bool = False) -> str:
    is_safe = command.strip().startswith(SAFE_COMMAND_PREFIXES)
    if not is_safe and not auto_confirm:
        answer = input(f"\n  Agent wants to run: {command}\n  Allow? [y/N] ").strip().lower()
        if answer != "y":
            return "Command blocked by user."
    from agent.sandbox import run_sandboxed
    return run_sandboxed(command, cwd=WORKSPACE_ROOT)


def _search_codebase(query: str, top_k: int = 5) -> str:
    # Imported lazily so tools.py has no hard dependency on the RAG stack
    # if the user hasn't indexed anything yet.
    from rag.search import search

    results = search(query, top_k=top_k)
    if not results:
        return "No indexed codebase found (or no matches). Run `index` first."
    formatted = []
    for r in results:
        formatted.append(f"--- {r['path']} (score {r['score']:.2f}) ---\n{r['text']}")
    return "\n\n".join(formatted)


def _grep_search(pattern: str, path: str = ".", include: str = None) -> str:
    """Fast regex search across files."""
    search_dir = _resolve(path)
    if not os.path.exists(search_dir):
        return f"Error: directory not found: {path}"
    
    results = []
    regex = re.compile(pattern, re.IGNORECASE)
    
    for root, dirs, files in os.walk(search_dir):
        # Skip hidden directories and common non-code dirs
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'venv', '.git')]
        
        for file in files:
            if include and not glob.fnmatch.fnmatch(file, include):
                continue
            
            filepath = os.path.join(root, file)
            rel_path = os.path.relpath(filepath, WORKSPACE_ROOT)
            
            try:
                with open(filepath, 'r', errors='replace') as f:
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            results.append(f"{rel_path}:{line_num}: {line.rstrip()}")
            except Exception:
                continue
    
    if not results:
        return "No matches found."
    
    return "\n".join(results[:50])  # Limit to 50 results


def _read_file_range(path: str, start_line: int, end_line: int) -> str:
    """Read specific line range from a file."""
    full = _resolve(path)
    if not os.path.exists(full):
        return f"Error: file not found: {path}"
    
    try:
        with open(full, "r", errors="replace") as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        if start_line < 1:
            start_line = 1
        if end_line > total_lines:
            end_line = total_lines
        
        selected_lines = lines[start_line-1:end_line]
        result = f"--- Lines {start_line}-{end_line} of {total_lines} ---\n"
        for i, line in enumerate(selected_lines, start_line):
            result += f"{i}: {line}"
        
        return result
    except Exception as e:
        return f"Error reading file: {e}"


def _find_files_by_glob(pattern: str) -> str:
    """Find files using glob patterns."""
    search_pattern = os.path.join(WORKSPACE_ROOT, pattern)
    matches = glob.glob(search_pattern, recursive=True)
    
    if not matches:
        return "No files matched the pattern."
    
    rel_paths = [os.path.relpath(m, WORKSPACE_ROOT) for m in matches]
    return "\n".join(sorted(rel_paths)[:100])  # Limit to 100 results


def _check_python_syntax(filepath: str) -> str | None:
    """Check Python file for syntax errors. Returns error message or None."""
    if not filepath.endswith('.py'):
        return None
    
    try:
        with open(filepath, 'r', errors='replace') as f:
            source = f.read()
        ast.parse(source)
        return None  # No syntax error
    except SyntaxError as e:
        return f"Syntax error at line {e.lineno}: {e.msg}"
    except Exception as e:
        return f"Error checking syntax: {e}"


def _is_write_blocked() -> str | None:
    """Return block message if project root is read-only."""
    if get_config().is_read_only:
        return (
            "Error: Write blocked - project root is read-only (AGENT_READ_ONLY=true). "
            "This mode only allows read/search/list. Set AGENT_READ_ONLY=false in .env to enable writes."
        )
    return None


def execute_tool(name: str, tool_input: dict) -> str:
    """Dispatch a tool call to its implementation. Always returns a string."""
    # Block writes when read-only
    if name in ("write_file", "edit_file", "run_shell_command", "undo_last_change"):
        blocked = _is_write_blocked()
        if blocked:
            # run_shell_command: allow safe read-only commands even in read-only mode
            if name == "run_shell_command":
                cmd = tool_input.get("command", "").strip()
                is_read_only_cmd = cmd.startswith(("ls", "dir", "cat", "type", "git status", "git diff", "git log", "pytest", "pip list", "pip show", "echo", "python sample.py", "python -m"))
                if not is_read_only_cmd:
                    return blocked
            else:
                return blocked
    try:
        if name == "read_file":
            return _read_file(tool_input["path"])
        elif name == "write_file":
            result = _write_file(tool_input["path"], tool_input["content"])
            # Auto-lint: check syntax after write
            full_path = _resolve(tool_input["path"])
            syntax_error = _check_python_syntax(full_path)
            if syntax_error:
                result += f"\n\n⚠️ AUTO-LINT: {syntax_error}"
            return result
        elif name == "edit_file":
            result = _edit_file(
                tool_input["path"],
                tool_input["old_string"],
                tool_input["new_string"],
                tool_input.get("replace_all", False),
            )
            # Auto-lint: check syntax after edit
            full_path = _resolve(tool_input["path"])
            syntax_error = _check_python_syntax(full_path)
            if syntax_error:
                result += f"\n\n⚠️ AUTO-LINT: {syntax_error}"
            return result
        elif name == "list_dir":
            return _list_dir(tool_input["path"])
        elif name == "run_shell_command":
            return _run_shell_command(tool_input["command"])
        elif name == "search_codebase":
            return _search_codebase(tool_input["query"], tool_input.get("top_k", 5))
        elif name == "grep_search":
            return _grep_search(
                tool_input["pattern"],
                tool_input.get("path", "."),
                tool_input.get("include"),
            )
        elif name == "read_file_range":
            return _read_file_range(
                tool_input["path"],
                tool_input["start_line"],
                tool_input["end_line"],
            )
        elif name == "find_files_by_glob":
            return _find_files_by_glob(tool_input["pattern"])
        elif name == "undo_last_change":
            success, msg = get_checkpoint_mgr().undo_last_checkpoint()
            return msg
        else:
            return f"Error: unknown tool '{name}'"
    except Exception as e:
        # Errors get fed back to the model as a tool_result too, so it can
        # self-correct (e.g. try list_dir if read_file 404s) instead of
        # crashing the whole agent loop.
        return f"Error running tool '{name}': {e}"

