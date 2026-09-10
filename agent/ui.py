"""
Terminal UI helpers using the Rich library.

Provides consistent, nicely formatted output across all CLI commands:
- Colored banner and panels
- Syntax-highlighted diffs
- Session tables
- Progress indicators
"""

import sys
from typing import Any, Optional

# Windows console Unicode support
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

# Single shared console (Rich handles terminal detection, colors, etc.)
console = Console(legacy_windows=False if sys.platform == "win32" else None)


def has_rich() -> bool:
    """Check if Rich is available at runtime."""
    return _HAS_RICH


def print_banner():
    """Print the Agentic IDE welcome banner."""
    if not _HAS_RICH:
        print("=" * 60)
        print(" Agentic IDE - AI-powered coding assistant")
        print("=" * 60)
        return

    console.print(
        Panel(
            "[bold cyan]Agentic IDE[/bold cyan] - [dim]AI-powered coding assistant "
            "with tool grounding[/dim]",
            border_style="cyan",
            expand=False,
        )
    )


def print_header(text: str, style: str = "bold cyan"):
    """Print a section header."""
    console.print(Text(text, style=style))


def print_success(msg: str):
    """Print a success message."""
    console.print(f"[green]✓[/green] {msg}")


def print_error(msg: str):
    """Print an error message in red."""
    console.print(f"[bold red]✗[/bold red] {msg}")


def print_warning(msg: str):
    """Print a warning message in yellow."""
    console.print(f"[yellow]![/yellow] {msg}")


def print_info(msg: str):
    """Print an info message."""
    console.print(f"[dim]{msg}[/dim]")


def print_markdown(text: str):
    """Render markdown (used for agent responses)."""
    if not _HAS_RICH:
        print(text)
        return
    console.print(Markdown(text))


def print_code(code: str, language: str = "python"):
    """Render syntax-highlighted code."""
    if not _HAS_RICH:
        print(code)
        return
    console.print(Syntax(code, language, theme="monokai", line_numbers=False))


def print_diff(diff_text: str):
    """Render a git diff with +/- coloring."""
    if not _HAS_RICH:
        print(diff_text)
        return

    if not diff_text or diff_text == "(No changes detected in workspace)":
        console.print("[dim]No changes detected in workspace[/dim]")
        return

    # Color diff lines and rebuild output
    colored_lines = []
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            colored_lines.append(f"[green]{line}[/green]")
        elif line.startswith("-") and not line.startswith("---"):
            colored_lines.append(f"[red]{line}[/red]")
        elif line.startswith("@@"):
            colored_lines.append(f"[cyan]{line}[/cyan]")
        elif line.startswith("diff") or line.startswith("index") or line.startswith("---") or line.startswith("+++"):
            colored_lines.append(f"[bold]{line}[/bold]")
        else:
            colored_lines.append(line)

    colored_diff = "\n".join(colored_lines)
    console.print(Panel(colored_diff, title="Workspace Diff", border_style="blue", expand=False))


def print_sessions_table(sessions: list[dict]):
    """Render the saved sessions list as a table."""
    if not sessions:
        console.print("[dim]No saved sessions found in .sessions/ directory.[/dim]")
        return

    if not _HAS_RICH:
        # Fallback to plain text
        print(f"\nSaved Sessions ({len(sessions)}):")
        print("-" * 75)
        for s in sessions:
            print(f"{s['session_id']:<26} {s['turn_count']:<7} {s['provider']:<10} {s['updated_at'][:10] if s['updated_at'] else 'N/A':<12} {s['title']}")
        return

    table = Table(title=f"Saved Sessions ({len(sessions)})", border_style="blue")
    table.add_column("Session ID", style="cyan", no_wrap=False)
    table.add_column("Turns", justify="right")
    table.add_column("Provider", style="magenta")
    table.add_column("Updated", style="dim")
    table.add_column("Title", style="yellow")

    for s in sessions:
        table.add_row(
            s["session_id"],
            str(s["turn_count"]),
            s["provider"],
            (s["updated_at"] or "")[:10],
            s["title"],
        )

    console.print(table)
    console.print("[dim]Resume with: agentic chat --session <id>[/dim]")


def print_eval_scores(result) -> None:
    """Render evaluation results."""
    from agent.eval import _score_icon

    if not _HAS_RICH:
        from agent.eval import format_evaluation
        print(format_evaluation(result))
        return

    from rich.table import Table

    table = Table(title="Evaluation Scores", border_style="cyan")
    table.add_column("Dimension", style="cyan")
    table.add_column("Score", style="magenta")
    table.add_column("", style="bold")

    table.add_row("Faithfulness", f"{result.faithfulness:.2f}", _score_icon(result.faithfulness))
    table.add_row("Relevance", f"{result.relevance:.2f}", _score_icon(result.relevance))
    table.add_row("Completeness", f"{result.completeness:.2f}", _score_icon(result.completeness))
    table.add_row("Groundedness", f"{result.groundedness:.2f}", _score_icon(result.groundedness))
    table.add_row("Overall", f"{result.overall_score:.2f}", result.quality_level)

    console.print(table)
    if result.feedback:
        console.print(Panel(result.feedback[:500], title="Feedback", border_style="dim", expand=False))


def print_spinner(msg: str):
    """Return a spin context manager for long-running operations."""
    if not _HAS_RICH:
        from contextlib import nullcontext
        return nullcontext()

    from contextlib import contextmanager

    @contextmanager
    def _spin():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            progress.add_task(msg, total=None)
            yield

    return _spin()


def print_progress_bar(title: str, current: int, total: int) -> None:
    """Render a simple progress bar."""
    if not _HAS_RICH:
        pct = (current / total * 100) if total else 0
        print(f"{title}: [{pct:.0f}%]", end="\r", flush=True)
        return

    bar = BarColumn()
    console.print(f"[bold]{title}[/bold] {bar.render(current=current, total=total, width=40)}")


def render_stream(chunk: str):
    """Render a streaming text chunk (plain output, no buffering)."""
    console.print(chunk, end="")


def tool_call_line(name: str, args: Any) -> None:
    """Display which tool is being invoked."""
    import json
    args_preview = json.dumps(args, ensure_ascii=False)
    arrow = "→" if sys.stdout and getattr(sys.stdout, "encoding", "").lower().startswith("utf") else "->"
    console.print(f"[bold magenta]{arrow}[/bold magenta] [cyan]{name}[/cyan]({args_preview})")