"""A-18 回归测试：ToolExecutor.tool_engine 由"双检锁懒初始化"改急切构建。

红绿说明（修复缺位时为红）：
- 原 property 用 threading.Lock 双重检查懒初始化：async 路径持同步锁
  （事件循环线程阻塞风险），且锁外首次读无保护。经核实 ToolEngine 构造
  为纯内存对象图（dict/RLock/deque + 默认守卫，无 IO/线程/网络），
  ExecutionEngine 单例组件初始化同样轻量——懒初始化无收益，改为
  __init__ 急切构建 + property 纯读，锁删除。
- 循环依赖规避不依赖懒初始化时机：_create_tool_engine 内保持函数级
  import（构建发生在 Agent 实例化期，非模块导入期），急切化不引入导入环。
"""

import builtins
from types import SimpleNamespace

from neurova.tool_executor import ToolExecutor


def _make_agent():
    return SimpleNamespace(config=SimpleNamespace(user_id="u", agent_id="a"))


class TestA18EagerToolEngine:
    def test_tool_engine_built_eagerly_in_init(self):
        """ToolExecutor 构造完成后 tool_engine 必须已就绪（不依赖首次访问触发构建）。"""
        ex = ToolExecutor(_make_agent())
        assert ex._tool_engine is not None, (
            "A-18: ToolEngine 构造轻量，应在 __init__ 急切构建；"
            "懒初始化让 async 路径持同步锁且锁外首读无保护"
        )
        assert ex.tool_engine is ex._tool_engine

    def test_no_lazy_init_lock_left_behind(self):
        """改急切构建后 DCL 互斥锁必须删除（property 纯读，无并发创建窗口）。"""
        ex = ToolExecutor(_make_agent())
        assert not hasattr(ex, "_tool_engine_lock"), (
            "A-18: property 已退化为纯读，_tool_engine_lock 不应再存在"
        )

    def test_eager_init_tolerates_engine_import_failure(self, monkeypatch):
        """ExecutionEngine/ToolEngine 导入失败时急切构建必须安静降级为 None，
        不得让 __init__ 抛异常（与原懒加载失败语义一致）。"""
        import neurova.tool_executor as te

        monkeypatch.setattr(te, "_ToolEngine", None)
        orig_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if "shared_core.execution_engine" in name or name.endswith(
                "execution_engine.tool_engine"
            ):
                raise ImportError("blocked for A-18 test")
            return orig_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        ex = ToolExecutor(_make_agent())

        assert ex._tool_engine is None
        assert ex.tool_engine is None
