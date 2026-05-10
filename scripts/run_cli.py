"""Run the in-tree SentrySearch Click CLI.

This avoids the Windows console-script wrapper when long-running background
jobs need a single process tree that is easier to monitor and stop.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sentrysearch.cli import cli  # noqa: E402


if __name__ == "__main__":
    cli()
