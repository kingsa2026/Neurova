"""
#7 删除 /v1/chat/sessions 死端点测试

背景:
    neurova/api/endpoints/chat.py 中有 4 个 /sessions 端点:
    - GET /sessions (line 262-327) — 与 console.py /chat/sessions 重复
    - POST /sessions (line 330-401) — 与 console.py /chat/sessions(POST)重复
    - PUT /sessions/{session_id} (line 404-437) — 纯 stub,注释说"我们没有实际的会话存储"
    - DELETE /sessions/{session_id} (line 440-469) — 纯 stub,注释说"我们没有实际的会话存储"

    完整路径:/api/v1/chat/sessions(因 chat.py 路由前缀是 /api/v1/chat)

    前端只用 /api/v1/console/chat/sessions(console.py 路由,已通过 SessionRepository 接入真实存储)。
    所有测试也只用 /console/chat/sessions。
    chat.py 的 4 个 /sessions 端点无前端调用方,无测试依赖。

    PUT/DELETE 是 stub,根本不操作任何数据(返回硬编码成功)。
    GET/POST 重复 console.py 功能,且 GET 用 hasattr(agent, "get_sessions") 守卫
    (Agent 类没有 get_sessions 方法,只有 session_manager 属性)。

Deletion test:
    删除后 complexity 转移到 console.py(已通过 SessionRepository 接入真实存储)。
    这是 pass-through,应删。

TDD RED 阶段:本测试在删除前应全部失败(确认端点仍存在)。
TDD GREEN 阶段:删除 4 个端点后,本测试应全部通过。
"""

import inspect

import pytest

# chat.py 模块路径
CHAT_MODULE_PATH = "neurova/api/endpoints/chat.py"


# ---------------------------------------------------------------------------
# RED 测试:验证 4 个死端点已从 chat.py 中删除
# ---------------------------------------------------------------------------


class TestDeadEndpointsRemoved:
    """验证 4 个 /sessions 死端点已从 chat.py 中删除"""

    def test_chat_source_no_get_sessions_endpoint(self):
        """RED: chat.py 不应包含 GET /sessions 端点"""
        with open(CHAT_MODULE_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        assert '@router.get("/sessions")' not in content, (
            "#7 失败:chat.py 仍包含 GET /sessions 死端点"
        )

    def test_chat_source_no_post_sessions_endpoint(self):
        """RED: chat.py 不应包含 POST /sessions 端点"""
        with open(CHAT_MODULE_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        assert '@router.post("/sessions")' not in content, (
            "#7 失败:chat.py 仍包含 POST /sessions 死端点"
        )

    def test_chat_source_no_put_sessions_endpoint(self):
        """RED: chat.py 不应包含 PUT /sessions/{session_id} 端点"""
        with open(CHAT_MODULE_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        assert '@router.put("/sessions/{session_id}")' not in content, (
            "#7 失败:chat.py 仍包含 PUT /sessions/{session_id} 死端点"
        )

    def test_chat_source_no_delete_sessions_endpoint(self):
        """RED: chat.py 不应包含 DELETE /sessions/{session_id} 端点"""
        with open(CHAT_MODULE_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        assert '@router.delete("/sessions/{session_id}")' not in content, (
            "#7 失败:chat.py 仍包含 DELETE /sessions/{session_id} 死端点"
        )


class TestDeadEndpointFunctionsRemoved:
    """验证 4 个死端点函数已从 chat.py 模块中删除"""

    def test_chat_module_no_get_chat_sessions_function(self):
        """RED: chat 模块不应再有 get_chat_sessions 函数"""
        from neurova.api.endpoints import chat

        assert not hasattr(chat, "get_chat_sessions"), (
            "#7 失败:chat 模块仍包含 get_chat_sessions 函数"
        )

    def test_chat_module_no_create_chat_session_function(self):
        """RED: chat 模块不应再有 create_chat_session 函数"""
        from neurova.api.endpoints import chat

        assert not hasattr(chat, "create_chat_session"), (
            "#7 失败:chat 模块仍包含 create_chat_session 函数"
        )

    def test_chat_module_no_rename_chat_session_function(self):
        """RED: chat 模块不应再有 rename_chat_session 函数"""
        from neurova.api.endpoints import chat

        assert not hasattr(chat, "rename_chat_session"), (
            "#7 失败:chat 模块仍包含 rename_chat_session 函数"
        )

    def test_chat_module_no_delete_chat_session_function(self):
        """RED: chat 模块不应再有 delete_chat_session 函数"""
        from neurova.api.endpoints import chat

        assert not hasattr(chat, "delete_chat_session"), (
            "#7 失败:chat 模块仍包含 delete_chat_session 函数"
        )


# ---------------------------------------------------------------------------
# GREEN 守卫:验证保留的端点(/history, POST /, /stream)不受影响
# ---------------------------------------------------------------------------


class TestPreservedEndpointsIntact:
    """验证保留的端点(POST "", POST /stream, GET /history 等)不受影响"""

    def test_chat_module_still_has_chat_endpoint(self):
        """GREEN 守卫:POST "" 端点(chat)应仍然存在"""
        from neurova.api.endpoints import chat

        # 检查路由表中是否还有 POST "" 端点
        routes = [(r.methods, r.path) for r in chat.router.routes]
        post_chat_exists = any(
            methods and "POST" in methods and path == ""
            for methods, path in routes
        )
        assert post_chat_exists, (
            f"GREEN 守卫失败:POST '' 端点应保留,但路由表: {routes}"
        )

    def test_chat_module_still_has_stream_endpoint(self):
        """GREEN 守卫:POST /stream 端点应仍然存在"""
        from neurova.api.endpoints import chat

        routes = [(r.methods, r.path) for r in chat.router.routes]
        stream_exists = any(
            methods and "POST" in methods and path == "/stream"
            for methods, path in routes
        )
        assert stream_exists, (
            f"GREEN 守卫失败:POST /stream 端点应保留,但路由表: {routes}"
        )

    def test_chat_module_still_has_history_endpoint(self):
        """GREEN 守卫:GET /history 端点应仍然存在"""
        from neurova.api.endpoints import chat

        routes = [(r.methods, r.path) for r in chat.router.routes]
        history_exists = any(
            methods and "GET" in methods and path == "/history"
            for methods, path in routes
        )
        assert history_exists, (
            f"GREEN 守卫失败:GET /history 端点应保留,但路由表: {routes}"
        )
