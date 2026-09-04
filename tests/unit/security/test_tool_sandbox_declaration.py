# -*- coding: utf-8 -*-
"""OpenClaw 对比 #15：工具 schema sandboxRequired 声明位。

参照 Dify P0-4 技能声明式权限的语义约定：
- 声明键缺省 = 旧行为（完全等价，无任何新裁决）
- 声明生效 = fail-closed 裁决有依据（声明工具强制走沙箱链）
- 开关默认关（NEUROVA_TOOL_SANDBOX_ENFORCE=1 才启用强制路由）

三层验证：
1. schema 层：_BUILTIN_SCHEMAS 可携带 sandbox_required，查询函数导出
2. API 层：/tool-layers/tools 回传 sandbox_required（前端徽标数据源）
3. 治理层：enforce 开启时，声明工具的调用被强制路由进沙箱/Deny 语义；
   关闭时与旧路径逐字节等价
"""
import importlib
import os
from unittest.mock import patch

import pytest

from neurova.builtin_tools import (
    _BUILTIN_SCHEMAS,
    get_builtin_tool_sandbox_declaration,
)


# ═══════════════════════════════════════════════════════════════
# schema 层：声明位存在且缺省安全
# ═══════════════════════════════════════════════════════════════


class TestSandboxDeclarationSchema:
    """_BUILTIN_SCHEMAS 声明位与查询函数。"""

    def test_schemas_may_carry_sandbox_required(self):
        """声明键可选——没有声明的 schema 不受影响（存量语义）。"""
        schema = {
            "description": "demo",
            "parameters": {"type": "object", "properties": {}},
            "sandbox_required": True,
        }
        _BUILTIN_SCHEMAS["__tdd_demo__"] = schema
        try:
            assert (
                get_builtin_tool_sandbox_declaration("__tdd_demo__") is True
            )
        finally:
            _BUILTIN_SCHEMAS.pop("__tdd_demo__", None)

    def test_undeclared_tool_returns_none(self):
        """未声明工具返回 None（缺省=旧行为，不触发任何新裁决）。"""
        assert "memory_search" in _BUILTIN_SCHEMAS
        assert get_builtin_tool_sandbox_declaration("memory_search") is None

    def test_unknown_tool_returns_none(self):
        assert get_builtin_tool_sandbox_declaration("no_such_tool_xyz") is None

    def test_declaration_ignores_non_bool_garbage(self):
        """声明值非法（非 bool）按未声明处理——声明面自身不做攻击面。"""
        schema = {
            "description": "demo",
            "parameters": {"type": "object", "properties": {}},
            "sandbox_required": "yes",
        }
        _BUILTIN_SCHEMAS["__tdd_garbage__"] = schema
        try:
            assert get_builtin_tool_sandbox_declaration("__tdd_garbage__") is None
        finally:
            _BUILTIN_SCHEMAS.pop("__tdd_garbage__", None)

    def test_list_sandbox_required_tools(self):
        """枚举声明工具（治理侧批量消费用）。"""
        from neurova.builtin_tools import list_sandbox_required_tools

        _BUILTIN_SCHEMAS["__tdd_sandboxed__"] = {
            "description": "demo",
            "parameters": {"type": "object", "properties": {}},
            "sandbox_required": True,
        }
        try:
            names = list_sandbox_required_tools()
            assert "__tdd_sandboxed__" in names
            assert "memory_search" not in names
        finally:
            _BUILTIN_SCHEMAS.pop("__tdd_sandboxed__", None)


# ═══════════════════════════════════════════════════════════════
# 治理层：强制路由（默认关）
# ═══════════════════════════════════════════════════════════════


