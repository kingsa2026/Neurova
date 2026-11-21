# -*- coding: utf-8 -*-
"""ACP v2 编解码层（G6 卡）：v2 线上形状 ↔ 本仓内部事件模型的纯函数转换。

schema 事实源：本机 ``@agentclientprotocol/sdk`` 包内
``schema/v2/schema.unstable.json``（v2.0.0-alpha.3，逐字段实读）。
本模块只做 schema 形状转换，不做 I/O、不持状态；未知分支按本仓
「未知类型跳过」纪律归档不消费，不臆造字段。

与 v1 的关键差异（本方法子集）：
- initialize 必填 ``info``（Implementation{name, version}），能力字段改名
  ``capabilities``（v1 为 clientCapabilities）；应答带 ``authMethods``
  （v1 独立 authenticate 方法在 v2 移除，由 auth/login、auth/logout 承接）。
- session/new 必填 cwd（绝对路径）；session/resume 必填
  sessionId + cwd（+ 可选 replayFrom 回放游标）。
- session/prompt 的 prompt 是内容块数组（ContentBlock：text/image/audio/
  resource/resource_link）；应答改回执 ``{messageId}``——完成与停止原因
  改经 state_update(idle, stopReason) 通知上报，不再在应答里带 stopReason。
- 取消按 ``$/cancel_request``（CancelRequestNotification，按 requestId），
  不是 v1 的 session/cancel{sessionId}。
- session/request_permission 请求增 sessionId/title/options/subject；
  应答为 ``{outcome: {outcome: selected|cancelled, optionId?}}``。
- session/update 为 24 分支联合（见 parseSessionUpdate 映射表）。
"""
from typing import Any, Dict, List, Optional

#: v2 协议版本（ProtocolVersion = integer uint16）
PROTOCOL_VERSION = 2
#: v2 取消通知方法（CancelRequestNotification）
CANCEL_REQUEST_METHOD = "$/cancel_request"
#: 本仓客户端实现名（Implementation.name）
CLIENT_NAME = "neurova"

#: SessionUpdate 分支 → 内部事件类别的映射表（汇报与测试的唯一出处）：
#:   agent_message_chunk      -> content    （流式正文，emitter("content")）
#:   agent_thought_chunk      -> reasoning  （流式思考，emitter("reasoning")）
#:   tool_call_update         -> tool_call  （工具调用镜像）
#:   tool_call_content_chunk  -> tool_call  （工具调用产出块，同一镜像面）
#:   agent_message            -> message    （完整代理消息 upsert）
#:   agent_thought            -> message    （完整思考 upsert）
#:   plan_update/plan_removed -> plan       （计划面）
#:   usage_update             -> usage      （cost/context 面板）
#:   compaction_update/_summary_chunk -> compaction（上下文压缩面）
#:   state_update(idle)       -> stop       （回合收口，带 stopReason）
#:   user_message_chunk/user_message       -> skip（用户回显，非产出）
#:   state_update(其余状态)                -> skip（非收口状态快照）
#:   terminal_update/terminal_output_chunk -> skip（terminal 面，无消费端）
#:   available_commands_update/config_option_update/session_info_update/notice
#:                                         -> skip（会话管理/通知面，无消费端）
#:   subagent_update/session_message/session_message_chunk -> skip（UNSTABLE）
#:   其余（自定义/未来类型）               -> skip（未知类型跳过纪律）
_SESSION_UPDATE_EVENT_BY_KIND = {
    "agent_message_chunk": "content",
    "agent_thought_chunk": "reasoning",
    "agent_message": "message",
    "agent_thought": "message",
    "tool_call_update": "tool_call",
    "tool_call_content_chunk": "tool_call",
    "plan_update": "plan",
    "plan_removed": "plan",
    "usage_update": "usage",
    "compaction_update": "compaction",
    "compaction_summary_chunk": "compaction",
    "user_message_chunk": "skip",
    "user_message": "skip",
    "terminal_update": "skip",
    "terminal_output_chunk": "skip",
    "available_commands_update": "skip",
    "config_option_update": "skip",
    "session_info_update": "skip",
    "notice": "skip",
    "subagent_update": "skip",
    "session_message": "skip",
    "session_message_chunk": "skip",
}

#: skip 分支的归档原因（诚实留痕，不消费也不假装消费）
_SKIP_REASON = {
    "user_message_chunk": "user_echo_chunk",
    "user_message": "user_echo_message",
    "terminal_update": "terminal_surface",
    "terminal_output_chunk": "terminal_surface",
    "available_commands_update": "session_management_surface",
    "config_option_update": "session_management_surface",
    "session_info_update": "session_management_surface",
    "notice": "notice_surface",
    "subagent_update": "unstable_surface",
    "session_message": "unstable_surface",
    "session_message_chunk": "unstable_surface",
}


