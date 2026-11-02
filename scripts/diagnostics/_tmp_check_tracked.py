# -------------------------
"""检查 tests/unit/core 下所有测试文件的 git 跟踪状态"""
# 两端口径必须一致：git 交回的是**仓内相对路径 + POSIX 分隔符**。旧实现拿绝对反斜杠路径
# 去比，结果恒等于「全部未跟踪」（176/176 就是这么来的）。
import subprocess, os, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from neurova.core.data_root import repoAsset

test_dir = repoAsset("tests", "unit", "core")
files = sorted(f.name for f in test_dir.iterdir() if f.is_file())
specs = [(test_dir.relative_to(REPO) / f).as_posix() for f in files]
tracked = set(subprocess.run(
    ["git", "ls-files", "--", *specs],
    cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
).stdout.splitlines())

untracked = [f for f, spec in zip(files, specs) if spec not in tracked]

print(f"Total: {len(files)} files, Untracked: {len(untracked)}")
for f in untracked:
    print(f"  UNTRACKED: {f}")
