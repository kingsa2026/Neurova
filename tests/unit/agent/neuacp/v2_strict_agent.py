# -*- coding: utf-8 -*-
"""v2 严格校验假 agent：真 stdio 子进程，按 ACP v2 schema 严格校验请求形状。

schema 事实源：@agentclientprotocol/sdk schema/v2/schema.unstable.json
（v2.0.0-alpha.3）。校验的是本仓方法子集的关键必填形状，不符一律回
-32602 Invalid params（复刻真实 v2 CLI 的 fail-closed 行为）：

- initialize：protocolVersion 必须是整数（非 bool）+ info 必填
  （Implementation{name, version}，name/version 均为非空字符串）；
  capabilities 若带必须是对象（v2 字段名，不是 v1 的 clientCapabilities）。
- session/new：cwd 必填且为绝对路径（v2 新增强制）。
- session/prompt：sessionId 必填 + prompt 必须是内容块数组
  （每块含字符串 type；text 块须带字符串 text）——v2 不再收字符串 prompt。
- $/cancel_request：requestId 必填（整数）——v2 按 requestId 取消，
  不是 v1 的 session/cancel{sessionId}。
- session/request_permission 应答：必须是 v2 形状
  {outcome: {outcome: selected|cancelled, optionId?}}，selected 的
  optionId 必须是所给选项之一（v1 的 {choice: ...} 形状不合规，按拒收处理）。

模式（环境变量 V2_STRICT_MODE）：
  ok             正常 v2 全流程：握手 → session/new → prompt 期推
                 agent_message_chunk / agent_thought_chunk → state_update
                 idle(end_of_turn) → 应答 {messageId}
  push_notify    握手后主动推一条 agent_message_chunk（练习入站 update 映射）
  acp_permission prompt 期发 session/request_permission（v2 形状，带
                 sessionId/title/options/subject），按客户端 v2 裁决继续/中止
  acp_cancel     prompt 期等 $/cancel_request{requestId}，校验通过后推
                 state_update idle(cancelled) 并应答 {messageId}
  bad_version    握手回 protocolVersion 9（版本协商 fail-closed 用）

入站 update / 应答帧均按 v2 形状构造（session/update params =
{sessionId, update:{sessionUpdate, ...}}；chunk 带 messageId + content 块）。
"""
import json
import os
import re
import sys

_ABSOLUTE_PATH_RE = re.compile(r"^([A-Za-z]:[\\/]|/)")


def send(out, obj):
    out.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    out.flush()


def invalidParams(out, msg_id, message):
    send(out, {"jsonrpc": "2.0", "id": msg_id,
               "error": {"code": -32602, "message": f"Invalid params: {message}"}})


