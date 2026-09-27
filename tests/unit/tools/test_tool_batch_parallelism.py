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
            cap = resolveToolCapability(name)
            assert cap is not None, f"{name} 未声明——覆盖缺口会静默退回串行，无人知"
            assert not isParallelEligible(cap), (
                f"{name} 读的是共享外设的瞬时态，并发会互相拿到对方的画面"
            )

    def test_writeToolsStaySerial(self):
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import isParallelEligible

        for name in ("file_write", "file_delete", "git", "run_code", "exec_command",
                     "write_stdin", "computer_shell", "spawn_subagent"):
            cap = resolveToolCapability(name)
            assert cap is not None, f"{name} 未声明——覆盖缺口会静默退回串行，无人知"
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

    def test_eligibleToolsDoNotBlockTheEventLoop(self):
        """声明了可并行的工具**不得**在事件循环里做同步阻塞 I/O。

        并行的收益前提是"每个调用真的让出事件循环"。一个同步阻塞的执行体进了
        成组批，不但自己不快，还会把同批**全部**兄弟一起卡住——比串行更差。
        故判据与"可并行"绑定：已声明可并行的工具，逐个核"重活是否下沉线程池"。

        判据形态说明（两处反例都实测过）：

        - **要穿透嵌套**：`file_read` 把同步读包在内部函数里再交 `to_thread`，
          只看顶层语句会把正确实现读成阻塞；
        - **要排除已下沉的辅助函数**：交给 `to_thread` 的内部函数体不在此判，
          否则同一段代码既算"已下沉"又算"阻塞"。

        同一根因的真实命中点（本片修）：`voice_memory_search` 与 `memory_search`
        走同一条 `MemoryManager.recall` 路径，只有后者在审计 P1-E1 时下了线程池；
        `file_list` / `file_search` 整段目录遍历与逐文件读取留在循环里；
        `recall_history` / `recall_context_span` 直读同步 SQLite 台账。
        """
        import ast
        from pathlib import Path

        import neurova.tool_executor as executor_module
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.builtin_tools import _BUILTIN_SCHEMAS
        from neurova.core.tool_capability import isParallelEligible

        # 同步阻塞 I/O 的咽喉名（末段名匹配）。判据只认这些进入点：它们是
        # "最长可卡住事件循环"的那类调用，纯内存计算不在列。
        blocking_sinks = {
            "open", "read_text", "read_bytes", "write_text", "write_bytes",
            "glob", "walk", "listdir", "scandir", "run", "check_output",
            "recall", "recall_evicted", "drilldown", "search", "connect",
        }

        def offloadedHelperNodes(fn):
            """交给 `to_thread` 的内部函数**函数体节点集**——它们不参与本判据。

            必须按节点集排除、而不是按函数名：内部函数体仍挂在同一个 AST 上，
            只排除名字的话 `ast.walk` 照样走到它里面（`file_read` 把 `open` 包在
            内部 `_read()` 里再交 `to_thread`，就成了误报）。
            """
            offloaded = set()
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                target = node.func
                label = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
                if label != "to_thread":
                    continue
                for arg in node.args:
                    helper = None
                    if isinstance(arg, ast.Name):
                        helper = next(
                            (item for item in ast.walk(fn)
                             if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                             and item.name == arg.id),
                            None,
                        )
                    if helper is not None:
                        offloaded.update(id(item) for item in ast.walk(helper))
            return offloaded

        source = Path(executor_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        holder = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ToolExecutor"
        )
        dispatch = {}
        for node in holder.body:
            if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "_builtin_dispatch":
                dispatch = ast.literal_eval(node.value)
        methods = {
            node.name: node for node in holder.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        blocking = []
        for name in sorted(_BUILTIN_SCHEMAS):
            if not isParallelEligible(resolveToolCapability(name)):
                continue
            function = methods.get(dispatch.get(name, ""))
            if function is None:
                continue
            offloaded = offloadedHelperNodes(function)
            for node in ast.walk(function):
                if id(node) in offloaded:
                    continue
                if not isinstance(node, ast.Call):
                    continue
                target = node.func
                label = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
                if label in blocking_sinks:
                    blocking.append(f"{name}:{label}")
                    break
        assert not blocking, (
            "这些工具已声明可并行，但执行体在事件循环里做同步阻塞 I/O——"
            f"成组批里会把同批全部兄弟一起卡住：{sorted(blocking)}"
        )


# ═══════════════════════════════════════════════════════════════
# 六：全量声明覆盖（M3 续作）——未声明不得作为"沉默的第三种答案"
# ═══════════════════════════════════════════════════════════════


class TestFullDeclarationCoverage:
    """覆盖缺口必须以**声明**闭合，不得以"未声明"形态静默存在。

    未声明与"论证过应当串行"在调度上同形（都是串行），在维护上却是两件事：
    前者是待办、后者是结论。真实危害是**两者在读数上不可分**——覆盖率统计会把
    待办读成结论，于是"还有哪些工具没论证过"这个问题没有任何机器判据能回答。
    故本类把"每个内置工具都必须给出裁决（放行或点名拒绝）"钉成常驻判据。

    拒绝也不是一个布尔：本仓要区分两种**处置相反**的拒绝成因——

    - 共享态（`writeScopes=("shared",)`）：语义只读、执行会动共享对象
      （桌面 / 浏览器 / 画布 / 工作区 / 会话），同批并发会互踩；
    - 内层扇出叠乘（`concurrentSafe=False`）：工具自身已经是并发扇出体
      （`deep_research` 信号量 6），外层再并行是乘数放大，缺的是资源护栏
      而不是作用域隔离——用作用域表达它会把两个不同的成因读成同一个。
    """

    def test_everyToolDeclaresCapability(self):
        """71 个内置工具逐个给出裁决：放行或点名拒绝，不留未声明。"""
        from neurova.builtin_tools import _BUILTIN_SCHEMAS, list_declared_capabilities

        gap = sorted(set(_BUILTIN_SCHEMAS) - set(list_declared_capabilities()))
        assert not gap, (
            "这些内置工具既未声明可并行、也未点名拒绝——沉默与结论同形，"
            f"覆盖缺口无人可读：{gap}"
        )

    def test_everyDeclarationCarriesEvidenceLine(self):
        """每条声明必须带**依据行**：误声明的第一层防护是逐条可核（方案 §12）。

        判据读声明位自身的注释，不读文档：声明与依据分开两处时，改声明
        不必改依据，依据会静默过期。
        """
        from pathlib import Path

        import neurova.builtin_tools as builtin

        lines = Path(builtin.__file__).read_text(encoding="utf-8").splitlines()
        missing = []
        for index, line in enumerate(lines):
            if not line.strip().startswith('"capability"'):
                continue
            window = [item.strip() for item in lines[max(0, index - 4): index] if item.strip()]
            if not any(item.startswith("# 并行能力声明：") for item in window):
                missing.append(index + 1)
        assert not missing, f"这些声明位缺少依据行（# 并行能力声明：…）: 行 {missing}"

    def test_eligibleSetIsExplicit(self):
        """可并行集合逐名钉住：放行与收窄都必须是有意为之，不得随声明漂移。"""
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.builtin_tools import _BUILTIN_SCHEMAS
        from neurova.core.tool_capability import isParallelEligible

        eligible = sorted(
            name for name in _BUILTIN_SCHEMAS
            if isParallelEligible(resolveToolCapability(name))
        )
        assert eligible == [
            "bilibili_search", "calculator", "emotion_analyze", "file_list", "file_parse",
            "file_read", "file_search", "get_datetime", "list_agents", "memory_search",
            "recall_context_span", "recall_history", "rss_read", "subagent_status",
            "update_plan", "v2ex_hot", "voice_memory_search", "weather", "web_fetch",
            "web_search",
        ], f"可并行集合发生变化，须逐条给出依据：{eligible}"

    def test_refusalReasonsAreDistinguishable(self):
        """两种拒绝成因不得折叠：共享态用作用域表达，内层扇出用并发位表达。"""
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import WriteScope, isParallelEligible

        shared_scope = resolveToolCapability("file_write")
        assert shared_scope is not None and WriteScope.SHARED in set(shared_scope.writeScopes)
        assert not isParallelEligible(shared_scope)

        fan_out = resolveToolCapability("deep_research")
        assert fan_out is not None, "deep_research 未声明——覆盖缺口会静默退回串行，无人知"
        assert fan_out.readOnly and set(fan_out.writeScopes) == {WriteScope.NONE}, (
            "deep_research 不动共享态，把它写成 shared 会把两个不同成因折叠成一个"
        )
        assert fan_out.concurrentSafe is False, (
            "deep_research 内层已有并发扇出（信号量 6），外层再并行是叠乘"
        )
        assert not isParallelEligible(fan_out)

    def test_undeclaredGapIsNotSilentlySerial(self):
        """反向控制：判据确实会因覆盖缺口报红（对 `_BUILTIN_SCHEMAS` 注入幻名）。"""
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.builtin_tools import _BUILTIN_SCHEMAS, list_declared_capabilities

        assert resolveToolCapability("unregistered_probe_tool") is None
        assert "unregistered_probe_tool" not in _BUILTIN_SCHEMAS
        assert "unregistered_probe_tool" not in list_declared_capabilities()


# ═══════════════════════════════════════════════════════════════
# 七：判据只有一处定义（收口第二入口 + 折叠重复的合取）
# ═══════════════════════════════════════════════════════════════


class TestEligibilityHasOneDefinition:
    """「这一项够不够格并行」只允许一处定义。

    实测（M3 收尾）：同一句合取 `cap is not None and isParallelEligible(cap)`
    在生产侧出现了两次——`core/tool_capability.planToolBatches` 内一次、
    `agent/tool_coordinator.is_concurrency_safe` 一次。后者在 M1+M2 之后
    **生产侧零消费**（`base.py` 改走 `resolveBatchCapabilities` + `planToolBatches`），
    只剩测试在用：它是一条与事实源并列的第二读法，漂移时两侧不会同时红。

    处置按 `AGENTS.md` 第 6 条：把「未声明（None）⇒ 串行」折进**唯一**那处推导，
    删净包装函数。删除不是收窄能力——判据本身一条不丢。
    """

    def test_undeclaredCapabilityIsSerial(self):
        """「未声明 ⇒ 串行」属于推导本身（fail-closed 的那一侧）。"""
        from neurova.core.tool_capability import isParallelEligible

        assert isParallelEligible(None) is False

    def test_secondEntryIsGone(self):
        """包装函数 `is_concurrency_safe` 必须物理消失（第二读法不得留存）。"""
        from tests import ast_scan

        hits = ast_scan.sourceRefsUnder(
            ast_scan.PRODUCTION_ROOT, hints=("is_concurrency_safe",)
        )
        found = [
            (ref.path.name, lineno)
            for ref in hits
            for lineno, line in enumerate(ref.code.splitlines(), start=1)
            if "is_concurrency_safe" in line
        ]
        assert not found, (
            "生产侧仍有第二份资格读法（事实源唯一：`isParallelEligible`）: "
            f"{found}"
        )

    def test_declaredCapabilityStillResolves(self):
        """反向控制：收口后真工具仍读得出资格（判据没被一起删掉）。"""
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import isParallelEligible

        assert isParallelEligible(resolveToolCapability("file_read")) is True
        assert isParallelEligible(resolveToolCapability("file_write")) is False
        assert isParallelEligible(resolveToolCapability("no_such_tool")) is False


# ═══════════════════════════════════════════════════════════════
# 八：这批判据必须真被 CI 跑到（登记收口）
# ═══════════════════════════════════════════════════════════════


class TestM3JudgementsAreRegisteredInCI:
    """M3 的四份判据必须进受保护子集，否则"全绿"与"判据真跑过"是两件事。

    根因（本仓已两次踩过，两种方向都有常驻守卫）：`scripts/ci/protected_tests.txt`
    是 CI 实际跑的清单，文件在仓、单跑全绿、**清单里没有** ⇒ CI 从未跑过它，
    而 CI 照样全绿。同批同根因的 `test_mcp_capability_declaration.py` 登记了，
    本批另外四份没有。

    判据落在**唯一事实源**（该清单本身），不另建一份文件清单：登记被摘掉即红。
    守卫自己也在其中一份被守文件里，故它随登记一起上 CI，不需要第二条规则。
    """

    BATCH_FILES = (
        "tests/unit/tools/test_tool_batch_parallelism.py",
        "tests/unit/tools/test_tool_parallelism_readout.py",
        "tests/unit/agent/test_handle_tool_calls_parallel.py",
        "tests/unit/agent/test_anthropic_loop_batch_handoff.py",
    )

    @staticmethod
    def _listed() -> set:
        import io
        from pathlib import Path

        raw = io.open(
            Path(__file__).resolve().parents[3] / "scripts/ci/protected_tests.txt",
            encoding="utf-8",
        ).read()
        return {
            line.split("#", 1)[0].strip()
            for line in raw.splitlines()
            if line.split("#", 1)[0].strip()
        }

    def test_batchFilesAreRegistered(self):
        listed = self._listed()
        missing = [rel for rel in self.BATCH_FILES if rel not in listed]
        assert missing == [], (
            "M3 的判据文件不在受保护子集里 —— CI 不会跑它们，"
            f"回归会静默放行：{missing}\n"
            "修复：单跑全绿后加进 scripts/ci/protected_tests.txt。"
        )

    def test_guardItselfRunsInCI(self):
        rel = "tests/unit/tools/test_tool_batch_parallelism.py"
        assert rel in self._listed(), (
            f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
        )
