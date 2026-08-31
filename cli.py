#!/usr/bin/env python3
"""Neurova REPL 聊天客户端
=========================

交互式命令行客户端，基于后端实测契约（2026-08-31）：
- 主聊天通道: /api/v1/console/chat（支持 SSE 流式 chunk/reasoning/tool_call/approval_required/done）
- 会话管理: /api/v1/console/chat/sessions|new|history
- 附件: /api/v1/files/upload (multipart 字段名 `file`) → console chat 的 file_ids
- 审批: /api/v1/governance/approvals/...
- 记忆: /api/v1/memory；知识: /api/v1/knowledge；诊断: /api/v1/stats|logs|health
- 命令: /agent /llm /session /new /history /think /model /file /approval /reject
         /memories /memory /knowledge /search /health /stats /logs /monitor
         /status /login /help /clear /exit
"""

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import httpx
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from scripts.common import _display_width

# 默认配置
DEFAULT_BASE_URL = "http://localhost:9527"
API_PREFIX = "/api/v1"

# 命令补全规格（command -> 子命令候选）
COMMAND_SPEC: Dict[str, List[str]] = {
    "agent": ["switch", "add", "del", "list"],
    "llm": ["switch", "add", "del", "list"],
    "sessions": [],
    "session": ["del", "archive"],
    "new": [],
    "history": [],
    "think": ["简单", "标准", "深度", "off"],
    "model": [],
    "file": ["clear"],
    "approval": ["list"],
    "reject": [],
    "memories": ["del"],
    "memory": ["save", "stats", "del"],
    "knowledge": ["list", "find", "add", "del"],
    "search": ["memory", "knowledge"],
    "health": [],
    "stats": [],
    "logs": [],
    "monitor": [],
    "status": [],
    "login": [],
    "help": [],
    "clear": [],
    "exit": [],
    "stop": [],
    "stream": [],
}

HISTORY_FILE = Path(os.path.expanduser("~")) / ".neurova_repl_history"
HISTORY_MAX = 500


# ==================== 模块级纯函数（可单测） ====================

# ---- REPL 界面主题 · Hermes 对齐 · 蓝色系 ----
# Rich 主题名 -> 颜色（消息流/面板/欢迎屏统一走这组 token）
REPL_THEME = {
    "nr.primary": "#5b9bff",
    "nr.accent": "#38bdf8",
    "nr.border": "#2a4a7f",
    "nr.text": "#e8eef7",
    "nr.muted": "#7d8fa8",
    "nr.dim": "#5a6b85",
    "nr.ok": "#4ade80",
    "nr.warn": "#fbbf24",
    "nr.err": "#f87171",
    # 组合样式键（rich Theme 需显式注册才能按名解析）
    "bold nr.accent": "bold #38bdf8",
    "bold nr.primary": "bold #5b9bff",
    "bold nr.text": "bold #e8eef7",
    "bold nr.ok": "bold #4ade80",
    "bold nr.err": "bold #f87171",
}

# 非 rich 通道（流式 raw file.write）用的 ANSI 序列
_ANSI_SEQ = {
    "primary": "\033[38;2;91;155;255m",
    "accent": "\033[38;2;56;189;248m",
    "muted": "\033[38;2;125;143;168m",
    "dim": "\033[38;2;90;107;133m",
    "ok": "\033[38;2;74;222;128m",
    "warn": "\033[38;2;251;191;36m",
    "error": "\033[38;2;248;113;113m",
    "reset": "\033[0m",
}

# 界面符号（Hermes messageLine 范式）
SYM_BULLET = "●"       # 助手回复/工具 marker
SYM_USER = "❯"         # 用户标签侧翼/prompt
SYM_THINK = "▸"        # 推理折叠箭头
SYM_OK = "✓"
SYM_WARN = "!"
SYM_ERR = "✕"
SYM_INFO = "○"
SYM_HINT = "›"

AI_NAME = "智星"        # Neurova 助手显示名

# 渲染函数一律返回 rich Text（样式名走 REPL_THEME），由 Console 统一
# 渲染——宽度/折行/导出快照（export_html）均正确；避免手搓 ANSI 字符串
# 被 rich 当字符计算宽度造成错位。


def ansi(text: str, style: str, enabled: bool = True) -> str:
    """给文本套单色 ANSI（仅流式 raw 输出用；非启用态/不支持时原样返回）。"""
    if not enabled:
        return text
    return f"{_ANSI_SEQ.get(style, '')}{text}{_ANSI_SEQ['reset']}"


def use_tty_color() -> bool:
    """默认着色开关：TTY 且未设 NO_COLOR。"""
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _style_name(style: str) -> str:
    """把 nr.ok/nr.warn/nr.err 缩写语义面扩展为完整 rich 样式名。"""
    return f"nr.{style}" if style in ("ok", "warn", "err", "primary", "accent", "muted", "dim") else style


def render_user_message(text: str) -> "Text":
    """用户消息回显: 蓝标签行 + 缩进正文（Hermes `❯ You` 范式）。"""
    out = Text()
    out.append(f"{SYM_USER} 你", style=_style_name("primary"))
    out.append("\n")
    for line in text.splitlines() or [""]:
        out.append(f"    {line}", style=_style_name("text"))
        out.append("\n")
    return out


def render_assistant_marker() -> "Text":
    """助手回复流式前缀（accent 天蓝 + 空格）。"""
    return Text(f"{SYM_BULLET} ", style=_style_name("accent"))


def render_tool_call(name: str, args_preview: str = "") -> "Text":
    """工具调用行: `● [工具] 名称 · 参数摘要`。"""
    out = Text(f"{SYM_BULLET} [工具] {name}", style=_style_name("accent"))
    if args_preview:
        short = args_preview[:80].replace("\n", " ")
        out.append(f" · {short}", style=_style_name("muted"))
    return out


def render_tool_result(preview: str) -> "Text":
    """工具结果行: `↳ 摘要`（dim 缩进）。"""
    short = preview[:200].replace("\n", " ")
    return Text(f"  ↳ {short}", style=_style_name("dim"))


def render_reasoning(text: str, limit: int = 200) -> "Text":
    """推理聚合单行: `▸ 思考 · 摘要[…]`。"""
    short = text[:limit]
    suffix = "…" if len(text) > limit else ""
    return Text(f"{SYM_THINK} 思考 · {short}{suffix}", style=_style_name("muted"))


def render_approval(tool_name: str, approval_id: str) -> "Text":
    """审批警示行（语义黄保留）。"""
    out = Text(f"{SYM_WARN} [待审批] {tool_name}", style=_style_name("warn"))
    out.append(f" ID: {approval_id}（/approval {approval_id} 批准，/reject {approval_id} 拒绝）", style=_style_name("muted"))
    return out


def render_welcome_icon_line(icon: str, text: str, style: str = "ok") -> "Text":
    """欢迎屏状态行: `✓ 文本`（图标按语义着色）。"""
    return Text(f"{icon} {text}", style=_style_name(style))


def render_status_bar(model: str = "-", session: str = "-", turn: int = 0, elapsed: float = 0.0) -> "Text":
    """回合收尾状态栏（Hermes 底栏范式）: `⚑ 模型 | 第 N 轮 · 会话 | 用时`。"""
    out = Text()
    out.append("⚑ ", style="bold nr.accent")
    out.append(model or "-", style="bold nr.text")
    out.append("  |  ", style="nr.dim")
    out.append(f"第 {turn} 轮", style="nr.muted")
    if session:
        out.append(f" · 会话 {session}", style="nr.muted")
    out.append("  |  ", style="nr.dim")
    out.append(f"{elapsed:.1f}s", style="nr.muted")
    return out


def render_welcome_panel(header_lines: List["Text"], footer: Optional["Text"] = None) -> Panel:
    """欢迎屏主面板（Hermes 窗口范式）: 圆角蓝框 + 左上标题。"""
    body = Text()
    for line in header_lines:
        if isinstance(line, str):
            line = Text(line)
        body.append_text(line)
        body.append("\n")
    if footer is not None:
        if isinstance(footer, str):
            footer = Text(footer)
        body.append("\n")
        body.append_text(footer)
    return Panel(
        body,
        title=Text(f"{SYM_BULLET} 智星 · Neurova REPL", style="bold nr.accent"),
        title_align="left",
        border_style="nr.primary",
        box=box.DOUBLE,  # 与 print_logo 同款双线框
        padding=(0, 1),
    )


def render_help_hint() -> "Text":
    """欢迎屏帮助提示（dim）。"""
    return Text(f"{SYM_HINT} 输入 /help 查看命令 · 直接输入文字开始聊天 · 按 Ctrl+C 退出", style=_style_name("dim"))


def prompt_text(enabled: bool = True) -> str:
    """输入提示符: `❯ `（raw 字符串 fed 给 input()；TTY 时带 accent 色）。"""
    return ansi(f"{SYM_USER} ", "accent", enabled)


def render_completion_hint(candidates: List[str]) -> "Text":
    """tab 补全候选提示（accent 点分）。"""
    return Text(f"{SYM_HINT} 候选: {' · '.join(candidates)}", style=_style_name("accent"))


