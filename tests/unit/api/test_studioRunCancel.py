# -*- coding: utf-8 -*-
"""Studio 长任务的取消能力（§6-72 第 1 格；2026-10-08 裁定按新能力做全套四件，§6-91）。

四件缺一件就是假取消，本文件按这个顺序钉：

1. **持久意图**——`runs.cancel_requested` 列与谓词。只有内存句柄的话，重启后
   "用户叫过停"这件事就消失了，行会重新变回"在跑"或 `process_died`。
2. **真句柄**——`_spawn_run` 的执行体能按 run id 在 `core/task_tracker` 里找回来。
   （这一件已由 `5011dddc`（H2-3 ④）落地，本文件里对应两档是**同绿**，不冒充本批战果；
   留在这里是因为四件套是一个整体：登记表在、终态语义错，仍然是假取消。）
3. **收敛单点**——意图被检查点消费、`Task.cancel()` 被 wrapper 消费，两条路都落到
   **同一个终态** `cancelled`；`failed` 不许冒充"用户叫停"（改前 ④ 落的就是
   `failed` + `run_cancelled`，那是"至少别永久 running"的中间形态，本批按实况改判）。
4. **读侧同源**——终态集合加了第四值，前端那份必须同步（跨语言判据
   `test_studioRunStatusVocabulary.py` 双向咬合），否则轮询侧永远等一个不来的状态。

新符号（`RUN_CANCELLED` / `requestCancel` / `guardCancel` / 取消端点）缺席时的红属
"新符号尚未存在"，与行为红分开报，不混成一个数字。
"""
from __future__ import annotations

import asyncio
import inspect
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.aigc_studio import services as svc
from neurova.aigc_studio import store as studio_store
from neurova.aigc_studio.store import RUN_FAILED, RUN_RUNNING, StudioStore
from tests.ast_scan import parseSource

pytestmark = pytest.mark.timeout(60)

USER = {"user_id": "u1", "username": "u1", "role": "user", "neuser_id": "u1"}
OTHER = {"user_id": "u2", "username": "u2", "role": "user", "neuser_id": "u2"}


def _cancelled() -> str:
    """取新常量；缺席即红（新符号红，与行为红分开计）。"""
    value = getattr(studio_store, "RUN_CANCELLED", None)
    assert value is not None, "studio 词汇表里还没有 cancelled 这一档（单源在 store.py）"
    return value


def _terminal() -> frozenset:
    return studio_store.RUN_TERMINAL_STATUSES


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = StudioStore(db_path=str(tmp_path / "studio.db"))
    from neurova.api.endpoints import studio_api

    monkeypatch.setattr(studio_api, "get_store", lambda: store)
    app = FastAPI()
    app.include_router(studio_api.router, prefix="/api/v1/studio")
    holder = {"user": USER}
    from neurova.api.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: holder["user"]
    # 必须走上下文形态：不带 `with` 时 TestClient 每个请求各起一个 portal，POST 一返回
    # 那个循环就关掉，`_spawn_run` 起的后台任务当场被 cancel——于是"取消端点找不到句柄"
    # 和"行已经是 cancelled"都会是**假绿/假红**的来源（本仓登记过的装配噪声形态）。
    with TestClient(app) as c:
        c.holder = holder  # type: ignore[attr-defined]
        c.store = store  # type: ignore[attr-defined]
        yield c


def _mkRun(store, kind="images", owner="u1"):
    project = store.create_project(owner_user_id=owner, title="取消测试")
    return project, store.add_run({"project_id": project["id"], "kind": kind})


def _awaitRow(store, runId, tries=250):
    """等执行体自己收尾（真事件循环在 TestClient 的循环里跑，只能轮询读库）。"""
    for _ in range(tries):
        row = store.get_run(runId)
        if row and row["status"] in _terminal():
            return row
        time.sleep(0.02)
    raise AssertionError(f"run {runId} 没有收敛到终态：{store.get_run(runId)}")


