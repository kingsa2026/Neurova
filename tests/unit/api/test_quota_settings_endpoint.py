# -*- coding: utf-8 -*-
"""quota section 的设置面契约（2026-11-14 LLM 日配额运营化）。

- PUT /v1/settings {"quota": {...}} 持久化到 app_settings 的 quota section；
- 非法值（非 int / <1 / 未知键）400 诚实拒收，不落盘——落盘后被管理器
  静默回落默认，运营会以为改成功了；
- GET /v1/settings 回显合并后的 quota（未配置键回落默认）；
- 单键 PUT /v1/settings/quota 400（section 必须走整表 PUT，与其它 section 同口径）。
"""
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_quota_0123456789")

from neurova.api.endpoints import settings as SETTINGS
from neurova.core import app_settings as APPS
from tests.auth_headers import overrideIdentity

ADMIN = {"user_id": "a1", "username": "a1", "role": "admin"}


@pytest.fixture()
def settings_client(tmp_path, monkeypatch):
    monkeypatch.setattr(APPS, "_settings_path", lambda path=None: tmp_path / "app_settings.json")
    app = FastAPI()
    app.include_router(SETTINGS.router, prefix="/api")
    overrideIdentity(app, dict(ADMIN))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, tmp_path
    app.dependency_overrides.clear()


class TestQuotaSettingsEndpoint:
    def test_put_quota_section_persists_and_reads_back(self, settings_client):
        c, tmp = settings_client
        r = c.put("/api/v1/settings", json={"settings": {"quota": {"max_llm_calls_per_day": 500}}})
        assert r.status_code == 200, r.text
        saved = json.loads((tmp / "app_settings.json").read_text(encoding="utf-8"))
        assert saved["quota"]["max_llm_calls_per_day"] == 500
        quota = c.get("/api/v1/settings").json()["settings"]["quota"]
        assert quota["max_llm_calls_per_day"] == 500
        assert quota["max_llm_tokens_per_day"] == 100_000  # 未配置键回落默认

    def test_put_quota_invalid_value_rejected_without_persisting(self, settings_client):
        c, tmp = settings_client
        r = c.put("/api/v1/settings", json={"settings": {"quota": {"max_llm_calls_per_day": -1}}})
        assert r.status_code == 400
        f = tmp / "app_settings.json"
        assert not f.exists() or "quota" not in json.loads(f.read_text(encoding="utf-8"))

    def test_put_quota_unknown_key_rejected(self, settings_client):
        c, _ = settings_client
        r = c.put("/api/v1/settings", json={"settings": {"quota": {"no_such_quota": 5}}})
        assert r.status_code == 400

    def test_put_quota_non_int_rejected(self, settings_client):
        c, _ = settings_client
        r = c.put("/api/v1/settings", json={"settings": {"quota": {"max_llm_calls_per_day": "很多"}}})
        assert r.status_code == 400

    def test_single_key_quota_rejected(self, settings_client):
        c, _ = settings_client
        r = c.put("/api/v1/settings/quota", json={"value": {"max_llm_calls_per_day": 500}})
        assert r.status_code == 400

    def test_get_merged_contains_quota_defaults(self, settings_client):
        c, _ = settings_client
        quota = c.get("/api/v1/settings").json()["settings"]["quota"]
        assert quota["max_llm_calls_per_day"] == 100
        assert quota["max_llm_tokens_per_day"] == 100_000
