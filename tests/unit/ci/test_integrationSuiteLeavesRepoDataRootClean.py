# -*- coding: utf-8 -*-
"""integration 族跑完不许在**仓内** `data/outbox` 留东西（§6-491）。

成因（现读取证，不是推测）：`data/outbox/dead-letter/` 里曾有 **460** 个 json，event_type 只有
六类测试夹具名（`stat_test`／`llm_cost_recorded`／`agent_event`／`expire_test`／`dlq_test`／
`retry_test`，其中 `llm_cost_recorded` 在 `neurova/` 里 0 命中、只出自那档测试 :360），最新 mtime
停在 **2026-10-06 18:49**。本批先复跑
`tests/integration/collaboration/test_phase3_intelligence.py`（23 passed）并前后各数一次目录——
**460 → 460、newest 不变** ⇒ 污染在今天已不复存在（数据根由 `tests/conftest.py:58` 钉到 session
临时目录，落点走 `neurova/core/data_root.py:96` 的 `callerPath` 单点）。那 460 个是**历史遗留**，
本批已整目录归档后清掉（归档在仓外临时目录并留 SHA-256 清单，属可逆优先）。

⇒ 这道常驻判据钉的是"别再发生"，不是"修好某个缺陷"。三格各防一种空转：

1. 行为格——真起子进程跑指定 integration 档，比较 `data/outbox` 前后快照，不许新增文件；
2. 牙齿格——用合成的"跑完多出两个文件"的快照喂同一个比较函数，必须报出新增（比较函数若被
   写成恒不报，第 1 格就成恒绿装饰）；
3. 不空转格——子进程必须真收集到用例（`collected>0` 且退出码 0），否则"目标档不见了"会被
   读成"没污染、通过"。

另有 `test_snapshotDiffIsRedWhenAFileActuallyLands`（第 2 格）之外的一发手工注入验证记在提交
说明里：判据落笔后真往 `data/outbox` 落一个探针文件复跑，看它红不红。
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from neurova.core.text_encoding import utf8ChildEnv

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: 本批复算过的两档 outbox 相关 integration 档（新增目标先验证它今天确实不污染，再进来）。
TARGETS = (
    "tests/integration/collaboration/test_phase3_intelligence.py",
)

#: 只盯 outbox 族：其它族的落点已有 `tests/conftest.py` 的 session 根与 `callerPath` 两道闸。
WATCHED_DIR = PROJECT_ROOT / "data" / "outbox"

#: 子进程跑一档 integration 的墙；父格墙必须严格大于它（常驻闸
#: `test_nestedPytestBudgetWallsAreOrdered.py` 的同文件闭包判据）。实测子进程 23 格约 5s。
CHILD_WALL_S = 120
PARENT_WALL_S = 200


def _snapshot(root: Path) -> dict:
    if not root.is_dir():
        return {}
    return {str(p.relative_to(root).as_posix()): p.stat().st_size
            for p in root.rglob("*") if p.is_file()}


def _newcomers(before: dict, after: dict) -> list:
    """跑完之后**多出来**的那些路径（改尺寸不算新增，本判据只管"别在仓里留文件"）。"""
    return sorted(set(after) - set(before))


@pytest.mark.timeout(PARENT_WALL_S)
def test_integrationSuiteLeavesRepoOutboxDirClean():
    collectedRe = re.compile(r"collected (\d+) item")
    for target in TARGETS:
        before = _snapshot(WATCHED_DIR)
        child = subprocess.run(
            [sys.executable, "-m", "pytest", target, "-q", "-p", "no:cacheprovider"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=utf8ChildEnv(), cwd=str(PROJECT_ROOT), timeout=CHILD_WALL_S)
        tail = child.stdout[-400:]
        collected = collectedRe.search(child.stdout)
        assert collected and int(collected.group(1)) > 0, (
            "%s 没被收集到任何用例（子进程输出尾部：%r）——目标档改名或消失时，"
            "「没污染」会是假绿" % (target, tail))
        assert child.returncode == 0, (
            "%s 子进程退出码 %s（输出尾部：%r）——判据前提是该档能跑完"
            % (target, child.returncode, tail))
        newcomers = _newcomers(before, _snapshot(WATCHED_DIR))
        assert newcomers == [], (
            "跑完 %s 后仓内 %s 多出 %d 个文件：%s——"
            "数据根没被 `tests/conftest.py` 钉住，或该档自己把落点指回了仓内"
            % (target, WATCHED_DIR.relative_to(PROJECT_ROOT), len(newcomers), newcomers[:5]))


def test_snapshotDiffIsRedWhenFilesActuallyLand():
    """牙齿格：比较函数必须真报新增——它写成恒不报时，上面那格就只是装饰。"""
    before = {"dead-letter/a.json": 10}
    after = {"dead-letter/a.json": 10, "dead-letter/b.json": 20,
             "pending/c.json": 5}
    assert _newcomers(before, after) == ["dead-letter/b.json", "pending/c.json"], (
        "新增文件没被报出来——本档的行为格从此恒绿")
    assert _newcomers(after, after) == [], "同一次快照自己都能报新增，判据在虚报"
    assert _newcomers(before, {"dead-letter/a.json": 99}) == [], (
        "尺寸变化被算成新增——本判据只管「仓里别留文件」，别把改写也判红")


def test_snapshotOfMissingDirIsNotACrash():
    """目录缺席（干净 clone 的初始态）必须读成空快照而不是异常——否则判据在 CI 上直接红。"""
    assert _snapshot(WATCHED_DIR.parent / "outbox-does-not-exist") == {}
