"""T-01：工具失败正文必须在执行回环处保住可诊断内容。

事故（2026-09-24 取证）：`run_code` 真跑起来但非零退出，咽喉给出
`{success: False, error: None, stderr: "…", exit_code: 3}`，回环只序列化
`error`（此处为 None），兜底串把语义补成一句 `工具执行失败: run_code` ——
`stderr` / `exit_code` 从未进入喂回模型的 tool 消息。模型于是拿到一句
无信息的话，无从自我纠正。

本文件钉四件事：
1. 真执行器（不 mock 业务对象）跑非零退出，喂回正文含 stderr 原文与 exit_code；
2. 超大 stderr 仍走既有 `apply_offload_policy` 折叠成指针（不新写截断器）；
3. 反向锁：撤掉诊断合并 ⇒ 正文回到只有兜底串，必红；
4. **生产装配态**下同样成立：app lifespan 默认开启 OutputRef（>8KiB 结果落盘引用），
   失败结果的正文正是诊断载体，不得被无诊断信息的引用顶替。

第 4 条是 CI 实测出来的：受保护子集整批跑时，前序用例装配了 OutputRef，
失败结果在咽喉处先被折叠成 `{success, output_ref, note}`，诊断键随之蒸发，
本文件的判据在"单跑绿、批跑红"之间摇摆。故夹具显式按生产口径装配 —— 判据要么
在生产装配下成立，要么以红灯暴露，不接受"顺序一变就绿"。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from neurova.agent.loops.base import BaseAgentLoop
from neurova.tool_executor import ToolExecutor

pytestmark = pytest.mark.asyncio

_FAILING_CODE = "echo boom >&2; exit 3"


@pytest.fixture(autouse=True)
def _productionOutputRefAssembly():
    """按生产装配态跑：OutputRef 默认开启（`app.py` lifespan 的 env 门控）。

    生产默认装配下，咽喉会把 >8KiB 的结果折叠成落盘引用。失败结果的正文
    就是模型自我纠正所需的诊断，折叠它等于把 T-01 修好的蒸发再放回来一次 ——
    故本夹具显式装配，把"批跑才红"的顺序依赖转成确定性判据。
    """
    from neurova.agent import tool_output_ref

    tool_output_ref.install_tool_output_ref()
    yield
    tool_output_ref.uninstall_tool_output_ref(force=True)


def _make_loop(workspace: str = "."):
    """最小 BaseAgentLoop 子类 + 真 ToolExecutor（原生链唯一执行咽喉）。"""

    class _StubLoop(BaseAgentLoop):
        async def predict_step(self, messages, tools=None, **kwargs):  # pragma: no cover
            return None

    agent = SimpleNamespace(
        skill_registry=None,
        _skill_registry=None,
        tool_memory=None,
        tool_lifecycle=None,
        skill_packer=None,
        tool_router=None,
        append_tool_messages=lambda records: None,
        config=SimpleNamespace(name="probe", user_id="default", agent_id="test-agent"),
        workspace_path=workspace,
    )
    agent.tool_executor = ToolExecutor(agent)
    loop = _StubLoop.__new__(_StubLoop)
    loop.agent = agent
    return loop


def _tool_call(code: str, call_id: str = "call_1"):
    return {
        "id": call_id,
        "function": {
            "name": "run_code",
            "arguments": json.dumps({"language": "shell", "code": code}),
        },
    }


class TestFailureBodyCarriesDiagnostics:
    async def test_runCodeNonZeroExit_keepsStderrAndExitCodeInToolMessage(self, tmp_path):
        loop = _make_loop(str(tmp_path))
        tool_msg, _ = await loop._execute_tool_call_worker(_tool_call(_FAILING_CODE))

        body = json.loads(tool_msg["content"])
        assert body.get("exit_code") == 3, f"exit_code 未进正文：{body}"
        assert "boom" in str(body.get("stderr")), f"stderr 原文未进正文：{body}"
        assert body.get("error"), "失败正文必须保留 error 标题"

    async def test_offloadStillApplies_whenStderrHuge(self, tmp_path):
        """超大 stderr 由既有 offload 政策折叠成指针，不另写截断器。"""
        loop = _make_loop(str(tmp_path))
        code = "head -c 200000 /dev/zero | tr '\\0' 'x' >&2; exit 4"
        tool_msg, records = await loop._execute_tool_call_worker(_tool_call(code, "call_big"))

        content = tool_msg["content"]
        assert "工具输出已截断并溢出至工作区文件" in content, (
            f"大正文没走既有 offload：{content[:200]}"
        )
        result_rec = next(r for r in records if r["type"] == "tool_result")
        assert result_rec.get("offload_path"), "溢出指针必须落在 result 记录上"

    async def test_nestedErrorVisibleWhenTopLevelErrorAbsent(self, tmp_path):
        """失败正文嵌在 `result` 键下时（参数解析失败形态）同样不许被兜底串遮蔽。"""
        loop = _make_loop(str(tmp_path))
        agent = loop.agent
        original = agent.tool_executor.execute_tool

        async def _nested(tool_name, params, user_input=""):
            return {
                "tool_call_id": "call_nested",
                "name": tool_name,
                "result": {"error": "工具 run_code 参数 JSON 解析失败: 期望值"},
                "success": False,
            }

        agent.tool_executor.execute_tool = _nested
        try:
            tool_msg, _ = await loop._execute_tool_call_worker(_tool_call("x", "call_nested"))
        finally:
            agent.tool_executor.execute_tool = original

        body = json.loads(tool_msg["content"])
        assert "参数 JSON 解析失败" in str(body.get("error")), (
            f"嵌套原因被兜底串遮蔽：{body}"
        )


class TestReverseLock:
    async def test_removingDiagnosticsMerge_returnsGenericErrorOnly(self, tmp_path, monkeypatch):
        """反向锁：把诊断键名单清空 ⇒ 正文只剩兜底串 ⇒ 上一条用例必然回到红。"""
        from neurova.agent import native_tool_dispatch

        monkeypatch.setattr(native_tool_dispatch, "FAILURE_DIAGNOSTIC_KEYS", ())
        loop = _make_loop(str(tmp_path))
        tool_msg, _ = await loop._execute_tool_call_worker(_tool_call(_FAILING_CODE, "call_lock"))

        body = json.loads(tool_msg["content"])
        assert "exit_code" not in body and "stderr" not in body, (
            f"诊断合并没被绕开，反向锁不成立：{body}"
        )
        assert body.get("error"), "撤掉合并后仍应只剩一句标题"
