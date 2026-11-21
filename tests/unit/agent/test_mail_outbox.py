# -*- coding: utf-8 -*-
"""A3 effect outbox（崩溃安全的副作用投递意图层）。

被测模块：`neurova/agent/mail_outbox.py`（持久投递意图）与
`neurova/agent/swarm.py::pushParentMail`（意图登记/销账接线）、
`neurova/agent/swarm_support.py::reconcileSwarmRunsAtStartup`（启动对账挂点）。

断言全部落在真实 SQLite 与真实 AgentMailbox 上（临时文件库，无 MagicMock 充当存储）：
- recordIntent 同 intentId 幂等（首写为准，不覆盖不重复）；
- markDelivered 幂等销账、未知 id 诚实 False；
- pendingIntents 按 pairingKey 过滤、按落单序返回；
- deleteDelivered 只清已投递（可按 before_ts 截断），防无界增长；
- 崩溃恢复：recordIntent 后「进程崩溃」（不销账、内存邮箱随进程丢失）→
  新 outbox 实例 + 新邮箱实例 reconcile → 邮箱收到补投；已入箱未销账的
  意图重投同 messageId 不重复生效（宁重不丢）；
- pushParentMail 接线：投递成功意图即销账；投递失败意图留待重投；
  outbox 故障（注入异常）不阻断投递主流程（fail-open）；
- 启动对账挂点：reconcileSwarmRunsAtStartup 会补投 outbox 里的 pending 意图。
"""
from __future__ import annotations

import json
import time

import pytest

import neurova.agent.swarm as swarm_module
from neurova.agent.swarm import (
    SUBAGENT_COMPLETED,
    SubAgentRun,
    get_swarm_manager,
    reset_swarm_manager,
)


# ── 夹具与工具 ──────────────────────────────────────────────────


@pytest.fixture()
def outbox(tmp_path):
    from neurova.agent.mail_outbox import MailOutbox

    box = MailOutbox(db_path=tmp_path / "mail_outbox.db")
    yield box
    box.close()


@pytest.fixture()
def mailbox(monkeypatch):
    from neurova.agent import mailbox as mb
    from neurova.agent.mailbox import AgentMailbox

    box = AgentMailbox()
    monkeypatch.setattr(mb, "_MAILBOX", box)
    yield box
    monkeypatch.setattr(mb, "_MAILBOX", None)


@pytest.fixture()
def wired_outbox(tmp_path, monkeypatch):
    """把 swarm._mailOutbox 指向临时库实例（接线测试不碰进程级单例落点）。"""
    from neurova.agent.mail_outbox import MailOutbox

    box = MailOutbox(db_path=tmp_path / "mail_outbox_wiring.db")
    monkeypatch.setattr(swarm_module, "_mailOutbox", lambda: box)
    yield box
    box.close()


@pytest.fixture()
def swarm():
    reset_swarm_manager()
    from neurova.agent.delegated_delivery import getDeliveryLedger
    from neurova.agent.mailbox import reset_agent_mailbox

    reset_agent_mailbox()
    ledger = getDeliveryLedger()
    ledger._tickets.clear()
    ledger._byMessageId.clear()
    yield get_swarm_manager()
    reset_swarm_manager()
    reset_agent_mailbox()


def _payload(message_id="dlv_t1", session="sess-1"):
    """与 pushParentMail 登记的 payload 契约同形（投递重放所需全量字段）。"""
    return {
        "session_id": session,
        "message_id": message_id,
        "tag": "子Agent结果",
        "envelope": {"kind": "submit_result", "summary": "已完成"},
        "priority": "normal",
    }


def _deliverFn(mailbox):
    """对账投递函数：按意图 payload 原样重投会话邮箱（与 _outboxRedeliver 同契约）。"""

    def deliver(intent):
        p = intent["payload"]
        return mailbox.push(
            p["session_id"],
            f"[{p['tag']}] " + json.dumps(p["envelope"], ensure_ascii=False),
            priority=p.get("priority") or "normal",
            message_id=p["message_id"],
        )

    return deliver


def _run(swarm, sid, status=SUBAGENT_COMPLETED, parent=""):
    run = SubAgentRun(
        subagent_id=sid, depth=1, agent_id="agent-a", agent_name="A",
        task="样例任务", origin="chat", session_id="sess-1",
        member_session_id="", parent_subagent_id=parent, status=status,
    )
    with swarm._lock:
        swarm._runs[sid] = run
    return run


# ── MailOutbox 基础契约 ─────────────────────────────────────────


