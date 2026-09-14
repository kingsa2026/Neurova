# -*- coding: utf-8 -*-
"""L4：AIGC 用量统计闭环（图像入账 → summary 聚合 → /generation/usage 契约）。"""
from __future__ import annotations

import pytest

from neurova.core.aigc_usage import AigcUsageHistory

pytestmark = pytest.mark.timeout(60)


@pytest.fixture()
def usage(tmp_path):
    u = AigcUsageHistory(db_path=str(tmp_path / "aigc.db"))
    yield u
    u.close()


class TestUsageLedger:
    def test_record_and_summary(self, usage):
        usage.record(kind="image", user_id="u1", model="seedream", protocol="ark",
                     status="success", items=2, duration_ms=1500)
        usage.record(kind="video", user_id="u1", status="failed", items=0)
        usage.record(kind="image", user_id="u2", status="success", items=1)

        s = usage.summary(user_id="u1", days=7)
        assert s["days"] == 7
        kinds = {(row["kind"], row["status"]): row for row in s["totals"]}
        assert kinds[("image", "success")]["items"] == 2
        assert kinds[("video", "failed")]["calls"] == 1
        # 属主隔离：u2 不在 u1 视图（daily 按 日期×kind×status 分组=2 行）
        assert len(s["daily"]) == 2
        s_all = usage.summary(user_id=None, days=7)
        assert sum(t["items"] for t in s_all["totals"]) == 3

    def test_summary_empty_on_fresh_db(self, tmp_path):
        u = AigcUsageHistory(db_path=str(tmp_path / "fresh.db"))
        assert u.summary() == {"daily": [], "totals": [], "days": 30}
        u.close()

    def test_record_never_raises(self, tmp_path):
        # db 路径被普通文件遮挡（mkdir 必然失败）：record/summary 静默回退
        blocked = tmp_path / "blocked"
        blocked.write_text("x")
        u = AigcUsageHistory(db_path=str(blocked / "nested" / "x.db"))
        u.record(kind="image", user_id="u1")  # 不抛
        assert u.summary() == {"daily": [], "totals": [], "days": 30}


class TestEndpointIntegration:
    def test_image_generates_usage_row(self, tmp_path, monkeypatch):
        """/image 成功与失败均入账（经 _ledger_add 单点）"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.endpoints import generation as gen_ep
        from neurova.core import aigc_usage as au
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators import task_ledger as ledger_mod
        from neurova.llm.generators.protocols import ProtocolCredentials
        from neurova.llm.generators.task_ledger import GenerationTaskLedger

        db = au.AigcUsageHistory(db_path=str(tmp_path / "usage.db"))
        monkeypatch.setattr(au, "_instance", db)
        monkeypatch.setattr(ledger_mod, "_ledger",
                            GenerationTaskLedger(path=str(tmp_path / "led.json")))

        app = FastAPI()
        app.include_router(gen_ep.router, prefix="/api/v1/generation")
        from neurova.api.deps import get_current_user as _gcu
        app.dependency_overrides[_gcu] = lambda: {
            "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser"}
        monkeypatch.setattr(gen_ep, "_GENERATION_OUTPUT_DIR", str(tmp_path))
        client = TestClient(app)

        monkeypatch.setattr(
            gen_runtime, "resolve_generation_creds",
            lambda *a, **k: ProtocolCredentials(api_key="k", base_url="https://x",
                                                model="flux", protocol="openai_compat"))

        async def fake_gen(creds, prompt, **kw):
            return {"images": ["http://cdn/a.png"], "task_id": None, "raw": {}}

        async def fake_persist(url, kind, task_id, index, out_dir=None):
            p = tmp_path / "a.png"
            p.write_bytes(b"P")
            return str(p)

        monkeypatch.setattr(proto_mod, "generate_image", fake_gen)
        monkeypatch.setattr(gen_runtime, "persist_media", fake_persist)
        assert client.post("/api/v1/generation/image", json={"prompt": "猫"}).status_code == 200

        async def boom(creds, prompt, **kw):
            raise RuntimeError("上游炸了")

        monkeypatch.setattr(proto_mod, "generate_image", boom)
        assert client.post("/api/v1/generation/image", json={"prompt": "猫"}).status_code == 502

        summary = db.summary()
        by_status = {(r["kind"], r["status"]): r for r in summary["totals"]}
        assert by_status[("image", "success")]["items"] == 1
        assert by_status[("image", "failed")]["calls"] == 1

        # /usage 端点契约
        r = client.get("/api/v1/generation/usage?days=7")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["days"] == 7 and data["totals"]
        monkeypatch.setattr(au, "_instance", None)
        db.close()
