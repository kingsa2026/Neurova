"""R1-5 观察预算参数化（CUA 升级方案 Phase 1，OCU text_limit/tree budget 契约）

验收：
- _trim_snapshot_tree 纯函数：按节点行数/深度裁剪，truncated 如实标注
- 不传预算 → 原样透传（与旧行为一致）
- BrowserManager.dom_snapshot / manager.browser_dom_snapshot 预算参数贯通到后端
"""

import pytest

from neurova.computer_use.browser_manager import BrowserManager, _trim_snapshot_tree

TREE = "\n".join(
    [
        "- generic: active",
        '  - button "登录"',
        '  - textbox "搜索"',
        "    - generic: 内部",
        "      - generic: 更深",
        '  - link "帮助"',
    ]
)


class TestTrimTree:
    def test_no_budgets_passthrough(self):
        trimmed, truncated = _trim_snapshot_tree(TREE, None, None)
        assert trimmed == TREE
        assert truncated is False

    def test_node_budget(self):
        trimmed, truncated = _trim_snapshot_tree(TREE, max_nodes=3, max_depth=None)
        assert len(trimmed.splitlines()) == 3
        assert truncated is True

    def test_depth_budget(self):
        """aria 快照 2 空格一级：depth=2 保留 0/2 缩进行，砍掉 4/6 缩进"""
        trimmed, truncated = _trim_snapshot_tree(TREE, max_nodes=None, max_depth=2)
        lines = trimmed.splitlines()
        assert "      - generic: 更深" not in lines
        assert "    - generic: 内部" not in lines
        assert '  - button "登录"' in lines
        assert truncated is True

    def test_within_budget_not_marked(self):
        trimmed, truncated = _trim_snapshot_tree(TREE, max_nodes=100, max_depth=10)
        assert trimmed == TREE and truncated is False

    def test_empty_tree(self):
        trimmed, truncated = _trim_snapshot_tree("", 5, 5)
        assert trimmed == "" and truncated is False


class TestBudgetWiring:
    @pytest.mark.asyncio
    async def test_manager_passes_budgets_to_backend(self):
        """预算参数从 manager 贯通到 backend.dom_snapshot"""
        recorded = {}

        class FakeBackend:
            _initialized = True

            async def dom_snapshot(self, generation=None, max_nodes=None, max_depth=None):
                recorded.update(
                    generation=generation, max_nodes=max_nodes, max_depth=max_depth
                )
                from neurova.computer_use.browser_manager import BrowserResult

                return BrowserResult(success=True, data=TREE)

        mgr = BrowserManager.__new__(BrowserManager)
        mgr._config = {}
        mgr._backends = {"playwright": FakeBackend()}
        mgr._user_camofox_backends = {}
        mgr._camofox_enabled = False
        mgr._active_backend = None
        mgr._spider_tool = None
        mgr._dialog_handler = None
        mgr._lock = __import__("threading").RLock()

        await mgr.dom_snapshot(generation=1, max_nodes=50, max_depth=8)
        assert recorded == {"generation": 1, "max_nodes": 50, "max_depth": 8}

    @pytest.mark.asyncio
    async def test_executor_passes_llm_budgets(self, monkeypatch):
        """agent 工具路径：max_nodes/max_depth 从 params 传到 manager"""
        from neurova.tool_executor import ToolExecutor

        recorded = {}

        class FakeCUManager:
            async def browser_dom_snapshot(self, generation=None, max_nodes=None, max_depth=None):
                recorded.update(max_nodes=max_nodes, max_depth=max_depth)
                from neurova.computer_use.browser_manager import BrowserResult

                return BrowserResult(success=True, data=TREE)

        import neurova.computer_use as cu

        monkeypatch.setattr(cu, "get_computer_use_manager", lambda: FakeCUManager())

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None})()

        result = await inst._execute_browser_dom_snapshot(
            {"generation": 2, "max_nodes": 30, "max_depth": 6}
        )
        assert result.get("success") is True
        assert recorded == {"max_nodes": 30, "max_depth": 6}
