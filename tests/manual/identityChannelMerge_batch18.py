# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-12 批 18，§6-163 裁定甲「身份通道全量合并」）：一条通道的活体读数。

判据档（`tests/unit/core/test_identityChannelMergedToOneSource.py` 等）审的是形状与台账；
这一支要证的是**跑起来之后**那三件人真正在意的事：

1. 进程里只剩一条装 user_id 的身份通道，且门面再也交不出身份（第三条实参当场 TypeError）；
2. 渠道群里说话的人进通道（配额/usage/profile 池都按他计），而那条会话仍出现在
   **agent 属主**的控制台里、不在发送者的列表里（Issue #290 Wave H-W0 不许回退）；
3. 上面那条可见性真来自那一次显式传参——把属主声明成空，会话立刻对全员可见（反照，
   证明第 2 格不是恒真）。

刻意**不打真 LLM**、不启真 camofox：本批动的是身份归属，不是模型与浏览器（本卷记过
「让探针真 await 生产回落＝把配额花在读判据上」）。替身按真 `Agent.chat` 的签名 bind，
形状错会照样在这里红。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/identityChannelMerge_batch18.py`
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaMerge18")

from neurova.channels import channel_router  # noqa: E402
from neurova.channels.user_identity import UserIdentityManager  # noqa: E402
from neurova.core.identity_context import get_request_user_id  # noqa: E402
from neurova.llm.multi_model_client import _consume_llm_quota  # noqa: E402
from neurova.mem_core import MemCore  # noqa: E402
from neurova.post_chat_pipeline import resolveSessionOwner  # noqa: E402
from neurova.session_manager import SessionManager  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


failures: list[str] = []
AGENT_ID = "merge18-agent"
OWNER = "owner-of-merge18"
PLATFORM_SENDER = "ou_merge18"
SENDER = f"ch:feishu:{PLATFORM_SENDER}"
OTHER = "ch:feishu:ou_other18"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


class _TurnAgent:
    """按真 `Agent.chat` 签名接回合，并用**生产写盘那一行**落会话。"""

    def __init__(self, sessions, sender=SENDER):
        from neurova.agent_core import Agent

        self._sig = inspect.signature(Agent.chat)
        self.config = SimpleNamespace(agent_id=AGENT_ID, owner_user_id=OWNER)
        self.session_manager = sessions
        self.memory_manager = None
        self.seen: dict = {}
        self.sender = sender

    async def chat(self, user_input, session_id=None, metadata=None, **kw):
        self._sig.bind(None, user_input, session_id=session_id, metadata=metadata)
        self.seen = {
            "channel": get_request_user_id(),
            "meta_user_id": (metadata or {}).get("user_id"),
            "session_owner_id": (metadata or {}).get("session_owner_id"),
            "resolved": resolveSessionOwner(metadata),
            "quota_gate": _consume_llm_quota(),
        }
        MemCore(self).save_to_session(user_input, "好的", session_id=session_id,
                                      metadata=metadata,
                                      session_owner=self.seen["resolved"])
        return {"text": "好的"}


def _identityChannelNames() -> set:
    """进程内**所有**装着 user_id 的身份类 ContextVar 的声明名（运行时读数，不扫源码）。"""
    out = set()
    for module in list(sys.modules.values()):
        if module is None:
            continue
        for value in vars(module).values():
            if isinstance(value, ContextVar) and "user_id" in value.name:
                out.add(value.name)
    return out


def _recordsOnDisk(sessions: SessionManager) -> dict:
    """直接读会话 JSON：`session_id → 落盘 user_id`。

    不拿 `list_sessions` 的 session_id 当锚点——实测同一份文件在"本进程内建的摘要索引"
    与"新进程重扫"两条读路里给出的 session_id 字形不同（`agent:chat` 与文件名里那段
    净化过的 `agent-chat-hash`）。那是本批之外的既有形态，已登记台账；本脚本只认盘上事实。
    """
    out: dict = {}
    for path in Path(sessions._sessions_dir).rglob("session_*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        out[str(data.get("session_id"))] = str(data.get("user_id") or "")
    return out


def _message(sender: str = PLATFORM_SENDER, content: str = "帮我看下天气"):
    from neurova.channels.base import ChannelMessage

    return ChannelMessage(channel_type="feishu", message_id="m1", sender_id=sender,
                          sender_name="群成员", content=content, chat_id="oc_merge18",
                          chat_type="p2p", metadata={"agent_id": AGENT_ID})


async def _runTurn(manager, sessions, sender=PLATFORM_SENDER):
    UserIdentityManager.resetInstance()
    UserIdentityManager(str(WORK_ROOT / "bindings18.db"))
    agent = _TurnAgent(sessions)
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    reply = await handler(_message(sender))
    return agent, reply


def main() -> int:
    from neurova.channels.manager import ChannelManager

    manager = ChannelManager()
    sessions = SessionManager()
    print(f"数据根：{WORK_ROOT}")

    agent, reply = asyncio.run(_runTurn(manager, sessions))
    seen = agent.seen

    check("[1] 进程里只剩一条装 user_id 的身份通道",
          _identityChannelNames() == {"neurova_request_user_id"},
          str(sorted(_identityChannelNames())))

    check("[2] 渠道回合真的跑完并回了话", bool(reply) and agent.seen != {}, str(reply))

    check("[3] 通道里是发送者（配额/usage/profile 池按谁在说话计）",
          seen.get("channel") == SENDER, repr(seen.get("channel")))

    check("[4] 载体里也是发送者（记忆隔离口径不变）",
          seen.get("meta_user_id") == SENDER, repr(seen.get("meta_user_id")))

    check("[5] 属主经显式元数据带上，且取法单点认它",
          seen.get("session_owner_id") == OWNER and seen.get("resolved") == OWNER,
          f"meta={seen.get('session_owner_id')!r} resolved={seen.get('resolved')!r}")

    check("[6] 配额闸在这一回合按发送者判（放行＝None；无身份才不判）",
          seen.get("quota_gate") is None, repr(seen.get("quota_gate")))

    # 反照先铺：另写一条"声明空属主"的会话（＝后台任务/排程那一形）。它同时也是下面
    # 三格读面计数的分母——没有它，"发送者看不见渠道会话"可能只是"列表根本不过滤"买来的恒真。
    blankId = "sess-merge18-blank"
    MemCore(SimpleNamespace(session_manager=sessions,
                            config=SimpleNamespace(agent_id=AGENT_ID))
            ).save_to_session("问", "答", session_id=blankId, metadata={},
                              session_owner=resolveSessionOwner({"session_owner_id": ""}))

    disk = _recordsOnDisk(sessions)
    ownedByOwner = [k for k, v in disk.items() if v == OWNER]
    blankRecords = [k for k, v in disk.items() if v == ""]

    check("[7] 盘上：渠道会话的属主字段就是 agent 属主（一条、不多不少）",
          len(ownedByOwner) == 1 and len(blankRecords) == 1, str(disk))

    ownerView = sessions.list_sessions(agent_id=AGENT_ID, user_id=OWNER)
    senderView = sessions.list_sessions(agent_id=AGENT_ID, user_id=SENDER)
    otherView = sessions.list_sessions(agent_id=AGENT_ID, user_id=OTHER)
    check("[8] 读面：属主的控制台列表 = 属主名下那条 + 空属主那条（H-W0 成立）",
          len(ownerView) == 2 and any(s.get("user_id") == OWNER for s in ownerView),
          f"ownerView={[(s['session_id'], s.get('user_id')) for s in ownerView]}")
    check("[9] 反向：发送者/路人各自的列表里只剩空属主那条（两件事没混成一件）",
          len(senderView) == 1 and len(otherView) == 1
          and all(s.get("user_id") == "" for s in senderView)
          and all(s.get("user_id") == "" for s in otherView),
          f"senderView={[(s['session_id'], s.get('user_id')) for s in senderView]} "
          f"otherView={[(s['session_id'], s.get('user_id')) for s in otherView]}")
    check("[10] 反照：声明空属主 ⇒ 落盘属主为空且对任意登录用户可见（[9] 的牙来自这里）",
          disk.get(blankId) == "" and any(s.get("session_id") in (blankId,) or
                                          s.get("user_id") == "" for s in otherView),
          f"disk[{blankId!r}]={disk.get(blankId)!r}")

    # 门面的第三条实参必须当场抛——不抛说明那条通道还有地方复活。
    from neurova.agent_core import Agent

    try:
        Agent.__new__(Agent).set_request_identity("x", "sess-x", "u-x")
        check("[11] 门面不再收身份（第三实参必 TypeError）", False, "竟然调用成功了")
    except TypeError as exc:
        check("[11] 门面不再收身份（第三实参必 TypeError）", True, str(exc))

    print(f"\n合计 {len(failures)} 项 FAIL")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