def _waitFlag(flag, key, tries=250):
    """跨线程等执行体的信号（TestClient 的循环在另一个线程，别用 asyncio.Event）。"""
    for _ in range(tries):
        if flag.get(key):
            return
        time.sleep(0.02)
    raise AssertionError(f"执行体没有到达 {key} 这一点")


def _blockingWork(flag):
    """造一条"长跑"的执行体：置 started，等 release 才继续。"""
    async def work(store, pid, content, llm=None, model=None, run_id=None):
        flag["started"] = True
        while not flag.get("release"):
            await asyncio.sleep(0.01)
        return {}

    return work


class TestCancelIntentIsPersisted:
    def test_cancelledIsInTheTerminalSet(self):
        value = _cancelled()
        assert value == "cancelled"
        assert value in _terminal(), (
            "轮询侧只认终态集合；cancelled 不在里面，前端就会一直等到超时"
        )

    def test_requestCancelMarksIntentWithoutEndingTheRow(self, tmp_path):
        store = StudioStore(db_path=str(tmp_path / "s.db"))
        _project, run = _mkRun(store)

        assert store.requestCancel(run["id"]) is True
        row = store.get_run(run["id"])
        assert bool(row["cancel_requested"]) is True, "意图必须落列，不能只在内存里"
        assert row["status"] == RUN_RUNNING, (
            "执行体还在跑时不许直接把行写成终态——那会把'正在收尾'说成'已停'"
        )

    def test_requestCancelRefusesTerminalRows(self, tmp_path):
        store = StudioStore(db_path=str(tmp_path / "s.db"))
        _project, run = _mkRun(store)
        store.update_run(run["id"], {"status": RUN_FAILED})

        assert store.requestCancel(run["id"]) is False
        assert store.get_run(run["id"])["status"] == RUN_FAILED

    def test_predicateReadsTheColumn(self, tmp_path):
        store = StudioStore(db_path=str(tmp_path / "s.db"))
        _project, run = _mkRun(store)
        assert store.cancelRequested(run["id"]) is False
        store.requestCancel(run["id"])
        assert store.cancelRequested(run["id"]) is True

    def test_leftoverCancelRequestedRowConvergesToCancelledNotProcessDied(self, tmp_path):
        """重启后：用户叫过停的行该收成 cancelled，而不是 failed(process_died)。

        两者说的是不同的事——一个是"人让它停的"，一个是"没人管它它就死了"。
        """
        db = str(tmp_path / "s.db")
        first = StudioStore(db_path=db)
        _project, run = _mkRun(first)
        first.requestCancel(run["id"])
        first.close()

        reopened = StudioStore(db_path=db)
        row = reopened.get_run(run["id"])
        assert row["status"] == _cancelled(), f"收敛形态不对：{row}"
        reopened.close()


class TestGuardRaisesAtCheckpoints:
    def test_guardCancelRaisesTheDedicatedError(self, tmp_path):
        store = StudioStore(db_path=str(tmp_path / "s.db"))
        _project, run = _mkRun(store)

        svc.guardCancel(store, run["id"])  # 没意图时应当直接返回

        store.requestCancel(run["id"])
        with pytest.raises(svc.RunCancelled):
            svc.guardCancel(store, run["id"])

    def test_guardCancelIsNoOpWithoutARowIdentity(self, tmp_path):
        """单独复用服务（脚本/测试/别的入口）时没有 run id，不该炸也不该查库。"""
        svc.guardCancel(None, "")
        svc.guardCancel(None, None)

    def test_runCancelledIsNotReusedGenericError(self):
        """专用异常类型：`except Exception` 兜底到处在隔离单镜失败，复用通用异常会让
        "取消"静默变成"这一镜失败了"。"""
        assert issubclass(svc.RunCancelled, Exception)
        assert svc.RunCancelled is not RuntimeError


