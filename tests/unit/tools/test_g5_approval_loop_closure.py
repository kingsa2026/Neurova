# -*- coding: utf-8 -*-
"""G5 审批闭环红测：ASK 的裁决结果无路回到模型与会话（先红，不含实现）。

## 要证的缺陷（一条链路四处断点）

现状是：模型调用工具 → 治理判 `ASK` → 咽喉返回
`{"success": False, "pending_approval": True, "approval_id": ...}` 作为**工具结果**，
循环不等待，模型对着一条"失败"继续推理。人工在前端点"批准"后，
`governance.approve_and_execute` 确实会按 metadata 里的 `tool_name/params` **真执行**，
但结果只进了那个 approve 请求的 **HTTP 响应体**（`governance.py:219`）。

于是原调用在模型视角**永久悬空**：它以为用户还没确认，而工具其实已经跑完了。
按 `AGENTS.md` 协作红线，这正是"写出无人读的字段 / 注册无消费者的模块"的形态。

四处断点各自钉一条：

| # | 断点 | 判据 |
|---|------|------|
| A | **写侧没有回投地址**：审批记录 metadata 只有 `tool_name/params/governance`，无 `session_id`/`tool_call_id` | 即使想回投也无路可寻 |
| B | **读侧没有投递**：批准重放成功后，结果不进任何会话面向 | 模型/用户后续对话看不到 |
| C | **信号通道零订阅者**：`register_notification_callback` 生产侧无调用方，`approval_result` 回调遍历空列表 | 只写不读的事件 |
| D | **没有有界等待**：既不阻塞，也就没有超时键；一旦实现阻塞而无界，会退化成永久挂起 | 参照侧正是栽在这一步 |

## 为什么这些断言"现在必然红"

不依赖任何未发布的内部接口，只依赖两件事：
① 生产装配点自己的源码事实（A/C/D 为纯静态反证，零重型导入，不引入模块层副作用）；
② B 直接调用生产端点函数 `approve_and_execute`，用替身把审批记录与 agent 注入，
   断言"执行结果必须送达会话"——这条今天无人送达，故红。

**本文件只做红灯，不含实现。** 转绿前不得进 `scripts/ci/protected_tests.txt`。
"""

from __future__ import annotations

import ast
import inspect
import typing
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_NEUROVA = _REPO / "neurova"


class _AskVerdict:
    """治理 ASK 裁决的最小替身：只带被测分支真读的两个成员。"""

    reasons = ("需要人工确认",)

    @staticmethod
    def to_dict():
        return {"decision": "ask", "reasons": ["需要人工确认"]}


def _readSource(relPath: str) -> str:
    return (_NEUROVA / relPath).read_text(encoding="utf-8")


def _functionNode(source: str, name: str) -> ast.AST:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"生产侧找不到函数定义 {name}——判据本身失效，先修守卫")


# ───────────────────────────────────────────────────────────────
# A · 写侧没有回投地址
# ───────────────────────────────────────────────────────────────


