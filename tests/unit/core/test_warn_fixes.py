"""WARN #2/#3/#4 修复测试 — 非阻塞审计项 TDD 修复

3 个审计 WARN (来自上轮 Verify 阶段审计 agent):
  WARN #2: chat_pipeline.py:300 silent suppression
    `logger.debug("SessionSyncManager event sync failed: %s", e)`
    — 异常吞掉,丢失堆栈,运维无法定位广播失败根因
    修复: 升级为 logger.warning + exc_info=True

  WARN #3: console.py:138 丢失 user_id 上下文
    `agent.chat(body.message, session_id=session_id)` 不传 metadata
    — ChatPipeline 用 "anonymous" 兜底,记忆保存/事件广播拿不到真实 user_id
    修复: 传 metadata={"user_id": user_id}

  WARN #4: session_manager.py:179-181 add_message 不检查写入返回值
    `_write_session_file_unlocked` 返回 False 时 add_message 无感知
    — 静默写入失败 → lost update 用户无感
    修复: 检查返回值,失败时 logger.error + 抛 IOError

二次优化 (本轮):
  WARN #2/#3: 源码字符串断言 → AST 断言 (鲁棒化,避免字面字符串脆弱性)
  WARN #4: 内层 `_write_session_file_unlocked` 的 `logger.error` → `logger.debug`
    理由: 外层 add_message 已带上下文 (agent_id/session_id/file_path) 记 error,
    内层重复 error 产生双 error 日志 noise. 内层降为 debug 保留诊断细节即可
    ("摘要 + 详情" 分层模式: 外层 error = 摘要, 内层 debug = 详情)
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from unittest.mock import MagicMock

import pytest


def _get_method_source(method) -> str:
    """获取方法的源码并 dedent,确保 ast.parse 能解析.

    inspect.getsource 返回类内方法时带缩进,直接 parse 会 IndentationError.
    用 textwrap.dedent 去除公共前导空格.
    """
    return textwrap.dedent(inspect.getsource(method))


# ════════════════════════════════════════════════════════════
# WARN #2: ChatPipeline._sync_event 日志级别升级
# ════════════════════════════════════════════════════════════


class TestWarn2SyncEventLogLevel:
    """WARN #2: _sync_event 不应用 debug 吞异常.

    AST 鲁棒化: 用 ast.walk 遍历 ExceptHandler 节点,检查其内部是否调
    `logger.debug(...)` (禁用) 以及是否调 `logger.warning(..., exc_info=True)`
    (必需). 替代原字面字符串断言,避免 docstring/注释措辞触发误匹配.
    """

    def test_sync_event_uses_warning_not_debug(self):
        """契约: _sync_event 的 except 块内不应调 logger.debug."""
        from neurova.agent.chat_pipeline import ChatPipeline

        source = _get_method_source(ChatPipeline._sync_event)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                for child in ast.walk(node):
                    if (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and isinstance(child.func.value, ast.Name)
                        and child.func.value.id == "logger"
                        and child.func.attr == "debug"
                    ):
                        pytest.fail(
                            "WARN #2: _sync_event 的 except 块仍调 logger.debug, "
                            "会吞异常堆栈,运维无法定位广播失败根因. "
                            "修复: 升级为 logger.warning(..., exc_info=True)."
                        )

    def test_sync_event_uses_warning_with_exc_info(self):
        """契约: _sync_event 的 except 块应调 logger.warning 且带 exc_info=True."""
        from neurova.agent.chat_pipeline import ChatPipeline

        source = _get_method_source(ChatPipeline._sync_event)
        tree = ast.parse(source)
        warning_with_exc_info = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                for child in ast.walk(node):
                    if (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and isinstance(child.func.value, ast.Name)
                        and child.func.value.id == "logger"
                        and child.func.attr == "warning"
                        and any(
                            kw.arg == "exc_info" and _is_truthy(kw.value)
                            for kw in child.keywords
                            if kw.arg
                        )
                    ):
                        warning_with_exc_info.append(child)
        assert warning_with_exc_info, (
            "WARN #2: _sync_event 的 except 块未调 logger.warning(..., exc_info=True). "
            "应保留堆栈便于运维定位根因."
        )


def _is_truthy(node: ast.AST) -> bool:
    """AST 节点是否表示真值 (用于 exc_info=True 判断)."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, ast.Name):
        # 不能静态判断 Name 真假,保守视为 truthy (调用方可能传变量)
        return node.id == "True"
    return False


# ════════════════════════════════════════════════════════════
# WARN #3: console.post_console_chat 补传 metadata
# ════════════════════════════════════════════════════════════


class TestWarn3ConsoleChatMetadata:
    """WARN #3: console 应传 metadata={"user_id": ...} 给 agent.chat.

    AST 鲁棒化: 找到 await agent.chat(...) 的 Call 节点,检查其 keywords 中
    含 metadata={...} 且 dict 字面量含 "user_id" 键. 替代原字面字符串断言,
    避免空格/引号风格变化触发误匹配.
    """

    def test_post_console_chat_passes_metadata(self):
        """契约: post_console_chat 调 agent.chat 时应传 metadata={"user_id": ...}."""
        from neurova.api.endpoints import console

        source = _get_method_source(console.post_console_chat)
        tree = ast.parse(source)
        matched_calls = []
        for node in ast.walk(tree):
            # await agent.chat(...) 或 agent.chat(...) 均匹配
            call = node.value if isinstance(node, ast.Await) and isinstance(node.value, ast.Call) else node
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "chat"):
                continue
            for kw in call.keywords:
                if kw.arg == "metadata" and isinstance(kw.value, ast.Dict):
                    for key in kw.value.keys:
                        if isinstance(key, ast.Constant) and key.value == "user_id":
                            matched_calls.append(call)
        assert matched_calls, (
            "WARN #3: post_console_chat 调 agent.chat 时未传 metadata={'user_id': ...}. "
            "导致 ChatPipeline 用 'anonymous' 兜底,记忆保存/事件广播拿不到真实 user_id. "
            "修复: agent.chat(..., metadata={'user_id': user_id})"
        )


