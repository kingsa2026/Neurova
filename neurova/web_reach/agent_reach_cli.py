"""agent-reach CLI 桥接——跨平台内容直达的唯一集成面（单一事实源）。

集成面收口记录：web_reach 此前对 agent-reach 的集成点是
``from agent_reach.core import AgentReach``／``agent_reach.config.Config``
两个库模块——经实测（run_doctor 旧 docstring 现量 + 本模块落地前复核），
PyPI ``agent-reach`` 0.1.0 与源码仓 main 的 ``src`` 布局都**不存在**这两个
模块，该集成点今天是死门（social_search 因此恒 backend_unavailable）。
上游真实提供的是 **CLI 面**（本模块的唯一对接对象），契约以 v1.6.0 实测为准：

- stdout 单行 JSON envelope：
  ``{schema_version, ok, channel, action, backend, items, meta, error}``
- doctor：``{ok, action:"doctor", result:{version, channels:[{channel, level,
  status, problems, hint, regressed}], ...}}``（channels 是**列表**，非字典）
- ``agent-reach channels``：全量渠道/动作/参数语法（机器可读）
- 错误码：NEED_SETUP／NEED_LOGIN／UPSTREAM_BROKEN／TIMEOUT／RATE_LIMITED／
  NOT_FOUND／BAD_INPUT，``error`` 恒带 ``{code, message, hint}``
- 安装（CLI 文档口径；PyPI 同名包不是本项目）：
  ``uv tool install https://github.com/Panniantong/Agent-Reach/archive/refs/tags/v1.6.0.zip``

安全边界：
- 一律 argv 直传（无 shell），位置参数入口拒绝 ``-`` 开头（防被解析成 flag）
- ``read`` 模式入口过 ``neurova.security.url_guard.assert_public_url``——CLI
  自带抓取会绕过本仓出网层，SSRF 门必须在桥接这一侧守住
- 子进程环境走 ``utf8ChildEnv()``（子进程编码单源纪律）
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.core.text_encoding import utf8ChildEnv
from neurova.security.url_guard import assert_public_url

logger = get_logger(__name__)

CLI_NAME = "agent-reach"
INSTALL_GUIDE = (
    "agent-reach CLI 未安装。安装：uv tool install "
    "https://github.com/Panniantong/Agent-Reach/archive/refs/tags/v1.6.0.zip"
    "（PyPI 同名包不是本项目）。装后若命令不在 PATH，重启终端或运行 uv tool update-shell。"
)
_DEFAULT_TIMEOUT_S = 200.0
_LIMIT_MIN, _LIMIT_MAX = 1, 100

# envelope 顶层键白名单：原样带出给消费方（其余键归一化时不透传）
_ENVELOPE_KEYS = ("channel", "action", "backend", "items", "meta", "result", "commands", "channels")


def resolveExecutable() -> Optional[str]:
    """定位 agent-reach 可执行文件：PATH 优先，回退 uv 默认 bin 目录。

    uv tool install 的产物落 ``~/.local/bin`` 且常不在当前进程 PATH 上
    （安装器自身会提示），不回退则已装用户也会被误报未安装。
    """
    found = shutil.which(CLI_NAME)
    if found:
        return found
    exeName = "agent-reach.exe" if os.name == "nt" else CLI_NAME
    fallback = Path.home() / ".local" / "bin" / exeName
    if fallback.is_file():
        return str(fallback)
    return None


def runAgentReach(args: List[str], timeout: float = _DEFAULT_TIMEOUT_S) -> Dict[str, Any]:
    """执行 agent-reach 子命令并把 JSON envelope 归一为统一结果形态。

    Returns:
        成功：``{success: True, <envelope 白名单键原样>}``
        失败：``{success: False, code?, error, hint?}``；未安装时附
        ``not_installed: True`` 与安装指引。失败一律点名原因，不吞不猜。
    """
    exe = resolveExecutable()
    if not exe:
        return {"success": False, "not_installed": True, "error": INSTALL_GUIDE}
    try:
        run = subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=utf8ChildEnv(),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"agent-reach 执行超时（{timeout:g}s）"}
    except OSError as e:
        return {"success": False, "error": f"agent-reach 执行失败: {e}"}

    text = (run.stdout or "").strip()
    if not text:
        return {
            "success": False,
            "error": f"agent-reach 无输出（exit {run.returncode}）: {(run.stderr or '')[:200]}",
        }
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError:
        return {"success": False, "error": f"agent-reach 输出非 JSON: {text[-200:]}"}
    if not isinstance(envelope, dict) or "ok" not in envelope:
        return {"success": False, "error": "agent-reach 输出缺 ok 字段（契约不符）", "raw": text[:200]}

    normalized: Dict[str, Any] = {key: envelope[key] for key in _ENVELOPE_KEYS if key in envelope}
    rawError = envelope.get("error")
    if envelope.get("ok") is True:
        normalized["success"] = True
        return normalized

    if isinstance(rawError, dict):
        normalized.update(
            success=False,
            code=str(rawError.get("code") or "UNKNOWN"),
            error=str(rawError.get("message") or "未知错误"),
            hint=rawError.get("hint"),
        )
    else:
        normalized.update(success=False, code="UNKNOWN", error=str(rawError or text[-200:]))
    return normalized


def runChannels() -> Dict[str, Any]:
    """列出全部渠道与动作语法（``agent-reach channels``）。"""
    return runAgentReach(["channels"])


def runRead(url: str) -> Dict[str, Any]:
    """按链接自动选渠道读取（``agent-reach read <url>``）。

    入口先过 SSRF 门（CLI 自带抓取绕过本仓出网层，门必须在桥接侧守住）。
    """
    url = (url or "").strip()
    if not url:
        return {"success": False, "error": "缺少 URL"}
    scheme = url.split(":", 1)[0].lower()
    if scheme not in ("http", "https"):
        return {"success": False, "error": f"仅支持 http/https 协议（收到 {scheme or '空'}）"}
    try:
        assert_public_url(url)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    return runAgentReach(["read", url])


def runChannelAction(
    channel: str,
    action: str,
    target: Optional[str] = None,
    limit: Optional[int] = None,
    extraArgs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """调渠道动作（``agent-reach <channel> <action> [args] [--limit N] ...``）。

    位置参数（target）入口拒绝 ``-`` 开头：会被 CLI 解析成 flag 而不是检索词。
    extra_args 是显式 flag 通道（各元素须为字符串，原样直传）。
    """
    channel = (channel or "").strip()
    action = (action or "").strip()
    if not channel or not action:
        return {"success": False, "error": "缺少 channel 或 action（先 runChannels 查语法）"}
    if channel.startswith("-") or action.startswith("-"):
        return {"success": False, "error": f"channel/action 不能以 - 开头（收到 {channel}/{action}）"}

    argv: List[str] = [channel, action]
    if target is not None:
        target = str(target).strip()
        if not target:
            target = None
        elif target.startswith("-"):
            return {"success": False, "error": f"target 不能以 - 开头（会被 CLI 当 flag）：{target[:40]}"}
        argv.append(target)

    if limit is not None:
        try:
            limitVal = int(limit)
        except (TypeError, ValueError):
            return {"success": False, "error": f"limit 需为整数（收到 {limit!r}）"}
        if not _LIMIT_MIN <= limitVal <= _LIMIT_MAX:
            return {"success": False, "error": f"limit 需在 {_LIMIT_MIN}..{_LIMIT_MAX}（收到 {limitVal}）"}
        argv.extend(["--limit", str(limitVal)])

    if extraArgs:
        extraArgs = list(extraArgs)
        if not all(isinstance(flag, str) for flag in extraArgs):
            return {"success": False, "error": "extra_args 各元素须为字符串（flag 原样直传）"}
        argv.extend(extraArgs)

    return runAgentReach(argv)


def runDoctor() -> Dict[str, Any]:
    """渠道后端体检（``agent-reach doctor``；只读配置，不执行渠道探测）。

    成功：``{success, data: <result 原样>, version}``；失败：错误透传。
    """
    res = runAgentReach(["doctor"])
    if not res.get("success"):
        return res
    data = res.get("result") or {}
    return {"success": True, "data": data, "version": (data or {}).get("version")}


def doctorChannels(doctorData: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """doctor 体检读数的渠道字典化（上游 channels 是列表，按名建索引）。"""
    return {
        str(entry.get("channel") or ""): entry
        for entry in (doctorData or {}).get("channels") or []
        if isinstance(entry, dict)
    }