class TestWrapperConvergence:
    def test_checkpointCancellationConvergesToCancelled(self, client, monkeypatch):
        """服务在检查点抛 RunCancelled → wrapper 落 cancelled，且不写成 failed。"""
        flag = {}

        async def work(store, pid, content, llm=None, model=None, run_id=None):
            flag["started"] = True
            assert run_id, "服务没收到本次请求那一行的 id，检查点就无处可查"
            svc.guardCancel(store, run_id)      # 第一道检查点：应当放行
            while not flag.get("release"):
                await asyncio.sleep(0.01)
            svc.guardCancel(store, run_id)      # 第二道：意图已写上，必须抛
            return {"should_not_reach": True}

        monkeypatch.setattr(svc, "split_script", work)
        pid = client.post("/api/v1/studio/projects",
                          json={"title": "T"}).json()["data"]["project"]["id"]
        runId = client.post(f"/api/v1/studio/projects/{pid}/script",
                            json={"content": "正文"}).json()["data"]["run_id"]
        _waitFlag(flag, "started")
        # 意图在两道检查点之间写上：真实的"用户在长任务跑动中点了停"
        client.store.requestCancel(runId)
        flag["release"] = True

        row = _awaitRow(client.store, runId)
        assert row["status"] == _cancelled(), f"取消后的终态形态：{row}"

    def test_taskHandleCancellationAlsoConvergesToCancelled(self, client, monkeypatch):
        """`Task.cancel()` 那条路（用户点停、句柄在）也必须落 cancelled，不是 failed。"""
        flag = {}
        monkeypatch.setattr(svc, "split_script", _blockingWork(flag))
        pid = client.post("/api/v1/studio/projects",
                          json={"title": "T"}).json()["data"]["project"]["id"]
        runId = client.post(f"/api/v1/studio/projects/{pid}/script",
                            json={"content": "正文"}).json()["data"]["run_id"]
        _waitFlag(flag, "started")

        from neurova.core.task_tracker import get_task_tracker

        assert get_task_tracker().request_session_stop(runId) >= 1, (
            "取消端点找不到句柄——登记表没接通"
        )
        row = _awaitRow(client.store, runId)
        assert row["status"] == _cancelled(), (
            f"句柄取消后落的是 {row['status']!r}：把'人让它停的'记成'它自己崩了'，"
            "运维按失败率排查时会去查一条根本没坏的任务")


