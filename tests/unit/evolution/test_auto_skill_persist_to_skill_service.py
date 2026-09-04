"""
s3 TDD: AutoSkillBuilder.register_to_skill_registry 后同步写入 SkillService 持久化

Bug 根因 (bug-hunt Phase 3):
  skill_encapsulation.py:441-487 的 register_to_skill_registry 只写 SkillRegistry
  (in-memory global), 不写 SkillService (per-agent disk manifest).
  导致:
    - 自动生成的技能在服务重启后丢失 (SkillRegistry 是内存态)
    - 前端 SkillPoolPage 调用 GET /private → SkillService.list_skills() 看不到自动技能
      (s2 修复后 /private 聚合 SkillService, 但 SkillService 仍空, 因为 register_to_skill_registry
       没写它)

修复契约 (s3 P0 #2):
  1. SkillService 新增 register_auto_skill(skill_id, name, ...) 方法 — 无文件路径, 仅元数据持久化
  2. AutoSkillBuilder.register_to_skill_registry(registry, skill_service=None) — 可选参数, 向后兼容
  3. 当 skill_service 提供时, 每个 active template 同步写入 SkillService
  4. 写入后 skill_service.list_skills() 应包含自动技能
  5. 不提供 skill_service 时, 保留原行为 (仅写 registry)
  6. 非活跃 template 不写入 SkillService
"""

import pytest
from unittest.mock import MagicMock, patch


class TestSkillServiceRegisterAutoSkill:
    """测试 SkillService.register_auto_skill 新方法"""

    def test_register_auto_skill_exists(self, tmp_path):
        """s3.1 SkillService 应有 register_auto_skill 方法"""
        from neurova.skills.skill_service import SkillService
        service = SkillService(agent_id="test", skills_dir=str(tmp_path))
        assert hasattr(service, "register_auto_skill"), "SkillService 应有 register_auto_skill 方法"

    def test_register_auto_skill_persists_metadata(self, tmp_path):
        """s3.2 register_auto_skill 应持久化元数据到 manifest"""
        from neurova.skills.skill_service import SkillService
        service = SkillService(agent_id="test", skills_dir=str(tmp_path))

        ok = service.register_auto_skill(
            skill_id="auto-1",
            name="auto_skill_1",
            description="auto generated",
            version="0.1.0",
            config={"tool_sequence": ["tool_a", "tool_b"]},
        )
        assert ok is True, "register_auto_skill 应返回 True"

        # list_skills 应包含新技能
        skills = service.list_skills()
        assert any(s["id"] == "auto-1" for s in skills), "list_skills 应包含自动技能"
        target = next(s for s in skills if s["id"] == "auto-1")
        assert target["name"] == "auto_skill_1"
        assert target["enabled"] is True

    def test_register_auto_skill_rejects_duplicate(self, tmp_path):
        """s3.3 register_auto_skill 重复注册同一 skill_id 应返回 False"""
        from neurova.skills.skill_service import SkillService
        service = SkillService(agent_id="test", skills_dir=str(tmp_path))

        service.register_auto_skill(skill_id="dup", name="first")
        ok = service.register_auto_skill(skill_id="dup", name="second")
        assert ok is False, "重复注册应返回 False"

    def test_register_auto_skill_survives_restart(self, tmp_path):
        """s3.4 register_auto_skill 写入磁盘后, 重新加载应仍可见"""
        from neurova.skills.skill_service import SkillService

        s1 = SkillService(agent_id="test", skills_dir=str(tmp_path))
        s1.register_auto_skill(skill_id="persist-1", name="persisted")

        # 模拟重启: 重新实例化
        s2 = SkillService(agent_id="test", skills_dir=str(tmp_path))
        skills = s2.list_skills()
        assert any(s["id"] == "persist-1" for s in skills), "重启后自动技能应仍可见"


class TestRegisterToSkillRegistryPersistsToSkillService:
    """测试 register_to_skill_registry 同步写入 SkillService"""

    def test_register_to_skill_registry_accepts_skill_service_param(self):
        """s3.5 register_to_skill_registry 应接受可选 skill_service 参数"""
        import inspect
        from neurova.evolution.skill_encapsulation import AutoSkillBuilder
        sig = inspect.signature(AutoSkillBuilder.register_to_skill_registry)
        assert "skill_service" in sig.parameters, (
            "register_to_skill_registry 应有 skill_service 参数"
        )
        # 默认值应为 None (向后兼容)
        assert sig.parameters["skill_service"].default is None, (
            "skill_service 默认值应为 None (向后兼容)"
        )

    def test_register_to_skill_registry_persists_to_skill_service(self, tmp_path):
        """s3.6 提供 skill_service 时, 自动技能应写入 SkillService"""
        from neurova.evolution.skill_encapsulation import AutoSkillBuilder
        from neurova.skills.skill_service import SkillService
        from neurova.skills.registry import SkillRegistry

        builder = AutoSkillBuilder(min_pattern_occurrences=2, min_success_rate=0.5)
        tool_seq = ["memory_search", "file_read"]
        for _ in range(3):
            builder.observe(
                tool_sequence=tool_seq,
                context="test",
                success=True,
                duration=0.5,
            )
        assert len(builder._templates) > 0, "前置: 应有封装的模板"

        # C10 评审闸：先批准全部待审模板再触发注册
        for _t in builder.list_pending_templates():
            assert builder.approve_template(_t["template_id"])

        registry = SkillRegistry()
        registry._skills = {}
        service = SkillService(agent_id="test", skills_dir=str(tmp_path))

        builder.register_to_skill_registry(registry, skill_service=service)

        # SkillService 应包含自动技能
        persisted = service.list_skills()
        assert len(persisted) > 0, "register_to_skill_registry 应同步写入 SkillService"

    def test_register_to_skill_registry_backward_compat_no_skill_service(self):
        """s3.7 不提供 skill_service 时, 保留原行为 (仅写 registry)"""
        from neurova.evolution.skill_encapsulation import AutoSkillBuilder
        from neurova.skills.registry import SkillRegistry

        builder = AutoSkillBuilder(min_pattern_occurrences=2, min_success_rate=0.5)
        for _ in range(3):
            builder.observe(
                tool_sequence=["tool_x"],
                context="ctx",
                success=True,
                duration=0.5,
            )

        registry = SkillRegistry()
        registry._skills = {}

        # 不传 skill_service — 应不抛异常
        count = builder.register_to_skill_registry(registry)
        assert count >= 0, "不传 skill_service 应正常工作"

    def test_register_to_skill_registry_skips_inactive_templates(self, tmp_path):
        """s3.8 非活跃 template 不写入 SkillService"""
        from neurova.evolution.skill_encapsulation import AutoSkillBuilder
        from neurova.skills.skill_service import SkillService
        from neurova.skills.registry import SkillRegistry

        builder = AutoSkillBuilder(min_pattern_occurrences=2, min_success_rate=0.5)
        for _ in range(3):
            builder.observe(
                tool_sequence=["active_tool"],
                context="ctx",
                success=True,
                duration=0.5,
            )
        # 标记所有模板为非活跃
        for tmpl in builder._templates.values():
            tmpl.is_active = False

        registry = SkillRegistry()
        registry._skills = {}
        service = SkillService(agent_id="test", skills_dir=str(tmp_path))

        builder.register_to_skill_registry(registry, skill_service=service)

        # SkillService 应为空 (没有活跃模板)
        assert len(service.list_skills()) == 0, "非活跃模板不应写入 SkillService"
