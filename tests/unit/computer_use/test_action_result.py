"""R1-2 ActionResult 封闭契约（CUA 升级方案 Phase 1，Cua C-1 × OCU 诚实降级）

契约（构造器强制不变式）：
- confirmed ⇒ evidence ≥ 1 且无 refusal_code
- refused ⇒ 无 evidence，delivery 必须为 not_applicable，refusal_code 必填
- suspected_noop ⇒ 不得带 evidence（"执行了但无验证手段"的诚实档）
- 词表封闭：route/delivery/effect/evidence/refusal_code 越界即拒
"""

import pytest

from neurova.computer_use import action_result as ar
from neurova.computer_use.action_result import ActionResultError


class TestBuildInvariants:
    def test_confirmed_requires_evidence(self):
        with pytest.raises(ActionResultError):
            ar.build("uia", "confirmed", delivery="background", evidence=None)
        with pytest.raises(ActionResultError):
            ar.build("uia", "confirmed", delivery="background", evidence=[])

    def test_confirmed_with_evidence_ok(self):
        r = ar.build("uia", "confirmed", delivery="background", evidence=["locator_ack"])
        assert r["effect"] == "confirmed" and r["evidence"] == ["locator_ack"]

    def test_refused_forbids_evidence_and_delivery(self):
        with pytest.raises(ActionResultError):
            ar.build("uia", "refused", refusal_code="stale_generation", evidence=["locator_ack"])
        with pytest.raises(ActionResultError):
            ar.build("uia", "refused", refusal_code="stale_generation", delivery="background")

    def test_refused_requires_code(self):
        with pytest.raises(ActionResultError):
            ar.build("uia", "refused")

    def test_suspected_noop_forbids_evidence(self):
        with pytest.raises(ActionResultError):
            ar.build("global_input", "suspected_noop", delivery="foreground", evidence=["delivery_ack"])

    def test_closed_vocabulary(self):
        for kwargs in (
            {"route": "teleport", "effect": "unverifiable"},
            {"route": "uia", "effect": "teleported"},
            {"route": "uia", "effect": "unverifiable", "delivery": "teleport"},
            {"route": "uia", "effect": "confirmed", "delivery": "background", "evidence": ["vibes"]},
            {"route": "uia", "effect": "refused", "refusal_code": "vibes"},
        ):
            with pytest.raises(ActionResultError):
                ar.build(**kwargs)


class TestConvenienceConstructors:
    def test_confirmed(self):
        r = ar.confirmed("playwright_role", "background", ["locator_ack"])
        assert r == {
            "route": "playwright_role",
            "effect": "confirmed",
            "delivery": "background",
            "evidence": ["locator_ack"],
        }

    def test_refused(self):
        r = ar.refused("uia", "background_unavailable")
        assert r["effect"] == "refused"
        assert r["refusal_code"] == "background_unavailable"
        assert "evidence" not in r and r["delivery"] == "not_applicable"

    def test_refused_with_escalation(self):
        r = ar.refused("uia", "background_unavailable", escalation={"target": "pixel", "reason": "route_unavailable"})
        assert r["escalation"] == {"target": "pixel", "reason": "route_unavailable"}

    def test_suspected_noop_and_unverifiable(self):
        assert ar.suspected_noop("camofox_ref", "background")["effect"] == "suspected_noop"
        assert ar.unverifiable("global_input", "foreground")["effect"] == "unverifiable"


class TestAttach:
    def test_attach_into_result(self):
        result = {"success": True}
        r = ar.attach(result, ar.confirmed("uia", "background", ["locator_ack"]))
        assert r is result and "action_result" in r


class TestBrowserDerivation:
    """BrowserResult → ActionResult 的推导映射（_normalize_browser_result 消费）"""

    def test_success_with_route_confirmed(self):
        r = ar.derive_from_browser_result({"success": True, "route": "playwright_role"})
        assert r == {
            "route": "playwright_role",
            "effect": "confirmed",
            "delivery": "background",
            "evidence": ["locator_ack"],
        }

    def test_success_without_route_no_result(self):
        """route 未知（历史路径）→ 不附加 action_result（诚实：不编造）"""
        assert ar.derive_from_browser_result({"success": True}) is None

    def test_stale_generation(self):
        r = ar.derive_from_browser_result({
            "success": False, "route": "camofox_ref",
            "error": "target generation 过期（当前 3，传入 2）——快照事实失效",
        })
        assert r["effect"] == "refused" and r["refusal_code"] == "stale_generation"

    def test_ref_not_found(self):
        r = ar.derive_from_browser_result({
            "success": False, "route": "camofox_ref",
            "error": "快照中未找到 role='button' name='登录' 的可交互元素",
        })
        assert r["refusal_code"] == "ref_not_found"

    def test_backend_error_fallback(self):
        r = ar.derive_from_browser_result({"success": False, "route": "dom", "error": "timeout"})
        assert r["refusal_code"] == "backend_error"

    def test_no_route_on_failure(self):
        assert ar.derive_from_browser_result({"success": False, "error": "x"}) is None
