# -*- coding: utf-8 -*-
"""仓根 `.tmp_*` 探针遗留的只降不升棘轮（2026-11-05 立）。

为什么这不是 `tests/conftest.py` 那条污染守卫的第二份：两条各管一个时间点。

- autouse 的 `_guardRepoRootAgainstPollution` 管**跑测期间**——某个用例在仓库根新增顶层条目
  即红，并逐条点名肇事用例；
- 它看不见**已经躺在仓根的历史遗留**：活体探针按既定约定落 `/.tmp_*`，而那行被 `.gitignore`
  豁免 ⇒ `git status` 恒显示干净，积累是无声发生的。「即用即删」这条纪律写在流水线里，
  连续若干批没有兑现，本仓的口径是：**只写在文档里的纪律，根因是缺一条自动复核通道**，
  所以要落成会红的判据（教义第 1 条同形）。

立档实测（本文的数字都是当场量的，不是抄的）：
- 发现时 57 件；其中 4 件是 **0 字节**件（只是"空"与某在册空文件哈希相同，不是真副本）；
- 其余 **53 件 / 1,346,349 字节**：拿对象库里全部 **25,723 个 blob** 比过，**0 件可重现**
  ⇒ 全是唯一内容，含 21 份未入库脚本、2 份与现值差 700+ 行的 `.bak`、1 份 216 KB 且与现树
  互相错位的 `.patch`、约 1.07 MB 的批次取证输出；
- 因此处置方式是**只移动、零删除**：2026-11-05 整体归档到仓外
  `~/neurova-scratch-archive/2026-11-05/`，逐件 sha256 移动前后对表全部一致，并留
  `INDEX.md` 记每件判定；仓根剩 0 件 ⇒ 基线随之从 53 下调到 **0**。
"""

from __future__ import annotations

import pathlib

# 本档在 tests/unit/ 下，仓根要上跳两级——按本档深度自己算，别抄别的档的基准
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: 只降不升的基线。2026-11-05 归档后现量 **0**（清理前 53，见上面的立档实测）。
#: 改大就是给自己开后门：新的探针遗留必须即用即删，要留档可复跑的活体请落 `tests/manual/`。
_SCRATCH_BASELINE = 0


def scratchEntries(root: pathlib.Path) -> list[str]:
    """列出仓库根被 `.gitignore` 豁免的探针遗留条目名（按修改时间新→旧）。

    排序取时间而不是字母名：棘轮红时要一眼看见**刚被谁写进来的那件**，
    按字母序会把新条目埋在中间，等于点名点了个错的。
    """
    entries = list(pathlib.Path(root).glob(".tmp_*"))
    return [p.name for p in sorted(entries, key=lambda p: p.stat().st_mtime, reverse=True)]


def test_repoRootAnchorResolvesToTheRealRepoRoot():
    """先证明这把尺量的确实是仓根：根指错了，下面每条都会恒绿。"""
    for mustExist in ("pyproject.toml", "AGENTS.md", ".gitignore"):
        assert (_REPO_ROOT / mustExist).is_file(), f"仓根锚点不对（缺 {mustExist}）：{_REPO_ROOT}"


def test_scratchLeftoverCountDoesNotRise():
    """存量棘轮：新增一件遗留就红，并点名最后几件。"""
    entries = scratchEntries(_REPO_ROOT)
    assert len(entries) <= _SCRATCH_BASELINE, (
        f"仓根探针遗留从基线 {_SCRATCH_BASELINE} 涨到 {len(entries)} 件；"
        f"最新的那几件：{entries[:5]}。流水线要求活体探针即用即删——"
        f"要留档可复跑的活体请落 tests/manual/，别留在仓根。"
    )


def test_counterReallyCountsAndOnlyCountsTheExemptPattern(tmp_path):
    """反向控制（自证尺子在数东西，也自证它不越界数别的形态）。

    不往仓根写盘：这条只在一个临时目录上验计数函数本身，避免把自己变成肇事用例。
    """
    assert scratchEntries(tmp_path) == [], "起点必须干净"
    (tmp_path / ".tmp_probe.py").write_text("x", encoding="utf-8")
    assert scratchEntries(tmp_path) == [".tmp_probe.py"], "计数尺没数到 .tmp_*"
    (tmp_path / "probe.log").write_text("y", encoding="utf-8")
    (tmp_path / ".tmp_visible_if_removed").write_text("z", encoding="utf-8")
    # 新→旧：后写的那件排前面
    assert scratchEntries(tmp_path) == [".tmp_visible_if_removed", ".tmp_probe.py"], (
        "尺子把非 .tmp_* 的条目也算进来了，或没按新→旧排"
    )


def test_measurementPatternAndTheGitignoreExemptionAreTheSameShape():
    """计数形态必须与豁免形态同源：闸数 `.tmp_*`，`.gitignore` 豁免 `/.tmp_*`。

    两边各漂各的会造出两种坏读数：豁免被放宽后遗留变成"看得见的脏"却没人报警；
    或闸改数别的模式，把存量读成 0 而恒绿。
    """
    lines = [ln.strip() for ln in (_REPO_ROOT / ".gitignore").read_text(
        encoding="utf-8", errors="replace").splitlines()]
    assert "/.tmp_*" in lines, ".gitignore 里那条 `/.tmp_*` 豁免不见了——尺子与豁免已不同源"