def testApprovalRecordCarriesReturnAddress():
    """ASK 创建的审批记录必须带"回到哪"的地址，否则反馈无路可走。

    实测缺陷：`tool_executor._create_approval_request` 的 metadata 只有
    tool_name / params / governance 三键 —— 没有 session_id，也没有 tool_call_id。
    后果：批准重放完成后，没有任何字段能指出该把结果送回哪一次调用、哪一个会话，
    "回投"这件事不是没人做，是**做不了**。

    为什么走行为而不是扫源码字面键：实现可以把地址收进一个 helper 再用
    `**` 展开（本仓的正当写法），扫字面键的判据会被这种写法**假绿**——
    判据比实现弱就等于没有判据。故此处真调生产方法，验实际落库的 metadata。
    """
    import neurova.tool_executor as te

    created: typing.List[typing.Dict[str, typing.Any]] = []

    class _Store:
        def create_approval_request(self, **kw):
            created.append(kw)

            class _R:
                request_id = "apr_a1"

            return _R()

    class _Verdict:
        reasons = ("danger",)

        @staticmethod
        def to_dict():
            return {"decision": "ask"}

    class _Executor(te.ToolExecutor):
        """只换掉"外部世界"（agent 身份、审批存储），被验的生产方法本身不替身。"""

        def _agent_identity(self):
            return ("u1", "a1")

    monkey = _Executor.__new__(_Executor)  # 绕开重型 __init__；被测方法不依赖其字段
    monkey._agent_identity = _Executor._agent_identity.__get__(monkey)

    from neurova.core.turn_context import set_turn_identity, set_turn_tool_call_id

    set_turn_identity("q", session_id="sess_a", user_id="u1")
    set_turn_tool_call_id("call_a")

    originalStore = te._get_approval_manager
    te._get_approval_manager = lambda: _Store()
    try:
        requestId = monkey._create_approval_request("exec_command", {"command": "ls"}, _Verdict())
    finally:
        te._get_approval_manager = originalStore

    assert requestId == "apr_a1", f"审批请求未创建（返回 {requestId!r}）"
    assert created, "生产方法没有调用 create_approval_request——判据需随实现更新"
    metadata = created[0]["metadata"]
    assert metadata.get("session_id") == "sess_a", (
        f"审批记录缺会话地址（metadata={sorted(metadata)}，session_id={metadata.get('session_id')!r}）"
        "⇒ 批准后的执行结果无路返回原会话"
    )
    assert metadata.get("tool_call_id") == "call_a", (
        f"审批记录缺调用地址（metadata={sorted(metadata)}，tool_call_id={metadata.get('tool_call_id')!r}）"
        "⇒ 同轮多次调用共享一条审批时，无法判定该回投给谁"
    )


def testApprovalReturnAddressIsIsolatedAcrossParallelCalls():
    """并行批次里各调用的回投地址不得互串。

    为什么单独钉一条：G3 之后同轮多调用走 asyncio.gather 子任务。若地址被实现成
    "挂在 agent/executor 上的共享字段"，并发调用会读到彼此的 call_id ——
    A 修好了键、B 却把结果投给错的调用，比修之前更难查（一个"看着对"的错地址）。
    判据真驱动生产方法本身，不测 ContextVar 语义。
    """
    import asyncio

    import neurova.tool_executor as te
    from neurova.core.turn_context import set_turn_identity, set_turn_tool_call_id

    created: typing.List[typing.Dict[str, typing.Any]] = []

    class _Store:
        def create_approval_request(self, **kw):
            created.append(kw)

            class _R:
                request_id = "apr"

            return _R()

    class _Verdict:
        reasons = ("danger",)

        @staticmethod
        def to_dict():
            return {"decision": "ask"}

    def _bareExecutor():
        ex = te.ToolExecutor.__new__(te.ToolExecutor)
        ex._agent_identity = lambda: ("u1", "a1")
        return ex

    async def _worker(callId: str) -> None:
        set_turn_tool_call_id(callId)
        await asyncio.sleep(0)  # 交叠：让别的任务先跑一段
        _bareExecutor()._create_approval_request("file_read", {"path": callId}, _Verdict())

    async def _drive() -> None:
        set_turn_identity("q", session_id="sess_p", user_id="u1")
        await asyncio.gather(*(_worker(f"call_{i}") for i in range(4)))

    originalStore = te._get_approval_manager
    te._get_approval_manager = lambda: _Store()
    try:
        asyncio.run(_drive())
    finally:
        te._get_approval_manager = originalStore

    assert len(created) == 4, f"应创建 4 条审批记录，实际 {len(created)}"
    recorded = [c["metadata"].get("tool_call_id") for c in created]
    assert sorted(recorded) == sorted(f"call_{i}" for i in range(4)), (
        f"并行调用写出的回投地址互串或丢失：{recorded}"
    )



