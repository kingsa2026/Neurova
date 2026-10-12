# -*- coding: utf-8 -*-
"""账本里那条 `result_url` 终于有了读者：抢救远端产物，别为一单再付一次钱（§6-99、H2-2 D 条账本侧）。

缺陷实况（本批复算后比原登记更窄也更准）：`result_url` **不是全仓零读者**——
`api/endpoints/generation.py:676/738` 读它（生成任务 REST 面）。缺的是 **Studio 这一侧**：
`video_reconcile.reconcileEpisode` 见到「账本 `succeeded` 而无 `local_path`」时，
`0dd80fd0` 已把镜头诚实改判成 `failed` + 成因（这一半早就闭环），
但账本里那条 URL 从此**再也没有人去取**——用户点「重试视频」时，
`services.generate_shot_videos` 直接重新 `submit_video` 向服务商再买一次，
而那一单原本已经付过钱、产物也还在远端。URL 过期即永丢，且系统表现得像"什么都没发生过"。

所以本批的接法不是"把过期外链摆到前端"（那要新建一条对外展示面，且链接本身不可靠），
而是**在花钱之前先抢救**：提交那一步之前查账本，若这条任务已 `succeeded` 且有远端 URL
而本地没件，就用仓内唯一的产物落盘点 `persist_media`（含出网安全闸）把它拉回本地；
拉回来就记 `done` 并**不再提交**，拉不回才照常提交——失败面一字不改，仍是诚实降级。

判据（缺一条这条链就是断的）：
1. 主行为：账本 succeeded + 有 URL + 无本地件 → `persist_media` 收到的正是那条 URL，
   `submit_video` **一次都没被调**，镜头落 `done` 且 `video_path` 就是拉回来的件；
2. 账本自身也要补上 `local_path`（只写镜头行会让下一次收口又判它"没本地化"）；
3. 拉不回（URL 过期/下载坏）→ 照常提交，不许静默丢弃这一镜；
4. 无远端 URL / 账本行丢了 → 走原路提交（不许把"没得救"读成"救过了"）；
5. `running` 的镜头在抢救之前就跳过（正在跑的活不该被半路截胡）；
6. 读数要有读者：`detail_json.fallback` 点名抢救条数与"未重复提交"，
   终态 `done_with_fallback`（前端 `describeRunOutcome` 已读这个键，不新造第二份口径）；
7. 边界回归：账本既无本地件也无远端 URL 时，收口仍诚实落 `failed`（§6-78 D 条那一半不许漂）。
"""
from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.timeout(60)

REMOTE_URL = "https://provider.example/v/clip-7.mp4"


@pytest.fixture()
def store(tmp_path):
    from neurova.aigc_studio.store import StudioStore

    return StudioStore(db_path=str(tmp_path / "studio.db"))


@pytest.fixture()
def ledgers(tmp_path):
    """生成任务账本换成临时件——判据要能往里栽 `succeeded` 行，且不碰仓内台账。"""
    from neurova.llm.generators import task_ledger as ledger_mod
    from neurova.llm.generators.task_ledger import GenerationTaskLedger

    led = GenerationTaskLedger(path=str(tmp_path / "led.json"))
    ledger_mod._ledger = led
    yield led
    ledger_mod._ledger = None


@pytest.fixture()
def submitProbe(monkeypatch):
    """提交替身只记"到底有没有再花一次钱"。"""
    from neurova.llm.generators import protocols as proto_mod
    from neurova.llm.generators import runtime as gen_runtime
    from neurova.llm.generators.protocols import ProtocolCredentials

    calls = []

    def fake_resolve(hint, model, provider_id, api_key, base_url, default_base):
        return ProtocolCredentials(api_key="k", base_url="https://x", model="m",
                                   protocol=hint)

    async def fakeSubmit(creds, prompt, **kw):
        calls.append("submitted")
        return {"task_id": "r-new", "poll_url": "", "raw": {}}

    monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
    monkeypatch.setattr(proto_mod, "submit_video", fakeSubmit)
    return calls


@pytest.fixture()
def persistProbe(monkeypatch, tmp_path):
    """落盘替身记下**收到的 URL**，并按需成功/失败（真件在盘上，判据才咬得住）。"""
    from neurova.llm.generators import runtime as gen_runtime

    box = {"urls": [], "fail": False, "path": str(tmp_path / "salvaged.mp4")}

    async def fakePersist(url, kind, task_id, index, out_dir=None):
        box["urls"].append(url)
        if box["fail"]:
            raise RuntimeError("403 Forbidden（URL 已过期）")
        with open(box["path"], "wb") as f:
            f.write(b"mp4")
        return box["path"]

    monkeypatch.setattr(gen_runtime, "persist_media", fakePersist)
    return box


