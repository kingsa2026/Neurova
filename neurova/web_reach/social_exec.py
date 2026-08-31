"""社交平台搜索的真实执行层：凭据经子进程 env 注入调用上游 CLI。

安全边界：
- 凭据只存在于子进程环境中（不进返回值、不进日志）
- 子进程按平台白名单映射到固定命令（argv 头部固定，query 作为 argv 参数）
- 输出按后端解析（JSON 优先，失败回退原始文本截断）
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.web_reach.credentials import PLATFORM_REQUIRED_KEYS

logger = get_logger(__name__)

# 平台 → 上游 CLI 命令（argv 头部固定；凭据走 env，不进 argv）
_PLATFORM_CLI = {
    "twitter": ["twitter"],
    "reddit": ["rdt"],
    "xiaohongshu": ["xhs"],
}


def _build_env(credentials: Dict[str, str], platform: str) -> Dict[str, str]:
    """复制当前环境并注入该平台凭据（凭据只存在于子进程环境中）。

    环境变量名由凭据 key 大写派生（如 twitter_auth_token → TWITTER_AUTH_TOKEN）。
    """
    env = dict(os.environ)
    for key in PLATFORM_REQUIRED_KEYS.get(platform, []):
        value = credentials.get(key)
        if value:
            env[key.upper()] = value
    return env


def _parse_output(stdout: str) -> List[Dict[str, Any]]:
    """解析上游 CLI 输出：JSON 优先，失败回退为行/文本形态"""
    text = (stdout or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
        if isinstance(payload, list):
            return [
                item if isinstance(item, dict) else {"text": str(item)}
                for item in payload
            ]
        if isinstance(payload, dict):
            for key in ("data", "results", "tweets", "items"):
                inner = payload.get(key)
                if isinstance(inner, list):
                    return [
                        item if isinstance(item, dict) else {"text": str(item)}
                        for item in inner
                    ]
            return [payload]
    except (json.JSONDecodeError, ValueError):
        pass
    # 回退：按行输出
    return [{"text": line} for line in text.splitlines() if line.strip()]


def execute_social_search(
    platform: str,
    query: str,
    limit: int = 10,
    credentials: Optional[Dict[str, str]] = None,
    active_backend: str = "",
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """执行社交平台搜索（凭据经 env 注入上游 CLI）。

    Returns:
        {"success", "executed": True, "results": [...], "active_backend", "query"}
    """
    credentials = credentials or {}
    cli = _PLATFORM_CLI.get(platform)
    if not cli:
        return {"success": False, "error": f"平台无执行命令映射: {platform}"}

    env = _build_env(credentials, platform)
    argv = cli + ["search", query, "-n", str(max(1, int(limit)))]

    try:
        run = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"{platform} 搜索超时（{timeout}s）", "executed": True}
    except FileNotFoundError:
        return {
            "success": False,
            "error": f"上游 CLI 未安装: {cli[0]}（请安装后重试）",
            "executed": True,
        }

    if run.returncode != 0:
        return {
            "success": False,
            "error": (run.stderr or run.stdout or "上游 CLI 执行失败")[:400],
            "executed": True,
            "active_backend": active_backend,
        }

    results = _parse_output(run.stdout)
    logger.info(
        "social search executed: platform=%s backend=%s results=%s",
        platform, active_backend, len(results),
    )
    return {
        "success": True,
        "executed": True,
        "results": results,
        "active_backend": active_backend,
        "query": query,
    }
