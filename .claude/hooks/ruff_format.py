"""PostToolUse hook: keep edited Python files ruff-formatted (CI runs `ruff format --check`).

Reads the hook JSON from stdin. Only touches .py files under src/, tests/ or scripts/.
Never fails the session: any problem is reported on stderr and the hook exits 0.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TARGET_DIRS = {"src", "tests", "scripts"}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        raw_path = payload.get("tool_input", {}).get("file_path")
        if not raw_path:
            return 0
        path = Path(raw_path).resolve()
        root = Path.cwd().resolve()
        relative = path.relative_to(root)
    except (ValueError, json.JSONDecodeError, OSError):
        return 0
    if path.suffix != ".py" or relative.parts[0] not in TARGET_DIRS or not path.is_file():
        return 0
    try:
        result = subprocess.run(
            ["uv", "run", "ruff", "format", str(path)], capture_output=True, text=True, check=False
        )
    except OSError as exc:
        print(f"ruff format skipped for {relative}: {exc}", file=sys.stderr)
        return 0
    if result.returncode != 0:
        print(f"ruff format failed for {relative}: {result.stderr.strip()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
