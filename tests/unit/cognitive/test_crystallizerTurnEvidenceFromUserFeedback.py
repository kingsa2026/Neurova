# -*- coding: utf-8 -*-
"""用户回执补进结晶器证据面（§6-209，用户裁定甲）。

被接的缺口是实算出来的：`POST /api/v1/console/chat/feedback`（`console.py:1847`）已带真
like/dislike 回执，并已向**记忆温度（±10/-15）**、**反思效力裁决**、**context 台账
observe_purpose** 三面扇出——唯独不喂结晶器。于是 `pattern_crystallizer.py:264` 的证据闸
永远看到 `evidenced=0`（盘上两份 `crystallizer_state.json` 实测 `observations=1 /
evidenced=0`），模式永不结晶。

裁定甲的形状在本文件里钉死：**只有含工具调用的轮**能被用户回执补票；纯对话轮的伪工具
`chat` 条目永不因点赞取得证据——那条教训（2026-09-05 寒暄进上下文）不能被"点赞"换个入口绕过。

三条机制约束也各自有格：补票**不新增一次观察**（否则观察计数被虚增、门槛形同虚设）、
**不覆盖已有客观票据**（工单 002/010 的优先级）、**对不上模式键时不新建键**
（静默双计是最难发现的那类错）。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

# 新符号**不在模块顶层 import**：本档会被 A/B 铺进基线树（HEAD 生产 + 新判据、无修复），
# 顶层 import 会让基线侧整场 collection 以 `Interrupted: 1 error` 中断——两侧就不可比了。
# 收进函数/夹具后，基线侧只有本批那几格红，其余照跑。
NEUROVA = Path(__file__).resolve().parents[3] / "neurova"


def _symbols():
    from neurova.cognitive_layers.memory_layer.pattern_crystallizer import (
        CHAT_PSEUDO_TOOL, PatternCrystallizer)
    return CHAT_PSEUDO_TOOL, PatternCrystallizer
QUESTION = "帮我查一下北京明天的天气并给出行衣建议"


class _FakeEngine:
    def __init__(self):
        self.stored = []

    def store(self, node):
        self.stored.append(node)
        return node.id

    def retrieve(self, query, limit=5, filters=None):
        return []


@pytest.fixture()
def crystallizer(tmp_path):
    _, PatternCrystallizer = _symbols()
    return PatternCrystallizer(
        engine=_FakeEngine(),
        evolution_orchestrator=None,
        state_path=str(tmp_path / "crystallizer_state.json"),
    )


def _entries(c, text=QUESTION):
    return c._buffer.get(c._extract_pattern_key(text), [])


class TestAttachTurnOutcome:
    def test_toolRoundGetsOneTicketAndNoNewObservation(self, crystallizer):
        crystallizer.observe(tool_name="weather_api", context=QUESTION, success=None)
        before = len(_entries(crystallizer))

        added = crystallizer.attachTurnOutcome(QUESTION, True)

        assert added == 1, "该补的那条没补上"
        assert len(_entries(crystallizer)) == before, "补票新增了一次观察＝门槛被虚增绕过"
        assert _entries(crystallizer)[0]["success"] is True

    def test_pureChatRoundNeverGainsEvidenceFromALike(self, crystallizer):
        """裁定甲的核心：寒暄轮不因点赞取得证据（回声污染不能再换个入口进来）。"""
        CHAT_PSEUDO_TOOL, _ = _symbols()
        crystallizer.observe(tool_name=CHAT_PSEUDO_TOOL, context=QUESTION, success=None)

        assert crystallizer.attachTurnOutcome(QUESTION, True) == 0
        assert _entries(crystallizer)[0]["success"] is None

    def test_objectiveTicketIsNotOverriddenEitherWay(self, crystallizer):
        """工单 002/010 的票据优先：主观回执不能把 False 翻成 True，反之亦然。"""
        crystallizer.observe(tool_name="weather_api", context=QUESTION, success=False)
        assert crystallizer.attachTurnOutcome(QUESTION, True) == 0
        assert _entries(crystallizer)[0]["success"] is False

        crystallizer.observe(tool_name="search", context=QUESTION + "（另一键）", success=True)
        assert crystallizer.attachTurnOutcome(QUESTION + "（另一键）", False) == 0
        assert _entries(crystallizer, QUESTION + "（另一键）")[0]["success"] is True

    def test_unknownPatternKeyAttachesNothingAndCreatesNoKey(self, crystallizer):
        """对不上键必须**不新建**：新建键就是静默双计，且比普通失败更难发现。"""
        crystallizer.observe(tool_name="weather_api", context=QUESTION, success=None)
        keysBefore = set(crystallizer._buffer)

        assert crystallizer.attachTurnOutcome("完全不同的一句话", True) == 0
        assert set(crystallizer._buffer) == keysBefore, "补票凭空造了一个新模式键"

    def test_mixedRoundAttachesOnlyToolEntries(self, crystallizer):
        CHAT_PSEUDO_TOOL, _ = _symbols()
        crystallizer.observe(tool_name=CHAT_PSEUDO_TOOL, context=QUESTION, success=None)
        crystallizer.observe(tool_name="weather_api", context=QUESTION, success=None)

        assert crystallizer.attachTurnOutcome(QUESTION, True) == 1
        entries = {e["tool"]: e["success"] for e in _entries(crystallizer)}
        assert entries[CHAT_PSEUDO_TOOL] is None, "伪工具 chat 也被补票＝越过裁定甲"
        assert entries["weather_api"] is True

    def test_singleAttachedTicketDoesNotBreachObservationThreshold(self, crystallizer):
        """补票不等于结晶：`min_observations` 那道门槛不能被一次点赞绕过。"""
        engine = crystallizer.engine
        crystallizer.observe(tool_name="weather_api", context=QUESTION, success=None)
        crystallizer.attachTurnOutcome(QUESTION, True)

        assert crystallizer.min_observations > 1
        assert engine.stored == [], "一次观察 + 一张票就直接结晶了"

    def test_stateFileSeesTheTicketAfterSave(self, crystallizer, tmp_path):
        """补票要落盘：状态文件里 `evidenced` 从 0 变 1，重启后不退回无票。"""
        crystallizer.observe(tool_name="weather_api", context=QUESTION, success=None)
        crystallizer.attachTurnOutcome(QUESTION, True)
        state = json.loads((tmp_path / "crystallizer_state.json").read_text(encoding="utf-8"))
        agg = [v for k, v in state.items() if k != "pending"]
        assert agg and sum(int(v.get("evidenced", 0)) for v in agg) == 1, (
            "票补进了内存却没落盘：%s" % state)


def _fakeRequest():
    from fastapi import Request

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request({"type": "http", "method": "POST",
                    "path": "/api/v1/console/chat/feedback", "headers": [],
                    "query_string": b""}, receive)


class TestEndpointFanOutRoutesTheVerdictToTheCrystallizer:
    """HTTP 面那一跳：`POST /console/chat/feedback` 的第四面扇出真的接上了。

    形状取自同族既有档 `tests/unit/api/test_feedback_purpose_signal.py`（在端点接缝上装桩，
    不新建第二套假 app）。这里要断的是"回执到了结晶器，并且只补工具条目"。
    """

    def _wire(self, monkeypatch, crystallizer, repoRound):
        import types

        import neurova.api.endpoints.console as consoleModule

        agent = types.SimpleNamespace(crystallizer=crystallizer, memory_agent=None,
                                      intrinsic_motivation=None)

        class _Repo:
            def find_session(self, session_id):
                return {"agent_id": "a1", "session_id": session_id, "user_id": "u1"}

            def update_message_metadata(self, **kw):
                return True

            def get_round(self, **kw):
                return repoRound

        monkeypatch.setattr(consoleModule, "_get_user_id", lambda *a: "u1")
        monkeypatch.setattr(consoleModule, "get_session_repository", lambda: _Repo())
        monkeypatch.setattr(consoleModule, "get_agent_instance", lambda agent_id="default": agent)
        return consoleModule

    def _post(self, consoleModule, feedback):
        import asyncio

        body = consoleModule.FeedbackRequest(session_id="s1", timestamp="2026-10-14T10:00:00",
                                             feedback=feedback)
        return asyncio.run(consoleModule.post_chat_feedback(
            body, _fakeRequest(), {"id": "u1", "username": "u1"}))

    def test_likeReachesCrystallizerAndSkipsTheChatEntry(self, tmp_path, monkeypatch):
        CHAT_PSEUDO_TOOL, PatternCrystallizer = _symbols()
        cry = PatternCrystallizer(engine=_FakeEngine(), evolution_orchestrator=None,
                                  state_path=str(tmp_path / "st.json"))
        cry.observe(tool_name="web_search", context=QUESTION, success=None)
        cry.observe(tool_name=CHAT_PSEUDO_TOOL, context=QUESTION, success=None)
        consoleModule = self._wire(monkeypatch, cry,
                                   {"user": {"content": QUESTION}, "assistant": {"content": "A"}})

        resp = self._post(consoleModule, "like")

        assert resp["code"] == 0
        entries = {e["tool"]: e["success"] for e in _entries(cry)}
        assert entries["web_search"] is True, "端点的第四面扇出没接上"
        assert entries[CHAT_PSEUDO_TOOL] is None, "寒暄条目经 HTTP 面被补票＝越过裁定甲"

    def test_cancellingFeedbackChangesNothing(self, tmp_path, monkeypatch):
        _, PatternCrystallizer = _symbols()
        """取消点赞（feedback=None）不撤也不加票——撤票会把三态写成两态，
        "取消"既不等于成功也不等于失败（与温度链路同形：取消不做操作）。"""
        cry = PatternCrystallizer(engine=_FakeEngine(), evolution_orchestrator=None,
                                  state_path=str(tmp_path / "st.json"))
        cry.observe(tool_name="web_search", context=QUESTION, success=None)
        consoleModule = self._wire(monkeypatch, cry,
                                   {"user": {"content": QUESTION}, "assistant": {"content": "A"}})
        self._post(consoleModule, "like")
        before = [dict(e) for e in _entries(cry)]

        self._post(consoleModule, None)

        assert [dict(e) for e in _entries(cry)] == before, "取消反馈撤了票（三态被写成两态）"


class TestChatPseudoToolNameIsSingleSourced:
    """伪工具名是"这轮没工具"的唯一记号，两处各写字面量就会各漂。"""

    def test_closedLoopUsesTheConstantNotALiteral(self):
        path = NEUROVA / "evolution" / "closed_loop.py"
        src = path.read_text(encoding="utf-8")
        assert "CHAT_PSEUDO_TOOL" in src, "closed_loop 不再引用单源常量，纯对话轮的记号开始各写各的"
        assert '["chat"]' not in src, "closed_loop 里仍有裸的 [\"chat\"] 字面量"

    def test_theConstantIsDefinedExactlyOnce(self):
        homes = []
        for py in sorted(NEUROVA.rglob("*.py")):
            if "__pycache__" in str(py):
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id == "CHAT_PSEUDO_TOOL":
                            homes.append(py.relative_to(NEUROVA).as_posix())
        assert homes == ["cognitive_layers/memory_layer/pattern_crystallizer.py"], (
            "伪工具名被定义了 %d 处：%s" % (len(homes), homes))