class TestHandleRegistryAndEndpoint:
    def test_spawnRunRegistersHandleUnderRunId(self, client, monkeypatch):
        """句柄按 run id 可找回（④ 已落地的一档，本批复跑防回归）。"""
        flag = {}
        monkeypatch.setattr(svc, "split_script", _blockingWork(flag))
        pid = client.post("/api/v1/studio/projects",
                          json={"title": "T"}).json()["data"]["project"]["id"]
        runId = client.post(f"/api/v1/studio/projects/{pid}/script",
                            json={"content": "正文"}).json()["data"]["run_id"]
        _waitFlag(flag, "started")

        from neurova.core.task_tracker import get_task_tracker

        entries = get_task_tracker().lookup_async_tasks(runId)
        assert entries, "执行体句柄没按 run id 登记——取消端点拿不到它"
        assert entries[0]["kind"].startswith("studio:"), entries

        flag["release"] = True
        _awaitRow(client.store, runId)
        assert get_task_tracker().lookup_async_tasks(runId) == [], (
            "done 回调没摘掉条目：登记表会变成第二个常驻引用源")

    def test_studioApiHasNoSecondTaskRegistry(self):
        from neurova.api.endpoints import studio_api

        assert not hasattr(studio_api, "_tasks"), (
            "studio_api 又自建了第二份任务登记：两处注册表必然漂移成"
            "「取消找得到/找不到句柄」的分裂读数")

    def test_cancelEndpointTakesOwnershipAndUnknownRow(self, client):
        """归属：非属主与"不存在"同构回 404。

        这一档必须**先证属主能拿到 200** 再反证：端点根本不存在时两种身份都是 404，
        只写反证的判据是恒真的（本仓登记过的假绿形态之一）。
        """
        _project, mine = _mkRun(client.store)
        assert client.post(f"/api/v1/studio/runs/{mine['id']}/cancel").status_code == 200, (
            "属主这条先红——端点没接上，后面的反证就是恒真")
        _otherProject, theirs = _mkRun(client.store, kind="videos")
        client.holder["user"] = OTHER
        assert client.post(f"/api/v1/studio/runs/{theirs['id']}/cancel").status_code == 404, (
            "非属主不得拿到这条 run 的存在性（与项目侧同构：deny 与不存在同形）")
        client.holder["user"] = USER
        assert client.post("/api/v1/studio/runs/nope_404/cancel").status_code == 404
        assert client.store.get_run(theirs["id"])["cancel_requested"] == 0, (
            "归属判定必须发生在写意图**之前**——先写后判就是越权叫停别人的长任务")

    def test_cancelEndpointRefusesTerminalRunWith409(self, client):
        _project, run = _mkRun(client.store)
        client.store.update_run(run["id"], {"status": "done"})
        r = client.post(f"/api/v1/studio/runs/{run['id']}/cancel")
        assert r.status_code == 409, f"已终态还接受取消就是假成功：{r.status_code} {r.text}"

    def test_cancelEndpointReportsMissingHandleHonestly(self, client):
        """行挂着但本进程没有句柄（重启过）→ 意图落库、句柄取消数如实报 0。

        不许报"已停止"——那等于把"没人执行这一步"写成"执行成功了"。
        """
        _project, run = _mkRun(client.store)
        r = client.post(f"/api/v1/studio/runs/{run['id']}/cancel")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["tasks_cancelled"] == 0, data
        assert bool(client.store.get_run(run["id"])["cancel_requested"]) is True

    def test_cancelEndpointCancelsTheLiveHandle(self, client, monkeypatch):
        """走端点这条真链路：点停 → 意图落库 + 句柄被打断 + 行收 cancelled。"""
        flag = {}
        monkeypatch.setattr(svc, "split_script", _blockingWork(flag))
        pid = client.post("/api/v1/studio/projects",
                          json={"title": "T"}).json()["data"]["project"]["id"]
        runId = client.post(f"/api/v1/studio/projects/{pid}/script",
                            json={"content": "正文"}).json()["data"]["run_id"]
        _waitFlag(flag, "started")

        r = client.post(f"/api/v1/studio/runs/{runId}/cancel")
        assert r.status_code == 200, r.text
        assert r.json()["data"]["tasks_cancelled"] == 1, r.json()
        row = _awaitRow(client.store, runId)
        assert row["status"] == _cancelled(), row


class TestServicesGetTheirCheckpoints:
    def test_batchServicesAcceptRunIdForCheckpoints(self):
        """四个批量服务收得到 run_id，才谈得上在分镜间隙查意图。"""
        for name in ("generate_shot_images", "generate_shot_videos",
                     "generate_asset_images", "synthesize_narration"):
            fn = getattr(svc, name)
            assert "run_id" in inspect.signature(fn).parameters, (
                f"{name} 没有 run_id 形参：它的取消检查点拿不到本次那一行")

    def test_batchLoopsGuardAtTheShardBoundary(self):
        """检查点必须放在**逐镜/逐资产循环体开头**：边界之后绝不许再开新的一镜。

        一步生图几十秒，打断它既不现实也不安全；但"点了停还继续把剩下的镜跑完"
        等于把取消做成了摆设。按 AST 取形：这四个函数体内必须有 `guardCancel(` 调用，
        且它出现在 `for ` 循环体之内。
        """
        import ast
        from pathlib import Path

        src = (Path(__file__).resolve().parents[3]
               / "neurova" / "aigc_studio" / "services.py").read_text(encoding="utf-8")
        tree = parseSource(src)
        wanted = {"generate_shot_images", "generate_shot_videos",
                  "generate_asset_images", "synthesize_narration"}
        found = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
                loops = [l for l in ast.walk(node) if isinstance(l, ast.For)]
                inside = any(
                    isinstance(c, ast.Call)
                    and getattr(c.func, "id", None) == "guardCancel"
                    for loop in loops for c in ast.walk(loop))
                found[node.name] = inside
        missing = sorted(n for n, ok in found.items() if not ok)
        assert not missing, f"这些批量服务没有分片检查点：{missing}"
        assert set(found) == wanted, f"四个服务没全找着：{sorted(found)}"
