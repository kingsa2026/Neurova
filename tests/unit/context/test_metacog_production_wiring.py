"""链B 教训注入的生产构造点接线回归（反思反哺闭环审计 2026-09-19）

根因：注入器的教训分支只在 `_metacog_agent_id` 非空时执行，而该值的唯一生产来源是
`ContextOrchestrator.init_context_system()` 的构造参数——该处从未传，于是自模型反思
每 10 轮写进台账的教训在生产环境没有任何一条改变下一轮行为。

既有测试在测试内手工传该 kwarg（test_metacog_lessons_injection.py:36、
test_v3_closed_loop.py:77），覆盖了契约却漏掉了布线。本文件的注入器一律取自生产
构造点，禁止测试内手工传 metacog_agent_id。
"""

import unittest
from types import SimpleNamespace

from neurova.cognitive_layers.meta_cognition_layer.ledger import (
    get_meta_ledger,
    reset_meta_ledger,
)
from neurova.cognitive_layers.meta_cognition_layer.self_model import (
    get_self_model_engine,
    reset_self_model_engine,
)
from neurova.context.envelope import parse_envelope

AGENT = "prod_wiring_agent"
FAILING_TOOL = "flaky_fetch"


def _seed_avoid_lesson():
    """45 失败 / 5 成功 → 确定性五算子产出 avoid_tool 教训并落台账。"""
    ledger = get_meta_ledger(AGENT)
    for _ in range(5):
        ledger.write_event(agent_id=AGENT, process_type="tool", description=FAILING_TOOL, success=True)
    for _ in range(45):
        ledger.write_event(agent_id=AGENT, process_type="tool", description=FAILING_TOOL, success=False)
    report = get_self_model_engine(AGENT).reflect(trigger="wiring_test")
    assert any(
        l["subject"] == FAILING_TOOL and l["recommendation"] == "avoid_tool" for l in report["lessons"]
    ), "种子必须产出 avoid_tool 教训，否则本文件验的是空集"


def _injector_from_production():
    from neurova.context.orchestrator import ContextOrchestrator

    agent = SimpleNamespace(
        config=SimpleNamespace(agent_id=AGENT, name="prod-wiring", show_empathy=True),
        memory_manager=SimpleNamespace(),
        growth_log_manager=None,
        question_queue_manager=None,
    )
    ContextOrchestrator(agent, use_pool=False).init_context_system()
    return agent.context_builder


class MetacogProductionWiringTest(unittest.TestCase):
    def setUp(self):
        reset_self_model_engine()
        reset_meta_ledger()

    def tearDown(self):
        reset_self_model_engine()
        reset_meta_ledger()

    def test_active_lesson_reaches_envelope_via_production_construction(self):
        """经生产构造点构建上下文时，活跃教训应出现在末条 user 消息的 lessons 块。"""
        _seed_avoid_lesson()
        builder = _injector_from_production()

        context = builder.build_context(
            system_prompt="base",
            memories=[],
            conversation_history=[],
            user_input="帮我抓一下这个页面",
        )

        lessons = parse_envelope(context[-1]["content"]).get("lessons", "")
        self.assertIn(FAILING_TOOL, lessons)

    def test_without_lessons_envelope_carries_no_lessons_block(self):
        """无教训时不得凭空造出 lessons 块（接线不得引入恒定噪声段）。"""
        builder = _injector_from_production()

        context = builder.build_context(
            system_prompt="base",
            memories=[],
            conversation_history=[],
            user_input="随便聊聊",
        )

        self.assertNotIn("lessons", parse_envelope(context[-1]["content"]))


if __name__ == "__main__":
    unittest.main()
