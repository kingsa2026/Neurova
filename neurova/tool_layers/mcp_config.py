"""
MCP Server 配置严格 schema 验证

未知键显式拒绝（fail fast，不静默丢弃）
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
    tool_capabilities  可选，{工具名: 并行能力声明}；缺省空表（一律串行）
    oauth       可选，{授权参数}；键名与必填项按 mcp_oauth 的取值点定（见 _OAUTH_*）
"""

import os.path
import typing

_ALLOWED_KEYS = {
    "id", "name", "description", "enabled", "transport",
    "command", "args", "cwd", "env",
    "url", "headers",
    "timeout_ms",
    # 本仓侧的并行能力声明位（工具名 → 声明）。MCP 工具的 schema 由第三方 server
    # 提供、本仓改不了，故声明落在**本仓侧的 server 配置**上——即"每个提供方
    # 自己的声明处"，不是集中一份大名单。形状与推导见 `core/tool_capability.py`。
    "tool_capabilities",
    # OAuth 参数位。读侧三处消费者（`mcp_client.call_tool` 取 token、
    # `/mcp-servers/{id}/oauth/authorize`、`GET /mcp-servers` 的 `oauth_grant`）
    # 一直在取它，此前却不在允许键里 ⇒ 生产注册路径存不下，只有测试夹具造得出。
    "oauth",
}

# oauth 子键集取自 `mcp_oauth.py` 的取值点（现场反推，不留第二份口径）：
# TokenCache.get_or_create 取 token_url/client_id（缺则调用期 KeyError），
# run_authorization_code_flow 取 authorization_url/registration_endpoint/redirect_uri/scope。
_OAUTH_KEYS = {
    "grant_type", "client_id", "client_secret", "scope",
    "token_url", "authorization_url", "registration_endpoint", "redirect_uri",
}
_OAUTH_GRANT_TYPES = {"client_credentials", "authorization_code"}

# oauth 里**由本仓主动出网请求**的三个 URL 字段。注册层据此走 `assert_public_url`
# （非 admin）——新增出网目标不得绕过既有 SSRF 门。
# 不含 redirect_uri：那是 IdP 回跳到**本机环回**的地址，语义相反（RFC 8252 要求环回）。
OAUTH_OUTBOUND_URL_KEYS = ("token_url", "authorization_url", "registration_endpoint")

_VALID_TRANSPORTS = {"stdio", "http", "sse"}

# M12：社区文档/前端常用 streamable_http 指代 streamable HTTP 传输，
# 归一化为 http 后进校验与存储
_TRANSPORT_ALIASES = {"streamable_http": "http"}

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


def _validate_oauth(oauth: typing.Any) -> None:
    """校验 oauth 子配置：拦掉「存进去就会在调用期炸」的形状。

    必填项取自读取方本身（`TokenCache.get_or_create` 用下标取 token_url/client_id，
    `run_authorization_code_flow` 要求 authorization_url 与 client_id|registration_endpoint
    二者之一）——在配置期拒绝，比在工具调用栈里抛 KeyError 诚实。
    """
    if not isinstance(oauth, dict):
        _reject("oauth 必须为「授权参数」字典")

    unknown = set(oauth.keys()) - _OAUTH_KEYS
    if unknown:
        _reject(f"oauth 未知字段 {sorted(unknown)}，允许的字段: {sorted(_OAUTH_KEYS)}")

    for key, value in oauth.items():
        if not isinstance(value, str):
            _reject(f"oauth.{key} 必须为字符串")

    grant_type = (oauth.get("grant_type") or "client_credentials").strip()
    if grant_type not in _OAUTH_GRANT_TYPES:
        _reject(
            f"oauth.grant_type 必须为 {'/'.join(sorted(_OAUTH_GRANT_TYPES))} 之一，收到 {grant_type!r}"
        )

    if not oauth.get("token_url"):
        _reject("oauth.token_url 必填（换取 access token 的端点）")

    if grant_type == "client_credentials":
        if not oauth.get("client_id"):
            _reject("oauth.client_id 必填（client_credentials 流需预配置客户端凭据）")
        return

    if not oauth.get("authorization_url"):
        _reject("oauth.authorization_url 必填（authorization_code 流的授权端点）")
    if not oauth.get("client_id") and not oauth.get("registration_endpoint"):
        _reject(
            "oauth.client_id 缺失时必须提供 oauth.registration_endpoint，"
            "以走 RFC 7591 动态客户端注册（DCR）"
        )
    redirect_uri = oauth.get("redirect_uri") or ""
    if redirect_uri:
        # 环回谓词与 mcp_oauth 同一份实现，不在此重述规则
        from neurova.tool_layers.mcp_oauth import _is_loopback_redirect_uri

        if not _is_loopback_redirect_uri(redirect_uri):
            _reject(f"oauth.redirect_uri 必须是环回地址（RFC 8252），拒绝: {redirect_uri}")


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

    capabilities = server.get("tool_capabilities")
    if capabilities is not None:
        if not isinstance(capabilities, dict):
            _reject("tool_capabilities 必须为「工具名 → 声明」的字典")
        for tool_name, declaration in capabilities.items():
            if not isinstance(tool_name, str) or not tool_name:
                _reject("tool_capabilities 的工具名必须为非空字符串")
            if not isinstance(declaration, dict):
                _reject(f"tool_capabilities[{tool_name!r}] 必须为字典")

    oauth = server.get("oauth")
    if oauth is not None and oauth != {}:
        # 空表＝"未配置"（前端与注册请求体的缺省形状），不是一套残缺的 OAuth 参数；
        # 除此之外一律进校验——oauth="" 这种错形状不许被当成空表静默放过
        _validate_oauth(oauth)

    transport = server.get("transport")
    if transport:
        # 空字符串视为未指定（交由 _infer_transport 按 command/url 推断）
        normalized = _TRANSPORT_ALIASES.get(transport, transport)
        if normalized not in _VALID_TRANSPORTS:
            _reject(f"transport 必须为 {'/'.join(sorted(_VALID_TRANSPORTS))} 之一，收到 {transport!r}")


def _infer_transport(server: typing.Dict[str, typing.Any]) -> str:
    capabilities = server.get("tool_capabilities")
    if capabilities is not None:
        if not isinstance(capabilities, dict):
            _reject("tool_capabilities 必须为「工具名 → 声明」的字典")
        for tool_name, declaration in capabilities.items():
            if not isinstance(tool_name, str) or not tool_name:
                _reject("tool_capabilities 的工具名必须为非空字符串")
            if not isinstance(declaration, dict):
                _reject(f"tool_capabilities[{tool_name!r}] 必须为字典")

    transport = server.get("transport")
    if transport:
        return _TRANSPORT_ALIASES.get(transport, transport)
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
        # 声明位进归一化副本：只加允许键而不落输出，声明会在校验那一刻被静默丢弃
        # （写了没人读的断点）。逐条深拷贝，调用方改返回值不会回写输入。
        "tool_capabilities": {
            str(tool_name): dict(declaration)
            for tool_name, declaration in (server.get("tool_capabilities") or {}).items()
        },
        # oauth 同规：允许了却不落输出，等于把断点从「存不下」换成「存下了却读不到」
        "oauth": dict(server.get("oauth") or {}),
    }
    return normalized
