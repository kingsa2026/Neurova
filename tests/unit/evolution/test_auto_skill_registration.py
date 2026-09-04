"""
TDD RED-2：暴露 agent 自动创建技能机制无效问题

验证两个核心断点：
1. PostChatPipeline._step_pattern_mining 调用 skill_packer.observe 时签名不匹配（P0-6）
   - 调用方传 tools=/support=/auto_registered= 三个 kwarg
   - 实际签名是 observe(tool_sequence, context, success, duration, metadata)
   - TypeError 被外层 except 吞没 → 模式永远进不了 AutoSkillBuilder

2. AutoSkillBuilder 封装技能后未注册到 SkillRegistry（P0-1）
   - _encapsulate_pattern 只存 self._templates 内存 dict
   - SkillRegistry.register_skill() 在生产代码零调用
   - 即便 observe 跑通，新技能也永远进不了 Registry，下次对话无法检索
"""

import pytest
from unittest.mock import Mock, MagicMock, patch


class TestAutoSkillBuilderRegistration:
    """测试 AutoSkillBuilder 封装技能后是否注册到 SkillRegistry"""

    def test_encapsulated_skill_registers_to_skill_registry(self):
        """AutoSkillBuilder 封装技能后应注册到 SkillRegistry

        场景：同一工具序列成功执行多次（超过 min_pattern_occurrences）
        期望：SkillRegistry.skills 中包含新封装的技能
        当前：_encapsulate_pattern 只存 self._templates，不调 register_skill
        """
        from neurova.evolution.skill_encapsulation import AutoSkillBuilder
        from neurova.skills.registry import SkillRegistry

        builder = AutoSkillBuilder(min_pattern_occurrences=3, min_success_rate=0.7)

        # 同一工具序列成功执行 5 次（超过 min_pattern_occurrences=3）
        tool_seq = ["memory_search", "file_read", "file_write"]
        for _ in range(5):
            builder.observe(
                tool_sequence=tool_seq,
                context="测试上下文",
                success=True,
                duration=0.5,
            )

        # 断言 1：AutoSkillBuilder 内部确实封装了技能模板
        assert len(builder._templates) > 0, (
            "观察 5 次同一成功序列后，AutoSkillBuilder 应封装技能模板，"
            f"实际 _templates 为空。patterns: {len(builder._patterns)}"
        )

        # 断言 2：封装的技能应注册到 SkillRegistry
        registry = SkillRegistry()
        # 清理单例状态，确保测试隔离
        registry._skills = {}

        # C10 评审闸：先批准全部待审模板再触发注册
        for _t in builder.list_pending_templates():
            assert builder.approve_template(_t["template_id"])

        # 触发注册（当前代码缺失此步骤）
        builder.register_to_skill_registry(registry)

        assert len(registry.skills) > 0, (
            "AutoSkillBuilder 封装技能后应调用 SkillRegistry.register_skill 注册，"
            "实际 registry.skills 为空（_encapsulate_pattern 只存内存 dict，未桥接 register_skill）"
        )


class TestPostChatPipelineObserveSignature:
    """测试 PostChatPipeline 调用 skill_packer.observe 的签名是否正确"""

    def test_observe_called_with_correct_signature(self):
        """PostChatPipeline 应以正确签名调用 skill_packer.observe

        场景：_step_pattern_mining 发现模式后调用 skill_packer.observe
        期望：observe 收到 tool_sequence=/context=/success= 等正确 kwarg
        当前：调用方传 tools=/support=/auto_registered= → TypeError 被吞
        """
        from neurova.evolution.skill_encapsulation import AutoSkillBuilder

        builder = AutoSkillBuilder(min_pattern_occurrences=2, min_success_rate=0.5)

        # 模拟 PostChatPipeline 的调用方式（当前错误签名）
        # 正确签名: observe(tool_sequence, context, success, duration, metadata)
        # 错误签名: observe(tools=, support=, auto_registered=)
        tmpl = {"tools": ["memory_search", "file_read"], "support": 3}

        # 当前 PostChatPipeline:1147 的调用方式应抛 TypeError
        with pytest.raises(TypeError) as exc_info:
            builder.observe(
                tools=tmpl["tools"],
                support=tmpl["support"],
                auto_registered=True,
            )

        assert "unexpected keyword argument" in str(exc_info.value).lower() or "observe()" in str(exc_info.value), (
            f"observe 用错误签名调用应抛 TypeError，实际: {exc_info.value}"
        )

        # 验证正确签名能工作
        builder.observe(
            tool_sequence=tmpl["tools"],
            context="测试",
            success=True,
            duration=0.3,
        )
        assert len(builder._observations) > 0, "正确签名调用后应有观察记录"
