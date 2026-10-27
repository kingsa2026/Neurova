# -*- coding: utf-8 -*-
"""H2-5 · K 条：蜂群子任务的终态必须总会到（超时/取消都有落点，卡死不占槽）。

缺陷形态（改前，§6-78 K 条）：`swarm.py` 里 `agent.chat` 是**裸 await**，全文件没有
`wait_for`/`timeout`/`cancel`；终态只在 `except Exception` 那一支落。于是

- 上游流静默停滞（2026-09-10 那族事故：`multi_model_client` 的静默看门狗只留 WARNING，
  **不中止**）→ run 永久停在 `running`；
- 外层任务被取消（`CancelledError` 继承 `BaseException`，不被 `except Exception` 捕获）
  → 同样永久 `running`；
- 而 `MAX_ACTIVE_CHILDREN=5` 的广度闸按 `pending|running` 计数、`_evict_finished_runs`
  只逐 `completed|failed` → **5 条卡死之后蜂群整体不可用**，且拒案文案让 LLM
  「请等待现有子任务完成」——指向一个永不会发生的完成。

修法（教义第 1/6 条）：

1. **预算不新造数字**：仓内早已声明这条链的窗口——`tool_coordinator` 的
   `TOOL_TIMEOUTS_S["spawn_subagent"] = 600.0`（2026-09-10 蜂群排查落表，注释写明
   「前台 spawn 子任务动辄数分钟，60s 默认=必然转后台」）。工具层 600s 后放弃等待，
   而 run 本身可以永远挂着——两份口径的差就是本条缺陷。现让 `_execute` **取同一份读数**
   （`_effectiveRuntimeBudget()`，可被 `NEUROVA_SWARM_SUBAGENT_BUDGET_SEC` 覆盖），
   `asyncio.wait_for` 到点即诚实落终态。
2. **任何退出路径都写终态**：`TimeoutError` → `failed` + 点名 `subagent_timeout（预算 Ns）`；
   `CancelledError` → `failed` + 点名 `subagent_cancelled`，**并继续上抛**（不吞取消）。
   状态值不新增（沿用 `failed`），免得制造「非终态/终态新增格必查四处」那一族的新命中点。
3. **状态词汇一份定义**：`pending|running|completed|failed` 的字面量散在 6 处
   （dataclass 默认、投影、`list_active`、`_count_active`、`_evict_finished_runs`、归档判定），
   收口成常量 + `_ACTIVE/_FINISHED` 两个集合，槽位计数与逐出**同一份口径**。

判据（缺一条这条链就是断的）：见各类文档串。全部打在**行为**上——真事件循环、真
`SwarmManager` 单例、真广度闸；member 的 `chat` 是服务商边界替身（真模型回复需要真配额）。
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from neurova.agent.swarm import reset_swarm_manager, get_swarm_manager
from tests.ast_scan import parseSource

SWARM_FILE = "neurova/agent/swarm.py"
REPO = Path(__file__).resolve().parents[3]

VOCAB = {"pending", "running", "completed", "failed"}

BUDGET_ENV = "NEUROVA_SWARM_SUBAGENT_BUDGET_SEC"


def _agent(reply="子任务报告", *, hang=False, boom=False):
    """member 替身：只替 `chat`（服务商边界），其余走 SwarmManager 真逻辑。"""
    agent = MagicMock()
    agent.config.name = "蜂群成员"

    async def chat(user_input, **kw):
        if hang:
            await asyncio.Event().wait()      # 永不返回：静默停滞的上游流
        if boom:
            raise RuntimeError("上游 5xx")
        return {"text": reply}

    agent.chat = chat
    return agent


@pytest.fixture()
def swarm():
    reset_swarm_manager()
    yield get_swarm_manager()
    reset_swarm_manager()


async def _awaitTerminal(swarm, sid, deadlineS=3.0):
    """等这条 run 落到任一终态。**判据不自己重述状态词值**（同 §6-82 那一格的教训：
    夹具/判据里抄一份词值，就会与生产各自漂开）。"""
    from neurova.agent.swarm import SUBAGENT_ACTIVE_STATUSES

    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadlineS
    while loop.time() < deadline:
        record = swarm.status(sid)
        if record.get("status") not in SUBAGENT_ACTIVE_STATUSES:
            return record
        await asyncio.sleep(0.05)
    return swarm.status(sid)


class TestTimeoutLandsTerminal:
    """判据 1/2：挂死的子任务必须有到点落终态的那一半。"""

    @pytest.mark.asyncio
    async def test_hung_chat_fails_by_budget_naming_the_cause(self, swarm, monkeypatch):
        monkeypatch.setenv(BUDGET_ENV, "0.2")
        agent = _agent(hang=True)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            spawned = await swarm.spawn(task="卡死任务", agent_id="m1", background=True)
        record = await _awaitTerminal(swarm, spawned["subagent_id"])
        assert record["status"] == "failed", (
            f"子任务挂在上游流上时没有任何东西给它落终态：读到 {record['status']!r}——"
            "它会永久占着一个派生槽")
        assert "subagent_timeout" in record["error"], record["error"]
        assert "0.2" in record["error"], (
            f"失败成因没点名预算读数，运维无从判断该调哪个数：{record['error']!r}")

    @pytest.mark.asyncio
    async def test_slots_are_reclaimed_so_the_gate_reopens(self, swarm, monkeypatch):
        """K 条最硬的那格：5 条卡死曾让蜂群整体不可用，且拒案指向永不发生的完成。"""
        monkeypatch.setenv(BUDGET_ENV, "0.3")
        agent = _agent(hang=True)
        ids = []
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            for n in range(swarm.MAX_ACTIVE_CHILDREN):
                spawned = await swarm.spawn(task=f"任务{n}", agent_id="m1", background=True)
                ids.append(spawned["subagent_id"])
            blocked = await swarm.spawn(task="第6条", agent_id="m1", background=True)
        assert blocked.get("rejected") is True
        assert blocked["rejection"]["code"] == "MAX_ACTIVE_CHILDREN"

        for sid in ids:
            record = await _awaitTerminal(swarm, sid)
            assert record["status"] == "failed", f"{sid} 没落终态：{record['status']}"

        with patch("neurova.api.endpoints.get_agent_instance", return_value=_agent()):
            reopened = await swarm.spawn(task="第6条重派", agent_id="m1", background=True)
        assert not reopened.get("rejected"), (
            "5 条卡死件都已落终态，广度闸仍拒——槽位没被真正释放")
        assert reopened["subagent_id"]

    @pytest.mark.asyncio
    async def test_real_failure_still_fails_and_success_still_completes(
            self, swarm, monkeypatch):
        """对照格：别把修复做成「全都失败」。"""
        monkeypatch.setenv(BUDGET_ENV, "5")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=_agent(boom=True)):
            bad = await swarm.spawn(task="会炸的", agent_id="m1")
        assert bad["status"] == "failed" and "上游 5xx" in bad["error"]

        with patch("neurova.api.endpoints.get_agent_instance",
                   return_value=_agent(reply="正常报告")):
            good = await swarm.spawn(task="正常的", agent_id="m1")
        assert good["status"] == "completed", good
        assert good["report"] == "正常报告"


class TestCancellationIsTerminalButNotSwallowed:
    """判据 3：取消要落终态，也要照常上抛——吞掉取消是教义第 2 条的禁物。"""

    @pytest.mark.asyncio
    async def test_cancel_marks_terminal_and_propagates(self, swarm, monkeypatch):
        monkeypatch.setenv(BUDGET_ENV, "30")
        agent = _agent(hang=True)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            running = asyncio.create_task(
                swarm.spawn(task="前台长跑", agent_id="m1", background=False))
            await asyncio.sleep(0.2)
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running

        records = swarm.list_all(limit=5)
        assert records, "取消后连运行记录都没了，无法归因"
        record = records[0]
        assert record["status"] == "failed", (
            f"取消把子任务永久留在 {record['status']!r}——槽位就此被占死")
        assert "subagent_cancelled" in record["error"], record["error"]
        assert not swarm.list_active(), "取消后仍被算作运行中，广度闸不会重开"


class TestBudgetIsNotASecondNumber:
    """判据 4：预算取自仓内既有那份读数，不在蜂群里另抄一个 600。"""

    def test_budget_defaults_to_the_spawn_subagent_tool_timeout(self, monkeypatch):
        from neurova.agent.swarm import SwarmManager
        from neurova.agent.tool_coordinator import get_tool_timeout

        monkeypatch.delenv(BUDGET_ENV, raising=False)
        monkeypatch.delenv("NEUROVA_SWARM_GOVERNANCE", raising=False)
        assert SwarmManager._effectiveRuntimeBudget() == get_tool_timeout("spawn_subagent"), (
            "蜂群侧自己写了一个窗口数字——工具层 600s 放弃等待、run 却能永远挂着，"
            "两份口径迟早漂开")

    def test_env_override_is_read_at_call_time(self, monkeypatch):
        from neurova.agent.swarm import SwarmManager

        monkeypatch.setenv(BUDGET_ENV, "1.5")
        assert SwarmManager._effectiveRuntimeBudget() == 1.5
        monkeypatch.setenv(BUDGET_ENV, "7")
        assert SwarmManager._effectiveRuntimeBudget() == 7.0, (
            "env 只在 import 期读一次的话，运行期调不动，判据也就测不到真分支")

    @pytest.mark.asyncio
    async def test_rejection_message_cites_the_same_budget(self, swarm, monkeypatch):
        """闸文案承诺「等待完成」时，必须把上界一并给出——否则 LLM 只能傻等。"""
        monkeypatch.setenv(BUDGET_ENV, "0.4")
        agent = _agent(hang=True)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            for n in range(swarm.MAX_ACTIVE_CHILDREN):
                await swarm.spawn(task=f"占槽{n}", agent_id="m1", background=True)
            blocked = await swarm.spawn(task="第6条", agent_id="m1", background=True)
        message = blocked["rejection"]["message"]
        assert "0.4" in message, (
            f"拒案没点名运行窗口上界：{message!r}——「请等待现有子任务完成」"
            "不给上界就等于让调用方无限等")


class TestStatusVocabularyIsDefinedOnce:
    """判据 5（教义第 6 条）：状态词值只许在 swarm.py 的常量处出现一次。"""

    def _compareOffenders(self, src: str):
        """`something.status == "running"` / `in ("pending","running")` 这类字面量比较。"""
        hits = []
        for node in ast.walk(parseSource(src)):
            if not isinstance(node, ast.Compare):
                continue
            left = node.left
            name = (left.attr if isinstance(left, ast.Attribute)
                    else left.id if isinstance(left, ast.Name) else "")
            if "status" not in name.lower():
                continue
            for comparator in node.comparators:
                strs = []
                if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                    strs = [comparator.value]
                elif isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
                    strs = [e.value for e in comparator.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                for value in strs:
                    if value in VOCAB:
                        hits.append(f"line {node.lineno}: {name} 与字面量 {value!r} 比")
        return hits

    def _defaultOffenders(self, src: str):
        """字段/变量默认值直接写词值（dataclass 那行 `status: str = "pending"` 属此类）。"""
        hits = []
        for node in ast.walk(parseSource(src)):
            target = None
            value = None
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target, value = node.target.id, node.value
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            if not target or value is None or "status" not in target.lower():
                continue
            if isinstance(value, ast.Constant) and value.value in VOCAB:
                hits.append(f"line {node.lineno}: {target} = {value.value!r}")
        return hits

    def test_no_literal_status_comparisons(self):
        src = (REPO / SWARM_FILE).read_text(encoding="utf-8")
        assert not self._compareOffenders(src), \
            f"{SWARM_FILE} 还在用字面量判状态：{self._compareOffenders(src)}"

    def test_no_literal_status_defaults(self):
        src = (REPO / SWARM_FILE).read_text(encoding="utf-8")
        assert not self._defaultOffenders(src), \
            f"{SWARM_FILE} 的状态默认值写着字面量词值：{self._defaultOffenders(src)}"

    def test_reverse_controls_prove_the_scanners_bite(self):
        """反向对照：扫不到东西 ≠ 干净，可能是在演空转（本仓老根因）。"""
        badCompare = 'def f(r):\n    return r.status in ("pending", "running")\n'
        assert self._compareOffenders(badCompare), "扫描器抓不到字面量成员测试"
        badSingle = 'def g(r):\n    return r.status == "completed"\n'
        assert self._compareOffenders(badSingle), "扫描器抓不到字面量等值比较"
        assert not self._compareOffenders(
            "def h(r):\n    return r.status in SUBAGENT_ACTIVE_STATUSES\n"), "合法形态被误伤"

        badDefault = 'class C:\n    status: str = "pending"\n'
        assert self._defaultOffenders(badDefault), "扫描器抓不到字面量状态默认值"
        assert not self._defaultOffenders(
            'class C:\n    status: str = SUBAGENT_PENDING\n'), "合法形态被误伤"

    def test_active_and_finished_sets_are_complementary(self):
        """计数与逐出共用一份口径：两个集合互斥、并起来就是整个状态域。"""
        from neurova.agent.swarm import (
            SUBAGENT_ACTIVE_STATUSES, SUBAGENT_FINISHED_STATUSES, SUBAGENT_STATUSES,
        )

        assert not (SUBAGENT_ACTIVE_STATUSES & SUBAGENT_FINISHED_STATUSES), (
            "一个状态同时算运行中与已完成——那既不会释放槽位也逐不出去，正是 K 条的死锁形态")
        assert SUBAGENT_ACTIVE_STATUSES | SUBAGENT_FINISHED_STATUSES == SUBAGENT_STATUSES
