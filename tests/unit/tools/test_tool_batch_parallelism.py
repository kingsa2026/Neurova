# -*- coding: utf-8 -*-
"""工具批次并行：能力声明单源 + 分组调度（红→绿）。

## 本片修的根因

一轮里的多个工具调用，此前由 `agent/tool_coordinator.py` 的
`_CONCURRENCY_SAFE_TOOLS`（一份**名字硬编码清单**）判定"能不能并发"，判据是
**all-or-nothing**：任一调用不在清单里 ⇒ 整轮全串行。清单只有 10 项且含两个
不存在的名字，而内置工具有 71 个 ⇒ 覆盖被钉死、且新工具（MCP / Skill /
workflow 的命名空间）永远进不来。

修法：事实下沉到**每个工具自己的声明**（装配期一处），调度侧只读声明并分组。
本文件钉住这条链的四段：声明形状 → 资格推导 → 分组调度 → 装配期一致性。

## 判据不许绕开装配点

不得把"哪些工具可并行"用 `monkeypatch` 塞进调度函数当参数——那测的是参数，
不是装配（`AGENTS.md` 教义第 3 条点名项）。故这里一律走**真实声明面**
（`_BUILTIN_SCHEMAS` 的声明位 + `ToolCoordinator` 的解析入口）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _call(index: int, name: str) -> dict:
    """构造一条 tool_call（只需 `function.name`，调度判据不碰参数）。"""
    return {"id": f"c{index}", "function": {"name": name, "arguments": "{}"}}


# ═══════════════════════════════════════════════════════════════
# 一：资格推导是三态合取（fail-closed）
# ═══════════════════════════════════════════════════════════════


class TestParallelEligibility:
    def test_undeclaredIsSerial(self):
        """缺省声明即最保守：不可并发。"""
        from neurova.core.tool_capability import ToolCapability, isParallelEligible

        assert isParallelEligible(ToolCapability()) is False

    def test_readOnlyAloneIsNotEnough(self):
        """只读不足以放行——共享外设的读就属此列（见下条）。"""
        from neurova.core.tool_capability import ToolCapability, isParallelEligible

        cap = ToolCapability(readOnly=True, concurrentSafe=True)
        assert isParallelEligible(cap) is False, (
            "readOnly 却未声明写作用域为空 ⇒ 仍不可并行（合取语义）"
        )

    def test_readOnlyRequiresNoWriteScope(self):
        """`readOnly=True` 但写作用域非空 ⇒ 不可并行（挡误声明）。"""
        from neurova.core.tool_capability import (
            ToolCapability,
            WriteScope,
            isParallelEligible,
        )

        cap = ToolCapability(
            readOnly=True,
            concurrentSafe=True,
            writeScopes=frozenset({WriteScope.SHARED}),
        )
        assert isParallelEligible(cap) is False

    def test_fullDeclarationIsEligible(self):
        from neurova.core.tool_capability import (
            ToolCapability,
            WriteScope,
            isParallelEligible,
        )

        cap = ToolCapability(
            readOnly=True,
            concurrentSafe=True,
            writeScopes=frozenset({WriteScope.NONE}),
        )
        assert isParallelEligible(cap) is True

    def test_sharedDeviceNeverEligible(self):
        """共享外设的"读"永不并行：并发会互相拿到对方设备的瞬时态。"""
        from neurova.core.tool_capability import (
            ToolCapability,
            WriteScope,
            isParallelEligible,
        )

        cap = ToolCapability(
            readOnly=True,
            concurrentSafe=True,
            writeScopes=frozenset({WriteScope.SHARED}),
        )
        assert isParallelEligible(cap) is False


# ═══════════════════════════════════════════════════════════════
# 二：分组调度（纯函数）
# ═══════════════════════════════════════════════════════════════


def _cap(readOnly=True, concurrentSafe=True, scopes=("none",)):
    from neurova.core.tool_capability import ToolCapability, WriteScope

    return ToolCapability(
        readOnly=readOnly,
        concurrentSafe=concurrentSafe,
        writeScopes=frozenset(WriteScope(s) for s in scopes),
    )


class TestBatchPlanning:
    def test_singleCallIsOneSerialBatch(self):
        from neurova.core.tool_capability import planToolBatches

        batches = planToolBatches([_call(0, "file_read")], {"file_read": _cap()}, maxParallel=4)
        assert len(batches) == 1 and batches[0].parallel is False

    def test_consecutiveEligibleCallsShareOneBatch(self):
        from neurova.core.tool_capability import planToolBatches

        calls = [_call(0, "file_read"), _call(1, "file_list")]
        caps = {"file_read": _cap(), "file_list": _cap()}
        batches = planToolBatches(calls, caps, maxParallel=4)
        assert len(batches) == 1 and batches[0].parallel is True
        assert [i for i, _ in batches[0].items] == [0, 1]

    def test_ineligibleSplitsTheBatch(self):
        """未声明项把可并发项切成两批——这正是旧判据的病灶所在。"""
        from neurova.core.tool_capability import planToolBatches

        calls = [_call(0, "web_search"), _call(1, "web_fetch"), _call(2, "file_write"),
                 _call(3, "weather"), _call(4, "calculator")]
        caps = {n: _cap() for n in ("web_search", "web_fetch", "weather", "calculator")}
        batches = planToolBatches(calls, caps, maxParallel=4)
        assert [(len(b), b.parallel) for b in batches] == [(2, True), (1, False), (2, True)]
        assert [i for b in batches for i, _ in b.items] == [0, 1, 2, 3, 4], "必须保原序"

    def test_singletonEligibleBatchIsMarkedSerial(self):
        """单项批一律标串行：此时并发与串行等价，标记必须等于实际执行形态。"""
        from neurova.core.tool_capability import planToolBatches

        calls = [_call(0, "file_write"), _call(1, "file_read"), _call(2, "file_delete")]
        batches = planToolBatches(calls, {"file_read": _cap()}, maxParallel=4)
        assert [b.parallel for b in batches] == [False, False, False]

    def test_mixedBatchKeepsEligiblePairTogether(self):
        """[读,读,写] 旧判据整轮串行（3 次），新判据 1 并行批 + 1 串行（2 次）。"""
        from neurova.core.tool_capability import planToolBatches

        calls = [_call(0, "file_read"), _call(1, "file_list"), _call(2, "file_write")]
        caps = {"file_read": _cap(), "file_list": _cap()}
        batches = planToolBatches(calls, caps, maxParallel=4)
        assert [(len(b), b.parallel) for b in batches] == [(2, True), (1, False)]

    def test_maxParallelCapsGroup(self):
        from neurova.core.tool_capability import planToolBatches

        calls = [_call(i, "file_read") for i in range(12)]
        caps = {"file_read": _cap()}
        batches = planToolBatches(calls, caps, maxParallel=4)
        assert len(batches) == 3
        assert all(b.parallel and len(b) <= 4 for b in batches)
        assert [i for b in batches for i, _ in b.items] == list(range(12))

    def test_unknownToolIsSerial(self):
        """未知工具（含 MCP/Skill/workflow 命名空间）按未声明处置 ⇒ 它自己串行，
        且不拖累相邻的已声明项。"""
        from neurova.core.tool_capability import planToolBatches

        calls = [_call(0, "mcp.srv.tool"), _call(1, "file_read"), _call(2, "file_list")]
        batches = planToolBatches(calls, {"file_read": _cap(), "file_list": _cap()},
                                  maxParallel=4)
        assert [(len(b), b.parallel) for b in batches] == [(1, False), (2, True)]

    def test_declarationOrderPreservedAcrossBatches(self):
        from neurova.core.tool_capability import planToolBatches

        calls = [_call(i, n) for i, n in enumerate(
            ["file_read", "file_write", "file_list", "file_search", "git"]
        )]
        caps = {n: _cap() for n in ("file_read", "file_list", "file_search")}
        batches = planToolBatches(calls, caps, maxParallel=4)
        order = [i for b in batches for i, _ in b.items]
        assert order == sorted(order) == list(range(5))


# ═══════════════════════════════════════════════════════════════
# 三：装配期一致性（声明面与现实咬合）
# ═══════════════════════════════════════════════════════════════


class TestDeclarationWiring:
    def test_nameListIsGone(self):
        """旧名单必须物理消失——留着就是"两边都留着加同步脚本"的反面教材。"""
        from tests import ast_scan

        hits = ast_scan.sourceRefsUnder(
            ast_scan.PRODUCTION_ROOT, hints=("_CONCURRENCY_SAFE_TOOLS",)
        )
        found = [
            (ref.path.name, lineno)
            for ref in hits
            for lineno, line in enumerate(ref.code.splitlines(), start=1)
            if "_CONCURRENCY_SAFE_TOOLS" in line
        ]
        assert not found, (
            "旧名单仍在生产侧出现（教义第 6 条：发现第二份定义就收口并删净）: "
            f"{found}"
        )

    def test_declaredToolsAreRealTools(self):
        """声明必须落在真实工具上——旧名单里的 phantom 名正是不咬合的证据。"""
        from neurova.builtin_tools import _BUILTIN_SCHEMAS, list_declared_capabilities

        declared = set(list_declared_capabilities())
        assert declared, "没有任何工具声明能力——判据空转"
        phantoms = sorted(declared - set(_BUILTIN_SCHEMAS))
        assert not phantoms, f"声明的工具名不存在（幻名）: {phantoms}"

    def test_oldEligibleNamesAreStillEligible(self):
        """旧名单的**真实**成员一项都不能丢——丢了就是静默收窄覆盖面。"""
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import isParallelEligible

        for name in (
            "calculator", "memory_search", "recall_history", "recall_context_span",
            "web_search", "web_fetch", "file_parse", "weather",
        ):
            assert isParallelEligible(resolveToolCapability(name)), (
                f"{name} 在旧名单里且语义未变，翻译后不得失去并行资格"
            )

    def test_legacyPhantomNamesAreGone(self):
        """旧名单里两个不存在的名字（get_time / time_now）不得再被声明为工具。"""
        from neurova.builtin_tools import _BUILTIN_SCHEMAS, list_declared_capabilities

        declared = set(list_declared_capabilities())
        for ghost in ("get_time", "time_now"):
            assert ghost not in _BUILTIN_SCHEMAS, f"{ghost} 不是内置工具"
            assert ghost not in declared, f"{ghost} 是幻名，不得出现在声明面"

    def test_fileReadIsDeclaredEligible(self):
        """旗舰场景"读三个文件 + 一次搜索 + 写一个文件"的可并发半边。"""
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import isParallelEligible

        for name in ("file_read", "file_list", "file_search", "get_datetime"):
            assert isParallelEligible(resolveToolCapability(name)), (
                f"{name} 是本地纯读，未声明并行资格 ⇒ 旗舰场景仍是全串行"
            )

    def test_sharedDeviceToolsStaySerial(self):
        """共享外设的读不得被声明为可并发（§4 的 computer_screenshot 反例）。"""
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import isParallelEligible

        for name in ("computer_screenshot", "computer_dom_snapshot", "computer_som_snapshot",
                     "browser_read", "browser_dom_read", "canvas_read", "canvas_list_nodes"):
            if resolveToolCapability(name) is None:
                continue
            assert not isParallelEligible(resolveToolCapability(name)), (
                f"{name} 读的是共享外设的瞬时态，并发会互相拿到对方的画面"
            )

    def test_writeToolsStaySerial(self):
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import isParallelEligible

        for name in ("file_write", "file_delete", "git", "run_code", "exec_command",
                     "write_stdin", "computer_shell", "spawn_subagent"):
            cap = resolveToolCapability(name)
            if cap is None:
                continue
            assert not isParallelEligible(cap), f"{name} 有副作用，不得声明为可并发"

    def test_everyWriteScopeHasAProducer(self):
        """每个 `WriteScope` 取值都必须有真实生产者——否则就是只写不读的断点。

        枚举里没人声明的取值 = 第二份"写出来无人读"的字段（协作红线点名的断点
        形态）。故反向钉住：枚举取值集合必须**恰等于**声明面实际用到的取值集合。
        """
        from neurova.builtin_tools import _BUILTIN_SCHEMAS
        from neurova.core.tool_capability import WriteScope

        used = set()
        for name, schema in _BUILTIN_SCHEMAS.items():
            raw = schema.get("capability")
            if isinstance(raw, dict) and isinstance(raw.get("writeScopes"), (list, tuple)):
                used.update(str(item) for item in raw["writeScopes"])
        declared = {scope.value for scope in WriteScope}
        assert used, "声明面没有任何写作用域取值——判据空转"
        assert used <= declared, f"声明面出现未登记的作用域：{sorted(used - declared)}"
        assert declared <= used, (
            f"枚举里有取值无生产者（只写不读的断点）：{sorted(declared - used)}"
        )

    def test_sharedDeviceFamilyIsDeclaredSerial(self):
        """共享外设读取族逐名钉住：声明了也必须推导为不可并行。

        §4 的反例（`computer_screenshot` 语义只读、却因共享设备而必须串行）
        不能只写在文档里——逐名钉住，覆盖面才不靠人记。
        """
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import isParallelEligible

        family = (
            "computer_screenshot", "computer_dom_snapshot", "computer_som_snapshot",
            "browser_read", "browser_dom_read", "canvas_read",
        )
        for name in family:
            cap = resolveToolCapability(name)
            assert cap is not None, f"{name} 未声明能力——覆盖缺口会静默退回串行，无人知"
            assert not isParallelEligible(cap), (
                f"{name} 读共享外设的瞬时态，并发会互相干扰，却被判为可并行"
            )

    def test_unknownToolResolvesToNone(self):
        from neurova.agent.tool_coordinator import resolveToolCapability

        assert resolveToolCapability("totally_unknown_tool") is None
        assert resolveToolCapability("mcp.some.server.tool") is None
        assert resolveToolCapability("") is None


# ═══════════════════════════════════════════════════════════════
# 三之二：逐工具判定（M3）——每个 verdict 都要有依据，拒绝也要点名
# ═══════════════════════════════════════════════════════════════


class TestPerToolVerdictsAreArgued:
    """覆盖缺口逐名收口：**能并行**与**判为串行**的都要落声明，不许沉默。

    覆盖率的敌人不是"慢"，是"没人声明"——未声明与"论证过应当串行"在调度上
    同形（都串行），在维护上却是两件事：前者是待办、后者是结论。故本类同时
    钉住两侧：拿得到并行的（收益面）与**明确判为串行且写明成因**的（否证面）。
    """

    def test_networkReadFamilyIsEligible(self):
        """无副作用远端读：GET/独立子进程，不落盘、不碰共享态。"""
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import isParallelEligible

        for name in ("rss_read", "v2ex_hot", "bilibili_search"):
            cap = resolveToolCapability(name)
            assert cap is not None, f"{name} 未声明能力——覆盖缺口会静默退回串行，无人知"
            assert isParallelEligible(cap), f"{name} 是无副作用远端读，却被判为串行"

    def test_localMetadataReadFamilyIsEligible(self):
        """本地只读枚举/打分：读注册表、读运行记录、纯文本打分。"""
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import isParallelEligible

        for name in ("list_agents", "subagent_status", "emotion_analyze"):
            cap = resolveToolCapability(name)
            assert cap is not None, f"{name} 未声明能力——覆盖缺口会静默退回串行，无人知"
            assert isParallelEligible(cap), f"{name} 是本地只读，却被判为串行"

    def test_refusalsAreDeclaredWithSharedScopeAndNamedCause(self):
        """拒绝并行不等于不声明：三者作用域落在共享态，逐名钉住。

        - `social_search`：取凭据经 `SecretStore.get_secret` 回写访问元数据与
          访问日志（共享凭据桶）；
        - `youtube_transcript`：yt-dlp 的 YouTube extractor 会把播放器数据写进
          固定的进程外缓存根（共享且不在本仓可控范围）；
        - `discover_skills`：检索面只读，但会懒建并落盘技能向量缓存
          （模块级 `_VECTOR_CACHES` + embeddings.json）。

        三者的共同点：**语义只读、执行会动共享态**——正是 §4 那条"一个布尔字段
        表达不了两件事"的真实落点，故用作用域表达，而不是把它们留在未声明里。
        """
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import WriteScope, isParallelEligible

        for name in ("social_search", "youtube_transcript", "discover_skills"):
            cap = resolveToolCapability(name)
            assert cap is not None, f"{name} 未声明——拒绝也要点名，沉默与结论同形"
            assert not isParallelEligible(cap), f"{name} 会动共享态，却被判为可并行"
            assert WriteScope.SHARED in set(cap.writeScopes), (
                f"{name} 的拒绝理由必须落在共享作用域上（成因要可读，不是随笔一个 False）"
            )

    def test_sharedScopeDeclarationDoesNotLeakIntoEligibleSet(self):
        """反向控制：共享作用域的声明**不得**让工具挤进并行资格集合。"""
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import WriteScope, isParallelEligible

        cap = resolveToolCapability("youtube_transcript")
        assert cap is not None and cap.readOnly and cap.concurrentSafe
        assert set(cap.writeScopes) == {WriteScope.SHARED}
        assert not isParallelEligible(cap), (
            "两个布尔位都放行时，作用域合取必须仍然把共享态挡在门外（教义第 1 条："
            "不得在报错处兜底，判据要在上游一次判死）"
        )


# ═══════════════════════════════════════════════════════════════
# 四：并行上限是单源配置键（缺陷 E）
# ═══════════════════════════════════════════════════════════════


class TestParallelBudgetIsSingleSource:
    def test_keyExistsInDefaults(self):
        from neurova.security.agent_limits_settings import DEFAULTS

        assert "max_parallel_tools" in DEFAULTS, (
            "并行上限必须落在既有配置单源（agent_limits_settings），不得新造平行体系"
        )

    def test_effectiveLimitsClampsToLegalRange(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_AGENT_LIMITS_SETTINGS", str(tmp_path / "limits.json"))
        from neurova.security import agent_limits_settings as limits

        limits.save_agent_limits({"max_parallel_tools": 9999})
        assert limits.get_effective_limits()["max_parallel_tools"] == limits.MAX_PARALLEL_TOOLS
        limits.save_agent_limits({"max_parallel_tools": 0})
        assert limits.get_effective_limits()["max_parallel_tools"] == limits.MIN_PARALLEL_TOOLS

    def test_envOverride(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_AGENT_LIMITS_SETTINGS", str(tmp_path / "limits.json"))
        monkeypatch.setenv("NEUROVA_AGENT_MAX_PARALLEL_TOOLS", "7")
        from neurova.security import agent_limits_settings as limits

        assert limits.get_effective_limits()["max_parallel_tools"] == 7

    def test_ledgerRegistersTheKey(self):
        """阈值型约束必须入册且与实测咬合（人改台账迎合即报红）。"""
        from scripts.ci import tool_loop_deadline_ledger as ledger

        rows = {str(row["symbol"]): row for row in ledger.facts()}
        assert "max_parallel_tools" in rows, "并行上限未登记进死线台账"
        problems = ledger.reconcile()
        for key, items in problems.items():
            assert not items, f"台账对账失败 [{key}]：{items}"


# ═══════════════════════════════════════════════════════════════
# 五：并行化前必须排除的危害（逐条实测留证）
# ═══════════════════════════════════════════════════════════════


class TestHazardsExcluded:
    """这几条是"并行前必须逐条排除"的清单，此前的并行路径也没测过。"""

    @pytest.mark.asyncio
    async def test_multipleBackgroundConversionsInOneBatch(self):
        """同批两项都超时转后台 ⇒ `_pending_hints` 收齐两条、不互相覆盖。

        改前 `handle_tool_calls` 已是并行（全声明批），但"一批内多项同时转后台"
        这条路径**从未有判据**——hints 汇聚是并行化的真实新增风险点。
        """
        import asyncio

        from neurova.agent.tool_coordinator import ToolCoordinator

        coordinator = ToolCoordinator()

        async def slow(tag):
            await asyncio.sleep(0.25)
            return {"ok": tag}

        first, second = await asyncio.gather(
            coordinator.run_with_timeout("web_search", lambda: slow("a"), timeout=0.05),
            coordinator.run_with_timeout("web_fetch", lambda: slow("b"), timeout=0.05),
        )
        assert first["status"] == "background" and second["status"] == "background"
        assert first["task_id"] != second["task_id"]

        await asyncio.sleep(0.4)  # 等两个后台观察者投递完
        hints = coordinator.pop_pending_hints()
        assert len(hints) == 2, f"hints 汇聚丢条（收到 {len(hints)}）"
        assert sorted(h.get("tool_name") for h in hints) == ["web_fetch", "web_search"]

    @pytest.mark.asyncio
    async def test_contextVarSharingSurvivesGather(self):
        """并行批内累加轮级工具耗时后，父上下文读到**合计**。

        钉住既有正确范式（`TurnElapsedAccumulator` 按引用跨任务共享）不被
        新调度路径破坏：不可变 float 的 `set()` 在 `gather` 子任务里落不到
        父上下文，那会在并行批下静默丢掉耗时读数。
        """
        import asyncio

        from neurova.core import turn_context

        turn_context.reset_turn_tool_elapsed()

        async def accumulate(seconds):
            turn_context.add_turn_tool_elapsed(seconds)

        await asyncio.gather(*(accumulate(0.25) for _ in range(3)))
        assert turn_context.get_turn_tool_elapsed() == pytest.approx(0.75)