# ════════════════════════════════════════════════════════════
# WARN #4: SessionManager.add_message 检查写入返回值
# ════════════════════════════════════════════════════════════


class TestWarn4AddMessageWriteCheck:
    """WARN #4: add_message 应检查 _write_session_file_unlocked 返回值."""

    def test_add_message_source_checks_write_return(self):
        """契约: add_message 应检查 _write_session_file_unlocked 返回值.

        AST 鲁棒化: 找到 add_message 内对 `self._write_session_file_unlocked(...)`
        的 Call 节点,要求该 Call 出现在 If.test (条件分支) 或 Assign (赋值后检查)
        上下文中. 替代原字面字符串断言,避免空格/变量名风格变化触发误匹配.
        """
        from neurova.session_manager import SessionManager

        source = _get_method_source(SessionManager.add_message)
        tree = ast.parse(source)

        # 收集所有 self._write_session_file_unlocked(...) 的 Call 节点
        write_calls = [
            node for node in ast.walk(tree)
            if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
                and node.func.attr == "_write_session_file_unlocked")
        ]
        assert write_calls, "WARN #4: add_message 未调用 _write_session_file_unlocked"

        # 检查至少有一个 Call 出现在被检查的位置:
        #   (a) 作为 If 的 test 直接被取反: `if not self._write_session_file_unlocked(...)`
        #   (b) 作为 If.test 的比较/布尔运算子表达式
        #   (c) 作为 Assign.value 赋值给变量 (后续会被检查)
        checked = False
        for call in write_calls:
            for parent in ast.walk(tree):
                # (a)/(b): call 是 If.test 的后代
                if isinstance(parent, ast.If) and _contains_node(parent.test, call):
                    checked = True
                    break
                # (c): call 是 Assign.value
                if isinstance(parent, ast.Assign) and _contains_node(parent.value, call):
                    checked = True
                    break
            if checked:
                break
        assert checked, (
            "WARN #4: add_message 调用 _write_session_file_unlocked 后未检查返回值. "
            "写入失败时静默返回成功 → lost update 用户无感. "
            "修复: 检查返回值,失败时 logger.error + 抛 IOError."
        )

    def test_add_message_raises_on_write_failure(self, tmp_path):
        """契约: 当写入失败时, add_message 应抛 IOError 而非静默成功."""
        from neurova.session_manager import SessionManager
        from neurova.session_repository import SessionRepository
        from threading import RLock

        # 用 object.__new__ 绕过单例 __init__,手动构造失败场景
        sm = object.__new__(SessionManager)
        sm._initialized = True
        sm._sessions_dir = tmp_path / "sessions"
        sm._sessions_dir.mkdir(exist_ok=True)
        sm._file_locks = {}
        sm._file_locks_lock = RLock()
        assert isinstance(sm, SessionRepository)

        # 让 _write_session_file_unlocked 返回 False (模拟写入失败)
        sm._write_session_file_unlocked = MagicMock(return_value=False)

        with pytest.raises(IOError, match="写入 session 文件失败"):
            sm.add_message(
                agent_id="test_agent",
                session_id="sess1",
                user_content="hello",
                assistant_content="hi",
            )


class TestWarn4InnerWriteLogLayering:
    """WARN #4 二次优化: 内层 _write_session_file_unlocked 失败日志应分层.

    "摘要 + 详情" 分层模式:
      - 外层 add_message: logger.error(带 agent_id/session_id/file_path 上下文) — 摘要
      - 内层 _write_session_file_unlocked: logger.debug (保留诊断细节) — 详情
    避免内外双 logger.error 产生 noise.
    """

    def test_inner_write_uses_debug_not_error(self):
        """契约: _write_session_file_unlocked except 块不应调 logger.error.

        理由: 外层 add_message 已在写入失败时 logger.error (带上下文),
        内层重复 error 会产生双 error 日志. 内层降为 debug 保留诊断细节即可.
        """
        from neurova.session_manager import SessionManager

        source = _get_method_source(SessionManager._write_session_file_unlocked)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                for child in ast.walk(node):
                    if (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and isinstance(child.func.value, ast.Name)
                        and child.func.value.id == "logger"
                        and child.func.attr == "error"
                    ):
                        pytest.fail(
                            "WARN #4 优化: _write_session_file_unlocked 的 except 块 "
                            "不应调 logger.error. 外层 add_message 已带上下文记 error, "
                            "内层重复 error 产生双日志 noise. 修复: 降为 logger.debug "
                            "(保留诊断细节作为详情层)."
                        )


# ════════════════════════════════════════════════════════════
# AST 辅助函数
# ════════════════════════════════════════════════════════════


def _contains_node(container: ast.AST, target: ast.AST) -> bool:
    """container AST 子树中是否包含 target 节点 (按对象身份比较)."""
    for node in ast.walk(container):
        if node is target:
            return True
    return False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
