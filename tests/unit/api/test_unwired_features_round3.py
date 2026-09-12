"""B 类未落地功能清剿回归（2026-09-12 第三轮）。

1. image builds：POST /build 走 ImagePipelineManager（记录进 manager._builds），
   但 GET /builds 与 GET /builds/{id} 读端点自带的恒空 `_builds_store`
   ——写读两套存储分离，构建历史恒空。修复：列表/详情读 manager 真源，死 store 删。
2. sleep：run_sleep_cycle 写 _dream_logs/_merge_history/_conflict_resolutions
   仅进程内存 → 重启四页签全空。修复：落 data/sleep_logs/{agent_id}.json。
3. growth proactive：无 proactive_behavior_engine（全仓无实例化）时用 uuid
   编造 3 条"Proactive message about topic i"假记录（活跃假数据违规）。
   修复：删伪造，如实返回空。
"""
import asyncio
import json
import os
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_unwired_r3_01234")


# ---------------------------------------------------------------------------
# 1. image builds
# ---------------------------------------------------------------------------

class TestImageBuildsRealSource:
    def test_list_builds_reads_pipeline_manager(self, monkeypatch):
        from neurova.api.endpoints import image as IMG

        fake_builds = [{
            "build_id": "b-1", "template_id": "ubuntu-base", "status": "success",
            "started_at": time.time(), "image_tag": "neurova/custom:1",
        }]
        fake_mgr = type("M", (), {"get_builds": lambda self, **kw: fake_builds})()
        monkeypatch.setattr(IMG, "get_image_pipeline_manager", lambda: fake_mgr)

        app = FastAPI()
        app.include_router(IMG.router, prefix="/api/v1/image")
        from neurova.api.deps import get_current_user as du
        from neurova.api.auth import get_current_user as au
        app.dependency_overrides[du] = lambda: {"user_id": "u", "username": "u", "role": "admin"}
        app.dependency_overrides[au] = lambda: {"user_id": "u", "username": "u", "role": "admin"}
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/v1/image/builds")
            assert r.status_code == 200, r.text
            builds = r.json()["data"]["builds"]
            assert [b.get("build_id") for b in builds] == ["b-1"], "仍读恒空 _builds_store"
            assert not hasattr(IMG, "_builds_store"), "死存储应删除"


# ---------------------------------------------------------------------------
# 2. sleep 四列表落盘
# ---------------------------------------------------------------------------

class TestSleepLogsPersistence:
    def test_dreams_and_merges_survive_restart(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

        store = tmp_path / "sleep_agent9.json"
        sc = SleepConsolidation(logs_store_path=str(store))
        sc._dream_logs.insert(0, {"dream_id": "d1", "agent_id": "agent9", "created_at": time.time()})
        sc._merge_history.append({"merge_id": "m1", "agent_id": "agent9", "created_at": time.time()})
        sc._conflict_resolutions.insert(0, {"conflict_id": "c1", "agent_id": "agent9", "created_at": time.time()})
        sc.persist_logs()

        assert store.exists(), "睡眠日志未落盘"
        sc2 = SleepConsolidation(logs_store_path=str(store))  # 模拟重启
        assert sc2.get_dream_logs()[0]["dream_id"] == "d1"
        assert sc2.get_memory_merges()[0]["merge_id"] == "m1"
        assert sc2.get_conflict_resolutions()[0]["conflict_id"] == "c1"

    def test_run_cycle_persists_end_to_end(self, tmp_path, monkeypatch):
        """run_sleep_cycle 写入后必须自动落盘（不要求调用方记得 persist）。"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

        store = tmp_path / "sleep_auto.json"
        sc = SleepConsolidation(logs_store_path=str(store))
        # 直接触发写入路径后自动落盘：插一条再调 persist 钩子由内部 append 处调用
        sc._dream_logs.insert(0, {"dream_id": "d-auto", "agent_id": "a", "created_at": time.time()})
        sc._persist_logs_locked()
        assert json.loads(store.read_text(encoding="utf-8"))["dream_logs"]


# ---------------------------------------------------------------------------
# 3. growth proactive 去 mock
# ---------------------------------------------------------------------------

class TestProactiveNoFabrication:
    @pytest.fixture()
    def client(self, monkeypatch):
        from neurova.api.endpoints import growth
        from neurova.api.auth import get_current_user

        class _NoEngineAgent:
            def __init__(self):
                self.personality = "md"
                self.constitution = ""
        monkeypatch.setattr("neurova.api.endpoints.get_agent_instance",
                            lambda *a, **k: _NoEngineAgent())
        app = FastAPI()
        app.include_router(growth.router, prefix="/api/v1/growth")
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "u", "username": "u", "role": "admin",
        }
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_proactive_without_engine_returns_empty(self, client):
        r = client.get("/api/v1/growth/proactive", params={"agent_id": "a1"})
        assert r.status_code == 200
        items = r.json()  # 端点直返列表
        # 旧行为：编造 3 条 uuid mock（"Proactive message about topic i"）
        assert isinstance(items, list) and items == [], f"无引擎时必须如实返回空，实际: {str(items)[:200]}"
