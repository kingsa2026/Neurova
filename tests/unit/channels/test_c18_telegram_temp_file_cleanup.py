"""C-18 回归测试：Telegram 临时文件必须在消费侧 finally 清理。

缺陷：_save_temp_file NamedTemporaryFile(delete=False) 后原消费点只在
_send_photo/_send_video 正常返回 bool 时 os.unlink，一旦发送抛异常
临时文件泄漏堆积。修复：提供 _cleanup_temp_file 统一收口，
消费侧 try/finally 调用（发送异常路径同样清理）。
"""

import os
from types import SimpleNamespace

import pytest

from neurova.channels import ContentType
from neurova.channels.telegram_ai_generation import TelegramAIGenerationMixin
from neurova.channels.telegram_api_client import TelegramAPIMixin


class FakeAdapter(TelegramAPIMixin, TelegramAIGenerationMixin):
    def __init__(self, send_photo=None, send_video=None):
        self._proxies = None
        self._send_photo_impl = send_photo
        self._send_video_impl = send_video
        self.last_temp_path = None

    async def _save_temp_file(self, data, extension):
        path = await TelegramAPIMixin._save_temp_file(self, data, extension)
        self.last_temp_path = path
        return path

    def _send_text_message(self, chat_id, text):
        pass

    def _send_photo(self, chat_id, photo):
        if self._send_photo_impl is not None:
            return self._send_photo_impl(chat_id, photo)
        return True

    def _send_video(self, chat_id, video):
        if self._send_video_impl is not None:
            return self._send_video_impl(chat_id, video)
        return True

    async def generate_text_to_image(self, prompt):
        return b"fake-png-bytes"

    async def generate_text_to_video(self, prompt):
        return b"fake-mp4-bytes"


def _text_message(content):
    return SimpleNamespace(
        content=content,
        content_type=ContentType.TEXT,
        file_url="",
        metadata={},
        chat_id="chat_1",
    )


# ---- _cleanup_temp_file 帮助函数本体 ----


@pytest.mark.asyncio
async def test_cleanup_temp_file_removes_file():
    adapter = FakeAdapter()
    path = await adapter._save_temp_file(b"x" * 16, "png")
    assert path and os.path.exists(path)
    adapter._cleanup_temp_file(path)
    assert not os.path.exists(path)


def test_cleanup_temp_file_none_and_missing_are_noop():
    adapter = FakeAdapter()
    adapter._cleanup_temp_file(None)
    adapter._cleanup_temp_file("")
    adapter._cleanup_temp_file("Z:/definitely/not/here.png")  # 不存在 → 不抛


# ---- 消费侧异常路径（旧实现泄漏点）----


@pytest.mark.asyncio
async def test_temp_file_cleaned_when_send_photo_raises():
    adapter = FakeAdapter(send_photo=lambda c, p: (_ for _ in ()).throw(RuntimeError("send boom")))
    with pytest.raises(RuntimeError):
        await adapter.handle_ai_generation(_text_message("生成图片: 一只猫"))
    assert adapter.last_temp_path and not os.path.exists(adapter.last_temp_path)


@pytest.mark.asyncio
async def test_temp_file_cleaned_when_send_video_raises():
    adapter = FakeAdapter(send_video=lambda c, p: (_ for _ in ()).throw(RuntimeError("send boom")))
    with pytest.raises(RuntimeError):
        await adapter.handle_ai_generation(_text_message("生成视频: 一段舞蹈"))
    assert adapter.last_temp_path and not os.path.exists(adapter.last_temp_path)


# ---- 消费侧正常路径回归 ----


@pytest.mark.asyncio
async def test_temp_file_cleaned_on_success_path():
    adapter = FakeAdapter()
    result = await adapter.handle_ai_generation(_text_message("生成图片: 一只猫"))
    assert result is True
    assert adapter.last_temp_path and not os.path.exists(adapter.last_temp_path)


@pytest.mark.asyncio
async def test_temp_file_cleaned_when_send_returns_false():
    adapter = FakeAdapter(send_photo=lambda c, p: False)
    result = await adapter.handle_ai_generation(_text_message("生成图片: 一只猫"))
    assert result is False
    assert adapter.last_temp_path and not os.path.exists(adapter.last_temp_path)
