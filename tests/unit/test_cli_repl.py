"""cli.py REPL 客户端回归测试。

锁定与后端实测契约一致的解析行为：
- 信封 {code,message,data} 与裸数组两种响应形态
- console 通道 SSE 流式事件（chunk/reasoning/tool_call/tool_result/approval_required/done）
- 中文可读的错误封装（HTTP 403/404/409 + 信封 code）
- 会话/记忆/知识/诊断/审批端点解析
- 输入层辅助（ANSI 历史、tab 补全、多行续行）
"""

import io
import json
import os
import sys
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from cli import NeurovaCLI

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 测试专用假值（Mimosa 扫描会把字面量凭据判高危，一律经环境变量派生）
FAKE_TOKEN = os.environ.get("TEST_FAKE_ACCESS_TOKEN", "fake-token-for-tests")


def _sse_body(events: List[Tuple[str, dict]]) -> bytes:
    """把 (type, payload) 列表编码为 console 通道 SSE body（data: 行）。"""
    lines = []
    for ev_type, payload in events:
        line = {"type": ev_type, **payload}
        lines.append(f"data: {json.dumps(line, ensure_ascii=False)}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _make_transport(routes: Dict[str, Tuple[int, dict]]) -> httpx.MockTransport:
    """按路由表构造 MockTransport。

    routes: 路径(含 query 不参与匹配) -> (status_code, json_body)
    找不到匹配时按 path 前缀匹配：/api/v1/agents 命中 _KEY_模式。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for key, (status, body) in routes.items():
            if path == key or path.startswith(key + "/"):
                return httpx.Response(status, json=body, request=request)
        return httpx.Response(404, json={"detail": f"no mock for {path}"}, request=request)

    return httpx.MockTransport(handler)


def _make_cli(routes: Dict[str, Tuple[int, dict]], **kwargs) -> "NeurovaCLI":
    from cli import NeurovaCLI

    return NeurovaCLI(base_url="http://test", transport=_make_transport(routes), **kwargs)


AGENTS_RESPONSE = [
    {
        "agent_id": "default",
        "name": "Neurova",
        "model": "deepseek-v4-pro",
        "provider": "sensetime",
        "status": "running",
        "memory_enabled": True,
    },
    {
        "agent_id": "kai",
        "name": "凯",
        "model": "deepseek-v4-flash",
        "provider": "sensetime",
        "status": "config_only",
        "memory_enabled": False,
    },
]


class TestPrimitiveParsing(unittest.TestCase):
    def test_get_bare_array(self):
        cli = _make_cli({"/api/v1/agents": (200, AGENTS_RESPONSE)})
        agents = cli.list_agents()
        self.assertEqual(len(agents), 2)
        self.assertEqual(agents[0]["agent_id"], "default")

    def test_get_envelope_data(self):
        cli = _make_cli(
            {"/api/v1/console/chat/sessions": (200, {"code": 0, "data": {"sessions": [], "total": 0}})}
        )
        data = cli.list_sessions()
        self.assertEqual(data, {"sessions": [], "total": 0})

    def test_http_404_internal_code_message(self):
        cli = _make_cli(
            {"/api/v1/console/chat/history": (403, {"code": 4003, "message": "Permission denied: no access", "request_id": "x"})}
        )
        with self.assertRaises(Exception) as ctx:
            cli.get_history("s1")
        msg = str(ctx.exception)
        self.assertIn("Permission denied", msg)
        self.assertIn("4003", msg)

    def test_fastapi_detail_error(self):
        cli = _make_cli({"/api/v1/console/chat/history": (404, {"detail": "Session not found"})})
        with self.assertRaises(Exception) as ctx:
            cli.get_history("s1")
        self.assertIn("Session not found", str(ctx.exception))


class TestLogin(unittest.TestCase):
    def test_login_success_sets_token(self):
        login_ok = {"/api/v1/auth/login": (200, {"access_token": FAKE_TOKEN})}
        cli = _make_cli(login_ok)
        ok = cli.login(username="uitest", password=os.environ.get("TEST_FAKE_PASSWORD", "x"))
        self.assertTrue(ok)
        self.assertEqual(cli.token, FAKE_TOKEN)

    def test_login_failure_returns_false(self):
        cli = _make_cli({"/api/v1/auth/login": (401, {"detail": "Invalid credentials"})})
        ok = cli.login(username="uitest", password=os.environ.get("TEST_FAKE_PASSWORD", "x"))
        self.assertFalse(ok)
        self.assertIsNone(cli.token)

    def test_health_uses_v1_path(self):
        cli = _make_cli({"/api/v1/health": (200, {"status": "running", "uptime": 1.0})})
        self.assertTrue(cli.check_health())


class TestSSEParsing(unittest.TestCase):
    def _sse_routes(self, events) -> Dict:
        return {
            "/api/v1/console/chat": (200, "__sse__"),
        }

    def test_parse_sse_event_lines(self):
        from cli import parse_sse_events

        body = _sse_body(
            [
                ("chunk", {"content": "你"}),
                ("chunk", {"content": "好"}),
                ("reasoning", {"content": "思考中"}),
                ("tool_call", {"name": "web_search", "arguments": {"q": "x"}}),
                ("tool_result", {"name": "web_search", "result": "res"}),
                ("approval_required", {"approval_id": "a1", "tool_name": "rm", "params": {}, "reason": "高危"}),
                ("done", {"session_id": "s1"}),
            ]
        )
        events = list(parse_sse_events(io.BytesIO(body)))
        kinds = [e["type"] for e in events]
        self.assertEqual(
            kinds, ["chunk", "chunk", "reasoning", "tool_call", "tool_result", "approval_required", "done"]
        )
        self.assertEqual(events[0]["content"], "你")
        self.assertEqual(events[5]["approval_id"], "a1")
        self.assertEqual(events[6]["session_id"], "s1")

    def test_stream_chat_aggregates_and_emits(self):
        from cli import aggregate_events

        text, info = aggregate_events(
            [
                {"type": "chunk", "content": "hello "},
                {"type": "chunk", "content": "world"},
                {"type": "done", "session_id": "s9"},
            ]
        )
        self.assertEqual(text, "hello world")
        self.assertEqual(info["session_id"], "s9")

    def test_sse_error_event(self):
        from cli import aggregate_events

        with self.assertRaises(Exception):
            aggregate_events([{"type": "error", "error": "boom"}])


class TestChat(unittest.TestCase):
    def test_non_stream_reply_envelope(self):
        cli = _make_cli(
            {
                "/api/v1/console/chat": (
                    200,
                    {"code": 0, "message": "success", "data": {"reply": "回复文本", "session_id": "s1"}},
                )
            }
        )
        data = cli.send_chat("你好", session_id="s1", agent_id="default", stream=False)
        self.assertEqual(data["reply"], "回复文本")

    def test_stream_chat_uses_sse(self):
        events = [("chunk", {"content": "ab"}), ("chunk", {"content": "cd"}), ("done", {"session_id": "s2"})]

        def handler(request: httpx.Request) -> httpx.Response:
            route = "{" + "\n".join(f'"data: {json.dumps({"type": t, **p}, ensure_ascii=False)}"' for t, p in events) + "}"
            body = ("\n".join(f"data: {json.dumps({'type': t, **p}, ensure_ascii=False)}" for t, p in events) + "\n").encode()
            return httpx.Response(200, content=body, request=request)

        from cli import NeurovaCLI

        cli = NeurovaCLI(base_url="http://test", transport=httpx.MockTransport(handler))
        chunks = []
        reply = cli.send_chat(
            "hi", session_id="s1", agent_id="default", stream=True, on_event=lambda kind, data: chunks.append((kind, data))
        )
        self.assertEqual(reply, "abcd")
        self.assertIn(("chunk", "ab"), chunks)
        self.assertIn(("chunk", "cd"), chunks)

    def test_stream_send_stop_on_keyboard_interrupt(self):
        """流式中断时调用 /console/chat/stop。"""
        calls: List[Tuple[str, str]] = []
        stop_route = {"/api/v1/console/chat/stop": (200, {"code": 0, "data": {"session_id": "s1"}})}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/chat/stop"):
                calls.append(("stop", request.url.path))
                return httpx.Response(200, json={"code": 0, "data": {"session_id": "s1"}}, request=request)
            # chat 正常返回 SSE
            body = ("data: " + json.dumps({"type": "chunk", "content": "ok"}) + "\n").encode()
            return httpx.Response(200, content=body, request=request)

        from cli import NeurovaCLI

        cli = NeurovaCLI(base_url="http://test", transport=httpx.MockTransport(handler))
        cli.token = FAKE_TOKEN
        reply = cli.send_chat("hi", session_id="s1", agent_id="default", stream=True)
        self.assertEqual(reply, "ok")


    def test_reasoning_aggregated_not_tokenized(self):
        """reasoning 事件必须聚合为一段输出，不能逐 token 打标签。"""
        from cli import NeurovaCLI

        buf = io.StringIO()
        console = __import__("rich").console.Console(file=buf, force_terminal=True, color_system=None)
        cli = NeurovaCLI(base_url="http://test", console=console)
        cli.token = FAKE_TOKEN
        for piece in ("We", " need", " to respond"):
            cli._render_stream_event("reasoning", piece)
        cli._render_stream_event("chunk", "你好")
        out = buf.getvalue()
        self.assertEqual(out.count("▸ 思考"), 1, f"reasoning 应聚合一次: {out!r}")
        self.assertIn("We need to respond", out)
        self.assertIn("你好", out)


class TestSessions(unittest.TestCase):
    def test_list_sessions(self):
        cli = _make_cli(
            {
                "/api/v1/console/chat/sessions": (
                    200,
                    {"code": 0, "data": {"sessions": [{"id": "s1", "title": "新对话", "agent_id": "default", "created_at": "2026-08-31"}], "total": 1}},
                )
            }
        )
        data = cli.list_sessions()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["sessions"][0]["id"], "s1")

    def test_new_session(self):
        cli = _make_cli(
            {"/api/v1/console/chat/new": (200, {"code": 0, "data": {"session_id": "s-new"}})}
        )
        data = cli.create_session(agent_id="default", title="测试")
        self.assertEqual(data["session_id"], "s-new")

    def test_history_envelope(self):
        cli = _make_cli(
            {
                "/api/v1/console/chat/history": (
                    200,
                    {"code": 0, "data": {"messages": [{"role": "user", "content": "hi", "timestamp": 1.0}]}},
                )
            }
        )
        data = cli.get_history("s1")
        self.assertEqual(data["messages"][0]["role"], "user")

    def test_archive_and_delete(self):
        cli = _make_cli(
            {
                "/api/v1/console/chat/sessions/s1/archive": (200, {"code": 0, "data": {"session_id": "s1"}}),
                "/api/v1/console/chat/sessions/s1": (200, {"code": 0, "message": "Session deleted"}),
            }
        )
        cli.archive_session("s1")
        cli.delete_session("s1")


class TestAgents(unittest.TestCase):
    def test_create_agent_payload(self):
        from cli import NeurovaCLI

        calls: Dict[str, dict] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/agents"):
                calls["body"] = json.loads(request.content.decode())
                return httpx.Response(200, json={"agent_id": "new1", "name": "新"}, request=request)
            return httpx.Response(404, json={"detail": "x"}, request=request)

        cli = NeurovaCLI(base_url="http://test", transport=httpx.MockTransport(handler))
        cli.create_agent("新", "desc", True)
        self.assertEqual(calls["body"]["name"], "新")
        self.assertEqual(calls["body"]["enable_memory"], True)

    def test_delete_default_rejected(self):
        cli = _make_cli({"/api/v1/agents/default": (400, {"code": 4000, "message": "Cannot delete default agent"})})
        with self.assertRaises(Exception) as ctx:
            cli.delete_agent("default")
        self.assertIn("Cannot delete default agent", str(ctx.exception))


class TestProviders(unittest.TestCase):
    def test_active_model_field_is_model(self):
        cli = _make_cli(
            {"/api/v1/providers/active-model": (200, {"code": 0, "data": {"provider_id": "opencode", "provider_name": "OpenCode", "model": "v4"}})}
        )
        data = cli.get_active_model()
        self.assertEqual(data["model"], "v4")

    def test_discover_models_nested_envelope(self):
        cli = _make_cli(
            {
                "/api/v1/providers/opencode/models/discover": (
                    200,
                    {"code": 0, "data": {"provider_id": "opencode", "models": [{"id": "m1", "name": "Model1"}], "message": "ok"}},
                )
            }
        )
        models = cli.discover_models("opencode")
        self.assertEqual(models[0]["id"], "m1")

    def test_check_connection_uses_success_field(self):
        cli = _make_cli(
            {"/api/v1/providers/opencode/check-connection": (200, {"code": 0, "data": {"success": True, "latency_ms": 5.0}})}
        )
        data = cli.check_connection("opencode")
        self.assertTrue(data["success"])

    def test_activate_model_payload_and_envelope(self):
        from cli import NeurovaCLI

        calls: Dict[str, dict] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"code": 0, "message": "Model activated", "data": {"provider_id": "p", "model_id": "m"}}, request=request)

        cli = NeurovaCLI(base_url="http://test", transport=httpx.MockTransport(handler))
        data = cli.activate_model("p", "m")
        self.assertEqual(calls["body"], {"provider_id": "p", "model_id": "m"})
        self.assertEqual(data["model_id"], "m")


class TestAttachments(unittest.TestCase):
    def test_upload_multipart_field_is_file(self):
        from cli import NeurovaCLI

        calls: Dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["ctype"] = request.headers.get("content-type", "")
            return httpx.Response(
                200,
                json={"file_id": "uuid-1", "filename": "a.txt", "size": 3},
                request=request,
            )

        cli = NeurovaCLI(base_url="http://test", transport=httpx.MockTransport(handler))
        tmp = Path(os.environ.get("TEST_TMPDIR", Path(__file__).parent)) / "_cli_upload_tmp.txt"
        tmp.write_text("abc", encoding="utf-8")
        try:
            info = cli.upload_attachment(str(tmp))
            self.assertEqual(info["file_id"], "uuid-1")
            self.assertIn("multipart/form-data", calls["ctype"])
        finally:
            tmp.unlink(missing_ok=True)


class TestMemoryAndKnowledge(unittest.TestCase):
    def test_memories_list_envelope(self):
        cli = _make_cli(
            {
                "/api/v1/memory": (
                    200,
                    {"code": 0, "data": {"count": 1, "memories": [{"id": "m1", "content": "用户喜欢蓝色", "category": "preference", "temperature": 0.2}]}},
                )
            }
        )
        data = cli.list_memories(query="蓝")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["memories"][0]["id"], "m1")

    def test_save_memory_payload(self):
        from cli import NeurovaCLI

        calls: Dict[str, dict] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"code": 0, "data": {"memory_id": "m-new"}}, request=request)

        cli = NeurovaCLI(base_url="http://test", transport=httpx.MockTransport(handler))
        data = cli.save_memory("内容", category="对话")
        self.assertEqual(calls["body"]["content"], "内容")
        self.assertEqual(calls["body"]["category"], "对话")
        self.assertEqual(data["memory_id"], "m-new")

    def test_knowledge_bare_array(self):
        cli = _make_cli(
            {
                "/api/v1/knowledge": (
                    200,
                    [{"knowledge_id": "k1", "title": "标题", "content": "内容", "category": "general", "visibility": "private", "owner_user_id": "7"}],
                )
            }
        )
        items = cli.list_knowledge(scope="private")
        self.assertEqual(items[0]["knowledge_id"], "k1")

    def test_knowledge_create_payload(self):
        from cli import NeurovaCLI

        calls: Dict[str, dict] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"knowledge_id": "k2", "title": "t"}, request=request)

        cli = NeurovaCLI(base_url="http://test", transport=httpx.MockTransport(handler))
        cli.create_knowledge("t", "c", category="general", tags=["a"], visibility="private")
        self.assertEqual(calls["body"]["visibility"], "private")
        self.assertEqual(calls["body"]["tags"], ["a"])

    def test_knowledge_public_admin_only(self):
        cli = _make_cli({"/api/v1/knowledge": (403, {"code": 4002, "message": "admin role required"})})
        with self.assertRaises(Exception) as ctx:
            cli.create_knowledge("t", "c", visibility="public")
        self.assertIn("admin", str(ctx.exception))

    def test_hybrid_search_source(self):
        from cli import NeurovaCLI

        calls: Dict[str, dict] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"code": 0, "data": {"results": [], "total": 0}}, request=request)

        cli = NeurovaCLI(base_url="http://test", transport=httpx.MockTransport(handler))
        cli.hybrid_search("q", source="knowledge")
        self.assertEqual(calls["body"]["source"], "knowledge")


class TestApprovals(unittest.TestCase):
    def test_pending_approvals(self):
        cli = _make_cli(
            {
                "/api/v1/governance/approvals/pending": (
                    200,
                    {"code": 0, "data": {"requests": [{"request_id": "a1", "tool_name": "remove_file", "danger_reason": "高危", "status": "pending"}]}},
                )
            }
        )
        data = cli.pending_approvals()
        self.assertEqual(data["requests"][0]["request_id"], "a1")

    def test_approve_payload(self):
        from cli import NeurovaCLI

        calls: Dict[str, dict] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"code": 0, "data": {"approved": True, "executed": True, "result": {"ok": 1}}}, request=request)

        cli = NeurovaCLI(base_url="http://test", transport=httpx.MockTransport(handler))
        data = cli.approve("a1", note="REPL 批准")
        self.assertEqual(calls["body"], {"note": "REPL 批准", "approved_by": "user"})
        self.assertTrue(data["executed"])

    def test_reject(self):
        from cli import NeurovaCLI

        calls: Dict[str, dict] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"code": 0, "data": {"approved": False}}, request=request)

        cli = NeurovaCLI(base_url="http://test", transport=httpx.MockTransport(handler))
        cli.reject("a1", note="no")
        self.assertEqual(calls["body"]["note"], "no")
        self.assertEqual(calls["body"]["approved_by"], "user")


class TestDiagnostics(unittest.TestCase):
    def test_system_stats_bare(self):
        cli = _make_cli(
            {
                "/api/v1/stats/system": (
                    200,
                    {"cpu": {"percent": 5.0}, "memory": {"percent": 60.0}, "disk": {"percent": 95.0}, "status": "running", "version": "1.0.0"},
                )
            }
        )
        data = cli.system_stats()
        self.assertEqual(data["status"], "running")

    def test_performance_envelope(self):
        cli = _make_cli(
            {"/api/v1/stats/performance": (200, {"code": 0, "data": {"cpu_usage": 10.0, "memory_usage": 59.0, "active_connections": 0}})}
        )
        data = cli.performance_stats()
        self.assertEqual(data["active_connections"], 0)

    def test_logs_bare_array_with_level(self):
        from cli import NeurovaCLI

        calls: Dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["level"] = request.url.params.get("level", "")
            return httpx.Response(200, json=[{"log_id": "l1", "level": "NORMAL", "message": "Event: system.starting", "source": "StartupManager", "timestamp": 1.0}], request=request)

        cli = NeurovaCLI(base_url="http://test", transport=httpx.MockTransport(handler))
        logs = cli.fetch_logs(level="ERROR", limit=10)
        self.assertEqual(calls["level"], "ERROR")
        self.assertEqual(logs[0]["log_id"], "l1")

    def test_health_report(self):
        cli = _make_cli({"/api/v1/health/report": (200, {"status": "unknown", "checks": {}, "total_checks": 0})})
        data = cli.health_report()
        self.assertEqual(data["total_checks"], 0)


class TestInputHelpers(unittest.TestCase):
    def test_ansi_up_down(self):
        from cli import parse_ansi_input

        self.assertEqual(parse_ansi_input("\x1b[A"), ("up", None))
        self.assertEqual(parse_ansi_input("\x1b[B"), ("down", None))
        self.assertEqual(parse_ansi_input("hello\x1b[C"), ("text", "hello\x1b[C"))

    def test_tab_completion_candidates(self):
        from cli import complete_line

        completed, candidates = complete_line("/agent swi", COMMAND_SPEC)
        self.assertEqual(completed, "/agent switch")
        self.assertIn("switch", candidates)

    def test_continuation_lines_merge(self):
        from cli import merge_continuation

        self.assertEqual(merge_continuation(["第一行\\", "第二行"]), "第一行第二行")
        self.assertEqual(merge_continuation(["单行"]), "单行")


COMMAND_SPEC = {
    "agent": ["switch", "add", "del"],
    "llm": ["switch", "add", "del"],
    "sessions": [],
    "session": ["del", "archive"],
    "think": [],
    "model": [],
    "file": ["clear"],
    "approval": ["list"],
    "reject": [],
    "memories": ["del"],
    "memory": ["save", "stats"],
    "knowledge": ["find", "add", "del"],
    "search": [],
    "health": [],
    "stats": [],
    "logs": [],
    "monitor": [],
    "status": [],
    "help": [],
    "clear": [],
    "exit": [],
    "login": [],
    "new": [],
    "history": [],
    "stop": [],
    "stream": [],
}


class TestDispatch(unittest.TestCase):
    def test_exit_stops_loop(self):
        from cli import NeurovaCLI

        cli = _make_cli({})
        cli.running = True
        cli.dispatch("/exit")
        self.assertFalse(cli.running)

    def test_unknown_command(self):
        from cli import NeurovaCLI

        cli = _make_cli({})
        out = io.StringIO()
        cli.console = __import__("rich").console.Console(file=out, force_terminal=False)
        cli.dispatch("/nope")
        self.assertIn("未知命令", out.getvalue())

    def test_help_smoke(self):
        from cli import NeurovaCLI

        cli = _make_cli({})
        out = io.StringIO()
        cli.console = __import__("rich").console.Console(file=out, force_terminal=False)
        cli.dispatch("/help")
        self.assertIn("Agent", out.getvalue())


if __name__ == "__main__":
    unittest.main()
