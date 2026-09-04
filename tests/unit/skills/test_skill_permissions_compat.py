"""P0-4 适配 — 四条技能链路不被声明语义阻断（防回归）。

背景（2026-09-04 用户审计）：P0-4 声明式权限落地后，验证
1. 棘轮剪枝递归进化（genetic_engine.register_to_skill_registry）
2. 肌肉记忆自动执行（ToolExecutionManager → tool_executor）
3. agent 自封装（create_skill / NL 合成 → register_skill + persist）
4. 市场安装（hub_client SKILL.md frontmatter 声明过门 + 冷启动恢复透传）

契约：无声明（键缺省）的存量链路行为不变；带声明的链路声明不丢失。
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class TestGeneticEngineRegistrationUnaffected:
    def test_genetic_skill_without_permissions_executes(self):
        """进化产出的技能无 permissions 声明 → 步进不裁决（旧行为）"""
        from neurova.skill_system import ToolSequenceSkill

        calls = []

        class _R:
            def execute(self, tool_name, params, agent_id=None, user_id=None):
                calls.append(tool_name)

                class _Res:
                    success = True
                    result = {"ok": True}
                    error = None

                return _Res()

        skill = ToolSequenceSkill(
            name="genetic_combo",
            description="遗传进化工具组合",
            tool_sequence=[{"tool": "file_write", "params": {"path": "x"}}],
            tool_router=_R(),
        )
        # 模拟 genetic_engine 构造的 config（无 permissions 键）
        assert "permissions" not in skill.config
        result = __import__("asyncio").run(skill.execute({}, context={}))
        assert result.success is True
        assert calls == ["file_write"]

    def test_register_skill_accepts_manifest_without_permissions_attr(self):
        """manifest 无 permissions 属性（存量 SimpleNamespace 形态）不报错"""
        from neurova.skill_system import SkillRegistry

        reg = SkillRegistry()
        m = SimpleNamespace(name="legacy_m", description="", config={"tool_sequence": [{"tool": "weather", "params": {}}]})
        assert reg.register_skill(m) is True
        assert "permissions" not in reg.get_skill("legacy_m").config


class TestMuscleMemoryUnaffected:
    def test_auto_execute_outside_scope_passthrough(self):
        """肌肉记忆自动执行不在 skill 作用域内 → 声明仲裁恒放行"""
        from neurova.tool_executor import ToolExecutor

        checker = ToolExecutor.__dict__["_check_skill_declaration"].__func__
        from neurova.skills.permissions import current_skill_permissions

        assert current_skill_permissions() is None, "无作用域时声明上下文必须为空"
        assert checker("file_write", None) is None

    def test_scope_only_wraps_skill_execution(self):
        """作用域仅在 execute_skill_tool 期间生效，退出即还原"""
        import asyncio

        from neurova.skills.permissions import (
            current_skill_permissions,
            skill_permission_scope,
        )
        from neurova.skills.permissions import SkillPermissions as P

        async def _run():
            with skill_permission_scope(P()):
                assert current_skill_permissions() is not None
            assert current_skill_permissions() is None

        asyncio.run(_run())


class TestCreateSkillAutoDeclaration:
    def test_auto_declared_tools_whitelist(self):
        """create_skill 按步进工具自动声明（声明=实际能力面）"""
        from neurova.skills.permissions import SkillPermissions

        tool_sequence = [
            {"tool": "web_search", "params": {"query": "x"}},
            {"tool": "file_write", "params": {"path": "x"}},
            {"tool": "memory_search", "params": {"query": "x"}},  # 平台工具不列入
        ]
        from neurova.skills.permissions import tool_category

        declared_tools = sorted({
            s.get("tool") for s in tool_sequence
            if s.get("tool") and tool_category(s.get("tool")) is not None
        })
        permissions = {"tools": {"enabled": True, "allow": declared_tools}} if declared_tools else None
        assert declared_tools == ["file_write", "web_search"]

        p = SkillPermissions.from_dict(permissions)
        assert p.allows_tool("web_search")
        assert p.allows_tool("file_write")
        assert p.allows_tool("memory_search"), "平台工具不受声明约束"
        assert not p.allows_tool("computer_shell"), "未用到的能力不得进声明"

    def test_validation_of_auto_declaration_passes_gate(self):
        """自动声明的形态必须过安装门（防 create_skill 与门契约漂移）"""
        from neurova.skills.skill_install_gate import validate_permissions_for_install

        verdict = validate_permissions_for_install(
            {"tools": {"enabled": True, "allow": ["web_search", "file_write"]}}
        )
        assert verdict["blocked"] is False, verdict


class TestHubClientDeclarationGate:
    def _make_hub(self, tmp_path):
        from neurova.skills.hub_client import SkillHubClient

        return SkillHubClient(base_dir=str(tmp_path))

    def test_invalid_frontmatter_permissions_rejected(self, tmp_path):
        hub = self._make_hub(tmp_path)
        skill_dir = tmp_path / "sk_bad"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: sk_bad\npermissions:\n  bogus_cap: true\n---\n# body",
            encoding="utf-8",
        )
        assert hub._gate_check_and_rollback(skill_dir, "sk_bad") is False
        assert not skill_dir.exists(), "非法声明须回滚删除"

    def test_valid_permissions_persisted_to_skill_json(self, tmp_path):
        hub = self._make_hub(tmp_path)
        skill_dir = tmp_path / "sk_ok"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: sk_ok\npermissions:\n  network: true\n---\n# body",
            encoding="utf-8",
        )
        # 内容扫描在无脚本文件时通过（quick 模式）
        assert hub._gate_check_and_rollback(skill_dir, "sk_ok") is True
        meta = json.loads((skill_dir / "skill.json").read_text(encoding="utf-8"))
        assert meta["permissions"]["network"] is True

    def test_no_permissions_still_installs(self, tmp_path):
        """无声明（存量市场技能）安装链路不受影响"""
        hub = self._make_hub(tmp_path)
        skill_dir = tmp_path / "sk_plain"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: sk_plain\n---\n# body", encoding="utf-8")
        assert hub._gate_check_and_rollback(skill_dir, "sk_plain") is True


class TestColdStartRestoreTransparency:
    def test_restore_preserves_declared_permissions(self, tmp_path):
        """冷启动恢复：manifest.config.permissions 透传进 ToolSequenceSkill"""
        from neurova.skill_system import SkillRegistry

        entry = {"id": "syn1", "name": "syn1", "description": "x"}
        info = {
            "manifest": {
                "source": "synthesized",
                "config": {
                    "tool_sequence": [{"tool": "web_search", "params": {}}],
                    "permissions": {"tools": {"enabled": True, "allow": ["web_search"]}},
                },
            }
        }
        service = MagicMock()
        service.list_skills.return_value = [entry]
        service.get_skill_info.return_value = info

        from neurova.skills.market_registry import restore_market_skills_from_service

        reg = SkillRegistry()
        restored = restore_market_skills_from_service(service, reg)
        assert restored == 1
        skill = reg.get_skill("syn1")
        assert skill is not None
        assert skill.config.get("permissions") == {
            "tools": {"enabled": True, "allow": ["web_search"]}
        }, "声明必须在冷启动后仍生效"

    def test_restore_without_permissions_unchanged(self, tmp_path):
        from neurova.skill_system import SkillRegistry

        entry = {"id": "syn2", "name": "syn2", "description": "x"}
        info = {
            "manifest": {
                "source": "synthesized",
                "config": {"tool_sequence": [{"tool": "weather", "params": {}}]},
            }
        }
        service = MagicMock()
        service.list_skills.return_value = [entry]
        service.get_skill_info.return_value = info

        from neurova.skills.market_registry import restore_market_skills_from_service

        reg = SkillRegistry()
        assert restore_market_skills_from_service(service, reg) == 1
        assert "permissions" not in reg.get_skill("syn2").config
