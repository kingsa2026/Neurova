# -*- coding: utf-8 -*-
"""P0-3 结构完整性 Doctor（上下文工程十轴 · 轴9）判据与只读诊断面测试。

五类结构病各至少一条红→绿用例 + 无病会话零误报 + 纯函数确定性。
判据口径以真实数据结构为准：
- 池条目 metadata：``turn_id``（turn_N，user 行开新轮、全会话稳定）、
  ``pairs_with``（TOOL_CALL 的配对锚）、``tool_call_id``；
- SUMMARY 层节点 metadata：``covers={turn_range, hashes}`` + ``fold_seq``；
- 会话时间线事件：``{kind, ts, event{...}}``，kind ∈
  {context_compacted, compaction_cooldown, fold_baseline}；
- 会话消息：``get_recent_model_context`` 重建的 OpenAI 形态
  （user/assistant/tool 行，assistant 带 tool_calls）。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.structure_doctor import (
    ISSUE_TYPES,
    SEVERITIES,
    StructureDiagnosis,
    diagnoseSession,
    diagnoseStructure,
)
from neurova.context_pool import contextFingerprint


# ── 造数辅助 ──────────────────────────────────────────────

def msg(role: str, content: str, **extra) -> dict:
    row = {"role": role, "content": content}
    row.update(extra)
    return row


def userTurn(text: str, turn: str = None) -> dict:
    row = msg("user", text)
    if turn:
        row["metadata"] = {"turn_id": turn}
    return row


def toolRow(call_id: str, content: str, name: str = "weather") -> dict:
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}


def assistantWithCalls(*call_ids: str, content: str = "") -> dict:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {"id": cid, "type": "function", "function": {"name": "weather", "arguments": "{}"}}
            for cid in call_ids
        ],
    }


def entry(
    content: str,
    source: ContextSource = ContextSource.CONVERSATION,
    *,
    turn_id: str = None,
    role: str = None,
    pairs_with: str = None,
    tool_call_id: str = None,
    covers: dict = None,
    fold_seq: int = None,
    entry_hash: str = None,
) -> ContextInput:
    metadata: dict = {}
    if role is not None:
        metadata["role"] = role
    if turn_id is not None:
        metadata["turn_id"] = turn_id
    if pairs_with is not None:
        metadata["pairs_with"] = pairs_with
    if tool_call_id is not None:
        metadata["tool_call_id"] = tool_call_id
    if covers is not None:
        metadata["covers"] = covers
    if fold_seq is not None:
        metadata["fold_seq"] = fold_seq
    return ContextInput(source=source, content=content, metadata=metadata, hash=entry_hash)


def timelineEvent(kind: str, **payload) -> dict:
    return {"kind": kind, "ts": "2026-11-22T00:00:00", "event": payload}


def typesOf(diagnosis: StructureDiagnosis):
    return [i.type for i in diagnosis.issues]


def healthyFixture():
    """一个结构完好的两轮会话（第 1 轮含工具块 + 有效摘要层 + 合规时间线）。"""
    messages = [
        userTurn("帮我查天气"),
        assistantWithCalls("c1", content="好的，我来查询。"),
        toolRow("c1", "晴 25°C"),
        msg("assistant", "北京今天晴，25°C。"),
        userTurn("谢谢"),
        msg("assistant", "不客气！"),
    ]
    user1 = entry("帮我查天气", ContextSource.CONVERSATION, turn_id="turn_1", role="user")
    asst1 = entry("好的，我来查询。", ContextSource.CONVERSATION, turn_id="turn_1", role="assistant")
    tool1 = entry(
        "晴 25°C", ContextSource.TOOL_CALL,
        turn_id="turn_1", role="tool", pairs_with="turn_1", tool_call_id="c1",
    )
    asst2 = entry("北京今天晴，25°C。", ContextSource.CONVERSATION, turn_id="turn_1", role="assistant")
    user2 = entry("谢谢", ContextSource.CONVERSATION, turn_id="turn_2", role="user")
    asst3 = entry("不客气！", ContextSource.CONVERSATION, turn_id="turn_2", role="assistant")
    covered = [tool1.hash]
    summary = entry(
        "摘要：第1轮查了北京天气", ContextSource.SUMMARY,
        covers={"turn_range": [1, 1], "hashes": covered}, fold_seq=1,
    )
    pool = [user1, asst1, tool1, asst2, user2, asst3, summary]
    timeline = [
        timelineEvent(
            "fold_baseline", lastFoldTokens=120, lastFoldMsgs=4, lastCount=6,
            foldSeq=1, summary="摘要：第1轮查了北京天气", covered=covered,
        ),
        timelineEvent(
            "context_compacted", cutoffIndex=2,
            cutoffMessageId=contextFingerprint(messages[1]),
            summaryFingerprint="f1", tokensBefore=200, tokensAfter=90,
            foldedCount=2, reason="threshold", summary="摘要", createdAt="2026-11-22T00:00:00",
        ),
    ]
    return messages, pool, timeline


# ── 1. concurrent_fork：同槽位互斥消息 ──────────────────────

class TestConcurrentFork:
    def test_sameToolCallTwoDistinctResultsInOneTurn(self):
        messages = [
            userTurn("q1"),
            assistantWithCalls("c1"),
            toolRow("c1", "结果A"),
            toolRow("c1", "结果B"),
        ]
        d = diagnoseStructure(messages=messages, pool_entries=[], timeline_events=[])
        forks = [i for i in d.issues if i.type == "concurrent_fork"]
        assert len(forks) == 1, "同一调用的两个不同结果必须判 fork"
        ev = forks[0].evidence
        assert ev["turn_id"] == "turn_1"
        assert ev["tool_call_id"] == "c1"
        assert forks[0].severity == "high"

    def test_twoUserPoolEntriesInSameTurn(self):
        pool = [
            entry("问题一", ContextSource.USER_INPUT, turn_id="turn_1", role="user"),
            entry("问题二", ContextSource.USER_INPUT, turn_id="turn_1", role="user"),
        ]
        d = diagnoseStructure(messages=[], pool_entries=pool, timeline_events=[])
        forks = [i for i in d.issues if i.type == "concurrent_fork"]
        assert len(forks) == 1, "一轮两条 user 池条目＝轮锚槽位互斥"
        assert forks[0].evidence["turn_id"] == "turn_1"

    def test_poolSameToolCallTwoDistinctResults(self):
        pool = [
            entry("r1", ContextSource.TOOL_CALL, turn_id="turn_2", role="tool",
                  tool_call_id="c1", pairs_with="turn_2"),
            entry("r2", ContextSource.TOOL_CALL, turn_id="turn_2", role="tool",
                  tool_call_id="c1", pairs_with="turn_2"),
        ]
        d = diagnoseStructure(messages=[], pool_entries=pool, timeline_events=[])
        assert typesOf(d).count("concurrent_fork") == 1

    def test_sequentialAssistantRowsInSameTurnAreNotFork(self):
        messages = [
            userTurn("q"),
            msg("assistant", "先说明一下"),
            assistantWithCalls("c1"),
            toolRow("c1", "r"),
            msg("assistant", "最终回答"),
        ]
        d = diagnoseStructure(messages=messages, pool_entries=[], timeline_events=[])
        assert "concurrent_fork" not in typesOf(d), "同轮顺序多条 assistant 行是合法形态"

    def test_identicalDuplicateResultsAreNotFork(self):
        messages = [
            userTurn("q"),
            assistantWithCalls("c1"),
            toolRow("c1", "same"),
            toolRow("c1", "same"),
        ]
        d = diagnoseStructure(messages=messages, pool_entries=[], timeline_events=[])
        assert "concurrent_fork" not in typesOf(d), "内容一致的重复行不互斥"


# ── 2. orphan_turn：工具结果无调用 / 池条目引用不存在对端 ─────

class TestOrphanTurn:
    def test_toolResultWithoutDeclaringCall(self):
        messages = [userTurn("q"), toolRow("ghost-call", "r")]
        d = diagnoseStructure(messages=messages, pool_entries=[], timeline_events=[])
        orphans = [i for i in d.issues if i.type == "orphan_turn"]
        assert len(orphans) == 1, "无声明调用的 tool 结果必须判孤儿"
        assert orphans[0].evidence["tool_call_id"] == "ghost-call"

    def test_poolPairsWithTargetAbsent(self):
        pool = [
            entry("工具结果", ContextSource.TOOL_CALL, turn_id="turn_1", role="tool",
                  pairs_with="turn_9", tool_call_id="c1"),
            entry("用户问题", ContextSource.USER_INPUT, turn_id="turn_1", role="user"),
        ]
        messages = [userTurn("用户问题")]
        d = diagnoseStructure(messages=messages, pool_entries=pool, timeline_events=[])
        orphans = [i for i in d.issues if i.type == "orphan_turn"]
        assert any(i.evidence.get("pairs_with") == "turn_9" for i in orphans), \
            "pairs_with 指向池与消息流都不存在的轮次必须判孤儿"

    def test_poolTurnIdAbsentInMessageTurns(self):
        pool = [entry("孤儿轮内容", ContextSource.CONVERSATION, turn_id="turn_7", role="assistant")]
        messages = [userTurn("q")]
        d = diagnoseStructure(messages=messages, pool_entries=pool, timeline_events=[])
        orphans = [i for i in d.issues if i.type == "orphan_turn"]
        assert any(i.evidence.get("turn_id") == "turn_7" for i in orphans), \
            "池条目引用消息流中不存在的轮次必须判孤儿"

    def test_pairedToolTurnHealthy(self):
        messages = [userTurn("q"), assistantWithCalls("c1"), toolRow("c1", "r")]
        pool = [
            entry("q", ContextSource.CONVERSATION, turn_id="turn_1", role="user"),
            entry("r", ContextSource.TOOL_CALL, turn_id="turn_1", role="tool",
                  pairs_with="turn_1", tool_call_id="c1"),
        ]
        d = diagnoseStructure(messages=messages, pool_entries=pool, timeline_events=[])
        assert "orphan_turn" not in typesOf(d)


# ── 3. stale_index：covered/covers 指纹指向不存在（或已不在）的消息 ──

class TestStaleIndex:
    MISSING = "f" * 64

    def test_summaryCoversPointsToMissingHash(self):
        pool = [entry(
            "摘要", ContextSource.SUMMARY,
            covers={"turn_range": [1, 1], "hashes": [self.MISSING]}, fold_seq=1,
        )]
        messages = [userTurn("q")]
        d = diagnoseStructure(messages=messages, pool_entries=pool, timeline_events=[])
        stale = [i for i in d.issues if i.type == "stale_index"]
        assert len(stale) == 1, "covers 指纹在池与消息指纹中都找不到必须判 stale"
        assert self.MISSING in stale[0].evidence["missing_hashes"]

    def test_summaryCoversResolvableHealthy(self):
        tool1 = entry("工具原文", ContextSource.TOOL_CALL, turn_id="turn_1", role="tool")
        pool = [
            tool1,
            entry("摘要", ContextSource.SUMMARY,
                  covers={"turn_range": [1, 1], "hashes": [tool1.hash]}, fold_seq=1),
        ]
        d = diagnoseStructure(messages=[userTurn("q")], pool_entries=pool, timeline_events=[])
        assert "stale_index" not in typesOf(d)

    def test_summaryCoversUnparsableFlagged(self):
        pool = [entry("摘要", ContextSource.SUMMARY, covers={"bad": "shape"}, fold_seq=1)]
        d = diagnoseStructure(messages=[userTurn("q")], pool_entries=pool, timeline_events=[])
        stale = [i for i in d.issues if i.type == "stale_index"]
        assert len(stale) == 1, "声明参加索引却解析不出的 covers 必须点名，不许装没病"
        assert stale[0].evidence.get("reason") == "covers_unparsable"

    def test_foldBaselineCoveredHashMissing(self):
        timeline = [timelineEvent("fold_baseline", foldSeq=1, summary="s",
                                  covered=["abc123" + "0" * 58])]
        d = diagnoseStructure(messages=[userTurn("q")], pool_entries=[], timeline_events=timeline)
        stale = [i for i in d.issues if i.type == "stale_index"]
        assert len(stale) == 1, "fold_baseline 的 covered 指纹失效必须判 stale"

    def test_compactionCutoffFingerprintMissing(self):
        timeline = [timelineEvent(
            "context_compacted", cutoffIndex=1, cutoffMessageId="0123456789abcdef",
            summaryFingerprint="", tokensBefore=100, tokensAfter=50,
            foldedCount=1, reason="threshold", summary="", createdAt="",
        )]
        d = diagnoseStructure(messages=[userTurn("q")], pool_entries=[], timeline_events=timeline)
        stale = [i for i in d.issues if i.type == "stale_index"]
        assert len(stale) == 1, "cutoffMessageId 在消息流中不存在必须判 stale"

    def test_compactionCutoffFingerprintResolvableHealthy(self):
        messages = [userTurn("q"), msg("assistant", "a")]
        timeline = [timelineEvent(
            "context_compacted", cutoffIndex=1,
            cutoffMessageId=contextFingerprint(messages[0]),
            summaryFingerprint="", tokensBefore=100, tokensAfter=50,
            foldedCount=1, reason="threshold", summary="", createdAt="",
        )]
        d = diagnoseStructure(messages=messages, pool_entries=[], timeline_events=timeline)
        assert "stale_index" not in typesOf(d)


# ── 4. segment_split：轮次断档 / 乱序 ───────────────────────

class TestSegmentSplit:
    def test_turnGapInMessageStream(self):
        messages = [userTurn("q1", turn="turn_1"), userTurn("q2", turn="turn_3")]
        d = diagnoseStructure(messages=messages, pool_entries=[], timeline_events=[])
        splits = [i for i in d.issues if i.type == "segment_split"]
        assert len(splits) == 1, "turn_1 → turn_3 缺 turn_2 必须判断档"
        assert splits[0].evidence["stream"] == "messages"

    def test_turnDisorderInMessageStream(self):
        messages = [userTurn("q1", turn="turn_2"), userTurn("q2", turn="turn_1")]
        d = diagnoseStructure(messages=messages, pool_entries=[], timeline_events=[])
        splits = [i for i in d.issues if i.type == "segment_split"]
        assert len(splits) == 1, "轮次乱序必须判 segment_split"

    def test_poolTurnGap(self):
        pool = [
            entry("a", ContextSource.CONVERSATION, turn_id="turn_1", role="user"),
            entry("c", ContextSource.CONVERSATION, turn_id="turn_3", role="user"),
        ]
        d = diagnoseStructure(messages=[], pool_entries=pool, timeline_events=[])
        splits = [i for i in d.issues if i.type == "segment_split"]
        assert len(splits) == 1, "池内轮次集合断档必须判 segment_split"
        assert splits[0].evidence["stream"] == "pool"

    def test_contiguousTurnsHealthy(self):
        messages = [userTurn("q1", turn="turn_1"), userTurn("q2", turn="turn_2")]
        pool = [
            entry("q1", ContextSource.CONVERSATION, turn_id="turn_1", role="user"),
            entry("q2", ContextSource.CONVERSATION, turn_id="turn_2", role="user"),
        ]
        d = diagnoseStructure(messages=messages, pool_entries=pool, timeline_events=[])
        assert "segment_split" not in typesOf(d)

    def test_derivedTurnsAlwaysContiguous(self):
        messages = [userTurn("q1"), userTurn("q2"), userTurn("q3")]
        d = diagnoseStructure(messages=messages, pool_entries=[], timeline_events=[])
        assert "segment_split" not in typesOf(d), "派生轮次天然连续，不得误报"


# ── 5. lost_content：应有内容的行 content 为空 / 事件缺关键载荷 ──

class TestLostContent:
    def test_userRowEmptyContent(self):
        d = diagnoseStructure(messages=[msg("user", "")], pool_entries=[], timeline_events=[])
        lost = [i for i in d.issues if i.type == "lost_content"]
        assert len(lost) == 1 and lost[0].evidence["stream"] == "messages"

    def test_toolRowEmptyContent(self):
        messages = [userTurn("q"), assistantWithCalls("c1"), toolRow("c1", "")]
        d = diagnoseStructure(messages=messages, pool_entries=[], timeline_events=[])
        assert typesOf(d).count("lost_content") == 1

    def test_assistantRowWithoutContentAndCalls(self):
        messages = [userTurn("q"), msg("assistant", "")]
        d = diagnoseStructure(messages=messages, pool_entries=[], timeline_events=[])
        assert typesOf(d).count("lost_content") == 1

    def test_assistantWithCallsEmptyContentHealthy(self):
        messages = [userTurn("q"), assistantWithCalls("c1"), toolRow("c1", "r")]
        d = diagnoseStructure(messages=messages, pool_entries=[], timeline_events=[])
        assert "lost_content" not in typesOf(d), "带 tool_calls 的 assistant 空 content 是合法形态"

    def test_poolEntryEmptyContent(self):
        pool = [entry("", ContextSource.CONVERSATION, turn_id="turn_1", role="user")]
        d = diagnoseStructure(messages=[], pool_entries=pool, timeline_events=[])
        lost = [i for i in d.issues if i.type == "lost_content"]
        assert len(lost) == 1 and lost[0].evidence["stream"] == "pool"

    def test_compactionEventMissingTokensAfter(self):
        timeline = [timelineEvent("context_compacted", cutoffIndex=1,
                                  cutoffMessageId="x" * 16, tokensBefore=10, foldedCount=1)]
        d = diagnoseStructure(messages=[], pool_entries=[], timeline_events=timeline)
        lost = [i for i in d.issues if i.type == "lost_content"]
        assert len(lost) == 1, "压缩事件缺 tokensAfter 关键字段必须判 lost_content"
        assert "tokensAfter" in lost[0].evidence["missing_fields"]

    def test_cooldownEventMissingConsecutiveFailures(self):
        timeline = [timelineEvent("compaction_cooldown", cooldownSeconds=5)]
        d = diagnoseStructure(messages=[], pool_entries=[], timeline_events=timeline)
        lost = [i for i in d.issues if i.type == "lost_content"]
        assert len(lost) == 1 and "consecutiveFailures" in lost[0].evidence["missing_fields"]

    def test_foldBaselineEmptyShell(self):
        timeline = [timelineEvent("fold_baseline", foldSeq=0, summary="", covered=[])]
        d = diagnoseStructure(messages=[], pool_entries=[], timeline_events=timeline)
        lost = [i for i in d.issues if i.type == "lost_content"]
        assert len(lost) == 1, "fold_baseline 无任何可恢复状态必须判 lost_content"

    def test_unknownTimelineKindNotJudged(self):
        timeline = [timelineEvent("some_future_kind")]
        d = diagnoseStructure(messages=[], pool_entries=[], timeline_events=timeline)
        assert d.issues == [], "不认识的 kind 不判（没检查的字段不判病）"


# ── 无病会话零误报 + 封闭集 + 确定性 ────────────────────────

class TestZeroFalsePositiveAndClosure:
    def test_healthySessionZeroIssues(self):
        messages, pool, timeline = healthyFixture()
        d = diagnoseStructure(messages=messages, pool_entries=pool, timeline_events=timeline)
        assert d.issues == [], f"完好会话必须零误报，实际：{d.to_dict()}"
        assert d.checked["messages"] == 6
        assert d.checked["pool_entries"] == 7
        assert d.checked["timeline_events"] == 2

    def test_issueTypesAndSeveritiesAreClosedSets(self):
        messages, pool, timeline = healthyFixture()
        # 注入全部五类病
        messages += [msg("user", ""), toolRow("ghost", "r"),
                     userTurn("q9", turn="turn_1"), toolRow("c1", "另一结果")]
        pool += [entry("", ContextSource.CONVERSATION, turn_id="turn_1", role="user")]
        timeline += [timelineEvent("compaction_cooldown", cooldownSeconds=5)]
        d = diagnoseStructure(messages=messages, pool_entries=pool, timeline_events=timeline)
        assert d.issues, "注入五类病后必须出 issue"
        for issue in d.issues:
            assert issue.type in ISSUE_TYPES
            assert issue.severity in SEVERITIES
            assert isinstance(issue.evidence, dict) and issue.evidence
            assert isinstance(issue.suggestion, str) and issue.suggestion

    def test_allFiveTypesDetectable(self):
        messages, pool, timeline = healthyFixture()
        messages += [msg("user", ""), toolRow("ghost", "r"),
                     userTurn("q9", turn="turn_1"), toolRow("c1", "另一结果")]
        pool += [entry("摘要", ContextSource.SUMMARY,
                       covers={"turn_range": [1, 1], "hashes": ["e" * 64]}, fold_seq=9)]
        timeline += [timelineEvent("compaction_cooldown", cooldownSeconds=5)]
        d = diagnoseStructure(messages=messages, pool_entries=pool, timeline_events=timeline)
        found = set(typesOf(d))
        assert found == set(ISSUE_TYPES), f"五类病必须全部可检出，实际：{found}"


class TestDeterminism:
    def test_sameInputTwiceIdentical(self):
        messages, pool, timeline = healthyFixture()
        messages += [msg("user", ""), toolRow("ghost", "r")]
        kwargs = dict(messages=messages, pool_entries=pool, timeline_events=timeline)
        d1 = diagnoseStructure(**kwargs).to_dict()
        d2 = diagnoseStructure(**kwargs).to_dict()
        assert d1 == d2

    def test_shuffledPoolEntriesSameResult(self):
        messages, pool, timeline = healthyFixture()
        pool += [entry("", ContextSource.CONVERSATION, turn_id="turn_2", role="assistant")]
        straight = diagnoseStructure(messages=messages, pool_entries=pool,
                                     timeline_events=timeline).to_dict()
        shuffled = list(reversed(pool))
        flipped = diagnoseStructure(messages=messages, pool_entries=shuffled,
                                    timeline_events=timeline).to_dict()
        assert straight["issues"] == flipped["issues"], "池条目输入顺序不得影响诊断结论"


# ── diagnoseSession 薄适配（真实存储读取） ───────────────────

@pytest.fixture
def isolatedSessionManager(tmp_path, monkeypatch):
    from neurova import session_manager as smModule
    from neurova.session_manager import SessionManager

    sessionsDir = tmp_path / "sessions"
    original = SessionManager._instance
    SessionManager._instance = None
    sm = SessionManager(sessions_dir=str(sessionsDir))
    monkeypatch.setattr(smModule, "get_session_manager", lambda: sm)
    yield sm
    SessionManager._instance = original


class TestDiagnoseSessionAdapter:
    def test_readsRealStorageThreeWays(self, isolatedSessionManager):
        from neurova.context_pool import ContextPool
        from neurova.context_pool_registry import get_registry

        sm = isolatedSessionManager
        sm.add_message("a1", "s1", "你好", "你好！有什么可以帮你？")
        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1")
        pool.add_context(entry("你好", ContextSource.CONVERSATION, turn_id="turn_1", role="user"))
        get_registry().adopt(pool)

        d = diagnoseSession("s1", agent_id="a1", session_manager=sm)
        assert d.checked["messages"] == 2
        assert d.checked["pool_entries"] >= 1
        assert d.checked["session_found"] == 1
        assert d.issues == [], f"健康会话必须零误报：{d.to_dict()}"

    def test_resolvesAgentFromSessionId(self, isolatedSessionManager):
        sm = isolatedSessionManager
        sm.add_message("a1", "s1", "问题", "回答")
        d = diagnoseSession("s1", session_manager=sm)
        assert d.agent_id == "a1", "缺省 agent_id 时应按会话文件反查"
        assert d.issues == []

    def test_unknownSessionHonestNotFound(self, isolatedSessionManager):
        d = diagnoseSession("no-such-session", agent_id="a1",
                            session_manager=isolatedSessionManager)
        assert d.checked.get("session_found", 0) == 0
        assert d.issues == [], "查无此会话＝没检查出依据，不造病"

    def test_timelineDiseaseSurfacesThroughAdapter(self, isolatedSessionManager):
        sm = isolatedSessionManager
        sm.add_message("a1", "s2", "问题", "回答")
        sm.append_timeline_event("a1", "s2", timelineEvent("context_compacted", cutoffIndex=1))
        d = diagnoseSession("s2", agent_id="a1", session_manager=sm)
        assert "lost_content" in typesOf(d), "时间线事件缺关键载荷须经适配面浮出"


# ── 只读诊断端点 ──────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    from neurova.api.endpoints import context as contextApi
    from neurova.context_pool_registry import get_registry
    from neurova.session_manager import SessionManager

    get_registry().reset()
    sessionsDir = tmp_path / "sessions"
    original = SessionManager._instance
    SessionManager._instance = None
    sm = SessionManager(sessions_dir=str(sessionsDir))
    monkeypatch.setattr("neurova.session_manager.get_session_manager", lambda: sm)

    # 落两个真实会话：s1 健康；s-bad 注入 lost_content 病（空内容行 + 缺字段事件）
    sm.add_message("a1", "s1", "你好", "你好！有什么可以帮你？")
    sm.add_message("a1", "s-bad", "", "")
    sm.append_timeline_event(
        "a1", "s-bad", timelineEvent("context_compacted", cutoffIndex=1))

    application = FastAPI()
    application.include_router(contextApi.router, prefix="/v1/context")
    application.dependency_overrides[contextApi.get_current_user] = lambda: {
        "user_id": "u1", "username": "u", "role": "admin", "neuser_id": "ne1",
    }
    yield TestClient(application)
    application.dependency_overrides.clear()
    SessionManager._instance = original
    get_registry().reset()


class TestStructureEndpoint:
    def test_unknownSessionReturns404(self, client):
        resp = client.get("/v1/context/diagnose/structure", params={"session_id": "ghost"})
        assert resp.status_code == 404, "查无此会话必须 404，不返回空报告冒充健康"

    def test_healthySessionZeroIssues(self, client):
        resp = client.get("/v1/context/diagnose/structure",
                          params={"session_id": "s1", "agent_id": "a1"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["healthy"] is True
        assert data["issue_count"] == 0
        assert data["checked"]["messages"] >= 2
        assert set(data["counts_by_type"].keys()) == set(ISSUE_TYPES)

    def test_diseasedSessionReportsIssues(self, client):
        resp = client.get("/v1/context/diagnose/structure",
                          params={"session_id": "s-bad", "agent_id": "a1"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["healthy"] is False
        assert any(i["type"] == "lost_content" for i in data["issues"])

    def test_detailLimitCapsIssues(self, client):
        resp = client.get("/v1/context/diagnose/structure",
                          params={"session_id": "s-bad", "agent_id": "a1", "detail_limit": 1})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["issues_total"] >= 2
        assert data["issues_returned"] == 1
        assert len(data["issues"]) == 1
