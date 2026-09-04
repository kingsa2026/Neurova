"""P0-4 声明式权限 — 安装门与运行时强制（TDD）。

契约（docs/Neurova_Dify代码级对比_2026-09-03.md §4 P0-4）：

1. 安装门：manifest permissions 非法（未知能力键 / tools.allow 非列表 /
   未声明网络但 manifest 描述声称联网）→ validate_permissions_for_install
   报告 errors，blocked=True（fail-closed）
2. 市场导入安装链路：skill.json 含非法 permissions → 安装拒绝
   （market_importer 落盘前过门）
3. 运行时强制：ToolSequenceSkill 按自身 permissions 声明裁决每一步——
   声明"无网络"的技能调 web_search 被拒（有依据，而非治理默认放行）
4. tool_executor 治理预检带 skill 声明仲裁入口（check_skill_tool_permission）
"""

import pytest

from neurova.skills.permissions import SkillPermissions


class TestInstallGateValidation:
    def test_valid_permissions_pass(self):
        from neurova.skills.skill_install_gate import validate_permissions_for_install

        verdict = validate_permissions_for_install(
            {"tools": {"enabled": True, "allow": ["web_search"]}, "network": True}
        )
        assert verdict["blocked"] is False
        assert verdict["errors"] == []

    def test_unknown_capability_key_blocked(self):
        from neurova.skills.skill_install_gate import validate_permissions_for_install

        verdict = validate_permissions_for_install({"bogus_capability": True})
        assert verdict["blocked"] is True
        assert any("bogus_capability" in e for e in verdict["errors"])

    def test_tools_allow_non_list_blocked(self):
        from neurova.skills.skill_install_gate import validate_permissions_for_install

        verdict = validate_permissions_for_install({"tools": {"enabled": True, "allow": "web_search"}})
        assert verdict["blocked"] is True

    def test_unknown_tool_in_allowlist_blocked(self):
        """白名单含未知工具名 → 拦（可能是拼写错误或伪装名）"""
        from neurova.skills.skill_install_gate import validate_permissions_for_install

        verdict = validate_permissions_for_install(
            {"tools": {"enabled": True, "allow": ["web_search", "not_a_real_tool_xyz"]}}
        )
        assert verdict["blocked"] is True
        assert any("not_a_real_tool_xyz" in e for e in verdict["errors"])

    def test_mcp_whitelist_requires_network_declaration(self):
        """白名单放行 mcp.* 工具但未声明 network → 拦（声明不一致）"""
        from neurova.skills.skill_install_gate import validate_permissions_for_install

        verdict = validate_permissions_for_install(
            {"tools": {"enabled": True, "allow": ["mcp.fs.read"]}}
        )
        assert verdict["blocked"] is True

    def test_none_permissions_passes(self):
        """无声明（向后兼容的存量技能）不拦——模型默认全拒已兜底调用时"""
        from neurova.skills.skill_install_gate import validate_permissions_for_install

        verdict = validate_permissions_for_install(None)
        assert verdict["blocked"] is False


class TestMarketImporterGate:
    @pytest.fixture
    def importer(self, tmp_path, monkeypatch):
        from neurova.skills.market_importer import MarketImporter

        imp = MarketImporter(skills_dir=str(tmp_path / "skills"))
        return imp

    def test_invalid_permissions_rejected(self, importer, tmp_path, monkeypatch):
        """catalog entry 带非法 permissions → 安装任务 FAILED，目录被拒"""
        monkeypatch.setattr(
            importer,
            "_lookup_catalog_entry",
            lambda skill_id: {"name": "bad_perm_skill", "permissions": {"no_such_cap": True}},
        )
        task = importer.import_skill("bad_perm_skill")
        assert task.status.value == "failed", f"非法权限声明应拒装: {task.status}"
        assert "permissions" in (task.error_message or "").lower() or "权限" in (task.error_message or "")

    def test_valid_permissions_installed(self, importer, tmp_path, monkeypatch):
        monkeypatch.setattr(
            importer,
            "_lookup_catalog_entry",
            lambda skill_id: {
                "name": "good_perm_skill",
                "permissions": {"network": True, "tools": {"enabled": True, "allow": ["web_search"]}},
            },
        )
        task = importer.import_skill("good_perm_skill")
        assert task.status.value == "completed", f"合法声明应放行: {task.error_message}"
        assert (tmp_path / "skills" / "good_perm_skill").exists()


