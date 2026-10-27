# -*- coding: utf-8 -*-
"""H2-4 · G 条：单镜「重试」必须用这条镜头当初的规格（§6-78 G 条，拍板＝绑定镜头行）。

缺陷形态（改前）：整集首发由前端把规格写在请求体里（`StudioProjectPage.vue` 传
`resolution: '720p'` → `studio_api.py` 整集支路透传），而**单镜重试支路一个都不传**
（`studio_api.py` 的 `retry_storyboard` video 支）——于是落回服务层默认 1080p/5s。
同一镜头点「重试」＝悄悄换了规格（更贵、更慢、画面尺寸也变了），账面毫无线索：
**规格从未与镜头绑定，重试时无处可查它上次用的是什么**。

修法（用户拍板 B 形态）：`storyboards.video_resolution` 一列承担「这条镜头是用什么规格
提交的」这一事实——提交时写、重试时读回；缺省才落服务层唯一默认。`duration` 不在此列，
它早已镜头级同源（`services.py` 提交时优先读 `sb["duration"]`，请求体那份只是兜底），
本批只补 resolution 这缺失的一半。形态与 C1 里 `characters.seed_value`「写下去要有人读」
同构。

判据（缺一条这条链就是断的）：

1. **写侧留痕**：整集首发传 `resolution='720p'` → 每条被提交的镜头行都落 `720p`，
   且实际发出的提交请求也是 720p（写的是用的那枚，不是另一枚）；
2. **读侧继承**（本批主红灯）：随后走**重试支路**（不传任何规格）→ 提交收到的仍是 `720p`。
   改前这里是 1080p——即「重试 = 换规格」；
3. **旧库不缺也不炸**：行内从未落过规格（改造前的存量镜头）→ 落服务层**唯一**默认，
   行为与本批之前一致（不趁机改默认档，那是另一件事）；
4. **默认值单源**：整集/重试两条端点支路不得再各自重述 `"1080p"` 这类字面量默认
   （AST 判 + **反向对照**，防「扫空即全绿」）；
5. **补列幂等**：把列从旧库删掉再开库，列被补回且能读写（走 store 既有的 PRAGMA 探测通道，
   不依赖异常吞 duplicate）。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from tests.ast_scan import parseSource

pytestmark = pytest.mark.timeout(60)

REPO = Path(__file__).resolve().parents[3]
_API_FILE = "neurova/api/endpoints/studio_api.py"


@pytest.fixture()
def store(tmp_path):
    from neurova.aigc_studio.store import StudioStore

    return StudioStore(db_path=str(tmp_path / "studio.db"))


@pytest.fixture()
def videoProbe(monkeypatch, tmp_path):
    """协议替身只记录「实际发出的规格」，断言打在出参上而非账面字段。"""
    from neurova.llm.generators import protocols as proto_mod
    from neurova.llm.generators import runtime as gen_runtime
    from neurova.llm.generators import task_ledger as ledger_mod
    from neurova.llm.generators.protocols import ProtocolCredentials
    from neurova.llm.generators.task_ledger import GenerationTaskLedger

    monkeypatch.setattr(ledger_mod, "_ledger",
                        GenerationTaskLedger(path=str(tmp_path / "led.json")))
    calls = []

    def fake_resolve(hint, model, provider_id, api_key, base_url, default_base):
        return ProtocolCredentials(api_key="k", base_url="https://x", model="m",
                                   protocol=hint)

    async def fake_submit(creds, prompt, **kw):
        calls.append({"resolution": kw.get("resolution"), "duration": kw.get("duration"),
                      "prompt": prompt})
        return {"task_id": "r1", "poll_url": "", "raw": {}}

    monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
    monkeypatch.setattr(proto_mod, "submit_video", fake_submit)
    return calls


def _episodeWithShot(store, tmp_path, withFrame=True):
    """一集一镜；首帧必须在盘——C1 的无首帧闸会先于规格逻辑拦下提交。"""
    project = store.create_project(owner_user_id="u1", title="规格继承",
                                   aspect_ratio="9:16")
    ep = store.add_episode(project["id"], {"number": 1, "title": "e"})
    sb = store.add_storyboard(ep["id"], {"number": 1, "video_prompt": "雨夜巷口对峙",
                                          "duration": 3})
    if withFrame:
        frame = tmp_path / f"frame_{sb['id']}.png"
        frame.write_bytes(b"IMG")
        store.update_storyboard(sb["id"], {"first_frame_path": str(frame)})
    return project, ep, sb


class TestShotRowRecordsSpec:
    def test_episode_run_stores_the_resolution_it_used(self, store, tmp_path, videoProbe):
        from neurova.aigc_studio import services

        project, ep, sb = _episodeWithShot(store, tmp_path)
        _run(services.generate_shot_videos(store, project["id"], ep["id"],
                                           resolution="720p"))
        assert [c["resolution"] for c in videoProbe] == ["720p"]
        assert store.get_storyboard(sb["id"])["video_resolution"] == "720p", \
            "提交时没把生效规格落到镜头行——重试时无处可查，规格就成了只存在于请求里的一次性参数"

    def test_stored_value_is_the_one_sent_not_the_requested_one(self, store, tmp_path, videoProbe):
        """行里落的必须是**实际发出**的那枚：服务商忽略该参数时不许把请求值抄成回执。"""
        from neurova.aigc_studio import services

        project, ep, sb = _episodeWithShot(store, tmp_path)
        _run(services.generate_shot_videos(store, project["id"], ep["id"],
                                           resolution="480p"))
        assert store.get_storyboard(sb["id"])["video_resolution"] == videoProbe[0]["resolution"]


class TestRetryInheritsRowSpec:
    def test_retry_without_params_reuses_the_rows_resolution(self, store, tmp_path, videoProbe):
        from neurova.aigc_studio import services

        project, ep, sb = _episodeWithShot(store, tmp_path)
        _run(services.generate_shot_videos(store, project["id"], ep["id"],
                                           resolution="720p"))
        # 重试支路：与 `retry_storyboard` 的 video 分支逐项同参，规格一个都不传
        videoProbe.clear()
        store.update_storyboard(sb["id"], {"video_status": "failed", "error": "上游超时"})
        _run(services.generate_shot_videos(store, project["id"], ep["id"],
                                           shot_ids=[sb["id"]]))
        assert videoProbe, "重试没走到提交，判据在演空转"
        assert videoProbe[0]["resolution"] == "720p", (
            f"同一镜头重试换了规格：发出 {videoProbe[0]['resolution']!r}，"
            "而这条镜头当初是 720p——用户点的是「重跑这一镜」，不是「换个尺寸重跑」")

    def test_duration_already_comes_from_the_row(self, store, tmp_path, videoProbe):
        """对照格：`duration` 早已镜头级同源，本批只补 resolution 那一半。"""
        from neurova.aigc_studio import services

        project, ep, sb = _episodeWithShot(store, tmp_path)
        _run(services.generate_shot_videos(store, project["id"], ep["id"]))
        assert videoProbe[0]["duration"] == 3, \
            "镜头行 duration=3 应优先于服务层兜底 5（这条本来就对，钉住它别被改坏）"

    def test_legacy_row_without_spec_uses_the_single_default(self, store, tmp_path, videoProbe):
        from neurova.aigc_studio import services
        from neurova.aigc_studio.services import DEFAULT_VIDEO_RESOLUTION

        project, ep, sb = _episodeWithShot(store, tmp_path)
        _run(services.generate_shot_videos(store, project["id"], ep["id"]))
        assert videoProbe[0]["resolution"] == DEFAULT_VIDEO_RESOLUTION, (
            "改造前的存量镜头（行内无规格）必须落那份唯一默认，行为与本批之前一致")


class TestNoSecondDefaultDefinition:
    """默认值只许在服务层一处；端点两条支路不得各自重述一遍。"""

    def _literals_in_endpoint(self):
        src = (REPO / _API_FILE).read_text(encoding="utf-8")
        found = []
        for node in ast.walk(parseSource(src)):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Attribute) \
                    and node.left.attr == "resolution":
                continue
            if isinstance(node, ast.keyword) and node.arg in ("resolution", "duration"):
                for sub in ast.walk(node.value):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                            and sub.value.endswith("p") and sub.value[:-1].isdigit():
                        found.append(f"line {node.lineno}: {sub.value}")
        return found

    def test_endpoint_has_no_hardcoded_resolution_default(self):
        offenders = self._literals_in_endpoint()
        assert not offenders, (
            f"{_API_FILE} 重述了规格字面量默认：{offenders}——「整集传 720p、重试落 1080p」"
            "的两份口径正是这样长出来的")

    def test_reverse_control_catches_a_restated_default(self):
        """反向对照：判据不是摆设——把字面量塞回去必须报红（防扫空即全绿）。"""
        src = ('def f(b):\n    return g(resolution=str(b.get("resolution") or "1080p"))\n')
        found = []
        for node in ast.walk(parseSource(src)):
            if isinstance(node, ast.keyword) and node.arg == "resolution":
                for sub in ast.walk(node.value):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                            and sub.value.endswith("p") and sub.value[:-1].isdigit():
                        found.append(sub.value)
        assert found == ["1080p"], f"扫描器抓不到端点重述的默认值：{found}"


class TestColumnMigration:
    def test_column_is_added_idempotently_to_old_db(self, tmp_path):
        """旧库（无该列）再开一次要补回来——走 store 既有的 PRAGMA 探测幂等通道。"""
        import sqlite3

        from neurova.aigc_studio.store import StudioStore

        db = str(tmp_path / "old.db")
        s = StudioStore(db_path=db)
        s.close()
        conn = sqlite3.connect(db)
        conn.execute("ALTER TABLE storyboards DROP COLUMN video_resolution")
        conn.commit()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(storyboards)")}
        conn.close()
        assert "video_resolution" not in cols

        reopened = StudioStore(db_path=db)
        cols2 = {r["name"] for r in reopened._conn.execute("PRAGMA table_info(storyboards)")}
        assert "video_resolution" in cols2, "旧库补列通道没覆盖这一列"
        project = reopened.create_project(owner_user_id="u1", title="旧库")
        ep = reopened.add_episode(project["id"], {"number": 1, "title": "e"})
        row = reopened.add_storyboard(ep["id"], {"number": 1, "prompt": "p"})
        reopened.update_storyboard(row["id"], {"video_resolution": "720p"})
        assert reopened.get_storyboard(row["id"])["video_resolution"] == "720p"
        reopened.close()


def _run(coro):
    import asyncio

    return asyncio.run(coro)
