# -*- coding: utf-8 -*-
"""per-tool 超时表的成员资格必须落在注册面上（Issue #271 M5 尾巴·第六命中点）。

## 根因（放大视角扫同契约消费方时逮到，本片新发现）

`agent/tool_coordinator.py` 的 `TOOL_TIMEOUTS_S` 是一份**手写名字表**，它的键
从未与注册面对过账。实测有一个**幻名**：

    "dom_snapshot": 45        ← 全仓注册处为 0（不在内置 71，也无别处注册）
    "browser_dom_snapshot": .. 真名，走默认 60s
    "computer_dom_snapshot": . 真名，走默认 60s

即：那条 45s 的放宽**从未作用在任何工具上**。而它的原意是给"快照类"留余量——
真名有**两个**（浏览器侧与桌面侧 UIA 树快照，后者正是"枚举控件树"这种慢操作），
两个都没拿到。

这是与并行轴旧名单被逮住的两个幻名（`get_time` / `time_now`）同型的形态：手写表
与真实工具面之间没有对账机制，写错的名字不会响，只是静默不生效。

## 处置

1. **幻名删净**，按原意补到真名上（`browser_dom_snapshot` / `computer_dom_snapshot`）；
2. **成员资格判据**：表里的键必须是注册面真名——幻名在这一条上红；
3. **完整性判据**：注册面里凡声明了 `timeoutDisposition`（超时处置轴，M3/G4 已立）
   的工具，必须有明确超时条目——"该有却不该走默认值"的工具不得静默落默认。
"""

from __future__ import annotations

import pytest

from neurova.agent.tool_coordinator import (
    TOOL_DEFAULT_TIMEOUT_S,
    TOOL_TIMEOUTS_S,
    get_tool_timeout,
)
from neurova.builtin_tools import (
    _BUILTIN_SCHEMAS,
    get_registered_tool_names,
)

#: 本片点名修掉的幻名（写它的人以为它就是快照工具）。
GHOST_NAME = "dom_snapshot"

#: 幻名 `dom_snapshot` 的原意（45s 窗口）应落在的真名上。
#: 45 < 默认 60，方向是**收紧**而非放宽——与表头「只读/轻工具短超时」同向：
#: 快照是只读探测，卡满 60s 没有意义，早收早转后台。
SNAPSHOT_TOOLS = {"browser_dom_snapshot", "computer_dom_snapshot"}


class TestNoGhostNames:
    def test_registeredSurfaceIsNotEmpty(self):
        assert len(get_registered_tool_names()) >= 60

    def test_everyTableKeyIsARegisteredTool(self):
        ghosts = sorted(set(TOOL_TIMEOUTS_S) - set(get_registered_tool_names()))
        assert ghosts == [], (
            f"超时表里有非注册工具名（幻名——表项静默不生效，没人会发现）：{ghosts}"
        )

    def test_theGhostIsGone(self):
        assert GHOST_NAME not in TOOL_TIMEOUTS_S, (
            f"`{GHOST_NAME}` 是幻名：它不在内置 71 内，也没有任何注册处。"
            "留着它只会让人以为快照类已有 45s 放宽"
        )
        assert get_tool_timeout(GHOST_NAME) == TOOL_DEFAULT_TIMEOUT_S, (
            "幻名必须回落默认——留着它等于给一个不存在的工具开特殊通道"
        )

    def test_snapshotToolsGotTheIntendedWindow(self):
        """幻名的原意（45s 窗口）落到了真名上，方向与表头口径一致（短超时）。"""
        for name in SNAPSHOT_TOOLS:
            assert name in TOOL_TIMEOUTS_S, f"{name} 是快照类真名，应拿到专属窗口"
            assert get_tool_timeout(name) == 45, (
                f"{name} 的超时读数不是 45（实为 {get_tool_timeout(name)}）"
                "——它正是幻名那条表项的原意"
            )
            assert get_tool_timeout(name) < TOOL_DEFAULT_TIMEOUT_S, (
                "快照类应短于默认（只读探测卡满默认窗口没有意义）"
            )


