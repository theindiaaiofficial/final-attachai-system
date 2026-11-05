"""Run the offline verification commands used by the repository handoff."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    commands = [
        [sys.executable, "-m", "compileall", "-q", "app", "tests", "scripts"],
        ["ruff", "check", "app", "tests", "scripts"],
        [sys.executable, "-m", "pytest", "-q"],
    ]
    for command in commands:
        result = subprocess.run(command, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
