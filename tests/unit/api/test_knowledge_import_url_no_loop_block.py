# -*- coding: utf-8 -*-
"""P1-10b /import-url 事件循环阻塞红测（全库断点审计 2026-11-12）

缺陷：async def import_knowledge_url 的 sync=True 默认分支在事件循环里
裸跑 `_fetch_url`（urllib.urlopen(timeout=15)）＋解析链——一次慢抓取期间
整个后端所有请求（含 chat 流式、healthcheck）排队，单点最高频的整服卡死源。

判据：两个并发 /import-url（抓取各 1s）——事件循环不被堵时总耗时≈单次抓取；
被堵时≈两次之和（≥2s）。修复口径（审计"最小止血"做全）：抓取与解析链
移入工作线程（asyncio.to_thread），sync 契约（响应带 items）不变。
"""
import asyncio
import os
import time

os.environ.setdefault("NEUROVA_JWT_SECRET", "test_secret_for_p1-10b_import_url")
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_for_p1-10b_import_url")

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from neurova.api.endpoints import knowledge_ingestion as ki

FETCH_SECONDS = 1.0


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    # SSRF 守卫做真实 DNS 解析——沙箱 DNS 抖动会让用例红在环境上而非被测行为
    # （本测试只判"事件循环不被同步抓取阻塞"），守卫恒真注入。
    monkeypatch.setattr(ki, "validate_public_http_url", lambda url: True)

    def _slow_fetch(url):
        time.sleep(FETCH_SECONDS)
        return b"<html><body>payload</body></html>"

    monkeypatch.setattr(ki, "_fetch_url", _slow_fetch)
    monkeypatch.setattr(
        ki, "_import_file_data",
        lambda data, filename, agent_id, user, **kwargs:
            ([{"title": "t", "content": "c"}], "ok"),
    )
    monkeypatch.setattr(ki, "_try_extract_to_graph", lambda *a, **k: None)
    monkeypatch.setattr(ki, "extract_event_summary", lambda *a, **k: None)

    application = FastAPI()
    application.include_router(ki.router)
    application.dependency_overrides[ki.get_current_user_or_service] = lambda: {
        "user_id": "u_test", "username": "tester", "role": "user",
        "neuser_id": "ne_test", "tenant_id": "default",
    }
    return application


@pytest.mark.asyncio
async def test_slow_fetch_does_not_block_event_loop(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async def one(tag):
            resp = await client.post(
                "/import-url",
                params={"url": f"https://example.com/{tag}.html", "sync": True},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["code"] == 0
            return resp.json()

        t0 = time.monotonic()
        results = await asyncio.gather(one("a"), one("b"))
        elapsed = time.monotonic() - t0

    assert len(results) == 2
    # 被堵形态：两次抓取串行 ≈ 2×FETCH_SECONDS；不堵形态 ≈ 1×FETCH_SECONDS
    assert elapsed < FETCH_SECONDS * 1.9, (
        f"事件循环被同步抓取阻塞：并发两请求耗时 {elapsed:.2f}s（阈值 "
        f"{FETCH_SECONDS * 1.9:.2f}s），慢抓取期间整服请求都会排队"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
