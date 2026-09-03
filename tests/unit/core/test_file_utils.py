"""
文件操作工具测试
测试文件操作相关的工具函数，包括三层隔离路径、文件元数据管理、MIME类型检测等。
"""

import pytest
import sys
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from neurova.core import file_utils


class TestSanitizeName:
    """测试名称清理函数"""

    def test_sanitize_normal_name(self):
        """测试清理普通名称"""
        name = "test_file"
        result = file_utils.sanitize_name(name)
        assert result == "test_file"

    def test_sanitize_with_special_chars(self):
        """测试清理包含特殊字符的名称"""
        name = "test@#$%file"
        result = file_utils.sanitize_name(name)
        assert result == "test____file"

    def test_sanitize_with_spaces(self):
        """测试清理包含空格的名称"""
        name = "test file name"
        result = file_utils.sanitize_name(name)
        assert result == "test_file_name"

    def test_sanitize_with_path_chars(self):
        """测试清理包含路径字符的名称"""
        name = "test/../file"
        result = file_utils.sanitize_name(name)
        assert result == "test__file"

    def test_sanitize_empty_name(self):
        """测试清理空名称"""
        name = ""
        result = file_utils.sanitize_name(name)
        assert result == "unknown"

    def test_sanitize_all_special_chars(self):
        """测试清理全部特殊字符"""
        name = "@#$%^&*()"
        result = file_utils.sanitize_name(name)
        assert result == "_________"


class TestGetIsolatedPath:
    """测试三层隔离路径获取"""

    def test_get_isolated_path_basic(self, tmp_path):
        """测试基本三层隔离路径"""
        with patch.object(file_utils, 'STORAGE_ROOT', tmp_path / "storage"):
            path = file_utils.get_isolated_path(
                user_id="user1",
                agent_id="agent1",
                session_id="session1",
                file_type="image"
            )
            
            assert path.exists()
            assert "user1" in str(path)
            assert "agent1" in str(path)
            assert "session1" in str(path)
            assert "image" in str(path)

    def test_get_isolated_path_with_special_chars(self, tmp_path):
        """测试带特殊字符的三层隔离路径"""
        with patch.object(file_utils, 'STORAGE_ROOT', tmp_path / "storage"):
            path = file_utils.get_isolated_path(
                user_id="user@123",
                agent_id="agent#456",
                session_id="session$789",
                file_type="video"
            )
            
            assert path.exists()
            assert "user_123" in str(path)
            assert "agent_456" in str(path)
            assert "session_789" in str(path)

    def test_get_isolated_path_with_none(self, tmp_path):
        """测试None值的隔离路径"""
        with patch.object(file_utils, 'STORAGE_ROOT', tmp_path / "storage"):
            path = file_utils.get_isolated_path(
                user_id="user1",
                agent_id=None,
                session_id=None,
                file_type=None
            )
            
            assert path.exists()
            assert "user1" in str(path)
            assert "default" in str(path)

    def test_get_isolated_path_different_types(self, tmp_path):
        """测试不同文件类型的路径"""
        with patch.object(file_utils, 'STORAGE_ROOT', tmp_path / "storage"):
            types = ["image", "video", "audio", "document", "other"]
            
            for file_type in types:
                path = file_utils.get_isolated_path(
                    user_id="user1",
                    agent_id="agent1",
                    session_id="session1",
                    file_type=file_type
                )
                assert path.exists()
                assert file_type in str(path)


class TestGenerateFileId:
    """测试文件ID生成"""

    def test_generate_file_id_format(self):
        """测试文件ID格式"""
        file_id = file_utils.generate_file_id()
        
        assert file_id.startswith("file_")
        assert len(file_id) == 17  # "file_" + 12位十六进制

    def test_generate_file_id_unique(self):
        """测试生成的ID唯一性"""
        ids = set()
        for _ in range(100):
            file_id = file_utils.generate_file_id()
            assert file_id not in ids
            ids.add(file_id)


class TestGetFileExtension:
    """测试文件扩展名获取"""

    def test_get_extension_with_dot(self):
        """测试带点的扩展名"""
        ext = file_utils.get_file_extension("test.txt")
        assert ext == "txt"

    def test_get_extension_without_dot(self):
        """测试不带点的扩展名"""
        ext = file_utils.get_file_extension("test.TXT")
        assert ext == "txt"

    def test_get_extension_multiple_dots(self):
        """测试多个点的文件名"""
        ext = file_utils.get_file_extension("test.file.pdf")
        assert ext == "pdf"

    def test_get_extension_no_extension(self):
        """测试无扩展名的文件"""
        ext = file_utils.get_file_extension("testfile")
        assert ext == ""

    def test_get_extension_with_path(self):
        """测试带路径的文件名"""
        ext = file_utils.get_file_extension("/path/to/test.txt")
        assert ext == "txt"


