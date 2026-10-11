"""Launcher that works from any folder: finds the orchestrator package next to or above this skill."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for candidate in (os.path.join(HERE, "..", ".."), os.path.join(HERE, "..")):
    if os.path.isdir(os.path.join(candidate, "orchestrator")):
        sys.path.insert(0, os.path.abspath(candidate))
        break

from orchestrator.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