class TestMailOutboxBasics:
    def test_recordIntent_persists_and_is_idempotent(self, outbox):
        first = outbox.recordIntent("dlv_1", "sess-1", _payload("dlv_1"))
        assert first["intent_id"] == "dlv_1"
        assert first["status"] == "intent"
        assert first["payload"] == _payload("dlv_1")
        # 同 id 重复登记：幂等返回既有意图，首写为准（不覆盖 payload）
        second = outbox.recordIntent("dlv_1", "sess-1", _payload("dlv_1", session="sess-other"))
        assert second["created_ts"] == first["created_ts"]
        assert second["payload"]["session_id"] == "sess-1"
        assert len(outbox.snapshot()) == 1

    def test_recordIntent_validates_inputs(self, outbox):
        from neurova.agent.mail_outbox import MailOutboxError

        with pytest.raises(MailOutboxError):
            outbox.recordIntent("", "sess-1", _payload())
        with pytest.raises(MailOutboxError):
            outbox.recordIntent("dlv_x", "  ", _payload())

    def test_markDelivered_idempotent_and_unknown(self, outbox):
        outbox.recordIntent("dlv_2", "sess-1", _payload("dlv_2"))
        assert outbox.markDelivered("dlv_2") is True
        assert outbox.pendingIntents() == []
        # 重复销账幂等；未知 id 诚实 False
        assert outbox.markDelivered("dlv_2") is True
        assert outbox.markDelivered("no-such-id") is False
        assert outbox.markDelivered("") is False

    def test_pendingIntents_filters_by_pairing_and_orders(self, outbox):
        outbox.recordIntent("dlv_a", "sess-1", _payload("dlv_a"))
        outbox.recordIntent("dlv_b", "sess-2", _payload("dlv_b", session="sess-2"))
        outbox.recordIntent("dlv_c", "sess-1", _payload("dlv_c"))
        outbox.markDelivered("dlv_a")
        pendingSess1 = outbox.pendingIntents("sess-1")
        assert [i["intent_id"] for i in pendingSess1] == ["dlv_c"]
        assert [i["intent_id"] for i in outbox.pendingIntents("sess-2")] == ["dlv_b"]
        # 全域待投按落单序
        assert [i["intent_id"] for i in outbox.pendingIntents()] == ["dlv_b", "dlv_c"]

    def test_deleteDelivered_cleans_only_delivered(self, outbox):
        outbox.recordIntent("dlv_old", "sess-1", _payload("dlv_old"))
        outbox.recordIntent("dlv_keep", "sess-1", _payload("dlv_keep"))
        outbox.markDelivered("dlv_old")
        # before_ts 在未来：清掉已投递的；未投递的保留
        assert outbox.deleteDelivered(before_ts=time.time() + 60) == 1
        assert [i["intent_id"] for i in outbox.pendingIntents()] == ["dlv_keep"]
        # before_ts=0：什么也不删
        outbox.markDelivered("dlv_keep")
        assert outbox.deleteDelivered(before_ts=0) == 0
        # 不带参：清剩余已投递（dlv_old 已被 before_ts 步骤清掉）
        assert outbox.deleteDelivered() == 1
        assert outbox.snapshot() == []

    def test_schema_domain_registered(self):
        from neurova.agent.mail_outbox import MAIL_OUTBOX_DB_DOMAIN
        from neurova.core.db_migration import latest_version, registered_domains

        assert MAIL_OUTBOX_DB_DOMAIN in registered_domains()
        assert latest_version(MAIL_OUTBOX_DB_DOMAIN) >= 1


# ── 崩溃恢复（核心场景）─────────────────────────────────────────


