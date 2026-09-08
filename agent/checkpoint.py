"""
Workspace checkpointing and undo system.

Uses local git tracking inside WORKSPACE_ROOT to capture snapshots before and
after every file modification. Provides instant rollback (/undo), workspace
diffs, and checkpoint history.
"""

import os
import shutil
import subprocess
import time
from typing import Optional

from agent.tools import WORKSPACE_ROOT


class CheckpointManager:
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = workspace_root or WORKSPACE_ROOT
        self.git_available = self._check_git_available()
        if self.git_available:
            self._ensure_git_repo()

    def _check_git_available(self) -> bool:
        """Check if git is installed and accessible."""
        try:
            res = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return res.returncode == 0
        except Exception:
            return False

    def _run_git(self, args: list[str]) -> tuple[int, str, str]:
        """Run a git command inside workspace_root."""
        if not self.git_available:
            return -1, "", "Git is not installed or available."
        try:
            res = subprocess.run(
                ["git"] + args,
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except Exception as e:
            return -1, "", str(e)

    def _ensure_git_repo(self):
        """Initialize git in workspace if not already present, with an initial commit."""
        git_dir = os.path.join(self.workspace_root, ".git")
        if not os.path.exists(git_dir):
            os.makedirs(self.workspace_root, exist_ok=True)
            self._run_git(["init"])
            # Set local user config so git commit never fails on fresh systems
            self._run_git(["config", "user.name", "Agentic-IDE"])
            self._run_git(["config", "user.email", "agent@agentic-ide.local"])
            
            # Create a default .gitignore for the workspace if none exists
            gitignore_path = os.path.join(self.workspace_root, ".gitignore")
            if not os.path.exists(gitignore_path):
                with open(gitignore_path, "w", encoding="utf-8") as f:
                    f.write("__pycache__/\n*.pyc\n.DS_Store\nnode_modules/\n")
            
            # Initial baseline commit
            self._run_git(["add", "-A"])
            self._run_git(["commit", "-m", "Initial workspace baseline", "--allow-empty"])

    def create_checkpoint(self, description: str) -> Optional[str]:
        """
        Stage all changes and commit with description.
        Returns commit hash or None if no git / failed.
        """
        if not self.git_available:
            return None

        # Stage all changes
        code, out, err = self._run_git(["add", "-A"])
        if code != 0:
            return None

        # Commit
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        commit_msg = f"{description} [{timestamp}]"
        code, out, err = self._run_git(["commit", "-m", commit_msg, "--allow-empty"])
        
        # Get latest commit hash
        code, hash_out, _ = self._run_git(["rev-parse", "--short", "HEAD"])
        if code == 0:
            return hash_out
        return None

    def undo_last_checkpoint(self) -> tuple[bool, str]:
        """
        Revert the workspace to the previous commit (HEAD~1).
        Cleans any untracked files created since then.
        """
        if not self.git_available:
            return False, "Git is not available to perform undo."

        # Check commit count
        code, count_str, _ = self._run_git(["rev-list", "--count", "HEAD"])
        if code != 0 or not count_str.isdigit():
            return False, "Failed to read workspace commit history."

        count = int(count_str)
        if count <= 1:
            return False, "Nothing to undo: workspace is at the initial baseline."

        # Get summary of what we're undoing
        _, last_msg, _ = self._run_git(["log", "-1", "--pretty=%s"])

        # Reset hard to HEAD~1
        code, out, err = self._run_git(["reset", "--hard", "HEAD~1"])
        if code != 0:
            return False, f"Undo failed during reset: {err}"

        # Clean untracked files
        self._run_git(["clean", "-fd"])

        return True, f"Undone: {last_msg}"

    def get_workspace_diff(self) -> str:
        """Get diff of uncommitted changes or last commit changes."""
        if not self.git_available:
            return "(Git not available)"

        # Check unstaged / staged changes first
        code, diff_out, _ = self._run_git(["diff", "HEAD"])
        if code == 0 and diff_out:
            return diff_out

        # If clean, show the diff of the latest commit
        code, last_commit_diff, _ = self._run_git(["show", "--stat", "--patch", "HEAD"])
        if code == 0 and last_commit_diff:
            return last_commit_diff

        return "(No changes detected in workspace)"

    def get_history(self, limit: int = 8) -> list[dict]:
        """Return a list of recent checkpoints."""
        if not self.git_available:
            return []

        format_str = "%h%x09%an%x09%ad%x09%s"
        code, out, _ = self._run_git([
            "log",
            f"-n{limit}",
            f"--pretty=format:{format_str}",
            "--date=short"
        ])
        if code != 0 or not out:
            return []

        entries = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 4:
                entries.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "message": parts[3],
                })
        return entries
