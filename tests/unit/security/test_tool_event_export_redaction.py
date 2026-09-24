# -*- coding: utf-8 -*-
"""工具事件出口脱敏：**全部**参数载荷键同契约（Issue #90 · T-10a 放大视角命中点）。

T-10a 给调用侧展示记录补了 `arguments`（模型原始参数串）—— 它是 `params`
之外的第二份"调用参数载荷"。而出口脱敏 `redact_tool_messages_for_channel`
只认 `params` 一个键名：新键原样透出，敏感值（password / token / api_key…）
从 channel 预览与 SSE 出口泄露。实测：

```
params:    {'url': 'https://x', 'password': 'hu***r2'}     ← 已脱敏
arguments: {"url": "https://x", "password": "hunter2"}      ← 原样泄露
```

根因不在"漏了某个键"，而在**脱敏面按单键名硬编码**：同一契约（"工具事件的
参数载荷不得原样出口"）在 `params` / `arguments` 上各写一遍，新增载荷键就再
漏一次，且"哪几个键算载荷"这件事本身没有事实源。故判据取**契约**：载荷键集合
由 `privacy_gate` 单点声明，集合内每个键走同一条脱敏路径。

不变量（每条都对应一个用例）：
1. `arguments` 里的敏感键值同样脱敏（不得原样出口）；
2. `arguments` 解析失败时不得原样透出（不可定位就不派发），且要出声；
3. `visibility:"private"` 同时丢 `params` 与 `arguments`（该分支的语义就是
   "不派发参数"，留一半等于没丢）；
4. 脱敏不改载荷**形态**（dict 仍是 dict、串仍是串），非敏感键原样保留；
5. 反向控制：载荷键集合真的覆盖两个键，且与写入端同源 —— 少一个即红。
"""

import json
from pathlib import Path

from neurova.security import privacy_gate
from neurova.security.privacy_gate import redact_tool_messages_for_channel

SECRET = "hunter2"
ARGUMENTS = json.dumps({"url": "https://x", "password": SECRET, "api_key": "sk-123"})


def _payloadKeys():
    """载荷键集合的生产声明面（缺失即红，不在 import 期炸收集）。"""
    keys = getattr(privacy_gate, "TOOL_PAYLOAD_KEYS", None)
    assert keys is not None, (
        "隐私门没有声明「工具事件参数载荷键」这一契约 —— 脱敏面按单键名硬编码，"
        "新增载荷键就再漏一次（本用例的根因）"
    )
    return tuple(keys)


def _call_event(**overrides):
    event = {
        "type": "tool_call",
        "tool_name": "web_fetch",
        "params": {"url": "https://x", "password": SECRET, "api_key": "sk-123"},
        "arguments": ARGUMENTS,
    }
    event.update(overrides)
    return event


def test_arguments_payload_is_redacted_too():
    """`arguments` 是第二份参数载荷 —— 敏感值同样不得原样出口。"""
    out = redact_tool_messages_for_channel([_call_event()])
    blob = json.dumps(out, ensure_ascii=False)
    assert SECRET not in blob and "sk-123" not in blob, f"调用的原始参数串绕过出口脱敏：{blob}"
    # 非敏感键的形状与值保留（脱敏不扩战场）
    assert json.loads(out[0]["arguments"])["url"] == "https://x"


def test_unparsable_arguments_not_exported_raw():
    """解析不开就不派发：不可定位的载荷不能原样出口（也不静默）。"""
    out = redact_tool_messages_for_channel([_call_event(arguments=f"password={SECRET}")])
    assert SECRET not in json.dumps(out, ensure_ascii=False), (
        "解析失败时把原始载荷原样出口 —— 脱敏失败必须退成不派发，不得静默放行"
    )


def test_private_visibility_drops_every_payload_key():
    """`private` 分支的语义是"不派发参数"：留一半等于没丢。"""
    out = redact_tool_messages_for_channel([_call_event(visibility="private")])
    for key in _payloadKeys():
        assert key not in out[0], f"visibility=private 仍透出载荷键 {key}：{out[0]}"


def test_payload_shape_is_preserved_by_redaction():
    """脱敏不改形态：dict 形态的载荷脱敏后仍是 dict（消费方按形态取用）。"""
    out = redact_tool_messages_for_channel(
        [_call_event(params={"password": SECRET, "nested": {"token": "t0k3n"}})]
    )[0]
    assert isinstance(out["params"], dict), f"dict 载荷被改成了 {type(out['params']).__name__}"
    assert out["params"]["nested"]["token"] != "t0k3n", "嵌套敏感键未脱敏"


def test_payload_key_set_is_covered_by_the_gate():
    """反向控制：判据取契约本体，少一个键即红（防"补一个键名"式漏修）。"""
    keys = _payloadKeys()
    assert set(keys) >= {"params", "arguments"}, f"载荷键集合未覆盖调用侧的两份参数：{keys}"
    # 与生产写入端同源：`agent/loops/base.py` 的调用侧记录确实写了这些键
    source = (Path(__file__).resolve().parents[3] / "neurova" / "agent" / "loops" / "base.py").read_text(
        encoding="utf-8"
    )
    for key in keys:
        assert f'"{key}"' in source, f"载荷键 {key} 在生产记录里不存在 —— 键集合已与写入端漂移"
