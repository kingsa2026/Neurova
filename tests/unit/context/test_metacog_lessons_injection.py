"""V3 遗留收口测试：教训上下文注入 + 调控门 + /lessons 过期口径

- ③ 行为改变通道②：injector 把活跃教训注入系统提示（metacog_agent_id 经 kwargs）
- 过期教训不注入（与调控门/端点同口径）
- 未配置 metacog_agent_id 时零行为变化（不注入）
"""

import unittest

from neurova.cognitive_layers.meta_cognition_layer.ledger import (
    get_meta_ledger,
    reset_meta_ledger,
)
from neurova.cognitive_layers.meta_cognition_layer.self_model import (
    get_self_model_engine,
    reset_self_model_engine,
)

AGENT = "inject_agent"


class MetacogLessonsInjectionTest(unittest.TestCase):
    def setUp(self):
        reset_self_model_engine()
        reset_meta_ledger()

    def tearDown(self):
        reset_self_model_engine()
        reset_meta_ledger()

    def _make_injector(self, agent_id=None):
        from types import SimpleNamespace
        from neurova.context.injector import UnifiedContextInjector

        mm = SimpleNamespace()
        kwargs = {"metacog_agent_id": agent_id} if agent_id else {}
        injector = UnifiedContextInjector(memory_manager=mm, enable_cache=False, **kwargs)
        return injector

    def _seed_lesson(self, tool="bad_tool"):
        ledger = get_meta_ledger(AGENT)
        for _ in range(5):
            ledger.write_event(agent_id=AGENT, process_type="tool", description=tool, success=True)
        for _ in range(45):
            ledger.write_event(agent_id=AGENT, process_type="tool", description=tool, success=False)
        engine = get_self_model_engine(AGENT)
        report = engine.reflect(trigger="test")
        assert any(l["recommendation"] == "avoid_tool" for l in report["lessons"])
        return engine

    def test_lessons_injected_into_system_prompt(self):
        """配置 agent_id 后，活跃教训应出现在系统提示的自我认知教训段。"""
        self._seed_lesson()
        injector = self._make_injector(agent_id=AGENT)
        content = injector._build_metacog_lessons(AGENT)
        self.assertIn("bad_tool", content)
        self.assertIn("drift", content)

    def _expired_lesson_content(self, injector):
        import datetime

        ledger = get_meta_ledger(AGENT)
        expired = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        ).isoformat()
        with ledger._lock:
            ledger._conn.execute(
                "UPDATE meta_records SET metadata=json_set(metadata, '$.expires_at', ?)"
                " WHERE agent_id=? AND kind='lesson'",
                (expired, AGENT),
            )
            ledger._conn.commit()
        return injector._build_metacog_lessons(AGENT)

    def test_expired_lessons_not_injected(self):
        """过期教训不注入（与调控门同口径）。"""
        self._seed_lesson()
        injector = self._make_injector(agent_id=AGENT)
        content = self._expired_lesson_content(injector)
        self.assertEqual(content, "")

    def test_no_agent_id_no_injection(self):
        """未配置 metacog_agent_id → _build_metacog_lessons 不被调用（默认路径零变化）。"""
        injector = self._make_injector()
        self.assertIsNone(injector._metacog_agent_id)


if __name__ == "__main__":
    unittest.main()
