"""
附件管理器测试
测试 AttachmentManager 的各种功能，包括附件保存、查询、删除等。
"""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from neurova.core.attachment_manager import (
    AttachmentManager,
    AttachmentInfo,
    get_attachment_manager
)


class TestAttachmentInfo:
    """测试附件信息"""

    def test_create_attachment_info(self):
        """测试创建附件信息"""
        info = AttachmentInfo(
            attachment_id="test-id",
            filename="test.txt",
            content_type="text/plain",
            size=1024,
            metadata={"key": "value"}
        )
        assert info.attachment_id == "test-id"
        assert info.filename == "test.txt"
        assert info.content_type == "text/plain"
        assert info.size == 1024
        assert info.metadata == {"key": "value"}

    def test_attachment_info_to_dict(self):
        """测试附件信息转换为字典"""
        info = AttachmentInfo(
            attachment_id="test-id",
            filename="test.txt",
            content_type="text/plain"
        )
        data = info.to_dict()
        assert data['attachment_id'] == "test-id"
        assert data['filename'] == "test.txt"
        assert data['content_type'] == "text/plain"
        assert 'created_at' in data


class TestAttachmentManager:
    """测试附件管理器"""

    @pytest.fixture
    def attachment_manager(self, mock_event_bus):
        """创建附件管理器实例"""
        return AttachmentManager(event_bus=mock_event_bus)

    def test_init(self, attachment_manager):
        """测试初始化"""
        assert attachment_manager is not None
        assert len(attachment_manager._attachments) == 0

    def test_save_attachment(self, attachment_manager):
        """测试保存附件"""
        attachment_id = attachment_manager.save(
            filename="test.txt",
            content_type="text/plain",
            size=1024
        )
        assert attachment_id is not None
        assert len(attachment_manager._attachments) == 1
        assert attachment_id in attachment_manager._attachments

    def test_save_with_metadata(self, attachment_manager):
        """测试保存带元数据的附件"""
        metadata = {"user_id": "123", "category": "document"}
        attachment_id = attachment_manager.save(
            filename="document.pdf",
            content_type="application/pdf",
            metadata=metadata
        )
        
        attachment = attachment_manager.get(attachment_id)
        assert attachment is not None
        assert attachment.metadata == metadata

    def test_get_attachment(self, attachment_manager):
        """测试获取附件"""
        attachment_id = attachment_manager.save(
            filename="test.txt",
            content_type="text/plain"
        )
        
        attachment = attachment_manager.get(attachment_id)
        assert attachment is not None
        assert attachment.attachment_id == attachment_id
        assert attachment.filename == "test.txt"

    def test_get_nonexistent_attachment(self, attachment_manager):
        """测试获取不存在的附件"""
        attachment = attachment_manager.get("non-existent-id")
        assert attachment is None

    def test_list_attachments(self, attachment_manager):
        """测试列出所有附件"""
        attachment_manager.save(filename="file1.txt")
        attachment_manager.save(filename="file2.txt")
        attachment_manager.save(filename="file3.txt")
        
        attachments = attachment_manager.list()
        assert len(attachments) == 3

    def test_delete_attachment(self, attachment_manager):
        """测试删除附件"""
        attachment_id = attachment_manager.save(filename="test.txt")
        assert len(attachment_manager._attachments) == 1
        
        result = attachment_manager.delete(attachment_id)
        assert result is True
        assert len(attachment_manager._attachments) == 0

    def test_delete_nonexistent_attachment(self, attachment_manager):
        """测试删除不存在的附件"""
        result = attachment_manager.delete("non-existent-id")
        assert result is False

    def test_multiple_attachments(self, attachment_manager):
        """测试多个附件"""
        ids = []
        for i in range(5):
            attachment_id = attachment_manager.save(
                filename=f"file{i}.txt",
                content_type="text/plain"
            )
            ids.append(attachment_id)
        
        assert len(attachment_manager.list()) == 5
        
        for i, attachment_id in enumerate(ids):
            attachment = attachment_manager.get(attachment_id)
            assert attachment is not None
            assert attachment.filename == f"file{i}.txt"


class TestGetAttachmentManager:
    """测试获取附件管理器单例"""

    def test_get_attachment_manager(self):
        """测试获取附件管理器实例"""
        manager1 = get_attachment_manager()
        manager2 = get_attachment_manager()
        assert manager1 is manager2


class TestEdgeCases:
    """测试边界情况"""

    def test_save_empty_filename(self):
        """测试保存空文件名"""
        manager = AttachmentManager()
        attachment_id = manager.save(filename="")
        assert attachment_id is not None

    def test_save_none_content_type(self):
        """测试保存无内容类型"""
        manager = AttachmentManager()
        attachment_id = manager.save(filename="file.dat")
        attachment = manager.get(attachment_id)
        assert attachment.content_type is None

    def test_save_none_size(self):
        """测试保存无大小"""
        manager = AttachmentManager()
        attachment_id = manager.save(filename="file.dat")
        attachment = manager.get(attachment_id)
        assert attachment.size is None

    def test_delete_all_attachments(self):
        """测试删除所有附件"""
        manager = AttachmentManager()
        for i in range(3):
            manager.save(filename=f"file{i}.txt")
        
        assert len(manager.list()) == 3
        
        for attachment in manager.list():
            manager.delete(attachment.attachment_id)
        
        assert len(manager.list()) == 0

    def test_update_attachment_metadata(self):
        """测试更新附件元数据"""
        manager = AttachmentManager()
        attachment_id = manager.save(
            filename="test.txt",
            metadata={"key1": "value1"}
        )
        
        attachment = manager.get(attachment_id)
        assert attachment.metadata["key1"] == "value1"