def isPlainInt(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validInitialize(params):
    """v2 InitializeRequest：protocolVersion 整数 + info{name,version} 必填。"""
    if not isPlainInt(params.get("protocolVersion")):
        return "protocolVersion must be integer"
    info = params.get("info")
    if not isinstance(info, dict):
        return "info is required"
    if not isinstance(info.get("name"), str) or not info.get("name"):
        return "info.name must be non-empty string"
    if not isinstance(info.get("version"), str) or not info.get("version"):
        return "info.version must be non-empty string"
    if "capabilities" in params and not isinstance(params.get("capabilities"), dict):
        return "capabilities must be object"
    return None


def validNewSession(params):
    """v2 NewSessionRequest：cwd 必填且为绝对路径。"""
    cwd = params.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return "cwd is required"
    if not _ABSOLUTE_PATH_RE.match(cwd):
        return "cwd must be absolute path"
    return None


def validPrompt(params):
    """v2 PromptRequest：sessionId 必填 + prompt 必须是内容块数组。"""
    if not isinstance(params.get("sessionId"), str) or not params.get("sessionId"):
        return "sessionId is required"
    prompt = params.get("prompt")
    if not isinstance(prompt, list) or not prompt:
        return "prompt must be non-empty array of content blocks"
    for block in prompt:
        if not isinstance(block, dict) or not isinstance(block.get("type"), str):
            return "prompt blocks must be objects with string type"
        if block.get("type") == "text" and not isinstance(block.get("text"), str):
            return "text block requires string text"
    return None


def contentChunk(message_id, text):
    """v2 ContentChunk 分支：{sessionUpdate, messageId, content:{type,text}}。"""
    return {"sessionUpdate": "agent_message_chunk", "messageId": message_id,
            "content": {"type": "text", "text": text}}


def thoughtChunk(message_id, text):
    return {"sessionUpdate": "agent_thought_chunk", "messageId": message_id,
            "content": {"type": "text", "text": text}}


def idleUpdate(stop_reason):
    """v2 StateUpdate idle 分支：收口 + 停止原因（结束前台工作必带）。"""
    update = {"sessionUpdate": "state_update", "state": "idle"}
    if stop_reason is not None:
        update["stopReason"] = stop_reason
    return update


def sendUpdate(out, session_id, update):
    send(out, {"jsonrpc": "2.0", "method": "session/update",
               "params": {"sessionId": session_id, "update": update}})


def main():
    mode = os.environ.get("V2_STRICT_MODE", "ok")
    out = sys.stdout.buffer
    session_id = "sess-v2-1"
    message_id = "msg-v2-1"
    pending_prompt_id = None

    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except Exception:
            continue
        msg_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params") or {}

        if method == "initialize":
            problem = validInitialize(params)
            if problem:
                invalidParams(out, msg_id, problem)
                continue
            if mode == "bad_version":
                result = {"protocolVersion": 9,
                          "info": {"name": "strict-v2-agent", "version": "2.0.0"},
                          "capabilities": {}, "authMethods": []}
            else:
                result = {"protocolVersion": params.get("protocolVersion"),
                          "info": {"name": "strict-v2-agent", "version": "2.0.0"},
                          "capabilities": {}, "authMethods": []}
            send(out, {"jsonrpc": "2.0", "id": msg_id, "result": result})
            if mode == "push_notify":
                sendUpdate(out, session_id, contentChunk(message_id, "你好 Neuacp"))
            continue

        if method == "session/new":
            problem = validNewSession(params)
            if problem:
                invalidParams(out, msg_id, problem)
                continue
            send(out, {"jsonrpc": "2.0", "id": msg_id, "result": {"sessionId": session_id}})
            continue

        if method == "session/prompt":
            problem = validPrompt(params)
            if problem:
                invalidParams(out, msg_id, problem)
                continue
            if mode == "acp_cancel":
                # 等 $/cancel_request{requestId}：先推一块证明在跑，再等取消。
                pending_prompt_id = msg_id
                sendUpdate(out, session_id, contentChunk(message_id, "等待取消"))
                send(out, {"jsonrpc": "2.0", "id": msg_id,
                           "result": {"messageId": message_id}})
                out.flush()
                cancelled = False
                while not cancelled:
                    wait_line = sys.stdin.buffer.readline()
                    if not wait_line:
                        sys.exit(4)
                    wait_line = wait_line.strip()
                    if not wait_line:
                        continue
                    try:
                        wait_msg = json.loads(wait_line.decode("utf-8"))
                    except Exception:
                        continue
                    if wait_msg.get("method") != "$/cancel_request":
                        if wait_msg.get("id") is not None:
                            send(out, {"jsonrpc": "2.0", "id": wait_msg.get("id"),
                                       "error": {"code": -32601, "message": "method not found"}})
                        continue
                    cancel_id = (wait_msg.get("params") or {}).get("requestId")
                    # v2：requestId 必须是整数且对上在途请求——乱指的 id 不算取消。
                    if not isPlainInt(cancel_id) or cancel_id != pending_prompt_id:
                        sendUpdate(out, session_id, {
                            "sessionUpdate": "notice", "severity": "warning",
                            "title": "invalid_cancel_request"})
                        continue
                    cancelled = True
                sendUpdate(out, session_id, idleUpdate("cancelled"))
                send(out, {"jsonrpc": "2.0", "id": pending_prompt_id,
                           "result": {"messageId": message_id}})
                continue
            if mode == "acp_permission":
                # v2 RequestPermissionRequest：sessionId/title/options/subject。
                options = [{"optionId": "opt-allow", "name": "允许", "kind": "allow_once"},
                           {"optionId": "opt-reject", "name": "拒绝", "kind": "reject_once"}]
                send(out, {"jsonrpc": "2.0", "id": 9001, "method": "session/request_permission",
                           "params": {"sessionId": session_id, "title": "写入 src/app.py",
                                      "options": options,
                                      "subject": {"type": "tool_call",
                                                  "toolCall": {"toolCallId": "tc-1",
                                                               "title": "写入 src/app.py",
                                                               "kind": "edit"}}}})
                resp_line = sys.stdin.buffer.readline()
                try:
                    resp = json.loads(resp_line.decode("utf-8"))
                except Exception:
                    resp = {}
                outcome = (resp.get("result") or {}).get("outcome")
                allowed = False
                if isinstance(outcome, dict) and outcome.get("outcome") == "selected":
                    allowed = outcome.get("optionId") == "opt-allow"
                if not allowed:
                    sendUpdate(out, session_id, contentChunk(message_id, "权限被拒，任务中止"))
                    sendUpdate(out, session_id, idleUpdate("end_of_turn"))
                    send(out, {"jsonrpc": "2.0", "id": msg_id, "result": {"messageId": message_id}})
                    continue
            # ok / push_notify / acp_permission(allow) 共用：流式块 → 未知分支
            # （notice 与自定义 _future_kind，验证「未知类型跳过」纪律）→
            # idle 收口 → 回执。
            sendUpdate(out, session_id, contentChunk(message_id, "你好 Neuacp"))
            sendUpdate(out, session_id, thoughtChunk(message_id + "-t", "思考中"))
            sendUpdate(out, session_id, {"sessionUpdate": "notice",
                                         "severity": "info", "title": "提示"})
            sendUpdate(out, session_id, {"sessionUpdate": "_future_kind",
                                         "payload": {"x": 1}})
            sendUpdate(out, session_id, idleUpdate("end_of_turn"))
            send(out, {"jsonrpc": "2.0", "id": msg_id, "result": {"messageId": message_id}})
            continue

        if method == "session/request_permission":
            # 客户端不应主动发这个方向；按 v1 时代遗留行为收到即回错。
            invalidParams(out, msg_id, "client must not send session/request_permission")
            continue

        if msg_id is not None:
            send(out, {"jsonrpc": "2.0", "id": msg_id,
                       "error": {"code": -32601, "message": "method not found"}})


if __name__ == "__main__":
    main()
