"""Tests for the Docker sandbox module."""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import subprocess

import agent.sandbox as sandbox
from agent.sandbox import (
    CONTAINER_WORKSPACE,
    _docker_build_command,
    _local_run,
    _sandbox_section,
    is_docker_available,
    run_sandboxed,
)


def test_sandbox_config_defaults():
    cfg = _sandbox_section()
    assert cfg["enabled"] is True
    assert cfg["image"] == "python:3.12-slim"
    assert cfg["network"] == "none"
    assert cfg["timeout"] > 0


def test_sandbox_config_env_override(monkeypatch):
    monkeypatch.setenv("SANDBOX_ENABLED", "false")
    monkeypatch.setenv("SANDBOX_NETWORK", "bridge")
    cfg = _sandbox_section()
    assert cfg["enabled"] is False
    assert cfg["network"] == "bridge"


def test_docker_build_command_contains_security_flags():
    cmd = _docker_build_command("pytest -q")
    assert cmd[:2] == ["docker", "run"]
    assert "--rm" in cmd
    assert "--workdir" in cmd and CONTAINER_WORKSPACE in cmd
    assert "--read-only" in cmd
    assert "--cap-drop" in cmd and "ALL" in cmd
    assert "--security-opt" in cmd and "no-new-privileges" in cmd
    assert "--network" in cmd and "none" in cmd
    assert cmd[-3:] == ["/bin/sh", "-c", "pytest -q"]


def test_docker_build_command_mounts_workspace():
    cmd = _docker_build_command("ls")
    vol_index = cmd.index("--volume")
    volume_spec = cmd[vol_index + 1]
    assert volume_spec.endswith(f":{CONTAINER_WORKSPACE}")


def test_is_docker_available_when_missing(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    assert is_docker_available() is False


def test_is_docker_available_when_daemon_down(monkeypatch):
    class FakeResult:
        returncode = 1

    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(
        sandbox.subprocess, "run",
        lambda *a, **k: FakeResult(),
    )
    assert is_docker_available() is False


def test_local_run_fallback(monkeypatch):
    monkeypatch.setenv("SANDBOX_ENABLED", "false")

    def fake_run(command, **kwargs):
        assert command == "echo hello"
        assert kwargs["cwd"] == sandbox.WORKSPACE_ROOT
        return subprocess.CompletedProcess(command, 0, stdout="hello\n", stderr="")

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    assert _local_run("echo hello", None).strip() == "hello"


def test_local_run_no_output(monkeypatch):
    monkeypatch.setenv("SANDBOX_ENABLED", "false")

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    assert _local_run("true", None) == "(command produced no output)"


def test_run_sandboxed_falls_back_when_docker_unavailable(monkeypatch):
    monkeypatch.setenv("SANDBOX_ENABLED", "true")
    monkeypatch.setattr(sandbox, "is_docker_available", lambda: False)

    def fake_run(command, **kwargs):
        assert command == "echo fallback"
        return subprocess.CompletedProcess(command, 0, stdout="fallback\n", stderr="")

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    assert run_sandboxed("echo fallback") == "fallback"


def test_run_sandboxed_uses_docker_when_available(monkeypatch):
    monkeypatch.setenv("SANDBOX_ENABLED", "true")
    monkeypatch.setattr(sandbox, "is_docker_available", lambda: True)

    def fake_run(cmd_list, **kwargs):
        assert cmd_list[:2] == ["docker", "run"]
        assert cmd_list[-1] == "echo in-docker"
        return subprocess.CompletedProcess(["docker"], 0, stdout="in-docker\n", stderr="")

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    assert run_sandboxed("echo in-docker") == "in-docker"


def test_run_sandboxed_surfaces_docker_error(monkeypatch):
    monkeypatch.setenv("SANDBOX_ENABLED", "true")
    monkeypatch.setattr(sandbox, "is_docker_available", lambda: True)

    def fake_run(cmd_list, **kwargs):
        assert cmd_list[:2] == ["docker", "run"]
        return subprocess.CompletedProcess(
            ["docker"], 125, stdout="", stderr="docker: Error response from daemon: no such image",
        )

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    result = run_sandboxed("echo boo")
    assert result.startswith("Error: Docker sandbox failed:")


def test_run_sandboxed_timeout(monkeypatch):
    monkeypatch.setenv("SANDBOX_ENABLED", "true")
    monkeypatch.setattr(sandbox, "is_docker_available", lambda: False)

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("cmd", 60)

    monkeypatch.setattr(sandbox.subprocess, "run", boom)
    assert run_sandboxed("sleep 100").startswith("Error: command timed out")
