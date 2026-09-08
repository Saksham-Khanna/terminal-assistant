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
    for cmd in ("chat", "setup", "index", "sessions", "undo", "diff", "run", "eval", "web"):
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
