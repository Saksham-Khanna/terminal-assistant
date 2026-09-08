"""
Docker sandbox for running agent shell commands securely.

When Docker is available the agent's ``run_shell_command`` tool runs inside
an ephemeral container that:

* mounts the workspace as read-write at ``/workspace``
* runs the container filesystem as read-only (host code can't be tampered
  with via the container anyway, but it limits blast radius)
* caps memory / CPU and disables network (default) to contain surprises
* is destroyed automatically after the call (``--rm``)

If Docker is missing (or disabled in config) it transparently falls back to
the plain local ``subprocess`` execution, matching the old behaviour so the
agent still works on machines without Docker.

Config (``agentic.toml`` ``[sandbox]`` section or env vars):
  SANDBOX_ENABLED   set "false" to force local execution
  SANDBOX_IMAGE     container image to use (default python:3.12-slim)
  SANDBOX_MEMORY    memory cap, e.g. "512m" or "1g"
  SANDBOX_CPUS      cpu cap, e.g. "2"
  SANDBOX_NETWORK   "none" (default) or "host"/"bridge"
  SANDBOX_TIMEOUT   per-command timeout in seconds
"""

import os
import shutil
import subprocess

from agent.config import get_config

# Mounted inside the container; run_shell_command uses this as cwd.
CONTAINER_WORKSPACE = "/workspace"
WORKSPACE_ROOT = os.path.abspath(get_config().workspace_root)

DEFAULT_IMAGE = "python:3.12-slim"


def _sandbox_section() -> dict:
    section = get_config().section("sandbox") or {}
    return {
        "enabled": (
            os.environ.get("SANDBOX_ENABLED", "true").lower() == "true"
            if os.environ.get("SANDBOX_ENABLED") is not None
            else bool(section.get("enabled", True))
        ),
        "image": os.environ.get("SANDBOX_IMAGE", section.get("image", DEFAULT_IMAGE)),
        "memory": os.environ.get("SANDBOX_MEMORY", section.get("memory", "512m")),
        "cpus": os.environ.get("SANDBOX_CPUS", section.get("cpus", "2")),
        "network": os.environ.get("SANDBOX_NETWORK", section.get("network", "none")),
        "timeout": int(os.environ.get("SANDBOX_TIMEOUT", section.get("timeout", 60))),
    }


def is_docker_available() -> bool:
    """Check if the docker CLI exists and the daemon responds."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _docker_build_command(command: str) -> list[str]:
    """Assemble the docker run command for the given shell command."""
    cfg = _sandbox_section()
    image = cfg["image"]
    memory = cfg["memory"]
    cpus = cfg["cpus"]
    network = cfg["network"]

    return [
        "docker", "run", "--rm",
        "--volume", f"{WORKSPACE_ROOT}:{CONTAINER_WORKSPACE}",
        "--workdir", CONTAINER_WORKSPACE,
        # Read-only filesystem + no extra privileges.
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        # Resource limits.
        "--memory", str(memory),
        "--cpus", str(cpus),
        # Network isolation (default) keeps it a true sandbox.
        "--network", network,
        image,
        "/bin/sh", "-c", command,
    ]


def _docker_exec(command: str) -> subprocess.CompletedProcess:
    """Run a command inside a throwaway Docker container."""
    build_cmd = _docker_build_command(command)
    timeout = _sandbox_section()["timeout"]
    result = subprocess.run(
        build_cmd,
        capture_output=True,
        text=True,
        timeout=timeout + 10,
    )
    # If the daemon refused to start, surface errors instead of empty output.
    if result.returncode not in (0, 137):
        err = result.stderr.strip() or result.stdout.strip()
        if err and ("docker:" in err or "Error response" in err):
            raise RuntimeError(f"Docker sandbox failed: {err}")
    return result


def run_sandboxed(command: str, cwd: str | None = None) -> str:
    """Run a shell command, preferring the Docker sandbox.

    Falls back to plain local ``subprocess`` when Docker isn't available or
    is disabled in config. Returns a human-readable output string.
    """
    cfg = _sandbox_section()
    use_sandbox = cfg["enabled"] and is_docker_available()

    try:
        if use_sandbox:
            result = _docker_exec(command)
            output = result.stdout + result.stderr
            return output.strip() or "(command produced no output)"
        return _local_run(command, cwd)
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {cfg['timeout']}s"
    except RuntimeError as e:
        # Docker came back with a real error — don't silently run locally
        # (that'd defeat the sandbox's purpose). Report it for the model.
        return f"Error: {e}"


def _local_run(command: str, cwd: str | None) -> str:
    """Fallback: execute directly on the host (original behaviour)."""
    cfg = _sandbox_section()
    work_directory = cwd or WORKSPACE_ROOT
    result = subprocess.run(
        command,
        shell=True,
        cwd=work_directory,
        capture_output=True,
        text=True,
        timeout=cfg["timeout"],
    )
    output = result.stdout + result.stderr
    return output.strip() or "(command produced no output)"
