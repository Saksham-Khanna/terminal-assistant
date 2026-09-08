"""
Agentic IDE - Terminal-based AI coding agent.

Usage:
    agentic index                 # index the workspace for RAG search
    agentic chat                  # start an interactive agent session
    agentic chat --session <id>   # resume or create a named session
    agentic chat --continue       # resume the most recent session
    agentic sessions              # list all saved sessions
    agentic undo                  # undo the last workspace change
    agentic diff                  # show current workspace git diff
    agentic run "your task here"  # run a single task and exit
    agentic eval [--clear]        # view or clear evaluation stats
"""

import sys
import os

# Windows console Unicode support
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv

load_dotenv()

import click

from agent.core import Agent
from agent.config import Config, PROJECT_CONFIG, create_default_config, get_config
from agent.session import SessionManager
from agent.checkpoint import CheckpointManager
from agent.eval import format_evaluation
from agent.eval_history import get_statistics, format_statistics, clear_history
from agent.tools import WORKSPACE_ROOT
from agent.errors import format_traceback
from agent.ui import (
    console,
    print_banner,
    print_header,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_diff,
    print_sessions_table,
    print_eval_scores,
    print_spinner,
)


@click.group()
@click.version_option(package_name="agentic-ide")
@click.option("--debug", is_flag=True, help="Show full tracebacks on errors", hidden=True)
def cli(debug):
    """Agentic IDE - AI-powered coding assistant with tool grounding."""
    # Store debug flag for the error handler
    global _DEBUG
    _DEBUG = debug
    # Show config warnings on every command but don't block
    _show_config_warnings()


_DEBUG = False


def _show_config_warnings():
    """Print friendly warnings if the user hasn't configured things yet."""
    import os

    config = get_config()
    warnings = config.validate()

    if warnings:
        click.echo(click.style("\n[setup required]", fg="yellow", bold=True))
        for w in warnings:
            click.echo(click.style(f"  {w}", fg="yellow"))
        click.echo(click.style(
            "  Run `agentic setup` for guided configuration.\n", fg="yellow"
        ))


@cli.command()
def setup():
    """One-time guided configuration wizard."""
    config = Config()
    create_default_config()

    print_header("Agentic IDE Setup")
    print_info("All values can be changed later in agentic.toml or .env")

    env_path = os.path.abspath(".env")
    env_example = {
        "GEMINI_API_KEY": "your-gemini-api-key",  # placeholder
    }
    has_existing = os.path.exists(env_path)
    env_lines = []
    if has_existing:
        with open(env_path, "r", encoding="utf-8") as f:
            env_lines = f.read().splitlines()

    # Provider selection
    current = config.provider if (config.has_gemini_key or config.has_groq_key) else None
    provider_choice = click.prompt(
        "Which provider?",
        type=click.Choice(["gemini", "groq"], case_sensitive=False),
        default=current or "gemini",
        show_default=True,
    )

    if provider_choice == "gemini":
        key = click.prompt(
            "Enter your Gemini API key",
            default="",
            show_default=False,
            hide_input=True,
        )
        if key:
            env_lines = [l for l in env_lines if not l.startswith("GEMINI_API_KEY=")]
            env_lines.append(f"GEMINI_API_KEY={key}")
        # Set provider
        env_lines = [l for l in env_lines if not l.startswith("MODEL_PROVIDER=")]
        env_lines.append(f"MODEL_PROVIDER=gemini")
    else:
        key = click.prompt(
            "Enter your Groq API key",
            default="",
            show_default=False,
            hide_input=True,
        )
        if key:
            env_lines = [l for l in env_lines if not l.startswith("GROQ_API_KEY=")]
            env_lines.append(f"GROQ_API_KEY={key}")
        env_lines = [l for l in env_lines if not l.startswith("MODEL_PROVIDER=")]
        env_lines.append("MODEL_PROVIDER=groq")

    # Workspace directory
    ws = click.prompt(
        "Workspace directory (where the agent operates)",
        default=config.workspace_root or "./workspace",
        show_default=True,
    )
    env_lines = [l for l in env_lines if not l.startswith("AGENT_WORKSPACE=")]
    env_lines.append(f"AGENT_WORKSPACE={ws}")

    # Write .env
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(env_lines) + "\n")

    click.echo()
    print_success("Setup complete!")
    print_info(f"Config file: {os.path.abspath(PROJECT_CONFIG)}")
    print_info(f"Environment: {os.path.abspath('.env')}")
    click.echo()
    print_header("Next steps")
    print_info("1. agentic index    # index workspace for semantic search")
    print_info("2. agentic chat     # start coding!")


@cli.command()
@click.option("--workspace", default=None,
              help="Workspace directory to create (default: from config)")
