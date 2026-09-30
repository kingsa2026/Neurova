# -*- coding: utf-8 -*-
"""T-08 · ref 一等寻址：自造的编号必须能自证，否则它比没有编号更坏。

## 为什么需要 ref（不是"省一次快照"）

`smart-click`/`smart-type` 现在遇到同名候选只能回 409 让人重说目标；而真页的重名率是
实测 **56%**（MDN 一页 618 条可交互行去重后 429）。camofox 侧早就内部算好了 ref
（`_resolve_ref_via_snapshot` 歧义时回 `ambiguous_ref` + 候选 ref），**但模型面没有任何能吃
ref 的动作工具** —— 这就是工单集里那句"候选列得出、动不了"的断链形状。

## 两条拍板决定了设计形状（§19）

- **D-1：ref 绑 `generation`**。Playwright 的 `aria_snapshot()` 不带 ref，要 ref 只能自己
  编号，而回解只能落到 `get_by_role(...).nth(k)`；`nth` 是 DOM 序位，DOM 一变就不保证
  还是那个元素。所以"跨快照稳定"是假承诺，ref 只在产出它的那一代里有效。
- **D-2：不暴露 selector/xpath 回退**。ref 是唯一新增的寻址入口，不给模型留一条绕开
  快照事实去猜选择器的路。

## 自证是本单的核心判据，不是附加品

自编号的风险是**静默指错**：快照第 3 行是"删除"按钮，`nth(2)` 在无障碍树序与 DOM 序
不一致时可能解到另一个元素——那时它会**成功点错**。所以每次解 ref 都要用该元素自己的
子树 `aria_snapshot()` 回读一遍，role+name 对不上就拒绝（`ref-mismatch`）并且**不发点击**。
判据里有这条的反面对照：解到错位元素时，旧形状是 success=True。
"""

from __future__ import annotations

import pytest

from neurova.computer_use import browser_manager as bm
from neurova.computer_use.browser_manager import (
    BrowserResult, NO_ACTIVE_TAB_ERROR, PlaywrightBackend, parseRefLine,
)

TREE = "\n".join([
    "- document:",
    '  - button "删除"',
    '  - link "帮助中心"',
    '  - button "删除"',
    '  - textbox "用户名输入框"',
    '  - button "删除"',
])


class TestAnnotate:
    def test_actionable_lines_get_sequential_refs_and_occurrences(self):
        text, refs = bm.annotateSnapshotRefs(TREE)
        assert refs[0].ref == "e1" and refs[0].role == "button" and refs[0].name == "删除"
        assert [r.ref for r in refs] == ["e1", "e2", "e3", "e4", "e5"]
        # 同名三行的 occurrence 必须是 0/1/2 —— 这就是 nth() 的序号，不是全表序号
        assert [r.occurrence for r in refs if r.name == "删除"] == [0, 1, 2]
        # 非可交互行（document）不得被编号
        assert "[e" in text and "document:" not in text.splitlines()[1]

    def test_already_annotated_text_is_left_alone(self):
        """camofox 的快照服务端就带了 `[eN]`：再归一一次就是双源编号。"""
        camofoxStyle = "- button 'Login' [e3]\n- textbox [e5]:"
        text, refs = bm.annotateSnapshotRefs(camofoxStyle)
        assert text == camofoxStyle
        assert [r.ref for r in refs] == ["e3", "e5"]

    def test_nameless_actionable_line_annotated_with_none_name(self):
        tree = "- document:\n  - checkbox:"
        text, refs = bm.annotateSnapshotRefs(tree)
        assert refs and refs[0].name is None, refs
        assert "[e1]" in text

    def test_parse_ref_line_handles_both_quote_styles_and_bare_names(self):
        assert parseRefLine("  - button 'Login' [e3]") == ("button", "Login", "3")
        assert parseRefLine('  - button "Login" [e3]') == ("button", "Login", "3")
        assert parseRefLine("  - button Login [e3]") == ("button", "Login", "3")
        assert parseRefLine("  - textbox [e5]:") == ("textbox", None, "5")
        assert parseRefLine("  - paragraph: 说明文字") is None


