# -*- coding: utf-8 -*-
"""P1-2 防回归：媒体文件必须落盘，字节不得永久驻留内存。

原缺陷（docs/资源型Bug扫描报告_2026-09-11.md RES-P1-2）：
1. ``_file_contents: Dict[str, bytes]`` 把所有上传媒体字节永久驻留内存
   （每文件 ≤50MB，从不落盘，100 次上传 ≈ 5GB 级增长直至 OOM）；
2. ``content = await file.read()`` 在大小校验前执行，任意大请求全量读入；
3. ``clear_cache`` 是返回 ``cleared_items: 0`` 的空壳。

本测试固定四条行为：
- save 内容写进 storage_path 指向的磁盘路径（目录自动创建），内存不留字节；
- 超限分块读取即停（413），不消费完整上传流，不残留半写文件；
- get/download 从磁盘提供内容（FileResponse），delete 同步删磁盘文件；
- clear_cache 实做清空内存媒体索引。

隔离纪律：storage_path 由 monkeypatch 指向 tmp_path，绝不写真实目录。
"""

import asyncio
import os
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

from neurova.api.endpoints import media as media_module


class _FakeUploadFile:
    """分块读取语义与 starlette.UploadFile 对齐：read(size) 至多返回 size 字节。

    bytes_served 记录累计消费的上传流字节数，用于断言「超限即停」。
    """

    def __init__(self, data: bytes, filename: str = "clip.png"):
        self.filename = filename
        self._data = data
        self._offset = 0
        self.bytes_served = 0

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            end = len(self._data)
        else:
            end = min(self._offset + size, len(self._data))
        chunk = self._data[self._offset:end]
        self._offset = end
        self.bytes_served += len(chunk)
        return chunk


@pytest.fixture()
def media_env(tmp_path, monkeypatch):
    """存储根指到 tmp_path；内存媒体索引每用例前后清空。"""
    monkeypatch.setattr(
        media_module,
        "_media_config",
        {**media_module._media_config, "storage_path": str(tmp_path / "media_storage")},
    )
    media_module._media_store.clear()
    yield tmp_path
    media_module._media_store.clear()


def _save(payload: bytes, filename: str = "clip.png", agent_id: str = "a1", media_type: str = "image"):
    return asyncio.run(
        media_module.save_media(
            file=_FakeUploadFile(payload, filename=filename),
            media_type=media_type,
            agent_id=agent_id,
        )
    )


def test_save_media_writes_to_disk_not_memory(media_env):
    """内容必须落盘到 storage_path，且不得再驻留任何内存字节字典。"""
    payload = b"png-bytes-1234"
    resp = _save(payload)
    data = resp["data"]

    # 响应契约字段不变
    assert data["storage_path"]
    assert data["filename"] == "clip.png"
    assert data["size"] == len(payload)
    assert data["agent_id"] == "a1"

    disk = Path(os.path.abspath(data["storage_path"]))
    assert disk.is_file(), f"媒体内容未落盘: {disk}"
    assert disk.read_bytes() == payload
    assert disk.is_relative_to(media_env), "落盘路径必须位于配置的存储根内"

    leftovers = dict(getattr(media_module, "_file_contents", {}) or {})
    assert not leftovers, "媒体字节仍在内存字典 _file_contents 中驻留（P1-2 未修复）"


def test_save_media_creates_missing_directories(media_env):
    """agent/media_type 子目录不存在时自动创建（mkdir parents）。"""
    resp = _save(b"x", agent_id="deep_agent", media_type="audio")
    disk = Path(os.path.abspath(resp["data"]["storage_path"]))
    assert disk.is_file()
    assert disk.parent == media_env / "media_storage" / "deep_agent" / "audio"


def test_save_media_oversize_413_stops_reading_and_cleans_partial(media_env, monkeypatch):
    """超限必须 413，且分块读取即停（不得全量消费上传流），不残留半写文件。

    上传流长度超过一个读取分块（生产代码单次 read 1MB），超限后累计消费
    不得超过「上限 + 一个分块」——旧实现先 await file.read() 全量读入再校验。
    """
    monkeypatch.setitem(media_module._media_config, "max_file_size", 8)
    chunk = 1024 * 1024  # 与 save_media 的读取分块一致
    payload = b"x" * (chunk + 512)
    fake = _FakeUploadFile(payload)

    with pytest.raises(HTTPException) as ei:
        asyncio.run(media_module.save_media(file=fake, media_type="image", agent_id="a1"))

    assert ei.value.status_code == 413
    assert fake.bytes_served < len(payload), "超限后未停止读取上传流（仍全量消费）"
    assert fake.bytes_served <= 8 + chunk, "超限后读取量超出『上限+一个分块』"
    root = media_env / "media_storage"
    assert not [p for p in root.rglob("*") if p.is_file()], "超限请求残留了半写文件"


def test_get_media_serves_from_disk(media_env):
    """读取端点从磁盘 FileResponse 提供内容（含既有响应头契约）。"""
    payload = b"wav-bytes-42"
    resp = _save(payload, filename="t.wav", media_type="audio")
    media_id = resp["data"]["media_id"]

    out = asyncio.run(media_module.get_media(media_id))
    assert isinstance(out, FileResponse), "读取端点应从磁盘 FileResponse 流式提供内容"
    assert Path(out.path).read_bytes() == payload
    assert out.headers["x-media-id"] == media_id
    assert "attachment" in out.headers["content-disposition"]


def test_download_attachment_serves_from_disk(media_env):
    payload = b"tts-audio"
    resp = _save(payload, filename="s.wav", media_type="audio")
    media_id = resp["data"]["media_id"]

    out = asyncio.run(media_module.download_attachment(media_id))
    assert isinstance(out, FileResponse)
    assert Path(out.path).read_bytes() == payload
    assert "attachment" in out.headers["content-disposition"]


def test_delete_media_removes_disk_file(media_env):
    resp = _save(b"doomed")
    media_id = resp["data"]["media_id"]
    disk = Path(os.path.abspath(resp["data"]["storage_path"]))
    assert disk.is_file()

    out = asyncio.run(media_module.delete_media(media_id))

    assert out["code"] == 0
    assert not disk.exists(), "delete_media 未同步删除磁盘文件"
    assert media_id not in media_module._media_store


def test_delete_media_missing_disk_file_still_removes_metadata(media_env):
    """磁盘文件已丢（外部清理）时删除端点不应 500。"""
    resp = _save(b"gone")
    media_id = resp["data"]["media_id"]
    Path(os.path.abspath(resp["data"]["storage_path"])).unlink()

    out = asyncio.run(media_module.delete_media(media_id))
    assert out["code"] == 0
    assert media_id not in media_module._media_store


def test_clear_cache_clears_media_index(media_env):
    """clear_cache 实做：清空内存媒体索引并回报真实计数（原为恒 0 空壳）。"""
    _save(b"one", filename="1.png")
    _save(b"two", filename="2.png")

    out = asyncio.run(media_module.clear_cache())

    assert out["code"] == 0
    assert out["data"]["cleared_items"] == 2
    assert out["data"]["freed_space"] == 6
    assert not media_module._media_store


def test_save_media_rejects_path_escape(media_env):
    """落盘后 storage_path 成真实写路径：携带路径片段的 agent_id 必须被拒绝。"""
    with pytest.raises(HTTPException) as ei:
        asyncio.run(
            media_module.save_media(
                file=_FakeUploadFile(b"z"), media_type="image", agent_id="../escape"
            )
        )
    assert ei.value.status_code == 400
    assert not (media_env / "escape").exists(), "路径穿越写到了存储根之外"
