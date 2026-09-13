# -*- coding: utf-8 -*-
"""rerank 模型通道生产装配（Yuxi 对比 P0-3）。

根因：Dify 对标轮把 ModelRerankRunner/factory 全写好了，但唯一生产入口
`semantic_search_api._resolve_rerank_provider` 是恒 None 占位（"声明未接线"
台账惯犯）；且 Yuxi 的反面教训——重排失败不得静默伪装成加权/空结果。

契约：
- neurova/llm/rerank_client.build_rerank_provider(model)：从 provider_manager
  解析 OpenAI 兼容 /rerank 端点，返回 (query, texts)->scores 的 callable
- 错误显式分型：RerankConfigError(not_configured/...) vs
  RerankBackendError(kind=network|http|contract)
- _build_rerank_runner 返回 (runner, label, note)：模型通道不可用时
  退化加权但 note 必须携带原因（响应体可见，不静默）
- ModelRerankRunner.last_error：provider 调用失败退化时记录原因
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from neurova.knowledge.rerank import ModelRerankRunner
from neurova.llm import rerank_client as rc
from neurova.llm.provider_manager import ProviderConfig


def _manager(*providers):
    return SimpleNamespace(list_providers=lambda: list(providers))


@pytest.fixture()
def sf_manager():
    return _manager(
        ProviderConfig(
            id="siliconflow",
            name="硅基流动",
            provider="openai",
            base_url="https://api.siliconflow.cn/v1",
            api_key="sk-test-1234567890",
            models=["BAAI/bge-reranker-v2-m3", "Qwen/Qwen3-8B"],
            model_metadata={
                "BAAI/bge-reranker-v2-m3": {"capabilities": ["rerank"]},
                "Qwen/Qwen3-8B": {"capabilities": ["text", "reasoning"]},
            },
        ),
        ProviderConfig(
            id="off",
            name="死渠道",
            provider="openai",
            base_url="https://off.example/v1",
            models=["off/reranker"],
            enabled=False,
        ),
    )


# ── build_rerank_provider 解析链 ───────────────────────────────────

def test_build_provider_by_name(sf_manager):
    provider = rc.build_rerank_provider("BAAI/bge-reranker-v2-m3", manager=sf_manager)
    assert callable(provider)


def test_build_provider_unknown_name_raises_typed(sf_manager):
    with pytest.raises(rc.RerankConfigError) as ei:
        rc.build_rerank_provider("no/such-reranker", manager=sf_manager)
    assert "not_configured" in ei.value.reason


def test_build_provider_disabled_channel_not_used(sf_manager):
    with pytest.raises(rc.RerankConfigError):
        rc.build_rerank_provider("off/reranker", manager=sf_manager)


def test_default_model_discovered_by_capability(sf_manager):
    assert rc.find_rerank_model(manager=sf_manager) == "BAAI/bge-reranker-v2-m3"
    provider = rc.build_rerank_provider("", manager=sf_manager)  # 空名走能力发现
    assert callable(provider)


def test_default_model_none_when_unconfigured():
    manager = _manager(
        ProviderConfig(id="p", name="p", provider="openai", base_url="https://x/v1",
                       models=["a/b"], model_metadata={"a/b": {"capabilities": ["text"]}})
    )
    assert rc.find_rerank_model(manager=manager) is None
    with pytest.raises(rc.RerankConfigError):
        rc.build_rerank_provider("", manager=manager)


# ── HTTP 协议与错误分型 ────────────────────────────────────────────

def _resp(payload, status_code=200):
    return httpx.Response(status_code=status_code, json=payload,
                          request=httpx.Request("POST", "https://api.example/v1/rerank"))


def test_provider_request_contract_and_score_order(sf_manager):
    provider = rc.build_rerank_provider("BAAI/bge-reranker-v2-m3", manager=sf_manager)
    captured = {}

    def fake_post(url, **kw):
        captured["url"] = url
        captured.update(kw)
        # 故意乱序返回，客户端须按 index 还原候选序
        return _resp({"results": [{"index": 1, "relevance_score": 0.9},
                                  {"index": 0, "relevance_score": 0.1}]})

    with patch.object(httpx, "post", side_effect=fake_post):
        scores = provider("查询", ["doc0", "doc1"])
    assert scores == [0.1, 0.9]
    assert captured["url"].endswith("/rerank")
    assert captured["json"]["model"] == "BAAI/bge-reranker-v2-m3"
    assert captured["json"]["query"] == "查询"
    assert captured["json"]["documents"] == ["doc0", "doc1"]
    assert captured["headers"]["Authorization"] == "Bearer sk-test-1234567890"


def test_provider_network_error_typed(sf_manager):
    provider = rc.build_rerank_provider("BAAI/bge-reranker-v2-m3", manager=sf_manager)
    with patch.object(httpx, "post", side_effect=httpx.ConnectError("boom")):
        with pytest.raises(rc.RerankBackendError) as ei:
            provider("q", ["d"])
    assert ei.value.kind == "network"


def test_provider_http_error_typed(sf_manager):
    provider = rc.build_rerank_provider("BAAI/bge-reranker-v2-m3", manager=sf_manager)
    with patch.object(httpx, "post", return_value=_resp({"error": "quota"}, status_code=403)):
        with pytest.raises(rc.RerankBackendError) as ei:
            provider("q", ["d"])
    assert ei.value.kind == "http"
    assert "403" in str(ei.value)


def test_provider_contract_error_typed(sf_manager):
    provider = rc.build_rerank_provider("BAAI/bge-reranker-v2-m3", manager=sf_manager)
    # 3 个候选只回 2 个分数 → 坏契约
    with patch.object(httpx, "post", return_value=_resp(
        {"results": [{"index": 0, "relevance_score": 0.5}, {"index": 1, "relevance_score": 0.4}]}
    )):
        with pytest.raises(rc.RerankBackendError) as ei:
            provider("q", ["a", "b", "c"])
    assert ei.value.kind == "contract"


# ── 端点装配层：不静默降级 ─────────────────────────────────────────

def test_runner_label_model_when_resolved(sf_manager):
    from neurova.api.endpoints import semantic_search_api as ssa

    with patch.object(rc, "get_provider_manager", return_value=sf_manager):
        runner, label, note = ssa._build_rerank_runner(
            {"method": "model", "rerank_provider": "BAAI/bge-reranker-v2-m3"}
        )
    assert label == "model" and note is None
    assert isinstance(runner, ModelRerankRunner)


def test_runner_degrades_with_explicit_note():
    from neurova.api.endpoints import semantic_search_api as ssa

    empty = _manager()
    with patch.object(rc, "get_provider_manager", return_value=empty):
        runner, label, note = ssa._build_rerank_runner(
            {"method": "model", "rerank_provider": "missing/reranker"}
        )
    assert label == "weight"
    assert note is not None, "退化必须可见（note 携带原因），禁止静默"
    assert "not_configured" in note["reason"]


def test_runner_default_capability_resolution(sf_manager):
    from neurova.api.endpoints import semantic_search_api as ssa

    with patch.object(rc, "get_provider_manager", return_value=sf_manager):
        runner, label, note = ssa._build_rerank_runner({"method": "model"})
    assert label == "model" and note is None  # 空 provider 名 → 能力发现命中


def test_weight_mode_unchanged():
    from neurova.api.endpoints import semantic_search_api as ssa

    runner, label, note = ssa._build_rerank_runner({"method": "weight"})
    assert label == "weight" and note is None


# ── runner 失败原因记录（后端故障与"零结果"可区分）─────────────────

def test_model_runner_records_last_error_on_fallback():
    def broken(q, docs):
        raise rc.RerankBackendError("upstream 500", kind="http")

    runner = ModelRerankRunner(
        broken, fallback_weights={"bm25": 1.0},
    )
    out = runner.rerank("q", [{"index": 0, "id": "a", "bm25": 0.5}])
    assert len(out) == 1
    assert runner.last_error and "http" in runner.last_error


def test_model_runner_success_clears_last_error():
    runner = ModelRerankRunner(lambda q, docs: [0.9], fallback_weights={"bm25": 1.0})
    runner.rerank("q", [{"index": 0, "id": "a", "bm25": 0.5}])
    assert runner.last_error is None