class _FakeLocator:
    """只装 Playwright locator 被用到的那三个面：nth / aria_snapshot / click|fill。"""

    def __init__(self, backend: "_FakePage", role: str, name, occurrence: int) -> None:
        self._p, self.role, self.name, self.n = backend, role, name, occurrence

    def nth(self, i: int) -> "_FakeLocator":
        return _FakeLocator(self._p, self.role, self.name, i)

    async def aria_snapshot(self) -> str:
        return self._p.subtree(self.role, self.name, self.n)

    async def click(self, timeout=None) -> None:
        self._p.actions.append(("click", self.role, self.name, self.n))

    async def fill(self, text, timeout=None) -> None:
        self._p.actions.append(("fill", self.role, self.name, text, self.n))


class _FakePage:
    def __init__(self, *, domOrderNames, ariaTreeNames) -> None:
        """domOrderNames：get_by_role(role,name).nth(k) 实际解到的元素名；
        ariaTreeNames：快照第 k 个可交互行声称的元素名。两者错位即模拟静默指错。"""
        self.dom = domOrderNames
        self.tree = ariaTreeNames
        self.actions: list = []
        self.url = "file:///fake"

    async def title(self) -> str:
        return "fake"

    def get_by_role(self, role, name=None) -> _FakeLocator:
        return _FakeLocator(self, role, name, 0)

    def subtree(self, role, name, occurrence: int) -> str:
        got = self.dom.get(role, {}).get(occurrence)
        return f'- {role} "{got}"' if got is not None else f"- {role}"


def _backendWithRefs(*, dom=None, tree=None):
    """构造一个"已快照过"的 Playwright 后端：存表走的是生产同一个 annotateSnapshotRefs。"""
    b = PlaywrightBackend({"headless": True})
    b._tabs = {"tab_a": {"page": None, "generation": 1, "refs": {}}}
    b._active_target_id = "tab_a"
    if tree:
        _text, refs = bm.annotateSnapshotRefs(tree)
        b._tabs["tab_a"]["refs"] = {r.ref: r for r in refs}
    return b


