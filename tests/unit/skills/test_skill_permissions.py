"""SkillPermissions 声明式权限模型（TDD — P0-4，Dify 对标）。

契约（docs/Neurova_Dify代码级对比_2026-09-03.md §2.4 resource.permission /
§4 P0-4）：

- 安装时声明（manifest），调用时强制（tool_executor）——Neurova 治理
  原本只管"调用时"（DENY/SANDBOX/ASK），缺"安装时声明"这层。
- 六类能力对齐 Dify resource.permission：tools（工具白名单）/ network /
  file / model / node / storage；未声明的能力默认拒绝（fail-closed）。
- manifest dict 解析（skill.json / SKILL.md frontmatter 均可透传 dict）：
  非法键忽略、类型错误宽松降级——安装门负责报错，模型负责解析。
- tool 分类判定：内置工具按注册表分类（network/file/system/…），
  mcp.* 前缀恒为 network，未分类工具只受 tools 白名单约束。
"""

import pytest

from neurova.skills.permissions import (
    SkillPermissionModel,
    SkillPermissions,
    tool_category,
    tools_for_categories,
)


class TestSkillPermissionsModel:
    def test_default_is_deny_all(self):
        """默认（无声明）= 全拒绝——fail-closed 是模型级默认值"""
        p = SkillPermissions()
        assert p.tools is None and p.network is False and p.file is False
        assert p.model is False and p.node is False and p.storage is False

    def test_from_dict_full_shape(self):
        p = SkillPermissions.from_dict(
            {
                "tools": {"enabled": True, "allow": ["web_search", "weather"]},
                "network": {"enabled": True},
                "file": {"enabled": True},
                "storage": {"enabled": True, "size": 1048576},
            }
        )
        assert p.network is True
        assert p.tools == ["web_search", "weather"]
        assert p.file is True and p.file_read_only is False
        assert p.storage is True and p.storage_size == 1048576

    def test_from_dict_flat_bool(self):
        """宽松形态：直接给 bool 也接受"""
        p = SkillPermissions.from_dict({"network": True, "tools": ["web_search"]})
        assert p.network is True
        assert p.tools == ["web_search"]

    def test_from_dict_ignores_unknown_keys(self):
        p = SkillPermissions.from_dict({"bogus_key": True, "network": True})
        assert p.network is True
        assert not hasattr(p, "bogus_key")

    def test_from_dict_none_or_invalid_returns_default(self):
        assert SkillPermissions.from_dict(None) == SkillPermissions()
        assert SkillPermissions.from_dict("not-a-dict") == SkillPermissions()

    def test_to_dict_roundtrip(self):
        src = {"tools": {"enabled": True, "allow": ["weather"]}, "network": True}
        p = SkillPermissions.from_dict(src)
        restored = SkillPermissions.from_dict(p.to_dict())
        assert restored == p


class TestToolCategory:
    def test_network_tools(self):
        for t in ("web_search", "web_fetch", "weather", "rss_read", "youtube_transcript"):
            assert tool_category(t) == "network", t

    def test_browser_tools_are_network(self):
        assert tool_category("browser_navigate") == "network"
        assert tool_category("browser_read") == "network"

    def test_file_tools(self):
        for t in ("file_read", "file_write", "file_create", "file_delete", "file_edit", "file_list"):
            assert tool_category(t) == "file", t

    def test_system_tools(self):
        for t in ("computer_shell", "run_code", "spawn_subagent"):
            assert tool_category(t) == "system", t

    def test_memory_tools_uncategorized(self):
        """记忆/规划类是平台能力，不属于六类能力面（不受能力声明约束）"""
        assert tool_category("memory_search") is None
        assert tool_category("planning") is None

    def test_mcp_prefix_is_network(self):
        assert tool_category("mcp.something.call") == "network"

    def test_unknown_tool_uncategorized(self):
        assert tool_category("totally_unknown_tool") is None

    def test_tools_for_categories_includes_registry(self):
        """分类展开应覆盖 builtin 注册表（file 类至少含 file_read）"""
        file_tools = tools_for_categories("file")
        assert "file_read" in file_tools and "file_write" in file_tools


class TestCapabilityCheck:
    def test_tool_allowed_by_explicit_whitelist(self):
        p = SkillPermissions.from_dict({"tools": {"enabled": True, "allow": ["web_search"]}})
        assert p.allows_tool("web_search")
        assert not p.allows_tool("file_write")

    def test_tool_allowed_by_category_declaration(self):
        """声明 network=True → 该分类全部工具放行"""
        p = SkillPermissions.from_dict({"network": True})
        assert p.allows_tool("web_search")
        assert p.allows_tool("mcp.any.tool")
        assert not p.allows_tool("file_write")

    def test_whitelist_overrides_category_deny(self):
        """tools.allow 白名单可单独放行某工具（即使分类未声明）"""
        p = SkillPermissions.from_dict(
            {"network": True, "tools": {"enabled": True, "allow": ["file_read"]}}
        )
        assert p.allows_tool("file_read")

    def test_uncategorized_tool_needs_explicit_whitelist(self):
        """平台能力工具（memory_search 等）不受分类约束，可默认调用"""
        p = SkillPermissions()
        assert p.allows_tool("memory_search")

    def test_deny_all_by_default(self):
        p = SkillPermissions()
        assert not p.allows_tool("web_search")
        assert not p.allows_tool("file_write")
        assert not p.allows_tool("computer_shell")

    def test_no_network_means_mcp_denied(self):
        p = SkillPermissions()
        assert not p.allows_tool("mcp.filesystem.read")

    def test_check_capability_helpers(self):
        p = SkillPermissions.from_dict({"file": {"enabled": True, "read_only": True}})
        assert p.allows_file_read
        assert not p.allows_file_write
        assert not p.model_enabled
