#!/usr/bin/env python3
"""Run each tests/test_*.py module in its own process, in parallel.

Usage: python3 tools/run_tests.py [-j N] [pattern ...]
Patterns are substrings of module names (e.g. `silo player`).
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def run(module):
    started = time.monotonic()
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", module + ".py"],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    return module, result.returncode, result.stderr, time.monotonic() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-j", type=int, default=os.cpu_count() or 4)
    parser.add_argument("patterns", nargs="*")
    args = parser.parse_args()
    modules = sorted(p.stem for p in (ROOT / "tests").glob("test_*.py"))
    if args.patterns:
        modules = [m for m in modules if any(p in m for p in args.patterns)]
    failed, total = [], 0
    with ThreadPoolExecutor(args.j) as pool:
        for module, code, stderr, seconds in pool.map(run, modules):
            counts = re.search(r"Ran (\d+) test", stderr)
            total += int(counts.group(1)) if counts else 0
            status = "ok" if code == 0 else "FAIL"
            print(f"{status:4} {seconds:6.1f}s {module}", flush=True)
            if code:
                failed.append((module, stderr))
    for module, stderr in failed:
        print("\n==== " + module + "\n" + stderr[-6000:])
    print(f"\n{total} tests in {len(modules)} modules; {len(failed)} modules failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
