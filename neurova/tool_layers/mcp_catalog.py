"""
MCP 白名单目录（P0-2，docs/Neurova_Agent工具扩展计划_2026-09-12.md）。

精选若干原生工具面缺失、社区高星且经 MCP 通道零核心改动接入的能力包，
让非专家一键接上。目录只负责「产出配置」，实际持久化/连接/鉴权复用既有
connect 端点链路（validate_mcp_server_config + stdio 需 admin 门）。

收敛记录：计划的「官方 servers 的 git/fetch」与 P0-3 原生 git 工具 + 已有
web_fetch 重叠，按「不镀金 / 白名单不是全都接」剔除，首批仅三个真缺口：
- github   代码托管协作（官方 github-mcp-server，分发形态 Docker → requires=docker）
- context7 库文档实时检索（官方 @upstash/context7-mcp，Node 已随包捆绑 → npx 开箱）
- dbhub    只读 SQL 查询（@bytebase/dbhub，token 友好，npx 开箱）

密钥去向按各 server 真实接口诚实标注（required_secrets[].into）：
- env：github token / context7 key（进程环境，不进 args 展示面）
- arg：dbhub DSN（该 server 仅支持 --dsn 命令行传参，无 env 通道；DSN 与既有
  用户手填 MCP 配置同属共享配置明文存储，风险面不变）
"""

import typing

# 每个条目：id / name / description / transport / command / args 模板 /
# requires（依赖探针，供 UI 门控）/ required_secrets（[{key, required, into, prompt}]）
_CATALOG: typing.List[typing.Dict[str, typing.Any]] = [
    {
        "id": "github",
        "name": "GitHub",
        "description": "GitHub 官方 MCP：仓库/Issue/PR/CI 协作（官方 github/github-mcp-server）。",
        "source": "github/github-mcp-server",
        "transport": "stdio",
        "requires": "docker",
        "command": "docker",
        "args": [
            "run", "-i", "--rm",
            "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
            "ghcr.io/github/github-mcp-server",
        ],
        "required_secrets": [
            {"key": "GITHUB_PERSONAL_ACCESS_TOKEN", "required": True, "into": "env",
             "prompt": "GitHub Personal Access Token"},
        ],
    },
    {
        "id": "context7",
        "name": "Context7",
        "description": "各主流库的最新版官方文档与代码示例实时检索（upstash/context7）。",
        "source": "upstash/context7",
        "transport": "stdio",
        "requires": "node",
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp"],
        "required_secrets": [
            {"key": "CONTEXT7_API_KEY", "required": False, "into": "env",
             "prompt": "Context7 API Key（可选，提升限额）"},
        ],
    },
    {
        "id": "dbhub",
        "name": "DBHub",
        # 只读约束的诚实落点（P1-4）：dbhub 无 --readonly CLI 标志（只读经 --config
        # TOML 或只读数据库账号，其官方 "read-only bundle" 亦靠此）。代理层正则匹配
        # SQL 写关键字会误伤所有 MCP 文本参数（mcp_config 注释点名的"安全剧场"），
        # 故本目录以「必须使用只读账号 DSN」为契约，把写权限收口在数据库账号授权面。
        "description": "只读 SQL 查询数据源（bytebase/dbhub，Postgres/MySQL/SQLite 等），token 友好。必须提供只读账号 DSN（写权限由数据库账号授权层禁止，非代理层字符串匹配）。",
        "source": "bytebase/dbhub",
        "transport": "stdio",
        "requires": "node",
        "command": "npx",
        "args": ["-y", "@bytebase/dbhub"],
        # dbhub 无 env 通道，DSN 只能经 --dsn 命令行参数传入
        "dsn_arg": ["--dsn"],
        "required_secrets": [
            {"key": "CONNECTION_STRING", "required": True, "into": "arg",
             "prompt": "只读账号数据库连接串（DSN）——必须使用仅有 SELECT 权限的账号",
             "read_only_required": True},
        ],
    },
]


def list_catalog() -> typing.List[typing.Dict[str, typing.Any]]:
    """返回目录条目（深拷贝副本，调用方不可改内部表）。"""
    import copy

    return copy.deepcopy(_CATALOG)


def get_entry(entry_id: str) -> typing.Dict[str, typing.Any]:
    for e in _CATALOG:
        if e["id"] == entry_id:
            return e
    raise KeyError(entry_id)


def build_server_config(
    entry_id: str, secrets: typing.Optional[typing.Dict[str, str]] = None
) -> typing.Dict[str, typing.Any]:
    """把目录条目 + 用户密钥实例化为一份 MCP server 配置（未校验，交调用方 validate）。

    Args:
        entry_id: 目录 id
        secrets: 密钥字典 {secret_key: value}

    Returns:
        符合 validate_mcp_server_config 字段的配置 dict

    Raises:
        KeyError: entry_id 不存在
        ValueError: 缺必填密钥
    """
    secrets = secrets or {}
    entry = get_entry(entry_id)

    env: typing.Dict[str, str] = {}
    extra_args: typing.List[str] = []
    for spec in entry["required_secrets"]:
        key = spec["key"]
        value = str(secrets.get(key) or "").strip()
        if not value:
            if spec.get("required"):
                raise ValueError(f"缺少必填密钥: {key}")
            continue
        if spec["into"] == "env":
            env[key] = value
        elif spec["into"] == "arg":
            dsn_flag = entry.get("dsn_arg", ["--dsn"])
            extra_args.extend([*dsn_flag, value])

    return {
        "id": f"catalog_{entry_id}",
        "name": entry["name"],
        "description": entry["description"],
        "transport": entry["transport"],
        "command": entry["command"],
        "args": list(entry["args"]) + extra_args,
        "env": env,
        "enabled": True,
    }
