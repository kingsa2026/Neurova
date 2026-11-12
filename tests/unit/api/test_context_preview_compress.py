# -*- coding: utf-8 -*-
"""P2-1 context 预览/压缩实装验收（全库断点审计 2026-11-12）。

缺陷：/{context_id}/preview 恒回 "Context preview not available"、
/{context_id}/compress 恒回 "not implemented yet"（成功壳谎报，修复教义
第 2 条）——根因是 /build 产物从未按 id 落册。

实装：/build 与 /build/v2 把构建产物按 id 登记进有界注册表；preview 读取
登记产物；compress 保留最近连续段落至目标 token 预算并写回登记。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from neurova.api.endpoints import context as context_api

    application = FastAPI()
    application.include_router(context_api.router, prefix="/v1/context")
    application.dependency_overrides[context_api.get_current_user] = lambda: {
        "user_id": "u1", "username": "u", "role": "admin", "neuser_id": "ne1",
    }
    return TestClient(application)


def test_build_preview_compress_roundtrip(client):
    built = client.post(
        "/v1/context/build",
        json={
            "agent_id": "agent_ctx",
            "user_input": "第一段用户输入\n第二段用户输入\n第三段用户输入",
            "session_id": "sess-ctx",
        },
    )
    assert built.status_code == 200, built.text
    context_id = built.json()["context_id"]
    original_tokens = built.json()["token_count"]
    assert original_tokens > 0

    # preview：读登记产物
    preview = client.get(f"/v1/context/{context_id}/preview")
    assert preview.status_code == 200
    assert preview.json()["content"] == built.json()["content"]
    assert preview.json()["token_count"] == original_tokens

    # compress：压缩到小预算 → token 下降、淘汰段有读数、写回登记
    compressed = client.post(
        f"/v1/context/{context_id}/compress", params={"target_tokens": 8}
    )
    assert compressed.status_code == 200, compressed.text
    data = compressed.json()["data"]
    assert data["compressed_tokens"] < original_tokens
    assert data["dropped_segments"] >= 1
    assert data["compressed_tokens"] == client.get(
        f"/v1/context/{context_id}/preview"
    ).json()["token_count"]

    # 未知 id：404
    assert client.get("/v1/context/no-such-id/preview").status_code == 404
    assert client.post("/v1/context/no-such-id/compress").status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
