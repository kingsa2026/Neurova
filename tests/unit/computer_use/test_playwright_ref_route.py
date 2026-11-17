"""P1-3（ZCode 电脑操控对照评测）：ref 路径的 route 自报必须进封闭词表。

browser_manager 的 click_ref/fill_ref 自报 `route="playwright_ref"`
（browser_manager.py 的 ref 动作成功分支），但 `action_result.ROUTES` 没有这个名字
→ `derive_from_browser_result` 对这类结果返回 None → ref 点击/输入**不携带**
ActionResult 契约——前端徽标（route/delivery/effect）与审计证据链在 ref 路径上断线。
修复：词表补登 `playwright_ref`（设计稿 §0.3 映射表同步登记，否则词表守卫红）。
"""

from neurova.computer_use import action_result as ar
from neurova.tool_executor import ToolExecutor


class TestPlaywrightRefRouteRegistered:
    def test_route_in_vocabulary(self):
        assert "playwright_ref" in ar.ROUTES, (
            "playwright_ref 不在 ROUTES 词表——ref 路径动作不携带 ActionResult 契约"
        )

    def test_ref_success_derives_action_result(self):
        out = ar.derive_from_browser_result({"success": True, "route": "playwright_ref"})
        assert out is not None, "ref 成功结果必须能推导 ActionResult"
        assert out["route"] == "playwright_ref"
        assert out["effect"] == "confirmed"

    def test_normalize_attaches_contract_for_ref_results(self):
        normalized = ToolExecutor._normalize_browser_result(
            {"success": True, "route": "playwright_ref", "data": {"ref": "e1"}}
        )
        assert normalized.get("action_result", {}).get("route") == "playwright_ref"

    def test_ref_failure_derives_refusal(self):
        out = ar.derive_from_browser_result(
            {"success": False, "route": "playwright_ref", "error": "ref e9 不在快照中（not found）"}
        )
        assert out is not None
        assert out["effect"] == "refused"
        assert out["refusal_code"] == "ref_not_found"