class TestDetectMimeType:
    """测试MIME类型检测"""

    def test_detect_mime_type_from_filename(self):
        """测试从文件名检测MIME类型"""
        mime = file_utils.detect_mime_type("test.txt")
        assert mime in ["text/plain", "application/octet-stream"]

    def test_detect_mime_type_pdf(self):
        """测试PDF文件的MIME类型"""
        mime = file_utils.detect_mime_type("document.pdf")
        assert mime == "application/pdf"

    def test_detect_mime_type_image(self):
        """测试图片文件的MIME类型"""
        mime = file_utils.detect_mime_type("image.png")
        assert mime == "image/png"

    def test_detect_mime_type_with_content(self):
        """测试带内容的MIME类型检测"""
        content = b"fake content"
        mime = file_utils.detect_mime_type("unknown", content)
        assert mime == "application/octet-stream"

    def test_detect_mime_type_unknown(self):
        """测试未知文件类型的MIME类型"""
        mime = file_utils.detect_mime_type("unknownfile")
        assert mime == "application/octet-stream"


class TestJsonDatabaseOperations:
    """测试JSON数据库操作"""

    def test_load_files_db_nonexistent(self, tmp_path):
        """测试加载不存在的数据库"""
        with patch.object(file_utils, 'FILES_DB', tmp_path / "files.json"):
            with patch.object(file_utils, 'DATA_DIR', tmp_path):
                data = file_utils.load_files_db()
                assert data == {}

    def test_save_and_load_files_db(self, tmp_path):
        """测试保存和加载数据库"""
        db_path = tmp_path / "files.json"
        
        with patch.object(file_utils, 'FILES_DB', db_path):
            with patch.object(file_utils, 'DATA_DIR', tmp_path):
                test_data = {
                    "file_123": {"name": "test.txt", "size": 1024},
                    "file_456": {"name": "test2.txt", "size": 2048}
                }
                
                result = file_utils.save_files_db(test_data)
                assert result is True
                
                loaded_data = file_utils.load_files_db()
                assert loaded_data == test_data

    def test_save_file_metadata(self, tmp_path):
        """测试保存文件元数据"""
        db_path = tmp_path / "files.json"
        
        with patch.object(file_utils, 'FILES_DB', db_path):
            with patch.object(file_utils, 'DATA_DIR', tmp_path):
                metadata = {"name": "test.txt", "size": 1024}
                result = file_utils.save_file_metadata("file_123", metadata)
                
                assert result is True
                
                loaded_metadata = file_utils.get_file_metadata("file_123")
                assert loaded_metadata == metadata

    def test_get_file_metadata_nonexistent(self, tmp_path):
        """测试获取不存在的文件元数据"""
        db_path = tmp_path / "files.json"
        
        with patch.object(file_utils, 'FILES_DB', db_path):
            with patch.object(file_utils, 'DATA_DIR', tmp_path):
                metadata = file_utils.get_file_metadata("nonexistent")
                assert metadata is None

    def test_delete_file_metadata(self, tmp_path):
        """测试删除文件元数据"""
        db_path = tmp_path / "files.json"
        
        with patch.object(file_utils, 'FILES_DB', db_path):
            with patch.object(file_utils, 'DATA_DIR', tmp_path):
                metadata = {"name": "test.txt"}
                file_utils.save_file_metadata("file_123", metadata)
                
                result = file_utils.delete_file_metadata("file_123")
                assert result is True
                
                loaded_metadata = file_utils.get_file_metadata("file_123")
                assert loaded_metadata is None

    def test_delete_nonexistent_file_metadata(self, tmp_path):
        """测试删除不存在的文件元数据"""
        db_path = tmp_path / "files.json"
        
        with patch.object(file_utils, 'FILES_DB', db_path):
            with patch.object(file_utils, 'DATA_DIR', tmp_path):
                result = file_utils.delete_file_metadata("nonexistent")
                assert result is False


