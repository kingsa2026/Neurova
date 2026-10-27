# -*- coding: utf-8 -*-
"""§6-46：`/v1/chat` 与 `/v1/chat/stream` 也要问闸、也要落 run 台账；台账实现只留一处。

拍板口径是"全量接"。这两条公开 API 与渠道面共用同一份模型额度，今天却既不问闸也不记账。
`/v1/chat` 那条挂起时**不许**回 `{"code":0,"message":"success"}` 带空 reply——那正是本仓
反复在修的"假成功"形态；如实回 `parked` + run_id。

最后一组是教义第 7 条的收口判据：run 台账的执行体（`AgentRunLedger`）与"问闸→挂起→
落库→构造回包"这段必须只有**一处实现**被四个入口共用。四处各抄一遍，下一轮改 park
语义时就会只改到一处，剩下的静默留着旧形态。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest
from fastapi.testclient import TestClient

from tests import ast_scan

from neurova.api.app import create_app
from neurova.collaboration.glance_yield_rules import GlanceYieldChecker
from neurova.core import agent_run_store as ars
from tests.ast_scan import parseSource

AGENT_ID = "api-agent"
OWNER = "api-owner"

_REPO = Path(__file__).resolve().parents[3]


class _FakeAgent:
    def __init__(self):
        self.calls = []
        self.config = SimpleNamespace(owner_user_id=OWNER, attachment_dir="")

    async def chat(self, user_input=None, stream=False, session_id=None, metadata=None, model=None, **kw):
        self.calls.append({"user_input": user_input, "session_id": session_id})
        emit = (metadata or {}).get("event_emitter")
        if emit:
            emit("content", "hello-v1")
        return {"text": "hello-v1", "tool_messages": [], "reasoning": ""}


_MISSING = object()


@pytest.fixture()
def runStore(tmp_path, monkeypatch):
    db = tmp_path / "v1.db"
    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(db))
    monkeypatch.setenv("NEUROVA_RUN_GATE", "on")
    monkeypatch.setenv("NEUROVA_YIELD_MAX_ATTEMPTS", "0")
    monkeypatch.setenv("NEUROVA_YIELD_WAIT_CAP_SECONDS", "0.05")
    ars.reset_agent_run_store()
    store = ars.AgentRunStore(db)
    monkeypatch.setattr(ars, "_store", store)
    yield store
    ars.reset_agent_run_store()


@pytest.fixture()
def yieldChecker(monkeypatch):
    monkeypatch.setattr(
        "neurova.collaboration.glance_yield_rules._glance_checker_instance",
        GlanceYieldChecker(),
        raising=False,
    )
    from neurova.collaboration import glance_yield_rules as gyr

    return gyr._glance_checker_instance


@pytest.fixture()
def makeClient(request, monkeypatch):
    """真 app + 身份覆盖；`create_app()` 返回进程内缓存的同一个 app，必须 set-or-pop。

    两个键都要盖：`chat.py` 用严格版 `api.auth.get_current_user`，而 `console.py` 经
    `api/deps.py` 拿到的是**再导出的可查询参数版**（同名不同体，§6-28 的既定命名），
    只盖一个键时另一条路会静默走真鉴权拿 401。
    """
    import neurova.api.auth as api_auth
    from neurova.api.deps import get_current_user as depsUser
    from neurova.api.endpoints import chat as chat_mod

    agent = _FakeAgent()
    monkeypatch.setattr(chat_mod, "_get_agent", lambda agent_id="": agent)
    app = create_app(enable_memory=False, enable_channels=False)
    identity = {"user_id": OWNER, "username": OWNER, "role": "user"}

    keys = [api_auth.get_current_user, depsUser]
    previous = {key: app.dependency_overrides.get(key, _MISSING) for key in keys}
    for key in keys:
        app.dependency_overrides[key] = lambda: dict(identity)

    def _restore() -> None:
        for key in keys:
            if previous[key] is _MISSING:
                app.dependency_overrides.pop(key, None)
            else:
                app.dependency_overrides[key] = previous[key]

    request.addfinalizer(_restore)
    return TestClient(app), agent


def _dataEvents(text: str):
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def testV1ChatTurnIsRecordedInRunLedger(makeClient, runStore, yieldChecker):
    client, agent = makeClient
    resp = client.post(
        "/api/v1/chat",
        json={"message": "正常一轮", "agent_id": AGENT_ID, "session_id": "v1-regular"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["reply"] == "hello-v1"
    rows = runStore.list_runs("v1-regular")
    assert len(rows) == 1, "/v1/chat 回合没进 run 台账"
    assert rows[0]["status"] == "completed"
    assert rows[0]["user_id"] == OWNER


def testV1ChatOverBudgetParksHonestly(makeClient, runStore, yieldChecker):
    """挂起不许伪装成 success：回 parked + run_id，且这一轮真没跑。"""
    client, agent = makeClient
    yieldChecker.trigger_rate_limit(AGENT_ID)

    resp = client.post(
        "/api/v1/chat",
        json={"message": "该被挂起", "agent_id": AGENT_ID, "session_id": "v1-park"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] != "success", f"挂起却报成功：{body}"
    assert body["data"].get("status") == ars.PARKED_STATUS
    runId = body["data"].get("run_id") or ""
    assert runId, "没回 run_id 就没有续跑凭据"
    assert agent.calls == [], "闸没接上：并发已满照样打到 LLM"

    rows = runStore.list_runs("v1-park")
    assert len(rows) == 1 and rows[0]["status"] == ars.PARKED_STATUS
    assert rows[0]["park_reason"]
    assert "该被挂起" in (rows[0]["resume_payload"] or "")


def testV1ChatStreamParksAndClosesStream(makeClient, runStore, yieldChecker):
    client, agent = makeClient
    yieldChecker.trigger_rate_limit(AGENT_ID)

    resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "流式该挂起", "agent_id": AGENT_ID, "session_id": "v1-stream"},
    )

    assert resp.status_code == 200
    events = _dataEvents(resp.text)
    kinds = [e.get("type") for e in events if e.get("type")]
    assert "parked" in kinds, f"流式面没有 parked 事件：{kinds}"
    assert kinds[-1] == "done", "挂起后流必须收尾，不能让客户端空等"
    assert "message" not in kinds, "挂起后不该有任何模型内容"
    assert agent.calls == []

    rows = runStore.list_runs("v1-stream")
    assert len(rows) == 1 and rows[0]["status"] == ars.PARKED_STATUS
    parked = next(e for e in events if e.get("type") == "parked")
    assert parked.get("run_id") == rows[0]["run_id"]


def testParkedV1ChatRunIsResumableByOwner(makeClient, runStore, yieldChecker):
    """挂起行落库后，属主从网页那条唯一续跑口能取回它（跨面闭环，不是死数据）。"""
    client, _agent = makeClient
    yieldChecker.trigger_rate_limit(AGENT_ID)
    resp = client.post(
        "/api/v1/chat",
        json={"message": "待续跑", "agent_id": AGENT_ID, "session_id": "v1-resume"},
    )
    runId = resp.json()["data"]["run_id"]
    yieldChecker._rate_limited_agents.pop(AGENT_ID, None)

    again = client.post(f"/api/v1/console/chat/resume?run_id={runId}")

    assert again.status_code == 200, again.text
    rows = runStore.list_runs("v1-resume")
    assert len(rows) == 1 and rows[0]["status"] in ("completed", "failed")
    assert rows[0]["resume_payload"] in (None, "")


class TestLedgerImplementationIsSingleSource:
    """台账执行体与闸口接入段只许一处实现，四入口共用（教义第 6/7 条）。"""

    def _topLevelNames(self, relPath: str) -> Dict[str, Any]:
        src = (_REPO / relPath).read_text(encoding="utf-8")
        tree = parseSource(src)
        return {n.name: n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}

    def test_consoleNoLongerOwnsTheLedger(self):
        names = self._topLevelNames("neurova/api/endpoints/console.py")
        assert "_AgentRunLedger" not in names, (
            "台账类还住在 console.py 里——渠道与 /v1/chat 只能另抄一份，正是本批判的形态"
        )

    def testEveryTurnEntryImportsTheOneLedger(self):
        shared = "neurova/core/agent_run_ledger.py"
        assert (_REPO / shared).exists(), f"台账单源模块不存在：{shared}"
        names = self._topLevelNames(shared)
        assert "AgentRunLedger" in names and "requestTurnAdmission" in names

        for relPath in (
            "neurova/api/endpoints/console.py",
            "neurova/api/endpoints/chat.py",
            "neurova/channels/channel_router.py",
        ):
            src = (_REPO / relPath).read_text(encoding="utf-8")
            tree = parseSource(src)
            imported = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module == "neurova.core.agent_run_ledger"
                for alias in node.names
            }
            assert {"AgentRunLedger", "requestTurnAdmission"} <= imported, (
                f"{relPath} 没有改用那份唯一实现"
            )

    @staticmethod
    def _callSitesNamed(source: str, name: str):
        """源码里调用名为 `name` 的落点行号（`f(...)` 与 `x.f(...)` 同收）。

        与 `ast_scan.callSites` 同一份 AST 判据，只多收**裸名**形态——本判据要钉的
        正是单源模块里那处裸名调用，而 `callSites` 只认属性调用，用它会把真命中
        读成零命中，判据退化成恒真的空断言（教义第 2 条不允许）。
        判定口径（哪些算调用、哪些不算）仍只有 ast.Call 一处，不新造平行体系。
        """
        return [
            node.lineno
            for node in ast.walk(parseSource(source))
            if isinstance(node, ast.Call)
            and name in (getattr(node.func, "id", None), getattr(node.func, "attr", None))
        ]

    def testAdmissionHelperIsNotReimplementedAnywhere(self):
        """不许有第二份"问闸→挂起→落库"：全仓 `requestYieldGate` 的调用点只许在单源模块里。

        取数走 `tests/ast_scan` 的共享解析预算（`sourceRefsUnder` + 文本预筛），
        不私有 `rglob + glob`：那条写法把判据成本绑在代码总量上——本用例原先单次
        全仓扫一遍 `neurova/`，与受保护子集其余文件共享机器时必偶发红
        （`tests/unit/test_ci_ast_scan_budget_guard.py` 判红的就是这处）。
        预筛词就是符号本身，是判据的充分条件：连 `requestYieldGate` 字样都没有的
        文件不可能有它的调用点，解析量从**代码总量**降到**命中面**。
        """
        hits = []
        for ref in ast_scan.sourceRefsUnder(
            ast_scan.PRODUCTION_ROOT, ".py", ast_scan.textHints("requestYieldGate")
        ):
            for lineno in self._callSitesNamed(ref.code, "requestYieldGate"):
                hits.append(f"{ast_scan.relativeToRepo(ref.path)}:{lineno}")
        # 判据是**文件级单源**：闸口调用点一处不多、一处不少地落在台账模块里。
        # 不钉具体行号——行号会随该模块里任何无关增删漂移（`e10ffc0d` 在文件尾
        # 追加蜂群记账后，调用点从 241 挪到 242），把「单源」读成「某一行」是
        # 拿判据打正当改动；但真正要防的形态仍然咬得住：搬到别的模块、或在
        # 台账模块里长出第二处，都会让下面的集合判断转红。
        assert hits, "全仓找不到 `requestYieldGate` 的调用点——闸口没被任何入口用上"
        offenders = [h for h in hits if not h.startswith("neurova/core/agent_run_ledger.py:")]
        assert not offenders, (
            f"闸口调用点搬出了单源模块（或长出第二处）：{hits}"
        )
        assert len(hits) == 1, (
            f"闸口调用点长出第二处：{hits}"
        )
