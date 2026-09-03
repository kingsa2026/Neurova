"""
审批回复跨事件循环测试

测试目标：验证 asyncio.Event 跨事件循环的问题
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestApprovalCrossEventLoop:
    """测试审批回复的跨事件循环问题"""

    def test_approval_event_cross_event_loop_issue(self):
        """测试: 跨事件循环/跨线程的审批回复（现行方案：threading.Event）

        历史问题：asyncio.Event 在另一个事件循环的线程里 set()，
        主循环可能无法感知。现行 exec_approval 已改用 threading.Event
        + run_in_executor 等待，天然跨线程安全。本测试锁定该契约。
        """
        import threading

        approval_event = threading.Event()
        approval_result = {"approved": None, "reason": ""}

        def on_approval_reply(message_content: str) -> bool:
            """处理审批回复（同步，可在任意线程调用）"""
            content_lower = message_content.lower().strip()
            approve_keywords = ["approve", "批准", "同意", "通过", "ok", "yes", "是"]
            reject_keywords = ["reject", "拒绝", "驳回", "不通过", "no", "否"]
            for keyword in approve_keywords:
                if keyword in content_lower:
                    approval_result["approved"] = True
                    approval_event.set()
                    return True
            for keyword in reject_keywords:
                if keyword in content_lower:
                    approval_result["approved"] = False
                    approval_result["reason"] = content_lower or "未说明原因"
                    approval_event.set()
                    return True
            return False

        # 模拟消息处理器（与 exec_approval 中的闭包一致）
        approver = "user_123"

        def message_handler(message):
            if hasattr(message, "sender_id") and message.sender_id == approver:
                content = message.content if hasattr(message, "content") else str(message)
                on_approval_reply(content)
            return None

        # 在另一个事件循环的线程中触发消息处理器（模拟渠道回调）
        class MockMessage:
            content = "同意"
            sender_id = approver

        def trigger_in_other_loop():
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(message_handler(MockMessage()))
            finally:
                loop.close()

        t = threading.Thread(target=trigger_in_other_loop)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive(), "回调线程应正常结束"

        # 主线程等待（threading.Event 跨线程可见）
        assert approval_event.wait(timeout=2), "threading.Event 应跨线程唤醒等待方"
        assert approval_result["approved"] is True

    def test_approval_event_same_event_loop(self):
        """测试: 同一事件循环中的审批事件"""
        
        # 模拟 exec_approval 中的 approval_event
        approval_event = asyncio.Event()
        approval_result = {"approved": None, "reason": ""}
        
        # 模拟审批人回复的关键词匹配逻辑
        async def on_approval_reply(message_content: str) -> bool:
            """处理审批回复"""
            content_lower = message_content.lower().strip()
            
            # 批准关键词
            approve_keywords = ["approve", "批准", "同意", "通过", "ok", "yes", "是"]
            # 拒绝关键词
            reject_keywords = ["reject", "拒绝", "驳回", "不通过", "no", "否"]
            
            for keyword in approve_keywords:
                if keyword in content_lower:
                    approval_result["approved"] = True
                    approval_event.set()
                    return True
            
            for keyword in reject_keywords:
                if keyword in content_lower:
                    approval_result["approved"] = False
                    # 提取拒绝原因
                    for kw in reject_keywords:
                        content_lower = content_lower.replace(kw, "").strip()
                    approval_result["reason"] = content_lower or "未说明原因"
                    approval_event.set()
                    return True
            
            return False
        
        # 模拟消息处理器
        async def message_handler(message):
            """消息处理器 — 过滤审批回复"""
            # 只处理来自审批人的消息
            if hasattr(message, 'sender_id') and message.sender_id == "user_123":
                # 尝试解析审批回复
                content = message.content if hasattr(message, 'content') else str(message)
                await on_approval_reply(content)
            return None  # 不自动回复
        
        # 在同一事件循环中执行所有操作
        async def run_test():
            """运行测试"""
            # 创建模拟消息
            approve_message = MagicMock()
            approve_message.content = "同意"
            approve_message.sender_id = "user_123"
            
            # 在同一事件循环中触发消息处理器
            await message_handler(approve_message)
            
            # 等待审批事件
            try:
                await asyncio.wait_for(approval_event.wait(), timeout=1)
                return {"status": "success", "approved": approval_result["approved"]}
            except asyncio.TimeoutError:
                return {"status": "timeout", "approved": None}
        
        # 运行测试
        result = asyncio.run(run_test())
        
        # 验证: 同一事件循环中审批事件应该被触发
        assert result["status"] == "success"
        assert result["approved"] is True

    def test_approval_event_with_shared_event_loop(self):
        """测试: 使用共享事件循环的审批事件"""
        
        # 模拟 exec_approval 中的 approval_event
        approval_event = asyncio.Event()
        approval_result = {"approved": None, "reason": ""}
        
        # 模拟审批人回复的关键词匹配逻辑
        async def on_approval_reply(message_content: str) -> bool:
            """处理审批回复"""
            content_lower = message_content.lower().strip()
            
            # 批准关键词
            approve_keywords = ["approve", "批准", "同意", "通过", "ok", "yes", "是"]
            # 拒绝关键词
            reject_keywords = ["reject", "拒绝", "驳回", "不通过", "no", "否"]
            
            for keyword in approve_keywords:
                if keyword in content_lower:
                    approval_result["approved"] = True
                    approval_event.set()
                    return True
            
            for keyword in reject_keywords:
                if keyword in content_lower:
                    approval_result["approved"] = False
                    # 提取拒绝原因
                    for kw in reject_keywords:
                        content_lower = content_lower.replace(kw, "").strip()
                    approval_result["reason"] = content_lower or "未说明原因"
                    approval_event.set()
                    return True
            
            return False
        
        # 模拟消息处理器
        async def message_handler(message):
            """消息处理器 — 过滤审批回复"""
            # 只处理来自审批人的消息
            if hasattr(message, 'sender_id') and message.sender_id == "user_123":
                # 尝试解析审批回复
                content = message.content if hasattr(message, 'content') else str(message)
                await on_approval_reply(content)
            return None  # 不自动回复
        
        # 使用共享事件循环
        async def run_test():
            """运行测试"""
            # 创建模拟消息
            approve_message = MagicMock()
            approve_message.content = "同意"
            approve_message.sender_id = "user_123"
            
            # 在同一事件循环中触发消息处理器
            await message_handler(approve_message)
            
            # 等待审批事件
            try:
                await asyncio.wait_for(approval_event.wait(), timeout=1)
                return {"status": "success", "approved": approval_result["approved"]}
            except asyncio.TimeoutError:
                return {"status": "timeout", "approved": None}
        
        # 运行测试
        result = asyncio.run(run_test())
        
        # 验证: 共享事件循环中审批事件应该被触发
        assert result["status"] == "success"
        assert result["approved"] is True