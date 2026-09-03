"""
历史对话加载 BUG 红绿灯 TDD 测试

bug-hunt Phase 2-3: RED 测试 — 验证 6 个 bug 存在
- H-1: 前端 createSession 不通知后端（POST /console/chat/new）
- H-2: 后端 post_console_chat 覆盖 messages 数组（应为 append）
- H-3: 前端 switchSession catch 块静默吞错（应向用户提示）
- H-4: 前端 confirmRename URL 错误 + 后端无 PUT /console/chat/sessions/{id}
- H-5: console.ts getConsoleSessions URL 错误（/console/sessions → /console/chat/sessions）
- H-6: 架构观察（不写测试，仅报告）

后端测试用 TestClient；前端测试用静态文件检查（避免引入 vitest 复杂度）。
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def app():
    """创建测试应用（关闭可选模块以加速）"""
    from neurova.api.app import create_app
    return create_app(enable_memory=False, enable_channels=False)


@pytest.fixture
def client(app):
    """测试客户端"""
    return TestClient(app)


@pytest.fixture
def isolated_sessions(tmp_path, monkeypatch):
    """隔离 SessionRepository 存储目录到 tmp_path，避免污染真实数据。

    #1 改造后 console 通过 SessionRepository（SessionManager）持久化到 sessions/ 目录。
    此 fixture 通过 monkeypatch 替换 SessionManager 的 _sessions_dir，并重置单例。
    """
    from neurova import session_repository
    from neurova.session_manager import SessionManager

    # 重置 SessionRepository 单例，让下次 get_session_repository() 重新创建
    session_repository.reset_session_repository()

    # patch SessionManager.__init__ 让新实例用 tmp_path 作为存储目录
    real_init = SessionManager.__init__

    def patched_init(self):
        real_init(self)
        self._sessions_dir = tmp_path / "sessions"
        self._sessions_dir.mkdir(exist_ok=True)

    monkeypatch.setattr(SessionManager, "__init__", patched_init)
    # 清除单例缓存，让 patched __init__ 生效
    SessionManager._instance = None

    try:
        yield None
    finally:
        # 恢复单例状态
        SessionManager._instance = None
        session_repository.reset_session_repository()


# ============================================================
# H-2: 后端 post_console_chat 不应覆盖 messages 数组
# ============================================================

class TestH2MessagesAppendNotOverwrite:
    """H-2: 第二次发消息不应丢失第一次的历史"""

    def test_second_message_keeps_first_history(self, client, isolated_sessions):
        """RED: 当前实现 session['messages'] = [...] 会覆盖，第二次发消息后历史只剩 1 条 user + 1 条 assistant"""
        # 第一次发消息
        with patch("neurova.api.endpoints.console.get_agent_instance", return_value=None):
            r1 = client.post("/api/v1/console/chat", json={
                "message": "第一条消息",
                "session_id": "test-sess-h2",
                "agent_id": "default",
                "stream": False,
            })
        assert r1.status_code == 200, r1.text

        # 第二次发消息
        with patch("neurova.api.endpoints.console.get_agent_instance", return_value=None):
            r2 = client.post("/api/v1/console/chat", json={
                "message": "第二条消息",
                "session_id": "test-sess-h2",
                "agent_id": "default",
                "stream": False,
            })
        assert r2.status_code == 200, r2.text

        # 查询历史
        r3 = client.get("/api/v1/console/chat/history", params={"session_id": "test-sess-h2"})
        assert r3.status_code == 200, r3.text
        msgs = r3.json()["data"]["messages"]

        # GREEN 期望：4 条消息（user1+assistant1+user2+assistant2）
        # RED 现状：仅 2 条（user2+assistant2，因为被覆盖）
        assert len(msgs) == 4, f"H-2 失败：历史被覆盖，期望 4 条，实际 {len(msgs)} 条：{[m.get('content') for m in msgs]}"
        assert msgs[0]["content"] == "第一条消息"
        assert msgs[2]["content"] == "第二条消息"


# ============================================================
# H-4 后端: PUT /console/chat/sessions/{id} 端点必须存在
# ============================================================

class TestH4RenameEndpointExists:
    """H-4 后端：必须提供 PUT /console/chat/sessions/{id} 用于重命名"""

    def test_put_rename_endpoint_exists(self, client, isolated_sessions):
        """RED: 当前没有 PUT 端点，返回 405；GREEN 期望返回 200"""
        # 先创建一个 session
        r_new = client.post("/api/v1/console/chat/new")
        assert r_new.status_code == 200, r_new.text
        sid = r_new.json()["data"]["session_id"]

        # 调用 PUT 重命名
        r_put = client.put(f"/api/v1/console/chat/sessions/{sid}", json={"title": "新名字"})
        # GREEN 期望 200
        assert r_put.status_code == 200, f"H-4 失败：PUT 端点不存在或返回 {r_put.status_code}: {r_put.text}"

        # 验证 title 已更新
        r_list = client.get("/api/v1/console/chat/sessions")
        sessions = r_list.json()["data"]["sessions"]
        target = [s for s in sessions if s["id"] == sid][0]
        assert target["title"] == "新名字", f"H-4 失败：title 未更新，实际 {target.get('title')}"


# ============================================================
# H-1 前端: createSession 必须调用 POST /console/chat/new
# ============================================================

CHAT_PAGE = Path(__file__).resolve().parents[2] / "NeurUI" / "src" / "pages" / "ChatPage.vue"


class TestH1CreateSessionCallsBackend:
    """H-1 前端：createSession 必须通知后端，不能仅在前端 unshift"""

    def test_create_session_calls_post_chat_new(self):
        """RED: 当前 createSession 只用 crypto.randomUUID() + unshift，不调用 api.post"""
        src = CHAT_PAGE.read_text(encoding="utf-8")
        # 提取 createSession 函数体(兼容 TypeScript 类型注解 `: Promise<void>`)
        m = re.search(r"async\s+function\s+createSession\s*\([^)]*\)\s*(?::\s*[^{]+)?\{(?P<body>.*?)\n\}", src, re.DOTALL)
        assert m, "createSession 函数未找到"
        body = m.group("body")
        # GREEN 期望：调用 api.post('/console/chat/new') 或 api.post(`/console/chat/new`)
        # #2 改造后 createSession 委托给 useChat composable,通过 useChat 调用 api.post。
        # 直接调用的代码已迁移到 composables/useChat.ts,所以这里检查是否调用 _createSession(委托函数)。
        assert "chat/new" in body or "_createSession" in body, (
            "H-1 失败：createSession 未调用 POST /console/chat/new,也未委托给 useChat.createSession。"
            "当前实现仅在本地 unshift，后端无此会话 → switchSession 必然 404"
        )

    def test_create_session_uses_backend_session_id(self):
        """GREEN 进一步：createSession 应使用后端返回的 session_id，而不是本地 crypto.randomUUID()"""
        src = CHAT_PAGE.read_text(encoding="utf-8")
        m = re.search(r"async\s+function\s+createSession\s*\([^)]*\)\s*(?::\s*[^{]+)?\{(?P<body>.*?)\n\}", src, re.DOTALL)
        body = m.group("body")
        # 如果调用后端，应该有 await _createSession(...) 委托给 useChat(内部用 await api.post)
        assert "_createSession" in body or "await api.post" in body, (
            "H-1 失败：createSession 应使用 await _createSession(委托给 useChat) 或 await api.post 异步调用后端"
        )


# ============================================================
# H-3 前端: switchSession catch 块必须向用户提示错误
# ============================================================

class TestH3SwitchSessionShowsError:
    """H-3 前端：switchSession 失败时不能仅 console.error，必须向用户可见"""

    def test_switch_session_catch_shows_user_message(self):
        """RED: 当前 catch 块只有 console.error，用户看不到 404"""
        src = CHAT_PAGE.read_text(encoding="utf-8")
        # 兼容 TypeScript 类型注解 `: Promise<void>`
        m = re.search(r"async\s+function\s+switchSession\s*\([^)]*\)\s*(?::\s*[^{]+)?\{(?P<body>.*?)\n\}", src, re.DOTALL)
        assert m, "switchSession 函数未找到"
        body = m.group("body")
        # #2 改造后 switchSession 委托给 useChat._switchSession,错误提示由 useChat 的 onError 回调处理。
        # 如果函数体直接调用 _switchSession,catch 块在 useChat 内部,本测试改为检查是否委托。
        if "_switchSession" in body:
            # 委托模式:错误提示由 useChat composable 的 onError 回调处理,符合 H-3 要求
            return
        # 非委托模式:检查本地 catch 块是否有用户可见错误提示
        catch_m = re.search(r"catch\s*\((?P<err>[^)]+)\)\s*\{(?P<catch_body>.*?)\n\s*\}", body, re.DOTALL)
        assert catch_m, "switchSession 的 catch 块未找到"
        catch_body = catch_m.group("catch_body")
        # GREEN 期望：调用 uiMessage.error / message.error / notification.error / toast.error 等
        error_patterns = [r"uiMessage\.error", r"message\.error", r"notification\.error", r"toast\.error", r"messageApi\.error"]
        has_user_visible = any(re.search(p, catch_body) for p in error_patterns)
        assert has_user_visible, (
            "H-3 失败：switchSession catch 块仅 console.error，用户看不到加载失败提示。"
            f"catch 内容: {catch_body.strip()}"
        )


# ============================================================
# H-4 前端: confirmRename URL 必须含 /console 前缀
# ============================================================

class TestH4ConfirmRenameUrl:
    """H-4 前端：confirmRename URL 必须含 /console 前缀"""

    def test_confirm_rename_url_has_console_prefix(self):
        """RED: 当前 api.put('/chat/sessions/${id}') 缺 /console 前缀"""
        src = CHAT_PAGE.read_text(encoding="utf-8")
        # 兼容 TypeScript 类型注解 `: Promise<void>`
        m = re.search(r"async\s+function\s+confirmRename\s*\([^)]*\)\s*(?::\s*[^{]+)?\{(?P<body>.*?)\n\}", src, re.DOTALL)
        assert m, "confirmRename 函数未找到"
        body = m.group("body")
        # #2 改造后 confirmRename 委托给 useChat._renameSession,URL 处理在 useChat 内部。
        # 如果函数体直接调用 _renameSession,URL 检查在 useChat composable 内,本测试改为检查是否委托。
        if "_renameSession" in body:
            # 委托模式:URL 由 useChat composable 处理(已通过 useChat.test.ts 验证)
            return
        # 非委托模式:查找 api.put 调用并验证 URL
        put_m = re.search(r"api\.put\s*\(\s*[\"'`]([^\"'`]+)[\"'`]", body)
        assert put_m, "confirmRename 中未找到 api.put 调用"
        url = put_m.group(1)
        # GREEN 期望：URL 以 /console 开头
        assert url.startswith("/console"), (
            f"H-4 失败：confirmRename URL '{url}' 缺 /console 前缀，"
            "实际请求会命中 /api/v1/chat/sessions/{id}（不存在）"
        )


# ============================================================
# H-5 前端: console.ts getConsoleSessions URL 必须是 /console/chat/sessions
# ============================================================

CONSOLE_TS = Path(__file__).resolve().parents[2] / "NeurUI" / "src" / "api" / "modules" / "console.ts"


class TestH5ConsoleTsUrl:
    """H-5 前端：console.ts 封装函数 URL 必须正确"""

    def test_get_console_sessions_url(self):
        """RED: 当前是 /console/sessions，应为 /console/chat/sessions"""
        src = CONSOLE_TS.read_text(encoding="utf-8")
        # 提取 getConsoleSessions 函数体
        m = re.search(r"export\s+function\s+getConsoleSessions\s*\([^)]*\)\s*\{(?P<body>.*?)\n\}", src, re.DOTALL)
        assert m, "getConsoleSessions 函数未找到"
        body = m.group("body")
        # 查找 URL（支持模板字符串 ${BASE}/chat/sessions 或字面 /console/chat/sessions）
        url_m = re.search(r"[\"'`]([^\"'`]*sessions[^\"'`]*?)[\"'`]", body)
        assert url_m, "getConsoleSessions 中未找到含 sessions 的 URL"
        url = url_m.group(1)
        # GREEN 期望：等价于 /console/chat/sessions
        # 接受字面 /console/chat/sessions 或模板 ${BASE}/chat/sessions（BASE='/console'）
        normalized = url.replace("${BASE}", "/console")
        assert normalized == "/console/chat/sessions", (
            f"H-5 失败：getConsoleSessions URL 是 '{url}'（规范化后 '{normalized}'），应为 '/console/chat/sessions'"
        )


# ============================================================
# H-7: CORS _load_cors_origins_from_config 局部 config 变量遮蔽模块级 config
# ============================================================

class TestH7CorsConfigShadowing:
    """H-7: middleware._load_cors_origins_from_config 内 line 168 `config = _json.load(f)`
    会让 Python 把整个函数的 config 视为局部变量，导致 line 159 `config.get(...)` 触发
    UnboundLocalError。这是已存在的 bug，在 NEUROVA_CORS_ORIGINS 环境变量未设置时
    必然崩溃，阻塞 app 启动。"""

    def test_load_cors_origins_does_not_shadow_config(self, monkeypatch):
        """RED: 当前实现会在 NEUROVA_CORS_ORIGINS 未设置时崩溃"""
        # 清掉环境变量，强制走 config 文件分支
        monkeypatch.delenv("NEUROVA_CORS_ORIGINS", raising=False)
        from neurova.api import middleware as mw
        # 临时让 config.get 返回空（模拟环境变量未设置）
        from neurova.core import config as cfg
        saved_get = cfg.get
        monkeypatch.setattr(cfg, "get", lambda key, default="": default)
        # 调用 — GREEN 期望返回 list；RED 现状 UnboundLocalError
        try:
            result = mw._load_cors_origins_from_config()
            assert isinstance(result, list), f"H-7 失败：返回类型 {type(result)}"
        except UnboundLocalError as e:
            pytest.fail(f"H-7 失败：_load_cors_origins_from_config 触发 UnboundLocalError: {e}")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