def _text_to_ansi(renderable: "Text", color: bool = True) -> str:
    """把 rich Text 渲染成带 ANSI 的字符串（供 raw file.write 流式通道复用）。"""
    if not color:
        return renderable.plain
    buf = io.StringIO()
    Console(file=buf, force_terminal=True, color_system="truecolor", theme=Theme(REPL_THEME)).print(renderable)
    return buf.getvalue().rstrip("\n")


# ---- 回合帧（对话内容双线框, 与 print_logo 同款 ╔═╗║╚═╝） ----


def _wrap_by_width(text: str, limit: int) -> List[str]:
    """按显示宽度折行（CJK 计 2 列），返回不超 limit 的行。"""
    if not text:
        return [""]
    lines: List[str] = []
    cur = ""
    w = 0
    for ch in text:
        cw = _display_width(ch)
        if w + cw > limit:
            lines.append(cur)
            cur = ch
            w = cw
        else:
            cur += ch
            w += cw
    lines.append(cur)
    return lines


def render_turn_frame_top(user_text: str, limit: int, color: bool = True) -> str:
    """回合顶框（开放帧）: ╔═ ❯ 你 ═══╗ + 用户消息行。

    limit = 内容显示宽（框总宽 = limit + 4: ║ 2 列 + ║ 2 列）。
    """
    rendered = render_user_message(user_text).plain  # "❯ 你\n    你好"
    lines = []
    first = True
    for raw_line in rendered.split("\n"):
        if first:
            title = raw_line.strip()
            fill = max(limit - _display_width(title) - 1, 1)
            lines.append("╔═ " + ansi(title, "primary", color) + " " + "═" * fill + "╗")
            first = False
        else:
            for wl in _wrap_by_width(raw_line, limit):
                pad = max(limit - _display_width(wl), 0)
                lines.append("║ " + wl + " " * pad + " ║")
    return "\n".join(lines)


def render_turn_frame_bottom(limit: int) -> str:
    """回合底框: ╚═════╝（宽度与顶框一致）。"""
    return "╚" + "═" * (limit + 2) + "╝"


def parse_ansi_input(raw: str) -> Tuple[str, Optional[str]]:
    """解析输入行中的 ANSI 方向键序列。

    Windows 终端把上下键以 ESC 序列发到 stdin，input() 会把它作为
    整行返回（此时行内容为 \x1b[A / \x1b[B）。返回 ("up"/"down", None)；
    其余情况返回 ("text", 原文)。
    """
    if raw == "\x1b[A":
        return ("up", None)
    if raw == "\x1b[B":
        return ("down", None)
    return ("text", raw)


def complete_line(line: str, spec: Dict[str, List[str]] = COMMAND_SPEC) -> Tuple[str, List[str]]:
    """对以 / 开头的行做简单前缀补全，返回 (补全后的行, 候选列表)。

    规则: "/ag swi" → 命令 "ag" 唯一匹配 "agent" 且 "swi" 唯一前缀匹配
    "switch" → 补全为 "/agent switch"；不唯一时返回候选。
    """
    tokens = line.strip().split()
    if not tokens or not tokens[0].startswith("/"):
        return line, []
    cmd_token = tokens[0].lower()
    cmd_candidates = [c for c in spec if c.startswith(cmd_token[1:])]
    if len(tokens) == 1:
        if len(cmd_candidates) == 1:
            return "/" + cmd_candidates[0], []
        return line, ["/" + c for c in cmd_candidates]
    sub_token = tokens[1].lower()
    subs = spec.get(cmd_candidates[0] if len(cmd_candidates) == 1 else "", [])
    sub_candidates = [s for s in subs if s.startswith(sub_token)]
    if len(sub_candidates) == 1:
        return "/" + cmd_candidates[0] + " " + sub_candidates[0], sub_candidates
    if sub_candidates:
        return line, sub_candidates
    return line, []


def merge_continuation(lines: List[str]) -> str:
    """把以 \\ 结尾的多行输入合并为一条消息（续行符丢出）。"""
    out = ""
    for line in lines:
        if line.endswith("\\"):
            out += line[:-1]
        else:
            out += line
    return out.strip()


def parse_sse_events(data: Any) -> Iterator[dict]:
    """解析 console 通道 SSE 帧（每帧一行 `data: {...}`），产出事件 dict。"""
    if hasattr(data, "read"):
        data = data.read()
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
    else:
        text = data
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload:
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


def aggregate_events(events: List[dict]) -> Tuple[str, dict]:
    """聚合一帧帧 SSE 事件为纯文本回复 + 摘要信息。

    - chunk 内容拼接为回复文本；reasoning 单独收集；done 提取 session_id；
    - error 事件抛异常。
    """
    info: Dict[str, Any] = {}
    text = ""
    for ev in events:
        ev_type = ev.get("type")
        if ev_type == "error":
            raise RuntimeError(f"服务端错误: {ev.get('error', 'unknown')}")
        if ev_type == "chunk":
            text += ev.get("content", "")
        elif ev_type == "done":
            info["session_id"] = ev.get("session_id")
        elif ev_type == "reasoning":
            info.setdefault("reasoning", "")
            info["reasoning"] += ev.get("content", "")
        elif ev_type == "approval_required":
            info.setdefault("approvals", []).append(ev)
    return text, info


# ==================== 错误封装 ====================


class CliError(Exception):
    """API 业务错误（可读中文消息）。"""


def _error_message(status_code: int, body: Any) -> str:
    """从响应体提取可读错误消息：信封 code/message 或 FastAPI detail。"""
    if isinstance(body, dict):
        if body.get("message") and "code" in body:
            return f"[{body.get('code')}] {body['message']}"
        if isinstance(body.get("detail"), str):
            return body["detail"]
    return f"HTTP {status_code}"


# ==================== 客户端 ====================


