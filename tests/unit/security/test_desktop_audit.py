"""R3-4 动作审计（CUA Phase 3 立项 §3）

隐私红线（立项书成文约束）：审计只存**元数据白名单**——时间/用户/工具/
目标窗口或 URL host/ActionResult 四元组/耗时/是否需人工。**永不存截图、
永不存键入文本、永不存 set_value 内容、永不存 shell 命令原文**。

验收：
1. 表列集合 == 白名单（机械测试，红线不可漂移）
2. 三入口（tool_executor 分发）各产一条审计
3. ActionResult effect/route/delivery/refusal_code 提取正确
4. 敏感字段（command/value/text/base64）即使出现在 params/result 也不落库
5. 写审计失败永不抛出（审计不阻断工具流）
6. 查询过滤（tool/user/时间窗/needs_human）+ TTL purge
7. needs_human 语义：拒绝码在列 或 effect ∈ {refused, unverifiable, suspected_noop}
"""

import time

import pytest

from neurova.security.desktop_audit import (
    ALLOWED_COLUMNS,
    DesktopAuditStore,
    extract_audit_meta,
)


@pytest.fixture
def store(tmp_path):
    s = DesktopAuditStore(db_path=str(tmp_path / "audit.db"))
    yield s
    s.close()


class TestPrivacyRedline:
    def test_columns_are_exactly_allowlist(self, store):
        """机械红线：表列集合 == ALLOWED_COLUMNS（任何新增列必须过立项评审）。"""
        cols = {r["name"] for r in store._conn.execute("PRAGMA table_info(desktop_action_audit)").fetchall()}
        assert cols == set(ALLOWED_COLUMNS)

    def test_no_content_columns_exist(self, store):
        forbidden = {"screenshot", "image", "text", "value", "command", "keys", "content", "base64"}
        cols = {r["name"] for r in store._conn.execute("PRAGMA table_info(desktop_action_audit)").fetchall()}
        assert not (cols & forbidden), f"红线漂移：审计表出现内容列 {cols & forbidden}"

    def test_sensitive_payload_never_stored(self, store):
        """command/value/base64 出现在 params/result 里也不得进任何列（按值搜索）。"""
        canary_cmd = "net user pwn PASS123 /add"
        canary_val = "MySecretPassword"
        canary_b64 = "iVBORw0KGgoAAAANS"
        store.record_computer_action(
            "computer_shell",
            {"command": canary_cmd},
            {"success": True, "stdout": canary_b64},
            12.0,
        )
        store.record_computer_action(
            "computer_type",
            {"text": canary_val},
            {"success": True},
            3.0,
        )
        dump = str(store._conn.execute("SELECT * FROM desktop_action_audit").fetchall())
        for canary in (canary_cmd, canary_val, canary_b64):
            assert canary not in dump


class TestExtraction:
    def test_action_result_fields_extracted(self):
        ar = {
            "effect": "confirmed",
            "route": "uia",
            "delivery": "background",
            "evidence": ["value_readback"],
            "refusal_code": None,
        }
        meta = extract_audit_meta(
            "computer_click_element",
            {"index": 3, "window_title": "记事本"},
            {"success": True, "action_result": ar},
        )
        assert meta["effect"] == "confirmed"
        assert meta["route"] == "uia"
        assert meta["delivery"] == "background"
        assert meta["refusal_code"] is None
        assert meta["target"] == "记事本"

    def test_browser_target_is_host_only(self):
        meta = extract_audit_meta(
            "browser_navigate",
            {"url": "https://example.com:8443/secret/path?token=abc"},
            {"success": True},
        )
        assert meta["target"] == "example.com"

    def test_needs_human_semantics(self):
        assert extract_audit_meta("computer_click", {}, {
            "action_result": {"effect": "refused", "refusal_code": "permission_required"},
        })["needs_human"] == 1
        assert extract_audit_meta("computer_click", {}, {
            "action_result": {"effect": "unverifiable"},
        })["needs_human"] == 1
        assert extract_audit_meta("computer_click", {}, {
            "action_result": {"effect": "confirmed", "evidence": ["x"]},
        })["needs_human"] == 0
        # 无 ActionResult 的成功动作 → 不需人工
        assert extract_audit_meta("computer_screenshot", {}, {"success": True})["needs_human"] == 0


class TestStoreLifecycle:
    def test_record_and_query_filters(self, store):
        store.record_computer_action("computer_click", {"x": 1, "y": 2}, {"success": True}, 5.0,
                                     user_id="u1", agent_id="a1", session_id="s1")
        store.record_computer_action("computer_type", {"text": "x"}, {"success": True}, 2.0,
                                     user_id="u2")
        assert len(store.query_actions()) == 2
        assert [r["tool_name"] for r in store.query_actions(tool="computer_click")] == ["computer_click"]
        assert len(store.query_actions(user="u2")) == 1
        future = time.time() + 3600
        assert len(store.query_actions(since=future)) == 0
        assert len(store.query_actions(until=time.time() - 3600)) == 0

    def test_needs_human_filter(self, store):
        store.record_computer_action("computer_click", {}, {
            "action_result": {"effect": "refused", "refusal_code": "stale_generation"},
        }, 1.0)
        store.record_computer_action("computer_screenshot", {}, {"success": True}, 1.0)
        rows = store.query_actions(needs_human=True)
        assert len(rows) == 1 and rows[0]["tool_name"] == "computer_click"

    def test_purge_older_than(self, store):
        store.record_computer_action("computer_click", {}, {"success": True}, 1.0)
        # 手改时间戳为 100 天前再 purge
        old = time.time() - 100 * 86400
        store._conn.execute("UPDATE desktop_action_audit SET ts=?", (old,))
        store._conn.commit()
        assert store.purge_older_than(days=90) == 1
        assert store.query_actions() == []

    def test_record_never_raises_on_db_failure(self, store, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("disk gone")

        monkeypatch.setattr(store, "_insert", boom)
        # 不抛异常 = 审计失败不阻断工具流
        assert store.record_computer_action("computer_click", {}, {"success": True}, 1.0) is None

    def test_idempotent_singleton_factory(self, tmp_path):
        from neurova.security import desktop_audit as da

        s1 = da.get_desktop_audit_store(db_path=str(tmp_path / "x.db"))
        s2 = da.get_desktop_audit_store(db_path=str(tmp_path / "x.db"))
        assert s1 is s2
        da.reset_desktop_audit_store()


class TestDispatchChokePoint:
    """三入口收口：tool_executor 分发点写审计（本地/远程/MCP 导出同源）。"""

    @pytest.mark.asyncio
    async def test_builtin_dispatch_records(self, monkeypatch):
        from neurova.security import desktop_audit as da
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": "s9"})()

        async def fake_shot(self, params):
            return {"success": True, "format": "png", "size_bytes": 10}

        monkeypatch.setattr(ToolExecutor, "_execute_computer_screenshot", fake_shot)
        rows = []
        real = da.get_desktop_audit_store(db_path=":memory:")
        monkeypatch.setattr(real, "record_computer_action",
                            lambda *a, **k: rows.append((a, k)) or 1)
        try:
            await inst._execute_builtin_tool("computer_screenshot", {})
            assert len(rows) == 1
            args, kwargs = rows[0]
            assert args[0] == "computer_screenshot"
        finally:
            da.reset_desktop_audit_store()