def _episodeWithSalvageableShot(store, tmp_path, led, *, status="succeeded",
                                resultUrl=REMOTE_URL, localPath=""):
    """一集一镜：有首帧（否则 C1 的无首帧闸会先拦下，判据看不到这一支）、
    账本里一条已收口的视频任务，镜头行 `failed`（＝收口成功但本地化失败后的形态）。"""
    project = store.create_project(owner_user_id="u1", title="抢救远端件",
                                   aspect_ratio="9:16")
    ep = store.add_episode(project["id"], {"number": 1, "title": "e"})
    sb = store.add_storyboard(ep["id"], {"number": 1, "video_prompt": "雨夜巷口对峙",
                                         "duration": 3})
    frame = tmp_path / f"frame_{sb['id']}.png"
    frame.write_bytes(b"IMG")
    store.update_storyboard(sb["id"], {"first_frame_path": str(frame)})
    if status is not None:
        from neurova.llm.generators.task_ledger import TaskRecord

        rec = led.add(TaskRecord(kind="video", protocol="dashscope", model="wan",
                                 status=status, remote_task_id="r-1",
                                 result_url=resultUrl, local_path=localPath,
                                 batch_key=ep["id"], project_id=project["id"]))
        store.update_storyboard(sb["id"], {"ledger_task_id": rec.task_id,
                                           "video_status": "failed",
                                           "error": "视频已生成但本地化失败，产物未落盘"})
    return project, ep, sb


class TestSalvageBeforePayingAgain:
    @pytest.mark.asyncio
    async def test_remote_artifact_is_pulled_back_instead_of_resubmitting(
            self, store, tmp_path, ledgers, submitProbe, persistProbe):
        from neurova.aigc_studio import services

        project, ep, sb = _episodeWithSalvageableShot(store, tmp_path, ledgers)
        stats = await services.generate_shot_videos(store, project["id"], ep["id"])

        assert submitProbe == [], (
            f"账本里那条远端产物还在，却已经又向服务商提交了一次：{submitProbe}")
        assert persistProbe["urls"] == [REMOTE_URL], (
            f"落盘替身收到的不是账本里那条 URL：{persistProbe['urls']}")
        row = store.get_storyboard(sb["id"])
        assert row["video_status"] == "done", f"抢救成功却没收敛镜头行：{row}"
        assert row["video_path"] == persistProbe["path"] and row["error"] == "", row
        assert stats["submitted"] == 0 and stats["recovered"] == 1, stats

    @pytest.mark.asyncio
    async def test_ledger_row_also_gets_the_local_path(self, store, tmp_path, ledgers,
                                                       submitProbe, persistProbe):
        """只写镜头行＝留下第二份事实：下一次收口又按账本判它"没本地化"。"""
        from neurova.aigc_studio import services

        project, ep, sb = _episodeWithSalvageableShot(store, tmp_path, ledgers)
        await services.generate_shot_videos(store, project["id"], ep["id"])
        task = ledgers.get(store.get_storyboard(sb["id"])["ledger_task_id"])
        assert task.local_path == persistProbe["path"], (
            f"账本行的 local_path 还是空的：{task.local_path!r}")

    @pytest.mark.asyncio
    async def test_unreachable_url_falls_through_to_a_real_submit(
            self, store, tmp_path, ledgers, submitProbe, persistProbe):
        """拉不回就照常提交——不许把"救过了"当成"这一镜不用管"，也不许假成功。"""
        from neurova.aigc_studio import services

        persistProbe["fail"] = True
        project, ep, sb = _episodeWithSalvageableShot(store, tmp_path, ledgers)
        stats = await services.generate_shot_videos(store, project["id"], ep["id"])

        assert submitProbe == ["submitted"], "抢救失败后这一镜被静默丢掉了"
        assert stats["submitted"] == 1 and stats.get("recovered", 0) == 0, stats
        row = store.get_storyboard(sb["id"])
        assert row["video_status"] == "running", (
            f"提交成功后镜头行没收口：{row['video_status']!r} / {row['error']!r}")

    @pytest.mark.asyncio
    async def test_nothing_to_salvage_keeps_the_old_path(self, store, tmp_path, ledgers,
                                                         submitProbe, persistProbe):
        """无远端 URL（或账本行丢了）→ 一次落盘都不该发，直接走原提交路。"""
        from neurova.aigc_studio import services

        p1, e1, s1 = _episodeWithSalvageableShot(store, tmp_path, ledgers, resultUrl="")
        p2, e2, s2 = _episodeWithSalvageableShot(store, tmp_path, ledgers, status=None)
        await services.generate_shot_videos(store, p1["id"], e1["id"])
        await services.generate_shot_videos(store, p2["id"], e2["id"])

        assert persistProbe["urls"] == [], f"没得救却发了落盘：{persistProbe['urls']}"
        assert len(submitProbe) == 2, submitProbe


    @pytest.mark.asyncio
    async def test_inline_data_url_is_salvaged_too(self, store, tmp_path, ledgers,
                                                   submitProbe, persistProbe):
        """provider 直接回内联 base64 时，账本里 `result_url` 是 `data:` 而 `local_path` 空
        （§6-78 的活体注记实测过这一支）。`persist_media` 原生吃这一形态，且它不需要出网——
        只认 `http` 就等于把"本地从没落过盘"那一类留在抢救门外。"""
        from neurova.aigc_studio import services

        dataUrl = "data:video/mp4;base64," + "A1" * 64
        project, ep, sb = _episodeWithSalvageableShot(store, tmp_path, ledgers,
                                                      resultUrl=dataUrl)
        stats = await services.generate_shot_videos(store, project["id"], ep["id"])

        assert persistProbe["urls"] == [dataUrl], (
            f"内联件没进抢救：{persistProbe['urls']}")
        assert submitProbe == [], "内联件明明能直接落盘，却又向服务商提交了一次"
        assert stats["recovered"] == 1, stats


