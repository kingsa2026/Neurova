"""EKB 注入侧接通回归测试（经验结晶闭环审计 2026-09-04 修复 ⑤）

断点⑤：Phase 4 重构后 build_context 恒传 experience=[]（非 None），
injector 的 `_build_experience_context`（EKB 查询）成为不可达分支——EKB 每轮写入
（3245 条）但主聊天路径永不消费。
修复：experience 为空列表时回退查询 EKB；仅显式传入非空列表（池预检索命中）时
跳过二次查询。同时对齐写读契约（写端存 reply_excerpt、读端读 reply_excerpt）。

附带修复的必炸 bug：injector 两处 `self.log_info(msg, data)` 双参调用与真实
BaseModule.log_info(message) 单参契约错位——build_context 尾部 TypeError，
统一注入器路径整体失效（被上游 except 吞掉降级）。修复后本文件所有用例
同步调用 build_context 必须无异常返回，即是该 bug 的防回归断言。
"""

from unittest.mock import MagicMock, patch

from neurova.context.injector import UnifiedContextInjector


def _make_injector():
    memory_manager = MagicMock()
    return UnifiedContextInjector(
        memory_manager=memory_manager, enable_cache=False, enable_compression=False
    )


def _build(injector, experience):
    return injector.build_context(
        system_prompt="base",
        memories=[],
        conversation_history=[{"role": "user", "content": "hi"}],
        user_input="帮我查北京天气",
        experience=experience,
    )


_EKB_RECORD = {
    "skill_name": "chat",
    "context": {"user_input": "查北京天气怎么样"},
    "result": {"reply_excerpt": "北京今天晴，25 度"},
    "success": 1,
}

_FIND = (
    "neurova.skills.experience_knowledge_base."
    "ExperienceKnowledgeBase.find_similar_experiences"
)


class TestEkbFallbackOnEmptyList:
    def test_empty_list_falls_back_to_ekb_query(self):
        injector = _make_injector()
        with patch(_FIND, return_value=[_EKB_RECORD]) as mock_find:
            result = _build(injector, [])
            assert mock_find.called
            kwargs = mock_find.call_args.kwargs
            assert kwargs["context"]["user_input"] == "帮我查北京天气"
        assert result.context

    def test_ekb_hits_injected_into_system_prompt(self):
        injector = _make_injector()
        with patch(_FIND, return_value=[_EKB_RECORD]):
            result = _build(injector, [])
        system = result.context[0]["content"]
        assert "相关经验" in system
        assert "北京今天晴" in system

    def test_pooled_hits_skip_second_query(self):
        """池预检索命中（非空列表）不触发二次查询"""
        injector = _make_injector()
        with patch(_FIND) as mock_find:
            result = _build(
                injector,
                [{"context": "池内经验", "result": "池内结果", "success": True}],
            )
            mock_find.assert_not_called()
        system = result.context[0]["content"]
        assert "池内经验" in system

    def test_reply_excerpt_contract(self):
        """写读契约对齐：读端取 reply_excerpt（写端 post_chat 存的就是它）"""
        injector = _make_injector()
        with patch(_FIND, return_value=[_EKB_RECORD]):
            result = _build(injector, [])
        system = result.context[0]["content"]
        assert "北京今天晴" in system

    def test_ekb_failure_degrades_to_empty(self):
        """EKB 查询失败不影响上下文构建"""
        injector = _make_injector()
        with patch(_FIND, side_effect=RuntimeError("db locked")):
            result = _build(injector, [])
        assert result.context  # 构建未崩

    def test_none_experience_still_queries_ekb(self):
        """None（调用方未传）维持原回退行为"""
        injector = _make_injector()
        with patch(_FIND, return_value=[_EKB_RECORD]) as mock_find:
            _build(injector, None)
            assert mock_find.called