class TestToolSequenceRuntimeEnforcement:
    """ToolSequenceSkill 按声明裁决步进（运行时强制面）"""

    def _router_stub(self, calls):
        class _R:
            def execute(self, tool_name, params, agent_id=None, user_id=None):
                calls.append(tool_name)

                class _Res:
                    success = True
                    result = {"ok": True, "tool": tool_name}
                    error = None

                return _Res()

        return _R()

    @pytest.mark.asyncio
    async def test_network_denied_when_undeclared(self):
        """声明"无网络"的技能调 web_search 被拒——fail-closed 有依据"""
        from neurova.skill_system import ToolSequenceSkill

        calls = []
        skill = ToolSequenceSkill(
            name="no_net_skill",
            description="x",
            tool_sequence=[{"tool": "web_search", "params": {"query": "hi"}}],
            tool_router=self._router_stub(calls),
        )
        skill.config["permissions"] = {"file": {"enabled": True}}  # 只声明文件能力

        result = await skill.execute({}, context={})
        assert result.success is False
        assert "web_search" in (result.error or "")
        assert "权限" in (result.error or "") or "permission" in (result.error or "").lower()
        assert calls == [], "被拒步进不得真的执行工具"

    @pytest.mark.asyncio
    async def test_whitelisted_tool_allowed(self):
        from neurova.skill_system import ToolSequenceSkill

        calls = []
        skill = ToolSequenceSkill(
            name="wl_skill",
            description="x",
            tool_sequence=[{"tool": "web_search", "params": {"query": "hi"}}],
            tool_router=self._router_stub(calls),
        )
        skill.config["permissions"] = {
            "tools": {"enabled": True, "allow": ["web_search"]},
        }
        result = await skill.execute({}, context={})
        assert result.success is True
        assert calls == ["web_search"]

    @pytest.mark.asyncio
    async def test_platform_tools_unaffected(self):
        """平台能力（memory_search）不受声明约束——保持可用"""
        from neurova.skill_system import ToolSequenceSkill

        calls = []
        skill = ToolSequenceSkill(
            name="plat_skill",
            description="x",
            tool_sequence=[{"tool": "memory_search", "params": {"query": "hi"}}],
            tool_router=self._router_stub(calls),
        )
        skill.config["permissions"] = {}
        result = await skill.execute({}, context={})
        assert result.success is True
        assert calls == ["memory_search"]

    @pytest.mark.asyncio
    async def test_empty_declaration_locks_down(self):
        """显式空声明 {}（非缺省）= 锁定为仅平台工具可调（模型级 fail-closed 开关）"""
        from neurova.skill_system import ToolSequenceSkill

        calls = []
        skill = ToolSequenceSkill(
            name="locked_skill",
            description="x",
            tool_sequence=[{"tool": "file_write", "params": {"path": "x"}}],
            tool_router=self._router_stub(calls),
        )
        skill.config["permissions"] = {}
        result = await skill.execute({}, context={})
        assert result.success is False
        assert calls == []

    @pytest.mark.asyncio
    async def test_no_declaration_keeps_legacy_behavior(self):
        """键缺省（存量技能）：不启用声明裁决，维持旧行为（内容治理预检仍兜底）。

        模式挖掘/NL 合成产出的自动技能均无 permissions 声明，声明层
        缺省不得破坏既有可用性（增量约束）；安装门负责让新技能声明。
        """
        from neurova.skill_system import ToolSequenceSkill

        calls = []
        skill = ToolSequenceSkill(
            name="legacy_skill",
            description="x",
            tool_sequence=[{"tool": "file_write", "params": {"path": "x"}}],
            tool_router=self._router_stub(calls),
        )
        assert "permissions" not in skill.config
        result = await skill.execute({}, context={})
        assert result.success is True, "无声明的存量技能应维持旧行为"
        assert calls == ["file_write"]


class TestGovernancePrecheckDeclarationHook:
    """tool_executor 治理预检的声明仲裁入口"""

    def _checker(self):
        from neurova.tool_executor import ToolExecutor

        return ToolExecutor.__dict__["_check_skill_declaration"].__func__

    def test_check_skill_tool_permission_denies_undeclared(self):
        verdict = self._checker()("web_search", SkillPermissions())
        assert verdict is not None and verdict["success"] is False
        assert verdict["governance"]["decision"] == "deny"
        assert verdict["governance"]["source"] == "skill_permissions"

    def test_check_skill_tool_permission_allows_declared(self):
        verdict = self._checker()("web_search", SkillPermissions.from_dict({"network": True}))
        assert verdict is None

    def test_check_skill_tool_permission_none_is_passthrough(self):
        """无声明（存量技能）恒放行——内容治理预检仍兜底"""
        assert self._checker()("web_search", None) is None
