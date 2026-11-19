# -*- coding: utf-8 -*-
"""B1/B2 红灯：外部编码代理治理线（设计文档 §4.4/§6.2/§6.3）。

B1 permission→审批链接线：适配器默认 permission_asker 接 ``requestRunApproval``；
ACP 泵线程内同步等待（``asyncio.run_coroutine_threadsafe(...).result(timeout)``
桥接回 chat 捕获的事件循环）；action 命名空间 ``acp:{tool}:{kind}``；
未 bindRun / 无事件循环一律 fail-closed deny。

B2 工具调用镜像：executor 的 tool_call(_update) 事件 → logEvent(run, "tool_call",
update) 写 H-4 账本，并经 bindRun 传入的 recorder 写 member span 轨迹；
无 recorder 时只走 logEvent。
"""
import asyncio
import sys
import threading
from pathlib import Path

from neurova.agent.neuacp.acp_executor import NeuacpStdioExecutor
from neurova.agent.neuacp.acp_member import NeuacpMemberAdapter
from neurova.agent.swarm import SubAgentRun, reset_swarm_manager
from neurova.security.approval_manager import ApprovalManager

FAKE_AGENT = Path(__file__).parent / "neuacp" / "fake_acp_agent.py"


def makeAdapter(mode, *, name="OpenCode 编码代理", permission_asker=None):
    executor = NeuacpStdioExecutor(
        [sys.executable, str(FAKE_AGENT)],
        cwd=str(FAKE_AGENT.parent),
        env_extra={"FAKE_ACP_MODE": mode},
    )
    return NeuacpMemberAdapter(
        executor,
        name=name,
        cwd=str(FAKE_AGENT.parent),
        permission_asker=permission_asker,
    )


def makeRun(**overrides):
    reset_swarm_manager()
    fields = dict(
        agent_id="ext-1", agent_name="外部编码代理", task="改个登录页",
        session_id="parent-session", origin="chat", member_session_id="swarm_member_b1",
    )
    fields.update(overrides)
    return SubAgentRun(**fields)


class FakeRecorder:
    """TrajectoryRecorder.record_event 的形状替身（B2 轨迹断言用）。"""

    def __init__(self):
        self.events = []

    def record_event(self, trace_id, event_type, data=None, span_id=None):
        self.events.append({
            "trace_id": trace_id, "event_type": event_type,
            "data": data, "span_id": span_id,
        })


# ── B1：permission → 审批链 ──────────────────────────────────────────────

def test_bindRunBridgesPermissionToApprovalChain(monkeypatch):
    """bindRun 后：泵线程的 permission 请求经 run_coroutine_threadsafe 桥接，
    以 acp:{tool}:{kind} 命名空间投给 requestRunApproval，裁决回流 agent。"""
    calls = []

    async def fakeRequestApproval(run, action, reason="", level="L1", context=""):
        calls.append({
            "run": run, "action": action, "reason": reason,
            "level": level, "context": context,
            "thread": threading.current_thread().name,
        })
        return {"approved": True, "level": level, "request_id": "req-1"}

    monkeypatch.setattr(
        "neurova.agent.approval_chain.requestRunApproval", fakeRequestApproval)

    # 探针：记录桥接同步段（阻塞等待 .result）所在的线程
    entryThreads = []
    originalAsker = NeuacpMemberAdapter._approvalPermissionAsker

    def probingAsker(self, action, reason, context):
        entryThreads.append(threading.current_thread().name)
        return originalAsker(self, action, reason, context)

    monkeypatch.setattr(NeuacpMemberAdapter, "_approvalPermissionAsker", probingAsker)

    runHolder = []

    async def scenario():
        adapter = makeAdapter("acp_permission")
        run = makeRun()
        runHolder.append(run)
        adapter.bindRun(run, lambda *args: None)
        chunks = []
        metadata = {"event_emitter": lambda kind, text: chunks.append((kind, text))}
        response = await adapter.chat("改配置", stream=True, session_id="m-1", metadata=metadata)
        await adapter.close()
        return chunks, response

    chunks, response = asyncio.run(scenario())
    # 裁决 allow → agent 按原流程继续（"你好 Neuacp" 在请求权限前已产出）
    assert ("content", "你好 Neuacp") in chunks
    assert response == {"text": "你好 Neuacp"}
    assert len(calls) == 1
    call = calls[0]
    assert call["run"] is runHolder[0]
    # action 命名空间 acp:{tool}:{kind}；fake agent 的 toolCall 无 kind → other
    assert call["action"].startswith("acp:")
    assert "写入 src/app.py" in call["action"]
    # 非 L0 kind → 声明档 L1（危险升档由链内 classifyActionLevel 统一处理）
    assert call["level"] == "L1"
    # context 携带原始 permission 参数（toolCall 摘要）
    assert "toolCall" in call["context"]
    # 桥接形态：同步等待段在 ACP 泵线程；审批协程被投回 chat 的事件循环线程
    assert len(entryThreads) == 1
    assert entryThreads[0] != threading.main_thread().name
    assert call["thread"] == threading.main_thread().name