class TestFileStorageOperations:
    """测试文件存储操作"""

    def test_save_file_to_isolated_path(self, tmp_path):
        """测试保存文件到隔离路径"""
        with patch.object(file_utils, 'STORAGE_ROOT', tmp_path / "storage"):
            with patch.object(file_utils, 'FILES_DB', tmp_path / "files.json"):
                with patch.object(file_utils, 'DATA_DIR', tmp_path):
                    content = b"test file content"
                    
                    result = file_utils.save_file_to_isolated_path(
                        user_id="user1",
                        agent_id="agent1",
                        session_id="session1",
                        file_type="document",
                        filename="test.txt",
                        content=content
                    )
                    
                    assert "file_id" in result
                    assert "storage_path" in result
                    assert "metadata" in result
                    assert result["metadata"]["name"] == "test.txt"
                    assert result["metadata"]["size"] == len(content)

    def test_load_file_from_isolated_path(self, tmp_path):
        """测试从隔离路径加载文件"""
        with patch.object(file_utils, 'STORAGE_ROOT', tmp_path / "storage"):
            with patch.object(file_utils, 'FILES_DB', tmp_path / "files.json"):
                with patch.object(file_utils, 'DATA_DIR', tmp_path):
                    content = b"test file content"
                    
                    result = file_utils.save_file_to_isolated_path(
                        user_id="user1",
                        agent_id="agent1",
                        session_id="session1",
                        file_type="document",
                        filename="test.txt",
                        content=content
                    )
                    
                    file_id = result["file_id"]
                    loaded = file_utils.load_file_from_isolated_path(file_id)
                    
                    assert loaded is not None
                    assert "file_path" in loaded
                    assert "metadata" in loaded

    def test_load_nonexistent_file(self, tmp_path):
        """测试加载不存在的文件"""
        with patch.object(file_utils, 'FILES_DB', tmp_path / "files.json"):
            with patch.object(file_utils, 'DATA_DIR', tmp_path):
                loaded = file_utils.load_file_from_isolated_path("nonexistent")
                assert loaded is None

    def test_delete_file_from_isolated_path(self, tmp_path):
        """测试从隔离路径删除文件"""
        with patch.object(file_utils, 'STORAGE_ROOT', tmp_path / "storage"):
            with patch.object(file_utils, 'FILES_DB', tmp_path / "files.json"):
                with patch.object(file_utils, 'DATA_DIR', tmp_path):
                    content = b"test file content"
                    
                    result = file_utils.save_file_to_isolated_path(
                        user_id="user1",
                        agent_id="agent1",
                        session_id="session1",
                        file_type="document",
                        filename="test.txt",
                        content=content
                    )
                    
                    file_id = result["file_id"]
                    delete_result = file_utils.delete_file_from_isolated_path(file_id)
                    
                    assert delete_result is True

    def test_delete_nonexistent_file(self, tmp_path):
        """测试删除不存在的文件"""
        with patch.object(file_utils, 'FILES_DB', tmp_path / "files.json"):
            with patch.object(file_utils, 'DATA_DIR', tmp_path):
                result = file_utils.delete_file_from_isolated_path("nonexistent")
                assert result is False


class TestGenerationFileInfo:
    """测试生成文件信息"""

    def test_get_generation_file_info_text_to_image(self):
        """测试文生图的文件信息"""
        info = file_utils.get_generation_file_info("text_to_image")
        
        assert info["file_type"] == "image"
        assert info["mime_type"] == "image/png"
        assert info["file_ext"] == "png"

    def test_get_generation_file_info_text_to_video(self):
        """测试文生视频的文件信息"""
        info = file_utils.get_generation_file_info("text_to_video")
        
        assert info["file_type"] == "video"
        assert info["mime_type"] == "video/mp4"
        assert info["file_ext"] == "mp4"

    def test_get_generation_file_info_text_to_audio(self):
        """测试文生音频的文件信息"""
        info = file_utils.get_generation_file_info("text_to_audio")
        
        assert info["file_type"] == "audio"
        assert info["mime_type"] == "audio/mpeg"
        assert info["file_ext"] == "mp3"

    def test_get_generation_file_info_unknown(self):
        """测试未知生成类型的文件信息"""
        info = file_utils.get_generation_file_info("unknown_type")
        
        assert info["file_type"] == "file"
        assert info["mime_type"] == "application/octet-stream"
        assert info["file_ext"] == "bin"


class TestEdgeCases:
    """测试边界情况"""

    def test_empty_user_id(self, tmp_path):
        """测试空用户ID"""
        with patch.object(file_utils, 'STORAGE_ROOT', tmp_path / "storage"):
            path = file_utils.get_isolated_path(
                user_id="",
                agent_id="agent1",
                session_id="session1",
                file_type="image"
            )
            assert path.exists()

    def test_very_long_filename(self, tmp_path):
        """测试超长文件名"""
        with patch.object(file_utils, 'STORAGE_ROOT', tmp_path / "storage"):
            with patch.object(file_utils, 'FILES_DB', tmp_path / "files.json"):
                with patch.object(file_utils, 'DATA_DIR', tmp_path):
                    long_filename = "a" * 1000 + ".txt"
                    content = b"test"
                    
                    result = file_utils.save_file_to_isolated_path(
                        user_id="user1",
                        agent_id="agent1",
                        session_id="session1",
                        file_type="document",
                        filename=long_filename,
                        content=content
                    )
                    
                    assert result is not None
                    assert len(result["file_id"]) > 0

    def test_special_metadata(self, tmp_path):
        """测试特殊字符元数据"""
        with patch.object(file_utils, 'STORAGE_ROOT', tmp_path / "storage"):
            with patch.object(file_utils, 'FILES_DB', tmp_path / "files.json"):
                with patch.object(file_utils, 'DATA_DIR', tmp_path):
                    content = b"test"
                    metadata = {
                        "description": "测试@#$%^&*()文件",
                        "custom_key": "特殊值"
                    }
                    
                    result = file_utils.save_file_to_isolated_path(
                        user_id="user1",
                        agent_id="agent1",
                        session_id="session1",
                        file_type="document",
                        filename="test.txt",
                        content=content,
                        metadata=metadata
                    )
                    
                    assert result["metadata"]["description"] == "测试@#$%^&*()文件"
