#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Issue #90 · T-10a 收口 live-verify：直取寻址按会话属主读台账（真链路）。

走**真构造面**，不手工造台账：

1. 真 `SessionManager`（唯一会话读写实现）写一轮带工具结果的会话；
2. 真 `ToolExecutor._recall_by_call_id` 按硬地址直取；
3. 断言取回的是刚落盘的原文，且读侧发给仓库的 agent_id = 会话属主。

改前（读侧传空 agent_id）本条即红：空值被 `SessionManager._get_session_dir`
归入 `default/` 目录，直取恒落空。

用法：
    PYTHONPATH=. python tests/manual/tool_call_ledger_owner_90.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from neurova.session_manager import SessionManager
from neurova.tool_executor import ToolExecutor

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402
isolatedDataRoot()

OWNER = "neurova_owner_lv"
SESSION = "sess_lv_t10a"
CALL_ID = "call_lv_owner_1"
RAW = "台账原文：北京晴，26 度"


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="t10a_owner_"))
    print(f"[0 环境] 临时 sessions 根 = {root}")

    session_manager = SessionManager()
    session_manager._sessions_dir = root
    session_manager.add_message(
        agent_id=OWNER,
        session_id=SESSION,
        user_content="查天气",
        assistant_content="好的",
        metadata=None,
        assistant_metadata={
            "tool_calls": [
                {"type": "tool_call", "tool_name": "probe_read",
                 "tool_call_id": CALL_ID, "arguments": '{"path": "w.txt"}'},
                {"type": "tool_result", "tool_name": "probe_read",
                 "tool_call_id": CALL_ID, "result": RAW, "success": True},
            ]
        },
        user_id="",
    )

    written_dirs = sorted(p.name for p in root.iterdir())
    print(f"[1 写侧] sessions 根下目录 = {written_dirs}")

    seen = {}
    real_repo = session_manager

    class _RecordingRepo:
        def get_history(self, agent_id="", session_id="", max_messages=0):
            seen["agent_id"] = agent_id
            return real_repo.get_history(
                agent_id=agent_id, session_id=session_id, max_messages=max_messages
            )

    agent = SimpleNamespace(
        current_session_id=SESSION,
        config=SimpleNamespace(name="probe", user_id="u1", agent_id=OWNER),
        session_repo=_RecordingRepo(),
        workspace_path=".",
    )
    executor = ToolExecutor.__new__(ToolExecutor)
    executor._agent = agent

    import asyncio

    out = asyncio.run(executor._recall_by_call_id(CALL_ID, {"session_id": SESSION}))

    print(f"[2 读侧] 发给仓库的 agent_id = {seen.get('agent_id')!r}（属主 = {OWNER!r}）")
    print(f"[3 直取] 取回 = {json.dumps(out, ensure_ascii=False)[:120]}")

    ok_owner = seen.get("agent_id") == OWNER
    got = out.get("result") or out.get("content")
    ok_text = got == RAW

    print(f"[4 判据] agent_id 与会话属主一致 = {ok_owner}；原文逐字取回 = {ok_text}")
    if ok_owner and ok_text:
        print("LIVE-VERIFY PASSED")
        return 0
    print("LIVE-VERIFY FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
