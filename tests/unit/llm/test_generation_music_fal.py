# -*- coding: utf-8 -*-
"""M1（多模态追平批一）：fal 音乐生成协议最小闭环。

契约事实源：fal.ai 官方文档 Queue API（docs.fal.ai/model-endpoints/queue，
2026-11-22 WebFetch 实核）：
- 提交 ``POST https://queue.fal.run/{owner}/{app}``，头 ``Authorization: Key <FAL_KEY>``，
  响应 {request_id, status_url, response_url, queue_position}；
- 轮询 ``GET {owner}/{app}/requests/{request_id}/status``，
  status ∈ IN_QUEUE / IN_PROGRESS / COMPLETED（失败在 COMPLETED 内带 error/error_type）；
- 取回 ``GET {owner}/{app}/requests/{request_id}`` → 模型输出
  （音频型为 audio.url / audio_url 形态，按候选字段宽松解析）；
- 状态/取回 URL 只含 owner/app 两段——完整模型 ID 的多余子路径不进轮询 URL
  （官方文档明示：带 endpoint 子路径的 URL 返回 405）。
"""
from __future__ import annotations

import pytest

from neurova.llm.generators import protocols as proto_mod
from neurova.llm.generators.protocols import (
    MusicProtocol,
    ProtocolCredentials,
    fal_result_url,
    fal_status_url,
    fal_submit_url,
    poll_music,
    resolve_music_protocol,
    submit_music,
)


def _creds(**kw) -> ProtocolCredentials:
    base = {"api_key": "fal-key-1", "base_url": "https://queue.fal.run",
            "model": "fal-ai/musicgen", "protocol": "fal"}
    base.update(kw)
    return ProtocolCredentials(**base)


class TestFalMusicUrlRules:
    def test_submit_url_is_model_path_under_queue_host(self):
        assert fal_submit_url("fal-ai/musicgen") == "https://queue.fal.run/fal-ai/musicgen"
        assert fal_submit_url("custom/app-name") == "https://queue.fal.run/custom/app-name"

    def test_status_and_result_urls_use_owner_app_only(self):
        """多段模型 ID（如 fal-ai/flux/schnell）→ 轮询/取回只取 owner/app 两段。"""
        assert fal_status_url("fal-ai/flux/schnell", "r1") == \
            "https://queue.fal.run/fal-ai/flux/requests/r1/status"
        assert fal_result_url("fal-ai/flux/schnell", "r1") == \
            "https://queue.fal.run/fal-ai/flux/requests/r1"

    def test_protocol_resolution(self):
        assert resolve_music_protocol("fal") is MusicProtocol.FAL
        assert resolve_music_protocol("", "fal-ai/musicgen", "") is MusicProtocol.FAL
        assert resolve_music_protocol("", "", "https://queue.fal.run") is MusicProtocol.FAL
        # 音乐当前唯一实测协议族：缺省即 fal（诚实默认，不虚构第二家）
        assert resolve_music_protocol() is MusicProtocol.FAL


class TestFalMusicSubmit:
    @pytest.mark.asyncio
    async def test_submit_maps_request_and_response(self, monkeypatch):
        captured = {}

        async def fake_post_json(url, headers, body, timeout=60.0):
            captured.update(url=url, headers=dict(headers), body=dict(body))
            return 200, {
                "request_id": "req-1",
                "status_url": "https://queue.fal.run/fal-ai/musicgen/requests/req-1/status",
                "response_url": "https://queue.fal.run/fal-ai/musicgen/requests/req-1",
                "queue_position": 0,
            }

        monkeypatch.setattr(proto_mod, "_post_json", fake_post_json)
        out = await submit_music(_creds(), "轻快的钢琴曲", duration=30)
        assert captured["url"] == "https://queue.fal.run/fal-ai/musicgen"
        # fal 鉴权头是 Key 前缀（非 Bearer），官方文档原文 Authorization: Key $FAL_KEY
        assert captured["headers"]["Authorization"] == "Key fal-key-1"
        assert captured["body"]["prompt"] == "轻快的钢琴曲"
        assert captured["body"]["duration"] == 30
        assert out["task_id"] == "req-1"
        assert out["poll_url"] == \
            "https://queue.fal.run/fal-ai/musicgen/requests/req-1/status"
        assert out["result_url"] == \
            "https://queue.fal.run/fal-ai/musicgen/requests/req-1"

    @pytest.mark.asyncio
    async def test_submit_failure_is_honest(self, monkeypatch):
        async def fake_post_json(url, headers, body, timeout=60.0):
            return 401, {"detail": "invalid FAL_KEY"}

        monkeypatch.setattr(proto_mod, "_post_json", fake_post_json)
        with pytest.raises(RuntimeError) as err_info:
            await submit_music(_creds(), "p")
        assert "401" in str(err_info.value)
        assert "invalid FAL_KEY" in str(err_info.value)


