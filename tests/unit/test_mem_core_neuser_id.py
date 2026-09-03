"""红绿灯 TDD：mem_core 三级隔离漏传 neuser_id (C7)。

全链路根因：MemCore.init_memory_modules 的方法签名已接收 neuser_id（三级隔离第2级：
系统用户隔离），但在构造 MemoryManager 时漏传该参数。MemoryManager 支持 neuser_id
参数，漏传会让记忆隔离退化为两级，跨系统用户数据可能串档。

init_memory_modules 在内部用 `from <module> import <Class>` 导入 10 个重依赖。测试通过
monkeypatch builtins.__import__，按真实模块路径拦截这些导入并返回 Stub / RecordingMM，
再断言 MemoryManager 实际收到的 neuser_id。

当前 bug：init_memory_modules 未把 neuser_id 传给 MemoryManager →
captured['neuser_id'] == "default" != "ne_abc" → 断言失败（红）。
修复后应 == "ne_abc"（绿）。
"""
from __future__ import annotations

import builtins
import types
from types import SimpleNamespace

from neurova.mem_core import MemCore

# init_memory_modules 内部真实的 `from <module> import <Class>` 路径
_TARGET_MODULES = {
    "neurova.cognitive_layers.memory_layer.conversation_buffer": {
        "ConversationMemoryBuffer",
        "MemoryWriteQueue",
    },
    "neurova.cognitive_layers.memory_layer.manager": {"MemoryManager"},
    "neurova.cognitive_layers.memory_layer.modules.buffer_module": {"BufferModule"},
    "neurova.cognitive_layers.memory_layer.temperature": {"TemperatureEngine"},
    "neurova.cognitive_layers.memory_layer.working_memory": {"WorkingMemoryAugmenter"},
    "neurova.cognitive_layers.meta_cognition_layer.growth_log": {"GrowthLogManager"},
    "neurova.cognitive_layers.meta_cognition_layer.question_queue": {
        "QuestionQueueManager"
    },
    "neurova.cognitive_layers.memory_layer.attachment_manager": {"AttachmentManager"},
    "neurova.cognitive_layers.memory_layer.muscle_memory": {"MuscleMemory"},
    "neurova.cognitive_layers.memory_layer.tool_memory_integration": {
        "ToolMemoryIntegration"
    },
}


def test_init_memory_modules_forwards_neuser_id(monkeypatch):
    captured: dict = {}

    class RecordingMemoryManager:
        def __init__(
            self,
            db_path,
            agent_id="default",
            neuser_id="default",
            user_id="default",
            enable_buffer=True,
        ):
            captured["db_path"] = db_path
            captured["agent_id"] = agent_id
            captured["neuser_id"] = neuser_id
            captured["user_id"] = user_id

    class Stub:
        def __init__(self, *args, **kwargs):
            pass

        @classmethod
        def from_agent_config(cls, *args, **kwargs):
            return cls()

    orig_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in _TARGET_MODULES:
            fake = types.ModuleType(name)
            for attr in fromlist:
                if attr in _TARGET_MODULES[name]:
                    cls = RecordingMemoryManager if name.endswith(".manager") else Stub
                    setattr(fake, attr, cls)
            return fake
        return orig_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    mem = SimpleNamespace(
        config=SimpleNamespace(
            db_path=":memory:",
            agent_id="agent_x",
            name="test_agent",
            workspace_path="/tmp/ws",
            attachment_dir="/tmp/att",
        ),
        _agent=SimpleNamespace(),
    )

    MemCore.init_memory_modules(mem, neuser_id="ne_abc", user_id="u_xyz")

    assert captured["neuser_id"] == "ne_abc"
    assert captured["agent_id"] == "agent_x"
    assert captured["user_id"] == "u_xyz"
