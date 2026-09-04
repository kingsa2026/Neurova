"""
健康检查 API 契约回归测试

回归背景（2026-09-05）：GET /v1/health/checks 恒 500 ——
HealthCheckResult（core 模型）没有 check_type 字段（它定义在检查定义
HealthCheck 上），而 API 层三个端点都读 result.check_type.value。
存量集成测试 test_api_health.py 因 create_app lifespan 在 TestClient
shutdown 时挂死而从未跑到断言，故此 bug 长期潜伏。本测试用轻量
APIRouter 挂载（不触发全量 app lifespan）直接钉住三层契约：
core 结果对象 → API 响应模型 → 端点序列化。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints.health import router as health_router
from neurova.core.health_checker import (
    CheckType,
    HealthChecker,
    HealthCheckResult,
    HealthStatus,
)


@pytest.fixture
def client():
    """轻量 app：只挂 health 路由，单例换成干净实例（不拉全量 lifespan）"""
    app = FastAPI()
    app.include_router(health_router, prefix="/health")
    from neurova.api.endpoints import health as health_mod
    checker = HealthChecker()
    checker.register(
        "database",
        lambda: (True, "OK"),
        check_type=CheckType.DEPENDENCY,
    )
    checker.register(
        "api_liveness",
        lambda: (True, "OK"),
        check_type=CheckType.LIVENESS,
    )
    # 生产时序：/health 端点先 run_all_checks 填充结果，/checks 再读结果
    checker.run_all_checks()
    orig = health_mod._get_health_checker
    health_mod._get_health_checker = lambda: checker
    with TestClient(app) as c:
        yield c
    health_mod._get_health_checker = orig


class TestHealthChecksContract:
    """/health/checks 契约：结果对象必须携带 check_type"""

    def test_get_all_checks_returns_check_type(self, client):
        """GET /health/checks 不得 500，且每项带 check_type"""
        response = client.get("/health/checks")
        assert response.status_code == 200, response.text
        items = response.json()
        assert isinstance(items, list) and len(items) == 2
        by_name = {i["name"]: i for i in items}
        assert by_name["database"]["check_type"] == "dependency"
        assert by_name["api_liveness"]["check_type"] == "liveness"

    def test_get_single_check_returns_check_type(self, client):
        """GET /health/checks/{name} 同样不得 500"""
        response = client.get("/health/checks/database")
        assert response.status_code == 200, response.text
        assert response.json()["check_type"] == "dependency"

    def test_run_check_returns_check_type(self, client):
        """POST /health/checks/{name}/run 同样不得 500"""
        response = client.post("/health/checks/database/run")
        assert response.status_code == 200, response.text
        assert response.json()["check_type"] == "dependency"


class TestHealthCheckResultCarriesCheckType:
    """core 层：结果对象应携带产生它的检查的类型"""

    def test_result_has_check_type_after_run(self):
        checker = HealthChecker()
        checker.register("db", lambda: (True, "OK"), check_type=CheckType.DEPENDENCY)

        result = checker.run_check("db")

        assert result is not None
        assert result.check_type == CheckType.DEPENDENCY

    def test_result_to_dict_includes_check_type(self):
        result = HealthCheckResult(
            name="db",
            status=HealthStatus.HEALTHY,
            check_type=CheckType.DEPENDENCY,
        )

        d = result.to_dict()

        assert d["check_type"] == "dependency"
