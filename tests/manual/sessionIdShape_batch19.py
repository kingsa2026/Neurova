# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-12 批 19，§6-163 留案②）：重启后列表给出的还是同一个会话号吗。

判据档 `tests/unit/session/testSessionIdShapeAcrossReadPaths.py` 在同一进程里比两条读路；
这一支要打的是**真跨进程**那一形——控制台重启（新进程读落盘的 `_summary_index.json`）之后，
列表里的渠道会话号必须仍是记录里那一个 `agent:chat`，而不是文件名净化后的
`agent-chat-<hash>`。前端 `stores/chat.optimized.ts` 按 `s.id` 与聊天响应里的 `session_id`
做字符串关联，两种字形一混，"我正在看哪一条"就指到别的行上。

不启 HTTP 栈：这一条性质全在 `SessionManager` 的读路里，起 app 只会把 LLM/端口噪声带进来
（本卷记过"判据问错对象＝弱保护"，也记过"别让探针去 await 生产回落"）。
子进程用**同一份解释器与同一份代码**，只是新开一个进程重新读盘 ⇒ 这才是"重启"的等价形。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/sessionIdShape_batch19.py`
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaSidShape19")

AGENT = "shape19-agent"
CHANNEL_ID = f"{AGENT}:oc_shape19"
OWNER = "owner-shape19"

failures: list[str] = []

CHILD = """
import json, sys
sys.path.insert(0, {repo!r})
from neurova.session_manager import SessionManager
m = SessionManager()
fast = m._summaries_via_sidecar([m._get_session_dir({agent!r})], {owner!r})
listing = [s["session_id"] for s in m.list_sessions(agent_id={agent!r}, user_id={owner!r})]
slow = [s["session_id"] for s in m._collect_summaries([m._get_session_dir({agent!r})], {owner!r})]
print(json.dumps({{"fast": [e["session_id"] for e in (fast or [])],
                   "listing": listing, "slow": slow}}))
"""


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def main() -> int:
    from neurova.session_manager import SessionManager, normalize_store_key

    manager = SessionManager()
    print(f"数据根：{WORK_ROOT}")

    manager.add_message(agent_id=AGENT, session_id=CHANNEL_ID, user_content="一",
                        assistant_content="A", user_id=OWNER)
    inProcess = [s["session_id"] for s in manager.list_sessions(agent_id=AGENT, user_id=OWNER)]
    files = sorted(p.name for p in manager._get_session_dir(AGENT).glob("session_*.json"))

    check("[1] 前提：渠道会话号天生会被净化（否则本脚本在为一个不存在的形状作证）",
          normalize_store_key(CHANNEL_ID) != CHANNEL_ID, f"{CHANNEL_ID} → {normalize_store_key(CHANNEL_ID)}")
    check("[2] 落盘文件名用的是净化名", normalize_store_key(CHANNEL_ID) in files[0], str(files))

    child = subprocess.run(
        [sys.executable, "-c", CHILD.format(repo=str(Path(__file__).resolve().parents[2]),
                                            agent=AGENT, owner=OWNER)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        # 写侧也钉 UTF-8：本机 locale 是 cp936 时，子进程 stdout 的编码由它决定，
        # 读侧显式 utf-8 而写侧照 locale 走，中文读数会被替换成 U+FFFD 而不是报错。
        env={**os.environ, "NEUROVA_DATA_DIR": str(WORK_ROOT), "PYTHONIOENCODING": "utf-8"},
    )
    payload = json.loads(child.stdout.strip().splitlines()[-1]) if child.stdout.strip() else {}
    check("[3] 子进程（＝重启后）读到了索引快路径，而不是回退全扫",
          bool(payload.get("fast")), (child.stderr or "")[-200:])
    check("[4] 重启后列表给出的仍是记录里的真会话号",
          payload.get("listing") == [CHANNEL_ID],
          f"listing={payload.get('listing')} fast={payload.get('fast')} slow={payload.get('slow')}")
    check("[5] 两条读路在重启后的进程里逐字同形",
          payload.get("fast") == payload.get("slow") == payload.get("listing"),
          f"fast={payload.get('fast')} slow={payload.get('slow')}")

    # 反照：按重启后拿到的 id 续聊，消息必须并进同一条记录（不另起一份文件）。
    listed = payload.get("listing") or []
    fresh = SessionManager()
    for sessionId in listed:
        fresh.add_message(agent_id=AGENT, session_id=sessionId, user_content="二",
                          assistant_content="B", user_id=OWNER)
    filesAfter = sorted(p.name for p in fresh._get_session_dir(AGENT).glob("session_*.json"))
    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in fresh._get_session_dir(AGENT).glob("session_*.json")]
    check("[6] 反照：按列表 id 续聊不另起会话，消息并进同一条记录",
          filesAfter == files and len(records) == 1 and len(records[0].get("messages", [])) == 4,
          f"files={filesAfter} 条数={len(records[0].get('messages', [])) if records else None}")

    print(f"\n合计 {len(failures)} 项 FAIL")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
