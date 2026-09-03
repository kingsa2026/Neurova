"""
ConversationContext 封装 agent.conversation_history TDD 测试

候选 #6：把裸 list[Dict] 升级为 deep module，集中 invariant：
- role 校验（user/assistant/system）
- 长度限制（max_messages，默认 100）
- 线程安全（threading.RLock）
- 只读快照（to_list 深拷贝）

兼容性：Agent.conversation_history 保持 list 类型（property 代理 to_list()）
"""
from __future__ import annotations

import threading
from typing import Dict, List

import pytest


# ============================================================
# 1. ConversationContext 类存在性与基本结构
# ============================================================

class TestConversationContextStructure:
    """验证 ConversationContext 类定义正确"""

    def test_class_exists(self):
        """RED: neurova.conversation_context 模块存在 ConversationContext 类"""
        from neurova.conversation_context import ConversationContext
        assert ConversationContext is not None

    def test_constructor_accepts_max_messages(self):
        """RED: ConversationContext(max_messages=100) 可构造"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext(max_messages=50)
        assert ctx.max_messages == 50

    def test_default_max_messages_is_100(self):
        """RED: 默认 max_messages=100（与 mem_core.py:676 现有逻辑一致）"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext()
        assert ctx.max_messages == 100


# ============================================================
# 2. append 行为与 invariant
# ============================================================

class TestAppendBehavior:
    """验证 append 方法的 invariant"""

    def test_append_increases_length(self):
        """RED: append 后 len 增加"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext()
        ctx.append("user", "你好")
        assert len(ctx) == 1

    def test_append_stores_role_and_content(self):
        """RED: append 后 to_list 返回正确结构"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext()
        ctx.append("user", "你好")
        ctx.append("assistant", "你好，有什么可以帮你？")
        msgs = ctx.to_list()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "你好"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "你好，有什么可以帮你？"

    def test_append_rejects_invalid_role(self):
        """RED: append 拒绝非法 role（不在 user/assistant/system 中）"""
        from neurova.conversation_context import ConversationContext, InvalidRoleError
        ctx = ConversationContext()
        with pytest.raises(InvalidRoleError):
            ctx.append("bot", "非法角色")

    def test_append_accepts_system_role(self):
        """RED: append 接受 system role（用于系统消息）"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext()
        ctx.append("system", "系统提示")
        assert len(ctx) == 1

    def test_append_with_metadata(self):
        """RED: append 支持 metadata 字段"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext()
        ctx.append("user", "带元数据", metadata={"source": "test"})
        msgs = ctx.to_list()
        assert msgs[0].get("metadata") == {"source": "test"}

    def test_append_auto_trims_when_exceeding_max(self):
        """RED: append 后超过 max_messages 自动 trim（保留最新）"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext(max_messages=3)
        ctx.append("user", "msg1")
        ctx.append("assistant", "reply1")
        ctx.append("user", "msg2")
        ctx.append("assistant", "reply2")  # 此时 len=4 > 3，应 trim 到 3
        assert len(ctx) == 3
        msgs = ctx.to_list()
        # 保留最新的 3 条
        assert msgs[0]["content"] == "reply1"
        assert msgs[-1]["content"] == "reply2"


# ============================================================
# 3. to_list 只读快照
# ============================================================

class TestToListSnapshot:
    """验证 to_list 返回只读快照"""

    def test_to_list_returns_list_of_dict(self):
        """RED: to_list 返回 List[Dict]"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext()
        ctx.append("user", "test")
        result = ctx.to_list()
        assert isinstance(result, list)
        assert all(isinstance(m, dict) for m in result)

    def test_to_list_does_not_mutate_internal_state(self):
        """RED: 修改 to_list 返回值不影响内部状态"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext()
        ctx.append("user", "original")
        snapshot = ctx.to_list()
        snapshot[0]["content"] = "tampered"
        # 内部状态应保持不变
        assert ctx.to_list()[0]["content"] == "original"

    def test_to_list_empty_returns_empty_list(self):
        """RED: 空 context 的 to_list 返回 []"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext()
        assert ctx.to_list() == []


# ============================================================
# 4. extend / clear / trim
# ============================================================

class TestExtendClearTrim:
    """验证批量操作"""

    def test_extend_appends_multiple(self):
        """RED: extend 批量追加"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext()
        messages = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "reply1"},
        ]
        ctx.extend(messages)
        assert len(ctx) == 2

    def test_extend_skips_invalid_role(self):
        """RED: extend 跳过非法 role 的消息（不抛异常）"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext()
        messages = [
            {"role": "user", "content": "valid"},
            {"role": "bot", "content": "invalid"},  # 应被跳过
        ]
        ctx.extend(messages)
        assert len(ctx) == 1

    def test_clear_empties_context(self):
        """RED: clear 后 len=0"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext()
        ctx.append("user", "test")
        ctx.clear()
        assert len(ctx) == 0
        assert ctx.to_list() == []

    def test_trim_to_specific_size(self):
        """RED: trim(max_messages=N) 保留最新 N 条"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext(max_messages=100)
        for i in range(10):
            ctx.append("user", f"msg{i}")
        ctx.trim(max_messages=5)
        assert len(ctx) == 5
        msgs = ctx.to_list()
        assert msgs[0]["content"] == "msg5"
        assert msgs[-1]["content"] == "msg9"


# ============================================================
# 5. 线程安全
# ============================================================

class TestThreadSafety:
    """验证线程安全（并发 append 不丢消息）"""

    def test_concurrent_append_no_loss(self):
        """RED: 100 个线程各 append 10 条，最终 len 应为 1000（受 max_messages 限制）"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext(max_messages=10000)  # 足够大避免 trim 干扰
        threads = []
        errors = []

        def worker(tid: int):
            try:
                for i in range(10):
                    ctx.append("user", f"t{tid}-msg{i}")
            except Exception as e:
                errors.append(e)

        for tid in range(100):
            t = threading.Thread(target=worker, args=(tid,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发 append 抛出异常: {errors}"
        assert len(ctx) == 1000, f"期望 1000 条，实际 {len(ctx)}（并发丢消息）"


# ============================================================
# 6. 迭代协议
# ============================================================

class TestIterationProtocol:
    """验证 __iter__ 兼容现有 for 循环读取"""

    def test_iter_yields_messages(self):
        """RED: for msg in ctx 遍历消息"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext()
        ctx.append("user", "msg1")
        ctx.append("assistant", "reply1")
        messages = [m for m in ctx]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"

    def test_iter_returns_dict_items(self):
        """RED: 迭代返回 dict（不是 ConversationContext 内部对象）"""
        from neurova.conversation_context import ConversationContext
        ctx = ConversationContext()
        ctx.append("user", "test")
        for m in ctx:
            assert isinstance(m, dict)


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
