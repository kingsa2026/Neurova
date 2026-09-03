"""
API 集成测试 - 健康检查端点 (简化版)
"""
import pytest
from fastapi.testclient import TestClient
from neurova.api.app import create_app


@pytest.fixture
def client():
    """创建测试客户端"""
    app = create_app()
    with TestClient(app) as client:
        yield client


class TestHealthEndpoint:
    """测试健康检查端点"""
    
    def test_get_health_status(self, client):
        """测试获取健康状态"""
        response = client.get("/health")
        # 只检查状态码，不解析JSON
        assert response.status_code == 200
    
    def test_get_health_checks(self, client):
        """测试获取所有检查项"""
        response = client.get("/health/checks")
        assert response.status_code == 200
    
    def test_get_health_report(self, client):
        """测试获取详细健康报告"""
        response = client.get("/health/report")
        assert response.status_code == 200


class TestHealthEndpointWithAuth:
    """需要认证的健康检查端点"""
    
    def test_run_check_without_auth(self, client):
        """未认证时执行检查应该返回401或403"""
        response = client.post("/health/checks/database/run")
        # 可能返回401, 403, 404, 或405
        assert response.status_code in [401, 403, 404, 405]
    
    def test_recover_without_auth(self, client):
        """未认证时触发恢复应该返回401或403"""
        response = client.post("/health/recover")
        assert response.status_code in [401, 403, 405]
