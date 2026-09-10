"""L-17 回归测试：文生视频 completed 任务携带 video_url 时必须正常完成。

红绿：无修复时 _extract_video_data 拿到 video_url 直接 return None，
_poll_task_status 收到 completed 后 video_data=None 继续轮询至超时，
调用方报"任务执行失败或超时"。断言：completed + video_url 时
_poll_task_status 返回下载的视频字节；direct-response 路径同样返回字节。
"""

import base64

import pytest

pytest.importorskip("aiohttp")

from neurova.llm.generators.text_to_video import create_text_to_video_generator


class _FakeResponse:
    """aiohttp 响应桩：异步上下文管理器。"""

    def __init__(self, status=200, json_data=None, body=b""):
        self.status = status
        self._json = json_data
        self._body = body

    async def json(self):
        return self._json

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """aiohttp 会话桩：按 URL 路由响应。"""

    def __init__(self, routes):
        self._routes = routes
        self.requested = []

    def get(self, url, headers=None, timeout=None):
        self.requested.append(url)
        return self._routes[url]


VIDEO_BYTES = b"FAKE_VIDEO_BYTES"


def _make_generator():
    return create_text_to_video_generator(api_key="k", base_url="http://fake", provider="generic")


class TestL17VideoUrlAssembled:
    @pytest.mark.asyncio
    async def test_poll_returns_video_bytes_when_completed_with_url(self):
        """completed + video_url：下载并返回视频字节，而非轮询到假性超时。"""
        gen = _make_generator()
        status_data = {"status": "completed", "output": {"video_url": "http://fake/video.mp4"}}
        session = _FakeSession(
            {
                "http://fake/tasks/t1": _FakeResponse(json_data=status_data),
                "http://fake/video.mp4": _FakeResponse(body=VIDEO_BYTES),
            }
        )
        result = await gen._poll_task_status(session, {}, "t1", "generic", max_attempts=2, poll_interval=0)
        assert result == VIDEO_BYTES, (
            "L-17: completed 且有 video_url 时必须组装结果正常完成，不得轮询至超时"
        )
        assert "http://fake/video.mp4" in session.requested

    @pytest.mark.asyncio
    async def test_completed_without_video_data_stops_polling(self):
        """completed 但确实无视频数据：立即返回 None，不再空轮询。"""
        gen = _make_generator()
        status_data = {"status": "completed"}
        session = _FakeSession({"http://fake/tasks/t1": _FakeResponse(json_data=status_data)})
        result = await gen._poll_task_status(session, {}, "t1", "generic", max_attempts=3, poll_interval=0)
        assert result is None
        assert len(session.requested) == 1, "completed 后不应继续轮询"

    @pytest.mark.asyncio
    async def test_extract_video_data_downloads_url(self):
        """_extract_video_data 对 video_url 走下载，返回字节。"""
        gen = _make_generator()
        session = _FakeSession({"http://fake/v.mp4": _FakeResponse(body=VIDEO_BYTES)})
        data = {"output": {"video_url": "http://fake/v.mp4"}}
        assert await gen._extract_video_data(session, data) == VIDEO_BYTES

    @pytest.mark.asyncio
    async def test_extract_video_data_base64_path_unchanged(self):
        """base64 路径行为保持不变（防过修）。"""
        gen = _make_generator()
        session = _FakeSession({})
        payload = base64.b64encode(b"abc123").decode()
        assert await gen._extract_video_data(session, {"video_base64": payload}) == b"abc123"

    @pytest.mark.asyncio
    async def test_extract_video_data_download_failure_returns_none(self):
        """下载失败（非 200）返回 None，不抛异常。"""
        gen = _make_generator()
        session = _FakeSession({"http://fake/v.mp4": _FakeResponse(status=404)})
        data = {"output": {"video_url": "http://fake/v.mp4"}}
        assert await gen._extract_video_data(session, data) is None