class TestGovernanceSandboxEnforcement:
    """GovernancePolicy 对声明工具的强制路由。"""

    def _policy(self):
        from neurova.security.governance import GovernancePolicy

        return GovernancePolicy()

    def test_default_off_undeclared_tool_untouched(self):
        """默认关：未声明工具走旧裁决，无任何变化。"""
        policy = self._policy()
        result = policy.evaluate_tool_call("shell", {"command": "echo hi"})
        # echo 不命中内容规则 → 旧语义 ALLOW（默认动作）
        from neurova.security.governance import GovernanceDecision

        assert result is not None
        assert result.decision == GovernanceDecision.ALLOW

    def test_default_off_declared_tool_not_forced(self):
        """默认关：即使声明了 sandbox_required，也不强制改道。"""
        _BUILTIN_SCHEMAS["__tdd_enforce__"] = {
            "description": "demo",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
            },
            "sandbox_required": True,
        }
        try:
            policy = self._policy()
            # 安全命令 echo：旧语义 ALLOW；强制关 → 仍 ALLOW
            from neurova.security.governance import GovernanceDecision

            result = policy.evaluate_tool_call("__tdd_enforce__", {"command": "echo hi"})
            assert result is not None
            assert result.decision == GovernanceDecision.ALLOW
        finally:
            _BUILTIN_SCHEMAS.pop("__tdd_enforce__", None)

    def test_enforce_on_declared_safe_command_goes_sandbox(self):
        """开关开启：声明工具即便命令安全也被强制路由进沙箱裁决。"""
        _BUILTIN_SCHEMAS["__tdd_enforce2__"] = {
            "description": "demo",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
            },
            "sandbox_required": True,
        }
        try:
            os.environ["NEUROVA_TOOL_SANDBOX_ENFORCE"] = "1"
            policy = self._policy()
            result = policy.evaluate_tool_call("__tdd_enforce2__", {"command": "echo hi"})
            # 无真隔离后端的测试平台 → P1-7 诚实化升级 DENY；有后端 → SANDBOX
            from neurova.security.governance import GovernanceDecision

            assert result is not None
            assert result.decision in (GovernanceDecision.SANDBOX, GovernanceDecision.DENY)
            assert any("sandbox" in r.lower() or "沙箱" in r for r in result.reasons)
        finally:
            _BUILTIN_SCHEMAS.pop("__tdd_enforce2__", None)
            os.environ.pop("NEUROVA_TOOL_SANDBOX_ENFORCE", None)

    def test_enforce_on_mcp_declaration_is_denied(self):
        """MCP 命名空间声明了沙箱需求：无命令行沙箱语义 → 直接 DENY（与
        _governance_precheck 的 MCP-SANDBOX 阻断语义一致）。"""
        _BUILTIN_SCHEMAS["mcp.__tdd_decl__"] = {
            "description": "demo",
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
            },
            "sandbox_required": True,
        }
        try:
            os.environ["NEUROVA_TOOL_SANDBOX_ENFORCE"] = "1"
            policy = self._policy()
            result = policy.evaluate_tool_call("mcp.__tdd_decl__", {"q": "hello"})
            from neurova.security.governance import GovernanceDecision

            assert result is not None
            assert result.decision == GovernanceDecision.DENY
        finally:
            _BUILTIN_SCHEMAS.pop("mcp.__tdd_decl__", None)
            os.environ.pop("NEUROVA_TOOL_SANDBOX_ENFORCE", None)

    def test_enforce_on_undeclared_tool_no_effect(self):
        """开关开启但工具未声明：不强制改道（声明面才是裁决依据）。"""
        os.environ["NEUROVA_TOOL_SANDBOX_ENFORCE"] = "1"
        try:
            policy = self._policy()
            from neurova.security.governance import GovernanceDecision

            result = policy.evaluate_tool_call("shell", {"command": "echo hi"})
            assert result is not None
            assert result.decision == GovernanceDecision.ALLOW
        finally:
            os.environ.pop("NEUROVA_TOOL_SANDBOX_ENFORCE", None)

    def test_enforce_env_needs_exact_value_one(self):
        """开关值容错：'1' 开启，其它值（'0'/'true'/任意）不开启——避免
        'false' 字符串意外开启的经典坑。"""
        for value, expected_on in (("1", True), ("0", False), ("true", False)):
            os.environ["NEUROVA_TOOL_SANDBOX_ENFORCE"] = value
            try:
                from neurova.security.governance import (
                    _tool_sandbox_enforce_enabled,
                )

                assert _tool_sandbox_enforce_enabled() is expected_on, value
            finally:
                os.environ.pop("NEUROVA_TOOL_SANDBOX_ENFORCE", None)


# ═══════════════════════════════════════════════════════════════
# API 层：/tool-layers/tools 回传声明位（前端徽标数据源）
# ═══════════════════════════════════════════════════════════════


class TestToolLayersApiDeclaration:
    """ToolInfo 增加 sandbox_required 字段并列出接口回传。"""

    def test_tool_info_has_optional_field(self):
        from neurova.api.endpoints.tool_layers import ToolInfo

        info = ToolInfo(tool_id="t", name="t")
        assert info.sandbox_required is None

        info2 = ToolInfo(tool_id="t", name="t", sandbox_required=True)
        assert info2.sandbox_required is True

    def test_list_all_tools_returns_declaration(self, monkeypatch, tmp_path):
        """内置工具列表端点回传 sandbox_required。"""
        _BUILTIN_SCHEMAS["__tdd_api__"] = {
            "description": "demo",
            "parameters": {"type": "object", "properties": {}},
            "sandbox_required": True,
        }
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient

            import neurova.api.endpoints.tool_layers as tl

            class _FakeBuiltin:
                name = "__tdd_api__"
                description = "demo"
                parameters = {"type": "object", "properties": {}}
                sandbox_required = True

            class _FakeAgent:
                _builtin_tools = type(
                    "R", (), {"list_tools": staticmethod(lambda: [_FakeBuiltin()])}
                )()

            monkeypatch.setattr(tl, "get_tool_engine",
                                lambda: type("E", (), {"list_tools": staticmethod(lambda status=None: [])})())
            # list_all_tools 内部 `from neurova.api.endpoints import get_agent_instance`
            # —— patch 源头模块的属性
            import neurova.api.endpoints as endpoints_pkg

            monkeypatch.setattr(endpoints_pkg, "get_agent_instance", lambda: _FakeAgent(), raising=False)

            app = FastAPI()
            app.include_router(tl.router, prefix="/v1/tool-layers")
            # 工具列表端点要求登录——测试覆盖鉴权依赖
            from neurova.api.auth import get_current_user

            app.dependency_overrides[get_current_user] = lambda: {"user_id": "tdd"}
            client = TestClient(app)
            resp = client.get("/v1/tool-layers/tools")
            assert resp.status_code == 200, resp.text
            tools = resp.json()
            hit = [t for t in tools if t["tool_id"] == "__tdd_api__"]
            assert hit and hit[0]["sandbox_required"] is True
        finally:
            _BUILTIN_SCHEMAS.pop("__tdd_api__", None)
