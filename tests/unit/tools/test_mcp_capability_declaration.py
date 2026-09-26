# -*- coding: utf-8 -*-
"""MCP 注册点的并行能力声明通道（Issue #271 的 M4 片，红→绿）。

## 本片修的根因（在上游，不在报错处）

上一片（commit `63cfa177`）把并行资格从"一份名字硬编码清单"换成"读工具自己的
声明"，但**只落了内置工具这一条注册路径**：MCP / Skill / workflow 三条命名空间
被记为"通道打开、注册点接线留后续片"。

于是运行期留着一条真实断链：`resolveToolCapability("mcp.srv.tool")` 恒 `None`
⇒ 多路 MCP 检索（本就最该并发的场景）**必然整轮串行**，且第三方 server 即便
在配置里声明了只读并发，也**没有任何一处**能把它翻成本仓的声明——`mcp_config`
的未知键显式拒绝会把声明位当场拒掉。这不是"少了个优化"，是**封闭性缺陷**：
能力无法由提供方声明，新 server 永远进不来。

## 修法纪律（为什么不是"在报错处补个默认值"）

不得在解析处按名字前缀猜资格（那是把清单换个形态重造一遍）。落点是两处根因：

1. **声明位**：MCP 工具的 schema 由第三方 server 提供、本仓改不了，故它的
   声明位落在**本仓侧的 server 配置**（`tool_capabilities`）——即"每个提供方
   自己的声明处"，不是集中一份大名单。
2. **解析口径**：内置侧与 MCP 侧必须**共用同一处**声明解析（形态非法一律
   按未声明处置）。两处各写一遍就是第二份定义，正是本片要收掉的东西。

缺省仍是串行（fail-closed：向第三方 server 的信任不该默认给，方案 D-4）。

## 判据不许绕开装配点

不得用 `monkeypatch` 把声明塞进解析函数当参数——那测的是参数不是装配
（`AGENTS.md` 教义第 3 条点名项）。故这里一律走真实入口：
`validate_mcp_server_config`（配置声明位，含持久化副本）+ 真实 Manager 隔离目录
+ `resolveToolCapability` / `resolveBatchCapabilities`（解析入口）
+ `planToolBatches`（分组调度），端到端跑一遍。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_ELIGIBLE = {"readOnly": True, "concurrentSafe": True, "writeScopes": ["none"]}
_SHARED_READ = {"readOnly": True, "concurrentSafe": True, "writeScopes": ["shared"]}


def _call(index: int, name: str) -> dict:
    """构造一条 tool_call（调度判据只碰 `function.name`）。"""
    return {"id": f"c{index}", "function": {"name": name, "arguments": "{}"}}


@pytest.fixture
def iso_manager(monkeypatch, tmp_path):
    """隔离配置落点：真实 `SharedConfigManager` 指向 tmp_path。"""
    import neurova.shared_config as sc

    manager = sc.SharedConfigManager(tmp_path / "cfg.json")
    monkeypatch.setattr(sc, "get_shared_config_manager", lambda: manager)
    yield manager
    sc.reset_shared_config_manager()


def _register(manager, server_id="srv", capabilities=None, tools=None):
    """经真实校验入口落一份 server 配置（走 Manager，不手改私有字段）。"""
    from neurova.tool_layers.mcp_config import validate_mcp_server_config

    config = validate_mcp_server_config({
        "id": server_id,
        "command": "python",
        "tool_capabilities": capabilities or {},
    })
    assert manager.add_mcp_server(config) is True
    return config


# ═══════════════════════════════════════════════════════════════
# 一：声明位必须进得了配置（此前会被未知键门当场拒绝）
# ═══════════════════════════════════════════════════════════════


class TestDeclarationSlotExists:
    def test_configKeepsDeclarations(self):
        """声明位必须进允许键集**且**落在归一化副本上。

        只加允许键而不落归一化输出，声明会在校验那一刻被静默丢弃——
        写了没人读的断点（协作红线点名形态）。
        """
        from neurova.tool_layers.mcp_config import validate_mcp_server_config

        cfg = validate_mcp_server_config({
            "id": "s",
            "command": "python",
            "tool_capabilities": {"read_file": dict(_ELIGIBLE)},
        })
        assert cfg["tool_capabilities"] == {"read_file": dict(_ELIGIBLE)}

    def test_absentSlotDefaultsToEmpty(self):
        """未声明 = 空表（不是 None）——读侧不必再分一个分支。"""
        from neurova.tool_layers.mcp_config import validate_mcp_server_config

        cfg = validate_mcp_server_config({"id": "s", "command": "python"})
        assert cfg["tool_capabilities"] == {}

    def test_malformedSlotRejectedWithFieldName(self):
        """形态非法在**入口**拒绝并指名字段（与未知键同一纪律，不静默丢弃）。"""
        from neurova.tool_layers.mcp_config import validate_mcp_server_config

        with pytest.raises(ValueError, match="tool_capabilities"):
            validate_mcp_server_config({
                "id": "s", "command": "python", "tool_capabilities": ["read_file"],
            })
        with pytest.raises(ValueError, match="tool_capabilities"):
            validate_mcp_server_config({
                "id": "s", "command": "python", "tool_capabilities": {"t": "yes"},
            })

    def test_declarationsSurvivePersistence(self, iso_manager):
        """持久化往返不丢声明——bootstrap 从配置重读，丢了就是接线断在中途。"""
        _register(iso_manager, "srv", {"read_file": dict(_ELIGIBLE)})
        stored = iso_manager.get_mcp_server("srv")
        assert stored["tool_capabilities"] == {"read_file": dict(_ELIGIBLE)}


# ═══════════════════════════════════════════════════════════════
# 二：解析口径是**同一处**（内置侧与 MCP 侧共用）
# ═══════════════════════════════════════════════════════════════


class TestParsingIsSingleSource:
    def test_builtinSideStillResolvesThroughSharedParser(self):
        """收口不得改变内置侧行为：既有声明工具逐条仍可解析。"""
        from neurova.builtin_tools import get_builtin_tool_capability
        from neurova.core.tool_capability import isParallelEligible

        for name in ("file_read", "web_search", "calculator", "get_datetime"):
            cap = get_builtin_tool_capability(name)
            assert cap is not None and isParallelEligible(cap), name

    def test_sharedDeviceStillSerialAfterConvergence(self):
        """共享外设读取族收口后仍是串行（合取判据未被收口改松）。"""
        from neurova.builtin_tools import get_builtin_tool_capability
        from neurova.core.tool_capability import isParallelEligible

        for name in ("computer_screenshot", "browser_read", "canvas_read"):
            cap = get_builtin_tool_capability(name)
            assert cap is not None and not isParallelEligible(cap), name

    def test_bothSidesAgreeOnMalformedDeclarations(self):
        """同一份非法声明，内置侧与 MCP 侧必须给出同一个答案（收口的判据）。

        两侧各写一遍解析时，这条最容易分叉——一侧拒、一侧采信，
        就等于给同一种输入两个事实。
        """
        from neurova.core.tool_capability import parseToolCapability

        for bad in (
            None,
            "yes",
            [],
            {},
            {"readOnly": "yes"},
            {"readOnly": True, "concurrentSafe": True},
            {"readOnly": True, "concurrentSafe": True, "writeScopes": ()},
            {"readOnly": True, "concurrentSafe": True, "writeScopes": ["nope"]},
            {"readOnly": True, "concurrentSafe": True, "writeScopes": []},
        ):
            assert parseToolCapability(bad) is None, f"非法声明被采信: {bad!r}"


# ═══════════════════════════════════════════════════════════════
# 三：`mcp.{server}.{tool}` 解析入口真的读得到声明
# ═══════════════════════════════════════════════════════════════


class TestMcpResolution:
    def test_declaredMcpToolBecomesEligible(self, iso_manager):
        """旗舰场景：配了并发声明的 MCP 只读工具，经命名空间名解析为可并行。"""
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import isParallelEligible

        _register(iso_manager, "search", {"query": dict(_ELIGIBLE)})
        cap = resolveToolCapability("mcp.search.query")
        assert cap is not None, "MCP 命名空间名解析不到声明——通道仍未接线"
        assert isParallelEligible(cap)

    def test_undeclaredMcpToolStaysSerial(self, iso_manager):
        """未声明的 MCP 工具仍是串行（fail-closed；D-4 的信任不该默认给）。"""
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import isParallelEligible

        _register(iso_manager, "search", {"query": dict(_ELIGIBLE)})
        assert resolveToolCapability("mcp.search.other") is None
        assert resolveToolCapability("mcp.unregistered.query") is None
        cap = resolveToolCapability("mcp.search.other")
        assert cap is None or not isParallelEligible(cap)

    def test_sharedScopeDeclarationStaysSerial(self, iso_manager):
        """声明了只读但作用域是共享：MCP 侧仍不得并行（合取在 MCP 通道同样生效）。"""
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import isParallelEligible

        _register(iso_manager, "browser", {"snap": dict(_SHARED_READ)})
        cap = resolveToolCapability("mcp.browser.snap")
        assert cap is not None and not isParallelEligible(cap), (
            "共享作用域的 MCP 工具被放开并行——合取在 MCP 通道上没生效"
        )

    def test_bareNameDoesNotBorrowDeclaration(self, iso_manager):
        """裸名不得借用 MCP 声明。

        MCP 工具在工具面上有裸名别名（无冲突时注册），但**调度侧只认命名空间名**
        ——裸名可能与内置/Skill 同名，按裸名取声明等于让第三方 server 的声明
        覆盖本仓工具。故裸名一律走各自来源，MCP 声明只对 `mcp.{server}.{tool}` 生效。
        """
        from neurova.agent.tool_coordinator import resolveToolCapability

        _register(iso_manager, "search", {"file_read": dict(_ELIGIBLE)})
        builtin = resolveToolCapability("file_read")
        assert builtin is not None, "内置声明被 MCP 声明挤掉"
        assert resolveToolCapability("mcp.search.file_read") is not None, (
            "命名空间名解析不到（前置条件未成立，本用例的对照失去意义）"
        )

    def test_batchResolverCoversMcp(self, iso_manager):
        """批量解析入口（调度侧唯一取数口）也必须覆盖 MCP。"""
        from neurova.agent.tool_coordinator import resolveBatchCapabilities

        _register(iso_manager, "search", {"query": dict(_ELIGIBLE)})
        caps = resolveBatchCapabilities([
            _call(0, "mcp.search.query"),
            _call(1, "mcp.search.nope"),
            _call(2, "file_read"),
        ])
        assert caps["mcp.search.query"] is not None
        assert caps["mcp.search.nope"] is None
        assert caps["file_read"] is not None

    def test_unknownNamespaceShapesResolveToNone(self, iso_manager):
        """名字形态不完整/前缀不符一律 None（不猜、不部分匹配）。"""
        from neurova.agent.tool_coordinator import resolveToolCapability

        _register(iso_manager, "search", {"query": dict(_ELIGIBLE)})
        for name in ("mcp.search", "mcp..query", "mcp.qsearch.query", "MCP.search.query"):
            assert resolveToolCapability(name) is None, name


# ═══════════════════════════════════════════════════════════════
# 四：分组调度真按 MCP 声明走（端到端，不只看解析函数）
# ═══════════════════════════════════════════════════════════════


class TestGroupingUsesMcpDeclarations:
    def test_mcpBatchRegroupsAndStaysOrdered(self, iso_manager):
        """三路 MCP 检索 + 一个写工具：改前整轮串行，改后并发组 + 串行项。

        保序不因分组改变：回装仍按原下标（前端 call/result 相邻配对契约）。
        """
        from neurova.agent.tool_coordinator import resolveBatchCapabilities
        from neurova.core.tool_capability import planToolBatches

        _register(iso_manager, "search", {
            "q1": dict(_ELIGIBLE), "q2": dict(_ELIGIBLE), "q3": dict(_ELIGIBLE),
        })
        calls = [
            _call(0, "mcp.search.q1"),
            _call(1, "mcp.search.q2"),
            _call(2, "mcp.search.q3"),
            _call(3, "file_write"),
        ]
        batches = planToolBatches(
            calls, resolveBatchCapabilities(calls), maxParallel=4
        )
        assert [batch.parallel for batch in batches] == [True, False], (
            f"批次形态不符（{[(len(b), b.parallel) for b in batches]}）"
        )
        assert len(batches[0]) == 3, "三路已声明 MCP 检索未合成一批"
        order = [index for batch in batches for index, _ in batch.items]
        assert order == [0, 1, 2, 3], f"回装下标被分组打乱: {order}"

    def test_maxParallelStillCapsMcpGroup(self, iso_manager):
        """单源上限对 MCP 组同样生效（缺陷 E 的护栏不得被新通道绕过）。"""
        from neurova.agent.tool_coordinator import resolveBatchCapabilities
        from neurova.core.tool_capability import planToolBatches

        _register(iso_manager, "search", {
            f"q{i}": dict(_ELIGIBLE) for i in range(6)
        })
        calls = [_call(i, f"mcp.search.q{i}") for i in range(6)]
        batches = planToolBatches(
            calls, resolveBatchCapabilities(calls), maxParallel=4
        )
        assert [len(b) for b in batches] == [4, 2], (
            f"单源上限未截断 MCP 组: {[len(b) for b in batches]}"
        )


# ═══════════════════════════════════════════════════════════════
# 五：写入面闭合（写入 → 读取 → 反馈）
# ═══════════════════════════════════════════════════════════════


class TestWritePathCloses:
    """声明位若有读无写，用户就永远配不出声明——写了没人读的反面同样成立。

    "写入 → 读取 → 反馈"闭环要求三处都通：API 能写入、持久化不丢、
    解析读得到。缺一处，声明位就是一个只有机器能填的字段。
    """

    def test_apiRequestBodyCarriesDeclarations(self):
        """请求模型必须带声明位，否则用户经 API 配了就丢。"""
        from neurova.api.endpoints.shared_config import MCPServerRequest

        body = MCPServerRequest(name="s", command="python",
                                tool_capabilities={"read_file": dict(_ELIGIBLE)})
        assert body.tool_capabilities == {"read_file": dict(_ELIGIBLE)}
        assert MCPServerRequest(name="s", command="python").tool_capabilities == {}

    def test_endpointPackingKeepsDeclarations(self):
        """端点组包不得漏掉声明位（漏了就是在入口处静默丢弃）。"""
        from neurova.api.endpoints.shared_config import (
            MCPServerRequest,
            _mcp_config_from_body,
        )

        config = _mcp_config_from_body(MCPServerRequest(
            name="s", command="python",
            tool_capabilities={"read_file": dict(_ELIGIBLE)},
        ))
        assert config["tool_capabilities"] == {"read_file": dict(_ELIGIBLE)}

    def test_toolLayersConnectRequestCarriesDeclarations(self):
        """另一条注册路径（tool-layers connect）同样不得漏。"""
        from neurova.api.endpoints.tool_layers import MCPServerConnectRequest

        body = MCPServerConnectRequest(
            name="s", command="python",
            tool_capabilities={"read_file": dict(_ELIGIBLE)},
        )
        assert body.tool_capabilities == {"read_file": dict(_ELIGIBLE)}

    def test_roundTripFromWriteToResolution(self, iso_manager):
        """端到端闭环：经请求模型 → 端点组包 → 校验 → 持久化 → 解析。

        这条取代"手改字典"的写法：判据必须从**装配点**起（教义第 3 条），
        手塞一个私有字段测的是参数，不是接线。
        """
        from neurova.api.endpoints.shared_config import (
            MCPServerRequest,
            _mcp_config_from_body,
        )
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import isParallelEligible
        from neurova.tool_layers.mcp_config import validate_mcp_server_config

        body = MCPServerRequest(
            name="search", command="python",
            tool_capabilities={"query": dict(_ELIGIBLE)},
        )
        config = validate_mcp_server_config(_mcp_config_from_body(body))
        assert iso_manager.add_mcp_server(config) is True

        cap = resolveToolCapability("mcp.search.query")
        assert cap is not None and isParallelEligible(cap), (
            "写入 → 读取闭环在某一环断了"
        )


# ═══════════════════════════════════════════════════════════════
# 六：解析读不到配置时不打断整轮（失败以诚实形态暴露）
# ═══════════════════════════════════════════════════════════════


class TestResolutionFailureIsBounded:
    """能力解析处在**每轮工具执行**的必经路径上，故它的失败边界必须钉住。

    这里不是"把异常吞掉换成功"：能力解析的失败一侧与"未声明"同一处置（串行），
    本就是安全的那一侧；让异常穿透会把"少用一点并行"升级成"这一轮工具全不跑"。
    与 `resolveParallelBudget()` 读不到设置即退串行的口径同型。
    """

    def test_managerFailureFallsBackToSerialWithoutRaising(self, monkeypatch, caplog):
        import logging

        import neurova.shared_config as sc
        from neurova.agent.tool_coordinator import resolveToolCapability

        def _boom(*_args, **_kwargs):
            raise RuntimeError("配置根不可写")

        monkeypatch.setattr(sc, "get_shared_config_manager", _boom)
        with caplog.at_level(logging.WARNING):
            assert resolveToolCapability("mcp.srv.tool") is None, (
                "读不到配置时应按未声明处置，且不得抛出"
            )
        assert any("MCP 并行声明读取失败" in record.message for record in caplog.records), (
            "失败必须留痕——静默退回串行等于问题看不见"
        )

    def test_builtinPathUnaffectedByManagerFailure(self, monkeypatch):
        """内置侧不经过配置面：MCP 侧读不到配置不得连带影响内置工具判定。"""
        import neurova.shared_config as sc
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.core.tool_capability import isParallelEligible

        monkeypatch.setattr(
            sc, "get_shared_config_manager",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("不可用")),
        )
        cap = resolveToolCapability("file_read")
        assert cap is not None and isParallelEligible(cap)
