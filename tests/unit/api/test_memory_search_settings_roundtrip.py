"""MemorySearchSettingsPage 保存假成功/回读错位修复回归（2026-09-12 空数据页面排查）。

根因:
- GET /enhanced-memory-search/settings 返回扁平硬编码 search_method/top_k/score_threshold
  （前端从不消费），而前端读写嵌套 {search,decay,enhancement} → search/enhancement 整段
  保存被 PUT 丢弃，刷新即回默认；
- PUT 只映射 decay 三键且按 0-1 校验，前端滑杆 0-100 → 值恒越界被 settings_config.update()
  静默跳过，端点仍回 code 0 "Updated 0"（假成功）。

修复契约:
- GET/PUT 对称嵌套 {search:{method,top_k,score_threshold}, decay:{enabled,rate,
  half_life_days,min_score}, enhancement:{enabled,boost_factor,recency_weight,
  frequency_weight}}，API 边界单位 = 前端滑杆单位（百分制/天数/1-10），
  rate/min_score/score_threshold 存储时换算为 0-1；
- decay.rate→temperature.decay_rate、decay.half_life_days→auto_context.compression_threshold_days、
  decay.min_score→threshold.default（真实消费键，mem_core 激活阈值/衰减曲线）；
  其余 search/enhancement/enabled 落 data/memory_search_ui_settings.json（预留位，重启可回读）；
- 越界/非法枚举 → 422（不再"Updated 0"假成功）。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_mssettings_0123456")

from neurova.api.deps import get_current_user
from neurova.api.endpoints import enhanced_memory_search_api as EMS
from neurova.cognitive_layers.memory_layer.settings_config import MemorySettingsConfig

MOCK_ADMIN = {"user_id": "a1", "username": "admin1", "role": "admin"}


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """memory-settings 与 UI 设置文件全部重定向 tmp_path（禁打真实 data/）。"""
    MemorySettingsConfig.reset_instance()
    MemorySettingsConfig.get_instance(data_dir=str(tmp_path))
    monkeypatch.setattr(EMS, "_UI_FILE", str(tmp_path / "memory_search_ui_settings.json"))
    yield tmp_path
    MemorySettingsConfig.reset_instance()


@pytest.fixture()
def client(isolated):
    app = FastAPI()
    app.include_router(EMS.router, prefix="/api/v1/enhanced-memory-search")
    app.dependency_overrides[get_current_user] = lambda: MOCK_ADMIN
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


class TestReadContract:
    def test_get_returns_nested_shape(self, client):
        r = client.get("/api/v1/enhanced-memory-search/settings")
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert set(d) >= {"search", "decay", "enhancement"}
        assert set(d["search"]) == {"method", "top_k", "score_threshold"}
        assert set(d["decay"]) == {"enabled", "rate", "half_life_days", "min_score"}
        assert set(d["enhancement"]) == {"enabled", "boost_factor", "recency_weight", "frequency_weight"}

    def test_get_defaults_in_slider_units(self, client):
        d = client.get("/api/v1/enhanced-memory-search/settings").json()["data"]
        assert d["search"]["method"] == "hybrid"
        assert d["decay"]["rate"] == pytest.approx(10)   # 存储 0.1 → 百分制 10
        assert d["decay"]["min_score"] == pytest.approx(30)  # threshold.default 0.3
        assert d["decay"]["half_life_days"] == 30


class TestSaveRoundTrip:
    def test_put_then_get_roundtrip(self, client):
        body = {
            "search": {"method": "vector", "top_k": 7, "score_threshold": 42},
            "decay": {"enabled": False, "rate": 25, "half_life_days": 45, "min_score": 15},
            "enhancement": {"enabled": False, "boost_factor": 3, "recency_weight": 70, "frequency_weight": 30},
        }
        r = client.put("/api/v1/enhanced-memory-search/settings", json=body)
        assert r.status_code == 200, r.text
        d = client.get("/api/v1/enhanced-memory-search/settings").json()["data"]
        assert d == {
            "search": {"method": "vector", "top_k": 7, "score_threshold": 42},
            "decay": {"enabled": False, "rate": 25, "half_life_days": 45, "min_score": 15},
            "enhancement": {"enabled": False, "boost_factor": 3, "recency_weight": 70, "frequency_weight": 30},
        }

    def test_decay_lands_in_real_consumer_keys(self, client):
        client.put("/api/v1/enhanced-memory-search/settings", json={
            "decay": {"rate": 25, "half_life_days": 45, "min_score": 15},
        })
        cfg = MemorySettingsConfig.get_instance()
        assert cfg.get("temperature.decay_rate") == pytest.approx(0.25)
        assert cfg.get("auto_context.compression_threshold_days") == 45
        assert cfg.get("threshold.default") == pytest.approx(0.15)

    def test_survives_restart(self, client):
        client.put("/api/v1/enhanced-memory-search/settings", json={
            "search": {"method": "bm25", "top_k": 9},
        })
        # 模拟重启：内存单例清空，从 JSON 文件重载
        MemorySettingsConfig.reset_instance()
        r = client.get("/api/v1/enhanced-memory-search/settings")
        d = r.json()["data"]
        assert d["search"]["method"] == "bm25"
        assert d["search"]["top_k"] == 9


class TestHonestValidation:
    def test_percent_scale_rejected(self, client):
        """旧 bug：滑杆 0-100 当 0-1 写 → 静默跳过假成功。现按滑杆单位收，
        真正越界（>100）必须 422，不得 code 0。"""
        r = client.put("/api/v1/enhanced-memory-search/settings", json={
            "decay": {"rate": 150},
        })
        assert r.status_code == 422

    def test_bad_method_enum_rejected(self, client):
        r = client.put("/api/v1/enhanced-memory-search/settings", json={
            "search": {"method": "magic"},
        })
        assert r.status_code == 422

    def test_partial_update_keeps_other_sections(self, client):
        client.put("/api/v1/enhanced-memory-search/settings", json={
            "search": {"method": "vector"},
        })
        d = client.get("/api/v1/enhanced-memory-search/settings").json()["data"]
        assert d["search"]["method"] == "vector"
        assert d["search"]["top_k"] == 10  # 默认保留
        assert d["enhancement"]["boost_factor"] == 2