class TestFalMusicPollFourStates:
    """轮询四态：IN_QUEUE / IN_PROGRESS / COMPLETED(取回成功) / 失败。"""

    @pytest.mark.asyncio
    async def test_in_queue_maps_to_running(self, monkeypatch):
        async def fake_get_json(url, headers, timeout=30.0):
            assert url == "https://queue.fal.run/fal-ai/musicgen/requests/req-1/status"
            return 200, {"status": "IN_QUEUE", "queue_position": 2}

        monkeypatch.setattr(proto_mod, "_get_json", fake_get_json)
        result = await poll_music(_creds(), "req-1")
        assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_in_progress_maps_to_running(self, monkeypatch):
        async def fake_get_json(url, headers, timeout=30.0):
            return 200, {"status": "IN_PROGRESS", "logs": []}

        monkeypatch.setattr(proto_mod, "_get_json", fake_get_json)
        result = await poll_music(_creds(), "req-1")
        assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_completed_fetches_result_audio_url(self, monkeypatch):
        seen_urls = []

        async def fake_get_json(url, headers, timeout=30.0):
            seen_urls.append(url)
            if url.endswith("/status"):
                return 200, {"status": "COMPLETED", "metrics": {"inference_time": 1.2}}
            return 200, {"audio": {"url": "https://cdn.fal.ai/out.mp3"}}

        monkeypatch.setattr(proto_mod, "_get_json", fake_get_json)
        result = await poll_music(_creds(), "req-1")
        assert result["status"] == "succeeded"
        assert result["audio_url"] == "https://cdn.fal.ai/out.mp3"
        assert any(u.endswith("/requests/req-1/status") for u in seen_urls)
        assert any(u.endswith("/requests/req-1") and not u.endswith("/status")
                   for u in seen_urls)

    @pytest.mark.asyncio
    async def test_completed_with_error_is_failed(self, monkeypatch):
        async def fake_get_json(url, headers, timeout=30.0):
            assert url.endswith("/status")
            return 200, {"status": "COMPLETED", "error": "model runtime crashed",
                         "error_type": "RuntimeError"}

        monkeypatch.setattr(proto_mod, "_get_json", fake_get_json)
        result = await poll_music(_creds(), "req-1")
        assert result["status"] == "failed"
        assert "model runtime crashed" in result["error"]

    @pytest.mark.asyncio
    async def test_http_error_is_failed_honest(self, monkeypatch):
        async def fake_get_json(url, headers, timeout=30.0):
            return 404, {"detail": "not found"}

        monkeypatch.setattr(proto_mod, "_get_json", fake_get_json)
        result = await poll_music(_creds(), "req-1")
        assert result["status"] == "failed"
        assert "404" in result["error"]

    @pytest.mark.asyncio
    async def test_audio_url_candidates_loose_parse(self, monkeypatch):
        """音频产物字段按候选宽松解析（audio_url / audio.url / url）。"""

        async def make(url_body):
            async def fake_get_json(url, headers, timeout=30.0):
                if url.endswith("/status"):
                    return 200, {"status": "COMPLETED"}
                return 200, url_body
            return fake_get_json

        for body, expected in (
            ({"audio_url": "https://x/a.mp3"}, "https://x/a.mp3"),
            ({"output": {"audio": {"url": "https://x/b.wav"}}}, "https://x/b.wav"),
            ({"url": "https://x/c.flac"}, "https://x/c.flac"),
        ):
            monkeypatch.setattr(proto_mod, "_get_json", await make(body))
            result = await poll_music(_creds(), "req-1")
            assert result["status"] == "succeeded"
            assert result["audio_url"] == expected
