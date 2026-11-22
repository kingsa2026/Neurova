# -*- coding: utf-8 -*-
"""R11（参照系 ad 追平批三）：LLM 层 embeddings 通道 + 工厂可选切换。

契约：
- NEUROVA_EMBEDDING_PROVIDER + NEUROVA_EMBEDDING_MODEL 双键齐备才启用远程；
- 远程引擎 duck-type 本地引擎消费面（encodeOrNone/encode/encode_batch）；
- 通道失败诚实暴露（encode 抛 EmbeddingChannelError / encodeOrNone None），
  **不回落本地**（防跨嵌入空间污染）；
- 未配置 env → 工厂走本地（存量行为逐位不变）。
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from neurova.llm.embeddings_channel import (
    EmbeddingChannelError,
    embedTexts,
    getEmbeddingChannelTarget,
)

VEC_A = [0.1, 0.2, 0.3]
VEC_B = [0.4, 0.5, 0.6]


class _EmbeddingStub:
    """OpenAI 兼容 /embeddings 桩；behavior: ok | server_error | partial。"""

    def __init__(self, behavior="ok"):
        self.behavior = behavior
        self.hits = 0

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                outer = self.server.stub
                outer.hits += 1
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                if outer.behavior == "server_error":
                    self.send_response(500)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                inputs = body.get("input") or []
                vectors = [VEC_A, VEC_B][:len(inputs)] if outer.behavior == "partial" \
                    else [[0.1 * (i + 1), 0.2, 0.3] for i in range(len(inputs))]
                payload = json.dumps({
                    "data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)],
                    "model": body.get("model", ""),
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.stub = self
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def base_url(self):
        return f"http://127.0.0.1:{self.port}/v1"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def _wire_global_provider(tmp_path, monkeypatch, base_url):
    """embedTexts 走全局 provider manager 单例——配置须挂全局（R2 同教训）。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    from neurova.llm import provider_manager as pm_mod

    pm_mod.reset_provider_manager()
    from neurova.llm.provider_manager import get_provider_manager

    get_provider_manager().add_provider(
        name="emb-src", provider="openai", base_url=base_url, api_key="sk-emb",
        models=["emb-model"], default_model="emb-model", priority=10)


