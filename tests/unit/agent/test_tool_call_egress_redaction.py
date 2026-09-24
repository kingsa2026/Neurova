# -*- coding: utf-8 -*-
"""T-10a 的出口一致性：新增的协议原文形态 `arguments` 必须同受隐私门控。

调用侧展示记录自 T-10a 起多带一个 `arguments`（provider 回传的原文串），
它会被两条出口广播出去：`AGENT_TOOL_RESULT` 事件（WS / 渠道）与流式
`tool_call` 事件。而 `redact_tool_messages_for_channel` 只认 `params`
一个键 —— 于是同一个密钥在 `params` 里被脱敏、在 `arguments` 里**原样出网**。

判据是"同一份敏感事实在出口处只有一个结论"：门控认的必须是记录里
**所有**可能携带参数的键，不是恰好是 `params` 这一个。
"""

import json

from neurova.security.privacy_gate import redact_tool_messages_for_channel

SECRET = "hunter2"


def test_arguments_redacted_like_params():
    record = {
        "type": "tool_call",
        "tool_name": "web_login",
        "params": {"user": "u", "password": SECRET},
        "arguments": json.dumps({"user": "u", "password": SECRET}),
        "tool_call_id": "call_1",
    }

    out = redact_tool_messages_for_channel([record])[0]

    assert SECRET not in json.dumps(out), (
        "协议原文形态的 arguments 未经脱敏就出网：params 被脱敏而 arguments 原样透传，"
        f"同一密钥在出口处有了两个结论 —— {out.get('arguments')}"
    )


def test_private_visibility_drops_arguments_too():
    """visibility=private 的语义是"整条不进渠道"，丢的键不能只挑 params。"""
    record = {
        "type": "tool_call",
        "tool_name": "computer_shell",
        "params": {"command": "ls"},
        "arguments": json.dumps({"command": "ls"}),
        "visibility": "private",
    }

    out = redact_tool_messages_for_channel([record])[0]

    assert "params" not in out and "arguments" not in out, (
        f"private 事件仍带着参数出网（键={sorted(out)}）"
    )
