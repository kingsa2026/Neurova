"""AgentModule._on_stop 不得丢弃 shutdown 协程

背景：Agent.shutdown 是 async def，而 Module 的 _on_stop 是同步钩子（在事件循环
线程内被 startup_manager.stop() 调用，先于/伴随进程退出）。原实现直接
agent.shutdown()——协程被创建后立刻丢弃：资源不释放 + "coroutine was never
awaited" RuntimeWarning。

职责归属：Agent 的关闭统一由异步 _on_shutdown() 负责（真正 await 且带超时），
且其先于 startup_manager.stop() 执行。本测试固定：模块停止不得对 agent 发起
注定被丢弃的 shutdown 调用。

FakeAgent 在 shutdown() 被调用（即协程被创建）的瞬间计数——被丢弃的协程体
永远不执行，所以"协程体计数"无法区分调用与否，必须记在调用点。
"""

from types import SimpleNamespace

from neurova.api import app as app_module


class _FakeAgent:
    def __init__(self):
        self.shutdown_calls = 0

    def shutdown(self):
        # 镜像 async def 的调用侧行为：调用即创建协程并返回，协程体不执行
        self.shutdown_calls += 1

        async def _shutdown():
            pass

        return _shutdown()


def _build_module(agent: _FakeAgent):
    """走真实的 _register_core_modules 路径拿到 AgentModule 类并实例化"""

    class _FakeStartupManager:
        def __init__(self):
            self.registered = {}

        def register_module(self, name, module_cls, dependencies=None):
            self.registered[name] = module_cls

    fake_state = SimpleNamespace(
        startup_manager=_FakeStartupManager(),
        get_agent=lambda agent_id=None: agent,
    )
    app_module._register_core_modules(fake_state)
    module_cls = fake_state.startup_manager.registered["agent"]
    return module_cls()


def test_agent_module_stop_does_not_drop_shutdown_coroutine():
    agent = _FakeAgent()
    module = _build_module(agent)
    # Module 状态机 CREATED -> initialize() -> start() -> stop()，stop 只在 RUNNING 态执行 _on_stop
    assert module.initialize() and module.start()

    module.stop()

    assert agent.shutdown_calls == 0, (
        "AgentModule._on_stop 是同步钩子，无法 await shutdown；"
        "在此调用只会创建被丢弃的协程，agent 关闭应由异步 _on_shutdown 统一负责"
    )