class TestEmbedTexts:
    def test_basic_order_preserved(self, tmp_path, monkeypatch):
        stub = _EmbeddingStub()
        try:
            _wire_global_provider(tmp_path, monkeypatch, stub.base_url())
            vectors = embedTexts(["甲", "乙"], provider_id="emb-src", model="emb-model")
            assert len(vectors) == 2
            assert vectors[0] == [0.1, 0.2, 0.3]
            assert vectors[1] == [0.2, 0.2, 0.3]
        finally:
            stub.stop()

    def test_empty_input_no_call(self, tmp_path, monkeypatch):
        stub = _EmbeddingStub()
        try:
            _wire_global_provider(tmp_path, monkeypatch, stub.base_url())
            assert embedTexts([], provider_id="emb-src", model="emb-model") == []
            assert stub.hits == 0
        finally:
            stub.stop()

    def test_missing_provider_raises(self, tmp_path, monkeypatch):
        stub = _EmbeddingStub()
        try:
            _wire_global_provider(tmp_path, monkeypatch, stub.base_url())
            with pytest.raises(EmbeddingChannelError):
                embedTexts(["x"], provider_id="no-such", model="emb-model")
        finally:
            stub.stop()

    def test_upstream_error_raises(self, tmp_path, monkeypatch):
        stub = _EmbeddingStub(behavior="server_error")
        try:
            _wire_global_provider(tmp_path, monkeypatch, stub.base_url())
            with pytest.raises(EmbeddingChannelError):
                embedTexts(["x"], provider_id="emb-src", model="emb-model")
        finally:
            stub.stop()

    def test_partial_vectors_raise(self, tmp_path, monkeypatch):
        stub = _EmbeddingStub(behavior="partial")
        try:
            _wire_global_provider(tmp_path, monkeypatch, stub.base_url())
            with pytest.raises(EmbeddingChannelError):
                embedTexts(["x", "y", "z"], provider_id="emb-src", model="emb-model")
        finally:
            stub.stop()

    def test_target_env_requires_both_keys(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_EMBEDDING_PROVIDER", raising=False)
        monkeypatch.delenv("NEUROVA_EMBEDDING_MODEL", raising=False)
        assert getEmbeddingChannelTarget() is None
        monkeypatch.setenv("NEUROVA_EMBEDDING_PROVIDER", "p1")
        assert getEmbeddingChannelTarget() is None  # 缺 model 不激活
        monkeypatch.setenv("NEUROVA_EMBEDDING_MODEL", "m1")
        assert getEmbeddingChannelTarget() == ("p1", "m1")


class TestRemoteEngineAndFactory:
    def test_engine_interface_and_factory_switch(self, tmp_path, monkeypatch):
        from neurova.embedding import get_embedding_engine, reset_embedding_engine
        from neurova.embedding.remote_engine import RemoteEmbeddingEngine

        stub = _EmbeddingStub()
        try:
            _wire_global_provider(tmp_path, monkeypatch, stub.base_url())
            monkeypatch.setenv("NEUROVA_EMBEDDING_PROVIDER", "emb-src")
            monkeypatch.setenv("NEUROVA_EMBEDDING_MODEL", "emb-model")
            reset_embedding_engine()
            engine = get_embedding_engine()
            assert isinstance(engine, RemoteEmbeddingEngine)
            assert engine.encodeOrNone("hello") == [0.1, 0.2, 0.3]
            assert engine.encode("world") == [0.1, 0.2, 0.3]
            batch = engine.encode_batch(["x", "y"])
            assert len(batch.vectors) == 2
            assert batch.dimension == 3
            assert batch.model_name == "emb-model"
        finally:
            reset_embedding_engine()
            stub.stop()

    def test_engine_encodeornone_none_on_failure(self, tmp_path, monkeypatch):
        from neurova.embedding.remote_engine import RemoteEmbeddingEngine

        engine = RemoteEmbeddingEngine("no-such-provider", "emb-model")
        assert engine.encodeOrNone("hello") is None  # 不回落本地，诚实无嵌入
        with pytest.raises(EmbeddingChannelError):
            engine.encode("hello")

    def test_factory_defaults_to_local_without_env(self, monkeypatch):
        from neurova.embedding import get_embedding_engine, reset_embedding_engine
        from neurova.embedding.remote_engine import RemoteEmbeddingEngine

        monkeypatch.delenv("NEUROVA_EMBEDDING_PROVIDER", raising=False)
        monkeypatch.delenv("NEUROVA_EMBEDDING_MODEL", raising=False)
        reset_embedding_engine()
        engine = get_embedding_engine()
        # 本地引擎或 None（薄环境无重依赖），绝不能是远程引擎
        assert not isinstance(engine, RemoteEmbeddingEngine)
        reset_embedding_engine()


class TestProviderDeclaredEmbedding:
    """R11 收尾：服务商级 embedding_model 声明面（env 双键仍全局覆盖）。"""

    def test_provider_config_embedding_model_roundtrip(self):
        from neurova.llm.provider_manager import ProviderConfig

        pc = ProviderConfig(id="x", name="x", provider="openai",
                            base_url="https://x.example.com/v1")
        assert pc.embedding_model is None
        data = pc.to_dict()
        assert data["embedding_model"] is None
        pc2 = ProviderConfig.from_dict({**data, "embedding_model": "bge-m3"})
        assert pc2.embedding_model == "bge-m3"

    def test_add_and_update_provider_embedding_model(self, tmp_path):
        from neurova.llm.provider_manager import LLMProviderManager

        mgr = LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})
        mgr.add_provider(name="e1", provider="openai",
                         base_url="https://e1.example.com/v1",
                         api_key="sk", models=["m"], default_model="m",
                         embedding_model="bge-m3")
        assert mgr.get_provider("e1").embedding_model == "bge-m3"
        assert mgr.update_provider("e1", embedding_model="text-embedding-v3")
        assert mgr.get_provider("e1").embedding_model == "text-embedding-v3"
        assert mgr.update_provider("e1", embedding_model="")
        assert mgr.get_provider("e1").embedding_model is None  # 空串=清除

    def test_target_from_provider_declaration(self, tmp_path, monkeypatch):
        """服务商级声明即启用（无需 env）；env 双键仍全局覆盖。"""
        monkeypatch.delenv("NEUROVA_EMBEDDING_PROVIDER", raising=False)
        monkeypatch.delenv("NEUROVA_EMBEDDING_MODEL", raising=False)
        _wire_global_provider(tmp_path, monkeypatch, "http://127.0.0.1:1/v1")
        from neurova.llm.provider_manager import get_provider_manager

        get_provider_manager().update_provider("emb-src", embedding_model="emb-model")
        assert getEmbeddingChannelTarget() == ("emb-src", "emb-model")
        # env 双键覆盖服务商声明
        monkeypatch.setenv("NEUROVA_EMBEDDING_PROVIDER", "other")
        monkeypatch.setenv("NEUROVA_EMBEDDING_MODEL", "other-model")
        assert getEmbeddingChannelTarget() == ("other", "other-model")

    def test_factory_uses_provider_declaration(self, tmp_path, monkeypatch):
        """无 env、服务商声明 embedding_model → 工厂出远程引擎且可取向量。"""
        from neurova.embedding import get_embedding_engine, reset_embedding_engine
        from neurova.embedding.remote_engine import RemoteEmbeddingEngine

        stub = _EmbeddingStub()
        try:
            monkeypatch.delenv("NEUROVA_EMBEDDING_PROVIDER", raising=False)
            monkeypatch.delenv("NEUROVA_EMBEDDING_MODEL", raising=False)
            _wire_global_provider(tmp_path, monkeypatch, stub.base_url())
            from neurova.llm.provider_manager import get_provider_manager

            get_provider_manager().update_provider("emb-src", embedding_model="emb-model")
            reset_embedding_engine()
            engine = get_embedding_engine()
            assert isinstance(engine, RemoteEmbeddingEngine)
            assert engine.encodeOrNone("hi") == [0.1, 0.2, 0.3]
        finally:
            reset_embedding_engine()
            stub.stop()
