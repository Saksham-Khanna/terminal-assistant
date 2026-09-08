"""
Diff/patch-based editing.

Replaces raw file overwrites with surgical, reviewable edits — the way
Aider/Claude Code actually work. Two tools are exposed to the agent:

  1. edit_file  — precise string replacement (old -> new) in an existing file.
  2. search_replace — find a unique anchor and replace it.

Every edit produces a unified diff so changes are reviewable before/after
they're applied. This avoids clobbering a whole file when only a few lines
need to change, and it makes long conversations safer because the model
doesn't have to reproduce entire files from memory (which is where
"forgets a line" bugs come from).
"""

import difflib
import os

from agent.tools import _resolve

# Unified diff context lines shown around each change.
DIFF_CONTEXT = 3

# Maximum chars a single old_string may span. Prevents the agent from trying
# to replace an entire file and encourages surgical edits.
MAX_EDIT_LENGTH = 8000


def make_unified_diff(path: str, old_text: str, new_text: str) -> str:
    """Build a readable unified diff between old and new file contents."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=DIFF_CONTEXT,
        lineterm="\n",
    ))
    if not diff_lines:
        return "(no changes)"
    return "".join(diff_lines)


def apply_edit(old_text: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """
    Apply a string replacement to old_text.

    If replace_all is False, old_string must appear exactly once (ambiguous
    matches are rejected so the model can't silently patch the wrong spot).
    Returns the new text.
    """
    count = old_text.count(old_string)

    if count == 0:
        raise ValueError(
            f"old_string not found in file. Make sure it matches exactly "
            f"(including whitespace/indentation)."
        )
    if not replace_all and count > 1:
        raise ValueError(
            f"old_string appears {count} times in the file — ambiguous. "
            f"Either add more surrounding context to make it unique, or set "
            f"replace_all=true to replace every occurrence."
        )

    if replace_all:
        return old_text.replace(old_string, new_string)
    return old_text.replace(old_string, new_string, 1)


def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
    show_diff_only: bool = False,
) -> str:
    """
    Apply a surgical edit to a file, returning a unified diff.

    Args:
        path: Relative path inside the workspace.
        old_string: Exact text to find and replace.
        new_string: Replacement text.
        replace_all: If True, replace every occurrence; else require a unique match.
        show_diff_only: If True, only preview the diff without writing (dry run).

    Returns:
        A human-readable unified diff (or an error message).
    """
    full = _resolve(path)
    if not os.path.exists(full):
        return f"Error: file not found: {path}"

    with open(full, "r", errors="replace") as f:
        old_text = f.read()

    if len(old_string) > MAX_EDIT_LENGTH:
        return (
            f"Error: old_string is {len(old_string)} chars, which exceeds the "
            f"{MAX_EDIT_LENGTH}-char limit. Make your edit more surgical — "
            f"replace a smaller block instead of a large one."
        )

    try:
        new_text = apply_edit(old_text, old_string, new_string, replace_all=replace_all)
    except ValueError as e:
        return f"Error: {e}"

    diff = make_unified_diff(path, old_text, new_text)

    if show_diff_only:
        return f"Dry-run diff (not applied):\n{diff}"

    with open(full, "w") as f:
        f.write(new_text)

    return f"Edit applied.\n{diff}\n\n({len(old_string)} chars replaced with {len(new_string)} chars)"


def rewrite_file(path: str, new_content: str) -> str:
    """
    Full-file write with a diff preview (safer than a silent overwrite).

    Kept separate from edit_file so the agent still has an escape hatch when
    a whole-file rewrite genuinely makes sense, but every overwrite is now
    visible as a diff instead of silently clobbering.
    """
    full = _resolve(path)
    old_text = ""
    existed = os.path.exists(full)
    if existed:
        with open(full, "r", errors="replace") as f:
            old_text = f.read()

    import os as _os
    _os.makedirs(_os.path.dirname(full), exist_ok=True)

    with open(full, "w") as f:
        f.write(new_content)

    if not existed:
        diff = f"Created new file {path} ({len(new_content)} chars)."
    else:
        diff = make_unified_diff(path, old_text, new_content)

    return f"Wrote {len(new_content)} chars to {path}.\n{diff}"
