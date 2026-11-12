# -*- coding: utf-8 -*-
"""防火墙工具级许可真实现红测（台账 §6-597，拍板：实现真实许可模型）。

三重死现场（全库断点审计 2026-11-12 追记）：
- `mcp_client._check_firewall` import 的 `Firewall` 类在 core/firewall.py 不存在
  （实名 AgentFirewall/get_firewall）→ ImportError 被吞，校验恒跳过；
- `AgentFirewall` 没有 `check_permission` 方法；
- 规则集没有 per-user 工具许可数据源。

修复口径（拍板：实现真实许可模型）：
- GlobalRuleSet/UserRuleSet 增 `blocked_tools`（黑名单制，与 UserRuleSet
  「只能加严不能放松」同向；全局∪用户任一命中即拒）；
- AgentFirewall.check_permission(user_id, resource_type, name) 真裁决；
- mcp_client._check_firewall 改用 get_firewall() 单源单例，显式拒绝真抛
  PermissionError（fail-closed on deny），基础设施故障仍 skip（不伪造放行对象）。
"""
import os

os.environ.setdefault("NEUROVA_JWT_SECRET", "test_secret_for_fw_tool_permission")
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_for_fw_tool_permission")

from pathlib import Path

import pytest


@pytest.fixture
def firewall(tmp_path):
    from neurova.core.firewall import AgentFirewall

    return AgentFirewall(config_path=str(tmp_path / "firewall.json"))


class TestCheckPermissionModel:
    def test_default_allows_unlisted_tool(self, firewall):
        assert firewall.check_permission("u1", "mcp_tool", "mcp.srv.read") is True

    def test_global_blocklist_denies_everyone(self, firewall):
        firewall.update_global_rules({"blocked_tools": ["mcp.srv.shell"]})
        assert firewall.check_permission("u1", "mcp_tool", "mcp.srv.shell") is False
        assert firewall.check_permission("admin", "mcp_tool", "mcp.srv.shell") is False

    def test_user_blocklist_denies_only_that_user(self, firewall):
        firewall.update_user_rules("u1", {"blocked_tools": ["mcp.srv.write"]})
        assert firewall.check_permission("u1", "mcp_tool", "mcp.srv.write") is False
        assert firewall.check_permission("u2", "mcp_tool", "mcp.srv.write") is True

    def test_effective_rules_merge_user_and_global(self, firewall):
        firewall.update_global_rules({"blocked_tools": ["t_g"]})
        firewall.update_user_rules("u1", {"blocked_tools": ["t_u"]})
        effective = firewall.get_effective_rules("u1")
        assert set(effective["blocked_tools"]) >= {"t_g", "t_u"}

    def test_blocked_tools_persist_roundtrip(self, firewall):
        firewall.update_global_rules({"blocked_tools": ["mcp.srv.shell"]})
        from neurova.core.firewall import AgentFirewall

        reloaded = AgentFirewall(config_path=firewall._config_path)
        assert firewall.check_permission("u1", "mcp_tool", "mcp.srv.shell") is False
        assert reloaded.check_permission("u1", "mcp_tool", "mcp.srv.shell") is False


class TestMcpCheckFirewallUsesRealFirewall:
    @pytest.fixture
    def client(self, firewall, monkeypatch):
        import asyncio

        import neurova.core.firewall as fw_mod
        from neurova.tool_layers.mcp_client import MCPToolClient

        monkeypatch.setattr(fw_mod, "get_firewall", lambda: firewall)
        client = MCPToolClient(user_id="u1")
        client._run = asyncio.run  # 直调 async 校验器的同步壳
        return client

    def test_denied_tool_raises_permission_error(self, client, firewall):
        firewall.update_user_rules("u1", {"blocked_tools": ["mcp.srv.shell"]})
        with pytest.raises(PermissionError):
            client._run(client._check_firewall("mcp.srv.shell", user_id="u1"))

    def test_allowed_tool_passes_silently(self, client):
        assert client._run(client._check_firewall("mcp.srv.read", user_id="u1")) is None

    def test_request_level_user_wins_over_client_default(self, client, firewall):
        """P0-3 语义保持：请求级 user_id 优先于 client 构造身份。"""
        firewall.update_user_rules("u2", {"blocked_tools": ["mcp.srv.shell"]})
        with pytest.raises(PermissionError):
            client._run(client._check_firewall("mcp.srv.shell", user_id="u2"))
        # 同一工具对 u1 仍放行（请求级身份各自按自己的规则裁决）
        assert client._run(client._check_firewall("mcp.srv.shell", user_id="u1")) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