@click.option("--force", is_flag=True, help="Recreate .env from template even if it already exists")
def init(workspace, force):
    """Scaffold a project: workspace, config, .env, and gitignore in one shot."""
    config = Config()

    # 1. Workspace directory
    ws = os.path.abspath(workspace or config.workspace_root)
    if not os.path.exists(ws):
        os.makedirs(ws, exist_ok=True)
        print_success(f"Created workspace: {ws}")
    else:
        print_info(f"Workspace already exists: {ws}")

    # 2. Sessions directory
    sess = os.path.abspath(config.session_dir)
    if not os.path.exists(sess):
        os.makedirs(sess, exist_ok=True)
        print_success(f"Created sessions dir: {sess}")
    else:
        print_info(f"Sessions dir already exists: {sess}")

    # 3. Config file
    cfg_path = create_default_config()
    print_success(f"Config file ready: {cfg_path}")

    # 4. .env (from template or inline fallback)
    env_path = os.path.abspath(".env")
    if os.path.exists(env_path) and not force:
        print_info(f".env already exists, leaving untouched: {env_path}")
    else:
        tpl = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.example")
        if os.path.exists(tpl):
            import shutil
            shutil.copyfile(tpl, env_path)
        else:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write("# Free key: https://aistudio.google.com/apikey\n")
                f.write("GEMINI_API_KEY=your-api-key-here\n\n")
                f.write("# Or Groq (free + fast): https://console.groq.com\n")
                f.write("# MODEL_PROVIDER=groq\n")
                f.write("# GROQ_API_KEY=your-groq-key-here\n")
        print_success(f".env written (add your API key): {env_path}")

    # 5. .gitignore entries
    _ensure_gitignore_entries(os.path.abspath(".gitignore"), [
        ".env",
        ".sessions/",
        "*.egg-info/",
        "__pycache__/",
        ".pytest_cache/",
        ".ruff_cache/",
    ])

    # 6. Summary
    click.echo()
    print_header("Project initialized")
    missing = config.validate()
    if missing:
        for w in missing:
            print_warning(w)
    print_info("Next: add your API key in .env, then run `agentic index` and `agentic chat`.")


def _ensure_gitignore_entries(path: str, entries: list[str]) -> None:
    """Append missing entries to a .gitignore file, creating it if needed."""
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(f"{e}\n" for e in entries))
        print_success(f"Created {path}")
        return
    with open(path, encoding="utf-8") as f:
        existing = f.read().splitlines()
    with open(path, "a", encoding="utf-8") as f:
        for e in entries:
            if e not in existing:
                f.write(f"{e}\n")
                print_success(f"Added '{e}' to {path}")


@cli.command()
def index():
    """Index the workspace for semantic search."""
    from rag.indexer import index_directory

    print_info(f"Indexing workspace: {WORKSPACE_ROOT}")
    with print_spinner("Indexing..."):
        count = index_directory(WORKSPACE_ROOT)
    print_success(f"Indexed {count} chunks.")


@cli.command()
@click.option("--session", "-s", default=None, help="Session ID to resume or create")
@click.option("--continue", "continue_latest", is_flag=True, help="Resume the most recent session")
def chat(session, continue_latest):
    """Start an interactive agent session."""
    mgr = SessionManager()

    if continue_latest:
        session = mgr.get_latest_session_id()
        if not session:
            click.echo("No previous session found to continue. Starting a new session.")

    agent = Agent(session_id=session)

    print_banner()
    print_info("Type /help for available commands or 'exit' to quit.")
    if agent.session_id:
        turns = len(agent.contents) if agent.provider != "groq" else len(agent.groq_messages)
        print_info(f"Active Session: '{agent.session_id}' ({turns} previous turns loaded)")
    click.echo()

    while True:
        try:
            task = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            click.echo()
            break

        if not task:
            continue

        if task.lower() in ("exit", "quit"):
            if agent.session_id:
                agent.save_session(agent.session_id)
                click.echo(f"Session '{agent.session_id}' saved.")
            break

        # Handle Slash Commands
        if task.startswith("/"):
            parts = task.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("/help", "/?"):
                _print_chat_help()
                continue
            elif cmd == "/save":
                saved_id = agent.save_session(session_id=arg if arg else None)
                print_success(f"Session saved successfully as: '{saved_id}'")
                continue
            elif cmd == "/load":
                if not arg:
                    print_warning("Usage: /load <session_id>")
                    continue
                if agent.load_session(arg):
                    turns = len(agent.contents) if agent.provider != "groq" else len(agent.groq_messages)
                    print_success(f"Loaded session '{agent.session_id}' ({turns} turns).")
                else:
                    print_error(f"Session '{arg}' not found.")
                continue
            elif cmd == "/sessions":
                _cmd_sessions()
                continue
            elif cmd == "/undo":
                success, msg = agent.undo_last_checkpoint()
                if success:
                    print_success(msg)
                else:
                    print_error(msg)
                continue
            elif cmd == "/diff":
                diff_text = agent.get_workspace_diff()
                print_diff(diff_text)
                continue
            elif cmd in ("/history", "/checkpoints"):
                history = agent.get_checkpoint_history(8)
                if not history:
                    print_info("No checkpoints found.")
                else:
                    print_header("Checkpoint History")
                    for h in history:
                        print_info(f"[{h['hash']}] {h['date']} | {h['message']}")
                    click.echo()
                continue
            elif cmd in ("/reset", "/new"):
                if agent.session_id:
                    agent.save_session(agent.session_id)
                agent.reset()
                agent.session_id = None
                print_success("Conversation reset. Started a fresh session.")
                continue
            elif cmd == "/model":
                if arg in ("gemini", "groq"):
                    agent.provider = arg
                    print_success(f"Switched model provider to: {arg}")
                else:
                    print_info(f"Current provider: {agent.provider}. Use '/model gemini' or '/model groq' to switch.")
                continue
            elif cmd == "/stats":
                _cmd_eval_stats()
                continue
            else:
                print_warning(f"Unknown command '{cmd}'. Type /help for available commands.")
                continue

        # Regular agent task execution
        console.print("[bold cyan]agent> [/bold cyan]", end="")
        for chunk in agent.run_stream(task):
            if isinstance(chunk, str):
                console.print(chunk, end="")
            else:
                print_eval_scores(chunk)
        console.print("\n")
        print_info(f"usage: {agent.usage.total_tokens:,} tok | "
                   f"${agent.usage.cost_usd:.4f} | "
                   f"{agent.usage.total_calls} calls | "
                   f"{len(agent.tools_called)} tools")