class TestCrashRecovery:
    def test_reconcile_redelivers_intent_after_crash(self, tmp_path, mailbox):
        from neurova.agent.mail_outbox import MailOutbox

        dbFile = tmp_path / "mail_outbox.db"
        # 进程一：登记意图后即崩溃——不 markDelivered，内存邮箱随进程丢失
        crashed = MailOutbox(db_path=dbFile)
        crashed.recordIntent("dlv_crash", "sess-1", _payload("dlv_crash"))
        crashed.close()

        # 进程二：新 outbox 实例（同一库文件）+ 新邮箱实例，启动对账补投
        reborn = MailOutbox(db_path=dbFile)
        try:
            report = reborn.reconcile(_deliverFn(mailbox))
            assert report == {"attempted": 1, "delivered": 1, "failed": 0}
            mails = mailbox.lease("sess-1")
            assert [m["messageId"] for m in mails] == ["dlv_crash"]
            assert reborn.pendingIntents() == []
            # 对账幂等：无待投意图时再跑不重复投递
            assert reborn.reconcile(_deliverFn(mailbox))["attempted"] == 0
            assert mailbox.pending("sess-1") == 1
        finally:
            reborn.close()

    def test_reconcile_after_push_before_mark_is_dedup_safe(self, tmp_path, mailbox):
        """「已入箱、销账前崩溃」：重投同 messageId 被邮箱幂等去重，不重复生效。"""
        from neurova.agent.mail_outbox import MailOutbox

        box = MailOutbox(db_path=tmp_path / "mail_outbox.db")
        box.recordIntent("dlv_dup", "sess-1", _payload("dlv_dup"))
        p = _payload("dlv_dup")
        mailbox.push(
            "sess-1",
            f"[{p['tag']}] " + json.dumps(p["envelope"], ensure_ascii=False),
            message_id="dlv_dup",
        )
        try:
            report = box.reconcile(_deliverFn(mailbox))
            assert report == {"attempted": 1, "delivered": 1, "failed": 0}
            assert mailbox.pending("sess-1") == 1
            assert box.pendingIntents() == []
        finally:
            box.close()

    def test_reconcile_keeps_intent_on_delivery_failure(self, tmp_path, mailbox):
        """投递失败（False/异常）意图保持 pending——宁重不丢，不下账。"""
        from neurova.agent.mail_outbox import MailOutbox

        box = MailOutbox(db_path=tmp_path / "mail_outbox.db")
        box.recordIntent("dlv_fail", "sess-1", _payload("dlv_fail"))
        try:
            report = box.reconcile(lambda intent: False)
            assert report == {"attempted": 1, "delivered": 0, "failed": 1}
            assert len(box.pendingIntents()) == 1

            def boom(intent):
                raise RuntimeError("邮箱不可用")

            report = box.reconcile(boom)
            assert report["failed"] == 1
            assert len(box.pendingIntents()) == 1
        finally:
            box.close()


# ── pushParentMail 接线 ─────────────────────────────────────────


class TestPushParentMailWiring:
    def test_push_settles_intent_on_success(self, swarm, wired_outbox, mailbox):
        child = _run(swarm, "child-out-1")
        assert swarm.pushParentMail(child, "子Agent结果", {"kind": "submit_result"}) is True
        assert mailbox.pending("sess-1") == 1
        # 正常路径：意图登记后随投递成功即销账
        assert wired_outbox.pendingIntents() == []
        rows = wired_outbox.snapshot()
        assert len(rows) == 1
        assert rows[0]["status"] == "delivered"
        assert rows[0]["payload"]["session_id"] == "sess-1"

    def test_push_failure_keeps_intent_pending(self, swarm, wired_outbox, mailbox):
        child = _run(swarm, "child-out-2")
        mailbox.max_per_session = 0  # 箱满 → push 诚实失败
        assert swarm.pushParentMail(child, "子Agent结果", {"kind": "submit_result"}) is False
        assert mailbox.pending("sess-1") == 0
        pending = wired_outbox.pendingIntents()
        assert len(pending) == 1
        assert pending[0]["status"] == "intent"

    def test_push_survives_outbox_failure(self, swarm, wired_outbox, mailbox, monkeypatch):
        child = _run(swarm, "child-out-3")

        def boom(*args, **kwargs):
            raise RuntimeError("outbox 磁盘故障")

        monkeypatch.setattr(wired_outbox, "recordIntent", boom)
        # outbox 故障 fail-open：投递主流程不受阻
        assert swarm.pushParentMail(child, "子Agent结果", {"kind": "submit_result"}) is True
        assert mailbox.pending("sess-1") == 1


# ── 启动对账挂点 ────────────────────────────────────────────────


class TestStartupReconcileHook:
    def test_reconcileSwarmRunsAtStartup_redelivers_pending(self, tmp_path, monkeypatch, mailbox):
        import neurova.agent.mail_outbox as mo
        import neurova.agent.swarm_support as support
        from neurova.agent.mail_outbox import MailOutbox

        monkeypatch.setenv("NEUROVA_RUN_GATE", "off")  # 单测不建台账库
        box = MailOutbox(db_path=tmp_path / "mail_outbox_hook.db")
        monkeypatch.setattr(mo, "_OUTBOX", box)
        box.recordIntent("dlv_startup", "sess-1", _payload("dlv_startup"))
        reset_swarm_manager()
        try:
            report = support.reconcileSwarmRunsAtStartup()
            assert mailbox.pending("sess-1") == 1
            mails = mailbox.lease("sess-1")
            assert [m["messageId"] for m in mails] == ["dlv_startup"]
            assert box.pendingIntents() == []
            assert report.get("outbox", {}).get("delivered") == 1
        finally:
            box.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
