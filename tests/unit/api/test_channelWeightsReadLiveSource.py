"""通道权重读面单源（§6-378）。

根因：`/channel-weights` 曾自带第三份意图权重硬编码表（另两份在
`IntentAwareRecallStrategy` 与已退役的 `channels/weight.py`），与召回实际使用、
以及反馈自适应写回后的权重都对不上。现在只从 live 引擎的 `intent_strategy` 读；
无引擎时用同一份类默认表，不再手抄。
"""
from pathlib import Path
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from neurova.api.endpoints import enhanced_memory_search_api as EMS  # noqa: E402
from neurova.cognitive_layers.memory_layer.neurova_recall import (  # noqa: E402
    IntentAwareRecallStrategy,
    QueryIntent,
    RecallChannel,
)
from tests.auth_headers import overrideIdentity  # noqa: E402


def test_weightsForIntentUsesLiveEngine():
    class FakeStrategy:
        def get_channel_weights(self, intent):
            assert intent is QueryIntent.FACTUAL
            return {RecallChannel.TEXT: 0.77, RecallChannel.GRAPH: 0.23}

    class FakeEngine:
        intent_strategy = FakeStrategy()

    assert EMS._weightsForIntent("factual", [FakeEngine()]) == {
        "text": 0.77, "graph": 0.23}


def test_weightsForIntentFallsBackToLiveDefaults():
    expected = {
        channel.value: weight
        for channel, weight in
        IntentAwareRecallStrategy.INTENT_CHANNEL_WEIGHTS[QueryIntent.FACTUAL].items()
    }

    assert EMS._weightsForIntent("factual", []) == expected


def test_endpointReturnsLiveWeightsNotACopy():
    app = FastAPI()
    app.include_router(EMS.router, prefix="/api/v1/enhanced-memory-search")
    overrideIdentity(app, {"user_id": "u1", "username": "u1", "role": "user"})
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/enhanced-memory-search/channel-weights?intent=factual")

    assert resp.status_code == 200, resp.text
    expected = {
        channel.value: weight
        for channel, weight in
        IntentAwareRecallStrategy.INTENT_CHANNEL_WEIGHTS[QueryIntent.FACTUAL].items()
    }
    assert resp.json()["data"]["weights"] == expected
