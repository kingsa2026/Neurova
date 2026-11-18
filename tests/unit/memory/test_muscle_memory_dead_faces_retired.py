"""M3 死面退役守卫：肌肉记忆三层收尾批次删除的三处无消费死面不得复活。

拍板依据（审计收尾）：
1. MemCore.muscle_memory 属性——生产从未赋值（真实句柄是
   agent.tool_memory.muscle_memory，见 agent_core.py 装配点），死读取面；
2. ContextBuilder._merge_tool_memory——消费 check_tool_memory 返回中
   不存在的 memories 键，空转支路；
3. ToolExecutor.execute_from_memory_async——自动执行链已由
   ChatPipeline._auto_execute_tool 经 ToolExecutionManager 承担，本方法
   无生产调用方。

守卫形态参照 test_neuhebb_retired.py：退役面以「不存在」断言钉死，
复活须先改本守卫并重走拍板。
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


class TestMemCoreMuscleMemoryPropertyRetired:
    def test_class_level_property_gone(self):
        from neurova.mem_core import MemCore

        assert not hasattr(MemCore, "muscle_memory"), (
            "MemCore.muscle_memory 已退役（真实句柄是 agent.tool_memory.muscle_memory）"
            "——复活须先改本守卫并重走拍板"
        )

    def test_instance_level_read_gone(self):
        from neurova.mem_core import MemCore

        mem_core = MemCore(MagicMock())
        assert not hasattr(mem_core, "muscle_memory"), (
            "MemCore 实例不得再暴露 muscle_memory 死读取面"
        )

    def test_source_has_no_property_remains(self):
        source = (_REPO_ROOT / "neurova" / "mem_core.py").read_text(encoding="utf-8")
        assert "def muscle_memory" not in source, (
            "mem_core.py 仍残留 muscle_memory property 死面"
        )


class TestBuilderMergeToolMemoryRetired:
    def test_method_gone(self):
        from neurova.context.builder import ContextBuilder

        assert not hasattr(ContextBuilder, "_merge_tool_memory"), (
            "ContextBuilder._merge_tool_memory 已退役（消费不存在的 memories 键，"
            "空转支路）——复活须先改本守卫并重走拍板"
        )

    def test_source_has_no_merge_remains(self):
        source = (_REPO_ROOT / "neurova" / "context" / "builder.py").read_text(
            encoding="utf-8"
        )
        # 只钉"能跑起来的复活"（定义/调用），退役说明注释里提到名字是正当的
        # （形态参照 test_neuhebb_retired.py）
        assert "def _merge_tool_memory" not in source, (
            "builder.py 仍残留 _merge_tool_memory 定义"
        )
        assert "._merge_tool_memory(" not in source, (
            "builder.py 仍残留 _merge_tool_memory 调用"
        )


class TestExecuteFromMemoryAsyncRetired:
    def test_method_gone(self):
        from neurova.tool_executor import ToolExecutor

        assert not hasattr(ToolExecutor, "execute_from_memory_async"), (
            "ToolExecutor.execute_from_memory_async 已退役（自动执行链由 "
            "ChatPipeline._auto_execute_tool 承担，本方法无生产调用方）"
            "——复活须先改本守卫并重走拍板"
        )

    def test_source_has_no_async_from_memory_remains(self):
        source = (_REPO_ROOT / "neurova" / "tool_executor.py").read_text(
            encoding="utf-8"
        )
        # 只钉"能跑起来的复活"（定义），退役说明注释里提到名字是正当的
        assert "def execute_from_memory_async" not in source, (
            "tool_executor.py 仍残留 execute_from_memory_async 定义"
        )
