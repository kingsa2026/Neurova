# -*- coding: utf-8 -*-
"""CORE-19：curl 响应体必须在读取过程中限量，不能先全量缓冲再检查大小。"""

from __future__ import annotations

import sys
import types

import pytest

from neurova import http_fetch


class _StreamingResponse:
    status_code = 200
    headers = {}

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.contentReads = 0
        self.chunkSizes = []
        self.closed = False

    @property
    def content(self):
        self.contentReads += 1
        raise AssertionError("限量读取不得访问全量 content 属性")

    def iter_content(self, chunk_size=None):
        self.chunkSizes.append(chunk_size)
        yield from self._chunks

    def close(self):
        self.closed = True


def _installStreamingCurl(monkeypatch, response):
    curl = types.ModuleType("curl_cffi")
    requestsModule = types.ModuleType("curl_cffi.requests")
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return response

    def noFallback(*_args, **_kwargs):
        raise AssertionError("本用例不得回落后端或访问网络")

    requestsModule.request = request
    curl.requests = requestsModule
    monkeypatch.setitem(sys.modules, "curl_cffi", curl)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", requestsModule)
    monkeypatch.setattr(http_fetch, "_ascii_ca", lambda: None)
    monkeypatch.setattr(http_fetch, "_urllib_once", noFallback)
    return calls


def testCurlBodyIsRejectedWhileStreamingBeforeFullBuffer(monkeypatch):
    response = _StreamingResponse([b"1234", b"5678"])
    calls = _installStreamingCurl(monkeypatch, response)

    with pytest.raises(http_fetch.PayloadTooLargeError, match="7"):
        http_fetch.request_once("https://public.example/big", max_bytes=7)

    assert response.contentReads == 0
    assert response.chunkSizes == [http_fetch._CHUNK_SIZE]
    assert response.closed is True
    assert calls[0][2]["stream"] is True


def testCurlBodyUnderLimitUsesChunksAndClosesResponse(monkeypatch):
    response = _StreamingResponse([b"1234", b"56"])
    _installStreamingCurl(monkeypatch, response)

    result = http_fetch.request_once("https://public.example/ok", max_bytes=6)

    assert result.content == b"123456"
    assert response.contentReads == 0
    assert response.closed is True
