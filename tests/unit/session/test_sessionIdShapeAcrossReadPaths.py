# -*- coding: utf-8 -*-
"""§6-163 留案② 取证之后的修复批：两条读路必须给出**同一个** `session_id`。

取证三问的实测答复（写在档头，免得下一个人再测一遍）：

① **用列表给出的 id 续聊，不会另起一条会话**。`normalize_store_key()` 对已合规的名字原样返回
   （幂等），而文件名里那串 `slug + sha1[:8]` 本身就合规 ⇒ 再归一还是它自己 ⇒ 仍指向同一个
   `session_{key}_{date}.json`。这条由下面的 `test_reopeningByListedIdIsIdempotent` 钉住——
   它钉的是"幂等"这个**前提**：哪天 `normalize_store_key` 改成每次追加 digest，续聊就开始
   分裂，而那时先红的应该是这格。
② 但两条读路给的**字形不同**：全量重扫用记录里的真 id（`agent-x:oc_private`），
   sidecar 快路径用**文件名派生的键**（`agent-x-oc_private-77286d14`）——而索引条目里
   本来就存着真 id（`_rebuild_sidecar` 同时写 `id` 与 `session_id`），
   `_summary_from_entry()` 只取了键。于是同一份数据在"进程内首次列出"与"重启后列出"
   给出两个 id。
③ 影响面正是**渠道会话**：`resolve_session_scope_id()` 天然产带冒号的键（冒号在 NTFS 是
   数据流分隔符，所以必须净化才能落盘），而控制台把"我正在看的这条"与列表行做关联是
   **按 id 字符串比**的（`NeurUI/src/stores/chat.optimized.ts` 的 `selectSession(s.id)`
   与聊天响应里的 `session_id` 相比）。跨重启后两边不同形 ⇒ 高亮/续聊指向另一行。

既有档 `tests/unit/api/test_session_summary_sidecar.py` 有一条"索引视图 == 全量扫描视图
逐字段一致"的质检，但它喂的 id 全部来自 `create_session()`（合规、不会被净化）⇒
**这条性质从没打过会变形的输入**，于是常年全绿。本档补的就是那一种形状。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pytest

from neurova.session_manager import SessionManager, normalize_store_key

AGENT = "shape-agent"
CHANNEL_ID = "shape-agent:oc_private"


@pytest.fixture()
def store(tmp_path) -> SessionManager:
    manager = SessionManager()
    assert manager._sessions_dir == tmp_path / "sessions", (
        f"会话落点没被隔离（{manager._sessions_dir}）——会读写仓库真实 data/sessions")
    manager._summary_cache.clear()
    manager._feedback_cache.clear()
    return manager


def _channelSession(manager: SessionManager, sessionId: str = CHANNEL_ID) -> None:
    manager.add_message(agent_id=AGENT, session_id=sessionId, user_content="一",
                        assistant_content="A", user_id="u-shape")


def _sidecarView(manager: SessionManager) -> List[Dict[str, object]]:
    """只走快路径：索引必须存在且有效（否则本函数返回 None，判据不会假装看过）。"""
    view = manager._summaries_via_sidecar([manager._get_session_dir(AGENT)], "u-shape")
    assert view is not None, "sidecar 快路径没生效——上一格读的是回退扫描，本档对照不成立"
    return view


def _fullScanView(manager: SessionManager) -> List[Dict[str, object]]:
    """只走全量扫描（读会话文件正文，拿记录里的真 id）。"""
    return manager._collect_summaries([manager._get_session_dir(AGENT)], "u-shape")


def _indexEntryIds(manager: SessionManager) -> Dict[str, str]:
    index = json.loads((manager._get_session_dir(AGENT) / "_summary_index.json")
                       .read_text(encoding="utf-8"))
    return {key: str(entry.get("session_id") or "")
            for key, entry in (index.get("sessions") or {}).items()}


class TestBothReadPathsAgreeOnTheId:
    def test_sidecarViewHandsBackTheRealSessionId(self, store):
        """① 快路径给出的 `session_id`/`id` 必须就是记录里那一个。"""
        _channelSession(store)
        assert store.list_sessions(agent_id=AGENT, user_id="u-shape")  # 触发建索引

        entry = _sidecarView(store)[0]

        assert entry["session_id"] == CHANNEL_ID, (
            f"sidecar 读路给的是文件名派生的 id {entry['session_id']!r}，而记录里是 "
            f"{CHANNEL_ID!r}——重启前后同一会话有两个 id，控制台按字符串比就比不中")
        assert entry["id"] == CHANNEL_ID, f"`id` 同形才对：{entry['id']!r}"

    def test_sidecarAndFullScanAreFieldForFieldEqual(self, store):
        """② 两视图逐字段相等（既有那条质检的口径，但喂**会被净化的 id**）。"""
        _channelSession(store)
        store.list_sessions(agent_id=AGENT, user_id="u-shape")

        fast = _sidecarView(store)
        slow = _fullScanView(store)

        assert [f["session_id"] for f in fast] == [s["session_id"] for s in slow], (
            f"两条读路的会话号不同形：sidecar {fast[0]['session_id']!r} / "
            f"全扫 {slow[0]['session_id']!r}")

    def test_reopeningByListedIdIsIdempotent(self, store):
        """③ 前提锁：按列表给出的 id 续聊，必须落回同一条会话（不另起一份文件）。

        这条今天就是绿的——留在这里是因为它是①②的安全前提：`normalize_store_key` 一旦
        不再幂等，重启后按净化名续聊就会分裂成新会话，而①②两格都看不出来。
        """
        _channelSession(store)
        listed = [s["session_id"] for s in store.list_sessions(agent_id=AGENT,
                                                               user_id="u-shape")]
        filesBefore = sorted(p.name for p in store._get_session_dir(AGENT).glob("session_*.json"))

        reopenIds = list(dict.fromkeys(listed + [normalize_store_key(CHANNEL_ID)]))
        for sessionId in reopenIds:
            store.add_message(agent_id=AGENT, session_id=sessionId, user_content="二",
                              assistant_content="B", user_id="u-shape")

        filesAfter = sorted(p.name for p in store._get_session_dir(AGENT).glob("session_*.json"))
        assert filesAfter == filesBefore, f"按列表 id 续聊另起了文件：{filesAfter}"
        records = [json.loads(p.read_text(encoding="utf-8"))
                   for p in store._get_session_dir(AGENT).glob("session_*.json")]
        assert len(records) == 1, f"一条渠道会话被拆成 {len(records)} 份文件"
        assert len(records[0].get("messages", [])) == 2 + 2 * len(reopenIds), (
            f"消息没并进同一条记录：{records[0].get('messages')}")


class TestThePremisesAndTheTeeth:
    def testChannelScopeIdReallyIsSanitizable(self, store):
        """④ 前提格：本档打的输入必须真在生产里出现——渠道会话号天生带冒号。

        没有这格，①②可能是在为一个不存在的形状作证（本卷记过：档案自写的取证限制
        被自己下一格违反）。
        """
        from neurova.channels.base import ChannelMessage
        from neurova.channels.manager import ChannelManager

        message = ChannelMessage(channel_type="feishu", message_id="m1", sender_id="ou_1",
                                 sender_name="群成员", content="你好", chat_id="oc_1",
                                 chat_type="p2p", metadata={"agent_id": AGENT})
        scopeId = ChannelManager().resolve_session_scope_id(message)
        assert scopeId, "resolve_session_scope_id 没产出会话号——渠道面今天不落的判断要重来"
        assert normalize_store_key(scopeId) != scopeId, (
            f"渠道会话号 {scopeId!r} 竟然不需要净化 ⇒ 本档①②的靶已换，须连同修复一起重判")

    def testIndexAlreadyCarriesTheRealId(self, store):
        """⑤ 修复点不是"多存一份字段"：索引条目里真 id 早就在，只是读侧没取它。"""
        _channelSession(store)
        assert store.list_sessions(agent_id=AGENT, user_id="u-shape")

        pairs = _indexEntryIds(store)

        assert normalize_store_key(CHANNEL_ID) in pairs, f"索引键不是净化名：{pairs}"
        assert pairs[normalize_store_key(CHANNEL_ID)] == CHANNEL_ID, (
            f"索引条目里的 session_id 不是真 id：{pairs}——那本档①的修法（读 entry）"
            "就不成立，得回到写侧补")

    def testReverseControlTakingTheKeyInsteadOfTheEntryIsCaught(self, store, monkeypatch):
        """⑥ 反向自证：把读侧改回 HEAD 那个取法（用键），①②两格必须当场红。"""
        _channelSession(store)
        assert store.list_sessions(agent_id=AGENT, user_id="u-shape")

        original = SessionManager._summary_from_entry

        def headShape(self, sid, entry):
            summary = original(self, sid, entry)
            summary["session_id"] = sid
            summary["id"] = sid
            return summary

        monkeypatch.setattr(SessionManager, "_summary_from_entry", headShape)

        assert _sidecarView(store)[0]["session_id"] != CHANNEL_ID, (
            "复刻 HEAD 取法却仍给出真 id ⇒ ① 是恒真的空守卫")
        assert [f["session_id"] for f in _sidecarView(store)] != [
            s["session_id"] for s in _fullScanView(store)], (
            "复刻 HEAD 取法两视图仍相等 ⇒ ② 是恒真的空守卫")

    def testSafeIdsAreUntouchedByTheFix(self, store):
        """⑦ 不误伤：本来合规的 id（控制台/网页会话）在两条读路里都原样。"""
        plain = "sess-plain-1"
        store.add_message(agent_id=AGENT, session_id=plain, user_content="一",
                          assistant_content="A", user_id="u-shape")
        assert store.list_sessions(agent_id=AGENT, user_id="u-shape")

        assert _sidecarView(store)[0]["session_id"] == plain
        assert _fullScanView(store)[0]["session_id"] == plain

    def testArchivedListUsesTheSameShape(self, store):
        """⑧ 存档那条读路是同一处代码（`list_archived_sessions` 也走 sidecar）——别只修活的一侧。"""
        _channelSession(store)
        store.archive_session(AGENT, CHANNEL_ID)

        archived = store.list_archived_sessions(agent_id=AGENT, user_id="u-shape")

        assert archived and archived[0]["session_id"] == CHANNEL_ID, (
            f"存档列表给的还是文件名派生 id：{[a['session_id'] for a in archived]}")
