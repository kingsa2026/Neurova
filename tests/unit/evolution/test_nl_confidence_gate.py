"""014 · min_confidence 是闸，不是提示（红绿灯 TDD）。

根因（两处，缺一不可）：
1. `synthesize()` 在置信度低于阈值时只 `result.warnings.append(...)`，随后**无条件**
   `stage = COMPLETED` + `success = True`；调用方 `chat_pipeline._check_nl_synthesis`
   只看这两个字段 ⇒ 这道门不存在（G15）。
2. 阈值本身打不到：`estimate_confidence` 对任何非空描述都有 ≈0.45 的下界
   （分类 general 也给分、序列只要非空就满 25 分），而默认阈值写的是 0.3 ⇒
   低置信分支在生产口径下是死代码。只把门做实、不管门能不能被触发，仍是半截活。

落定契约：
- 低置信 ⇒ `stage = PENDING_REVIEW`（不是 COMPLETED）、`success = False`，产物仍挂在
  `synthesized_tool` 上供人工复核，`warnings` 保留为信息位但不再是唯一处置；
- 调用方不得把 PENDING_REVIEW 的产物注册进 SkillRegistry；
- 反向锁：略高于阈值的产物必须照常通过（不得靠把阈值抬到 1.0 交差）；
- 旋钮微分（对齐 004 的"事实源必须可达"）：把阈值调到实测置信度之下 ⇒ 同一描述
  必须照常通过，证明门读的是参数而不是硬编码常量。

测试一律走 `NLToolSynthesizer()` 的**生产默认装配**（agent_core.py 构造时不传
min_confidence），断言里先钉住实测置信度，估器漂移时测试会自己报出来。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from neurova.evolution.nl_synthesizer import (
    NLToolSynthesizer,
    SynthesisStage,
)

LOW_CONFIDENCE_DESC = "帮我 zzzz"
HIGH_CONFIDENCE_DESC = "搜索 文件 数据"


@pytest.fixture()
def synth():
    return NLToolSynthesizer()


def _confidence_of(synth, description: str) -> float:
    return synth.synthesize(description=description).synthesized_tool.confidence


class TestGateBites:
    def test_low_confidence_product_is_not_completed(self, synth):
        c = _confidence_of(synth, LOW_CONFIDENCE_DESC)
        assert c < synth._min_confidence, f"用例失效：{c} 并不低于默认阈值 {synth._min_confidence}"

        result = synth.synthesize(description=LOW_CONFIDENCE_DESC)
        assert result.success is False, "低置信不得报 success=True"
        assert result.synthesized_tool.stage is SynthesisStage.PENDING_REVIEW, (
            "低置信必须落在显式的待人工态，而不是 COMPLETED"
        )
        assert SynthesisStage.COMPLETED.value not in [
            getattr(s, "value", s) for s in result.stages_completed
        ]
        assert result.synthesized_tool is not None, "拦下不等于丢弃产物，人工复核要能看到它"
        assert result.warnings, "warnings 保留为信息位"

    def test_high_confidence_still_completes(self, synth):
        """反向锁：略高于阈值的产物照常放行（不得靠抬阈值交差）。"""
        c = _confidence_of(synth, HIGH_CONFIDENCE_DESC)
        assert c > synth._min_confidence, f"用例失效：{c} 并不高于默认阈值 {synth._min_confidence}"

        result = synth.synthesize(description=HIGH_CONFIDENCE_DESC)
        assert result.success is True
        assert result.synthesized_tool.stage is SynthesisStage.COMPLETED
        assert result.warnings == []

    def test_threshold_knob_is_live(self, synth):
        """旋钮微分：阈值调到实测置信度之下 ⇒ 同一描述必须放行。

        门若把阈值硬编码在别处（004 的幻影旋钮形态），这条会持续红。
        """
        c = _confidence_of(synth, LOW_CONFIDENCE_DESC)
        relaxed = NLToolSynthesizer(min_confidence=max(0.0, c - 0.01))
        result = relaxed.synthesize(description=LOW_CONFIDENCE_DESC)
        assert result.success is True, f"阈值 {relaxed._min_confidence} 低于实测 {c}，仍被拦说明门不吃参数"
        assert result.synthesized_tool.stage is SynthesisStage.COMPLETED


class TestConsumerDoesNotRegisterPendingReview:
    """调用方判据：只有 COMPLETED 的产物才进注册路径。

    靶心是"进不进注册路径"这一步：`_register_synthesized_tool` 之后还有创建治理
    （`publish_automatic` 要工具链真实执行证据）决定启不启用，那不是本闸的职责，
    所以这里把注册出口当收集器，而不是去断言 SkillRegistry 的最终内容。
    """

    class Registrar:
        def __init__(self):
            self.calls = []

        def __call__(self, registry, tool):
            self.calls.append(tool)
            return {"success": True}

    def _pipeline(self, synthesizer):
        from neurova.agent.chat_pipeline import ChatPipeline
        from neurova.skill_system import SkillRegistry

        registry = SkillRegistry()
        agent = SimpleNamespace(
            config=SimpleNamespace(agent_id="agent-nl-01"),
            tool_synthesizer=synthesizer,
            skill_manager=None,
            _skill_registry=registry,
        )
        pipeline = ChatPipeline.__new__(ChatPipeline)
        pipeline._agent = agent
        registrar = self.Registrar()
        pipeline._register_synthesized_tool = registrar
        return pipeline, registrar

    def _run(self, pipeline, user_input: str):
        ctx = SimpleNamespace(user_input=user_input)
        asyncio.run(pipeline._check_nl_synthesis(ctx, force=True))

    def test_low_confidence_product_never_reaches_registry(self, synth):
        pipeline, registrar = self._pipeline(synth)
        self._run(pipeline, LOW_CONFIDENCE_DESC)
        assert registrar.calls == [], "被置信闸拦下的产物不得进注册路径"

    def test_completed_product_still_enters_registration(self, synth):
        """正例对照：负例不是因为探针断了才看起来像拦住了。"""
        pipeline, registrar = self._pipeline(synth)
        self._run(pipeline, HIGH_CONFIDENCE_DESC)
        assert len(registrar.calls) == 1, "过闸产物仍须进入注册（门不是无条件封死）"
        assert registrar.calls[0].stage is SynthesisStage.COMPLETED
