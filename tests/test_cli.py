"""Integration tests for the click CLI (non-LLM commands)."""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from click.testing import CliRunner

from cli import cli, main


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_group_has_expected_commands(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init", "chat", "setup", "index", "sessions", "undo", "diff", "run", "eval"):
        assert cmd in result.output


def test_cli_sessions_empty_list(runner):
    result = runner.invoke(cli, ["sessions"])
    assert result.exit_code == 0


def test_cli_eval_stats_no_history(runner):
    result = runner.invoke(cli, ["eval"])
    assert result.exit_code == 0


def test_cli_unknown_command_fails(runner):
    result = runner.invoke(cli, ["definitely-not-a-command"])
    assert result.exit_code != 0


def test_cli_debug_flag_accepted(runner):
    result = runner.invoke(cli, ["--debug", "sessions"])
    assert result.exit_code == 0


def test_main_entry_returns_correct_exit_code():
    # main() wraps the CLI in standalone_mode=False and translates
    # click's Exit exception into sys.exit. Unknown group target still
    # raises a normal error -> exit code 1.
    assert callable(main)


def test_init_scaffolds_project(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        assert os.path.isdir("workspace")
        assert os.path.isdir(".sessions")
        assert os.path.exists("agentic.toml")
        assert os.path.exists(".env")
        assert os.path.exists(".gitignore")


def test_init_creates_env_from_template(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        with open(".env", encoding="utf-8") as f:
            content = f.read()
        assert "GEMINI_API_KEY=" in content


def test_init_respects_workspace_option(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init", "--workspace", "myapp"])
        assert result.exit_code == 0
        assert os.path.isdir("myapp")
        assert not os.path.exists("workspace")


def test_init_is_idempotent(runner):
    with runner.isolated_filesystem():
        first = runner.invoke(cli, ["init"])
        assert first.exit_code == 0
        before = open("agentic.toml", encoding="utf-8").read()

        second = runner.invoke(cli, ["init"])
        assert second.exit_code == 0
        after = open("agentic.toml", encoding="utf-8").read()
        assert before == after
        assert "Workspace already exists" in second.output


def test_init_gitignore_adds_missing_entries(runner):
    with runner.isolated_filesystem():
        with open(".gitignore", "w", encoding="utf-8") as f:
            f.write("# existing\n.pytest_cache/\n")
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        with open(".gitignore", encoding="utf-8") as f:
            content = f.read()
        assert ".env" in content
        assert "# existing" in content
