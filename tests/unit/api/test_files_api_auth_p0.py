"""
BE-API-005 (P0) 安全修复测试: 文件端点无认证

验证所有 /v1/files 端点都需要认证，匿名访问返回 401。
"""

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api import auth
from neurova.api.endpoints import files_api


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """创建带 files 路由的测试客户端（不依赖 create_app）"""
    monkeypatch.setattr(files_api, "STORAGE_ROOT", tmp_path / "storage/users")

    app = FastAPI()
    app.include_router(files_api.router, prefix="/v1/files")
    client = TestClient(app, raise_server_exceptions=False)
    return client


@pytest.fixture
def auth_token():
    """生成有效的认证 token"""
    return auth.create_access_token({
        "sub": "user123",
        "username": "testuser",
        "role": "user",
    })


@pytest.fixture
def auth_headers(auth_token):
    """认证请求头"""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def clean_files_store():
    """清空文件存储"""
    saved = files_api._files_store.copy()
    files_api._files_store.clear()
    yield files_api._files_store
    files_api._files_store.clear()
    files_api._files_store.update(saved)


class TestFilesEndpointAuth:
    """所有文件端点必须要求认证"""

    def test_upload_without_auth_returns_401(self, app_client, clean_files_store):
        """上传文件无认证返回 401"""
        response = app_client.post(
            "/v1/files/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 401

    def test_list_files_without_auth_returns_401(self, app_client, clean_files_store):
        """列出文件无认证返回 401"""
        response = app_client.get("/v1/files")
        assert response.status_code == 401

    def test_get_file_info_without_auth_returns_401(self, app_client, clean_files_store):
        """获取文件信息无认证返回 401"""
        response = app_client.get("/v1/files/some-id")
        assert response.status_code == 401

    def test_download_file_without_auth_returns_401(self, app_client, clean_files_store):
        """下载文件无认证返回 401"""
        response = app_client.get("/v1/files/some-id/download")
        assert response.status_code == 401

    def test_preview_file_without_auth_returns_401(self, app_client, clean_files_store):
        """预览文件无认证返回 401"""
        response = app_client.get("/v1/files/some-id/preview")
        assert response.status_code == 401

    def test_update_file_without_auth_returns_401(self, app_client, clean_files_store):
        """更新文件无认证返回 401"""
        response = app_client.put("/v1/files/some-id", json={"filename": "new.txt"})
        assert response.status_code == 401

    def test_delete_file_without_auth_returns_401(self, app_client, clean_files_store):
        """删除文件无认证返回 401"""
        response = app_client.delete("/v1/files/some-id")
        assert response.status_code == 401

    def test_get_storage_info_without_auth_returns_401(self, app_client, clean_files_store):
        """获取存储信息无认证返回 401"""
        response = app_client.get("/v1/files/storage/info")
        assert response.status_code == 401

    def test_get_file_versions_without_auth_returns_401(self, app_client, clean_files_store):
        """获取版本历史无认证返回 401"""
        response = app_client.get("/v1/files/some-id/versions")
        assert response.status_code == 401

    def test_approve_file_without_auth_returns_401(self, app_client, clean_files_store):
        """批准文件无认证返回 401"""
        response = app_client.post("/v1/files/some-id/approve")
        assert response.status_code == 401

    def test_reject_file_without_auth_returns_401(self, app_client, clean_files_store):
        """拒绝文件无认证返回 401"""
        response = app_client.post("/v1/files/some-id/reject")
        assert response.status_code == 401

    def test_upload_with_auth_not_401(self, app_client, auth_headers, clean_files_store):
        """带认证上传文件不应返回 401"""
        response = app_client.post(
            "/v1/files/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
            headers=auth_headers,
        )
        assert response.status_code != 401, "带认证不应返回 401"