def test_unboundAdapterFailsClosedOnPermission():
    """未 bindRun（无 run/无 loop）→ permission 一律 deny（fail-closed）。"""

    async def scenario():
        adapter = makeAdapter("acp_permission")
        chunks = []
        metadata = {"event_emitter": lambda kind, text: chunks.append((kind, text))}
        response = await adapter.chat("改配置", stream=True, session_id="m-2", metadata=metadata)
        await adapter.close()
        return chunks, response

    chunks, response = asyncio.run(scenario())
    assert ("content", "权限被拒，任务中止") in chunks
    assert "权限被拒" in response["text"]


def test_permissionRequestRunsThroughRealApprovalChain(tmp_path, monkeypatch):
    """真审批链：L1 interactive 无人在场 → 等待预算内未获准 → deny 回注会话，
    审批单落 ApprovalManager（source=swarm）且 run.approvals 留痕。"""
    mgr = ApprovalManager(str(tmp_path / "approval_ws"))
    monkeypatch.setattr("neurova.security.approval_manager.get_approval_manager", lambda: mgr)
    monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "1")

    async def scenario():
        adapter = makeAdapter("acp_permission")
        run = makeRun()
        adapter.bindRun(run, lambda *args: None)
        chunks = []
        metadata = {"event_emitter": lambda kind, text: chunks.append((kind, text))}
        response = await adapter.chat("改配置", stream=True, session_id="m-3", metadata=metadata)
        await adapter.close()
        return run, chunks, response

    run, chunks, response = asyncio.run(scenario())
    assert ("content", "权限被拒，任务中止") in chunks
    assert "权限被拒" in response["text"]
    # 审批单真实落库（蜂群单源），run 留痕
    assert len(run.approvals) == 1
    entry = run.approvals[0]
    assert entry["action"].startswith("acp:")
    assert entry["effective_level"] == "L1"
    request = mgr.get_request(entry["request_id"])
    assert request is not None
    assert request.metadata["source"] == "swarm"
    assert "写入 src/app.py" in request.command


def test_acpActionLevelMapping():
    """acp:{tool}:{kind} → 声明档：读/搜索类 L0，写/执行/未知 L1。"""
    from neurova.agent.neuacp.acp_member import acpActionLevel

    assert acpActionLevel("acp:读取 README.md:read") == "L0"
    assert acpActionLevel("acp:全局搜索:search") == "L0"
    assert acpActionLevel("acp:抓取页面:fetch") == "L0"
    assert acpActionLevel("acp:写入 src/app.py:edit") == "L1"
    assert acpActionLevel("acp:rm -rf /tmp/x:execute") == "L1"
    assert acpActionLevel("acp:删除构建产物:delete") == "L1"
    # 非 acp 命名空间 / 缺 kind → 保守 L1
    assert acpActionLevel("write_file") == "L1"
    assert acpActionLevel("acp:只有两段") == "L1"
    assert acpActionLevel("") == "L1"


def test_bindRunRebindReplacesContext():
    """重复 bindRun 以最近一次为准（续跑/换 run 场景）。"""
    adapter = makeAdapter("ok")
    runA, runB = makeRun(member_session_id="m-a"), makeRun(member_session_id="m-b")
    seen = []
    adapter.bindRun(runA, lambda *args: seen.append("a"))
    adapter.bindRun(runB, lambda *args: seen.append("b"))
    assert adapter._run is runB
    adapter._mirrorToolCall({"sessionUpdate": "tool_call"})
    assert seen == ["b"]


