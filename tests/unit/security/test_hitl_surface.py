"""P1-2 HITL surface 安全模型（TDD — Dify HumanInputSurface 对标）。

契约（docs/Neurova_Dify代码级对比_2026-09-03.md §2.3/§4 P1-2）：
- HumanInputSurface 三态枚举：SERVICE_API / CONSOLE / OPENAPI
- 接收方裁剪（allowed_recipients）：SERVICE_API/OPENAPI 只能收
  STANDALONE_WEB_APP 类 web 表单请求；CONSOLE 只收 CONSOLE/BACKSTAGE
  ——按调用面裁剪可接收的审批来源，防"API 请求伪装成控制台审批"
- surface 参数贯通：ApprovalRequest.metadata["surface"]（向后兼容，
  缺省 = 不裁剪，存量行为不变）
- resolve_recipient(surface, requested_surface)：裁决函数返回
  (allowed: bool, reason: str)
"""

import pytest

from neurova.security.hitl_surface import (
    HumanInputSurface,
    RequestOrigin,
    resolve_recipient,
)


class TestSurfaceEnum:
    def test_three_surfaces(self):
        assert HumanInputSurface.SERVICE_API.value == "service_api"
        assert HumanInputSurface.CONSOLE.value == "console"
        assert HumanInputSurface.OPENAPI.value == "openapi"

    def test_request_origins(self):
        assert RequestOrigin.STANDALONE_WEB_APP.value == "standalone_web_app"
        assert RequestOrigin.CONSOLE.value == "console"
        assert RequestOrigin.BACKSTAGE.value == "backstage"


class TestRecipientResolution:
    def test_service_api_only_accepts_web_app(self):
        allowed, reason = resolve_recipient(HumanInputSurface.SERVICE_API, RequestOrigin.STANDALONE_WEB_APP)
        assert allowed is True
        for origin in (RequestOrigin.CONSOLE, RequestOrigin.BACKSTAGE):
            ok, why = resolve_recipient(HumanInputSurface.SERVICE_API, origin)
            assert ok is False, origin
            assert why, "拒绝须有理由（审计用）"

    def test_openapi_only_accepts_web_app(self):
        assert resolve_recipient(HumanInputSurface.OPENAPI, RequestOrigin.STANDALONE_WEB_APP)[0] is True
        assert resolve_recipient(HumanInputSurface.OPENAPI, RequestOrigin.CONSOLE)[0] is False

    def test_console_accepts_console_and_backstage(self):
        assert resolve_recipient(HumanInputSurface.CONSOLE, RequestOrigin.CONSOLE)[0] is True
        assert resolve_recipient(HumanInputSurface.CONSOLE, RequestOrigin.BACKSTAGE)[0] is True
        assert resolve_recipient(HumanInputSurface.CONSOLE, RequestOrigin.STANDALONE_WEB_APP)[0] is False

    def test_surface_from_string(self):
        """字符串宽松解析（API 层透传字符串形态）"""
        assert resolve_recipient("console", "backstage")[0] is True
        assert resolve_recipient("SERVICE_API", "standalone_web_app")[0] is True
        with pytest.raises(ValueError):
            resolve_recipient("bogus_surface", "console")


class TestApprovalManagerIntegration:
    @pytest.fixture
    def manager(self, tmp_path):
        from neurova.security.approval_manager import ApprovalManager

        return ApprovalManager(str(tmp_path))

    def test_request_with_surface_recorded(self, manager):
        """创建审批时带 surface → 记入 metadata（可审计）"""
        req = manager.create_approval_request(
            agent_id="a1", user_id="u1", command="rm -rf /tmp/x",
            description="t", danger_reason="destructive",
            metadata={"surface": "service_api", "request_origin": "standalone_web_app"},
        )
        assert req.metadata["surface"] == "service_api"
        assert req.metadata["request_origin"] == "standalone_web_app"

    def test_legacy_request_without_surface_unchanged(self, manager):
        """缺省（无 surface）→ 行为不变（向后兼容）"""
        req = manager.create_approval_request(
            agent_id="a1", user_id="u1", command="ls", description="t",
        )
        assert "surface" not in req.metadata
