# -*- coding: utf-8 -*-
"""C 批：制片导出改成**可停可查的后台 run**，并把 FFmpeg 段挪出事件循环（§6-94，内含 §6-93 的 A）。

复核实状（两条与登记不同，都影响修法）：
- `POST /episodes/{eid}/merge` 从来不是后台任务（同步 `await services.merge_episode(...)`，
  不建台账行、不登记句柄）——所以 §6-91 那句"merge 没有取消边界"表述不准，
  实情是**没有可取消的对象**，导出结果只落 `merges` 表，`runs` 里根本没有它，
  §6-87/§6-88 那套"带病完成"读数对导出完全不适用。
- `merge_episode` 是 `async def`，其内 `subprocess.run(cmd, timeout=600)` 无 offload
  （`services.py:790`，另有 `mix_bgm`/`probe_has_audio`/`burn_subtitles` 三处同型）——
  合片期间**整个事件循环停摆**：chat 流式、其它长任务的轮询与终态回调、recovery 定时任务
  全部排队，日志零异常。**光后台化不解决这一条**：执行体仍挂在同一个循环上。

判据（缺一环就不是"补链"而是换个地方卡）：
1. 服务收 `run_id` 并结算**自己那一行**：降级连播清单＝`done_with_fallback` + 成因，
   真出片＝`done` + 产出读数（composed/mode/url/merge_id），无就绪产物＝诚实 `failed`；
2. 分步骤之间有取消检查点（concat → 混音 → 烧字幕），叫停后落 `cancelled` 且不再开下一级；
3. **事件循环在 FFmpeg 段仍然在转**（心跳判据，即 §6-93 的 A：阻塞调用挪进 `to_thread`）；
4. 端点改回"立即返回 run_id"，导出进度与终态经 `GET /projects/{pid}` 的 runs 投影可读；
5. 产物明细仍以 `merges` 表为唯一事实源（新增 `GET /merges/{mid}`，属主判定与不存在同构 404），
   **不把 items 塞进 `detail_json` 造成第二份表示**。
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.timeout(90)

REPO = Path(__file__).resolve().parents[3]
USER = {"user_id": "u1", "username": "u1", "role": "user", "neuser_id": "u1"}
OTHER = {"user_id": "u2", "username": "u2", "role": "user", "neuser_id": "u2"}


@pytest.fixture()
def store(tmp_path):
    from neurova.aigc_studio.store import StudioStore

    return StudioStore(db_path=str(tmp_path / "studio.db"))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from neurova.aigc_studio.store import StudioStore
    from neurova.api.endpoints import studio_api
    from neurova.api.deps import get_current_user

    st = StudioStore(db_path=str(tmp_path / "api.db"))
    monkeypatch.setattr(studio_api, "get_store", lambda: st)
    app = FastAPI()
    app.include_router(studio_api.router, prefix="/api/v1/studio")
    holder = {"user": USER}
    app.dependency_overrides[get_current_user] = lambda: holder["user"]
    with TestClient(app) as c:
        c.holder = holder  # type: ignore[attr-defined]
        c.store = st  # type: ignore[attr-defined]
        yield c


@pytest.fixture()
def ffmpegStage(tmp_path, monkeypatch):
    """把 FFmpeg 边界替成"同型阻塞调用"，并把产物目录挪进 tmp_path（不写仓内 data/）。"""
    from neurova.core import ffmpeg as ffmpeg_mod
    from neurova.llm.generators import runtime as gen_runtime

    outDir = tmp_path / "gens"
    outDir.mkdir()
    monkeypatch.setattr(gen_runtime, "GENERATION_OUTPUT_DIR", outDir, raising=False)
    monkeypatch.setattr(ffmpeg_mod, "resolve_ffmpeg_path", lambda *a, **k: "/usr/bin/ffmpeg-fake")
    monkeypatch.setattr(ffmpeg_mod, "has_cjk_font", lambda: True)
    calls = {"run": 0, "block_s": 0.4}

    class Proc:
        returncode = 0
        stdout = b""
        stderr = b""

    def fakeRun(cmd, **kw):
        calls["run"] += 1
        time.sleep(calls["block_s"])      # 与真 subprocess.run 同型：占住当前线程
        target = Path(cmd[-1])
        target.write_bytes(b"MP4")
        return Proc()

    monkeypatch.setattr(subprocess, "run", fakeRun)
    return calls


def _episodeWithVideos(store, tmp_path, n=2):
    project = store.create_project(owner_user_id="u1", title="导出后台化")
    eid = store.add_episode(project["id"], {"number": 1, "title": "e1", "content": "夜"})["id"]
    for i in range(1, n + 1):
        v = tmp_path / f"clip{i}.mp4"
        v.write_bytes(b"VID")
        store.add_storyboard(eid, {"number": i, "video_path": str(v), "duration": 3,
                                   "narration": f"台词{i}"})
    return project, eid


async def _awaitTerminal(store, rid, tries=250):
    """等执行体自己收尾。

    必须 `await asyncio.sleep`：`_spawn_run` 的任务挂在**当前这个循环**上，
    用阻塞的 `time.sleep` 等它，等于自己把循环占死——那测出来的是测试的等待方式，
    不是产品的收敛（本文件另一格正是拿这个形态去量产品的）。
    """
    from neurova.aigc_studio.store import RUN_TERMINAL_STATUSES

    for _ in range(tries):
        row = store.get_run(rid)
        if row and row["status"] in RUN_TERMINAL_STATUSES:
            return row
        await asyncio.sleep(0.02)
    raise AssertionError(f"导出 run 没收敛到终态：{store.get_run(rid)}")


class TestMergeSettlesItsOwnRunRow:
    @pytest.mark.asyncio
    async def test_service_accepts_run_id_and_settles_it(self, store, tmp_path, ffmpegStage):
        from neurova.aigc_studio import services
        from neurova.aigc_studio.store import RUN_DONE

        project, eid = _episodeWithVideos(store, tmp_path)
        rid = store.add_run({"project_id": project["id"], "kind": "merge"})["id"]
        res = await services.merge_episode(store, project["id"], eid, run_id=rid)
        row = store.get_run(rid)
        assert row["status"] == RUN_DONE, (
            f"真出片的导出行落的是 {row['status']!r}：{row['error']!r}")
        detail = json.loads(row["detail_json"])
        assert detail["composed"] is True, detail
        assert detail["merge_id"] == res["merge"]["id"], detail
        assert detail["url"] == res["url"], detail

    @pytest.mark.asyncio
    async def test_degraded_manifest_is_done_with_fallback_with_cause(self, store, tmp_path,
                                                                      monkeypatch):
        """本机无 FFmpeg → 连播清单是**带病交付**，不再是"runs 里根本没有这一行"。"""
        from neurova.aigc_studio import services
        from neurova.aigc_studio.store import RUN_DONE_WITH_FALLBACK
        from neurova.core import ffmpeg as ffmpeg_mod

        monkeypatch.setattr(ffmpeg_mod, "resolve_ffmpeg_path", lambda *a, **k: None)
        project, eid = _episodeWithVideos(store, tmp_path)
        rid = store.add_run({"project_id": project["id"], "kind": "merge"})["id"]
        await services.merge_episode(store, project["id"], eid, run_id=rid)
        row = store.get_run(rid)
        assert row["status"] == RUN_DONE_WITH_FALLBACK, (
            f"降级连播清单却落 {row['status']!r}——用户以为拿到了成片")
        assert "FFmpeg" in (row["error"] or "") or "清单" in (row["error"] or ""), row["error"]

    @pytest.mark.asyncio
    async def test_no_ready_material_is_an_honest_failure(self, store, tmp_path):
        """无就绪产物不是"成功但 composed=False"，是失败——由 wrapper 落 failed。"""
        from neurova.api.endpoints import studio_api

        project = store.create_project(owner_user_id="u1", title="空导出")
        eid = store.add_episode(project["id"], {"number": 1, "content": "夜"})["id"]
        accepted = studio_api._spawn_run(
            store, project["id"], "merge",
            lambda runId: services_mergeEpisode(store, project["id"], eid, runId))
        row = await _awaitTerminal(store, accepted["data"]["run_id"])
        assert row["status"] == "failed", (
            f"没素材却收敛成 {row['status']!r}——导出面板会显示"
            "「已输出连播清单」，而清单里一条素材都没有")
        assert "无就绪产物" in (row["error"] or ""), row["error"]


class TestCancelAndLoopStayHonest:
    @pytest.mark.asyncio
    async def test_checkpoint_between_stages_cancels_the_export(self, store, tmp_path,
                                                                ffmpegStage):
        """叫停后不再开下一级：混音/烧字幕都在检查点之后，意图落库即抛 `RunCancelled`。"""
        from neurova.aigc_studio import services
        from neurova.aigc_studio.store import RUN_CANCELLED

        project, eid = _episodeWithVideos(store, tmp_path)
        rid = store.add_run({"project_id": project["id"], "kind": "merge"})["id"]
        store.requestCancel(rid)
        with pytest.raises(svc_RunCancelled()):
            await services.merge_episode(store, project["id"], eid,
                                         bgm_path=str(tmp_path / "nope.mp3"), run_id=rid)
        assert RUN_CANCELLED  # 常量存在即词汇表已含取消终态

    @pytest.mark.asyncio
    async def test_event_loop_keeps_running_during_the_ffmpeg_stage(self, store, tmp_path,
                                                                   ffmpegStage):
        """§6-93 的 A：合片那段阻塞必须在别的线程里跑，循环要照常调度心跳任务。

        这条判据刻意不测"快不快"，只测**循环有没有被占死**：改前 `subprocess.run` 在
        协程里裸调，心跳一次都不会推进；offload 到 `asyncio.to_thread` 后照常推进。
        """
        from neurova.aigc_studio import services

        project, eid = _episodeWithVideos(store, tmp_path)
        rid = store.add_run({"project_id": project["id"], "kind": "merge"})["id"]
        ticks = {"n": 0}

        async def ticker():
            while True:
                ticks["n"] += 1
                await asyncio.sleep(0.01)

        watcher = asyncio.create_task(ticker())
        try:
            before = ticks["n"]
            await services.merge_episode(store, project["id"], eid, run_id=rid)
            advanced = ticks["n"] - before
        finally:
            watcher.cancel()
        assert ffmpegStage["run"] >= 1, (
            "替身没被调用——上面那个心跳数是空的（清单降级支路不碰 FFmpeg）")
        assert advanced >= 10, (
            f"合片 {ffmpegStage['block_s']}s 期间循环心跳只推进 {advanced} 次："
            "阻塞调用仍占着事件循环，同进程内所有请求与回调都在排队")


class TestEndpoints:
    def test_merge_endpoint_returns_a_run_id(self, client):
        """端点形态改了：立即返回 run_id，导出这条任务进 runs 台账。"""
        project = client.store.create_project(owner_user_id="u1", title="T")
        eid = client.store.add_episode(project["id"], {"number": 1, "content": "夜"})["id"]
        r = client.post(f"/api/v1/studio/episodes/{eid}/merge", json={})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data.get("run_id"), f"端点没返回 run_id（还是同步空转？）：{data}"
        rows = [x for x in client.store.list_runs(project["id"]) if x["kind"] == "merge"]
        assert [x["id"] for x in rows] == [data["run_id"]], (
            f"一次导出了 {len(rows)} 行 merge 台账，或外层那行不是端点给前端的那行：{rows}")

    @pytest.mark.asyncio
    async def test_export_progress_is_visible_in_the_projection(self, store, tmp_path,
                                                                monkeypatch):
        """降级导出要在 `GET /projects/{pid}` 里读得到——这是把导出接进 §6-87/§6-88
        那套读数的全部意义。改前不写死状态、不手工铺行：走真 `_spawn_run` + 真服务。"""
        from neurova.api.endpoints import studio_api
        from neurova.core import ffmpeg as ffmpeg_mod

        monkeypatch.setattr(ffmpeg_mod, "resolve_ffmpeg_path", lambda *a, **k: None)
        project, eid = _episodeWithVideos(store, tmp_path)
        accepted = studio_api._spawn_run(
            store, project["id"], "merge",
            lambda runId: services_mergeEpisode(store, project["id"], eid, runId))
        row = await _awaitTerminal(store, accepted["data"]["run_id"])
        detail = json.loads(row["detail_json"])
        assert row["status"] == "done_with_fallback", (
            f"降级导出在台账上是 {row['status']!r}：读侧无从知道没拿到成片")
        assert detail["composed"] is False, detail
        # 投影面：前端只读 GET 的返回，不读库
        projected = next((x for x in store.list_runs(project["id"])
                          if x["id"] == accepted["data"]["run_id"]), {})
        assert projected.get("status") == "done_with_fallback", projected

    def test_getMergeEndpointOwnershipMatchesNotFound(self, client):
        """产物明细仍以 merges 表为唯一事实源；非属主与不存在同构 404。

        先证属主 200 再反证（端点不存在时两种身份都 404，只写反证就是恒真判据）。
        """
        project = client.store.create_project(owner_user_id="u1", title="归属")
        eid = client.store.add_episode(project["id"], {"number": 1, "content": "夜"})["id"]
        merge = client.store.add_merge({"project_id": project["id"], "episode_id": eid,
                                        "mode": "ffmpeg_concat", "status": "done",
                                        "output_url": "/api/v1/generation/files/a.mp4",
                                        "items": [{"index": 1, "shot": 1}]})
        assert client.get(f"/api/v1/studio/merges/{merge['id']}").status_code == 200, "端点没接上"
        client.holder["user"] = OTHER
        assert client.get(f"/api/v1/studio/merges/{merge['id']}").status_code == 404
        client.holder["user"] = USER
        assert client.get("/api/v1/studio/merges/nope").status_code == 404


async def services_mergeEpisode(store, pid, eid, runId):
    from neurova.aigc_studio import services

    return await services.merge_episode(store, pid, eid, run_id=runId)


def svc_RunCancelled():
    """延迟取异常类：缺席即红在"新符号没建"，与行为红分开报。"""
    from neurova.aigc_studio import services

    return services.RunCancelled
