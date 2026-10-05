"""API 集成测试 - 健康检查端点

路径口径（2026-10-05 实测校正）：健康检查的唯一挂载事实源是
`ENDPOINT_MODULES` 里 `("neurova.api.endpoints.health", "/v1/health", ...)`，经
`endpoints/__init__.py:340` 拼成 `/api/v1/health/*`。裸 `/health` 只有两份内联端点
（`app.py` 的版本/就绪上报 + `/health/detailed`），`/health/checks` 这类路径从来不存在。
此前本文件断言的正是那批不存在的路径，且靠 lifespan 关停卡死（已修，见 b5f80e9c）
从未跑到断言，于是 404 被"路径写错"长期掩着。

鉴权口径同样实测校正：是否 401 取决于 `NEUROVA_GLOBAL_AUTH` 三态（默认 off），
所以这里把模式显式钉住再断言**单一**状态码，不再用"401/403/404/405 里任一即通过"
这种四值放宽断言（教义第 3 条禁止的写法）。
"""

import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app


@pytest.fixture
def client():
    """默认鉴权模式（off）下的测试客户端"""
    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def enforcedClient(monkeypatch, client):
    """`NEUROVA_GLOBAL_AUTH=enforce` 下的同一 app（模式每请求读取，注入即生效）"""
    monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "enforce")
    return client


class TestHealthEndpoint:
    """健康检查端点：真实挂载路径 + 真实消费者（CLI 诊断走 `/api/v1/health/report`）"""

    def test_get_health_status(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        # /health 是 API 版本上报的单源（docs_url 已移除，版本只从这里出）
        assert response.json()["version"], response.text

    def test_get_health_checks(self, client):
        response = client.get("/api/v1/health/checks")
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), list)

    def test_get_health_report(self, client):
        response = client.get("/api/v1/health/report")
        assert response.status_code == 200, response.text
        assert response.json()["status"], response.text

    def test_recover_is_not_a_fake_success(self, client):
        """`trigger_recovery` 自陈 `# TODO: 实现恢复逻辑`，却回 `success: true` +
        `"Recovery triggered"`——调用方被告知恢复已发生，实际什么都没做（教义第 2 条
        禁止的假成功）。未实现须以显式 501 + 点名原因暴露。"""
        response = client.post("/api/v1/health/recover")
        assert response.status_code == 501, response.text
        assert "未实现" in response.json()["detail"], response.text

    def test_legacyBarePathsAreNotMounted(self, client):
        """挂载点单源反证：健康检查只经 `ENDPOINT_MODULES` 挂在 `/api/v1/health`。
        裸 `/health/checks` 一旦可达，说明 `app.py` 那组旁路 include_router 又长回来了
        （2026-09 删它就是因为双前缀与缺 `/v1` 让前端必 404）。"""
        assert client.get("/health/checks").status_code == 404


class TestHealthEndpointAuth:
    """受保护面：`/api/v1/health/*` 不在精确白名单内，enforce 下必须 401"""

    def test_run_check_without_auth_is_401(self, enforcedClient):
        response = enforcedClient.post("/api/v1/health/checks/database/run")
        assert response.status_code == 401, response.text
        assert response.json()["code"] == "AUTH_FAILED"

    def test_recover_without_auth_is_401(self, enforcedClient):
        response = enforcedClient.post("/api/v1/health/recover")
        assert response.status_code == 401, response.text
        assert response.json()["code"] == "AUTH_FAILED"

    def test_bare_health_stays_public_under_enforce(self, enforcedClient):
        """白名单是精确匹配、不做前缀扩散：裸 /health 仍可匿名（桌面壳就绪探测）"""
        response = enforcedClient.get("/health")
        assert response.status_code == 200, response.text
