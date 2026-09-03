"""
API标准单元测试
测试 API 标准的各种功能
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import uuid
import time

from neurova.core.api_standard import (
    APIVersion,
    HTTPMethod,
    APIRequest,
    APIResponse,
    PageRequest,
    PageResponse,
    AuthToken,
    APIClient,
    ModuleAPI
)
from neurova.core.error_handler import ErrorCode, NeurovaError


class TestAPIVersion:
    """测试API版本枚举"""

    def test_api_version_values(self):
        """测试API版本值"""
        assert APIVersion.V1.value == "v1"
        assert APIVersion.V2.value == "v2"


class TestHTTPMethod:
    """测试HTTP方法枚举"""

    def test_http_method_values(self):
        """测试HTTP方法值"""
        assert HTTPMethod.GET.value == "GET"
        assert HTTPMethod.POST.value == "POST"
        assert HTTPMethod.PUT.value == "PUT"
        assert HTTPMethod.PATCH.value == "PATCH"
        assert HTTPMethod.DELETE.value == "DELETE"


class TestAPIRequest:
    """测试API请求类"""

    def test_create_api_request(self):
        """测试创建API请求"""
        request = APIRequest(
            method=HTTPMethod.GET,
            path="/api/v1/test",
            params={"key": "value"},
            body={"data": "test"},
            headers={"Authorization": "Bearer token"},
            version=APIVersion.V1,
            module_id="test_module"
        )
        assert request.method == HTTPMethod.GET
        assert request.path == "/api/v1/test"
        assert request.params == {"key": "value"}
        assert request.body == {"data": "test"}
        assert request.headers == {"Authorization": "Bearer token"}
        assert request.version == APIVersion.V1
        assert request.module_id == "test_module"
        assert request.request_id is not None
        assert request.timestamp is not None

    def test_to_dict(self):
        """测试转换为字典"""
        request = APIRequest(
            method=HTTPMethod.GET,
            path="/api/v1/test",
            request_id="test-id-123"
        )
        data = request.to_dict()
        assert data["method"] == "GET"
        assert data["path"] == "/api/v1/test"
        assert data["request_id"] == "test-id-123"
        assert data["version"] == "v1"


class TestAPIResponse:
    """测试API响应类"""

    def test_create_success_response(self):
        """测试创建成功响应"""
        response = APIResponse(
            success=True,
            data={"result": "success"},
            request_id="test-id-123"
        )
        assert response.success is True
        assert response.data == {"result": "success"}
        assert response.error is None
        assert response.error_code is None
        assert response.request_id == "test-id-123"

    def test_create_error_response(self):
        """测试创建错误响应"""
        response = APIResponse(
            success=False,
            error="Something went wrong",
            error_code=ErrorCode.INVALID_ARGUMENT,
            request_id="test-id-456"
        )
        assert response.success is False
        assert response.data is None
        assert response.error == "Something went wrong"
        assert response.error_code == ErrorCode.INVALID_ARGUMENT

    def test_ok_classmethod(self):
        """测试ok类方法"""
        response = APIResponse.ok(data={"result": "ok"}, request_id="test-id")
        assert response.success is True
        assert response.data == {"result": "ok"}
        assert response.request_id == "test-id"

    def test_error_classmethod(self):
        """测试error类方法"""
        response = APIResponse.error(
            error="Error message",
            code=ErrorCode.INVALID_ARGUMENT,
            request_id="test-id"
        )
        assert response.success is False
        assert response.error == "Error message"
        assert response.error_code == ErrorCode.INVALID_ARGUMENT

    def test_from_exception_with_neurova_error(self):
        """测试从NeurovaError创建响应"""
        error = NeurovaError(
            message="Test error",
            code=ErrorCode.INVALID_ARGUMENT
        )
        response = APIResponse.from_exception(error, request_id="test-id")
        assert response.success is False
        assert response.error == "Test error"
        assert response.error_code == ErrorCode.INVALID_ARGUMENT

    def test_from_exception_with_value_error(self):
        """测试从ValueError创建响应"""
        error = ValueError("Invalid value")
        response = APIResponse.from_exception(error, request_id="test-id")
        assert response.success is False
        assert "Invalid value" in response.error
        assert response.error_code == ErrorCode.INVALID_ARGUMENT

    def test_from_exception_with_key_error(self):
        """测试从KeyError创建响应"""
        error = KeyError("key")
        response = APIResponse.from_exception(error, request_id="test-id")
        assert response.success is False
        assert response.error_code == ErrorCode.INVALID_ARGUMENT

    def test_from_exception_with_timeout_error(self):
        """测试从TimeoutError创建响应"""
        error = TimeoutError("Timeout")
        response = APIResponse.from_exception(error, request_id="test-id")
        assert response.success is False
        assert response.error_code == ErrorCode.UNKNOWN_ERROR

    def test_from_exception_with_generic_exception(self):
        """测试从通用异常创建响应"""
        error = Exception("Generic error")
        response = APIResponse.from_exception(error, request_id="test-id")
        assert response.success is False
        assert response.error == "Generic error"
        assert response.error_code == ErrorCode.UNKNOWN_ERROR

    def test_to_dict(self):
        """测试转换为字典"""
        response = APIResponse(
            success=True,
            data={"result": "test"},
            metadata={"extra": "info"}
        )
        data = response.to_dict()
        assert data["success"] is True
        assert data["data"] == {"result": "test"}
        assert data["metadata"] == {"extra": "info"}


class TestPageRequest:
    """测试分页请求类"""

    def test_create_page_request_defaults(self):
        """测试创建默认分页请求"""
        request = PageRequest()
        assert request.page == 1
        assert request.page_size == 20
        assert request.sort_by is None
        assert request.sort_order == "asc"

    def test_create_page_request_custom(self):
        """测试创建自定义分页请求"""
        request = PageRequest(
            page=2,
            page_size=50,
            sort_by="created_at",
            sort_order="desc"
        )
        assert request.page == 2
        assert request.page_size == 50
        assert request.sort_by == "created_at"
        assert request.sort_order == "desc"

    def test_to_dict(self):
        """测试转换为字典"""
        request = PageRequest(
            page=3,
            page_size=10,
            sort_by="name",
            sort_order="asc"
        )
        data = request.to_dict()
        assert data["page"] == 3
        assert data["page_size"] == 10
        assert data["sort_by"] == "name"
        assert data["sort_order"] == "asc"


class TestPageResponse:
    """测试分页响应类"""

    def test_create_page_response(self):
        """测试创建分页响应"""
        response = PageResponse(
            items=[1, 2, 3, 4, 5],
            total=25,
            page=1,
            page_size=5
        )
        assert response.items == [1, 2, 3, 4, 5]
        assert response.total == 25
        assert response.page == 1
        assert response.page_size == 5

    def test_total_pages(self):
        """测试总页数计算"""
        response = PageResponse(
            items=[],
            total=25,
            page=1,
            page_size=5
        )
        assert response.total_pages == 5

    def test_total_pages_zero_size(self):
        """测试零页大小的总页数"""
        response = PageResponse(
            items=[],
            total=25,
            page=1,
            page_size=0
        )
        assert response.total_pages == 0

    def test_has_next_true(self):
        """测试有下一页"""
        response = PageResponse(
            items=[],
            total=25,
            page=1,
            page_size=5
        )
        assert response.has_next is True

    def test_has_next_false(self):
        """测试无下一页"""
        response = PageResponse(
            items=[],
            total=25,
            page=5,
            page_size=5
        )
        assert response.has_next is False

    def test_has_prev_true(self):
        """测试有上一页"""
        response = PageResponse(
            items=[],
            total=25,
            page=2,
            page_size=5
        )
        assert response.has_prev is True

    def test_has_prev_false(self):
        """测试无上一页"""
        response = PageResponse(
            items=[],
            total=25,
            page=1,
            page_size=5
        )
        assert response.has_prev is False

    def test_to_dict(self):
        """测试转换为字典"""
        response = PageResponse(
            items=[1, 2, 3],
            total=10,
            page=1,
            page_size=5
        )
        data = response.to_dict()
        assert data["items"] == [1, 2, 3]
        assert data["total"] == 10
        assert data["page"] == 1
        assert data["page_size"] == 5
        assert data["total_pages"] == 2
        assert data["has_next"] is True
        assert data["has_prev"] is False


class TestAuthToken:
    """测试认证令牌类"""

    def test_create_auth_token(self):
        """测试创建认证令牌"""
        token = AuthToken(
            token="secret-token-123",
            token_type="Bearer",
            expires_at=time.time() + 3600,
            scope=["read", "write"],
            module_id="test_module"
        )
        assert token.token == "secret-token-123"
        assert token.token_type == "Bearer"
        assert token.scope == ["read", "write"]
        assert token.module_id == "test_module"

    def test_is_expired_false(self):
        """测试未过期"""
        token = AuthToken(
            token="test",
            expires_at=time.time() + 3600
        )
        assert token.is_expired is False

    def test_is_expired_true(self):
        """测试已过期"""
        token = AuthToken(
            token="test",
            expires_at=time.time() - 3600
        )
        assert token.is_expired is True

    def test_is_expired_zero(self):
        """测试零过期时间（永不过期）"""
        token = AuthToken(
            token="test",
            expires_at=0
        )
        assert token.is_expired is False

    def test_to_header(self):
        """测试转换为请求头"""
        token = AuthToken(
            token="my-token",
            token_type="Bearer"
        )
        header = token.to_header()
        assert header["Authorization"] == "Bearer my-token"


class TestAPIClientAbstract:
    """测试APIClient抽象基类"""

    def test_cannot_instantiate_abstract(self):
        """测试不能实例化抽象类"""
        with pytest.raises(TypeError):
            APIClient()


class TestModuleAPIAbstract:
    """测试ModuleAPI抽象基类"""

    def test_cannot_instantiate_abstract(self):
        """测试不能实例化抽象类"""
        with pytest.raises(TypeError):
            ModuleAPI()


class TestConcreteAPIClient:
    """测试具体的APIClient实现"""

    class ConcreteAPIClient(APIClient):
        """具体的API客户端实现"""

        def __init__(self):
            self.requests_made = []
            self.authenticated = False

        async def request(self, req: APIRequest) -> APIResponse:
            self.requests_made.append(req)
            return APIResponse.ok(data={"success": True}, request_id=req.request_id)

        async def get(self, path: str, params=None, **kwargs) -> APIResponse:
            req = APIRequest(
                method=HTTPMethod.GET,
                path=path,
                params=params
            )
            return await self.request(req)

        async def post(self, path: str, body=None, **kwargs) -> APIResponse:
            req = APIRequest(
                method=HTTPMethod.POST,
                path=path,
                body=body
            )
            return await self.request(req)

        async def put(self, path: str, body=None, **kwargs) -> APIResponse:
            req = APIRequest(
                method=HTTPMethod.PUT,
                path=path,
                body=body
            )
            return await self.request(req)

        async def delete(self, path: str, **kwargs) -> APIResponse:
            req = APIRequest(
                method=HTTPMethod.DELETE,
                path=path
            )
            return await self.request(req)

        async def authenticate(self, token: AuthToken) -> bool:
            self.authenticated = True
            return True

    @pytest.fixture
    def client(self):
        """创建具体的API客户端"""
        return self.ConcreteAPIClient()

    @pytest.mark.asyncio
    async def test_get_request(self, client):
        """测试GET请求"""
        response = await client.get("/api/test", params={"key": "value"})
        assert response.success is True
        assert len(client.requests_made) == 1
        assert client.requests_made[0].method == HTTPMethod.GET
        assert client.requests_made[0].path == "/api/test"

    @pytest.mark.asyncio
    async def test_post_request(self, client):
        """测试POST请求"""
        response = await client.post("/api/test", body={"data": "test"})
        assert response.success is True
        assert len(client.requests_made) == 1
        assert client.requests_made[0].method == HTTPMethod.POST

    @pytest.mark.asyncio
    async def test_put_request(self, client):
        """测试PUT请求"""
        response = await client.put("/api/test", body={"data": "test"})
        assert response.success is True
        assert len(client.requests_made) == 1
        assert client.requests_made[0].method == HTTPMethod.PUT

    @pytest.mark.asyncio
    async def test_delete_request(self, client):
        """测试DELETE请求"""
        response = await client.delete("/api/test")
        assert response.success is True
        assert len(client.requests_made) == 1
        assert client.requests_made[0].method == HTTPMethod.DELETE

    @pytest.mark.asyncio
    async def test_authenticate(self, client):
        """测试认证"""
        token = AuthToken(token="test-token")
        result = await client.authenticate(token)
        assert result is True
        assert client.authenticated is True


class TestConcreteModuleAPI:
    """测试具体的ModuleAPI实现"""

    class ConcreteModuleAPI(ModuleAPI):
        """具体的模块API实现"""

        def __init__(self):
            self.requests_handled = []

        @property
        def api_version(self) -> APIVersion:
            return APIVersion.V1

        async def handle_request(self, request: APIRequest) -> APIResponse:
            self.requests_handled.append(request)
            return APIResponse.ok(data={"handled": True}, request_id=request.request_id)

        def get_api_routes(self) -> dict:
            return {
                "/test": HTTPMethod.GET,
                "/data": HTTPMethod.POST
            }

    @pytest.fixture
    def module_api(self):
        """创建具体的模块API"""
        return self.ConcreteModuleAPI()

    def test_api_version(self, module_api):
        """测试API版本"""
        assert module_api.api_version == APIVersion.V1

    def test_get_api_routes(self, module_api):
        """测试获取API路由"""
        routes = module_api.get_api_routes()
        assert "/test" in routes
        assert "/data" in routes
        assert routes["/test"] == HTTPMethod.GET
        assert routes["/data"] == HTTPMethod.POST

    @pytest.mark.asyncio
    async def test_handle_request(self, module_api):
        """测试处理请求"""
        request = APIRequest(
            method=HTTPMethod.GET,
            path="/test"
        )
        response = await module_api.handle_request(request)
        assert response.success is True
        assert len(module_api.requests_handled) == 1
        assert module_api.requests_handled[0] is request
