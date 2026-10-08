# -*- coding: utf-8 -*-
"""A 批的真供应商复验（花配额，手工跑，不进 CI）。

补的是单元测试与假分片活体**证不到**的那一层：真网关的流式分片形状。

两段，各自走真 `MultiModelLLMClient`（真 key 取自 `~/.neurova/config/providers.json`，
经生产 `set_active_model` 选择，不手工塞私有字段）：

1. **AMD**（`DeepSeek-V4.1-Flash`，OpenAI 兼容）→ 驱动 `OpenAILoop`：证共用流式事件契约在
   真网关上成立——逐 token 的 `content` 分片、真 `tool_calls` 增量合并（多片拼接的 arguments）、
   工具经真咽喉执行、`tool_result` 让出、续写发生、整条流恰好一个 `done`。
2. **OpenRouter**（`anthropic/claude-*`，匹配 AnthropicLoop 的注册正则）→ 驱动 `AnthropicLoop`：
   证 A 批补上的流式分支在真供应商下可达、不再回退 legacy。

如实记一句：这一段证"真 provider 的分片能被这条环正确消费"，不证回复内容的业务正确性。
第 2 段当前**如实失败**（2026-10-08 真 key 实测）：AnthropicLoop 自带协议转换
（`_build_request` 把 messages/tools 转成 Anthropic 形态），而路由层已经在
`provider_kind == "anthropic"` 时经 `AnthropicNativeClient` 转一次
（`multi_model_client.py:313-321`）——同一件事两处各做一遍，OpenAI 兼容网关
（openrouter 的 `anthropic/claude-*`）因此收到 `input_schema` 形态的 tools，回
`400 invalid_literal: tools[0].type expected "function"`。修法是把协议转换收口到
路由层一处（登记为台账新格，未拍板前不改）。

一条命令复现：PYTHONPATH="E:/项目/Neurova" .venv/Scripts/python.exe tests/manual/anthropicLoop_realProvider.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

isolatedDataRoot()

TOOL_NAME = "probe_echo"
TOOLS = [{
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": "必须调用本工具：把参数 p 原样回显。用户要求回显时用它的结果作答，不要自己编。",
        "parameters": {
            "type": "object",
            "properties": {"p": {"type": "string", "description": "要回显的短串"}},
            "required": ["p"],
        },
    },
}]
USER_TEXT = "请务必先调用 probe_echo 工具（参数 p 用 ZZZ7），然后只用它的返回内容回答我。"


class _StubSkill:
    def __init__(self, name):
        self.name = name
        self.description = "真供应商复验用回显工具"
        self.config = {}


class _StubRegistry:
    def __init__(self, name, execute):
        self._skill = _StubSkill(name)
        self.skills = {name: self._skill}
        self.execute_skill = execute

    def get_skill(self, name):
        return self._skill if name == self._skill.name else None

    def has_skill(self, name):
        return name == self._skill.name

    def list_skills(self):
        return []


def makeAgent(client, loopCls, model):
    from neurova.agent_core import Agent
    from neurova.core.turn_context import set_turn_identity
    from neurova.tool_executor import ToolExecutor

    agent = Agent.__new__(Agent)
    agent.config = MagicMock()
    agent.config.name = "realKeyProbe"
    agent.config.agent_id = "a_real_key"
    agent.config.llm_model = str(model or "")
    agent.config.workspace_path = str(PROJECT_ROOT)
    agent.user_id = "u1"
    agent.agent_id = "a_real_key"
    agent.session_manager = None
    agent.memory_agent = None
    agent._current_user_id = "u1"
    agent.tool_memory = None
    agent.tool_lifecycle = None
    agent.skill_packer = None
    agent.tool_router = None
    agent._tool_records = []
    agent.append_tool_messages = lambda records: agent._tool_records.extend(records or [])
    agent.get_tool_messages_snapshot = lambda: list(agent._tool_records)
    agent._collect_tool_messages = lambda: list(agent._tool_records)
    agent.reset_tool_messages = lambda: agent._tool_records.clear()
    agent.llm_client = client
    agent.tool_executor = ToolExecutor(agent)

    async def echo(*args, **kwargs):
        params = args[1] if len(args) > 1 else (kwargs or {})
        return {"content": f"ECHO<{params.get('p', '?')}>"}

    agent._skill_registry = _StubRegistry(TOOL_NAME, AsyncMock(side_effect=echo))
    set_turn_identity(USER_TEXT, "sess_real_key", "u1")
    loop = loopCls(agent)
    loop.llm_client = client
    agent.loop = loop
    return agent, loop


def toolRoundCounts(events):
    types = [e.get("type") for e in events if isinstance(e, dict)]
    return {
        "content": types.count("content"),
        "tool_call": types.count("tool_call"),
        "tool_result": types.count("tool_result"),
        "done": types.count("done"),
        "gate_terminate": types.count("gate_terminate"),
        "types": sorted(set(types)),
    }


async def drive(loopCls, label, providerId, model):
    from neurova.agent_core import AgentLLMClient

    print(f"\n=== {label}：provider={providerId} model={model} ===")
    # 生产同一个客户端：不持有 key，按 (model, provider_id) 经路由层取真凭证
    client = AgentLLMClient(model=model, provider_id=providerId)

    agent, loop = makeAgent(client, loopCls, model)
    messages = [{"role": "user", "content": USER_TEXT}]
    gen = await loop.predict_step(messages, tools=TOOLS, stream=True)
    events = [e async for e in gen]

    readings = toolRoundCounts(events)
    toolResults = [
        e["data"].get("tool_call_id")
        for e in events
        if isinstance(e, dict) and e.get("type") == "tool_result"
    ]
    replayed = [m.get("tool_call_id") for m in messages if m.get("role") == "tool"]
    declared = {
        c.get("id")
        for m in messages
        if m.get("role") == "assistant" and m.get("tool_calls")
        for c in m["tool_calls"]
    }
    reply = "".join(
        e.get("data", "") for e in events if isinstance(e, dict) and e.get("type") == "content"
    )
    print(f"  事件读数 = {json.dumps(readings, ensure_ascii=False)}")
    print(f"  回复（前 120 字）= {reply[:120]!r}")
    print(f"  让出 tool_result={toolResults} 历史已回放={replayed} assistant 声明={sorted(declared)}")

    assert readings["done"] == 1, f"整条流必须恰好一个 done：{readings}"
    assert readings["content"] >= 1 or toolResults, f"真网关没有任何可消费事件：{readings}"
    if toolResults:
        assert set(toolResults) <= set(replayed), (
            f"真供应商下重放缺口：让出 {toolResults} 而历史只有 {replayed}"
        )
        assert set(replayed) <= declared, "历史里存在孤儿 tool 结果（缺 assistant 声明）"
        echoed = any("ECHO<" in str(m.get("content")) for m in messages if m.get("role") == "tool")
        assert echoed, "回环的不是真执行结果（工具没真跑到）"
        print("  工具轮：真执行 + 真回放 + 协议配对 —— OK")
    else:
        print("  本轮模型未发起工具调用（内容/事件契约仍成立）——工具轮未覆盖，如实记")
    return "ran" if toolResults else "ran-no-tool"


def main() -> int:
    from neurova.agent.loops.anthropic_loop import AnthropicLoop
    from neurova.agent.loops.openai_loop import OpenAILoop
    from neurova.llm.multi_model_client import get_multi_model_client

    client = get_multi_model_client()
    available = [
        (str(m.get("provider_id")), str(m.get("model")))
        for m in (client.list_available_models() or [])
        if m.get("provider_id") in ("amd", "openrouter")
    ]
    print(f"真配置里可用模型 {len(available)} 条；provider 覆盖 = {sorted({p for p, _ in available})}")

    amdModel = next((m for p, m in available if p == "amd" and m), "DeepSeek-V4.1-Flash")
    claudeModel = next((m for p, m in available if p == "openrouter" and "claude" in m.lower()),
                       "anthropic/claude-3.5-sonnet")

    r1 = asyncio.run(drive(OpenAILoop, "① AMD 真网关（共用流式契约）", "amd", amdModel))
    try:
        r2 = asyncio.run(drive(AnthropicLoop, "② OpenRouter claude（A 批流式分支）", "openrouter", claudeModel))
        r2Failed = None
    except Exception as exc:  # noqa: BLE001 - 第 2 段的真缺陷要原文暴露，不掩盖也不中断第 1 段的取证
        import traceback

        r2, r2Failed = "second-leg-failed", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"

    print(f"\n读数汇总：AMD={r1}  Anthropic={r2}")
    if r2Failed is not None:
        # 不替故障猜成因：只打异常类型与原文栈，成因回台账对格
        print(f"第 2 段未通过：{r2Failed}")
        return 1
    print("REAL-PROVIDER VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
