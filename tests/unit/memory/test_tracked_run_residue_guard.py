"""仓库里不许再有"跑测留下的会话/轨迹"这类历史污染。

病灶（审计 2026-09-21 §7 / B-12）：`sessions/` 与 `trajectories/` 是**运行期产物**
目录，`.gitignore` 里本来就写着 `/sessions/` 与 `/trajectories/`。但更早的一次提交
把它们的内容一起提交了进来——于是 ignore 规则从此看不见它们，一份 2026-06-04 的
"hello" 会话与五份 anonymous 轨迹（`session_id=test`）在仓库里躺了三个多月，
每次读 `sessions/` 都会被当成真实会话。

判据：`git ls-files` 在那两个根下必须零命中。规格说明（`docs/**`）不受影响——
写文档描述这些目录的形状是对的，往仓库里塞运行期文件不是。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOTS = ("sessions", "trajectories")

pytestmark = pytest.mark.skipif(
    not (PROJECT_ROOT / ".git").exists() or shutil.which("git") is None,
    reason="需要 git 工作树与可执行的 git 才能查跟踪状态")


def _trackedUnder(root: str) -> list:
    result = subprocess.run(
        ["git", "ls-files", "--", root], cwd=str(PROJECT_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        pytest.skip("git 不可用：%s" % result.stderr.strip())
    return [line for line in result.stdout.splitlines() if line.strip()]


class TestRuntimeRootsAreNotTracked:
    @pytest.mark.parametrize("root", RUNTIME_ROOTS)
    def test_noTrackedFilesUnderRuntimeRoot(self, root):
        """目录本身可以在（运行期要往里写），但它底下不许有被跟踪的文件。

        空目录不进版本库，所以在一次全新建的克隆里它可能还不存在——这不在这条
        判据的范围里（运行时自会创建），判据只咬"有没有内容被提交进来"。
        """
        tracked = _trackedUnder(root)

        assert tracked == [], (
            "%s/ 下仍有被跟踪的运行期文件 %d 个（前 5：%s）——它们是跑测留下的污染，"
            "且因 ignore 规则看不见而长期滞留" % (root, len(tracked), tracked[:5]))

    def test_bothRootsAreIgnored(self):
        """.gitignore 必须继续挡住新增——否则清完还会长回来。"""
        ignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

        for root in RUNTIME_ROOTS:
            assert "/%s/" % root in ignore, "%s/ 不再被 .gitignore 忽略" % root

    def test_docsMayStillDescribeTheShape(self):
        """规格说明不受影响：本项目**描述**这些目录是合规的，塞文件才不合规。"""
        docs = list((PROJECT_ROOT / "docs").rglob("*.md"))
        assert docs, "docs 下零 Markdown，这条反向控制成了空的"