class V2ProtocolError(ValueError):
    """v2 schema 形状违规（fail-closed 类；由调用方映射为协议错误）。"""


def clientInfo() -> dict:
    """本仓 Implementation{name, version}（v2 initialize 必填 info）。"""
    try:
        import neurova

        version = str(getattr(neurova, "__version__", "") or "0.0.0")
    except Exception:  # noqa: BLE001 - 版本取不到不阻断握手，诚实降级
        version = "0.0.0"
    return {"name": CLIENT_NAME, "version": version}


def buildInitializeParams(protocol_version: int, client_capabilities: Optional[dict] = None) -> dict:
    """v2 InitializeRequest：整数版本 + 必填 info + capabilities。"""
    return {
        "protocolVersion": int(protocol_version),
        "info": clientInfo(),
        "capabilities": dict(client_capabilities or {}),
    }


def parseInitializeResponse(result: Optional[dict]) -> dict:
    """校验 v2 InitializeResponse：protocolVersion 整数 + info{name, version}。"""
    result = result or {}
    version = result.get("protocolVersion")
    if not isinstance(version, int) or isinstance(version, bool):
        raise V2ProtocolError(f"protocolVersion 必须是整数，实际 {version!r}")
    info = result.get("info")
    if not isinstance(info, dict):
        raise V2ProtocolError("initialize 应答缺 info（Implementation）")
    if not isinstance(info.get("name"), str) or not info.get("name"):
        raise V2ProtocolError("info.name 必须是非空字符串")
    if not isinstance(info.get("version"), str) or not info.get("version"):
        raise V2ProtocolError("info.version 必须是非空字符串")
    return result


def buildNewSessionParams(cwd: str, mcp_servers: Optional[List[dict]] = None) -> dict:
    """v2 NewSessionRequest：cwd 必填（绝对路径），mcpServers 数组。"""
    return {"cwd": str(cwd or ""), "mcpServers": list(mcp_servers or [])}


def parseNewSessionResponse(result: Optional[dict]) -> dict:
    """校验 v2 NewSessionResponse：sessionId 必填。"""
    result = result or {}
    session_id = result.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        raise V2ProtocolError(f"session/new 应答缺 sessionId，实际 {session_id!r}")
    return result


def buildResumeParams(session_id: str, cwd: str,
                      replay_from: Optional[dict] = None) -> dict:
    """v2 ResumeSessionRequest：sessionId + cwd 必填；replayFrom 缺省省略。"""
    params: Dict[str, Any] = {"sessionId": str(session_id or ""), "cwd": str(cwd or "")}
    if replay_from is not None:
        params["replayFrom"] = replay_from
    return params


def buildPromptParams(session_id: str, task_text: str) -> dict:
    """v2 PromptRequest：prompt 为内容块数组（本仓文本任务 → 单 text 块）。"""
    return {
        "sessionId": str(session_id or ""),
        "prompt": [{"type": "text", "text": str(task_text or "")}],
    }


def parsePromptResponse(result: Optional[dict]) -> dict:
    """校验 v2 PromptResponse：messageId 必填（完成语义已移至 state_update）。"""
    result = result or {}
    message_id = result.get("messageId")
    if not isinstance(message_id, str) or not message_id:
        raise V2ProtocolError(f"session/prompt 应答缺 messageId，实际 {message_id!r}")
    return {"messageId": message_id}


def buildCancelRequestParams(request_id: int) -> dict:
    """v2 CancelRequestNotification：按 requestId 取消在途请求。"""
    return {"requestId": int(request_id)}


def buildPermissionResponse(decision: Optional[dict], request_params: Optional[dict]) -> dict:
    """v2 RequestPermissionResponse：把本仓 {approved} 裁决映射为 v2 outcome。

    - 批准 → selected 第一个 allow_* 选项；拒绝 → selected 第一个 reject_* 选项；
    - 找不到匹配选项时回 ``cancelled``（fail-closed：v2 规定 selected 之外的
      形状不得被 agent 视为批准，cancelled 语义上同样绝不等于放行）。
    """
    options = (request_params or {}).get("options") or []
    approved = bool((decision or {}).get("approved"))
    wanted = "allow" if approved else "reject"
    for option in options:
        if not isinstance(option, dict):
            continue
        kind = str(option.get("kind") or "")
        if kind.startswith(wanted) and option.get("optionId") is not None:
            return {"outcome": {"outcome": "selected", "optionId": option["optionId"]}}
    return {"outcome": {"outcome": "cancelled"}}


def textFromContentBlock(block: Any) -> str:
    """ContentBlock → 纯文本；仅取 schema 保证的 text 块，其余不臆造。"""
    if isinstance(block, dict) and block.get("type") == "text":
        text = block.get("text")
        return text if isinstance(text, str) else ""
    return ""


