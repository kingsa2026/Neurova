# -*- coding: utf-8 -*-
"""H2-3 · ①：四个批量长任务必须结算**自己那一行**台账（§6-86 ①，接 §6-70 的第③格）。

`split_script`/`extract_assets`/`break_storyboards` 三个服务已经走
`rid = run_id or store.add_run(...)` 并在收尾时写 `RUN_DONE` / `RUN_DONE_WITH_FALLBACK`
（§6-70 闭环）。剩下四个——`generate_shot_images`、`generate_shot_videos`、
`generate_asset_images`、`synthesize_narration`——签名里没有 `run_id`，端点那侧的
lambda 直接把 `_runId` 丢弃。于是这一行的终态由 `_spawn_run` 的 wrapper 兜底写成
`done`，**带病完成被压平成成功**：一批里有 3 镜因引用缺失被阻断、2 镜提交失败，
台账上仍是一行干净的 `done`，读侧无从知道它没跑完（与 §6-70 第③格同一形态，
只是当时只修了前三个服务）。

判据（缺一条这条链就是断的）：
1. 部分失败的批量生成 → 行落 `done_with_fallback`，`error` 点名失败/阻断条数；
2. 全部成功 → 行落 `done` 且 `error` 为空（别把成功写成带病）；
3. 一次请求只有一行该 kind 的台账（外层那行就是服务写的行，不另起一行）；
4. 端点的 lambda 不再丢弃 `_runId`（结构守卫 + 反向对照）。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.timeout(90)]

REPO = Path(__file__).resolve().parents[3]
_API_FILE = REPO / "neurova" / "api" / "endpoints" / "studio_api.py"
_SERVICES_FILE = REPO / "neurova" / "aigc_studio" / "services.py"


@pytest.fixture()
def store(tmp_path):
    from neurova.aigc_studio.store import StudioStore

    return StudioStore(db_path=str(tmp_path / "studio.db"))


def _episodeWithShots(store, tmp_path, frames: dict):
    """frames: 镜头序号 → 是否给首帧文件（决定它能不能提交视频）。"""
    project = store.create_project(owner_user_id="u1", title="台账结算", aspect_ratio="9:16")
    ep = store.add_episode(project["id"], {"number": 1, "title": "e"})
    shots = []
    for n, hasFrame in frames.items():
        sb = store.add_storyboard(ep["id"], {"number": n, "video_prompt": f"镜{n}",
                                             "prompt": f"镜{n}", "duration": 3})
        if hasFrame:
            f = tmp_path / f"f{n}.png"
            f.write_bytes(b"IMG")
            store.update_storyboard(sb["id"], {"first_frame_path": str(f)})
        shots.append(sb)
    return project, ep, shots


def _videoProbe(monkeypatch, tmp_path, okTaskIds=("r1",)):
    from neurova.llm.generators import protocols as proto_mod
    from neurova.llm.generators import runtime as gen_runtime
    from neurova.llm.generators import task_ledger as ledger_mod
    from neurova.llm.generators.protocols import ProtocolCredentials
    from neurova.llm.generators.task_ledger import GenerationTaskLedger

    monkeypatch.setattr(ledger_mod, "_ledger",
                        GenerationTaskLedger(path=str(tmp_path / "led.json")))

    def fakeResolve(hint, model, providerId, apiKey, baseUrl, defaultBase=None, **kw):
        return ProtocolCredentials(api_key="k", base_url="https://x", model="m", protocol=hint)

    async def fakeSubmit(creds, prompt, **kw):
        return {"task_id": f"r{len(kw) and 1}", "poll_url": "", "raw": {}}

    monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fakeResolve)
    monkeypatch.setattr(proto_mod, "submit_video", fakeSubmit)


class TestServiceSettlesItsOwnRow:
    @pytest.mark.asyncio
    async def test_partial_failure_lands_done_with_fallback_and_names_the_counts(
            self, store, tmp_path, monkeypatch):
        from neurova.aigc_studio import services

        _videoProbe(monkeypatch, tmp_path)
        project, ep, shots = _episodeWithShots(store, tmp_path, {1: True, 2: False})
        rid = store.add_run({"project_id": project["id"], "kind": "videos"})["id"]
        stats = await services.generate_shot_videos(store, project["id"], ep["id"],
                                                     model="wan-x", run_id=rid)
        row = store.get_run(rid)
        assert stats["blocked_no_frame"] == 1, stats
        assert row["status"] == "done_with_fallback", (
            f"有镜头被阻断，台账行却是干净的 {row['status']!r}——带病完成被压平成成功，"
            "读侧无从知道这批没跑完（§6-70 第③格的残留面）")
        assert "1" in (row["error"] or ""), row["error"]
        assert json.loads(row["detail_json"])["blocked_no_frame"] == 1

    @pytest.mark.asyncio
    async def test_all_success_lands_plain_done_with_no_error(self, store, tmp_path, monkeypatch):
        from neurova.aigc_studio import services

        _videoProbe(monkeypatch, tmp_path)
        project, ep, shots = _episodeWithShots(store, tmp_path, {1: True})
        rid = store.add_run({"project_id": project["id"], "kind": "videos"})["id"]
        await services.generate_shot_videos(store, project["id"], ep["id"],
                                            model="wan-x", run_id=rid)
        row = store.get_run(rid)
        assert row["status"] == "done", row
        assert not (row["error"] or ""), f"全成功却被写成带病：{row['error']!r}"

    @pytest.mark.asyncio
    async def test_asset_images_and_narration_settle_their_row_too(
            self, store, tmp_path, monkeypatch):
        """同一根因的另外两个服务：不能只修视频那一个（教义第 5 条）。"""
        from neurova.aigc_studio import services

        project = store.create_project(owner_user_id="u1", title="资产结算")
        rid = store.add_run({"project_id": project["id"], "kind": "asset_images"})["id"]

        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators.protocols import ProtocolCredentials

        def fakeResolve(hint, model, providerId, apiKey, baseUrl, defaultBase=None, **kw):
            return ProtocolCredentials(api_key="k", base_url="https://x", model="m", protocol=hint)

        async def boomImage(creds, prompt, **kw):
            raise RuntimeError("上游炸了")

        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fakeResolve)
        monkeypatch.setattr(proto_mod, "generate_image", boomImage)
        store.add_character(project["id"], {"name": "甲"})
        stats = await services.generate_asset_images(store, project["id"], run_id=rid)
        row = store.get_run(rid)
        assert stats["failed"] >= 1, stats
        assert row["status"] == "done_with_fallback", (
            f"定妆图全失败却被记成 {row['status']!r}：同一根因不能只修视频那一个")


class TestOneRequestOneRow:
    @pytest.mark.asyncio
    async def test_endpoint_path_writes_the_outer_row_only(self, store, tmp_path, monkeypatch):
        """走真 `_spawn_run`：一次请求该 kind 只该有一行，且那行由服务结算。"""
        from unittest.mock import patch

        from neurova.api.endpoints import studio_api

        _videoProbe(monkeypatch, tmp_path)
        project, ep, shots = _episodeWithShots(store, tmp_path, {1: True, 2: False})
        monkeypatch.setattr("neurova.aigc_studio.store.get_store", lambda: store)
        with patch("neurova.api.endpoints.get_agent_instance"):
            spawned = studio_api._spawn_run(
                store, project["id"], "videos",
                lambda runId: services_generateVideos(store, project["id"], ep["id"], runId))
        runId = spawned["data"]["run_id"]
        for _ in range(60):
            import asyncio
            await asyncio.sleep(0.1)
            row = store.get_run(runId)
            if row and row["status"] != "running":
                break
        sameKind = [r for r in store.list_runs(project["id"]) if r["kind"] == "videos"]
        assert len(sameKind) == 1, (
            f"一次请求在 runs 表里留下 {len(sameKind)} 行同 kind——读侧无从判断哪条代表这次请求")
        row = store.get_run(runId)
        assert row["status"] == "done_with_fallback", (
            f"外层那行仍是 wrapper 兜底的 {row['status']!r}，说明 run_id 没贯通到服务")


async def services_generateVideos(store, pid, eid, runId):
    from neurova.aigc_studio import services

    return await services.generate_shot_videos(store, pid, eid, model="wan-x",
                                               run_id=runId)


class TestRunIdIsNotDiscarded:
    """判据 4：端点 lambda 不许再丢弃形参（结构守卫 + 反向对照）。"""

    def _discardedRunIds(self, src: str) -> list[str]:
        """`lambda _runId: ...` 且体内没引用该形参 = 句柄被丢掉。"""
        hits = []
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Lambda):
                continue
            names = [a.arg for a in node.args.args]
            if not any(n.startswith("_runId") or n == "_runId" for n in names):
                continue
            used = {n.id for n in ast.walk(node.body) if isinstance(n, ast.Name)}
            if not set(names) & used:
                hits.append(f"line {node.lineno}: lambda {names[0]} 被丢弃")
        return hits

    def test_no_endpoint_lambda_throws_away_the_run_id(self):
        offenders = self._discardedRunIds(_API_FILE.read_text(encoding="utf-8"))
        assert not offenders, f"studio_api 仍有 lambda 丢弃 run_id：{offenders}"

    def test_reverse_control_catches_a_discarded_handle(self):
        src = "f = lambda _runId: work(1)\ng = lambda runId: work(runId)\n"
        assert self._discardedRunIds(src) == ["line 1: lambda _runId 被丢弃"], \
            "扫描器抓不到被丢弃的句柄——那判据就是在演空转"
        assert self._discardedRunIds("f = lambda runId: work(runId)\n") == []
