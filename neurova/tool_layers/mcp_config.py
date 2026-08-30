"""
MCP Server 配置严格 schema 验证

参照 ZCode 配置模式：未知键显式拒绝（fail fast，不静默丢弃）、
transport 推断（command→stdio / url→http，显式声明优先）、缺必需字段拒绝并指名。

字段集:
    id          必填 str，服务器唯一标识
    name        展示名，默认取 id
    description 默认 ""
    enabled     默认 True
    transport   stdio / http / sse；缺省时按 command/url 推断
    command/args/cwd/env    stdio 必需 command
    url/headers             http、sse 必需 url
    timeout_ms  默认 30000，必须为正数
"""

import os.path
import typing

_ALLOWED_KEYS = {
    "id", "name", "description", "enabled", "transport",
    "command", "args", "cwd", "env",
    "url", "headers",
    "timeout_ms",
}

_VALID_TRANSPORTS = {"stdio", "http", "sse"}

_DEFAULT_TIMEOUT_MS = 30000

# shell 拒绝表（P0-1）：stdio MCP server 的 command 是 argv[0]（无 shell
# 注入面），但显式以 shell 作为 server 进程等于把任意命令执行敞开。
# 不做解释器白名单——npx/python 本身就能执行任意代码，白名单是安全剧场；
# 进程派生的权限边界由 API 层角色校验承担（stdio 仅限 admin）。
# Windows 可执行后缀在匹配前剥离（bash.exe 与 bash 同为 shell）。
_SHELL_COMMANDS = {
    "sh", "bash", "zsh", "fish", "csh", "tcsh", "ksh",
    "cmd", "powershell", "pwsh", "wsl",
}
_SHELL_SUFFIXES = (".exe", ".cmd", ".bat")


def _reject_shell_command(server: typing.Dict[str, typing.Any]) -> None:
    command = server.get("command")
    if not command:
        return
    basename = os.path.basename(str(command)).lower()
    if basename.endswith(_SHELL_SUFFIXES):
        basename = basename[: -len(basename.rsplit(".", 1)[1]) - 1]
    if basename in _SHELL_COMMANDS:
        _reject(
            f"command 禁止使用 shell（{basename}）——stdio MCP server "
            "不应包装 shell 执行，请直接指定目标可执行文件"
        )


def _reject(message: str) -> typing.NoReturn:
    raise ValueError(f"MCP server 配置无效: {message}")


def _validate_types(server: typing.Dict[str, typing.Any]) -> None:
    sid = server.get("id")
    if not sid or not isinstance(sid, str):
        _reject("id 必须为非空字符串")

    if "name" in server and not isinstance(server["name"], str):
        _reject("name 必须为字符串")

    command = server.get("command")
    if command is not None and not isinstance(command, str):
        _reject("command 必须为字符串")

    url = server.get("url")
    if url is not None and not isinstance(url, str):
        _reject("url 必须为字符串")

    args = server.get("args")
    if args is not None:
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            _reject("args 必须为字符串列表")

    env = server.get("env")
    if env is not None and not isinstance(env, dict):
        _reject("env 必须为字符串到字符串的字典")

    headers = server.get("headers")
    if headers is not None and not isinstance(headers, dict):
        _reject("headers 必须为字符串到字符串的字典")

    timeout_ms = server.get("timeout_ms")
    if timeout_ms is not None:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, (int, float)) or timeout_ms <= 0:
            _reject("timeout_ms 必须为正数")

    transport = server.get("transport")
    if transport is not None and transport not in _VALID_TRANSPORTS:
        _reject(f"transport 必须为 {'/'.join(sorted(_VALID_TRANSPORTS))} 之一，收到 {transport!r}")


def _infer_transport(server: typing.Dict[str, typing.Any]) -> str:
    transport = server.get("transport")
    if transport:
        return transport
    if server.get("command"):
        return "stdio"
    if server.get("url"):
        return "http"
    _reject("transport 缺失，且无法从 command/url 推断")


def _require_transport_inputs(transport: str, server: typing.Dict[str, typing.Any]) -> None:
    if transport == "stdio" and not server.get("command"):
        _reject("transport=stdio 需要 command 字段")
    if transport in ("http", "sse") and not server.get("url"):
        _reject(f"transport={transport} 需要 url 字段")


def validate_mcp_server_config(server: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
    """校验并规范化 MCP server 配置。

    未知键显式拒绝（含键名），合法配置返回填充了默认值的规范化副本，不修改入参。

    Raises:
        ValueError: 配置非法（消息指名问题字段）
    """
    if not isinstance(server, dict):
        _reject("配置必须为字典")

    unknown = set(server.keys()) - _ALLOWED_KEYS
    if unknown:
        _reject(f"未知字段 {sorted(unknown)}，允许的字段: {sorted(_ALLOWED_KEYS)}")

    _validate_types(server)

    transport = _infer_transport(server)
    _require_transport_inputs(transport, server)
    _reject_shell_command(server)

    normalized = {
        "id": server["id"],
        "name": server.get("name") or server["id"],
        "description": server.get("description", ""),
        "enabled": server.get("enabled", True),
        "transport": transport,
        "command": server.get("command", ""),
        "args": list(server.get("args") or []),
        "cwd": server.get("cwd"),
        "env": dict(server.get("env") or {}),
        "url": server.get("url", ""),
        "headers": dict(server.get("headers") or {}),
        "timeout_ms": server.get("timeout_ms") or _DEFAULT_TIMEOUT_MS,
    }
    return normalized
