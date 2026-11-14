"""注入 write-ahead 账本（P1-6）。

- 记录/读取回路：seq 单调、content 字节级留痕（含中文）、hash=sha256(content)；
- verifyInjections：完好计数 + 篡改点名；
- 坏行（崩溃截断的半行）跳过不炸读侧；
- 体量治理：超过阈值压缩保留最近 KEEP 行；
- 编排器装配出口（_finishContext）write-ahead：先落账、后进模型；
  健康读数 injection_ledger 槽反映行数与完整性。
"""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from neurova.context import injection_ledger as il


@pytest.fixture
def dataRoot(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "neurova.core.data_root.resolveDataPath",
        lambda *parts, **k: tmp_path.joinpath(*parts),
    )
    return tmp_path


class TestLedgerRoundtrip:
    def test_record_and_read(self, dataRoot, session="sess-1"):
        row1 = il.recordInjection(session, "final_user_view", "第一轮<envelope>注入</envelope>\n\n输入一")
        row2 = il.recordInjection(session, "final_user_view", "第二轮输入")
        assert row1["seq"] == 1 and row2["seq"] == 2
        rows = il.readInjections(session)
        assert [r["seq"] for r in rows] == [1, 2]
        assert rows[0]["content"] == "第一轮<envelope>注入</envelope>\n\n输入一"
        assert rows[1]["content"] == "第二轮输入"

    def test_hash_is_sha256_of_content(self, dataRoot):
        row = il.recordInjection("s", "final_user_view", "abc")
        assert row["hash"] == hashlib.sha256("abc".encode("utf-8")).hexdigest()

    def test_verify_ok(self, dataRoot):
        il.recordInjection("s", "k", "a")
        il.recordInjection("s", "k", "b")
        report = il.verifyInjections("s")
        assert report == {"rows": 2, "ok": 2, "broken": 0, "last_seq": 2, "last_error": None}

    def test_verify_detects_tampering(self, dataRoot):
        il.recordInjection("s", "k", "original")
        il.recordInjection("s", "k", "second")
        path = il.ledgerPathFor("s")
        lines = path.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(lines[0])
        tampered["content"] = "改过的历史"
        lines[0] = json.dumps(tampered, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = il.verifyInjections("s")
        assert report["rows"] == 2 and report["broken"] == 1 and report["ok"] == 1

    def test_empty_session(self, dataRoot):
        assert il.readInjections("ghost") == []
        assert il.verifyInjections("ghost")["rows"] == 0

    def test_invalid_input_noop(self, dataRoot):
        assert il.recordInjection("", "k", "c") is None
        assert il.recordInjection("s", "k", "") is None
        assert il.readInjections("s") == []

    def test_broken_line_skipped(self, dataRoot):
        il.recordInjection("s", "k", "good")
        path = il.ledgerPathFor("s")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"seq": 2, "content": "半行截断\n')
        rows = il.readInjections("s")
        assert [r["seq"] for r in rows] == [1]
        assert il.verifyInjections("s")["rows"] == 1

    def test_compaction_keeps_recent_bytes(self, dataRoot, monkeypatch):
        """体量治理按字节：实测单行可达数百 KB，按行数治理会膨到数百 MB。"""
        monkeypatch.setattr(il, "COMPACTION_CHECK_INTERVAL", 5)
        monkeypatch.setattr(il, "COMPACTION_MAX_BYTES", 4000)
        monkeypatch.setattr(il, "COMPACTION_KEEP_BYTES", 2000)
        for i in range(1, 21):
            il.recordInjection("s", "k", "x" * 300)
        rows = il.readInjections("s")
        assert len(rows) < 20, "老行应被按体量压缩掉"
        assert rows[-1]["content"] == "x" * 300
        assert il.verifyInjections("s")["broken"] == 0


class TestFinishContextWriteAhead:
    """装配出口 write-ahead：_finishContext 先落账、后进模型。"""

    def _orchestrator(self):
        from neurova.context.orchestrator import ContextOrchestrator

        orch = ContextOrchestrator.__new__(ContextOrchestrator)
        orch._context_health = orch._emptyContextHealth()
        return orch

    def test_finish_context_writes_ahead(self, dataRoot, monkeypatch):
        monkeypatch.setattr(
            "neurova.core.turn_context.get_turn_session_id", lambda: "sess-test"
        )
        orch = self._orchestrator()
        context = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "<memories>召回行</memories>\n\n用户输入"},
        ]
        asyncio.run(orch._finishContext(context))
        rows = il.readInjections("sess-test")
        assert len(rows) == 1
        assert rows[-1]["kind"] == "final_user_view"
        assert rows[-1]["content"] == context[-1]["content"]
        assert rows[-1]["meta"]["messages_in_view"] == 2
        health = orch.get_context_health()
        assert health["injection_ledger"]["rows"] == 1
        assert health["injection_ledger"]["ok"] == 1

    def test_no_session_identity_no_ledger(self, dataRoot, monkeypatch):
        monkeypatch.setattr(
            "neurova.core.turn_context.get_turn_session_id", lambda: None
        )
        orch = self._orchestrator()
        context = [{"role": "user", "content": "x"}]
        asyncio.run(orch._finishContext(context))
        assert il.readInjections("sess-test") == []
        health = orch.get_context_health()
        assert health["injection_ledger"]["rows"] == 0

    def test_last_user_message_selected_not_first(self, dataRoot, monkeypatch):
        """多轮视图里取的是最后一条 user（信封挂在末条），不是第一条。"""
        monkeypatch.setattr(
            "neurova.core.turn_context.get_turn_session_id", lambda: "sess-multi"
        )
        orch = self._orchestrator()
        context = [
            {"role": "user", "content": "历史 user 行"},
            {"role": "assistant", "content": "回复"},
            {"role": "user", "content": "信封+最新输入"},
        ]
        asyncio.run(orch._finishContext(context))
        rows = il.readInjections("sess-multi")
        assert rows[-1]["content"] == "信封+最新输入"