def textFromContentBlocks(blocks: Any) -> str:
    """ContentBlock 数组 → 顺序拼接的纯文本（无分隔符，不加工）。"""
    if not isinstance(blocks, list):
        return ""
    return "".join(textFromContentBlock(block) for block in blocks)


def parseSessionUpdate(params: Optional[dict]) -> dict:
    """v2 SessionUpdate 24 分支 → 本仓内部事件模型（归一化单事件）。

    返回形状（只携带 schema 里存在的字段，不臆造）：
      event      内部事件类别：content/reasoning/tool_call/message/plan/
                 usage/compaction/stop/skip
      text       已提取纯文本（仅 text 块；无则空串）
      messageId  chunk/message 分支的标识（无则空串）
      stopReason state_update=idle 时的停止原因（无则空串）
      update     原始 v2 update dict（镜像与归档用）
      reason     event=skip 时的归档原因（其余空串）

    未知 sessionUpdate 类型（含 `_` 前缀扩展与未来变体）一律 skip 并原样
    保留 update——「未知类型跳过」纪律：归档不消费。
    """
    update = (params or {}).get("update")
    if not isinstance(update, dict):
        return {"event": "skip", "text": "", "messageId": "", "stopReason": "",
                "update": {}, "reason": "missing_update"}
    kind = update.get("sessionUpdate")
    if not isinstance(kind, str) or not kind:
        return {"event": "skip", "text": "", "messageId": "", "stopReason": "",
                "update": update, "reason": "missing_session_update_type"}

    if kind == "state_update":
        state = update.get("state")
        if state == "idle":
            stop_reason = update.get("stopReason")
            return {"event": "stop", "text": "", "messageId": "",
                    "stopReason": stop_reason if isinstance(stop_reason, str) else "",
                    "update": update, "reason": ""}
        return {"event": "skip", "text": "", "messageId": "", "stopReason": "",
                "update": update, "reason": f"state_{state}"}

    if kind in _SESSION_UPDATE_EVENT_BY_KIND:
        event = _SESSION_UPDATE_EVENT_BY_KIND[kind]
        if event == "skip":
            reason = _SKIP_REASON.get(kind, "unknown_session_update_type")
        else:
            reason = ""
        text = ""
        message_id = ""
        if kind in ("agent_message_chunk", "agent_thought_chunk", "user_message_chunk"):
            text = textFromContentBlock(update.get("content"))
            message_id = str(update.get("messageId") or "")
        elif kind in ("agent_message", "agent_thought", "user_message"):
            text = textFromContentBlocks(update.get("content"))
            message_id = str(update.get("messageId") or "")
        return {"event": event, "text": text, "messageId": message_id,
                "stopReason": "", "update": update, "reason": reason}

    # 未知/自定义/未来分支：原样归档，不消费
    return {"event": "skip", "text": "", "messageId": "", "stopReason": "",
            "update": update, "reason": "unknown_session_update_type"}


class V2Codec:
    """v2 编解码器：acp_client 按协商版本选择（v2 实例 / v1 None）。

    方法逐一委托模块级纯函数；``protocol_version``/``cancel_method`` 供
    执行体做版本化分发，不散落魔法值。
    """

    protocol_version = PROTOCOL_VERSION
    cancel_method = CANCEL_REQUEST_METHOD

    def initializeParams(self, protocol_version: int,
                         client_capabilities: Optional[dict] = None) -> dict:
        return buildInitializeParams(protocol_version, client_capabilities)

    def parseInitializeResponse(self, result: Optional[dict]) -> dict:
        return parseInitializeResponse(result)

    def newSessionParams(self, cwd: str, mcp_servers: Optional[List[dict]] = None) -> dict:
        return buildNewSessionParams(cwd, mcp_servers)

    def parseNewSessionResponse(self, result: Optional[dict]) -> dict:
        return parseNewSessionResponse(result)

    def resumeParams(self, session_id: str, cwd: str,
                     replay_from: Optional[dict] = None) -> dict:
        return buildResumeParams(session_id, cwd, replay_from)

    def promptParams(self, session_id: str, task_text: str) -> dict:
        return buildPromptParams(session_id, task_text)

    def parsePromptResponse(self, result: Optional[dict]) -> dict:
        return parsePromptResponse(result)

    def cancelRequestParams(self, request_id: int) -> dict:
        return buildCancelRequestParams(request_id)

    def permissionResponse(self, decision: Optional[dict],
                           request_params: Optional[dict]) -> dict:
        return buildPermissionResponse(decision, request_params)

    def parseSessionUpdate(self, params: Optional[dict]) -> dict:
        return parseSessionUpdate(params)
