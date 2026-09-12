"""B-11 防复活锁存：AnthropicNativeClient 同步流式桥保持已删除。

删除依据（2026-09-11 终账 B-11）：`_SyncStreamBridge` 每 chunk 新建事件
循环（asyncio.run(__anext__)），而流式主链 multi_model_client 只消费
chat_stream_async（P1 修复注释明示同步生成器无法 async for）——同步桥
零运行时调用方。async 主路径（chat / chat_stream_async）必须保留。

注：本测试刻意不 import 目标模块（其顶层依赖 aiohttp，测试环境可能
未安装），改用 find_spec + 源码文本锁存，避免环境差异误报。
"""

import importlib.util
from pathlib import Path


def test_sync_stream_bridge_class_deleted():
    spec = importlib.util.find_spec("neurova.llm.providers.anthropic_client")
    assert spec is not None and spec.origin, "anthropic_client 模块必须存在（async 主路径）"
    source = Path(spec.origin).read_text(encoding="utf-8")
    assert "_SyncStreamBridge" not in source, "同步桥 _SyncStreamBridge 不得复活（B-11 判定删除）"
    assert "\n    def chat_stream(" not in source, "同步 chat_stream 桥方法不得回归"


def test_native_client_keeps_async_stream_path_only():
    spec = importlib.util.find_spec("neurova.llm.providers.anthropic_client")
    source = Path(spec.origin).read_text(encoding="utf-8")
    assert "async def chat_stream_async" in source, "async 流式主路径必须保留"
    assert "async def chat(" in source, "chat 主路径必须保留"
