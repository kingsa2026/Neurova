# -*- coding: utf-8 -*-
"""Studio 长任务台账收口（2026-10-08 长任务闭环审计 E 批）。

`/studio` 的长任务与对话的 `agent_runs` 是两张表、两套账（这本身合理：一边是对话 run，
一边是生成任务）。不合理的是 **studio 这一套没有启动收敛**，而且同一次请求会落两行：

1. `runs.status` 建表默认 `'running'`（store.py:88），终态只有 `done`/`failed` 两个写入点
   （studio_api.py:127/132）。执行体是 `asyncio.create_task` 塞进**进程内** `_tasks`
   （studio_api.py:26/134），进程一没，行就永久停在 running——`agent_runs` 有
   `reconcile_at_startup`（store.py:124）兜这类遗留，runs 表**没有对偶**。
   前端 `useStudioRun.ts:15-29` 轮 10 分钟后返回 null，用户看到"超时"，库里那条还"在跑"。
2. 外层 `_spawn_run` 建一行，服务内部（`split_script`/`extract_assets`/
   `storyboard_breakdown`）又各建一行并各自写终态；前端只 poll 外层那条。一次请求两行
   同 kind，`GET /projects/{pid}` 的 runs 投影里并排出现，读侧无法知道哪条是这次请求。

根因都在**生命周期的归属没收口到一处**：谁建的行、谁写终态、谁来证明它活着，三件事分散在
两层。修法就是把「一次请求 = 一行 = 一个生命周期拥有者」做实，并给 runs 表补上对偶的
启动收敛。

判据（改前逐条实测不成立）：
1. 重开库（模拟进程重启）后，遗留 running 必须被收敛成 failed 并写明成因；
2. 走真端点发起一次剧本拆解，`runs` 表里这次请求只有一行，且它自己就是终态；
3. 服务单独调用（不经端点）时仍能自建台账行——不能把独立复用的能力修没了。
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.aigc_studio import services as svc
from neurova.aigc_studio.store import StudioStore
from neurova.api.deps import get_current_user
from neurova.api.endpoints import studio_api

pytestmark = pytest.mark.timeout(60)

USER = {"user_id": "u1", "username": "u1", "role": "user", "neuser_id": "u1"}


@pytest.fixture()
def store(tmp_path):
    s = StudioStore(db_path=str(tmp_path / "studio.db"))
    yield s
    s.close()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "studio.db")
    s = StudioStore(db_path=db)
    monkeypatch.setattr(studio_api, "get_store", lambda: s)
    app = FastAPI()
    app.include_router(studio_api.router, prefix="/api/v1/studio")
    app.dependency_overrides[get_current_user] = lambda: USER
    c = TestClient(app)
    c.db_path = db  # type: ignore[attr-defined]
    c.store = s  # type: ignore[attr-defined]
    return c


def _waitTerminal(store, pid, runId, seconds=8.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        for row in store.list_runs(pid):
            if row["id"] == runId and row["status"] != "running":
                return row
        time.sleep(0.05)
    return None


class TestStartupConvergence:
    def test_reopenConvergesLeftoverRunningRows(self, tmp_path):
        """进程重启：仍标着 running 的行只可能来自已死进程，必须写明成因收掉。

        与 `agent_run_store.reconcile_at_startup` 同一形态，不是第二份口径——两张表
        本来就各管一类任务，缺的是 runs 表这一侧的对偶。
        """
        db = str(tmp_path / "reopen.db")
        first = StudioStore(db_path=db)
        run = first.add_run({"project_id": "p1", "kind": "videos"})
        first.close()

        second = StudioStore(db_path=db)
        row = next(r for r in second.list_runs("p1") if r["id"] == run["id"])
        assert row["status"] == "failed", (
            f"遗留 running 未被启动收敛：{row['status']}——"
            "前端 poll 到超时，库里这条永远『在跑』"
        )
        assert "process_died" in str(row["error"]), (
            f"收敛了但没写成因，读侧无从区分真失败与进程没落："
            f"{row['error']!r}"
        )
        second.close()

    def test_freshStoreDoesNotFabricateRows(self, tmp_path):
        """新库无遗留行时不得凭空造出 failed（收敛只能改既存行）。"""
        s = StudioStore(db_path=str(tmp_path / "fresh.db"))
        assert s.list_runs("") == []
        s.close()


class TestOneRowPerRequest:
    def test_scriptEndpointWritesExactlyOneRunRow(self, client, monkeypatch):
        """经真端点发起的一次拆解：runs 表里这次请求只有一行，且它自己到终态。"""

        async def fakeLlm(prompt, system):
            return json.dumps(
                [{"number": 1, "title": "第一集", "content": "正文", "synopsis": "梗概"}],
                ensure_ascii=False,
            )

        monkeypatch.setattr(svc, "call_llm", fakeLlm)

        pid = client.post("/api/v1/studio/projects",
                          json={"title": "T", "style": "水墨"}).json()["data"]["project"]["id"]
        accepted = client.post(f"/api/v1/studio/projects/{pid}/script",
                               json={"content": "从前有座山。" * 3}).json()["data"]
        runId = accepted["run_id"]

        terminal = _waitTerminal(client.store, pid, runId)
        assert terminal is not None, f"外层 run 从未到终态：{client.store.list_runs(pid)}"

        rows = [r for r in client.store.list_runs(pid) if r["kind"] == "script"]
        assert len(rows) == 1, (
            f"一次请求落了 {len(rows)} 行 kind=script（{[r['id'] for r in rows]}）："
            "外层行由 _spawn_run 建、内层行由服务自建，前端只 poll 外层那条，"
            "读侧无法判断哪条代表这次请求"
        )
        assert rows[0]["id"] == runId, "终态写在另一行上，poll 的那条永远在 running"
        assert rows[0]["status"] in ("done", "done_with_fallback"), rows[0]["status"]
        detail = json.loads(rows[0]["detail_json"] or "{}")
        assert detail, "复用外层行后 detail_json 应带上服务侧的产出读数"

    def test_fallbackReasonSurvivesTheWrapper(self, client, monkeypatch):
        """收口成一行后，服务写的终态与成因不得被 wrapper 抹掉。

        改前 wrapper 无条件 `{"status": "done", "detail_json": 返回值}`：
        `extract_assets` 标好的 `done_with_fallback` 被压成 `done`，detail 里的
        回退成因被返回值覆盖——一行只剩状态字，「为什么算带病完成」这件事又回到只有日志里。
        """
        from neurova.aigc_studio import services as svc

        async def raisingLlm(prompt, system):
            raise RuntimeError("上游 429 打不通")

        monkeypatch.setattr(svc, "call_llm", raisingLlm)

        pid = client.post("/api/v1/studio/projects",
                          json={"title": "T"}, ).json()["data"]["project"]["id"]
        eid = client.store.add_episode(pid, {"number": 1, "title": "第一集",
                                             "content": "山上有座庙"})["id"]
        accepted = client.post(f"/api/v1/studio/episodes/{eid}/extract", json={}).json()["data"]

        terminal = _waitTerminal(client.store, pid, accepted["run_id"])
        assert terminal is not None, "抽取任务从未到终态"
        assert terminal["status"] == "done_with_fallback", (
            f"带病完成被 wrapper 改写成干净完成：{terminal['status']}"
        )
        detail = json.loads(terminal["detail_json"] or "{}")
        assert "429" in str(detail.get("error", "")), (
            f"回退成因不在账上：{detail}"
        )


    def test_serviceStandaloneStillOwnsItsRow(self, store):
        """不经端点单独调用服务时，它仍自建台账行（不能把独立复用能力修没）。"""
        import asyncio

        async def fakeLlm(prompt, system):
            return json.dumps([{"number": 1, "title": "集", "content": "正文"}],
                              ensure_ascii=False)

        project = store.create_project("u1", title="P")
        asyncio.run(svc.split_script(store, project["id"], "正文", llm=fakeLlm))
        rows = [r for r in store.list_runs(project["id"]) if r["kind"] == "script"]
        assert len(rows) == 1 and rows[0]["status"] in ("done", "done_with_fallback"), rows