class TestRefActions:
    @pytest.mark.asyncio
    async def test_click_ref_resolves_the_recorded_occurrence(self):
        b = _backendWithRefs(tree='  - button "删除" [e1]\n  - button "删除" [e2]')
        assert [r.occurrence for r in b._tabs["tab_a"]["refs"].values()] == [0, 1], "存表口径错了"
        page = _FakePage(domOrderNames={"button": {0: "删除", 1: "删除"}}, ariaTreeNames=[])
        b._tabs["tab_a"]["page"] = page
        res = await b.click_ref("e2", generation=b._tabs["tab_a"]["generation"])
        assert res.success is True, res.error
        assert page.actions and page.actions[0][0] == "click" and page.actions[0][3] == 1, page.actions

    @pytest.mark.asyncio
    async def test_misresolved_ref_is_refused_and_no_click_is_sent(self):
        """快照说第 2 个"删除"，nth 却解到"取消"：必须拒，且**不发点击**。"""
        b = _backendWithRefs(tree='  - button "删除" [e2]')
        page = _FakePage(domOrderNames={"button": {1: "取消"}}, ariaTreeNames=[])
        b._tabs["tab_a"]["page"] = page
        res = await b.click_ref("e2", generation=b._tabs["tab_a"]["generation"])
        assert res.success is False, f"错位却成功了——这就是静默点错：{res}"
        assert "ref-mismatch" in (res.error or ""), (
            f"错位必须带可判定 marker（与 snapshot-empty / no-active-tab 同风格）：{res.error}"
        )
        assert page.actions == [], "拒绝路径上仍然发出了点击"

    @pytest.mark.asyncio
    async def test_unknown_ref_is_refused_with_a_triageable_cause(self):
        b = _backendWithRefs(tree='  - button "删除" [e1]')
        page = _FakePage(domOrderNames={}, ariaTreeNames=[])
        b._tabs["tab_a"]["page"] = page
        res = await b.click_ref("e99", generation=b._tabs["tab_a"]["generation"])
        assert res.success is False and "e99" in (res.error or ""), res.error
        assert page.actions == []

    @pytest.mark.asyncio
    async def test_stale_generation_is_refused_before_any_lookup(self):
        """D-1：ref 绑 generation。过期时连表都不该查——否则跨代同号照样能点。"""
        b = _backendWithRefs(tree='  - button "删除" [e1]')
        page = _FakePage(domOrderNames={"button": {0: "删除"}}, ariaTreeNames=[])
        b._tabs["tab_a"]["page"] = page
        b._tabs["tab_a"]["generation"] = 7
        res = await b.click_ref("e1", generation=6)
        assert res.success is False and "过期" in (res.error or ""), res.error
        assert page.actions == []

    @pytest.mark.asyncio
    async def test_action_invalidates_refs_and_generation(self):
        """动作后旧 ref 必须作废：否则模型会拿已被 DOM 变化改位的编号继续点。"""
        b = _backendWithRefs(tree='  - button "删除" [e1]')
        page = _FakePage(domOrderNames={"button": {0: "删除"}}, ariaTreeNames=[])
        b._tabs["tab_a"]["page"] = page
        gen = b._tabs["tab_a"]["generation"]
        assert (await b.click_ref("e1", generation=gen)).success is True
        assert b._tabs["tab_a"]["generation"] == gen + 1
        res = await b.click_ref("e1", generation=b._tabs["tab_a"]["generation"])
        assert res.success is False, "generation 已推进却仍按旧代执行"

    @pytest.mark.asyncio
    async def test_no_page_still_names_the_state(self):
        b = _backendWithRefs(tree=None)
        b._tabs["tab_a"]["page"] = None
        res = await b.fill_ref("e1", "abc", generation=None)
        assert res.success is False and (res.error or "").startswith(NO_ACTIVE_TAB_ERROR.split(":")[0]), res.error


class TestSingleSourceGrammar:
    def test_camofox_does_not_keep_a_second_parser(self):
        """两套同一语法的解析器 = 两份事实源（教义第 6 条），必须共用 browser_manager 那一份。"""
        from neurova.computer_use import camofox_server_backend as cf

        assert cf._parse_ref_line is parseRefLine, (
            "camofox 又自带了一份 ref 行解析：快照文本一改形状就会两侧漂移"
        )


