# -*- coding: utf-8 -*-
"""默认 agent 的身份必须只有一处定义，且"切换默认 Agent"必须真的有下游读者。

## 要证的缺陷

`POST /api/v1/agents/{agent_id}/switch` 写的是 `_app_state["default_agent_id"]`
（`endpoints/agent.py:696`），而解析侧一律不读它：

- `endpoints.get_agent_instance(agent_id="default")` 在 `agent_id` 为空时**写死**回落
  到字面量 `"default"`（`endpoints/__init__.py:66-68`）；
- `AppState.default_agent_id` 属性在 `__init__` 里赋 `"default"`，全仓除自身
  `get_agent()` 外无人再赋值、无人再读（`app.py:48/70`）；
- 另有 6 处调用点直接把 `"default"` 当参数写死。

于是"切换默认 Agent"是一个**只写不读**的配置：端点回 200 并说
`Switched to agent 'x'`，而此后的每一次未指名解析仍然落回 `"default"`。这正是
AGENTS.md 协作红线点名的"只写不读的配置"断点形态——表现不是报错，是一个对外
承诺了却没人执行的开关。

**本文件先只做红灯。** 转绿前不得进 `scripts/ci/protected_tests.txt`。
"""

from __future__ import annotations


class _Sentinel:
    """按 agent_id 自证的哨兵：断言要能说清"解析到的到底是哪一个"。"""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id

    def __repr__(self):
        return f"<Agent {self.agent_id}>"


def _pool(monkeypatch, agents, **extra):
    from neurova.api import endpoints as ep

    state = {"agents": dict(agents)}
    state.update(extra)
    monkeypatch.setattr(ep, "_app_state", state)
    return ep


def testResolutionWrappersDelegateTheUnNamedCase(monkeypatch):
    """每个解析包装层在"未指名"时必须把决定权交给单源，而不是自己填一个名字。

    这是活体否证换来的判据：第一轮 `governance._get_agent` 写的是
    `get_agent_instance(agent_id or "default")`——单源已被修对，包装层却仍把钉死的
    名字递下去，真端点 `/rsi/status` 切换后纹丝不动，而只喂解析器的单测全绿。
    判据落在包装层，才咬得住这一层。
    """
    from neurova.api.endpoints import governance as gov

    kai = _Sentinel("kai")
    yi = _Sentinel("yi_ling")
    _pool(monkeypatch, {"default": kai, "yi_ling": yi}, default_agent_id="yi_ling")

    assert gov._get_agent(None) is yi, (
        f"governance 包装层未指名时给的是 {gov._get_agent(None)!r} ⇒ "
        "审批/RSI 面永远只认开机那一位，switch 对它无效"
    )
    # 指名而不在池中仍不回落（守住上一轮定下的语义）
    assert gov._get_agent("ghost") is None, "指名的 agent 不在池中却回落给了默认位"


def testNoCallSitePinsTheDefaultAgentIdentity():
    """解析链上不许把 agent 身份钉成 `"default"`——实参里、默认参数里都不行。

    活体第一轮否证了我最初的判据：单测直接喂 `get_agent_instance()` 时它是绿的，而真端点
    `/rsi/status` 切换后仍解析到 `'default'`——因为 `governance._get_agent` 传下去的是
    `agent_id or "default"`，包装层把钉死的名字交给单源，单源再正确也没用。同类形态在
    各端点的 `def _get_agent(agent_id: str = "default")` 里复制了约十份。

    判据因此只看两处：**传给解析器的实参**，与**解析包装层的默认参数值**。
    函数体里别处的 `"default"`（会话 id、用户名、`auth.get("agent_id", "default")` 这类
    另一件事实）不在本判据射程内——把判据写宽只会让它对真缺陷麻木。
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "neurova"
    singleSource = (root / "api" / "endpoints" / "__init__.py").resolve()
    WRAPPERS = {"get_agent_instance", "defaultAgentId", "_get_agent", "get_agent"}
    offenders = []
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts or path.resolve() == singleSource:
            continue  # 单源模块本身就是那份定义的落点
        rel = str(path.relative_to(root))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in ast.walk(tree):
            # (a) 实参里出现 default 字面量（含 `x or "default"` 这种回落）
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in WRAPPERS):
                for arg in list(node.args) + [k.value for k in node.keywords]:
                    if any(isinstance(c, ast.Constant) and c.value == "default"
                           for c in ast.walk(arg)):
                        offenders.append(f"{rel}:{node.func.lineno} 实参")
            # (b) 解析包装层自己的默认参数值
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in WRAPPERS:
                for d in node.args.defaults:
                    if isinstance(d, ast.Constant) and d.value == "default":
                        offenders.append(f"{rel}:{node.lineno} 默认参数")

    assert not offenders, (
        f"{sorted(set(offenders))} 把 agent 身份钉成字面量 ⇒ 这些环节不跟随当前默认位"
    )


def testDefaultAgentKeyLiteralHasExactlyOneHome():
    """`"default_agent_id"` 这个键名只允许出现在单源模块里。

    写侧与读侧分处两个模块各写一遍键名字面量，就是本缺陷的成因形态：一边写
    `state["default_agent_id"]`、一边读硬编码 `"default"`，两半各自都"对"，合起来
    是个不回应的开关。收口成 `defaultAgentId()` / `setDefaultAgentId()` 一对入口后，
    键名只在那一对函数体里出现一次。
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "neurova"
    allowed = (root / "api" / "endpoints" / "__init__.py").resolve()

    def _usesKey(path: Path) -> bool:
        """只认**可执行代码**里的键名使用（字符串常量/属性名）。

        docstring 里写"历史上 `_app_state[\"default_agent_id\"]` 无人读"是正当的
        病灶记录，按原文扫会把说明当违规——本仓同类守卫（工单 011 的反向锁）也按
        AST 取用，不按文本取用。
        """
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "default_agent_id":
                return True
            if isinstance(node, ast.Attribute) and node.attr == "default_agent_id":
                return True
        return False

    offenders = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
        and path.resolve() != allowed
        and _usesKey(path)
    )
    assert not offenders, (
        f"{offenders} 的代码里还出现 `default_agent_id` ⇒ 键名泄到第二个模块，"
        "写读两侧会重新分叉"
    )


