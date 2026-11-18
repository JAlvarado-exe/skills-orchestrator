"""Smoke-test an installed wheel outside the source tree, with network access disabled in pip."""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    wheel = parser.parse_args().wheel.resolve(strict=True)
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "installed"
        subprocess.run([sys.executable, "-m", "pip", "--disable-pip-version-check", "install", "--no-compile",
                        "--no-index", "--no-deps", "--target", str(target), str(wheel)], cwd=tmp, check=True)
        check = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from orchestrator import __version__
from orchestrator.cli import DATA_DIR, main
from orchestrator.profiles import load_profile
assert Path(DATA_DIR).resolve().is_relative_to(Path(sys.argv[1]))
for profile in ('business', 'code', 'core', 'docs', 'research', 'reverse'):
    assert load_profile(profile, [str(Path(DATA_DIR) / 'profiles')])
assert (Path(DATA_DIR) / 'language_bridges.json').is_file()
assert main(['--help']) == 0
"""
        subprocess.run([sys.executable, "-I", "-B", "-c", check, str(target)], cwd=tmp, check=True)


if __name__ == "__main__":
    main()