# ── B2：tool_call(_update) 镜像 ──────────────────────────────────────────

def makeBoundAdapterWithRealExecutor():
    """真 NeuacpStdioExecutor（不启动进程）+ 绑定好的适配器。"""
    executor = NeuacpStdioExecutor(["true"])
    adapter = NeuacpMemberAdapter(executor, name="外部编码代理")
    return executor, adapter


def test_toolCallMirroredToLogEventAndTrajectory():
    """tool_call(_update) → logEvent(run, "tool_call", update) + 轨迹 record_event。"""
    executor, adapter = makeBoundAdapterWithRealExecutor()
    run = makeRun(trace_id="tr-b2")
    logged = []
    recorder = FakeRecorder()
    adapter.bindRun(run, lambda r, kind, payload: logged.append((r, kind, payload)),
                    recorder=recorder, spanId="span-1")

    executor._onEvent("session/update", {"update": {
        "sessionUpdate": "tool_call", "toolCallId": "t-1",
        "title": "编辑 main.py", "kind": "edit"}})
    executor._onEvent("session/update", {"update": {
        "sessionUpdate": "tool_call_update", "toolCallId": "t-1", "status": "completed"}})

    # H-4 账本：两条都到，payload 是原始 update
    assert [kind for _, kind, _ in logged] == ["tool_call", "tool_call"]
    assert all(r is run for r, _, _ in logged)
    assert logged[0][2]["toolCallId"] == "t-1"
    assert logged[1][2]["status"] == "completed"
    # member span 轨迹：同步写入，带 trace/span 归属
    assert len(recorder.events) == 2
    first = recorder.events[0]
    assert first["trace_id"] == "tr-b2"
    assert first["span_id"] == "span-1"
    assert first["data"]["event"] == "tool_call"
    assert first["data"]["tool_call"]["title"] == "编辑 main.py"


def test_toolCallMirrorWithoutRecorderOnlyLogs():
    """无 recorder → 只走 logEvent（不落轨迹，也不报错）。"""
    executor, adapter = makeBoundAdapterWithRealExecutor()
    run = makeRun(trace_id="tr-b2b")
    logged = []
    adapter.bindRun(run, lambda r, kind, payload: logged.append((r, kind, payload)))

    executor._onEvent("session/update", {"update": {
        "sessionUpdate": "tool_call", "toolCallId": "t-2", "title": "读 main.py"}})

    assert len(logged) == 1
    assert logged[0][1] == "tool_call"


def test_toolCallMirrorWithoutBindRunIsNoop():
    """未 bindRun：工具事件无处可写，静默忽略（不抛、不误记）。"""
    executor, adapter = makeBoundAdapterWithRealExecutor()
    executor._onEvent("session/update", {"update": {
        "sessionUpdate": "tool_call", "toolCallId": "t-3", "title": "x"}})
    # 未绑定的镜像不应触碰 executor 之外的任何状态
    assert adapter._run is None


def test_adapterHookFallsBackToAttribute():
    """无 setToolCallHandler 方法的执行体（如插件形态）→ 退回 _on_tool_call 属性挂钩。"""

    class AttributeOnlyExecutor:
        def __init__(self):
            self._on_tool_call = None

        async def start(self, ctx):
            return None

        async def prompt(self, task_text, emitter, on_permission):
            from neurova.agent.neuacp.executor import NeuacpExecResult
            return NeuacpExecResult(text="done")

        async def cancel(self):
            return None

        async def close(self):
            return None

    executor = AttributeOnlyExecutor()
    adapter = NeuacpMemberAdapter(executor, name="插件成员")
    run = makeRun()
    logged = []
    adapter.bindRun(run, lambda r, kind, payload: logged.append(kind))

    assert callable(executor._on_tool_call)
    executor._on_tool_call({"sessionUpdate": "tool_call", "toolCallId": "t-9"})
    assert logged == ["tool_call"]