# ───────────────────────────────────────────────────────────────
# B · 读侧没有投递（走真实端点函数）
# ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def testApprovedReplayDeliversResultToConversation(monkeypatch):
    """带外批准后，执行终态必须进入会话的晚到通路（而不是只回给点批准的那个请求）。

    靶子为什么是 coordinator 而不是 `append_tool_messages`：批准发生在另一个 HTTP
    请求里，那时原轮次多半已收尾，没有活着的轮次可 append。本仓对"结果比轮次晚到"
    已有唯一通路——超时转后台工具的 pending hints，由流水线在下一轮排干注入。
    故断言两端：① 端点把终态投进 agent 自己的 coordinator；② 该 hint 带原 call_id
    且可被排干（投进没人排水的实例等于没投）。
    """
    from neurova.agent.tool_coordinator import ToolCoordinator
    from neurova.api.endpoints import governance as gov
    from neurova.security.approval_manager import ApprovalStatus

    class _Request:
        request_id = "apr_g5_1"
        status = ApprovalStatus.PENDING
        metadata = {
            "tool_name": "exec_command",
            "params": {"command": "echo hi"},
            "session_id": "sess_g5",
            "tool_call_id": "call_g5",
        }

    class _Store:
        def get_request(self, request_id):
            return _Request()

        def approve_request(self, *a, **kw):
            return True

    class _Executor:
        def __init__(self, agent):
            self.agent = agent
            # 生产里 coordinator 挂在 ToolExecutor 上（tool_executor.py:378），
            # 投递侧取的就是这条属性；fixture 不给就等于测了个不存在的形状。
            self.tool_coordinator = ToolCoordinator()

        async def _execute_single_tool(self, tool_name, params, skip_governance=False):
            return {"success": True, "stdout": "hi", "tool": tool_name}

        @staticmethod
        def _result_is_success(result):
            return bool(isinstance(result, dict) and result.get("success"))

    class _Agent:
        def __init__(self):
            # 用真 ToolCoordinator：投/取两端都要被验到，替身会把"投进空实例"也判成过
            self.tool_executor = _Executor(self)

    agent = _Agent()
    monkeypatch.setattr(gov, "_get_approvals", lambda: _Store())
    monkeypatch.setattr(gov, "_get_agent", lambda: agent)
    # 端点里是函数级 import（from neurova.tool_executor import ToolExecutor），
    # 接缝必须打在源模块上 —— 打 gov.ToolExecutor 会 AttributeError，红在器械不在缺陷。
    monkeypatch.setattr("neurova.tool_executor.ToolExecutor", _Executor)

    response = await gov.approve_and_execute(
        None, "apr_g5_1", gov.ApprovalActionRequest(approved_by="admin"), _admin=None
    )
    payload = response.get("data") if isinstance(response, dict) else None
    assert payload and payload.get("executed") is True, f"批准未走到重放分支：{response!r}"

    hints = agent.tool_executor.tool_coordinator.pop_pending_hints()
    assert hints, (
        "重放执行成功（result 已产生）但会话的晚到通路收到 0 条 ⇒ "
        "结果只进了 approve 的 HTTP 响应体，模型视角那次调用仍停在『待用户确认』"
    )
    assert hints[0].get("task_id") == "call_g5", (
        f"回投未绑定原调用 id：{hints[0]!r} ⇒ 同轮多次调用配不上是哪一次"
    )
    assert hints[0].get("kind") == "approval", (
        f"审批终态与后台完成混成同一种提示，模型无从区分：{hints[0]!r}"
    )


@pytest.mark.asyncio
async def testRejectedApprovalAlsoReachesLateResultChannel(monkeypatch):
    """拒绝也必须给终态：用户已答复，答复不能烂在审批单里。

    与批准同一条通路，差别只在 success=False。不钉这条的话，"拒绝不回投"
    会变成批准修好之后剩下的那半个静默丢弃——而同一个病根。
    """
    from neurova.agent.tool_coordinator import ToolCoordinator
    from neurova.api.endpoints import governance as gov
    from neurova.security.approval_manager import ApprovalStatus

    class _Request:
        request_id = "apr_g5_r"
        status = ApprovalStatus.PENDING
        metadata = {"tool_name": "file_write", "params": {"path": "x"},
                    "session_id": "sess_r", "tool_call_id": "call_r"}

    class _Store:
        def get_request(self, request_id):
            return _Request()

        def reject_request(self, *a, **kw):
            return True

    class _Executor:
        tool_coordinator = ToolCoordinator()

        @staticmethod
        def _result_is_success(result):
            return False

    class _Agent:
        tool_executor = _Executor()

    monkeypatch.setattr(gov, "_get_approvals", lambda: _Store())
    monkeypatch.setattr(gov, "_get_agent", lambda: _Agent())

    await gov.reject_approval(
        None, "apr_g5_r", gov.ApprovalActionRequest(approved_by="admin", note="不许"), _admin=None
    )
    hints = _Executor.tool_coordinator.pop_pending_hints()
    assert hints and hints[0].get("success") is False and hints[0].get("task_id") == "call_r", (
        f"拒绝没有产生可回投的终态：{hints!r}"
    )