#: 声明了超时处置但**有意走默认窗口**的工具：逐条给结论，不许含糊。
#: 走默认不是缺陷（默认值 60s 是合法可达窗口，处置照常生效）；缺陷是"没人论证过"。
#: 本表是**豁免登记**：命中而未登记者红，登记后不得再漂（键还在、声明还在）。
DEFAULT_WINDOW_LEDGER = {
    "exec_command": (
        "长任务由工具自身的 yield_time_ms 语义承接：未结束即返回 "
        "session_id + status=running，不等满窗口，故 60s 默认即够"
    ),
    "computer_shell": (
        "系统操作命令（进程/服务/安装依赖）走既有保守默认；本片不改数值——"
        "调它是行为变更（超时点从 60s 挪到别处），不在声明面收口的范围内"
    ),
    "run_code": (
        "同上：数据处理/算法代码走既有保守默认，改数值属行为变更，不在本片"
    ),
}


class TestDispositionDeclaredToolsHaveAConclusion:
    """凡声明了超时处置的工具，必须**逐条有结论**（有条目，或登记为有意走默认）。"""

    def _declared(self):
        return {
            n for n, s in _BUILTIN_SCHEMAS.items()
            if isinstance(s, dict)
            and (s.get("capability") or {}).get("timeoutDisposition") is not None
        }

    def test_dispositionSurfaceIsNotEmpty(self):
        assert self._declared(), "反向锁：声明面确实有成员（空集会让下面几条恒真）"

    def test_everyDeclaredToolHasEntryOrLedgerReason(self):
        missing = sorted(
            n for n in self._declared()
            if n not in TOOL_TIMEOUTS_S and n not in DEFAULT_WINDOW_LEDGER
        )
        assert missing == [], (
            "这些工具声明了自己的超时处置（`timeoutDisposition`），却既没有超时条目、"
            f"也没有登记'有意走默认'的理由——没人论证过：{missing}"
        )

    def test_ledgerReasonsAreConcrete(self):
        """登记的理由必须具体（不是"允许保留"这类空话）。"""
        for name, reason in DEFAULT_WINDOW_LEDGER.items():
            assert len(reason) >= 20, f"{name} 的结论太笼统，等于没写理由：{reason!r}"

    def test_ledgerHasNoStaleEntries(self):
        """登记项必须仍是有意走默认的：一旦它有了条目或不再声明处置，登记即过期。"""
        stale = sorted(
            n for n in DEFAULT_WINDOW_LEDGER
            if n in TOOL_TIMEOUTS_S or n not in self._declared()
        )
        assert stale == [], (
            f"登记表里的这些条目已不成立（有了条目或不再声明处置），必须重新给结论：{stale}"
        )


class TestExistingContractUnchanged:
    """等价迁移：既有条目的读数逐条不变（含大小写不敏感与未知回落）。"""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("calculator", 5),
            ("memory_search", 10),
            ("web_search", 30),
            ("web_fetch", 30),
            ("weather", 15),
            ("browser_navigate", 90),
            ("browser_click", 60),
            ("browser_type", 60),
            ("browser_screenshot", 60),
            ("browser_extract_text", 60),
            ("computer_ssh_exec", 180),
            ("deep_research", 180),
            ("file_parse", 120),
            ("git", 120),
            ("spawn_subagent", 600),
        ],
    )
    def test_existingEntriesUnchanged(self, name, expected):
        assert get_tool_timeout(name) == expected

    def test_unknownFallsBackToDefault(self):
        assert get_tool_timeout("totally_unknown_tool") == TOOL_DEFAULT_TIMEOUT_S

    def test_caseInsensitive(self):
        assert get_tool_timeout("WEB_SEARCH") == 30


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
