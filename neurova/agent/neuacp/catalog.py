# -*- coding: utf-8 -*-
"""外部编码代理工具目录：内置预设 + 本机命令探测。

- 运行时事实源是名册 ``executor.command``（生效值）；本目录只给默认值、
  能力标注与本机可用探测（设计文档 §4.9）。
- CLI 安装检查发生在「用户启用连接时」（catalog 查询/测试连接的实时
  ``shutil.which`` 探测），部署期不预装不强校验；未命中返回
  ``installed=false`` + ``install_hint``。
"""
import shutil
from typing import Any, Dict, List, Optional

#: 内置预设（默认 command 为官方口径，允许名册覆盖）。
CATALOG: Dict[str, Dict[str, Any]] = {
    "opencode": {
        "kind": "acp",
        "transport": "stdio",
        "command": ["opencode", "acp"],
        "origin": "native",
        "install_hint": "https://opencode.ai/docs/",
    },
    "qoder": {
        "kind": "acp",
        "transport": "stdio",
        "command": ["qoder", "--acp"],
        "origin": "native",
        "install_hint": "https://docs.qoder.com/cli/acp",
    },
    "codebuddy": {
        "kind": "acp",
        "transport": "stdio",
        "command": ["npx", "@tencent-ai/codebuddy-code", "--acp"],
        "origin": "native",
        "requires_node": True,
        "install_hint": "npm i -g @tencent-ai/codebuddy-code",
    },
    "zcode": {
        "kind": "plugin",
        "transport": "stdio",
        "command": [
            "zcode",
            "--output-format", "stream-json",
            "--no-color",
            "--mode", "yolo",
            "--disallowed-tools", "AskUserQuestion,EnterPlanMode,ExitPlanMode",
        ],
        "origin": "headless-cli",
        "install_hint": "https://zcode.z.ai/cn/docs",
    },
    "gemini-cli": {
        "kind": "acp",
        "transport": "stdio",
        "command": ["gemini", "--acp"],
        "origin": "native",
        "install_hint": "https://github.com/google-gemini/gemini-cli",
    },
    "claude-code": {
        "kind": "acp",
        "transport": "stdio",
        "command": ["npx", "@agentclientprotocol/claude-agent-acp"],
        "origin": "adapter",
        "requires_node": True,
        "install_hint": "npm i -g @agentclientprotocol/claude-agent-acp",
    },
    "codex": {
        "kind": "acp",
        "transport": "stdio",
        "command": ["npx", "@agentclientprotocol/codex-acp"],
        "origin": "adapter",
        "requires_node": True,
        "install_hint": "npm i -g @agentclientprotocol/codex-acp",
    },
    # 已裁定暂不接入（2026-11-19）：结论留档，不进生效预设。
    "trae": {
        "kind": "acp",
        "transport": "stdio",
        "command": ["traecli", "acp", "serve"],
        "origin": "native",
        "disabled": True,
        "install_hint": "https://docs.trae.cn/cli_agent-client-protocol",
    },
}


def defaultCommand(tool: str) -> Optional[List[str]]:
    """目录默认启动命令；未知工具/禁用工具返回 None。"""
    entry = CATALOG.get(str(tool or "").strip())
    if entry is None or entry.get("disabled"):
        return None
    return list(entry.get("command") or [])


def probeTool(tool: str) -> Dict[str, Any]:
    """单工具本机探测：CLI 安装检查在用户启用连接时实时执行。"""
    entry = CATALOG.get(str(tool or "").strip())
    if entry is None:
        return {"tool": tool, "known": False, "installed": False}
    head = (entry.get("command") or [""])[0]
    needs_node = bool(entry.get("requires_node"))
    installed = bool(shutil.which(head)) if head else False
    if needs_node and installed:
        installed = bool(shutil.which("node")) or bool(shutil.which("npx"))
    return {
        "tool": tool,
        "known": True,
        "kind": entry.get("kind"),
        "origin": entry.get("origin"),
        "command": entry.get("command"),
        "requires_node": needs_node,
        "disabled": bool(entry.get("disabled")),
        "installed": installed,
        "install_hint": entry.get("install_hint"),
    }


def listCatalog() -> List[Dict[str, Any]]:
    """全量目录（每项附本机探测结果），供管理面/前端下拉。"""
    return [probeTool(tool) for tool in CATALOG]