def testFastApiDependencyAlsoHonoursTheSwitchedDefault(monkeypatch):
    """`deps.get_agent_instance`（FastAPI 依赖注入用）不得自持第二份默认口径。

    它原本自带 `agent_id: str = "default"` 的默认参数**并自己查一遍 agents 字典**——
    于是走依赖注入的端点与走解析器的端点对同一个"当前默认"给出不同答案。收口后
    这里只保留"取不到就 404"这层语义，解析本身委托单源。
    """
    from fastapi import HTTPException

    from neurova.api import deps

    kai = _Sentinel("kai")
    yi = _Sentinel("yi_ling")
    ep = _pool(monkeypatch, {"default": kai, "yi_ling": yi}, default_agent_id="yi_ling")

    assert deps.get_agent_instance() is ep.get_agent_instance(), (
        f"依赖注入给 {deps.get_agent_instance()!r}，解析器给 "
        f"{ep.get_agent_instance()!r} ⇒ 第二类消费者仍按自己那份默认口径取人"
    )

    # 指名而不在池中仍须 404（委托之后这层语义不能丢）
    try:
        deps.get_agent_instance("ghost")
        raise AssertionError("指名的 agent 不在池中却没抛 404")
    except HTTPException as exc:
        assert exc.status_code == 404, exc.status_code


def testAppStateAccessorAgreesWithTheResolver(monkeypatch):
    """`AppState.get_agent()`（memory/base.py 走的那条）必须与单源解析给同一个对象。

    这条是"两份定义"的直接反证：`AppState.default_agent_id` 在 `__init__` 里赋死
    `"default"` 且全仓再无人改写，而切换写的是 `_app_state` 那份状态。两份各持一半，
    表现是同一个问题有两个答案——记忆端点按"当前默认 agent"取记忆域，解析端点按另一份
    取，切了默认之后两边指向不同的人。
    """
    from neurova.api.app import AppState

    kai = _Sentinel("kai")
    yi = _Sentinel("yi_ling")
    ep = _pool(monkeypatch, {"default": kai, "yi_ling": yi}, default_agent_id="yi_ling")

    state = AppState()
    state.agents = {"default": kai, "yi_ling": yi}

    assert state.get_agent() is ep.get_agent_instance(), (
        f"`AppState.get_agent()` 给 {state.get_agent()!r}，"
        f"而 `get_agent_instance()` 给 {ep.get_agent_instance()!r} ⇒ 同一个默认位两份定义"
    )


def testSwitchedDefaultAgentIsWhatUnNamedResolutionReturns(monkeypatch):
    """切上去之后，未指名的解析必须给出被切上去的那个 agent——这才叫闭环。

    走真端点（真路由 + 真 `_get_app_state()`），因为缺陷的一半就藏在"写侧与读侧
    是不是同一份状态"里：单元测试只喂解析器，永远发现不了写的键没人读。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api.auth import get_current_user
    from neurova.api.endpoints import agent as agent_ep

    kai = _Sentinel("kai")
    yi = _Sentinel("yi_ling")
    ep = _pool(monkeypatch, {"default": kai, "yi_ling": yi})

    app = FastAPI()
    app.include_router(agent_ep.router, prefix="/api/v1/agents")
    # 覆盖的是 agent.py 实际 import 的那个 `get_current_user`（它来自
    # `neurova.api.auth`，不是 `neurova.api.deps` 的同名壳）——打错对象会得到 401，
    # 红在器械不在缺陷。
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "admin1", "role": "admin"}
    client = TestClient(app)

    switched = client.post("/api/v1/agents/yi_ling/switch")
    assert switched.status_code == 200, switched.text

    assert ep.get_agent_instance() is yi, (
        f"端点已回 `Switched to agent 'yi_ling'`，而未指名解析仍拿到 "
        f"{ep.get_agent_instance()!r} ⇒ 这个开关写的值全仓无人读，功能是不存在的"
    )
