"""SkillPermissions 声明式权限模型。

契约（§2.4 resource.permission /
§4 P0-4）：

- 安装时声明（manifest），调用时强制（tool_executor）——Neurova 治理
  原本只管"调用时"（DENY/SANDBOX/ASK），缺"安装时声明"这层。
tools（工具白名单）/ network /
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
    check_tool_permission,
    tool_categories,
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


class TestMultiCategoryTools:
    """一个工具可以同属多类（write_pdf 既写文件又可能出网）。

    旧实现用 dict 推导生成单值映射，工具进两个集合会被后一个静默覆盖——
    归类结果取决于遍历顺序，权限判定随之漂移。多归属的语义取"每一类都必须授权"
    （AND）：只声明 file 的技能拿不到会出网的工具。
    """

    def test_write_pdf_belongs_to_file_and_network(self):
        assert tool_categories("write_pdf") == {"file", "network"}

    def test_single_category_tools_are_sets_of_one(self):
        assert tool_categories("file_read") == {"file"}
        assert tool_categories("web_fetch") == {"network"}
        assert tool_categories("mcp.anything") == {"network"}
        assert tool_categories("memory_search") == set()

    def test_file_only_skill_cannot_reach_the_network_tool(self):
        perms = SkillPermissions(file=True)
        assert perms.allows_tool("file_write") is True
        assert perms.allows_tool("write_pdf") is False

    def test_both_grants_make_it_allowed(self):
        assert SkillPermissions(file=True, network=True).allows_tool("write_pdf") is True

    def test_read_only_file_face_still_denies_it(self):
        """只读文件面 + 网络面 ≠ 可以出件（出件是写）。"""
        assert SkillPermissions(file_read_only=True, network=True).allows_tool("write_pdf") is False

    def test_denial_reason_names_every_category(self):
        reason = check_tool_permission(SkillPermissions(file=True), "write_pdf")
        assert reason and "network" in reason


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


class TestReadOnlyFaceJudgment:
    """跨类**只读**判定（`isReadOnlyFace`）——MCP 导出面对非属主调用方放行与否就判这一次。

    逐类别给理由，不靠"名字看起来是读"：`network` 类里同时装着
    `browser_navigate/browser_click/browser_type`（用公共口 `tool_categories` 复核），
    按类别粒度判定时整类不算只读；只有 `model` 与 file 的读子集是读侧。
    """

    def test_empty_declaration_is_not_read_only(self):
        """无声明不等于只读——外部面按 fail-closed 处理，宁拒不错放。"""
        assert not SkillPermissions().isReadOnlyFace()

    def test_model_only_declaration_is_read_only(self):
        assert SkillPermissions.from_dict({"model": True}).isReadOnlyFace()

    def test_file_read_subset_is_read_only(self):
        p = SkillPermissions.from_dict({"file": {"read_only": True}})
        assert p.file_read_only and not p.file
        assert p.isReadOnlyFace()

    def test_file_full_writes_are_not_read_only(self):
        assert not SkillPermissions.from_dict({"file": {"enabled": True}}).isReadOnlyFace()

    def test_network_is_not_read_only_because_the_category_carries_writes(self):
        """这一条是本判定最容易想错的地方：`web_search` 看着是读，但它所在的
        `network` 类含 `browser_click/type/fill`，类别粒度下不许当只读放行。"""
        assert "network" in tool_categories("browser_click"), "前提变了要重判这一格"
        assert not SkillPermissions.from_dict({"network": True}).isReadOnlyFace()

    def test_system_and_node_and_storage_are_write_side(self):
        for raw in ({"system": True}, {"node": True}, {"storage": {"enabled": True}}):
            assert not SkillPermissions.from_dict(raw).isReadOnlyFace(), raw

    def test_mixed_declaration_takes_the_widest_side(self):
        """只读＋写侧同时出现 ⇒ 整体算写侧（判定不许"有一项读就算读"）。"""
        p = SkillPermissions.from_dict({"model": True, "system": True})
        assert p.model and not p.isReadOnlyFace()

    def test_explicit_tool_allowlist_alone_is_not_read_only(self):
        """`tools` 白名单能点到任何工具，声明里出现它就不可能被证明"只含读侧"。"""
        p = SkillPermissions.from_dict({"tools": ["memory_search"]})
        assert p.tools is not None and not p.isReadOnlyFace()

    def test_skill_level_helper_follows_the_declaration_not_the_name(self):
        """技能级入口只读 `config.permissions`，不看技能名字——名单不在这里造。"""
        from neurova.skills.permissions import skillIsReadOnlyFace

        class _S:
            def __init__(self, config):
                self.config = config

        assert skillIsReadOnlyFace(_S({"permissions": {"model": True}}))
        assert not skillIsReadOnlyFace(_S({"permissions": {"file": {"enabled": True}}}))
        assert not skillIsReadOnlyFace(_S({})), "无声明 ⇒ 不是只读"
        assert not skillIsReadOnlyFace(None), "查无此技能 ⇒ 不许判成只读后放给非属主"
