# -*- coding: utf-8 -*-
"""NL 合成工具名必须携带身份（Issue #189）：同名覆盖的**产生侧**根因。

病灶：`NLToolSynthesizer._generate_tool_name` 只按 category（或描述里前 3 个
ASCII 词）拼名字，与产物身份 `tool_id = synth_<hex8>` 无关。于是任意两条
「中文描述 + 同一 category」的合成产物都叫 `ai_tool` / `general_tool`——
身份不同、名字相同。

而 `SkillRegistry` 按 `skill.name` 建键（ADR 0019：查询键 = name，记账键 =
identity），后到者**静默**顶掉先到者：`tool.name` 已经定了，注册表里那条先到者
在工具面上直接消失。本次启动实测累计 10 次（`ai_tool` / `general_tool`）。

为什么修在名字这一侧：三条写入臂里另两条（`skill_encapsulation._generate_skill_name`
带 `pattern_id`、`genetic_engine` 直接用身份当名字）早已携带身份，只有 NL 合成这条
臂在自造无名身份的名字——这是"同契约的某个生产方漏做"，不是注册表的事。
注册表按 name 建键的键域迁移是 ADR 0019 明确留的另单，不在本单硬拒存量。
"""
from __future__ import annotations

import re

import pytest

from neurova.evolution.nl_synthesizer import NLToolSynthesizer

_OPENAI_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


@pytest.fixture
def synth():
    return NLToolSynthesizer()


class TestDistinctSynthesisGetsDistinctName:
    def test_same_category_different_intent_do_not_share_a_name(self, synth):
        """两条中文描述（都会回退到 category）不得产出同一个工具名。"""
        first = synth.synthesize(description="用模型预测销量趋势")
        second = synth.synthesize(description="用模型识别图片里的猫狗")
        assert first.success and second.success, "合成未成功，判据前提失效"
        name_a = first.synthesized_tool.name
        name_b = second.synthesized_tool.name
        identity_a = first.synthesized_tool.tool_id
        identity_b = second.synthesized_tool.tool_id
        assert identity_a != identity_b, "两条产物的身份应当不同"
        assert name_a != name_b, (
            f"身份不同（{identity_a} / {identity_b}）却同名（{name_a}）——"
            "注册表按 name 建键，后到者会静默顶掉先到者（工具面少一个）"
        )

    def test_general_category_does_not_collide_either(self, synth):
        """general 分类（无 ASCII 词，回退到 category）同样不得撞名。"""
        a = synth.synthesize(description="帮我随便处理一下某个未知的事情")
        b = synth.synthesize(description="看看这个东西有没有类似的案例，请帮我处理需要的东西")
        assert a.success and b.success, "合成未成功，判据前提失效"
        assert a.synthesized_tool.category == b.synthesized_tool.category
        assert a.synthesized_tool.name != b.synthesized_tool.name


class TestNameStillObeysTheToolNameContract:
    """名字仍然必须是合法 OpenAI 工具名（T-3 修复不能被本单回退）。"""

    @pytest.mark.parametrize(
        "description",
        ["帮我搜索文件", "读取配置文件", "用模型预测销量", "generate a report"],
    )
    def test_name_is_ascii_within_64_chars(self, synth, description):
        name = synth._generate_tool_name(description, synth.detect_category(description))
        assert _OPENAI_NAME.match(name), f"工具名不合法: {name!r}（长度 {len(name)}）"

    def test_long_ascii_description_stays_within_limit(self, synth):
        name = synth._generate_tool_name(
            "please analyze and transform the quarterly revenue dataset thoroughly", "data"
        )
        assert _OPENAI_NAME.match(name), f"工具名超长或含非法字符: {name!r}（长度 {len(name)}）"


class TestGeneratorCarriesTheIdentityItWasGiven:
    def test_namingFunctionUsesTheIdentityWhenProvided(self, synth):
        """名字生成器要能接收身份——否则它无从知道"这俩是不是同一条产物"。"""
        name = synth._generate_tool_name("用模型预测销量", "ai", tool_id="synth_ab12cd34")
        assert "synth_ab12cd34" in name, (
            "名字未携带身份：注册表按 name 建键时无从区分同 category 的两条产物"
        )


class TestRegistryNoLongerSeesTheseCollisions:
    def test_registry_collision_count_stays_zero_for_two_syntheses(self, synth):
        """放大视角自证：走注册表这条真链路，两条产物不再触发同名覆盖。"""
        from neurova.skill_system import Skill, SkillRegistry

        registry = SkillRegistry()
        for result in (
            synth.synthesize(description="用模型预测销量趋势"),
            synth.synthesize(description="用模型识别图片里的猫狗"),
        ):
            tool = result.synthesized_tool
            skill = Skill(tool.name, tool.description)
            skill.skill_id = tool.tool_id
            skill.config = {"skill_id": tool.tool_id}
            registry.register(skill)
        assert getattr(registry, "_name_collision_count", 0) == 0, (
            "同名覆盖仍被触发——名字侧根因未修净"
        )
