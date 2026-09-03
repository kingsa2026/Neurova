"""
画布 IO 节点执行器测试（TDD 红绿）。

覆盖：
- media_input（远程 / 上传）
- file_input（上传 / 远程 URL）
- knowledge_base（本地记忆库 / 远程 API）
- remote_api（GET / POST，mock 网络）
- output（文件 / 文本）

注：执行器为 async，测试用 asyncio.run 运行，避免依赖 pytest-asyncio 插件。
"""

import asyncio
import json
import sys

import pytest

from neurova.collaboration.neurflow.builtin import (
    exec_file_input,
    exec_knowledge_base,
    exec_media_input,
    exec_output,
    exec_remote_api,
)


class FakeOutboundResponse:
    def __init__(self, ok=True, status=200, data=None, url=""):
        self.ok = ok
        self.status_code = status
        self._data = data or {}
        self.text = json.dumps(self._data) if data else ""
        self.url = url

    def json(self):
        return self._data


class FakeSafeRequest:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, **kwargs):
        if "knowledge" in url or "kb" in url:
            self.calls.append(("post", url, kwargs.get("json")))
            return FakeOutboundResponse(data={"results": [{"content": "kb-hit"}]})
        self.calls.append((method, url, kwargs.get("json")))
        return FakeOutboundResponse(data={"status_code": 200, "body": {"ok": True}})


@pytest.fixture
def patch_safe_request(monkeypatch):
    fsr = FakeSafeRequest()
    monkeypatch.setattr(
        "neurova.collaboration.neurflow.builtin._safe_request", fsr
    )
    yield fsr


class FakeMemoryManager:
    def search(self, query, limit=5):
        item = type("M", (), {"to_dict": lambda self: {"content": "mem-" + query}})()
        return [item]


def _run(coro):
    return asyncio.run(coro)


# ============ media_input ============

def test_media_input_remote():
    r = _run(
        exec_media_input(
            {"media_type": "image", "source": "remote", "source_format": "url", "value": "http://x/a.png"}, {}
        )
    )
    assert r["status"] == "success"
    assert r["output"]["media"]["source"] == "url"
    assert r["output"]["media"]["value"] == "http://x/a.png"


def test_media_input_upload():
    r = _run(
        exec_media_input(
            {"media_type": "video", "source": "upload", "upload_file": {"name": "v.mp4"}}, {}
        )
    )
    assert r["status"] == "success"
    assert r["output"]["media"]["source"] == "upload"
    assert r["output"]["media"]["file"] == {"name": "v.mp4"}


# ============ file_input ============

def test_file_input_upload():
    r = _run(
        exec_file_input(
            {"source": "upload", "file_types": "pdf", "upload_file": {"name": "a.pdf", "dataUrl": "data:"}}, {}
        )
    )
    assert r["status"] == "success"
    assert r["output"]["file"]["source"] == "upload"
    assert r["output"]["file"]["kind"] == "pdf"


def test_file_input_remote_url():
    r = _run(exec_file_input({"source": "url", "value": "http://x/a.docx"}, {}))
    assert r["status"] == "success"
    assert r["output"]["file"]["value"] == "http://x/a.docx"


# ============ knowledge_base ============

def test_knowledge_base_local():
    r = _run(
        exec_knowledge_base(
            {"kb_type": "local", "query": "气候", "limit": 3}, {"memory_manager": FakeMemoryManager()}
        )
    )
    assert r["status"] == "success"
    assert r["output"]["results"][0]["content"] == "mem-气候"


def test_knowledge_base_local_no_manager():
    r = _run(exec_knowledge_base({"kb_type": "local", "query": "x"}, {}))
    assert r["status"] == "failed"


def test_knowledge_base_remote(monkeypatch):
    """R-5: 远程知识库走 GenericRESTAdapter（mock 类级 http_post，SSRF 校验放行）"""
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured["payload"] = payload
        captured["headers"] = headers
        return {"results": [{"id": "r1"}]}

    from neurova.knowledge import adapters as kb_adapters

    monkeypatch.setattr(kb_adapters, "_validate_remote_url", lambda u: True)
    monkeypatch.setattr(kb_adapters.GenericRESTAdapter, "_default_post", staticmethod(fake_post))
    r = _run(
        exec_knowledge_base(
            {
                "kb_type": "custom",
                "query": "项目",
                "api_url": "https://kb.example/retrieve",
                "api_key": "k",
                "dataset_id": "d1",
            },
            {},
        )
    )
    assert r["status"] == "success"
    assert r["output"]["kb_type"] == "custom"
    assert captured["payload"]["query"] == "项目"
    assert captured["payload"]["dataset_id"] == "d1"
    assert captured["headers"]["Authorization"] == "Bearer k"


def test_knowledge_base_remote_missing_url():
    # custom/未知类型缺 api_url → failed（GenericREST 契约）
    r = _run(exec_knowledge_base({"kb_type": "custom", "query": "x", "api_url": ""}, {}))
    assert r["status"] == "failed"


