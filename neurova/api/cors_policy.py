"""CORS 口径的唯一事实源（§6-199，序 9 双源口径批）。

建档时实测的分散形态（都在本模块收口，两侧不再各留一份）：
- 8 项 origins 白名单逐字写了两遍：`api/middleware.py` 的 `DEFAULT_CORS_ORIGINS` 与
  `api/endpoints/settings.py` 的 `_DEFAULT_CORS_ORIGINS`；
- `allow_methods` / `allow_headers` 两条清单写了 6 遍（中间件装配处 1 遍 + 管理端模型缺省、
  兜底 dict、GET 回显、PUT 回显各 1 遍）；
- 行为分叉：三级优先（env > 文件 > 默认）只有中间件实现，管理端 `GET /settings/cors`
  只看文件与自带缺省 ⇒ 设了 env 后面板显示的是一份**没在生效**的清单，
  管理员照着它改白名单会改错东西。

本模块只提供一份口径，两侧各自的生产读取函数都转发到这里：
`middleware._load_cors_origins_from_config` 与 `settings._load_cors_config`。

env 仍经 `neurova.core.config.get` 读（不是直取 `os.environ`）——既有守卫
`test_cors_tauri_origins.py` 就 patch 这个入口，直取 env 会把那条守卫绕过。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core import config
from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 桌面壳（Tauri v2 WebView）与开发端口的 origin 白名单。少一条 `*.tauri.localhost`
#: 就会让打包产物打不通后端——历史成因见 `tests/unit/api/test_cors_tauri_origins.py` 的档头。
DEFAULT_ORIGINS = (
    "http://localhost:8100",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:8100",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "http://tauri.localhost",
    "https://tauri.localhost",
)

#: 允许的 HTTP 方法与请求头（此前散在 6 处字面量里，收口后只此一处）
ALLOW_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS")
ALLOW_HEADERS = ("Authorization", "Content-Type", "Accept", "X-Request-ID")

#: 覆盖式白名单的环境变量名（逗号分隔）
ORIGINS_ENV_KEY = "NEUROVA_CORS_ORIGINS"

ALLOW_CREDENTIALS_DEFAULT = True


def configFile() -> Path:
    """CORS 配置落点：仓库 `config/cors.json`（打包时原样带进安装包）。

    此前中间件与管理端各算一遍这个路径；两处算法今天恰好得出同一个结果，
    但"靠巧合一致"不是单源——一处改径即分叉。
    """
    return Path(__file__).resolve().parent.parent.parent / "config" / "cors.json"


def _originsFromEnv() -> Optional[List[str]]:
    raw = (config.get(ORIGINS_ENV_KEY, "") or "").strip()
    if not raw:
        return None
    return [item.strip() for item in raw.split(",") if item.strip()]


def _originsFromFile(path: Path) -> Optional[List[str]]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning("CORS 配置读不懂，本次不采信也不改写 %s: %s", path, exc)
        return None
    origins = data.get("origins")
    if isinstance(origins, list) and origins:
        return [str(item) for item in origins]
    return None


def effectiveOrigins(config_file: Optional[str] = None) -> List[str]:
    """当前**实际生效**的 origins：环境变量 > 配置文件 > 默认值。"""
    fromEnv = _originsFromEnv()
    if fromEnv:
        return fromEnv
    path = Path(config_file) if config_file is not None else configFile()
    fromFile = _originsFromFile(path)
    if fromFile:
        return fromFile
    return list(DEFAULT_ORIGINS)


def effectiveConfig(config_file: Optional[str] = None) -> Dict[str, Any]:
    """当前**实际生效**的完整 CORS 口径（面板与中间件共读这一份）。

    文件里写了 `allow_credentials` 就采信文件的，否则用缺省——方法与请求头
    不提供按文件覆盖：仓内没有任何一处按调用方放宽它们的场景，留两个可选键
    只会多两本账。
    """
    path = Path(config_file) if config_file is not None else configFile()
    credentials = ALLOW_CREDENTIALS_DEFAULT
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict) and "allow_credentials" in data:
                credentials = bool(data["allow_credentials"])
        except (OSError, ValueError) as exc:
            logger.warning("CORS 配置读不懂，本次不采信也不改写 %s: %s", path, exc)
    return {
        "origins": effectiveOrigins(config_file),
        "allow_credentials": credentials,
        "allow_methods": list(ALLOW_METHODS),
        "allow_headers": list(ALLOW_HEADERS),
    }
