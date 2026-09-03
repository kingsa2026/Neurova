"""
测试：files_api 文件类型分类 + 附件读取 helper（R-3 附件多模态）

背景根因（R-3）:
  files_api._determine_file_type 只分类 image/audio/video/code/text 五类，
  doc/docx/xls/xlsx/ppt/pptx/pdf/csv/html 全部落到 "file"（通用），
  会话路由无法按类型分派附件处理。

修复契约:
  1. _determine_file_type 对 Office/PDF/HTML 返回 "document"
  2. get_file_info / get_file_bytes 能按 file_id 读取已上传文件（供 console 注入）
  3. 安全：非本用户（user_id 不匹配）访问返回 None（防 IDOR）
"""

import pytest

from neurova.api.endpoints import files_api


# ── 分类 ────────────────────────────────────────────────────────────

class TestDetermineFileType:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("报告.docx", "document"),
            ("演示.pptx", "document"),
            ("表格.xlsx", "document"),
            ("旧版.doc", "document"),
            ("旧表.xls", "document"),
            ("旧版.ppt", "document"),
            ("手册.pdf", "document"),
            ("数据.csv", "document"),
            ("页面.html", "document"),
            ("页面.htm", "document"),
            ("说明.md", "text"),
            ("说明.txt", "text"),
            ("说明.rst", "text"),
            ("photo.jpg", "image"),
            ("photo.png", "image"),
            ("photo.svg", "image"),
            ("voice.mp3", "audio"),
            ("voice.wav", "audio"),
            ("video.mp4", "video"),
            ("video.mkv", "video"),
            ("main.py", "code"),
            ("app.js", "code"),
            ("archive.zip", "file"),
            ("unknown.xyz", "file"),
        ],
    )
    def test_type_mapping(self, filename, expected):
        assert files_api._determine_file_type(filename) == expected


# ── 附件读取 helper ─────────────────────────────────────────────────

class TestAttachmentAccess:
    def test_get_file_info_returns_record(self, tmp_path, monkeypatch):
        # 直接写入内存 store（模拟已上传文件）
        files_api._files_store.clear()
        info = {
            "file_id": "test-file-1",
            "filename": "x.docx",
            "file_type": "document",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "size": 4,
            "user_id": "u-1",
            "agent_id": "default",
            "path": str(tmp_path / "x.docx"),
        }
        (tmp_path / "x.docx").write_bytes(b"abcd")
        files_api._files_store["test-file-1"] = info

        found = files_api.get_attachment_info("test-file-1", "u-1")
        assert found is not None
        assert found["file_type"] == "document"
        assert found["filename"] == "x.docx"

    def test_get_file_info_other_user_returns_none(self, tmp_path):
        files_api._files_store.clear()
        info = {
            "file_id": "test-file-2",
            "filename": "x.txt",
            "file_type": "text",
            "mime_type": "text/plain",
            "size": 4,
            "user_id": "u-2",
            "agent_id": "default",
            "path": str(tmp_path / "x.txt"),
        }
        (tmp_path / "x.txt").write_bytes(b"text")
        files_api._files_store["test-file-2"] = info

        # 非属主读取 → None（防 IDOR，与端点 _get_owned_file 一致）
        assert files_api.get_attachment_info("test-file-2", "u-1") is None

    def test_get_file_bytes_reads_disk(self, tmp_path):
        files_api._files_store.clear()
        info = {
            "file_id": "test-file-3",
            "filename": "x.txt",
            "file_type": "text",
            "mime_type": "text/plain",
            "size": 5,
            "user_id": "u-1",
            "agent_id": "default",
            "path": str(tmp_path / "x.txt"),
        }
        (tmp_path / "x.txt").write_bytes(b"hello")
        files_api._files_store["test-file-3"] = info

        data = files_api.get_attachment_bytes("test-file-3")
        assert data == b"hello"

    def test_get_file_bytes_missing_returns_none(self, tmp_path):
        files_api._files_store.clear()
        info = {
            "file_id": "test-file-4",
            "filename": "gone.txt",
            "file_type": "text",
            "mime_type": "text/plain",
            "size": 5,
            "user_id": "u-1",
            "agent_id": "default",
            "path": str(tmp_path / "gone.txt"),
        }
        files_api._files_store["test-file-4"] = info

        assert files_api.get_attachment_bytes("test-file-4") is None
