"""进程环境配置读取入口。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def get(key: str, default: Optional[str] = None) -> Optional[str]:
    """读取环境变量字符串值，未设置时返回 default。"""
    return os.environ.get(key, default)


def loadEnvFile(envPath: Optional[Path] = None) -> bool:
    """加载 .env 文件进 os.environ；python-dotenv 缺席时返回 False。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    return bool(load_dotenv(envPath))


def get_int(key: str, default: int = 0) -> int:
    """读取环境变量并转为整数；缺失或非法时返回 default。"""
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def get_bool(key: str, default: bool = False) -> bool:
    """读取环境变量并转为布尔值。"""
    val = os.environ.get(key)
    if val is None:
        return default
    return val.lower() in ("true", "1", "yes", "on")


def proxyUvicornArgs() -> Dict[str, object]:
    """经反代/中继运行时 uvicorn 需要的参数。"""
    return {
        "proxy_headers": True,
        "forwarded_allow_ips": ",".join(
            get_list("NEUROVA_FORWARDED_ALLOW_IPS", default=["127.0.0.1"])
        ),
    }


def get_list(
    key: str,
    default: Optional[List[str]] = None,
    sep: str = ",",
) -> List[str]:
    """读取环境变量并拆分列表，去除空白与空项。"""
    val = os.environ.get(key)
    if val is None:
        return default if default is not None else []
    return [item.strip() for item in val.split(sep) if item.strip()]