def test_knowledge_base_ima_missing_token():
    # ima 走 ImaKBAdapter：缺 token → failed（不依赖通用 api_url）
    r = _run(exec_knowledge_base({"kb_type": "ima", "query": "x", "base_url": "http://127.0.0.1:9007"}, {}))
    assert r["status"] == "failed"
    assert "token" in r.get("error", "")


def test_knowledge_base_iflow_dispatch(monkeypatch):
    """R-5: kb_type=iflow 分派到 IflowKBAdapter（协议 startSearch/poll）"""
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda s: None)

    def fake_post_form(path, data, timeout):
        return {"success": True, "data": {"searchId": "s-9"}}

    def fake_get(path, timeout):
        return {
            "success": True,
            "data": {"list": [{"status": "DONE", "results": [{"title": "iflow-hit"}]}]},
        }

    from neurova.knowledge.adapters import IflowKBAdapter

    original_init = IflowKBAdapter.__init__

    def patched_init(self, config, **kwargs):
        original_init(
            self,
            {**config, "poll_interval": 0, "poll_max": 1},
            post_form=fake_post_form,
            get=fake_get,
            validate_url=lambda u: True,
        )

    monkeypatch.setattr(IflowKBAdapter, "__init__", patched_init)

    r = _run(
        exec_knowledge_base(
            {"kb_type": "iflow", "query": "装饰器", "api_key": "k", "dataset_id": "kb-1"},
            {},
        )
    )
    assert r["status"] == "success"
    assert r["output"]["kb_type"] == "iflow"
    assert r["output"]["results"][0]["title"] == "iflow-hit"


# ============ remote_api ============

def test_remote_api_post(patch_safe_request):
    r = _run(
        exec_remote_api(
            {"method": "POST", "url": "https://api.example/x", "headers": "{}", "body": '{"a":1}'}, {}
        )
    )
    assert r["status"] == "success"
    assert r["output"]["status_code"] == 200


def test_remote_api_get_missing_url():
    r = _run(exec_remote_api({"method": "GET", "url": ""}, {}))
    assert r["status"] == "failed"


# ============ output ============

def test_output_file():
    r = _run(
        exec_output(
            {"output_type": "file", "file_kind": "video", "name": "out.mp4"},
            {"inputs": {"input": {"path": "/tmp/out.mp4"}}},
        )
    )
    assert r["status"] == "success"
    assert r["output"]["output_type"] == "file"
    assert r["output"]["file_kind"] == "video"
    assert r["output"]["content"] == {"path": "/tmp/out.mp4"}


def test_output_text():
    r = _run(exec_output({"output_type": "text", "name": ""}, {"inputs": {"input": "hello"}}))
    assert r["status"] == "success"
    assert r["output"]["text"] == "hello"


def test_registry_contains_new_nodes():
    from neurova.collaboration.neurflow.node_registry import get_node_registry

    r = get_node_registry()
    r.ensure_builtin()
    types = {d.type for d in r.list_all()}
    for t in (
        "builtin:media_input",
        "builtin:file_input",
        "builtin:knowledge_base",
        "builtin:remote_api",
        "builtin:output",
    ):
        assert t in types, f"{t} 未注册"


def test_knowledge_base_refs_config(monkeypatch):
    """B: kb_config_id 引用用户级配置 → 解密 api_key 注入 adapter（不再手填）。

    2026-09-01 隔离修订：配置默认私有、按用户隔离（fail-closed）——
    ctx 必须携带与配置属主一致的 user_id，否则拒绝引用。
    """
    from neurova.collaboration.neurflow import builtin as builtin_mod
    from neurova.knowledge.adapters import IflowKBAdapter

    cfg_id = "kbc_ref1"

    captured = {}

    async def fake_search(self, query, limit=5):
        captured["api_key"] = self.api_key
        return {"status": "success", "results": [{"title": "hit"}]}

    monkeypatch.setattr(IflowKBAdapter, "search", fake_search)
    monkeypatch.setattr(
        builtin_mod,
        "_load_kb_config_secret",
        lambda cid, user_id: "sk-from-config" if cid == cfg_id and user_id == "u-owner" else None,
    )
    # storage 契约：cfg 属主 = u-owner（exec 内 `from ... import get_knowledge_storage`，
    # 须在源模块上替换）
    monkeypatch.setattr(
        "neurova.knowledge.storage.get_knowledge_storage",
        lambda: type(
            "S",
            (),
            {
                "get_config_by_id": staticmethod(
                    lambda cid: {"id": cfg_id, "user_id": "u-owner", "source_type": "iflow", "settings": {}}
                    if cid == cfg_id
                    else None
                )
            },
        )(),
    )

    r = _run(
        builtin_mod.exec_knowledge_base(
            {"kb_type": "iflow", "query": "x", "kb_config_id": cfg_id, "api_key": ""},
            {"user_id": "u-owner"},
        )
    )
    assert r["status"] == "success"
    assert captured["api_key"] == "sk-from-config", "必须用配置解密的密钥"
