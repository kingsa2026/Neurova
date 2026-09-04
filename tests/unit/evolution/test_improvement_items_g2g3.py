"""§6 改进项组 2/3（B2/B3 + C9/C10/C11）契约测试。

B2 model_invocable：config.model_invocable=False 的技能不进 LLM 工具面。
B3 依赖声明：config.requires.bins 缺失时执行结果附 deps_warning（不阻断）。
C9 结晶缓冲持久化：PatternCrystallizer 观察/结晶计数落盘（buffer_state 文件），
   重启后恢复——"≥3 次结晶"不再因重启清零。
C10 技能评审闸：AutoSkillBuilder 产物默认 pending，经 approve 才进 SkillRegistry
   （create_skill 自动注册路径维持原状——由治理与注入扫描兜底，评审闸作用于
   pattern 挖掘的 AutoSkillBuilder 批量注册面）。
C11 技能使用计数：SkillService.record_skill_usage 累计 use_count/last_used_at_ms
   并持久化 manifest。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestB2ModelInvocable(unittest.TestCase):
    def test_skill_merge_skips_model_invocable_false(self):
        """_build_tools_for_llm 技能段跳过 model_invocable=False 的技能。"""
        skill = MagicMock()
        skill.name = "human_only_skill"
        skill.description = "d"
        skill.config = {"model_invocable": False}
        skill._get_parameters.return_value = {}

        registry = MagicMock()
        registry.skills = {"human_only_skill": (skill, None)}

        # 直接构造最小 self（绕过 router 段）
        from neurova.context.orchestrator import ContextOrchestrator

        self_mock = MagicMock(spec=[])
        self_mock.config = MagicMock()
        self_mock.skill_registry = registry
        self_mock.tool_router = None

        import asyncio

        from neurova.context.orchestrator import _build_tools_for_llm

        tools = asyncio.run(_build_tools_for_llm(self_mock))
        names = [t["function"]["name"] for t in tools or []]
        self.assertNotIn("human_only_skill", names)

    def test_normal_skill_still_included(self):
        skill = MagicMock()
        skill.name = "normal_skill"
        skill.description = "d"
        skill.config = {}
        skill._get_parameters.return_value = {}
        registry = MagicMock()
        registry.skills = {"normal_skill": (skill, None)}

        from neurova.context.orchestrator import _build_tools_for_llm

        self_mock = MagicMock(spec=[])
        self_mock.config = MagicMock()
        self_mock.skill_registry = registry
        self_mock.tool_router = None

        import asyncio

        tools = asyncio.run(_build_tools_for_llm(self_mock))
        names = [t["function"]["name"] for t in tools or []]
        self.assertIn("normal_skill", names)


class TestB3RequiresBins(unittest.TestCase):
    def test_missing_bins_attaches_warning(self):
        """bins 声明了不存在的命令 → deps_warning 附加，执行不阻断。"""
        from neurova.tool_executor import ToolExecutor

        executor = object.__new__(ToolExecutor)
        registry = MagicMock()
        agent = MagicMock()
        agent._skill_registry = registry
        executor._agent = agent
        skill = MagicMock()
        skill.config = {"requires": {"bins": ["definitely_not_exist_xyz_9137"]}}

        async def _fake_execute(params, context):
            return {"ok": True}

        skill.execute = _fake_execute
        registry.get_skill.return_value = skill

        import asyncio

        result = asyncio.run(executor.execute_skill_tool("s", {}))
        self.assertIn("deps_warning", result)
        self.assertIn("definitely_not_exist_xyz_9137", result["deps_warning"])

    def test_no_requires_no_warning(self):
        from neurova.tool_executor import ToolExecutor

        executor = object.__new__(ToolExecutor)
        registry = MagicMock()
        agent = MagicMock()
        agent._skill_registry = registry
        executor._agent = agent
        skill = MagicMock()
        skill.config = {}

        async def _fake_execute(params, context):
            return {"ok": True}

        skill.execute = _fake_execute
        registry.get_skill.return_value = skill

        import asyncio

        result = asyncio.run(executor.execute_skill_tool("s", {}))
        self.assertNotIn("deps_warning", result)


class TestC9CrystallizerPersistence(unittest.TestCase):
    def test_buffer_survives_reinit(self):
        """observe 后重建实例（模拟重启），缓冲计数从 state 文件恢复。"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

        with tempfile.TemporaryDirectory() as td:
            state_path = str(Path(td) / "crystal_state.json")
            engine = MagicMock()

            c1 = PatternCrystallizer(engine=engine, state_path=state_path)
            c1.observe("web_search", "搜索天气", success=True)
            c1.observe("web_search", "搜索天气", success=True)
            del c1

            c2 = PatternCrystallizer(engine=engine, state_path=state_path)
            # 恢复后第三条应触发结晶（≥3 次同一模式）
            stored = []
            engine.store.side_effect = lambda node: stored.append(node)
            c2.observe("web_search", "搜索天气", success=True)
            self.assertGreaterEqual(len(stored), 1, "恢复计数后第三次 observe 应触发结晶")


class TestC10SkillReviewGate(unittest.TestCase):
    def test_packer_registration_requires_approval(self):
        """AutoSkillBuilder.register_to_skill_registry 在 pending 模式下不注册，
        approve_template 后可注册。默认 pending（评审闸开）。"""
        from neurova.evolution.skill_encapsulation import AutoSkillBuilder

        builder = AutoSkillBuilder(min_pattern_occurrences=1, min_success_rate=0.1)
        seq = ["click", "type"]
        for _ in range(3):
            builder.observe(tool_sequence=seq, context="测试", success=True)

        # 产物进入待审集合
        pending = builder.list_pending_templates()
        self.assertTrue(pending, "评审闸开启时新产物应先入 pending")

        registry = MagicMock()
        registry.has_skill.return_value = False
        registry.register_skill.return_value = True
        registered = builder.register_to_skill_registry(registry)
        self.assertEqual(registered, 0, "未批准不得注册")

        template_id = pending[0]["template_id"] if isinstance(pending[0], dict) else pending[0]
        self.assertTrue(builder.approve_template(template_id))
        registered = builder.register_to_skill_registry(registry)
        self.assertEqual(registered, 1)


class TestC11SkillUseCount(unittest.TestCase):
    def test_record_usage_persists(self):
        from neurova.skills.skill_service import SkillService

        with tempfile.TemporaryDirectory() as td:
            svc = SkillService(agent_id="t", skills_dir=str(Path(td) / "skills"))
            svc._skills["s1"] = {"id": "s1", "name": "s1", "enabled": True}
            svc.record_skill_usage("s1", success=True)
            svc.record_skill_usage("s1", success=False)

            raw = json.loads((Path(td) / "skills" / "manifest.json").read_text(encoding="utf-8"))
            usage = raw["s1"]["usage"]
            self.assertEqual(usage["use_count"], 2)
            self.assertEqual(usage["success_count"], 1)
            self.assertGreater(usage["last_used_at_ms"], 0)

            # 重载后读取一致（持久化生效）
            svc2 = SkillService(agent_id="t", skills_dir=str(Path(td) / "skills"))
            self.assertEqual(svc2.get_skill_usage("s1")["use_count"], 2)


if __name__ == "__main__":
    unittest.main()
