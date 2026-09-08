"""CLI entry point wrapper.

This module re-exports the main and entry functions from the root cli.py
so that the package entry point works correctly.
"""

import sys
import os

# Add project root to path so we can import cli
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from cli import main, entry

__all__ = ["main", "entry"]