"""Run the test suites and save the full output to test_results/latest.txt (overwritten).

Usage:  python scripts/save_test_results.py [--no-live]

The live suite makes real requests to bwfbadminton.com (a few dozen seconds, rate limited).
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "test_results" / "latest.txt"


def run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def pytest_run(label: str, extra: list[str]) -> tuple[str, str, int]:
    cmd = [sys.executable, "-m", "pytest", "-v", "--color=no", *extra]
    proc = run(cmd)
    output = proc.stdout + proc.stderr
    last = next((ln for ln in reversed(output.splitlines()) if ln.strip()), "(no output)")
    section = f"{'=' * 78}\n{label}\n$ {' '.join(['pytest', '-v', *extra])}\nexit code: {proc.returncode}\n{'=' * 78}\n{output}\n"
    return section, last.strip("= ").strip(), proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-live", action="store_true", help="skip the live smoke tests")
    args = parser.parse_args()

    commit = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip() or "unknown"
    dirty = bool(run(["git", "status", "--porcelain"]).stdout.strip())

    sections, summaries, codes = [], [], []
    for label, extra in [("OFFLINE TESTS (default suite)", [])] + (
        [] if args.no_live else [("LIVE SMOKE TESTS (real requests)", ["-m", "live"])]
    ):
        section, summary, code = pytest_run(label, extra)
        sections.append(section)
        summaries.append(f"{label.split(' (')[0]:<22} {summary}")
        codes.append(code)

    header = (
        f"Test results - {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        f"Python {platform.python_version()} on {platform.platform()}\n"
        f"Base commit: {commit}{' (+ uncommitted changes from the current iteration)' if dirty else ''}\n\n"
        "SUMMARY\n" + "\n".join(summaries) + "\n\n"
    )
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(header + "\n".join(sections), encoding="utf-8")
    print(header, f"Full output saved to {OUTPUT.relative_to(ROOT)}", sep="")
    return max(codes)


if __name__ == "__main__":
    raise SystemExit(main())