class TestSalvageDoesNotStealInFlightWork:
    @pytest.mark.asyncio
    async def test_running_shot_is_skipped_before_any_salvage(self, store, tmp_path,
                                                              ledgers, submitProbe,
                                                              persistProbe):
        """`running` 的镜头在跳过闸门之后、抢救之前就该被摘掉——正跑着的活不截胡。"""
        from neurova.aigc_studio import services

        project, ep, sb = _episodeWithSalvageableShot(store, tmp_path, ledgers)
        store.update_storyboard(sb["id"], {"video_status": "running", "error": ""})
        stats = await services.generate_shot_videos(store, project["id"], ep["id"])

        assert persistProbe["urls"] == [] and submitProbe == [], (
            "running 的镜头被抢救/重复提交了")
        assert stats["skipped"] == 1, stats


class TestSalvageReadsBackToTheLedgerRow:
    @pytest.mark.asyncio
    async def test_run_detail_names_the_rescue_for_the_existing_reader(self, store, tmp_path,
                                                                       ledgers, submitProbe,
                                                                       persistProbe):
        """前端 `describeRunOutcome` 只读 `fallback` 这一族键——抢救条数要走它，不新造口径。"""
        import json

        from neurova.aigc_studio import services
        from neurova.aigc_studio.store import RUN_DONE_WITH_FALLBACK

        project, ep, sb = _episodeWithSalvageableShot(store, tmp_path, ledgers)
        await services.generate_shot_videos(store, project["id"], ep["id"])

        runs = [r for r in store.list_runs(project["id"]) if r["kind"] == "videos"]
        assert len(runs) == 1, runs
        detail = json.loads(runs[0]["detail_json"] or "{}")
        cause = str(detail.get("fallback") or "")
        assert runs[0]["status"] == RUN_DONE_WITH_FALLBACK, (
            f"抢救这一跳没进终态读数：{runs[0]['status']!r}")
        assert "1" in cause and ("未重复提交" in cause or "抢救" in cause), (
            f"成因人读不出抢救了几条：{cause!r}")


class TestReconcileBoundaryUnchanged:
    @pytest.mark.asyncio
    async def test_localization_failure_without_url_still_lands_honest_failed(
            self, store, tmp_path, ledgers):
        """§6-78 D 条那一半不许漂：没得救时仍诚实 `failed`，不写 done + 空路径。"""
        from neurova.aigc_studio import video_reconcile

        project, ep, sb = _episodeWithSalvageableShot(store, tmp_path, ledgers,
                                                      resultUrl="")
        store.update_storyboard(sb["id"], {"video_status": "running"})
        video_reconcile.reconcileEpisode(store, ep["id"])
        row = store.get_storyboard(sb["id"])
        assert row["video_status"] == "failed", row
        assert "本地化失败" in (row["error"] or ""), row["error"]
        assert not row["video_path"], f"本地没有件却写了路径：{row['video_path']}"

    def test_the_salvageHasExactlyOneOwner(self):
        """抢救逻辑只许一处实装：`video_reconcile` 里那个同步入口，别在 services 再抄一份。"""
        import ast
        from pathlib import Path

        repo = Path(__file__).resolve().parents[3]
        found = []
        for rel in ("neurova/aigc_studio/services.py", "neurova/aigc_studio/video_reconcile.py"):
            tree = ast.parse((repo / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and node.name.startswith("salvage"):
                    found.append(f"{rel}:{node.lineno}")
        assert len(found) == 1, f"抢救实装出现 {len(found)} 份：{found}"
