"""Launcher that works from any folder and through links: finds the orchestrator package above this skill."""
import os
import sys

# realpath, not abspath: the platform may reach this folder through a symlink or junction
HERE = os.path.dirname(os.path.realpath(__file__))
for candidate in (os.path.join(HERE, "..", ".."), os.path.join(HERE, "..")):
    if os.path.isdir(os.path.join(candidate, "orchestrator")):
        sys.path.insert(0, os.path.abspath(candidate))
        break

from orchestrator.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
