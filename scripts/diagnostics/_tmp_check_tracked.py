# -*- coding: utf-8 -*-
"""检查 tests/unit/core 下所有测试文件的 git 跟踪状态"""
import subprocess, os

test_dir = "tests/unit/core"
files = sorted(os.listdir(test_dir))
tracked = subprocess.run(
    ["git", "ls-files"] + [os.path.join(test_dir, f) for f in files],
    capture_output=True, text=True
).stdout.strip().splitlines()

untracked = []
for f in files:
    fp = os.path.join(test_dir, f)
    if fp not in tracked:
        untracked.append(f)

print(f"Total: {len(files)} files, Untracked: {len(untracked)}")
for f in untracked:
    print(f"  UNTRACKED: {f}")
