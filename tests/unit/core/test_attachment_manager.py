"""
附件管理器测试（对齐 neurova/core/attachment_manager.py 真实契约）
save(filename, file_content) 真落盘；AttachmentInfo 含 file_path/file_size。
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from neurova.core.attachment_manager import (
    AttachmentManager,
    AttachmentInfo,
    get_attachment_manager,
    reset_attachment_manager,
)


def _make_manager(tmp_path):
    return AttachmentManager(config={"storage_dir": str(tmp_path / "attachments")})


class TestAttachmentInfo:
    """测试附件信息"""

    def test_create_attachment_info(self):
        """测试创建附件信息（必填 file_path/file_size）"""
        info = AttachmentInfo(
            attachment_id="test-id",
            filename="test.txt",
            file_path="/tmp/test.txt",
            file_size=1024,
            content_type="text/plain",
            metadata={"key": "value"},
        )
        assert info.attachment_id == "test-id"
        assert info.filename == "test.txt"
        assert info.file_path == "/tmp/test.txt"
        assert info.file_size == 1024
        assert info.content_type == "text/plain"
        assert info.metadata == {"key": "value"}

    def test_attachment_info_to_dict(self):
        """测试附件信息转换为字典"""
        info = AttachmentInfo(
            attachment_id="test-id",
            filename="test.txt",
            file_path="/tmp/test.txt",
            file_size=10,
            content_type="text/plain",
        )
        data = info.to_dict()
        assert data["attachment_id"] == "test-id"
        assert data["filename"] == "test.txt"
        assert data["file_size"] == 10
        assert data["content_type"] == "text/plain"
        assert "created_at" in data
        assert "metadata" in data


class TestAttachmentManager:
    """测试附件管理器"""

    @pytest.fixture
    def attachment_manager(self, tmp_path):
        """创建附件管理器实例（隔离存储目录）"""
        return _make_manager(tmp_path)

    def test_init(self, attachment_manager):
        """测试初始化"""
        assert attachment_manager is not None
        assert attachment_manager._attachments == {}

    def test_save_attachment(self, attachment_manager):
        """测试保存附件（真落盘，返回 AttachmentInfo）"""
        info = attachment_manager.save(
            filename="test.txt",
            file_content=b"hello world",
            content_type="text/plain",
        )

        assert info is not None
        assert info.attachment_id in attachment_manager._attachments
        assert info.file_size == len(b"hello world")
        assert Path(info.file_path).exists()
        assert Path(info.file_path).read_bytes() == b"hello world"

    def test_save_preserves_extension(self, attachment_manager):
        """保存保留文件扩展名"""
        info = attachment_manager.save(filename="doc.pdf", file_content=b"%PDF")

        assert info.file_path.endswith(".pdf")

    def test_save_with_metadata(self, attachment_manager):
        """测试保存带元数据的附件"""
        metadata = {"user_id": "123", "category": "document"}
        info = attachment_manager.save(
            filename="document.pdf",
            file_content=b"pdf-bytes",
            content_type="application/pdf",
            metadata=metadata,
        )

        attachment = attachment_manager.get(info.attachment_id)
        assert attachment is not None
        assert attachment.metadata == metadata

    def test_get_attachment(self, attachment_manager):
        """测试获取附件"""
        info = attachment_manager.save(filename="test.txt", file_content=b"data")

        attachment = attachment_manager.get(info.attachment_id)
        assert attachment is not None
        assert attachment.attachment_id == info.attachment_id
        assert attachment.filename == "test.txt"

    def test_get_nonexistent_attachment(self, attachment_manager):
        """测试获取不存在的附件"""
        assert attachment_manager.get("non-existent-id") is None

    def test_list_attachments(self, attachment_manager):
        """测试列出所有附件"""
        attachment_manager.save(filename="file1.txt", file_content=b"1")
        attachment_manager.save(filename="file2.txt", file_content=b"2")
        attachment_manager.save(filename="file3.txt", file_content=b"3")

        assert len(attachment_manager.list()) == 3

    def test_list_filter_by_content_type(self, attachment_manager):
        """按 content_type 过滤列表"""
        attachment_manager.save(filename="a.txt", file_content=b"a", content_type="text/plain")
        attachment_manager.save(filename="b.png", file_content=b"b", content_type="image/png")

        texts = attachment_manager.list(content_type="text/plain")
        assert len(texts) == 1
        assert texts[0].filename == "a.txt"

    def test_delete_attachment(self, attachment_manager):
        """测试删除附件（文件+元数据双删）"""
        info = attachment_manager.save(filename="test.txt", file_content=b"data")
        file_path = Path(info.file_path)
        assert file_path.exists()

        result = attachment_manager.delete(info.attachment_id)

        assert result is True
        assert info.attachment_id not in attachment_manager._attachments
        assert not file_path.exists()

    def test_delete_nonexistent_attachment(self, attachment_manager):
        """测试删除不存在的附件"""
        assert attachment_manager.delete("non-existent-id") is False

    def test_multiple_attachments(self, attachment_manager):
        """测试多个附件"""
        ids = []
        for i in range(5):
            info = attachment_manager.save(filename=f"file{i}.txt", file_content=bytes([i]))
            ids.append(info.attachment_id)

        assert len(attachment_manager.list()) == 5

        for i, attachment_id in enumerate(ids):
            attachment = attachment_manager.get(attachment_id)
            assert attachment is not None
            assert attachment.filename == f"file{i}.txt"

    def test_get_storage_stats(self, attachment_manager):
        """测试存储统计"""
        attachment_manager.save(filename="a.txt", file_content=b"abc", content_type="text/plain")
        attachment_manager.save(filename="b.png", file_content=b"xy", content_type="image/png")

        stats = attachment_manager.get_storage_stats()
        assert stats["total_attachments"] == 2
        assert stats["total_size"] == 5
        assert stats["type_counts"] == {"text/plain": 1, "image/png": 1}

    def test_cleanup_orphaned_files(self, attachment_manager):
        """测试孤立文件清理（无元数据的落盘文件被删）"""
        orphan = attachment_manager._storage_dir / "orphan-id.txt"
        orphan.write_bytes(b"orphan")

        info = attachment_manager.save(filename="kept.txt", file_content=b"keep")

        cleaned = attachment_manager.cleanup_orphaned_files()

        assert cleaned == 1
        assert not orphan.exists()
        assert Path(info.file_path).exists()


class TestGetAttachmentManager:
    """测试获取附件管理器单例"""

    def test_get_attachment_manager(self):
        """测试获取附件管理器实例"""
        reset_attachment_manager()
        manager1 = get_attachment_manager()
        manager2 = get_attachment_manager()
        assert manager1 is manager2
        reset_attachment_manager()


class TestEdgeCases:
    """测试边界情况"""

    def test_save_empty_filename(self, tmp_path):
        """测试保存空文件名（无扩展名路径）"""
        manager = _make_manager(tmp_path)
        info = manager.save(filename="", file_content=b"data")
        assert info.attachment_id is not None
        assert Path(info.file_path).exists()

    def test_save_default_content_type(self, tmp_path):
        """未指定 content_type 用默认 octet-stream"""
        manager = _make_manager(tmp_path)
        info = manager.save(filename="file.dat", file_content=b"x")

        assert info.content_type == "application/octet-stream"

    def test_save_empty_content(self, tmp_path):
        """空内容附件 size=0"""
        manager = _make_manager(tmp_path)
        info = manager.save(filename="empty.txt", file_content=b"")

        assert info.file_size == 0
        assert Path(info.file_path).read_bytes() == b""

    def test_delete_all_attachments(self, tmp_path):
        """测试删除所有附件"""
        manager = _make_manager(tmp_path)
        infos = [manager.save(filename=f"file{i}.txt", file_content=b"x") for i in range(3)]

        for info in infos:
            manager.delete(info.attachment_id)

        assert len(manager.list()) == 0

    def test_metadata_persistence_roundtrip(self, tmp_path):
        """元数据落盘后新实例可恢复"""
        manager = _make_manager(tmp_path)
        info = manager.save(filename="test.txt", file_content=b"data", metadata={"key1": "value1"})

        manager2 = _make_manager(tmp_path)
        restored = manager2.get(info.attachment_id)
        assert restored is not None
        assert restored.metadata["key1"] == "value1"
        assert restored.filename == "test.txt"
