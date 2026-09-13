# -*- coding: utf-8 -*-
"""配置契约单源生成 + 防漂移守卫（Yuxi 对比 P2 #15）。

对位 Yuxi `get_query_params_config`（dataclass metadata 反射出表单/参数契约
单源）。Neurova 历次键位契约漂移事故（睡眠设置键位/负一屏公共字段丢弃/
ChannelIntegration 不回填）共同根因=前后端各写各的字段清单。

本批增量：`form_options(model_cls)` 从 pydantic 字段（title/description/
json_schema_extra）单源生成表单描述；负一屏域接入（GET 响应附 schema 字段，
裸对象契约加性不破坏）；**防漂移契约测试**：前端 API 模块 TS interface
字段集必须是后端 schema 键集的子集（新键前端未接 = 红）。
"""
import re
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from neurova.core.config_schema import form_options


class SampleModel(BaseModel):
    enabled: bool = Field(False, title="是否启用", description="总开关")
    push_url: str = Field("", title="推送 URL")
    auth_code: str = Field("", title="授权码", json_schema_extra={"secret": True})
    retries: int = 3
    maybe_none: str | None = None


def test_form_options_single_source():
    opts = {o["key"]: o for o in form_options(SampleModel)}
    assert set(opts) == {"enabled", "push_url", "auth_code", "retries", "maybe_none"}
    assert opts["enabled"]["type"] == "boolean" and opts["enabled"]["default"] is False
    assert opts["enabled"]["label"] == "是否启用"
    assert opts["enabled"]["description"] == "总开关"
    assert opts["auth_code"]["secret"] is True
    assert opts["auth_code"]["label"] == "授权码"
    assert opts["push_url"]["required"] is False
    assert opts["retries"]["type"] == "integer" and opts["retries"]["default"] == 3
    assert opts["maybe_none"]["type"] == "string"


def test_form_options_empty_model():
    class Empty(BaseModel):
        pass

    assert form_options(Empty) == []


def test_nipscreen_update_model_schema():
    """端点模型接入单源（GET 响应 schema 字段的数据源）。"""
    from neurova.api.endpoints.negative_screen_settings import UpdateNegativeScreenConfigRequest

    opts = form_options(UpdateNegativeScreenConfigRequest)
    keys = {o["key"] for o in opts}
    assert {"auth_code", "enabled", "push_url"} <= keys
    secret = [o for o in opts if o["key"] == "auth_code"][0]
    assert secret["secret"] is True, "授权码必须标记 secret（前端不得回填明文）"


def test_frontend_negscreen_keys_are_subset_of_backend_schema():
    """防漂移钉：negative-screen.ts 的 Update 接口字段 ⊆ 后端 schema 键集。
    （i18n locale guard 同族模式：从源文件解析，缺键即红）"""
    ts_path = (
        Path(__file__).resolve().parents[3]
        / "NeurUI" / "src" / "api" / "modules" / "negative-screen.ts"
    )
    assert ts_path.exists(), f"前端契约文件失踪: {ts_path}"
    src = ts_path.read_text(encoding="utf-8")
    m = re.search(r"export interface UpdateNegativeScreenConfig \{(.*?)\}", src, re.S)
    assert m, "前端 Update 接口改名/删除——契约面已漂移，同步更新本钉"
    fe_keys = set(re.findall(r"^\s*(\w+)\??\s*:", m.group(1), re.M))
    from neurova.api.endpoints.negative_screen_settings import UpdateNegativeScreenConfigRequest

    be_keys = {o["key"] for o in form_options(UpdateNegativeScreenConfigRequest)}
    missing = fe_keys - be_keys
    assert not missing, f"前端提交了后端不认识的键（单源违例）: {missing}"
