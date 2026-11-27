#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

CI_DIR = Path(__file__).resolve().parent


def shardNumbers(directory: Path = CI_DIR) -> list[int]:
    numbers = []
    for path in directory.glob("protected_tests.*.txt"):
        match = re.fullmatch(r"protected_tests\.(\d+)\.txt", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return sorted(numbers)


def main() -> int:
    parser = argparse.ArgumentParser(description="从受保护子集分片清单派生 CI 矩阵")
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args()
    payload = json.dumps(shardNumbers(), separators=(",", ":"))
    print(f"shards={payload}" if args.github_output else payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
