"""
BE-API-004 (P0) 安全修复测试: 文件上传路径遍历漏洞

验证 file.filename 含 ../../ 时不能逃逸 storage_dir。
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

# 设置测试环境变量
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")


@pytest.fixture
def clean_files_store():
    """清空文件存储，隔离测试"""
    from neurova.api.endpoints import files_api
    saved = files_api._files_store.copy()
    files_api._files_store.clear()
    yield files_api._files_store
    files_api._files_store.clear()
    files_api._files_store.update(saved)


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    """将 STORAGE_ROOT 重定向到临时目录"""
    from neurova.api.endpoints import files_api
    monkeypatch.setattr(files_api, "STORAGE_ROOT", tmp_path / "storage/users")
    return tmp_path


def _make_upload_file(filename: str, content: bytes = b"test content") -> UploadFile:
    """构造 UploadFile mock"""
    uf = MagicMock(spec=UploadFile)
    uf.filename = filename
    uf.read = AsyncMock(return_value=content)
    return uf


def _current_user(user_id: str = "u1") -> dict:
    """构造 current_user dict（模拟 Depends(get_current_user) 的返回值）"""
    return {"user_id": user_id, "username": "testuser", "role": "user"}


class TestUploadFilePathTraversal:
    """上传文件时 file.filename 含路径分隔符不能逃逸存储目录"""

    @pytest.mark.asyncio
    async def test_filename_with_deep_dotdot_traversal_stays_in_file_dir(self, isolated_storage, clean_files_store):
        """深层 ../../../../../../evil.txt 不能逃逸到 storage_root 之外"""
        from neurova.api.endpoints.files_api import upload_file, STORAGE_ROOT

        # 从 file 目录到 storage_root 之外需要 6+ 层 ../
        evil_filename = "../../../../../../evil.txt"
        file = _make_upload_file(evil_filename, b"pwned")

        info = await upload_file(file=file, agent_id="a1", session_id="s1", current_user=_current_user())

        saved_path = Path(info.path).resolve()
        expected_root = STORAGE_ROOT.resolve()
        # 核心断言：最终路径必须在 storage_root 内
        assert saved_path.is_relative_to(expected_root), (
            f"路径遍历漏洞：{saved_path} 不在 {expected_root} 内"
        )
        # 验证文件没有写到 storage_root 之外
        evil_outside = isolated_storage / "evil.txt"
        assert not evil_outside.exists(), "路径遍历成功：文件被写到 storage_root 之外"

    @pytest.mark.asyncio
    async def test_filename_sanitized_to_basename(self, isolated_storage, clean_files_store):
        """info.filename 应只保留 basename，不含路径分隔符或 .."""
        from neurova.api.endpoints.files_api import upload_file

        evil_filename = "../../evil.txt"
        file = _make_upload_file(evil_filename, b"pwned")

        info = await upload_file(file=file, agent_id="a1", session_id="s1", current_user=_current_user())

        # info.filename 必须是净化后的 basename
        assert "/" not in info.filename, f"filename 含正斜杠: {info.filename}"
        assert "\\" not in info.filename, f"filename 含反斜杠: {info.filename}"
        assert ".." not in info.filename, f"filename 含 ..: {info.filename}"
        assert info.filename == "evil.txt"

    @pytest.mark.asyncio
    async def test_filename_with_backslash_traversal_stays_in_storage(self, isolated_storage, clean_files_store):
        """Windows 风格 ..\\..\\evil.txt 也不能逃逸"""
        from neurova.api.endpoints.files_api import upload_file, STORAGE_ROOT

        evil_filename = "..\\..\\evil.txt"
        file = _make_upload_file(evil_filename, b"pwned")

        info = await upload_file(file=file, agent_id="a1", session_id="s1", current_user=_current_user())

        saved_path = Path(info.path).resolve()
        expected_root = STORAGE_ROOT.resolve()
        assert saved_path.is_relative_to(expected_root), (
            f"路径遍历漏洞：{saved_path} 不在 {expected_root} 内"
        )
        assert "\\" not in info.filename

    @pytest.mark.asyncio
    async def test_filename_with_absolute_path_sanitized(self, isolated_storage, clean_files_store):
        """绝对路径 /etc/passwd 应被净化为 passwd"""
        from neurova.api.endpoints.files_api import upload_file, STORAGE_ROOT

        evil_filename = "/etc/passwd"
        file = _make_upload_file(evil_filename, b"pwned")

        info = await upload_file(file=file, agent_id="a1", session_id="s1", current_user=_current_user())

        saved_path = Path(info.path).resolve()
        expected_root = STORAGE_ROOT.resolve()
        assert saved_path.is_relative_to(expected_root), (
            f"路径遍历漏洞：{saved_path} 不在 {expected_root} 内"
        )
        # 绝对路径应被净化为 basename
        assert "/" not in info.filename
        assert info.filename == "passwd"

    @pytest.mark.asyncio
    async def test_normal_filename_works(self, isolated_storage, clean_files_store):
        """正常文件名应正常上传"""
        from neurova.api.endpoints.files_api import upload_file

        file = _make_upload_file("normal.txt", b"hello")
        info = await upload_file(file=file, agent_id="a1", session_id="s1", current_user=_current_user())
        assert info.filename == "normal.txt"
        assert Path(info.path).exists()
        assert Path(info.path).read_bytes() == b"hello"