class TestToolFaceIsWired:
    """后端能做 ≠ 模型能用。ref 必须同时出现在 schema / dispatch / 参数白名单 / 人读标签四面。

    这一类断言的存在理由不是形式：本仓有过"执行体接好了、名单没跟着扩"的漂移
    （截图补拍名单曾零消费），而三面一致性守卫 `test_computer_tool_faces_reconcile.py`
    只在**已知集合**上对账，新工具若整面缺席它不会主动喊。
    """

    def test_schemas_dispatch_and_allowlist_all_contain_the_ref_tools(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS
        import neurova.tool_executor as te

        dispatch = te.ToolExecutor._builtin_dispatch
        assert isinstance(dispatch, dict) and dispatch, "dispatch 表形状变了，判据需随之更新"
        for tool in ("browser_click_ref", "browser_fill_ref"):
            assert tool in _BUILTIN_SCHEMAS, f"{tool} 没有 schema：模型看不见它"
            assert tool in dispatch, f"{tool} 在 dispatch 里缺席：schema 有、调用即 unknown tool"
            assert tool in te._COMPUTER_TOOL_PARAM_KEYS, \
                f"{tool} 没有参数白名单——幻影旋钮守卫会失配"
            # 白名单必须与 schema 的 properties 逐字相等，否则一侧漂移一侧静默
            props = set(_BUILTIN_SCHEMAS[tool]["parameters"]["properties"])
            assert props == set(te._COMPUTER_TOOL_PARAM_KEYS[tool]), (
                f"{tool} 的 schema 参数与白名单不一致：仅 schema 有={sorted(props - set(te._COMPUTER_TOOL_PARAM_KEYS[tool]))}"
                f"，仅白名单有={sorted(set(te._COMPUTER_TOOL_PARAM_KEYS[tool]) - props)}"
            )

    def test_click_ref_handler_reaches_the_manager_with_ref_and_generation(self, monkeypatch):
        import asyncio

        import neurova.computer_use as cu
        from neurova.tool_executor import ToolExecutor

        calls: list = []

        class _Mgr:
            async def browser_click_ref(self, ref, generation=None):
                calls.append((ref, generation))
                return BrowserResult(success=True, data={"ref": ref}, generation=4,
                                     route="playwright_ref")

        monkeypatch.setattr(cu, "get_computer_use_manager", lambda *a, **k: _Mgr())
        handler = getattr(ToolExecutor, "_execute_browser_click_ref", None)
        assert handler is not None, "执行体没接：模型面与后端之间是断的"

        executor = ToolExecutor.__new__(ToolExecutor)

        async def _noEvent(*a, **k):
            return None

        monkeypatch.setattr(executor, "_emit_computer_event", _noEvent)
        res = asyncio.run(handler(executor, {"ref": "e3", "generation": 3}))
        assert calls == [("e3", 3)], calls
        assert res.get("success") is True, res

    def test_missing_ref_param_is_named_not_crashed(self, monkeypatch):
        """参数缺失要点名"缺什么、下一步做什么"，不是抛出去变成 500 式噪声。"""
        import asyncio

        from neurova.tool_executor import ToolExecutor

        executor = ToolExecutor.__new__(ToolExecutor)
        res = asyncio.run(ToolExecutor._execute_browser_click_ref(executor, {}))
        assert isinstance(res, dict) and "ref" in (res.get("error") or ""), res

    def test_ref_tool_schemas_expose_no_selector_path(self):
        """D-2：ref 工具的参数面就是 `ref`（+ text/generation），不得留 selector/xpath 口子。"""
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        for tool in ("browser_click_ref", "browser_fill_ref"):
            props = set(_BUILTIN_SCHEMAS[tool]["parameters"]["properties"])
            assert "ref" in props, f"{tool} 连 ref 都不收，等于没接通"
            forbidden = {p for p in props if any(
                k in p.lower() for k in ("selector", "xpath", "css", "query"))}
            assert not forbidden, f"{tool} 暴露了绕开快照事实的入口：{sorted(forbidden)}"

    def test_permissionFaceKeepsRefToolsWithTheRoleFamily(self):
        """权限面按类别放行，**未归类的工具被当作平台能力恒放行**——新工具漏登记
        不是「少一项权限」，而是把写操作做成了关不掉的口子。ref 族必须与 role 族同类。
        """
        from neurova.skills.permissions import SkillPermissions, tool_categories

        roleFace = tool_categories("browser_click_role")
        assert roleFace, "前提变了：role 族已不在任何能力类别里，判据需随之更新"
        for tool in ("browser_click_ref", "browser_fill_ref"):
            assert tool_categories(tool) == roleFace, (
                f"{tool} 的能力归属与 role 族不一致：{sorted(tool_categories(tool))} vs {sorted(roleFace)}"
            )

        locked = SkillPermissions.from_dict(
            {"system": False, "network": False, "file": False, "model": False})
        assert locked.allows_tool("browser_click_role") is False, "前提变了：role 族不再受网络面约束"
        for tool in ("browser_click_ref", "browser_fill_ref"):
            assert locked.allows_tool(tool) is False, (
                f"{tool} 在能力面全关的技能下仍被放行——它没进任何类别"
            )
