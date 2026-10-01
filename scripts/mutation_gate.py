"""Fail when the mutmut score drops below a ratchet threshold.

Run after ``mutmut run``: ``uv run python scripts/mutation_gate.py --min-score 92``.
The score is (killed + timeout) / all mutants. Survivors are reviewed by hand
(see verification/mutation-survivors.md); this gate only catches regressions.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter

DETECTED = {"killed", "timeout"}
TOOL_FAILURES = {"suspicious", "segfault", "not checked", "check was interrupted by user"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-score", type=float, required=True, help="minimum score, in percent")
    args = parser.parse_args()

    completed = subprocess.run(
        ["mutmut", "results", "--all", "true"], capture_output=True, text=True, check=True
    )
    statuses = Counter(
        line.rsplit(": ", 1)[1].strip() for line in completed.stdout.splitlines() if ": " in line
    )
    total = sum(statuses.values())
    if total == 0:
        print("mutation gate: no mutant results found; did `mutmut run` complete?", file=sys.stderr)
        return 1
    detected = sum(statuses[status] for status in DETECTED)
    score = 100 * detected / total
    print(
        "mutation gate: "
        + ", ".join(f"{status}={count}" for status, count in sorted(statuses.items()))
        + f"; score {score:.1f}% (minimum {args.min_score:.1f}%)"
    )
    failures = sum(statuses[status] for status in TOOL_FAILURES)
    if failures:
        print(f"mutation gate: {failures} mutants did not run cleanly", file=sys.stderr)
        return 1
    if score < args.min_score:
        print("mutation gate: score is below the minimum", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
