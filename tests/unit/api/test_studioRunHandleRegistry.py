# -*- coding: utf-8 -*-
"""H2-3 · ④：Studio 后台任务的句柄必须进 `task_tracker`，模块级无键 set 退役（§6-78）。

缺陷形态（改前）：`studio_api.py:27` 的 `_tasks: set = set()` 只是一份**无键强引用**，
`_spawn_run` 往里 `add`、完成时 `discard`。它能防 GC，但谁也**找不回**任何一条句柄——
没有 run_id→Task 的索引，就没有取消、没有停机排空、没有"这条 run 现在还在跑吗"的读数。
`core/task_tracker.py` 早已是仓内那份注册表（`/console/chat/stop` 的真取消就靠它），
两处各存一份句柄正是教义第 6 条要收口的形态。

取消落点也一起接：wrapper 只 `except Exception`，而 `CancelledError` 继承 `BaseException`——
被取消的 run 会永久停在 `running`（与 §6-84 那格同族的台账版），所以取消分支必须显式收尾
并**照常上抛**。这一格是 §6-72 第 1 格「Studio 取消四件套」的前置：句柄先找得回，
取消端点才有东西可取消。

判据（缺一条这条链就是断的）：
1. 跑起来的 run 能在注册表里**按 run_id 找回句柄**，kind 带出是哪一类长任务；
2. 对它请求停止 → 任务被取消、`CancelledError` 不被吞、台账行落 `cancelled` 且点名成因
   （`task_cancelled`；2026-10-09 起，改前落 `failed`，见 §6-91 的改判说明）
   （改前：行停在 running，且没有任何地方能取消它）；
3. 正常跑完的 run 自动从注册表移除（不留残条目，这是 TaskTracker 自带的 done 回调）；
4. `studio_api.py` 里不得再存在"模块级裸 set 持任务"的形态（AST 判 + **反向对照**）。
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

REPO = Path(__file__).resolve().parents[3]
_API_FILE = REPO / "neurova" / "api" / "endpoints" / "studio_api.py"


def _moduleLevelBareSets(src: str) -> list[str]:
    """模块级 `X = set()` 且该名字在后面被 `.add(...)` 用过——就是无键句柄袋。"""
    tree = ast.parse(src)
    declared = {
        t.id for node in tree.body if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name) and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name) and node.value.func.id == "set"
    }
    if not declared:
        return []
    used = {
        node.func.value.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add" and isinstance(node.func.value, ast.Name)
    }
    return sorted(declared & used)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    from neurova.aigc_studio.store import StudioStore, reset_store

    reset_store()
    s = StudioStore(db_path=str(tmp_path / "studio.db"))
    monkeypatch.setattr("neurova.aigc_studio.store.get_store", lambda: s)
    yield s
    reset_store()


@pytest.fixture()
def tracker():
    from neurova.core.task_tracker import get_task_tracker, reset_task_tracker

    reset_task_tracker()
    yield get_task_tracker()
    reset_task_tracker()


class TestHandlesAreFindable:
    @pytest.mark.asyncio
    async def test_running_run_is_registered_by_run_id(self, store, tracker):
        from neurova.api.endpoints import studio_api

        pid = store.create_project(owner_user_id="u1", title="句柄")["id"]
        gate = asyncio.Event()

        async def work(runId):
            await gate.wait()
            return {"ok": True}

        spawned = studio_api._spawn_run(store, pid, "script", lambda runId: work(runId))
        runId = spawned["data"]["run_id"]
        await asyncio.sleep(0)   # 让 _wrapper 起步

        entries = tracker.lookup_async_tasks(runId)
        assert entries, (
            "跑起来的 run 在注册表里找不回句柄——没有 run_id→Task 的索引，"
            "取消端点就没有东西可取消，停机也无从排空")
        assert entries[0]["kind"].endswith("script"), entries[0]
        gate.set()
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_finished_run_is_dropped_from_the_registry(self, store, tracker):
        from neurova.api.endpoints import studio_api

        pid = store.create_project(owner_user_id="u1", title="回收")["id"]
        gate = asyncio.Event()
        spawned = studio_api._spawn_run(
            store, pid, "narration", lambda runId: gate.wait())
        runId = spawned["data"]["run_id"]
        await asyncio.sleep(0)
        # 先证条目真登记过——否则"查不到"只是空转绿（本仓反复踩的那一格）
        assert tracker.lookup_async_tasks(runId), "没登记过，下面的查空就没有意义"
        gate.set()
        await asyncio.sleep(0.1)
        assert tracker.lookup_async_tasks(runId) == [], \
            "任务结束后条目没移除——注册表会随长任务次数无界增长"


class TestCancelHasAnHonestLanding:
    @pytest.mark.asyncio
    async def test_stop_request_cancels_and_lands_cancelled_with_cause(self, store, tracker):
        from neurova.api.endpoints import studio_api

        pid = store.create_project(owner_user_id="u1", title="取消")["id"]
        gate = asyncio.Event()
        spawned = studio_api._spawn_run(
            store, pid, "images", lambda runId: gate.wait())
        runId = spawned["data"]["run_id"]
        await asyncio.sleep(0)

        assert tracker.request_session_stop(runId) == 1
        await asyncio.sleep(0.1)

        row = store.get_run(runId)
        # 2026-10-09 改判：本批给 runs 加了 `cancelled` 终态（§6-91），句柄被打断落的就是它。
        # 改前这格断的是 `failed` + `run_cancelled`——那是"至少别永久 running"的中间形态，
        # 把"人让它停的"记成"它自己崩了"；两件事的排查方向完全不同。
        assert row["status"] == "cancelled", (
            f"被取消的 run 停在 {row['status']!r}——CancelledError 不被 except Exception 捕获，"
            "行就成了永远在跑的幽灵（前端轮满 10 分钟才报超时）")
        assert "task_cancelled" in (row["error"] or ""), row["error"]
        gate.set()


class TestUnkeyedBagIsRetired:
    def test_studio_api_has_no_module_level_handle_set(self):
        offenders = _moduleLevelBareSets(_API_FILE.read_text(encoding="utf-8"))
        assert not offenders, (
            f"studio_api 仍用模块级裸 set 持句柄：{offenders}——"
            "无键集合只能防 GC，找不回任何一条任务")

    def test_reverse_control_catches_a_reintroduced_bag(self):
        """反向对照：扫不到东西不等于干净（本仓老根因「扫空即全绿」）。"""
        src = "_tasks = set()\n\n\ndef f(t):\n    _tasks.add(t)\n"
        assert _moduleLevelBareSets(src) == ["_tasks"], "扫描器抓不到重新引入的无键句柄袋"
        assert _moduleLevelBareSets("seen = set()\n\n\ndef f(x):\n    seen.add(x)\n") == ["seen"]
        # 合法形态：普通集合不当句柄袋用（没被 .add 走过就不算）
        assert _moduleLevelBareSets("words = set()\n\n\ndef f():\n    return len(words)\n") == []


class TestUnfinishedIsJudgedOnce:
    """H2-3 ②：「这一行还没结束」只许按终态集合判一次，不留窄比较的第二份定义。

    如实记一句：这一格**不是活 bug**——runs 表当前取值域里外层行只会是
    `running → 终态`，`== RUN_RUNNING` 与 `not in RUN_TERMINAL_STATUSES` 今天行为等价。
    它是防漂移收口：等有人写入第三种非终态值（或 wrapper 换个状态判断）那天，
    窄比较会静默漏判，而 `RUN_TERMINAL_STATUSES` 已是写侧与读侧共同的单源。
    """

    def _narrowComparisons(self, src: str) -> list[str]:
        return [f"line {i}: {line.strip()}" for i, line in enumerate(src.splitlines(), 1)
                if "== RUN_RUNNING" in line or "!= RUN_RUNNING" in line]

    def test_wrapper_uses_the_terminal_set_not_a_single_value(self):
        src = _API_FILE.read_text(encoding="utf-8")
        assert not self._narrowComparisons(src), \
            f"studio_api 又写了单值窄比较：{self._narrowComparisons(src)}"

    def test_reverse_control_catches_a_narrow_comparison(self):
        assert self._narrowComparisons("if row.get('status') == RUN_RUNNING:\n    pass\n")
        assert self._narrowComparisons("while x != RUN_RUNNING:\n    pass\n")
        assert not self._narrowComparisons(
            "if row.get('status') not in RUN_TERMINAL_STATUSES:\n    pass\n")