class NeurovaCLI:
    """Neurova REPL 客户端（httpx transport 可注入，测试用 MockTransport）。"""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        transport: Optional[httpx.BaseTransport] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        console: Optional[Console] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}{API_PREFIX}"
        self.transport = transport
        self.token: Optional[str] = None
        self.username = username
        self.password = password
        self.current_agent_id: Optional[str] = None
        self.current_session_id: Optional[str] = None
        self.current_model: Optional[str] = None
        self.thinking_effort: str = ""
        self.streaming: bool = True
        self.attachments: List[str] = []
        self.running = True
        self.console = console or Console(theme=Theme(REPL_THEME))
        self._history: List[str] = []
        self._history_cache: List[str] = []
        self._reasoning_buf: List[str] = []
        self._reply_marker: bool = False  # 助手流式 ● 前缀是否已打（每回合复位）
        self._turn_count: int = 0
        self._frame_col: int = 0          # 回合帧当前列（0=行首; 含 ║ 前缀 2 列）
        self._draw_color = self.console.is_terminal and os.environ.get("NO_COLOR") is None

    # ---------- HTTP 原语 ----------

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _client(self, timeout: float = 60.0) -> httpx.Client:
        return httpx.Client(timeout=timeout, transport=self.transport)

    def _req(self, method: str, path: str, **kwargs) -> Any:
        """发起请求并返回响应体（dict/list）。非 2xx 抛 CliError（可读消息）。"""
        url = f"{self.api_url}{path}"
        try:
            with self._client() as client:
                resp = client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.ConnectError as e:
            raise CliError(f"无法连接到服务器 {self.base_url}（{e}）——请确认后端已启动") from e
        except httpx.TimeoutException:
            raise CliError("请求超时") from None
        if resp.status_code >= 400:
            body = self._parse_json(resp)
            raise CliError(_error_message(resp.status_code, body))
        return self._parse_json(resp)

    @staticmethod
    def _parse_json(resp: httpx.Response) -> Any:
        if not resp.content:
            return {}
        try:
            return resp.json()
        except json.JSONDecodeError:
            return {"detail": resp.text[:200]}

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        return self._req("GET", path, params=params)

    def _post(self, path: str, json: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        return self._req("POST", path, json=json, params=params)

    def _delete(self, path: str) -> Any:
        return self._req("DELETE", path)

    def _put(self, path: str, json: Optional[dict] = None) -> Any:
        return self._req("PUT", path, json=json)

    # ---------- 连接与鉴权 ----------

    def check_health(self) -> bool:
        try:
            body = self._get("/health")
            return isinstance(body, dict) and body.get("status") in ("running", "unknown", "ok")
        except CliError:
            return False

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """登录获取 token（顶层 access_token）。失败返回 False 不抛异常。"""
        username = username or self.username or os.environ.get("NEUROVA_USERNAME")
        password = password or self.password or os.environ.get("NEUROVA_PASSWORD")
        if not username:
            raise CliError("缺少用户名（可用 --username 或 NEUROVA_USERNAME 提供）")
        if not password:
            raise CliError("缺少密码（可用 --password 或 NEUROVA_PASSWORD 提供）")
        try:
            body = self._post("/auth/login", json={"username": username, "password": password})
        except CliError:
            return False
        token = body.get("access_token") if isinstance(body, dict) else None
        if not token:
            return False
        self.token = token
        self.username = username
        return True

    # ---------- Agent ----------

    def list_agents(self) -> list:
        body = self._get("/agents")
        return body if isinstance(body, list) else []

    def create_agent(self, name: str, description: str = "", enable_memory: bool = True) -> dict:
        body = self._post("/agents", json={"name": name, "description": description, "enable_memory": enable_memory})
        return body if isinstance(body, dict) else {}

    def delete_agent(self, agent_id: str) -> dict:
        body = self._delete(f"/agents/{agent_id}")
        return body if isinstance(body, dict) else {}

    # ---------- Provider / 模型 ----------

    def list_providers(self) -> list:
        body = self._get("/providers")
        return body if isinstance(body, list) else []

    def get_active_model(self) -> dict:
        body = self._get("/providers/active-model")
        return (body or {}).get("data", {}) if isinstance(body, dict) else {}

    def discover_models(self, provider_id: str) -> list:
        body = self._get(f"/providers/{provider_id}/models/discover")
        if isinstance(body, dict):
            return body.get("data", {}).get("models", [])
        return []

    def activate_model(self, provider_id: str, model_id: str) -> dict:
        body = self._post("/providers/activate-model", json={"provider_id": provider_id, "model_id": model_id})
        return (body or {}).get("data", {}) if isinstance(body, dict) else {}

    def check_connection(self, provider_id: str) -> dict:
        body = self._post(f"/providers/{provider_id}/check-connection")
        return (body or {}).get("data", {}) if isinstance(body, dict) else {}

    # ---------- 会话 ----------

    def list_sessions(self) -> dict:
        body = self._get("/console/chat/sessions")
        return (body or {}).get("data", {}) if isinstance(body, dict) else {}

    def create_session(self, agent_id: Optional[str] = None, title: str = "新对话") -> dict:
        body = self._post("/console/chat/new", json={"agent_id": agent_id, "title": title})
        return (body or {}).get("data", {}) if isinstance(body, dict) else {}

    def delete_session(self, session_id: str) -> dict:
        body = self._delete(f"/console/chat/sessions/{session_id}")
        return body if isinstance(body, dict) else {}

    def archive_session(self, session_id: str) -> dict:
        body = self._post(f"/console/chat/sessions/{session_id}/archive")
        return body if isinstance(body, dict) else {}

    def get_history(self, session_id: str) -> dict:
        body = self._get("/console/chat/history", params={"session_id": session_id})
        return (body or {}).get("data", {}) if isinstance(body, dict) else {}

    # ---------- 聊天 ----------

    def stop_chat(self, session_id: str) -> None:
        try:
            self._post("/console/chat/stop", json={"session_id": session_id})
        except CliError:
            pass

    def send_chat(
        self,
        message: str,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        stream: Optional[bool] = None,
        model: Optional[str] = None,
        thinking_effort: Optional[str] = None,
        file_ids: Optional[List[str]] = None,
        on_event: Optional[Callable[[str, dict], None]] = None,
    ) -> str:
        """发送消息：stream=True 走 SSE 增量回调并返回聚合文本，否则返回 data.reply。"""
        stream = self.streaming if stream is None else stream
        payload = {
            "message": message,
            "agent_id": agent_id or self.current_agent_id or "default",
            "session_id": session_id or self.current_session_id,
            "stream": stream,
            "model": model or self.current_model,
            "thinking_effort": thinking_effort if thinking_effort is not None else self.thinking_effort,
        }
        if file_ids:
            payload["file_ids"] = file_ids
        url = f"{self.api_url}/console/chat"
        try:
            with self._client(timeout=300) as client:
                resp = client.post(url, json=payload, headers=self._headers())
            if resp.status_code >= 400:
                raise CliError(_error_message(resp.status_code, self._parse_json(resp)))
            if stream:
                events = []
                for ev in parse_sse_events(resp.content):
                    events.append(ev)
                    if on_event and ev.get("type") != "done":
                        ev_type = ev.get("type")
                        if ev_type in ("chunk", "reasoning"):
                            on_event(ev_type, ev.get("content", ""))
                        else:
                            on_event(ev_type, ev)
                text, info = aggregate_events(events or [{"type": "chunk", "content": ""}])
                if info.get("session_id"):
                    self.current_session_id = info["session_id"]
                return text
            body = self._parse_json(resp)
            data = body.get("data", {}) if isinstance(body, dict) else {}
            if isinstance(data, dict) and data.get("session_id"):
                self.current_session_id = data["session_id"]
            return data
        except httpx.ConnectError as e:
            raise CliError(f"无法连接到服务器 {self.base_url}（{e}）") from e
        except KeyboardInterrupt:
            if self.current_session_id:
                self.stop_chat(self.current_session_id)
            raise

    # ---------- 附件 ----------

    def upload_attachment(self, file_path: str) -> dict:
        path = Path(file_path)
        if not path.exists():
            raise CliError(f"文件不存在: {file_path}")
        url = f"{self.api_url}/files/upload"
        try:
            with open(path, "rb") as f:
                with self._client(timeout=120) as client:
                    resp = client.post(
                        url,
                        headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
                        files={"file": (path.name, f, "application/octet-stream")},
                        params={
                            "agent_id": self.current_agent_id or "default",
                            "session_id": self.current_session_id or "default",
                        },
                    )
        except httpx.ConnectError as e:
            raise CliError(f"无法连接到服务器 {self.base_url}（{e}）") from e
        if resp.status_code >= 400:
            raise CliError(_error_message(resp.status_code, self._parse_json(resp)))
        body = self._parse_json(resp)
        return body if isinstance(body, dict) else {}

    # ---------- 审批 ----------

    def pending_approvals(self) -> dict:
        body = self._get("/governance/approvals/pending")
        return (body or {}).get("data", {}) if isinstance(body, dict) else {}

    def approve(self, approval_id: str, note: str = "REPL 批准") -> dict:
        body = self._post(f"/governance/approvals/{approval_id}/approve", json={"note": note, "approved_by": "user"})
        return (body or {}).get("data", {}) if isinstance(body, dict) else {}

    def reject(self, approval_id: str, note: str = "REPL 拒绝") -> dict:
        body = self._post(f"/governance/approvals/{approval_id}/reject", json={"note": note, "approved_by": "user"})
        return (body or {}).get("data", {}) if isinstance(body, dict) else {}

    # ---------- 记忆 ----------

    def list_memories(self, query: Optional[str] = None, limit: int = 30) -> dict:
        params: Dict[str, Any] = {"limit": limit, "agent_id": self.current_agent_id or "default"}
        if query:
            params["query"] = query
        body = self._get("/memory", params=params)
        return (body or {}).get("data", {}) if isinstance(body, dict) else {}

    def save_memory(self, content: str, category: Optional[str] = None) -> dict:
        payload: Dict[str, Any] = {"content": content}
        if category:
            payload["category"] = category
        body = self._post("/memory", json=payload)
        return (body or {}).get("data", {}) if isinstance(body, dict) else {}

    def delete_memory(self, memory_id: str) -> dict:
        body = self._delete(f"/memory/{memory_id}")
        return body if isinstance(body, dict) else {}

    def memory_stats(self) -> dict:
        body = self._get("/memory/stats")
        return (body or {}).get("data", {}) if isinstance(body, dict) else {}

    # ---------- 知识库 ----------

    def list_knowledge(self, scope: str = "private", limit: int = 30, category: Optional[str] = None) -> list:
        params: Dict[str, Any] = {"scope": scope, "limit": limit, "agent_id": self.current_agent_id or "default"}
        if category:
            params["category"] = category
        body = self._get("/knowledge", params=params)
        return body if isinstance(body, list) else []

    def search_knowledge(self, query: str, limit: int = 10) -> list:
        body = self._post("/knowledge/search", json={"query": query, "limit": limit})
        return body if isinstance(body, list) else []

    def create_knowledge(
        self,
        title: str,
        content: str,
        category: str = "general",
        tags: Optional[List[str]] = None,
        visibility: str = "private",
    ) -> dict:
        body = self._post(
            "/knowledge",
            json={
                "title": title,
                "content": content,
                "category": category,
                "tags": tags or [],
                "visibility": visibility,
            },
        )
        return body if isinstance(body, dict) else {}

    def delete_knowledge(self, knowledge_id: str) -> dict:
        body = self._delete(f"/knowledge/{knowledge_id}")
        return body if isinstance(body, dict) else {}

    def hybrid_search(self, query: str, source: str = "memory", top_k: int = 5) -> dict:
        body = self._post("/semantic-search/hybrid", json={"query": query, "top_k": top_k, "source": source})
        return (body or {}).get("data", {}) if isinstance(body, dict) else {}

    # ---------- 诊断 ----------

    def system_stats(self) -> dict:
        body = self._get("/stats/system")
        return body if isinstance(body, dict) else {}

    def performance_stats(self) -> dict:
        body = self._get("/stats/performance")
        return (body or {}).get("data", {}) if isinstance(body, dict) else {}

    def fetch_logs(self, limit: int = 30, level: Optional[str] = None) -> list:
        params: Dict[str, Any] = {"limit": limit}
        if level:
            params["level"] = level
        body = self._get("/logs", params=params)
        return body if isinstance(body, list) else []

    def health_report(self) -> dict:
        body = self._get("/health/report")
        return body if isinstance(body, dict) else {}

    # ==================== 渲染 ====================

    def _ok(self, msg: str) -> None:
        self.console.print(f"[bold nr.ok]{SYM_OK}[/bold nr.ok] {msg}")

    def _warn(self, msg: str) -> None:
        self.console.print(f"[bold nr.warn]{SYM_WARN}[/bold nr.warn] {msg}")

    def _err(self, msg: str) -> None:
        self.console.print(f"[bold nr.err]{SYM_ERR}[/bold nr.err] {msg}")

    @staticmethod
    def _short_id(sid: str, n: int = 8) -> str:
        return sid[:n] if sid else "-"

    # ---------- 命令：Agent ----------

    def cmd_agent(self, args: List[str]) -> None:
        if not args:
            self._agent_list()
            return
        sub = args[0].lower()
        if sub == "add":
            self._agent_create()
        elif sub in ("del", "delete"):
            self._agent_delete(args[1] if len(args) > 1 else None)
        elif sub == "switch":
            self._agent_switch(args[1] if len(args) > 1 else None)
        elif sub == "list":
            self._agent_list()
        elif sub.isdigit():
            self._agent_switch(sub)
        else:
            self._err("用法: /agent [list|add|del <序号|id>|switch <序号>]")

    def _agent_list(self) -> None:
        try:
            agents = self.list_agents()
        except CliError as e:
            self._err(str(e))
            return
        if not agents:
            self._warn("没有找到 Agent")
            return
        table = Table(title="Agent 列表", header_style="bold cyan")
        table.add_column("#", width=3)
        table.add_column("名称", overflow="fold")
        table.add_column("ID", overflow="fold")
        table.add_column("状态")
        table.add_column("模型", overflow="fold")
        for i, a in enumerate(agents, 1):
            marker = "▶" if a.get("agent_id") == self.current_agent_id else ""
            name = f"{marker} {a.get('name', 'Unknown')}"
            status = a.get("status", "unknown")
            color = "green" if status == "running" else ("yellow" if status == "config_only" else "red")
            table.add_row(str(i), name, a.get("agent_id", "-"), f"[{color}]{status}[/{color}]", a.get("model", "N/A"))
        self.console.print(table)
        self._warn("输入 /agent switch <序号> 切换")

    def _agent_switch(self, arg: Optional[str]) -> None:
        try:
            agents = self.list_agents()
        except CliError as e:
            self._err(str(e))
            return
        if not agents:
            self._err("没有可切换的 Agent")
            return
        if arg is None:
            self._warn("用法: /agent switch <序号|agent_id>")
            return
        if arg.isdigit():
            idx = int(arg) - 1
            if idx < 0 or idx >= len(agents):
                self._err(f"无效的序号: {arg}")
                return
            agent = agents[idx]
        else:
            agent = next((a for a in agents if a.get("agent_id") == arg), None)
            if not agent:
                self._err(f"未找到 Agent: {arg}")
                return
        self.current_agent_id = agent.get("agent_id")
        self.current_session_id = None
        self._ok(f"已切换 Agent: {agent.get('name')} (ID: {self.current_agent_id})")

    def _agent_create(self) -> None:
        name = self._input("Agent 名称: ").strip()
        if not name:
            return
        desc = self._input("描述 (可选): ").strip()
        ans = self._input("启用记忆? (Y/n): ").strip().lower()
        enable_memory = ans != "n"
        try:
            result = self.create_agent(name, desc, enable_memory)
        except CliError as e:
            self._err(str(e))
            return
        if result:
            self._ok(f"Agent 创建成功: {name} (ID: {result.get('agent_id')})")

    def _agent_delete(self, arg: Optional[str]) -> None:
        try:
            agents = self.list_agents()
        except CliError as e:
            self._err(str(e))
            return
        if not agents:
            self._warn("没有可删除的 Agent")
            return
        self._agent_list()
        agent = self._pick(agents, arg, key="agent_id")
        if not agent:
            return
        if agent.get("agent_id") == "default":
            self._err("default Agent 不可删除")
            return
        confirm = self._input(f"确定删除 Agent '{agent.get('name')}'? (y/N): ").strip().lower()
        if confirm != "y":
            self._warn("删除已取消")
            return
        try:
            self.delete_agent(agent.get("agent_id"))
        except CliError as e:
            self._err(str(e))
            return
        self._ok(f"Agent '{agent.get('name')}' 已删除")
        if self.current_agent_id == agent.get("agent_id"):
            self.current_agent_id = None

    # ---------- 命令：LLM ----------

    def cmd_llm(self, args: List[str]) -> None:
        if not args:
            self._llm_list()
            return
        sub = args[0].lower()
        if sub == "add":
            self._llm_create()
        elif sub in ("del", "delete"):
            self._llm_delete(args[1] if len(args) > 1 else None)
        elif sub == "switch":
            self._llm_switch(args[1] if len(args) > 1 else None)
        elif sub == "list":
            self._llm_list()
        elif sub.isdigit():
            self._llm_switch(sub)
        else:
            self._err("用法: /llm [list|add|del <序号|id>|switch <序号>]")

    def _llm_list(self) -> None:
        try:
            providers = self.list_providers()
        except CliError as e:
            self._err(str(e))
            return
        if not providers:
            self._warn("没有找到 LLM 服务商（普通用户未配置时为空是设计行为）")
            return
        table = Table(title="LLM 服务商", header_style="bold cyan")
        table.add_column("#", width=3)
        table.add_column("名称", overflow="fold")
        table.add_column("类型")
        table.add_column("状态")
        table.add_column("模型数", justify="right")
        for i, p in enumerate(providers, 1):
            active = "▶" if p.get("is_active") else ""
            status = p.get("status", "unknown")
            color = "green" if status == "connected" else "yellow"
            table.add_row(
                str(i),
                f"{active} {p.get('name', '-')}",
                p.get("provider_type", "-"),
                f"[{color}]{status}[/{color}]",
                str(p.get("models_count", 0)),
            )
        self.console.print(table)
        try:
            active = self.get_active_model()
            if active:
                model = active.get("model") or "未设置"
                self._ok(f"当前激活模型: {model} ({active.get('provider_name', 'N/A')})")
        except CliError:
            pass
        self._warn("/llm switch <序号> 切换服务商与模型")

    def _llm_switch(self, arg: Optional[str]) -> None:
        try:
            providers = self.list_providers()
        except CliError as e:
            self._err(str(e))
            return
        if not providers:
            self._err("没有可切换的服务商")
            return
        provider = self._pick(providers, arg, key="provider_id")
        if not provider:
            return
        try:
            models = self.discover_models(provider.get("provider_id"))
        except CliError as e:
            self._err(str(e))
            return
        if not models:
            self._warn(f"服务商 '{provider.get('name')}' 没有可用模型")
            return
        table = Table(title=f"{provider.get('name')} - 模型列表", header_style="bold cyan")
        table.add_column("#", width=3)
        table.add_column("模型 ID", overflow="fold")
        table.add_column("名称", overflow="fold")
        for i, m in enumerate(models, 1):
            mid = m.get("id", m) if isinstance(m, dict) else m
            table.add_row(str(i), str(mid), str(m.get("name", "")) if isinstance(m, dict) else "")
        self.console.print(table)
        choice = self._input("选择模型序号: ").strip()
        if not choice.isdigit():
            return
        idx = int(choice) - 1
        if idx < 0 or idx >= len(models):
            self._err("无效的序号")
            return
        model = models[idx]
        model_id = model.get("id", model) if isinstance(model, dict) else model
        try:
            result = self.activate_model(provider.get("provider_id"), str(model_id))
            self.current_model = result.get("model_id") or str(model_id)
            self._ok(f"已切换到模型: {self.current_model} ({provider.get('name')})")
        except CliError as e:
            self._err(f"激活失败: {e}")

    def _llm_create(self) -> None:
        self._warn("向导: openai/anthropic/gemini/ollama/openrouter/custom")
        name = self._input("服务商名称: ").strip()
        if not name:
            return
        ptype = self._input("服务商类型: ").strip()
        if ptype not in ("openai", "anthropic", "gemini", "ollama", "openrouter", "custom"):
            self._err("不支持的类型（支持: openai/anthropic/gemini/ollama/openrouter/custom）")
            return
        default_urls = {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com",
            "gemini": "https://generativelanguage.googleapis.com",
            "ollama": "http://localhost:11434",
            "openrouter": "https://openrouter.ai/api/v1",
            "custom": "https://api.example.com/v1",
        }
        base_url = self._input(f"API URL [{default_urls[ptype]}]: ").strip() or default_urls[ptype]
        api_key = ""
        if ptype != "ollama":
            api_key = self._input("API Key: ").strip()
            if not api_key:
                self._warn("未提供 API Key，连接可能失败")
        payload: Dict[str, Any] = {"name": name, "provider_type": ptype, "base_url": base_url}
        if api_key:
            payload["api_key"] = api_key
        try:
            result = self._post("/providers", json=payload)
        except CliError as e:
            self._err(str(e))
            return
        pid = result.get("provider_id") if isinstance(result, dict) else None
        self._ok(f"服务商创建成功: {name} (ID: {pid})")
        if pid:
            try:
                conn = self.check_connection(pid)
                if conn.get("success"):
                    self._ok(f"连接成功 ({conn.get('latency_ms', '-')} ms)")
                else:
                    self._err(f"连接失败: {conn.get('error', 'unknown')}")
            except CliError as e:
                self._err(str(e))

    def _llm_delete(self, arg: Optional[str]) -> None:
        try:
            providers = self.list_providers()
        except CliError as e:
            self._err(str(e))
            return
        provider = self._pick(providers, arg, key="provider_id")
        if not provider:
            return
        confirm = self._input(f"确定删除服务商 '{provider.get('name')}'？(y/N): ").strip().lower()
        if confirm != "y":
            self._warn("删除已取消")
            return
        try:
            self._delete(f"/providers/{provider.get('provider_id')}")
            self._ok(f"服务商 '{provider.get('name')}' 已删除")
        except CliError as e:
            self._err(str(e))

    # ---------- 命令：会话 ----------

    def cmd_sessions(self, args: List[str]) -> None:
        try:
            data = self.list_sessions()
        except CliError as e:
            self._err(str(e))
            return
        sessions = data.get("sessions", [])
        if not sessions:
            self._warn("暂无会话，用 /new [标题] 新建")
            return
        table = Table(title=f"会话列表（共 {data.get('total', 0)}）", header_style="bold cyan")
        table.add_column("#", width=3)
        table.add_column("ID", width=12)
        table.add_column("标题", overflow="fold")
        table.add_column("Agent", overflow="fold")
        table.add_column("创建时间", width=20, overflow="fold")
        for i, s in enumerate(sessions, 1):
            sid = s.get("id", "")
            marker = "▶" if sid == self.current_session_id else ""
            table.add_row(str(i), self._short_id(sid), f"{marker} {s.get('title', '-')}", s.get("agent_id", "-"), str(s.get("created_at", "")))
        self.console.print(table)
        self._warn("/session <序号|id> 切换，/new [标题] 新建")

    def cmd_session(self, args: List[str]) -> None:
        if not args:
            self.cmd_sessions([])
            return
        sub = args[0].lower()
        if sub in ("del", "delete"):
            self._session_delete(args[1] if len(args) > 1 else None)
        elif sub == "archive":
            self._session_archive(args[1] if len(args) > 1 else None)
        else:
            self._session_switch(args[0])

    def _session_switch(self, arg: str) -> None:
        try:
            data = self.list_sessions()
        except CliError as e:
            self._err(str(e))
            return
        sessions = data.get("sessions", [])
        if not sessions:
            self._err("暂无会话")
            return
        session = self._pick(sessions, arg, key="id")
        if not session:
            return
        self.current_session_id = session.get("id")
        self._ok(f"已切换会话: {session.get('title', '-')} (ID: {self._short_id(self.current_session_id)})")

    def _session_delete(self, arg: Optional[str]) -> None:
        try:
            data = self.list_sessions()
        except CliError as e:
            self._err(str(e))
            return
        session = self._pick(data.get("sessions", []), arg, key="id")
        if not session:
            return
        confirm = self._input(f"确定删除会话 '{session.get('title', '-')}'？(y/N): ").strip().lower()
        if confirm != "y":
            self._warn("删除已取消")
            return
        try:
            self.delete_session(session.get("id"))
            self._ok("会话已删除")
        except CliError as e:
            self._err(str(e))
        if self.current_session_id == session.get("id"):
            self.current_session_id = None

    def _session_archive(self, arg: Optional[str]) -> None:
        try:
            data = self.list_sessions()
        except CliError as e:
            self._err(str(e))
            return
        session = self._pick(data.get("sessions", []), arg, key="id")
        if not session:
            return
        try:
            self.archive_session(session.get("id"))
            self._ok("会话已归档")
        except CliError as e:
            self._err(str(e))

    def cmd_new(self, args: List[str]) -> None:
        title = " ".join(args) or "新对话"
        try:
            data = self.create_session(agent_id=self.current_agent_id, title=title)
        except CliError as e:
            self._err(str(e))
            return
        self.current_session_id = data.get("session_id")
        self.attachments = []
        self._ok(f"已新建会话: {title} (ID: {self._short_id(self.current_session_id)})")

    def cmd_history(self, args: List[str]) -> None:
        if not self.current_session_id:
            self._warn("尚未选择会话，先 /new 新建或用 /session 切换")
            return
        try:
            data = self.get_history(self.current_session_id)
        except CliError as e:
            self._err(str(e))
            return
        messages = data.get("messages", [])
        if not messages:
            self._warn("当前会话暂无消息")
            return
        table = Table(title=f"会话历史（{self._short_id(self.current_session_id)}）", header_style="bold cyan")
        table.add_column("角色", width=8)
        table.add_column("内容", overflow="fold")
        for m in messages:
            role = m.get("role", "-")
            color = "green" if role == "user" else "cyan"
            table.add_row(f"[{color}]{role}[/{color}]", str(m.get("content", ""))[:600])
        self.console.print(table)

    # ---------- 命令：thinking / model / stream ----------

    _THINK_MAP = {
        "简单": "light",
        "light": "light",
        "标准": "standard",
        "standard": "standard",
        "深度": "deep",
        "deep": "deep",
        "off": "",
        "关闭": "",
    }

    def cmd_think(self, args: List[str]) -> None:
        if not args:
            current = self.thinking_effort or "标准(默认)"
            self._warn(f"当前思考深度: {current}；用法: /think 简单|标准|深度|off")
            return
        raw = args[0]
        target = self._THINK_MAP.get(raw)
        if target is None:
            self._err("用法: /think 简单|标准|深度|off")
            return
        self.thinking_effort = target
        label = "标准(默认)" if target == "" else raw
        self._ok(f"思考深度已设为: {label}")

    def cmd_model(self, args: List[str]) -> None:
        if not args:
            self._warn(f"当前模型: {self.current_model or '未指定（后端默认）'}")
            return
        self.current_model = args[0]
        self._ok(f"模型已设为: {self.current_model}")

    def cmd_stream(self, args: List[str]) -> None:
        if not args:
            self._warn(f"当前模式: {'流式' if self.streaming else '非流式'}")
            return
        if args[0] in ("on", "1", "true", "流式"):
            self.streaming = True
            self._ok("已切换到流式输出")
        elif args[0] in ("off", "0", "false", "非流式"):
            self.streaming = False
            self._ok("已切换到非流式输出（等待完整回复）")
        else:
            self._err("用法: /stream [on|off]")

    # ---------- 命令：附件 ----------

    def cmd_file(self, args: List[str]) -> None:
        if not args:
            if self.attachments:
                self._warn(f"已添加附件: {', '.join(self.attachments)}")
            else:
                self._warn("用法: /file <路径> 添加附件；/file clear 清空")
            return
        if args[0] == "clear":
            self.attachments = []
            self._ok("附件已清空")
            return
        path = " ".join(args)
        try:
            info = self.upload_attachment(path)
        except CliError as e:
            self._err(str(e))
            return
        file_id = info.get("file_id")
        if not file_id:
            self._err("上传未返回 file_id")
            return
        self.attachments.append(file_id)
        self._ok(f"已添加附件: {info.get('filename', path)} ({info.get('size', '?')} 字节)")

    # ---------- 命令：审批 ----------

    def cmd_approval(self, args: List[str]) -> None:
        if not args or args[0].lower() in ("list", "ls"):
            self._approval_list()
            return
        try:
            data = self.approve(args[0])
        except CliError as e:
            self._err(str(e))
            return
        self._print_approval_result(data)

    def _approval_list(self) -> None:
        try:
            data = self.pending_approvals()
        except CliError as e:
            self._err(str(e))
            return
        requests = data.get("requests", [])
        if not requests:
            self._warn("当前没有待审批事项")
            return
        table = Table(title="待审批列表", header_style="bold yellow")
        table.add_column("#", width=3)
        table.add_column("ID", width=16)
        table.add_column("工具")
        table.add_column("原因", overflow="fold")
        table.add_column("状态")
        for i, r in enumerate(requests, 1):
            table.add_row(str(i), r.get("request_id", "-"), r.get("tool_name", "-"), str(r.get("danger_reason", ""))[:80], r.get("status", "?"))
        self.console.print(table)
        self._warn("/approval <ID|序号> 批准；/reject <ID|序号> 拒绝")

    def _print_approval_result(self, data: dict) -> None:
        if data.get("approved"):
            if data.get("executed"):
                self._ok("工具已获批准并执行")
                result = data.get("result")
                if result:
                    self.console.print(f"[dim]执行结果:[/dim] {json.dumps(result, ensure_ascii=False)[:200]}")
                self._warn("工具执行结果不会自动回插原对话流；可用 /history 查看或直接继续对话")
            else:
                self._ok("工具已批准（无可重放内容）")
        else:
            self._err("批准失败")

    def cmd_reject(self, args: List[str]) -> None:
        if not args:
            self._err("用法: /reject <审批ID|序号> [备注]")
            return
        rid = args[0]
        note = " ".join(args[1:]) or "REPL 拒绝"
        if rid.isdigit():
            try:
                data = self.pending_approvals()
            except CliError as e:
                self._err(str(e))
                return
            req = self._pick(data.get("requests", []), rid, key="request_id")
            if not req:
                return
            rid = req.get("request_id")
        try:
            self.reject(rid, note=note)
            self._ok("已拒绝该审批")
        except CliError as e:
            self._err(str(e))

    # ---------- 命令：记忆 / 知识 ----------

    def cmd_memories(self, args: List[str]) -> None:
        if args and args[0].lower() in ("del", "delete"):
            self._memory_delete(args[1] if len(args) > 1 else None)
            return
        query = " ".join(args) or None
        try:
            data = self.list_memories(query=query)
        except CliError as e:
            self._err(str(e))
            return
        memories = data.get("memories", [])
        if not memories:
            self._warn("没有相关记忆（可用 /memory save <内容> 保存）")
            return
        table = Table(title=f"记忆列表（{data.get('count', 0)} 条）", header_style="bold cyan")
        table.add_column("ID", width=14)
        table.add_column("内容", overflow="fold")
        table.add_column("分类")
        table.add_column("温度", justify="right")
        for m in memories:
            table.add_row(self._short_id(m.get("id", ""), 12), str(m.get("content", ""))[:80], m.get("category", "-"), f"{m.get('temperature', 0):.2f}")
        self.console.print(table)

    def _memory_delete(self, arg: Optional[str]) -> None:
        if not arg:
            self._err("用法: /memories del <ID>")
            return
        confirm = self._input(f"确定删除记忆 {arg}？(y/N): ").strip().lower()
        if confirm != "y":
            self._warn("删除已取消")
            return
        try:
            self.delete_memory(arg)
            self._ok("记忆已删除")
        except CliError as e:
            self._err(str(e))

    def cmd_memory(self, args: List[str]) -> None:
        if not args:
            self._memory_stats()
            return
        sub = args[0].lower()
        if sub == "stats":
            self._memory_stats()
        elif sub == "save":
            content = " ".join(args[1:])
            if not content:
                self._err("用法: /memory save <内容>")
                return
            category = None
            if "--category" in args:
                i = args.index("--category")
                category = args[i + 1] if i + 1 < len(args) else None
            try:
                data = self.save_memory(content, category=category)
                self._ok(f"记忆已保存: {data.get('memory_id', '-')}")
            except CliError as e:
                self._err(str(e))
        elif sub in ("del", "delete"):
            self._memory_delete(args[1] if len(args) > 1 else None)
        else:
            self._err("用法: /memory [stats|save <内容>|del <ID>]")

    def _memory_stats(self) -> None:
        try:
            data = self.memory_stats()
        except CliError as e:
            self._err(str(e))
            return
        stats = data if isinstance(data, dict) else {}
        self.console.print(
            f"记忆统计: 总数 [cyan]{stats.get('total_memories', 0)}[/cyan]，"
            f"近期保留 [cyan]{stats.get('remember_count', 0)}[/cyan]，"
            f"召回 [cyan]{stats.get('recall_count', 0)}[/cyan]；/memories 查看列表"
        )

    def cmd_knowledge(self, args: List[str]) -> None:
        if not args or args[0].lower() in ("list", "ls"):
            self._knowledge_list(args[1:])
            return
        sub = args[0].lower()
        if sub == "find":
            self._knowledge_search(" ".join(args[1:]))
        elif sub == "add":
            self._knowledge_add(args[1:])
        elif sub in ("del", "delete"):
            self._knowledge_delete(args[1] if len(args) > 1 else None)
        else:
            self._err("用法: /knowledge [list|find <关键词>|add <标题> --content <内容>|del <ID>]")

    def _knowledge_list(self, args: List[str]) -> None:
        scope = "private"
        category = None
        if "--scope" in args:
            i = args.index("--scope")
            if i + 1 < len(args):
                scope = args[i + 1]
        if "--category" in args:
            i = args.index("--category")
            if i + 1 < len(args):
                category = args[i + 1]
        try:
            items = self.list_knowledge(scope=scope, category=category)
        except CliError as e:
            self._err(str(e))
            return
        if not items:
            self._warn("没有知识条目（可用 /knowledge add <标题> --content <内容> 添加）")
            return
        table = Table(title=f"知识库（scope={scope}）", header_style="bold cyan")
        table.add_column("ID", width=20)
        table.add_column("标题", overflow="fold")
        table.add_column("分类")
        table.add_column("可见性")
        for k in items:
            table.add_row(self._short_id(k.get("knowledge_id", ""), 16), k.get("title", "-"), k.get("category", "-"), k.get("visibility", "-"))
        self.console.print(table)

    def _knowledge_search(self, query: str) -> None:
        if not query:
            self._err("用法: /knowledge find <关键词>")
            return
        try:
            items = self.search_knowledge(query)
        except CliError as e:
            self._err(str(e))
            return
        if not items:
            self._warn(f"知识库中未找到: {query}")
            return
        table = Table(title=f"知识检索: {query}", header_style="bold cyan")
        table.add_column("ID", width=20)
        table.add_column("标题", overflow="fold")
        table.add_column("内容", overflow="fold")
        for k in items:
            table.add_row(self._short_id(k.get("knowledge_id", ""), 16), k.get("title", "-"), str(k.get("content", ""))[:80])
        self.console.print(table)

    def _knowledge_add(self, args: List[str]) -> None:
        title = None
        content = None
        category = "general"
        visibility = "private"
        rest = list(args)
        if "--content" in rest:
            i = rest.index("--content")
            title = " ".join(rest[:i]) or None
            content = " ".join(rest[i + 1:])
        elif len(args) >= 2:
            title = args[0]
            content = " ".join(args[1:])
        if "--category" in rest:
            i = rest.index("--category")
            if i + 1 < len(rest):
                category = rest[i + 1]
        if "--visibility" in rest:
            i = rest.index("--visibility")
            if i + 1 < len(rest):
                visibility = rest[i + 1]
        if not title or not content:
            self._err("用法: /knowledge add <标题> --content <内容> [--category 分类] [--visibility private|public]")
            return
        try:
            result = self.create_knowledge(title, content, category=category, visibility=visibility)
        except CliError as e:
            if "admin" in str(e).lower():
                self._err(f"设为 public 需要 admin 权限: {e}")
            else:
                self._err(str(e))
            return
        self._ok(f"知识条目已创建: {result.get('knowledge_id', '-')}")

    def _knowledge_delete(self, arg: Optional[str]) -> None:
        if not arg:
            self._err("用法: /knowledge del <ID>")
            return
        confirm = self._input(f"确定删除知识条目 {arg}？(y/N): ").strip().lower()
        if confirm != "y":
            self._warn("删除已取消")
            return
        try:
            self.delete_knowledge(arg)
            self._ok("知识条目已删除")
        except CliError as e:
            self._err(str(e))

    def cmd_search(self, args: List[str]) -> None:
        query = " ".join(args)
        source = "memory"
        if query.rsplit(" ", 1)[-1] in ("memory", "knowledge"):
            parts = query.rsplit(" ", 1)
            query = parts[0]
            source = parts[1]
        if not query:
            self._err("用法: /search <关键词> [memory|knowledge]")
            return
        try:
            data = self.hybrid_search(query, source=source)
        except CliError as e:
            self._err(str(e))
            return
        results = data.get("results", [])
        if not results:
            self._warn(f"[{source}] 检索无结果: {query}")
            return
        table = Table(title=f"混合检索: {query}（{source}，共 {data.get('total', 0)} 条）", header_style="bold cyan")
        table.add_column("#", width=3)
        table.add_column("内容", overflow="fold")
        table.add_column("得分", justify="right")
        for i, r in enumerate(results, 1):
            text = r.get("text") or r.get("content") or json.dumps(r, ensure_ascii=False)[:80]
            score = r.get("score", r.get("similarity", "-"))
            table.add_row(str(i), str(text)[:100], f"{score:.3f}" if isinstance(score, float) else str(score))
        self.console.print(table)

    # ---------- 命令：诊断 ----------

    def cmd_health(self, args: List[str]) -> None:
        ok = self.check_health()
        if not ok:
            self._err(f"后端不可达: {self.base_url}")
            return
        try:
            report = self.health_report()
        except CliError as e:
            self._err(str(e))
            return
        checks = report.get("checks", {}) if isinstance(report, dict) else {}
        self.console.print(
            f"健康状态: [green]{report.get('status', 'unknown')}[/green]，"
            f"检查器 {report.get('healthy_count', 0)}/{report.get('total_checks', 0)} 通过"
        )
        if not checks:
            self._warn("未注册系统检查器（health/checks 为空）；建议查看 /stats 与 /logs")
        else:
            for name, c in checks.items():
                color = "green" if c.get("status") == "ok" else "red"
                self.console.print(f"  [{color}]{name}[/{color}]: {c.get('message', '')}")

    def cmd_stats(self, args: List[str]) -> None:
        try:
            sys_stats = self.system_stats()
        except CliError as e:
            self._err(str(e))
            return
        cpu = sys_stats.get("cpu", {})
        mem = sys_stats.get("memory", {})
        disk = sys_stats.get("disk", {})
        self.console.print(
            f"系统: [bold]{sys_stats.get('status', '?')}[/bold] 版本 {sys_stats.get('version', '?')} | "
            f"CPU [cyan]{cpu.get('percent', 0):.1f}%[/cyan] | "
            f"内存 [cyan]{mem.get('percent', 0):.1f}%[/cyan] | "
            f"磁盘 [cyan]{disk.get('percent', 0):.1f}%[/cyan]"
        )
        try:
            perf = self.performance_stats()
            net = perf.get("network_io", {})
            self.console.print(
                f"性能: 网络收发 {net.get('bytes_sent', 0)} 字节 / "
                f"活动连接 {perf.get('active_connections', 0)}"
            )
        except CliError:
            pass

    def cmd_logs(self, args: List[str]) -> None:
        level = None
        limit = 30
        if args and args[0].lower() == "level" and len(args) > 1:
            level = args[1].upper()
        elif args:
            try:
                limit = int(args[0])
            except ValueError:
                limit = 30
        try:
            logs = self.fetch_logs(limit=limit, level=level)
        except CliError as e:
            self._err(str(e))
            return
        if not logs:
            self._warn("没有日志记录")
            return
        table = Table(title=f"系统事件日志（最近 {limit} 条）", header_style="bold cyan")
        table.add_column("级别", width=10)
        table.add_column("来源")
        table.add_column("消息", overflow="fold")
        for log in logs[-limit:]:
            lvl = str(log.get("level", "-"))
            color = "yellow" if lvl in ("WARNING", "ERROR", "CRITICAL") else "cyan"
            table.add_row(f"[{color}]{lvl}[/{color}]", str(log.get("source", "-")), str(log.get("message", ""))[:120])
        self.console.print(table)

    def cmd_monitor(self, args: List[str]) -> None:
        try:
            body = self._get("/monitor/status")
        except CliError as e:
            self._err(str(e))
            return
        self.console.print(
            f"[bold]monitor[/bold] 状态: {body.get('status', '?')} 版本 {body.get('version', '?')} "
            f"Python {body.get('python_version', '?')}"
        )
        try:
            resources = self._get("/monitor/resources")
            if isinstance(resources, dict):
                self.console.print(f"[dim]{json.dumps(resources, ensure_ascii=False)[:300]}[/dim]")
        except CliError:
            pass

    def cmd_status(self, args: List[str]) -> None:
        agent = self.current_agent_id or "未选择"
        session = self._short_id(self.current_session_id) if self.current_session_id else "未选择"
        think = self.thinking_effort or "标准(默认)"
        self.console.print(
            f"用户 [cyan]{self.username or '-'}[/cyan] | Agent [cyan]{agent}[/cyan] | "
            f"会话 [cyan]{session}[/cyan] | 模型 [cyan]{self.current_model or '后端默认'}[/cyan] | "
            f"思考深度 [cyan]{think}[/cyan] | 输出模式 [cyan]{'流式' if self.streaming else '非流式'}[/cyan]"
        )
        if self.attachments:
            self._warn(f"附件: {len(self.attachments)} 个已就绪，下条消息将携带")

    def cmd_login(self, args: List[str]) -> None:
        user = args[0] if args else None
        pwd = None
        if "--password" in args:
            i = args.index("--password")
            if i + 1 < len(args):
                pwd = args[i + 1]
        user = user or self._input("用户名: ").strip()
        if not pwd:
            import getpass
            pwd = getpass.getpass("密码: ")
        if self.login(username=user, password=pwd):
            self._ok(f"登录成功，欢迎 {self.username}")
        else:
            self._err("登录失败，请检查用户名/密码")

    def cmd_help(self, args: List[str]) -> None:
        self.console.print(
            """[bold]Neurova REPL 命令[/bold]
[cyan]/agent[/cyan]          [list|add|del <序号>|switch <序号>] 管理 Agent
[cyan]/llm[/cyan]            [list|add|del <序号>|switch <序号>] 管理 LLM 服务商与模型
[cyan]/model[/cyan] <id>     指定本次对话模型（回车查看当前）
[cyan]/think[/cyan] <简单|标准|深度|off>  调整思考深度
[cyan]/stream[/cyan]         [on|off] 切换流式/非流式输出
[cyan]/sessions[/cyan]       列出会话
[cyan]/session[/cyan] <序号|id>   切换会话；[del <序号>|archive <序号>] 清理
[cyan]/new[/cyan] [标题]     新建会话
[cyan]/history[/cyan] [N]    查看当前会话历史
[cyan]/file[/cyan] <路径>    上传附件（下条消息携带）；/file clear 清空
[cyan]/approval[/cyan]       [list|ID] 查看/批准待审批事项
[cyan]/reject[/cyan] <ID>    拒绝待审批事项
[cyan]/memories[/cyan]       [关键词|del <ID>] 查看/删除记忆
[cyan]/memory[/cyan]         [stats|save <内容>|del <ID>] 记忆管理
[cyan]/knowledge[/cyan]      [list|find <词>|add <标题> --content <内容>|del <ID>]
[cyan]/search[/cyan] <词>    [memory|knowledge] 混合检索
[cyan]/health[/cyan]         后端健康与检查器
[cyan]/stats[/cyan]          系统资源统计
[cyan]/logs[/cyan] [N|level LEVEL]  最近系统事件日志
[cyan]/monitor[/cyan]        进程级概览
[cyan]/status[/cyan]         当前用户/Agent/会话/模型/思考深度
[cyan]/login[/cyan]          重新登录
[cyan]/help[/cyan]           帮助 · [cyan]/clear[/cyan] 清屏 · [cyan]/exit[/cyan] 退出
直接输入文字开始聊天；行尾 \\ 续行；Ctrl+C 中断生成或退出"""
        )

    # ---------- 输入辅助 ----------

    def _input(self, prompt: str) -> str:
        try:
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            return ""

    def _pick(self, items: list, arg: Optional[str], key: str) -> Optional[dict]:
        """按序号（1 起始）或 id 从列表挑选实体。"""
        if not items:
            self._err("列表为空")
            return None
        if arg is None:
            self._warn("缺少参数（序号或 ID）")
            return None
        if arg.isdigit():
            idx = int(arg) - 1
            if idx < 0 or idx >= len(items):
                self._err(f"无效的序号: {arg}")
                return None
            item = items[idx]
            return item if isinstance(item, dict) else None
        for item in items:
            if isinstance(item, dict) and item.get(key) == arg:
                return item
        self._err(f"未找到: {arg}")
        return None

    # ---------- 主循环 ----------

    def dispatch(self, line: str) -> None:
        """分发一条已归一化的命令/消息行。"""
        line = line.strip()
        if not line:
            return
        if line.startswith("/"):
            parts = line.split()
            cmd = parts[0].lower().lstrip("/")
            args = parts[1:]
            # 直觉别名（复数/缩写）
            cmd = {
                "agents": "agent",
                "provider": "llm",
                "providers": "llm",
                "llms": "llm",
                "mem": "memory",
                "kb": "knowledge",
                "sess": "session",
            }.get(cmd, cmd)
            handler = {
                "agent": self.cmd_agent,
                "llm": self.cmd_llm,
                "sessions": self.cmd_sessions,
                "session": self.cmd_session,
                "new": self.cmd_new,
                "history": self.cmd_history,
                "think": self.cmd_think,
                "model": self.cmd_model,
                "stream": self.cmd_stream,
                "file": self.cmd_file,
                "approval": self.cmd_approval,
                "reject": self.cmd_reject,
                "memories": self.cmd_memories,
                "memory": self.cmd_memory,
                "knowledge": self.cmd_knowledge,
                "search": self.cmd_search,
                "health": self.cmd_health,
                "stats": self.cmd_stats,
                "logs": self.cmd_logs,
                "monitor": self.cmd_monitor,
                "status": self.cmd_status,
                "login": self.cmd_login,
                "help": self.cmd_help,
                "clear": lambda a: self.console.print("\033[2J\033[H", end=""),
                "exit": lambda a: setattr(self, "running", False),
                "stop": lambda a: self.stop_chat(self.current_session_id) if self.current_session_id else None,
            }.get(cmd)
            if handler:
                handler(args)
            else:
                self._err(f"未知命令: {cmd}。输入 /help 查看帮助")
        else:
            self._chat_message(line)

    def _chat_message(self, message: str) -> None:
        if not self.current_agent_id:
            self._warn("未选择 Agent（/agent switch <序号> 选择后再聊）")
            return
        self.console.print("")
        self._begin_turn(message)
        started = time.monotonic()
        try:
            result = self.send_chat(
                message,
                file_ids=self.attachments or None,
                on_event=lambda kind, data: self._render_stream_event(kind, data),
            )
            self.attachments = []
            self._flush_reasoning()
            reply = result.get("reply", "") if isinstance(result, dict) else result
        except CliError as e:
            self._flush_reasoning()
            self._write_frame_stream(ansi(f"{SYM_ERR} {e}", "error", self._draw_color) + "\n")
        except KeyboardInterrupt:
            self._flush_reasoning()
            self._write_frame_stream(ansi(f"{SYM_ERR} 生成已中断", "error", self._draw_color) + "\n")
        finally:
            self._end_turn()
            # 回合收尾: Hermes 状态栏（模型/轮次/会话/用时）——流被中断也保留会话粘性
            elapsed = time.monotonic() - started
            self._turn_count += 1
            self.console.print(
                render_status_bar(
                    self.current_model or "-",
                    self._short_id(self.current_session_id) if self.current_session_id else "",
                    turn=self._turn_count,
                    elapsed=elapsed,
                )
            )
            self._reply_marker = False

    # ---------- 回合帧（对话内容双线框） ----------

    @property
    def _frame_limit(self) -> int:
        """帧内容显示宽（框总宽 = console 宽）。"""
        return max(int(getattr(self.console, "width", 80)) - 4, 20)

    def _begin_turn(self, message: str) -> None:
        """开回合帧: 顶框（含用户消息）后进入流式状态。"""
        self._reply_marker = False
        file = self.console.file
        file.write(render_turn_frame_top(message, self._frame_limit, self._draw_color) + "\n")
        file.flush()
        self._frame_col = 0

    def _write_frame_stream(self, text: str) -> None:
        """流式/整行写入帧内: 行首补 ║, 换行与满宽自动折行, 右竖线固定在框边。

        ANSI SGR 转义按 0 宽度透传（不参与列计数）。
        """
        file = self.console.file
        limit = self._frame_limit
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == "\x1b":
                j = text.find("m", i)
                if j == -1:
                    file.write(text[i:])
                    break
                # 行首先落 ║ 前缀, 再透传色码（避免左竖线被染色）
                if self._frame_col == 0:
                    file.write("║ ")
                    self._frame_col = 2
                file.write(text[i : j + 1])
                i = j + 1
                continue
            if self._frame_col == 0:
                file.write("║ ")
                self._frame_col = 2
            if ch == "\n":
                self._frame_close_line()
                i += 1
                continue
            file.write(ch)
            self._frame_col += _display_width(ch)
            if self._frame_col >= limit + 2:
                file.write(" ║\n")
                self._frame_col = 0
            i += 1
        file.flush()

    def _frame_close_line(self) -> None:
        """闭合当前帧内行: 补齐空格让右竖线落在固定列。"""
        limit = self._frame_limit
        pad = limit - (self._frame_col - 2)
        if pad > 0:
            self.console.file.write(" " * pad)
        self.console.file.write(" ║\n")
        self._frame_col = 0

    def _end_turn(self) -> None:
        """闭合回合帧: 补齐尾部竖线 + 底框。"""
        file = self.console.file
        if self._frame_col != 0:
            self._frame_close_line()
        file.write(render_turn_frame_bottom(self._frame_limit) + "\n")
        file.flush()
        self._frame_col = 0

    def _flush_reasoning(self) -> None:
        """把聚合的思考段落一次性输出（避免逐 token 刷屏）。

        Hermes 对齐: `▸ 思考 · 摘要` 单行（muted 蓝），在回合帧内输出。
        """
        if not self._reasoning_buf:
            return
        text = "".join(self._reasoning_buf)
        self._write_frame_stream(_text_to_ansi(render_reasoning(text), self._draw_color) + "\n")
        self._reasoning_buf = []

    def _render_stream_event(self, kind: str, data: Any) -> None:
        """流式事件的增量渲染（chunk 正文 / reasoning 聚合 / 工具折叠）。

        回调 data 语义：chunk/reasoning 为内容字符串；tool_*/approval 为事件 dict。
        """
        color = self._draw_color
        if kind == "reasoning":
            text = data if isinstance(data, str) else (data or {}).get("content", "")
            if text:
                self._reasoning_buf.append(text)
        elif kind == "chunk":
            self._flush_reasoning()
            text = data if isinstance(data, str) else (data or {}).get("content", "")
            if text:
                if not self._reply_marker:
                    self._write_frame_stream(_text_to_ansi(render_assistant_marker(), color))
                    self._reply_marker = True
                self._write_frame_stream(text)
        elif kind == "tool_call":
            self._flush_reasoning()
            name = (data or {}).get("name", "-")
            args = (data or {}).get("arguments", "")
            self._write_frame_stream(_text_to_ansi(render_tool_call(name, str(args)), self._draw_color) + "\n")
        elif kind == "tool_result":
            self._flush_reasoning()
            content = (data or {}).get("content", "")
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            self._write_frame_stream(_text_to_ansi(render_tool_result(text), self._draw_color) + "\n")
        elif kind == "approval_required":
            self._flush_reasoning()
            aid = (data or {}).get("approval_id", "-")
            tool = (data or {}).get("tool_name", "-")
            self._write_frame_stream(_text_to_ansi(render_approval(tool, aid), self._draw_color) + "\n")

    def _load_history(self) -> None:
        try:
            if self.console.is_terminal and HISTORY_FILE.exists():
                lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
                self._history = [l for l in lines if l.strip()][-HISTORY_MAX:]
        except OSError:
            self._history = []

    def _save_history(self, line: str) -> None:
        if not line.strip():
            return
        try:
            self._history.append(line)
            if len(self._history) > HISTORY_MAX:
                self._history = self._history[-HISTORY_MAX:]
            HISTORY_FILE.write_text("\n".join(self._history[-HISTORY_MAX:]), encoding="utf-8")
        except OSError:
            pass

    def _read_input(self, prompt: str) -> str:
        """带历史回填与 tab 补全的输入读取（Windows ANSI 序列处理）。"""
        try:
            raw = input(prompt)
        except EOFError:
            return ""
        except KeyboardInterrupt:
            raise
        kind, text = parse_ansi_input(raw)
        if kind == "up":
            if not self._history_cache and self._history:
                self._history_cache = list(self._history)
            if self._history_cache:
                line = self._history_cache.pop()
                sys.stdout.write("\r" + " " * 80 + "\r" + prompt + line)
                sys.stdout.flush()
                return line
            return self._read_input(prompt)
        if kind == "down":
            self._history_cache = []
            return self._read_input(prompt)
        line = text or ""
        if "\t" in line:
            completed, candidates = complete_line(line.replace("\t", " "))
            if candidates:
                hint = render_completion_hint(candidates).plain
                sys.stdout.write("\r" + " " * 80 + "\r" + hint + "\n" + prompt + line)
                sys.stdout.flush()
                return self._read_input(prompt)
            line = completed
        return line

    def run(self) -> None:
        from scripts.common import print_logo

        self._load_history()
        print_logo("Neurova REPL 聊天客户端")
        # 欢迎屏（Hermes welcome 范式: 品牌 → 圆角面板状态行 → 帮助提示）
        welcome_lines: List[Text] = [
            render_welcome_icon_line(SYM_INFO, f"服务器  {self.base_url}", style="accent"),
        ]
        if not self.check_health():
            self._err(f"无法连接到后端 {self.base_url}——请先启动 (python start_server.py)")
            return
        welcome_lines.append(render_welcome_icon_line(SYM_OK, "后端连接成功"))
        try:
            if not self.login():
                welcome_lines.append(render_welcome_icon_line(SYM_ERR, "自动登录失败，输入 /login 手动登录；或 /status 查看状态"))
            else:
                welcome_lines.append(render_welcome_icon_line(SYM_OK, f"登录成功: {self.username}"))
        except CliError as e:
            welcome_lines.append(render_welcome_icon_line(SYM_ERR, str(e)))
        try:
            agents = self.list_agents()
            if agents:
                self.current_agent_id = agents[0].get("agent_id")
                self.current_model = agents[0].get("model") or self.current_model
                welcome_lines.append(
                    render_welcome_icon_line(SYM_INFO, f"Agent {agents[0].get('name')} · {agents[0].get('model', '-')}", style="accent")
                )
        except CliError:
            pass
        self.console.print(render_welcome_panel(welcome_lines, render_help_hint()))
        self.console.print("")
        while self.running:
            try:
                prompt = prompt_text(self._draw_color)
                raw = self._read_input(prompt)
                if raw is None:
                    continue
                message = raw.strip()
                if not message:
                    continue
                # 行尾 \ 续行
                while message.endswith("\\"):
                    nxt = self._read_input("... ")
                    if not nxt:
                        break
                    message = message[:-1] + nxt.strip()
                self._save_history(message)
                self.dispatch(message)
            except KeyboardInterrupt:
                self.console.print("\n[dim]再见！[/dim]")
                self.running = False
            except CliError as e:
                self._err(str(e))


def main():
    parser = argparse.ArgumentParser(description="Neurova REPL 聊天客户端")
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="服务器 URL")
    parser.add_argument("--username", default=None, help="登录用户名（默认交互输入或 NEUROVA_USERNAME）")
    parser.add_argument("--password", default=None, help="登录密码（默认交互输入或 NEUROVA_PASSWORD）")
    args = parser.parse_args()
    cli = NeurovaCLI(base_url=args.url, username=args.username, password=args.password)
    cli.run()


if __name__ == "__main__":
    main()
