# -*- coding: utf-8 -*-
"""视频收口不该等"有人来 GET"（§6-78 的 A 条，H2-1a）。

现场事实（逐条复核过）：

- 收口循环 `recovery.py` 只写任务账本（`:68/73/77/82/85` 全是 `ledger.update(...)`），
  **全文零 `update_storyboard`**；
- 镜头行被回填的唯一入口是 `GET /api/v1/studio/episodes/{eid}` 里的一次
  `_backfill_video_status`（定义 `studio_api.py:245`，全仓唯一调用点 `:277`）。

于是"这条镜头跑完了"这件事只存在于账本，投影面要等有人来看才更新。补链的形态是：
把映射搬到 studio 层的一处实现，让它既有 HTTP 那一个消费者，也有服务端周期驱动这一个。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from neurova.aigc_studio.store import StudioStore
from tests.ast_scan import parseSource

pytestmark = pytest.mark.timeout(60)

REPO = Path(__file__).resolve().parents[3]


def _seedRunningShot(store, tmp_path, monkeypatch, *, succeeded=True, withArtifact=True):
    """真账本 + 真镜头行：一条"视频已跑完但没人来读"的状态。"""
    from neurova.llm.generators import task_ledger as ledger_mod
    from neurova.llm.generators.task_ledger import GenerationTaskLedger, TaskRecord

    # 进程级单例必须走 monkeypatch 归还（直接写 `_ledger=` 会把假账本漏给后续用例）
    led = GenerationTaskLedger(path=str(tmp_path / "led.json"))
    monkeypatch.setattr(ledger_mod, "_ledger", led)
    art = None
    if withArtifact:
        art = tmp_path / "v.mp4"
        art.write_bytes(b"M")
    project = store.create_project("u1", title="收口测试")
    ep = store.add_episode(project["id"], {"number": 1, "title": "e"})
    task = led.add(TaskRecord(
        kind="video", status="succeeded" if succeeded else "failed",
        local_path=str(art) if art else "", remote_task_id="r1",
        error="" if succeeded else "上游报失败"))
    sb = store.add_storyboard(ep["id"], {
        "number": 1, "video_status": "running", "ledger_task_id": task.task_id})
    return project, ep, sb


class TestReconcileConvergesWithoutAReader:
    def test_reconcileEpisodeConvergesTheRowWithNoHttp(self, tmp_path, monkeypatch):
        """服务端自己就能收敛——这一档不调任何端点。"""
        from neurova.aigc_studio.video_reconcile import reconcileEpisode

        store = StudioStore(db_path=str(tmp_path / "s.db"))
        _project, ep, sb = _seedRunningShot(store, tmp_path, monkeypatch)

        reconcileEpisode(store, ep["id"])

        row = store.get_storyboard(sb["id"])
        assert row["video_status"] == "done", f"没人 GET 就不收敛：{row}"
        assert row["video_path"].endswith("v.mp4"), row

    def test_reconcileRunningEpisodesFindsThemItself(self, tmp_path, monkeypatch):
        """不需要调用方报 eid：全库扫"有在跑的视频"的分集并逐集收敛。"""
        from neurova.aigc_studio.video_reconcile import reconcileRunningEpisodes

        store = StudioStore(db_path=str(tmp_path / "s.db"))
        _project, ep, sb = _seedRunningShot(store, tmp_path, monkeypatch)

        touched = reconcileRunningEpisodes(store)
        assert touched >= 1, "服务端驱动器一条都没处理——等于没接线"
        row = store.get_storyboard(sb["id"])
        assert row["video_status"] == "done", row

    def test_failedTaskConvergesToFailedNotSilentlySkipped(self, tmp_path, monkeypatch):
        from neurova.aigc_studio.video_reconcile import reconcileRunningEpisodes

        store = StudioStore(db_path=str(tmp_path / "s.db"))
        _project, _ep, sb = _seedRunningShot(store, tmp_path, monkeypatch,
                                             succeeded=False, withArtifact=False)

        reconcileRunningEpisodes(store)
        row = store.get_storyboard(sb["id"])
        assert row["video_status"] == "failed", row
        assert "上游报失败" in (row["error"] or ""), row

    def test_danglingLedgerTaskDoesNotHangForever(self, tmp_path, monkeypatch):
        """账本行取不到时必须诚实收尾（§6-78 的 C 条同根，这里先钉住形态）。

        改前是 `continue`：镜头永远停在 running，而重跑又被 running 闸门拒绝——
        既收不了口也重新提交不了。
        """
        from neurova.llm.generators import task_ledger as ledger_mod
        from neurova.aigc_studio.video_reconcile import reconcileRunningEpisodes

        store = StudioStore(db_path=str(tmp_path / "s.db"))
        _project, _ep, sb = _seedRunningShot(store, tmp_path, monkeypatch)
        # 换成一个空账本：那条 ledger_task_id 现在指向不存在的行
        monkeypatch.setattr(ledger_mod, "_ledger",
                            ledger_mod.GenerationTaskLedger(path=str(tmp_path / "other.json")))

        reconcileRunningEpisodes(store)
        row = store.get_storyboard(sb["id"])
        assert row["video_status"] != "running", (
            f"账本行丢了就永远停在 running：{row}")


class TestMappingHasOneImplementation:
    """映射只许一处：**按 import 归属判**，不按字面量计数。

    第一版写成"全仓 `video_status` 字面量只许出现在一处"，当场被证伪为假红——
    提交侧本来就有权写 `"running"`（`services.py:418`）、白名单也合法地接受这两个键
    （`studio_api.py:322`）。真正的断言是：**终态收敛这件事**不再由端点自己做。
    """

    def testEndpointNoLongerOwnsTheConvergenceMapping(self):
        source = (REPO / "neurova" / "api" / "endpoints" / "studio_api.py").read_text(
            encoding="utf-8")
        tree = parseSource(source)
        # 端点里"由账本推终态"这两件事都不该再出现：读账本、按 `succeeded` 收敛镜头
        readsLedger = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module and n.module.endswith("task_ledger")
        ]
        assert not readsLedger, (
            f"studio_api 还自己读任务账本（{len(readsLedger)} 处 import）："
            "收敛映射的第二份实现留在端点里，服务端驱动器与 HTTP 投影迟早漂成两种读数"
        )
        assert "def _backfill_video_status" not in source, (
            "端点仍持有那份 `_backfill_video_status` 实现——接线没做完"
        )

    def testStoryboardsStillOwnTheirSubmitSideLiterals(self):
        """反向对照：提交侧写 running 是它的工作，守卫不许把它一起判红。"""
        services = (REPO / "neurova" / "aigc_studio" / "services.py").read_text(
            encoding="utf-8")
        assert 'video_status": "running"' in services or "video_status\": \"running\"" in services


class TestSweepIsWiredIntoLifespan:
    """写了要有人驱动（与 D 批 §6-69 同一形态）：周期体必须挂在 lifespan 上，成对启停。"""

    def testAppLifespanStartsAndStopsTheSweep(self):
        source = (REPO / "neurova" / "api" / "app.py").read_text(encoding="utf-8")
        assert "startReconcileSweep" in source and "stopReconcileSweep" in source, (
            "app.py 没挂点：驱动器只是又一个写了没人读的模块"
        )
        assert source.index("stopReconcileSweep") > source.index("startReconcileSweep"), (
            "启停不成对：常驻 task 会拖住 TestClient 的 teardown"
        )
        # 顺带钉住 D 批那条钩子没被我这次插入顶掉（改前我用整段替换写法误删过一次）
        assert "startStaleSweep" in source and "stopStaleSweep" in source, (
            "AgentRun 租约扫描的 lifespan 钩子不见了"
        )

    def testStartRefusesWithoutARunningLoop(self, tmp_path):
        """无运行循环时如实回 False——不许假报"已在跑"。"""
        from neurova.aigc_studio.video_reconcile import startReconcileSweep

        store = StudioStore(db_path=str(tmp_path / "s.db"))
        assert startReconcileSweep(store) is False