@cli.command(name="sessions")
def list_sessions():
    """List all saved sessions."""
    _cmd_sessions()


@cli.command()
def undo():
    """Undo the last workspace change."""
    mgr = CheckpointManager()
    success, msg = mgr.undo_last_checkpoint()
    if success:
        print_success(msg)
    else:
        print_error(msg)


@cli.command()
def diff():
    """Show current workspace git diff."""
    mgr = CheckpointManager()
    diff_output = mgr.get_workspace_diff()
    print_diff(diff_output)


@cli.command()
@click.argument("task")
def run(task):
    """Run a single task and exit."""
    agent = Agent()
    print_header(f"Task: {task}")
    console.print()
    for chunk in agent.run_stream(task):
        if isinstance(chunk, str):
            console.print(chunk, end="")
        else:
            print_eval_scores(chunk)
    console.print("\n")
    console.print(agent.get_usage_summary())


@cli.command()
@click.option("--clear", is_flag=True, help="Clear evaluation history")
def eval(clear):
    """View or clear evaluation statistics."""
    if clear:
        clear_history()
        print_success("Evaluation history cleared.")
    else:
        _cmd_eval_stats()


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind (default 127.0.0.1)")
@click.option("--port", "-p", default=8000, type=int, help="Port to run on (default 8000)")
@click.option("--reload", is_flag=True, help="Auto-reload server on code changes (dev only)")
def web(host, port, reload):
    """Launch the web UI (FastAPI backend)."""
    try:
        from webapp.server import run_server
    except ImportError as e:
        print_error(f"Web UI dependencies missing: {e}")
        click.echo("  Run: pip install -r requirements.txt")
        return

    print_header(f"Agentic IDE Web UI")
    print_info(f"  URL:   http://{host}:{port}")
    print_info(f"  Ctrl+C to stop")
    click.echo()
    run_server(host=host, port=port, reload=reload)


def _print_chat_help():
    print_header("Available Slash Commands")
    commands = [
        ("/help, /?", "Show this help menu"),
        ("/save [name]", "Save current conversation session to disk"),
        ("/load <name_or_id>", "Switch / restore a saved conversation session"),
        ("/sessions", "List all saved sessions"),
        ("/undo", "Rollback the last file modification made by the agent"),
        ("/diff", "Show git diff of recent workspace changes"),
        ("/history", "Show recent checkpoint commit history"),
        ("/reset, /new", "Clear current conversation history & start fresh"),
        ("/model [gemini|groq]", "Switch LLM provider on the fly"),
        ("/stats", "Display response evaluation statistics"),
        ("exit, quit", "Exit the interactive session"),
    ]
    if console.is_terminal:
        from rich.table import Table
        table = Table(border_style="dim", show_header=False, pad_edge=False)
        table.add_column("Command", style="cyan")
        table.add_column("Description", style="white")
        for c, d in commands:
            table.add_row(c, d)
        console.print(table)
    else:
        for c, d in commands:
            console.print(f"  {c:<25} {d}")


def _cmd_sessions():
    mgr = SessionManager()
    sessions = mgr.list_sessions()
    print_sessions_table(sessions)


def _cmd_eval_stats():
    stats = get_statistics()
    if stats["total_evaluations"] == 0:
        print_info("No evaluation history yet.")
        return
    click.echo(format_statistics(stats))


def main():
    """Main entry point for the CLI."""
    try:
        cli(standalone_mode=False)
    except click.exceptions.Exit as e:
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        click.echo()
        sys.exit(130)
    except Exception as e:
        if _DEBUG:
            click.echo(format_traceback(e))
        else:
            from agent.errors import friendly_error
            click.echo()
            click.echo(click.style("[Error]", fg="red", bold=True) + f" {friendly_error(e)}")
        sys.exit(1)


def entry():
    """console_scripts entry point (wraps main)."""
    main()


if __name__ == "__main__":
    main()