@pytest.mark.asyncio
async def testTimeoutReleasesWaiterSoLateApprovalStillExecutes(monkeypatch):
    """等待超时后必须注销登记，否则人工后批准时**两边都不执行**。

    这条不是"顺手加的健壮性"，是本片自己引入的缺陷的回执：`hasApprovalWaiter`
    是批准端点决定"要不要重放"的唯一依据。超时若留着陈旧登记，端点就认为
    "原调用会执行"而跳过重放，而原调用早已放手 —— 工具谁都不跑，且无任何报错。
    """
    import neurova.tool_executor as te
    from neurova.security.approval_relay import hasApprovalWaiter

    monkeypatch.setenv("NEUROVA_APPROVAL_WAIT_SECONDS", "0.05")

    verdict = _AskVerdict()

    def _bare():
        ex = te.ToolExecutor.__new__(te.ToolExecutor)
        ex._create_approval_request = lambda *a, **k: "apr_timeout_1"
        return ex

    assert hasApprovalWaiter("apr_timeout_1") is False, "前置：开始时无人等待"

    result = await _bare()._awaitApprovalVerdict("exec_command", {"command": "ls"}, verdict)

    assert isinstance(result, dict) and result.get("approval_timeout") is True, (
        f"超时未给出可辨识的诚实终态：{result!r}"
    )
    assert result.get("governance"), "超时终态缺 governance 键 ⇒ is_policy_denial 认不出，会被记成工具故障"
    assert hasApprovalWaiter("apr_timeout_1") is False, (
        "超时后登记未注销 ⇒ 批准端点误判『原调用会执行』而跳过重放，"
        "而原调用已放手 —— 工具两边都不跑，且没有任何报错"
    )


# ───────────────────────────────────────────────────────────────
# C · 信号通道零订阅者
# ───────────────────────────────────────────────────────────────


def testApprovalNotificationHasProductionSubscriber():
    """`approval_result` 事件必须有至少一个生产消费者。

    实测：`ApprovalManager.register_notification_callback`（`:231`）在全仓
    只有定义、没有调用方，于是 `:778-780` 那段回调广播遍历的是空列表——
    一个注册了却无人订阅的模块，与"写出无人读的字段"同形态。
    """
    callers = []
    for path in _NEUROVA.rglob("*.py"):
        if path.name == "approval_manager.py":
            continue  # 自身定义与内部广播不计为消费者
        text = path.read_text(encoding="utf-8", errors="replace")
        if "register_notification_callback" in text:
            callers.append(str(path.relative_to(_REPO)))

    assert callers, (
        "register_notification_callback 生产侧零调用方 ⇒ approval_request / "
        "approval_result 两个事件无人接收；批准与拒绝既不进会话也不推前端"
    )


# ───────────────────────────────────────────────────────────────
# D · 有界等待的契约必须先存在
# ───────────────────────────────────────────────────────────────


def testApprovalWaitIsBoundedByDeclaredSetting():
    """阻塞式审批必须有**被声明的**超时上界。

    为什么现在就钉：把"不阻塞"改成"阻塞"是本条缺陷的修法，而参照侧同样以
    "真阻塞"为目标，结果超时参数全仓无人赋值 ⇒ 阻塞无上界，变成永久挂起。
    同一个坑不必用一次线上故障去踩。上界必须像 `agent_limits_settings` 那样
    单源声明并被读侧真实读取，不接受写死的字面量。
    """
    from neurova.security.governance_settings import load_governance_settings

    defaults = load_governance_settings()
    timeoutKeys = [k for k in defaults if "approval" in k and ("timeout" in k or "wait" in k)]
    assert timeoutKeys, (
        f"治理设置里没有审批等待上界的键（现有键 {sorted(defaults)[:8]}…）"
        "⇒ 一旦 ASK 改为阻塞等待，就没有任何东西给它设上界"
    )

    readerFound = any(
        any(tok in p.read_text(encoding="utf-8", errors="replace") for tok in timeoutKeys)
        for p in _NEUROVA.rglob("*.py")
        if p.name != "governance_settings.py"
    )
    assert readerFound, (
        f"超时键 {timeoutKeys} 无人读取 = 只写不读的配置，"
        "声明了等于没声明（本仓已为这类形态立过守卫）"
    )


# ───────────────────────────────────────────────────────────────
# 反向控制：以上判据整体失效时不能空转通过
# ───────────────────────────────────────────────────────────────


def testGuardIsNotVacuous():
    """正向对照：一个已知"确实有人调用"的方法必须被同一套扫描判为有消费者。

    没有这条，A/B/C/D 任何一条判据写坏（比如路径拼错导致永远扫不到文件）
    都会以"全红"或"全绿"的形态蒙过去。
    """
    source = _readSource("tool_executor.py")
    assert "_create_approval_request" in source
    assert inspect.isawaitable  # 端点侧断言用得上，顺带钉住 asyncio 标记非空转
    fn = _functionNode(source, "_governance_precheck")
    assert isinstance(fn, ast.AsyncFunctionDef), (
        "_governance_precheck 不再是 async ⇒ 本文件的阻塞前提已消失，"
        "判据要随之改写，而不是留着一条永不生效的红"
    )


@pytest.mark.asyncio
async def testApprovalWakeCrossesRealThreadBoundary(tmp_path, monkeypatch):
    """真 ApprovalManager（真 SQLite）+ 从另一个线程批准，复现 HTTP 请求的真实形态。

    为什么必须有这条：中继的唤醒走 `loop.call_soon_threadsafe`，因为批准方与等待方
    不在同一个事件循环。若只在同线程里 `set_result`，这条跨循环投递永不被验到——
    写错时的表现正是"咽喉干等至超时、批准后两边都不执行"。

    同一趟还顺带钉住不重复执行的不变量：批准线程在动手前先记录 `hasApprovalWaiter`，
    为真即代表端点会跳过重放、由咽喉执行一次，且只有一次。
    """
    import threading
    import time

    import neurova.tool_executor as te
    from neurova.security.approval_manager import ApprovalManager
    from neurova.security.approval_relay import hasApprovalWaiter, installApprovalRelay

    manager = ApprovalManager(str(tmp_path))
    assert installApprovalRelay(manager), "中继安装失败"

    requestId: dict = {}

    def _create(tool_name, params, v):
        req = manager.create_approval_request(
            agent_id="a1", user_id="u1", command="pwd", description="d", danger_reason="r",
            metadata={"tool_name": tool_name, "params": params,
                      "session_id": "sess_t", "tool_call_id": "call_t"},
        )
        requestId["id"] = req.request_id
        return req.request_id

    ex = te.ToolExecutor.__new__(te.ToolExecutor)
    ex._create_approval_request = _create
    monkeypatch.setenv("NEUROVA_APPROVAL_WAIT_SECONDS", "10")

    observed = {}

    def _approveFromAnotherThread():
        time.sleep(0.4)
        rid = requestId.get("id")
        # 批准瞬间：登记应仍在 ⇒ 端点据此跳过重放 ⇒ 全局只执行一次
        observed["waiterPresentAtApprove"] = hasApprovalWaiter(rid)
        manager.approve_request(rid, approved_by="admin")

    worker = threading.Thread(target=_approveFromAnotherThread, daemon=True)
    worker.start()

    result = await ex._awaitApprovalVerdict("exec_command", {"command": "pwd"}, _AskVerdict())
    worker.join(timeout=5)

    assert result is None, (
        f"另一线程批准后咽喉未被唤醒、没拿到放行（返回 {result!r}）"
        "⇒ 跨事件循环投递失效，表现为干等到超时"
    )
    assert observed.get("waiterPresentAtApprove") is True, (
        f"批准时登记不在场（{observed!r}）⇒ 端点会重放、咽喉也会执行，同一条命令跑两遍"
    )
    assert not hasApprovalWaiter(requestId["id"]), "裁决后登记未注销，后续同名审批会被误判"
