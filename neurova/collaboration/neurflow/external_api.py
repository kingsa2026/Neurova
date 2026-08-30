"""
Neurflow 外部平台 API 统一客户端层 — 深模块

为 Neurflow 节点提供统一的外部平台接入：
- 图像生成 ImageGenClient（ComfyUI / OpenAI / 可灵 / 即梦 / 通义万相 / Stability）
- 视频生成 VideoGenClient（可灵 / 即梦 / Runway / Pika / ComfyUI，提交+轮询）
- 电商数据 CommercePlatformClient（亚马逊/淘宝/京东/抖音/TikTok/拼多多/1688/小红书/咸鱼/希音）
- 视频发布 PublishPlatformClient（抖音/快手/B站/TikTok/小红书）

约定：
- API Key 统一经 SecretStore 加密存储，resolve_api_key() 解析（显式 key 优先）
- 所有调用失败返回 {"status": "failed", "output": None, "error": ..., "provider": ...}
- httpx 为可选依赖；未安装时明确报错
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from neurova.core.logger import get_logger

if TYPE_CHECKING:
    from .store_connections import StoreCredentials

logger = get_logger(__name__)

# ==================== 服务商 / 平台目录 ====================

IMAGE_PROVIDERS: Dict[str, str] = {
    "comfyui": "ComfyUI 自建",
    "openai": "OpenAI",
    "kling": "可灵 Kling",
    "jimeng": "即梦",
    "wanx": "通义万相",
    "stability": "Stability",
}

VIDEO_PROVIDERS: Dict[str, str] = {
    "kling": "可灵 Kling",
    "jimeng": "即梦",
    "runway": "Runway",
    "pika": "Pika",
    "comfyui": "ComfyUI 自建",
}

COMMERCE_PLATFORMS: Dict[str, str] = {
    "amazon": "亚马逊",
    "taobao": "淘宝",
    "jd": "京东",
    "douyin-ecom": "抖音电商",
    "tiktok": "TikTok",
    "pdd": "拼多多",
    "ali1688": "1688",
    "xiaohongshu": "小红书",
    "xianyu": "咸鱼",
    "shein": "希音",
}

PUBLISH_PLATFORMS: Dict[str, str] = {
    "douyin": "抖音",
    "kuaishou": "快手",
    "bilibili": "B站",
    "tiktok": "TikTok",
    "xiaohongshu": "小红书",
}

# ==================== SecretStore Key 命名映射 ====================

IMAGE_KEY_NAMES: Dict[str, List[str]] = {
    "comfyui": [],
    "openai": ["NEUROVA_IMAGE_OPENAI_KEY", "NEUROVA_OPENAI_API_KEY"],
    "kling": ["NEUROVA_IMAGE_KLING_KEY", "NEUROVA_KLING_API_KEY"],
    "jimeng": ["NEUROVA_IMAGE_JIMENG_KEY", "NEUROVA_JIMENG_API_KEY"],
    "wanx": ["NEUROVA_IMAGE_WANX_KEY", "NEUROVA_WANX_API_KEY", "NEUROVA_DASHSCOPE_API_KEY"],
    "stability": ["NEUROVA_IMAGE_STABILITY_KEY", "NEUROVA_STABILITY_API_KEY"],
}

VIDEO_KEY_NAMES: Dict[str, List[str]] = {
    "kling": ["NEUROVA_VIDEO_KLING_KEY", "NEUROVA_KLING_API_KEY"],
    "jimeng": ["NEUROVA_VIDEO_JIMENG_KEY", "NEUROVA_JIMENG_API_KEY"],
    "runway": ["NEUROVA_VIDEO_RUNWAY_KEY", "NEUROVA_RUNWAY_API_KEY"],
    "pika": ["NEUROVA_VIDEO_PIKA_KEY", "NEUROVA_PIKA_API_KEY"],
    "comfyui": [],
}

COMMERCE_KEY_NAMES: Dict[str, List[str]] = {
    "amazon": [
        "NEUROVA_AMAZON_SP_REFRESH_TOKEN",
        "NEUROVA_AMAZON_SP_CLIENT_ID",
        "NEUROVA_AMAZON_SP_CLIENT_SECRET",
    ],
    "taobao": ["NEUROVA_TAOBAO_API_KEY", "NEUROVA_TAOBAO_APP_KEY"],
    "jd": ["NEUROVA_JD_API_KEY"],
    "douyin-ecom": ["NEUROVA_DOUYIN_ECOM_API_KEY"],
    "tiktok": ["NEUROVA_TIKTOK_API_KEY"],
    "pdd": ["NEUROVA_PDD_API_KEY"],
    "ali1688": ["NEUROVA_1688_API_KEY"],
    "xiaohongshu": ["NEUROVA_XIAOHONGSHU_API_KEY"],
    "xianyu": ["NEUROVA_XIANYU_API_KEY"],
    "shein": ["NEUROVA_SHEIN_API_KEY"],
}

PUBLISH_KEY_NAMES: Dict[str, List[str]] = {
    "douyin": ["NEUROVA_DOUYIN_ACCESS_TOKEN"],
    "kuaishou": ["NEUROVA_KUAISHOU_ACCESS_TOKEN"],
    "bilibili": ["NEUROVA_BILIBILI_ACCESS_TOKEN"],
    "tiktok": ["NEUROVA_TIKTOK_ACCESS_TOKEN"],
    "xiaohongshu": ["NEUROVA_XIAOHONGSHU_ACCESS_TOKEN"],
}

# ==================== 亚马逊开放平台（SP-API）常量 ====================
# 依据官方开发文档 developer-docs.amazon.com/sp-api：
# - 认证：LWA 令牌交换（grant_type=refresh_token），调用头为 x-amz-access-token
# - 区域端点：NA / EU / FE 三端点（SP-API Endpoints 文档）
# - MarketplaceId：Store Identifiers 文档
# - 价格：Product Pricing API v0 getPricing / getCompetitivePricing
# - 库存：FBA Inventory API v1 getInventorySummaries
# - 评论洞察：Customer Feedback API v2024-06-01 getItemReviewTopics
#   （SP-API 不提供原始评论拉取与回复提交）
# - 报表：Reports API v2021-06-30 createReport → getReport → getReportDocument

AMAZON_LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"

AMAZON_SP_REGIONS: Dict[str, str] = {
    "na": "https://sellingpartnerapi-na.amazon.com",
    "eu": "https://sellingpartnerapi-eu.amazon.com",
    "fe": "https://sellingpartnerapi-fe.amazon.com",
}

AMAZON_SP_MARKETPLACES: Dict[str, str] = {
    "US": "ATVPDKIKX0DER",
    "CA": "A2EUQ1WTGCTBG2",
    "MX": "A1AM78C64UM0Y8",
    "BR": "A2Q3Y263D00KWC",
    "IE": "A28R8C7NBKEWEA",
    "ES": "A1RKKUPIHCS9HS",
    "UK": "A1F83G8C2ARO7P",
    "FR": "A13V1IB3VIYZZH",
    "BE": "AMEN7PMS3EDWL",
    "NL": "A1805IZSGTT6HS",
    "DE": "A1PA6795UKMFR9",
    "IT": "APJ6JRA9NG5V4",
    "SE": "A2NODRKZP88ZB9",
    "PL": "A1C3SOZRARQ6R3",
    "TR": "A33AVAJ2PDY3EV",
    "SA": "A17E79C6D8DWNP",
    "AE": "A2VIGQ35RCS4UG",
    "IN": "A21TJRUUN4KGV",
    "SG": "A19VAU5U5O7RUS",
    "AU": "A39IBJ37TRP1C6",
    "JP": "A1VC38T7YXB528",
}

AMAZON_SP_REPORT_TYPES: List[Dict[str, str]] = [
    {"value": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL", "label": "订单报表（按下单日期）"},
    {"value": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE_GENERAL", "label": "订单报表（按更新日期）"},
    {"value": "GET_AMAZON_FULFILLED_SHIPMENTS_DATA_GENERAL", "label": "FBA 发货报表"},
    {"value": "GET_FBA_INVENTORY_RECEIPT_SUMMARY", "label": "FBA 库存收货汇总"},
    {"value": "GET_MERCHANT_LISTINGS_ALL_DATA", "label": "在售 Listing 报表"},
    {"value": "GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT", "label": "品牌分析-搜索词报表"},
]

AMAZON_SP_KEY_NAMES: Dict[str, List[str]] = {
    "refresh_token": ["NEUROVA_AMAZON_SP_REFRESH_TOKEN"],
    "client_id": ["NEUROVA_AMAZON_SP_CLIENT_ID"],
    "client_secret": ["NEUROVA_AMAZON_SP_CLIENT_SECRET"],
}

# Amazon Ads API — 独立于 SP-API 的广告开放平台（advertising.amazon.com）
# 认证：LWA client_credentials，scope=advertising::campaign_management
# 请求头：Authorization Bearer + Amazon-Advertising-API-ClientId + Amazon-Advertising-API-Scope(profileId)
AMAZON_ADS_REGIONS: Dict[str, str] = {
    "na": "https://advertising-api.amazon.com",
    "eu": "https://advertising-api-eu.amazon.com",
    "fe": "https://advertising-api-fe.amazon.com",
}

AMAZON_ADS_KEY_NAMES: Dict[str, List[str]] = {
    "client_id": ["NEUROVA_AMAZON_ADS_CLIENT_ID"],
    "client_secret": ["NEUROVA_AMAZON_ADS_CLIENT_SECRET"],
}

AMAZON_ADS_METRIC_COLUMNS: Dict[str, str] = {
    "impressions": "impressions",
    "clicks": "clicks",
    "spend": "spend",
    "conversions": "purchases7d",
    "sales": "sales7d",
    "ctr": "clickThroughRate",
    "cpc": "costPerClick",
    "acos": "costOfAdvertising7d",
}

# ==================== 淘宝/京东/拼多多/抖店/TikTok Shop 开放网关常量 ====================
# 依据各平台开放平台开发文档的网关协议（文档站为 JS 渲染，以下为长期稳定的公开规范）：
# - 淘宝 TOP（open.taobao.com）：POST eco.taobao.com/router/rest 表单网关
#   公共参数 method/app_key/session/timestamp(yyyy-MM-dd HH:mm:ss)/format/v/sign_method/sign
#   签名 MD5(secret + 按 key 升序 key+value 拼接 + secret) 大写
#   令牌刷新 POST oauth.taobao.com/token（grant_type=refresh_token）
# - 京东（open.jd.com）：POST api.jd.com/routerjson 表单网关
#   业务参数置于 360buy_param_json，响应包装键 {method}_responce（历史拼写）
# - 拼多多（open.pinduoduo.com）：POST gw-api.pinduoduo.com/api/router 表单网关
#   type 为 API 名，业务参数平铺，timestamp 为 unix 秒，金额单位分
# - 抖店（op.jinritemai.com）：POST openapi-fxg.jinritemai.com 表单网关
#   业务参数置于 param_json（紧凑 JSON），签名仅 app_key/method/param_json/timestamp/v 五键
#   响应 {err_no, message, data}，金额单位分
# - TikTok Shop（partner.tiktokshop.com）：REST open-api.tiktokglobalshop.com
#   版本在路径（/product/202309/...），SHA256(secret + 升序 key+value 拼接 + secret) 小写
#   POST 请求体参与签名，响应 {code, message, data}，金额为最小货币单位（分）
# 京东/拼多多/抖店/TikTok Shop 开放平台均不提供商品评论拉取 API（仅淘宝 TOP traderates.get）；
# 五平台开放 API 均仅提供自营数据，不提供竞品数据。

TAOBAO_GATEWAY_URL = "https://eco.taobao.com/router/rest"
TAOBAO_OAUTH_TOKEN_URL = "https://oauth.taobao.com/token"
TAOBAO_KEY_NAMES: Dict[str, List[str]] = {
    "app_key": ["NEUROVA_TAOBAO_APP_KEY"],
    "app_secret": ["NEUROVA_TAOBAO_APP_SECRET"],
    "access_token": ["NEUROVA_TAOBAO_ACCESS_TOKEN"],
    "refresh_token": ["NEUROVA_TAOBAO_REFRESH_TOKEN"],
}

JD_GATEWAY_URL = "https://api.jd.com/routerjson"
JD_OAUTH_TOKEN_URL = "https://open-oauth.jd.com/oauth2/token"
JD_KEY_NAMES: Dict[str, List[str]] = {
    "app_key": ["NEUROVA_JD_APP_KEY"],
    "app_secret": ["NEUROVA_JD_APP_SECRET"],
    "access_token": ["NEUROVA_JD_ACCESS_TOKEN"],
    "refresh_token": ["NEUROVA_JD_REFRESH_TOKEN"],
}

PDD_GATEWAY_URL = "https://gw-api.pinduoduo.com/api/router"
PDD_OAUTH_TOKEN_URL = "https://open-api.pinduoduo.com/oauth/token"
PDD_KEY_NAMES: Dict[str, List[str]] = {
    "client_id": ["NEUROVA_PDD_CLIENT_ID"],
    "client_secret": ["NEUROVA_PDD_CLIENT_SECRET"],
    "access_token": ["NEUROVA_PDD_ACCESS_TOKEN"],
    "refresh_token": ["NEUROVA_PDD_REFRESH_TOKEN"],
}

DOUYIN_ECOM_GATEWAY_URL = "https://openapi-fxg.jinritemai.com"
DOUYIN_ECOM_OAUTH_REFRESH_URL = "https://openapi-fxg.jinritemai.com/oauth2/refresh_token"
DOUYIN_ECOM_KEY_NAMES: Dict[str, List[str]] = {
    "app_key": ["NEUROVA_DOUYIN_ECOM_APP_KEY"],
    "app_secret": ["NEUROVA_DOUYIN_ECOM_APP_SECRET"],
    "access_token": ["NEUROVA_DOUYIN_ECOM_ACCESS_TOKEN"],
    "refresh_token": ["NEUROVA_DOUYIN_ECOM_REFRESH_TOKEN"],
}

TIKTOK_SHOP_GATEWAY_URL = "https://open-api.tiktokglobalshop.com"
TIKTOK_SHOP_TOKEN_REFRESH_PATH = "/api/v2/token/refresh"
TIKTOK_SHOP_KEY_NAMES: Dict[str, List[str]] = {
    "app_key": ["NEUROVA_TIKTOK_SHOP_APP_KEY"],
    "app_secret": ["NEUROVA_TIKTOK_SHOP_APP_SECRET"],
    "access_token": ["NEUROVA_TIKTOK_SHOP_ACCESS_TOKEN"],
    "refresh_token": ["NEUROVA_TIKTOK_SHOP_REFRESH_TOKEN"],
}

# 五平台独立广告系统（与电商开放网关不互通，需各自单独接入）
CN_AD_PLATFORM_HINTS: Dict[str, str] = {
    "taobao": "阿里妈妈（直通车/万相台）",
    "jd": "京准通",
    "pdd": "多多推广（多多搜索/场景展示）",
    "douyin-ecom": "巨量千川",
    "tiktok": "TikTok Ads（business-api.tiktok.com）",
}

# 默认服务地址（可用 base_url / 环境变量覆盖）
_DEFAULT_BASES: Dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "kling": "https://api.klingai.com/v1",
    "jimeng": "https://ark.cn-beijing.volces.com/api/v3",
    "wanx": "https://dashscope.aliyuncs.com/api/v1",
    "stability": "https://api.stability.ai/v2beta",
    "runway": "https://api.dev.runwayml.com/v1",
    "pika": "https://api.pika.art/v1",
    "amazon": "https://sellingpartnerapi-na.amazon.com",
    "taobao": "https://eco.taobao.com/router/rest",
    "jd": "https://api.jd.com/routerjson",
    "douyin-ecom": "https://openapi-fxg.jinritemai.com",
    "tiktok": "https://open-api.tiktokglobalshop.com",
    "pdd": "https://gw-api.pinduoduo.com/api/router",
    "ali1688": "https://gw.open.1688.com/openapi",
    "xiaohongshu": "https://ark.xiaohongshu.com",
    "xianyu": "https://openapi.taobao.com/router/rest",
    "shein": "https://openapi.sheincorp.cn",
    "douyin": "https://open.douyin.com",
    "kuaishou": "https://open.kuaishou.com",
    "bilibili": "https://api.bilibili.com",
    "tiktok-pub": "https://open.tiktokapis.com",
}

# ==================== HTTP 辅助（httpx 可选依赖） ====================

try:
    import httpx  # type: ignore

    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore
    _HTTPX_AVAILABLE = False


class ExternalAPIError(Exception):
    """外部 API 调用失败（网络 / 平台错误）"""


def _http_client(timeout: float):
    return httpx.AsyncClient(timeout=timeout)


async def _http_post(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json: Optional[Dict[str, Any]] = None,
    data: Any = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    if not _HTTPX_AVAILABLE:
        raise ExternalAPIError("httpx 未安装，无法调用外部 API")
    try:
        async with _http_client(timeout) as client:
            resp = await client.post(url, headers=headers, json=json, data=data, params=params)
            resp.raise_for_status()
            return resp.json()
    except ExternalAPIError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ExternalAPIError(f"HTTP POST 失败: {exc}") from exc


async def _http_get(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    if not _HTTPX_AVAILABLE:
        raise ExternalAPIError("httpx 未安装，无法调用外部 API")
    try:
        async with _http_client(timeout) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()
    except ExternalAPIError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ExternalAPIError(f"HTTP GET 失败: {exc}") from exc


async def _http_get_text(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 60.0,
) -> str:
    """下载文本报表（httpx 自动解压 gzip），用于 SP-API/Ads 报表文档"""
    if not _HTTPX_AVAILABLE:
        raise ExternalAPIError("httpx 未安装，无法调用外部 API")
    try:
        async with _http_client(timeout) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text
    except ExternalAPIError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ExternalAPIError(f"HTTP GET 文本失败: {exc}") from exc


def _period_to_iso_range(period: str) -> tuple:
    """将统计周期转换为 SP-API 所需的 ISO 8601 时间范围

    支持：YYYY-MM / YYYY-MM-DD / YYYY-MM-DD~YYYY-MM-DD
    返回 (dataStartTime, dataEndTime)，无法解析时返回 ("", "")
    """
    import calendar
    import re

    p = str(period or "").strip()
    if "~" in p:
        start_s, end_s = (x.strip() for x in p.split("~", 1))
        start = f"{start_s}T00:00:00Z" if re.match(r"^\d{4}-\d{2}-\d{2}$", start_s) else start_s
        end = f"{end_s}T23:59:59Z" if re.match(r"^\d{4}-\d{2}-\d{2}$", end_s) else end_s
        return start, end
    match = re.match(r"^(\d{4})-(\d{2})$", p)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        last_day = calendar.monthrange(year, month)[1]
        return f"{p}-01T00:00:00Z", f"{p}-{last_day:02d}T23:59:59Z"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", p):
        return f"{p}T00:00:00Z", f"{p}T23:59:59Z"
    return "", ""


def _period_to_date_range(period: str) -> tuple:
    """统计周期 → (start_date, end_date) YYYY-MM-DD（国内平台订单 API 用）

    支持：YYYY-MM / YYYY-MM-DD / YYYY-MM-DD~YYYY-MM-DD；无法解析时默认近 30 天
    """
    import calendar
    import re
    from datetime import date, timedelta

    p = str(period or "").strip()
    if "~" in p:
        start_s, end_s = (x.strip() for x in p.split("~", 1))
        if re.match(r"^\d{4}-\d{2}-\d{2}$", start_s) and re.match(r"^\d{4}-\d{2}-\d{2}$", end_s):
            return start_s, end_s
    match = re.match(r"^(\d{4})-(\d{2})$", p)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        last_day = calendar.monthrange(year, month)[1]
        return f"{p}-01", f"{p}-{last_day:02d}"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", p):
        return p, p
    today = date.today()
    return (today - timedelta(days=29)).isoformat(), today.isoformat()


def _date_to_unix(date_str: str, end_of_day: bool = False) -> int:
    """YYYY-MM-DD → 本地 unix 时间戳（end_of_day 取 23:59:59）"""
    from datetime import datetime

    dt = datetime.strptime(str(date_str), "%Y-%m-%d")
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return int(time.mktime(dt.timetuple()))


def _stringify_param(value: Any) -> str:
    """网关表单参数序列化：dict/list 转紧凑 JSON，其余转字符串"""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _fen_to_yuan(value: Any) -> Optional[float]:
    """金额分 → 元（京东/拼多多/抖店/TikTok Shop 金额多为最小货币单位）"""
    try:
        return round(float(value) / 100.0, 2)
    except (TypeError, ValueError):
        return None


# ==================== 开放网关签名 ====================


def _router_sign_md5(secret: str, params: Dict[str, Any]) -> str:
    """淘宝 TOP / 京东 / 拼多多通用签名

    MD5(secret + 按 key 升序 key+value 拼接 + secret)，十六进制大写
    """
    base = str(secret) + "".join(f"{k}{params[k]}" for k in sorted(params)) + str(secret)
    return hashlib.md5(base.encode("utf-8")).hexdigest().upper()


def _douyin_sign_md5(secret: str, params: Dict[str, Any]) -> str:
    """抖店网关签名：仅 app_key/method/param_json/timestamp/v 五键按字母序参与"""
    keys = ("app_key", "method", "param_json", "timestamp", "v")
    base = str(secret) + "".join(f"{k}{params[k]}" for k in keys if k in params) + str(secret)
    return hashlib.md5(base.encode("utf-8")).hexdigest().upper()


def _tiktok_sign_sha256(secret: str, params: Dict[str, Any]) -> str:
    """TikTok Shop 签名：SHA256(secret + 按 key 升序 key+value 拼接 + secret)，十六进制小写"""
    base = str(secret) + "".join(f"{k}{params[k]}" for k in sorted(params)) + str(secret)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


# ==================== SecretStore 集成 ====================

def get_secret_store():
    """懒导入避免循环依赖"""
    from neurova.llm.providers.secret_store import get_secret_store as _gss

    return _gss()


def get_api_key(key_name: str) -> Optional[str]:
    try:
        value = get_secret_store().get(key_name)
        return str(value) if value else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 SecretStore key %s 失败: %s", key_name, exc)
        return None


def resolve_api_key(key_names: List[str], explicit: str = "") -> Optional[str]:
    """显式 key 优先，否则逐个回落 SecretStore"""
    if explicit:
        stripped = str(explicit).strip()
        if stripped:
            return stripped
    for name in key_names:
        value = get_api_key(name)
        if value:
            return value
    return None


def _comfyui_host() -> Optional[str]:
    try:
        from neurova.core.config import get

        host = get("NEUROVA_COMFYUI_HOST", None)
        return str(host) if host else None
    except Exception:  # noqa: BLE001
        return None


def _base_url(service: str, base_url: str = "") -> str:
    if base_url:
        return base_url.rstrip("/")
    try:
        from neurova.core.config import get

        env_val = get(f"NEUROVA_{service.upper().replace('-', '_')}_API_BASE", None)
        if env_val:
            return str(env_val).rstrip("/")
    except Exception:  # noqa: BLE001
        pass
    return _DEFAULT_BASES.get(service, "").rstrip("/")


# ==================== 结果辅助 ====================

def _ok(output: Dict[str, Any], provider: str = "") -> Dict[str, Any]:
    return {"status": "success", "output": output, "error": None, "provider": provider}


def _fail(error: str, provider: str = "") -> Dict[str, Any]:
    return {"status": "failed", "output": None, "error": error, "provider": provider}


def _extract(data: Any, keys: List[str], default: Any = None) -> Any:
    """从嵌套响应中提取第一个命中的键值（顶层优先）"""
    if isinstance(data, dict):
        for key in keys:
            if key in data:
                return data[key]
        inner = data.get("data")
        if isinstance(inner, dict):
            for key in keys:
                if key in inner:
                    return inner[key]
    return default


def _deep_extract(data: Any, keys: List[str], default: Any = None) -> Any:
    """从嵌套响应中提取第一个命中的键值（跳过 data 包装层）"""
    if isinstance(data, dict):
        for key in keys:
            if key in data:
                return data[key]
        inner = data.get("data")
        if isinstance(inner, dict):
            for key in keys:
                if key in inner:
                    return inner[key]
    return default


def _first_float(obj: Any, keys: tuple, default: Optional[float] = None) -> Optional[float]:
    """防御式数值提取：字段名待平台文档核对时依次尝试多个候选键"""
    if not isinstance(obj, dict):
        return default
    for key in keys:
        value = obj.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _first_int(obj: Any, keys: tuple, default: int = 0) -> int:
    if not isinstance(obj, dict):
        return default
    for key in keys:
        value = obj.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default


# ==================== ImageGenClient ====================

class ImageGenClient:
    """文生图客户端：多服务商，通过 httpx 调用"""

    def is_available(self, provider: str, api_key: str = "") -> bool:
        provider = str(provider or "").lower()
        if provider == "comfyui":
            return bool(_comfyui_host())
        names = IMAGE_KEY_NAMES.get(provider, [])
        return bool(resolve_api_key(names, api_key))

    async def generate(
        self,
        provider: str,
        prompt: str,
        api_key: str = "",
        size: str = "1024x1024",
        base_url: str = "",
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        provider = str(provider or "").lower()
        if provider not in IMAGE_PROVIDERS:
            return _fail(f"不支持的图像服务商: {provider}", provider)
        if not self.is_available(provider, api_key):
            return _fail(f"图像服务商 '{IMAGE_PROVIDERS[provider]}' 未配置 API Key", provider)
        if provider == "comfyui":
            return await self._generate_comfyui(prompt, size)
        key = resolve_api_key(IMAGE_KEY_NAMES[provider], api_key)
        url = f"{_base_url(provider, base_url)}/images/generations"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body = {"prompt": prompt, "size": size, "n": 1}
        try:
            data = await _http_post(url, headers=headers, json=body, timeout=timeout)
            url_out = _extract(data, ["url", "image_url"])
            if not url_out:
                items = _extract(data, ["data", "images"])
                if isinstance(items, list) and items:
                    url_out = _extract(items[0], ["url", "image_url"])
            return _ok(
                {"prompt": prompt, "size": size, "provider": provider, "url": url_out, "raw": data},
                provider,
            )
        except ExternalAPIError as exc:
            logger.warning("图像生成失败 (%s): %s", provider, exc)
            return _fail(str(exc), provider)

    async def _generate_comfyui(self, prompt: str, size: str) -> Dict[str, Any]:
        width, height = _parse_size(size)
        client = get_comfyui_client()
        result = await client.execute_node(
            "EmptyLatentImage",
            {"width": width, "height": height, "batch_size": 1},
            {"prompt": prompt, "save_images": True},
        )
        return {
            "status": result.get("status", "failed"),
            "output": result.get("output"),
            "error": result.get("error"),
            "provider": "comfyui",
        }


def get_comfyui_client():
    """懒加载 ComfyUI 客户端（延迟导入避免循环依赖）"""
    from .comfyui_client import get_comfyui_client as _impl

    return _impl()


def _parse_size(size: str):
    try:
        width, height = (int(part) for part in str(size).lower().split("x")[:2])
        return width, height
    except Exception:  # noqa: BLE001
        return 1024, 1024


_image_gen_instance: Optional[ImageGenClient] = None


def get_image_gen_client() -> ImageGenClient:
    global _image_gen_instance
    if _image_gen_instance is None:
        _image_gen_instance = ImageGenClient()
    return _image_gen_instance


def reset_image_gen_client() -> None:
    global _image_gen_instance
    _image_gen_instance = None


# ==================== VideoGenClient ====================

class VideoGenClient:
    """图生视频/文生视频客户端：提交任务 + 轮询状态"""

    def __init__(self, poll_interval: float = 2.0) -> None:
        self._poll_interval = poll_interval

    def is_available(self, provider: str, api_key: str = "") -> bool:
        provider = str(provider or "").lower()
        if provider == "comfyui":
            return bool(_comfyui_host())
        names = VIDEO_KEY_NAMES.get(provider, [])
        return bool(resolve_api_key(names, api_key))

    async def generate(
        self,
        provider: str,
        prompt: str,
        api_key: str = "",
        first_frame_url: str = "",
        duration: int = 5,
        base_url: str = "",
        timeout: float = 180.0,
        max_polls: int = 10,
    ) -> Dict[str, Any]:
        provider = str(provider or "").lower()
        if provider not in VIDEO_PROVIDERS:
            return _fail(f"不支持的视频服务商: {provider}", provider)
        if not self.is_available(provider, api_key):
            return _fail(f"视频服务商 '{VIDEO_PROVIDERS[provider]}' 未配置 API Key", provider)
        if provider == "comfyui":
            return self._fail_not_impl("ComfyUI 图生视频暂未支持", provider)
        key = resolve_api_key(VIDEO_KEY_NAMES[provider], api_key)
        base = _base_url(provider, base_url)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body: Dict[str, Any] = {"prompt": prompt, "duration": duration}
        if first_frame_url:
            body["first_frame_url"] = first_frame_url
            body["image_url"] = first_frame_url
        try:
            submit = await _http_post(f"{base}/videos/generations", headers=headers, json=body, timeout=timeout)
            task_id = _extract(submit, ["task_id", "id"])
            if not task_id:
                return _ok(
                    {"provider": provider, "task_id": None, "video_url": None, "raw": submit},
                    provider,
                )
            for _ in range(max_polls):
                status = await _http_get(f"{base}/videos/tasks/{task_id}", headers=headers, timeout=timeout)
                task_status = str(_extract(status, ["status", "task_status"]) or "pending").lower()
                if task_status in ("succeed", "success", "completed", "done"):
                    video_url = _extract(status, ["video_url", "url", "result"])
                    if isinstance(video_url, dict):
                        video_url = _extract(video_url, ["video_url", "url"])
                    return _ok(
                        {"provider": provider, "task_id": task_id, "video_url": video_url, "raw": status},
                        provider,
                    )
                if task_status in ("failed", "error", "fail"):
                    return _fail(f"视频任务失败: {_extract(status, ['message', 'error', 'reason'], '未知原因')}", provider)
                await _sleep(self._poll_interval)
            return _fail(f"视频生成轮询超时（任务 {task_id}）", provider)
        except ExternalAPIError as exc:
            logger.warning("视频生成失败 (%s): %s", provider, exc)
            return _fail(str(exc), provider)

    async def _fail_not_impl(self, message: str, provider: str) -> Dict[str, Any]:
        return _fail(message, provider)


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


_video_gen_instance: Optional[VideoGenClient] = None


def get_video_gen_client() -> VideoGenClient:
    global _video_gen_instance
    if _video_gen_instance is None:
        _video_gen_instance = VideoGenClient()
    return _video_gen_instance


def reset_video_gen_client() -> None:
    global _video_gen_instance
    _video_gen_instance = None


# ==================== AmazonSPAPIClient ====================


class AmazonSPAPIClient:
    """Amazon Selling Partner API 客户端（深模块）

    按官方文档实现真实调用流程：
    1. LWA 令牌交换：POST https://api.amazon.com/auth/o2/token
       form: grant_type=refresh_token & refresh_token & client_id & client_secret
    2. 区域端点 + 请求头：x-amz-access-token / x-amz-date / user-agent
    3. 各业务 API：
       - 价格   GET /products/pricing/v0/pricing（Product Pricing API v0）
       - 竞价   GET /products/pricing/v0/competitivePrice
       - 库存   GET /fba/inventory/v1/summaries（FBA Inventory API v1）
       - 评论   GET /customerFeedback/2024-06-01/items/{asin}/reviews/topics
       - 报表   POST /reports/2021-06-30/reports → getReport → getReportDocument
    """

    def __init__(self) -> None:
        self._token_cache: Dict[str, Any] = {}

    def _resolve_credentials(
        self,
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> tuple:
        store_rt = store_creds.refresh_token if store_creds else ""
        store_cid = store_creds.app_key if store_creds else ""
        store_cs = store_creds.app_secret if store_creds else ""
        rt = refresh_token or store_rt or (resolve_api_key(AMAZON_SP_KEY_NAMES["refresh_token"], "") or "")
        cid = client_id or store_cid or (resolve_api_key(AMAZON_SP_KEY_NAMES["client_id"], "") or "")
        cs = client_secret or store_cs or (resolve_api_key(AMAZON_SP_KEY_NAMES["client_secret"], "") or "")
        return rt, cid, cs

    def is_available(
        self,
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> bool:
        rt, cid, cs = self._resolve_credentials(refresh_token, client_id, client_secret, store_creds)
        return bool(rt and cid and cs)

    async def get_access_token(
        self, refresh_token: str = "", client_id: str = "", client_secret: str = ""
    ) -> str:
        """LWA 令牌交换，返回 access_token（有效期约 3600 秒）"""
        rt, cid, cs = self._resolve_credentials(refresh_token, client_id, client_secret)
        if not (rt and cid and cs):
            raise ExternalAPIError(
                "Amazon SP-API 未配置：需要 NEUROVA_AMAZON_SP_REFRESH_TOKEN / "
                "NEUROVA_AMAZON_SP_CLIENT_ID / NEUROVA_AMAZON_SP_CLIENT_SECRET"
            )
        data = await _http_post(
            AMAZON_LWA_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": rt,
                "client_id": cid,
                "client_secret": cs,
            },
        )
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise ExternalAPIError(f"LWA 令牌交换失败: {data}")
        return str(token)

    async def _access_token(
        self,
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> str:
        import time

        now = time.time()
        rt, cid, cs = self._resolve_credentials(refresh_token, client_id, client_secret, store_creds)
        # 缓存按 (client_id, refresh_token 尾缀) 指纹隔离多店铺，不新增签名改动
        cache_key = f"{cid}|{rt[-6:] if len(rt) >= 6 else rt}"
        cached = self._token_cache.get(cache_key) or {}
        if cached.get("token") and cached.get("expires_at", 0) > now + 60:
            return str(cached["token"])
        token = await self.get_access_token(rt, cid, cs)
        self._token_cache[cache_key] = {"token": token, "expires_at": now + 3540}
        return token

    def _sp_headers(self, access_token: str) -> Dict[str, str]:
        from datetime import datetime, timezone

        return {
            "x-amz-access-token": access_token,
            "x-amz-date": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "user-agent": "Neurova/1.0 (Language=Python)",
            "Content-Type": "application/json",
        }

    def _region_base(self, region: str) -> str:
        return AMAZON_SP_REGIONS.get(str(region or "na").lower(), AMAZON_SP_REGIONS["na"])

    def resolve_marketplace_id(self, marketplace_id: str) -> str:
        """接受国家代码（US/DE/JP...）或原始 MarketplaceId"""
        mid = str(marketplace_id or "").strip()
        if not mid:
            return AMAZON_SP_MARKETPLACES["US"]
        return AMAZON_SP_MARKETPLACES.get(mid.upper(), mid)

    @staticmethod
    def _extract_offer_price(item: Dict[str, Any]) -> Dict[str, Any]:
        product = item.get("product") or {}
        best: Optional[Dict[str, Any]] = None
        for offer in product.get("offers") or []:
            for key in ("buyingPrice", "listingPrice"):
                money = offer.get(key) or {}
                amount = money.get("amount")
                if amount is None:
                    continue
                try:
                    price = float(amount)
                except (TypeError, ValueError):
                    continue
                if best is None or price < best["price"]:
                    best = {"price": price, "currency": str(money.get("currencyCode") or "")}
        return best or {"price": None, "currency": ""}

    async def fetch_prices(
        self,
        asins: List[str],
        marketplace_id: str = "",
        region: str = "na",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> Dict[str, Any]:
        """Product Pricing API v0 getPricing — 按 ASIN 批量查询价格"""
        if not self.is_available(refresh_token, client_id, client_secret):
            return _fail("Amazon SP-API 未配置（需 refresh_token/client_id/client_secret）", "amazon")
        asin_list = [str(a).strip() for a in asins if str(a).strip()]
        try:
            token = await self._access_token(refresh_token, client_id, client_secret)
            mid = self.resolve_marketplace_id(marketplace_id)
            url = f"{self._region_base(region)}/products/pricing/v0/pricing"
            data = await _http_get(
                url,
                headers=self._sp_headers(token),
                params={"MarketplaceId": mid, "ItemType": "Asin", "Asins": ",".join(asin_list)},
            )
            payload = data.get("payload") or []
            prices: Dict[str, Any] = {}
            for item in payload:
                if not isinstance(item, dict):
                    continue
                asin = item.get("asin")
                if not asin:
                    identifiers = (item.get("identifiers") or {})
                    asin = identifiers.get("asin")
                if asin:
                    prices[str(asin)] = self._extract_offer_price(item)
            return _ok({"prices": prices, "marketplace_id": mid, "raw": payload}, "amazon")
        except ExternalAPIError as exc:
            logger.warning("SP-API 价格查询失败: %s", exc)
            return _fail(str(exc), "amazon")

    async def fetch_competitive_prices(
        self,
        asins: List[str],
        marketplace_id: str = "",
        region: str = "na",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> Dict[str, Any]:
        """Product Pricing API v0 getCompetitivePricing — 竞品竞价（Buy Box 等）"""
        if not self.is_available(refresh_token, client_id, client_secret):
            return _fail("Amazon SP-API 未配置（需 refresh_token/client_id/client_secret）", "amazon")
        asin_list = [str(a).strip() for a in asins if str(a).strip()]
        try:
            token = await self._access_token(refresh_token, client_id, client_secret)
            mid = self.resolve_marketplace_id(marketplace_id)
            url = f"{self._region_base(region)}/products/pricing/v0/competitivePrice"
            data = await _http_get(
                url,
                headers=self._sp_headers(token),
                params={"MarketplaceId": mid, "ItemType": "Asin", "Asins": ",".join(asin_list)},
            )
            payload = data.get("payload") or []
            prices: Dict[str, Any] = {}
            for item in payload:
                if not isinstance(item, dict):
                    continue
                asin = item.get("asin")
                if not asin:
                    continue
                product = item.get("product") or {}
                competitive = product.get("competitivePricing") or {}
                best: Optional[Dict[str, Any]] = None
                for cp in competitive.get("competitivePrices") or []:
                    price_obj = (cp or {}).get("price") or {}
                    for key in ("landedPrice", "listingPrice"):
                        money = price_obj.get(key) or {}
                        amount = money.get("amount")
                        if amount is None:
                            continue
                        try:
                            price = float(amount)
                        except (TypeError, ValueError):
                            continue
                        if best is None or price < best["price"]:
                            best = {"price": price, "currency": str(money.get("currencyCode") or "")}
                prices[str(asin)] = best or {"price": None, "currency": ""}
            return _ok({"prices": prices, "marketplace_id": mid, "raw": payload}, "amazon")
        except ExternalAPIError as exc:
            logger.warning("SP-API 竞价查询失败: %s", exc)
            return _fail(str(exc), "amazon")

    async def fetch_inventory(
        self,
        skus: List[str],
        marketplace_id: str = "",
        region: str = "na",
        seller_id: str = "",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> Dict[str, Any]:
        """FBA Inventory API v1 getInventorySummaries — FBA 库存汇总（sellerSkus ≤ 50）"""
        if not self.is_available(refresh_token, client_id, client_secret):
            return _fail("Amazon SP-API 未配置（需 refresh_token/client_id/client_secret）", "amazon")
        sku_list = [str(s).strip() for s in skus if str(s).strip()][:50]
        try:
            token = await self._access_token(refresh_token, client_id, client_secret)
            mid = self.resolve_marketplace_id(marketplace_id)
            params: Dict[str, Any] = {
                "granularityType": "Marketplace",
                "granularityId": mid,
                "marketplaceIds": mid,
                "details": "true",
            }
            if sku_list:
                params["sellerSkus"] = ",".join(sku_list)
            if seller_id:
                params["sellerId"] = str(seller_id).strip()
            url = f"{self._region_base(region)}/fba/inventory/v1/summaries"
            data = await _http_get(url, headers=self._sp_headers(token), params=params)
            payload = data.get("payload") or {}
            inventory: Dict[str, Any] = {}
            for row in payload.get("inventorySummaries") or []:
                if not isinstance(row, dict):
                    continue
                sku = row.get("sellerSku")
                if not sku:
                    continue
                details = row.get("inventoryDetails") or {}
                inventory[str(sku)] = {
                    "asin": row.get("asin", ""),
                    "totalQuantity": row.get("totalQuantity", 0),
                    "fulfillableQuantity": details.get("fulfillableQuantity", 0),
                }
            return _ok({"inventory": inventory, "marketplace_id": mid, "raw": payload}, "amazon")
        except ExternalAPIError as exc:
            logger.warning("SP-API 库存查询失败: %s", exc)
            return _fail(str(exc), "amazon")

    async def fetch_review_topics(
        self,
        asin: str,
        marketplace_id: str = "",
        region: str = "na",
        sort_by: str = "MENTIONS",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> Dict[str, Any]:
        """Customer Feedback API v2024-06-01 getItemReviewTopics

        返回 ASIN 的正面/负面评论主题洞察（含评论片段）。
        注意：SP-API 不提供原始评论拉取与回复提交，仅提供主题洞察。
        """
        if not self.is_available(refresh_token, client_id, client_secret):
            return _fail("Amazon SP-API 未配置（需 refresh_token/client_id/client_secret）", "amazon")
        asin = str(asin or "").strip()
        if not asin:
            return _fail("Customer Feedback API 需要 ASIN", "amazon")
        try:
            token = await self._access_token(refresh_token, client_id, client_secret)
            mid = self.resolve_marketplace_id(marketplace_id)
            url = f"{self._region_base(region)}/customerFeedback/2024-06-01/items/{asin}/reviews/topics"
            data = await _http_get(
                url,
                headers=self._sp_headers(token),
                params={"marketplaceId": mid, "sortBy": sort_by or "MENTIONS"},
            )
            topics = data.get("topics") or {}
            return _ok(
                {
                    "asin": asin,
                    "marketplace_id": mid,
                    "positive_topics": topics.get("positiveTopics") or [],
                    "negative_topics": topics.get("negativeTopics") or [],
                    "raw": data,
                },
                "amazon",
            )
        except ExternalAPIError as exc:
            logger.warning("SP-API 评论洞察查询失败: %s", exc)
            return _fail(str(exc), "amazon")

    async def create_report(
        self,
        report_type: str,
        marketplace_ids: List[str],
        data_start_time: str = "",
        data_end_time: str = "",
        region: str = "na",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> Dict[str, Any]:
        """Reports API v2021-06-30 createReport"""
        if not self.is_available(refresh_token, client_id, client_secret):
            return _fail("Amazon SP-API 未配置（需 refresh_token/client_id/client_secret）", "amazon")
        try:
            token = await self._access_token(refresh_token, client_id, client_secret)
            body: Dict[str, Any] = {
                "reportType": str(report_type),
                "marketplaceIds": [self.resolve_marketplace_id(m) for m in marketplace_ids]
                or [AMAZON_SP_MARKETPLACES["US"]],
            }
            if data_start_time:
                body["dataStartTime"] = data_start_time
            if data_end_time:
                body["dataEndTime"] = data_end_time
            url = f"{self._region_base(region)}/reports/2021-06-30/reports"
            data = await _http_post(url, headers=self._sp_headers(token), json=body)
            report_id = data.get("reportId") if isinstance(data, dict) else None
            if not report_id:
                return _fail(f"createReport 未返回 reportId: {data}", "amazon")
            return _ok({"reportId": str(report_id)}, "amazon")
        except ExternalAPIError as exc:
            logger.warning("SP-API createReport 失败: %s", exc)
            return _fail(str(exc), "amazon")

    async def get_report(
        self,
        report_id: str,
        region: str = "na",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> Dict[str, Any]:
        """Reports API getReport — 查询报表处理状态"""
        try:
            token = await self._access_token(refresh_token, client_id, client_secret)
            url = f"{self._region_base(region)}/reports/2021-06-30/reports/{report_id}"
            data = await _http_get(url, headers=self._sp_headers(token))
            return _ok(data.get("payload") or {}, "amazon")
        except ExternalAPIError as exc:
            return _fail(str(exc), "amazon")

    async def get_report_document(
        self,
        report_document_id: str,
        region: str = "na",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> Dict[str, Any]:
        """Reports API getReportDocument — 获取报表文档下载地址"""
        try:
            token = await self._access_token(refresh_token, client_id, client_secret)
            url = f"{self._region_base(region)}/reports/2021-06-30/documents/{report_document_id}"
            data = await _http_get(url, headers=self._sp_headers(token))
            return _ok(data.get("payload") or {}, "amazon")
        except ExternalAPIError as exc:
            return _fail(str(exc), "amazon")

    async def fetch_sales_report(
        self,
        report_type: str,
        marketplace_ids: List[str],
        data_start_time: str = "",
        data_end_time: str = "",
        region: str = "na",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        max_polls: int = 10,
        poll_interval: float = 5.0,
    ) -> Dict[str, Any]:
        """完整报表流程：createReport → 轮询 getReport → getReportDocument"""
        created = await self.create_report(
            report_type=report_type,
            marketplace_ids=marketplace_ids,
            data_start_time=data_start_time,
            data_end_time=data_end_time,
            region=region,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
        )
        if created.get("status") != "success":
            return created
        report_id = created["output"]["reportId"]
        fatal_status = {"CANCELLED", "FATAL"}
        for _ in range(max_polls):
            got = await self.get_report(
                report_id, region, refresh_token, client_id, client_secret
            )
            if got.get("status") != "success":
                return got
            payload = got.get("output") or {}
            status = str(payload.get("processingStatus") or "").upper()
            if status == "DONE":
                doc_id = payload.get("reportDocumentId") or ""
                doc = await self.get_report_document(
                    doc_id, region, refresh_token, client_id, client_secret
                )
                if doc.get("status") != "success":
                    return doc
                return _ok(
                    {
                        "report_id": report_id,
                        "report_document_id": doc_id,
                        "document_url": (doc.get("output") or {}).get("url"),
                        "processing_status": "DONE",
                        "report_type": report_type,
                    },
                    "amazon",
                )
            if status in fatal_status:
                return _fail(f"SP-API 报表处理失败: {status}", "amazon")
            await _sleep(poll_interval)
        return _fail(f"SP-API 报表轮询超时（reportId={report_id}）", "amazon")


_amazon_sp_instance: Optional[AmazonSPAPIClient] = None


def get_amazon_sp_client() -> AmazonSPAPIClient:
    global _amazon_sp_instance
    if _amazon_sp_instance is None:
        _amazon_sp_instance = AmazonSPAPIClient()
    return _amazon_sp_instance


def reset_amazon_sp_client() -> None:
    global _amazon_sp_instance
    _amazon_sp_instance = None


# ==================== AmazonAdsClient ====================


class AmazonAdsClient:
    """Amazon Ads API 客户端 — 独立于 SP-API 的广告开放平台

    - 认证：LWA client_credentials，scope=advertising::campaign_management
    - 请求头：Authorization Bearer + Amazon-Advertising-API-ClientId
      + Amazon-Advertising-API-Scope（profileId）
    - 报表：POST /reporting/reports → 轮询 GET /reporting/reports/{id} → 下载 NDJSON
    """

    def __init__(self) -> None:
        self._token_cache: Dict[str, Any] = {}

    def _resolve_credentials(self, client_id: str = "", client_secret: str = "") -> tuple:
        cid = resolve_api_key(AMAZON_ADS_KEY_NAMES["client_id"], client_id)
        cs = resolve_api_key(AMAZON_ADS_KEY_NAMES["client_secret"], client_secret)
        return cid, cs

    def is_available(self, client_id: str = "", client_secret: str = "") -> bool:
        cid, cs = self._resolve_credentials(client_id, client_secret)
        return bool(cid and cs)

    async def get_access_token(self, client_id: str = "", client_secret: str = "") -> str:
        cid, cs = self._resolve_credentials(client_id, client_secret)
        if not (cid and cs):
            raise ExternalAPIError(
                "Amazon Ads API 未配置：需要 NEUROVA_AMAZON_ADS_CLIENT_ID / "
                "NEUROVA_AMAZON_ADS_CLIENT_SECRET"
            )
        data = await _http_post(
            AMAZON_LWA_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data={
                "grant_type": "client_credentials",
                "scope": "advertising::campaign_management",
                "client_id": cid,
                "client_secret": cs,
            },
        )
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise ExternalAPIError(f"Amazon Ads LWA 令牌交换失败: {data}")
        return str(token)

    def _ads_headers(self, token: str, client_id: str, profile_id: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Amazon-Advertising-API-ClientId": str(client_id),
            "Amazon-Advertising-API-Scope": str(profile_id),
            "Content-Type": "application/json",
            "user-agent": "Neurova/1.0 (Language=Python)",
        }

    def _region_base(self, region: str) -> str:
        return AMAZON_ADS_REGIONS.get(str(region or "na").lower(), AMAZON_ADS_REGIONS["na"])

    async def fetch_campaign_metrics(
        self,
        campaign_ids: List[str],
        metrics: List[str],
        start_date: str,
        end_date: str,
        profile_id: str,
        region: str = "na",
        client_id: str = "",
        client_secret: str = "",
        max_polls: int = 10,
        poll_interval: float = 3.0,
    ) -> Dict[str, Any]:
        """Sponsored Products 活动指标报表（v3 reporting，异步生成）"""
        cid, cs = self._resolve_credentials(client_id, client_secret)
        if not (cid and cs):
            return _fail("Amazon Ads API 未配置（需 client_id/client_secret）", "amazon-ads")
        if not str(profile_id or "").strip():
            return _fail("Amazon Ads API 需要 profileId（GET /v2/profiles 获取）", "amazon-ads")
        try:
            token = await self.get_access_token(client_id, client_secret)
            headers = self._ads_headers(token, cid, profile_id)
            base = self._region_base(region)
            columns = ["campaignId", "campaignName"]
            for m in metrics or []:
                col = AMAZON_ADS_METRIC_COLUMNS.get(str(m).lower(), str(m))
                if col not in columns:
                    columns.append(col)
            configuration: Dict[str, Any] = {
                "adProduct": "SPONSORED_PRODUCTS",
                "groupBy": ["campaign"],
                "columns": columns,
                "reportTypeId": "spCampaigns",
                "timeUnit": "DAILY",
                "format": "JSON",
            }
            id_list = [str(c).strip() for c in campaign_ids if str(c).strip()]
            if id_list:
                configuration["filters"] = [{"field": "campaignId", "values": id_list}]
            body = {
                "name": "Neurova campaign metrics report",
                "startDate": start_date,
                "endDate": end_date,
                "configuration": configuration,
            }
            submit = await _http_post(f"{base}/reporting/reports", headers=headers, json=body)
            report_id = submit.get("reportId") if isinstance(submit, dict) else None
            if not report_id:
                return _fail(f"Amazon Ads 报表创建失败: {submit}", "amazon-ads")
            for _ in range(max_polls):
                status_resp = await _http_get(
                    f"{base}/reporting/reports/{report_id}", headers=headers
                )
                st = str(status_resp.get("status") or "").upper()
                if st == "COMPLETED":
                    doc_url = status_resp.get("url") or ""
                    rows = await self._download_rows(doc_url)
                    return _ok(
                        {
                            "items": self._aggregate_rows(rows),
                            "report_id": str(report_id),
                            "raw_rows": rows[:50],
                        },
                        "amazon-ads",
                    )
                if st in ("FAILED", "CANCELLED"):
                    return _fail(f"Amazon Ads 报表处理失败: {st}", "amazon-ads")
                await _sleep(poll_interval)
            return _fail(f"Amazon Ads 报表轮询超时（reportId={report_id}）", "amazon-ads")
        except ExternalAPIError as exc:
            logger.warning("Amazon Ads 指标查询失败: %s", exc)
            return _fail(str(exc), "amazon-ads")

    async def _download_rows(self, url: str) -> List[Dict[str, Any]]:
        import json as _json

        if not url:
            return []
        text = await _http_get_text(url)
        rows: List[Dict[str, Any]] = []
        for line in str(text).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = _json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(obj, dict):
                rows.append(obj)
        return rows

    @staticmethod
    def _aggregate_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        aggregated: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            cid = str(row.get("campaignId") or "unknown")
            entry = aggregated.setdefault(
                cid, {"campaign_id": cid, "campaign_name": row.get("campaignName", "")}
            )
            for key, value in row.items():
                if key in ("campaignId", "campaignName"):
                    continue
                if isinstance(value, (int, float)):
                    entry[key] = round(float(entry.get(key, 0)) + float(value), 4)
        return list(aggregated.values())


_amazon_ads_instance: Optional[AmazonAdsClient] = None


def get_amazon_ads_client() -> AmazonAdsClient:
    global _amazon_ads_instance
    if _amazon_ads_instance is None:
        _amazon_ads_instance = AmazonAdsClient()
    return _amazon_ads_instance


def reset_amazon_ads_client() -> None:
    global _amazon_ads_instance
    _amazon_ads_instance = None


# ==================== 淘宝 / 京东 / 拼多多 / 抖店 / TikTok Shop 客户端 ====================


class _OpenGatewayClientBase:
    """国内电商开放网关客户端公共逻辑：凭据解析 + access_token 缓存/刷新"""

    KEY_NAMES: Dict[str, List[str]] = {}
    OAUTH_REFRESH_URL: str = ""
    OAUTH_ID_FIELD: str = "client_id"
    PROVIDER: str = ""

    def __init__(self) -> None:
        self._token_cache: Dict[str, Any] = {}

    def _resolve_credentials(
        self,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> tuple:
        """凭据解析优先级：显式传参 > store_creds（店铺注册表）> 环境变量"""
        store_ak = store_creds.app_key if store_creds else ""
        store_sk = store_creds.app_secret if store_creds else ""
        store_at = store_creds.access_token if store_creds else ""
        store_rt = store_creds.refresh_token if store_creds else ""
        ak = (app_key or client_id) or store_ak or (resolve_api_key(self.KEY_NAMES.get("app_key", []), "") or "")
        sk = (app_secret or client_secret) or store_sk or (resolve_api_key(self.KEY_NAMES.get("app_secret", []), "") or "")
        at = access_token or store_at or (resolve_api_key(self.KEY_NAMES.get("access_token", []), "") or "")
        rt = refresh_token or store_rt or (resolve_api_key(self.KEY_NAMES.get("refresh_token", []), "") or "")
        return ak, sk, at, rt

    def is_available(
        self,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> bool:
        ak, sk, at, rt = self._resolve_credentials(
            app_key, app_secret, access_token, refresh_token, client_id, client_secret, store_creds
        )
        return bool(ak and sk and (at or rt))

    async def get_access_token(
        self,
        app_key: str = "",
        app_secret: str = "",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> str:
        """OAuth refresh_token 刷新 access_token（各平台表单字段略有差异）"""
        ak, sk, _, rt = self._resolve_credentials(
            app_key, app_secret, "", refresh_token, client_id, client_secret
        )
        if not (ak and sk and rt):
            raise ExternalAPIError(
                f"{self.PROVIDER} 未配置：需要 app_key/app_secret/refresh_token"
            )
        data = await _http_post(
            self.OAUTH_REFRESH_URL,
            data={
                "grant_type": "refresh_token",
                self.OAUTH_ID_FIELD: ak,
                "client_secret": sk,
                "refresh_token": rt,
            },
        )
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token and isinstance(data, dict) and isinstance(data.get("data"), dict):
            token = data["data"].get("access_token")
        if not token:
            raise ExternalAPIError(f"{self.PROVIDER} 令牌刷新失败: {data}")
        return str(token)

    async def _access_token(
        self,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> str:
        now = time.time()
        cache_key = store_id or "default"
        cached = self._token_cache.get(cache_key) or {}
        if cached.get("token") and cached.get("expires_at", 0) > now + 60:
            return str(cached["token"])
        _, _, at, rt = self._resolve_credentials(
            app_key, app_secret, access_token, refresh_token, client_id, client_secret, store_creds
        )
        if at:
            return at
        if rt:
            ak, sk, _, _ = self._resolve_credentials(
                app_key, app_secret, "", "", client_id, client_secret, store_creds
            )
            token = await self.get_access_token(ak, sk, rt)
            self._token_cache[cache_key] = {"token": token, "expires_at": now + 86000}
            return token
        raise ExternalAPIError(f"{self.PROVIDER} 未配置 access_token / refresh_token")


class TaobaoTopClient(_OpenGatewayClientBase):
    """淘宝开放平台（TOP）客户端

    按官方文档实现真实调用流程：
    1. 网关：POST https://eco.taobao.com/router/rest（表单）
    2. 公共参数：method/app_key/session/timestamp(yyyy-MM-dd HH:mm:ss)/format/v/sign_method/sign
    3. 签名：MD5(secret + 按 key 升序 key+value 拼接 + secret) 大写
    4. 业务 API：
       - 商品/价格/库存 taobao.item.get（price 单位元，num 为库存）
       - 订单 taobao.trades.sold.get（payment 单位元）
       - 评论 taobao.traderates.get（result=好评/中评/差评）
    """

    KEY_NAMES = TAOBAO_KEY_NAMES
    OAUTH_REFRESH_URL = TAOBAO_OAUTH_TOKEN_URL
    OAUTH_ID_FIELD = "client_id"
    PROVIDER = "淘宝开放平台（TOP）"

    _RATE_SENTIMENT = {"差评": "negative", "中评": "neutral", "好评": "positive"}
    _RATE_SCORE = {"差评": 1, "中评": 3, "好评": 5}

    async def call(
        self,
        method: str,
        biz_params: Optional[Dict[str, Any]] = None,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        """TOP 网关调用，返回 {method}_response 包装内的业务数据"""
        from datetime import datetime

        ak, sk, _, _ = self._resolve_credentials(
            app_key, app_secret, access_token, refresh_token, store_creds=store_creds
        )
        if not (ak and sk):
            raise ExternalAPIError(
                "淘宝 TOP 未配置：需要 NEUROVA_TAOBAO_APP_KEY / NEUROVA_TAOBAO_APP_SECRET"
            )
        token = await self._access_token(
            app_key, app_secret, access_token, refresh_token, store_id=store_id, store_creds=store_creds
        )
        params: Dict[str, Any] = {
            "method": method,
            "app_key": ak,
            "session": token,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
        }
        for k, v in (biz_params or {}).items():
            params[k] = _stringify_param(v)
        params["sign"] = _router_sign_md5(sk, params)
        data = await _http_post(TAOBAO_GATEWAY_URL, data=params)
        if not isinstance(data, dict):
            raise ExternalAPIError(f"TOP 响应格式异常: {data}")
        if "error_response" in data:
            err = data.get("error_response") or {}
            raise ExternalAPIError(f"TOP 错误 {err.get('code')}: {err.get('sub_msg') or err.get('msg')}")
        key = method.replace(".", "_") + "_response"
        if key in data:
            return data[key] or {}
        for k, v in data.items():
            if k.endswith("_response"):
                return v or {}
        raise ExternalAPIError(f"TOP 无法识别的响应: {data}")

    async def fetch_prices(self, num_iids: List[str], **creds) -> Dict[str, Any]:
        """taobao.item.get — 按 num_iid 查询价格（price 单位元）"""
        ids = [str(i).strip() for i in num_iids if str(i).strip()][:20]
        try:
            prices: Dict[str, Any] = {}
            raw_items: List[Dict[str, Any]] = []
            for nid in ids:
                resp = await self.call(
                    "taobao.item.get",
                    {"num_iid": nid, "fields": "num_iid,title,price,num"},
                    **creds,
                )
                item = resp.get("item") or {}
                price = item.get("price")
                try:
                    price_val = float(price) if price is not None else None
                except (TypeError, ValueError):
                    price_val = None
                prices[nid] = {"price": price_val, "currency": "CNY", "title": item.get("title", "")}
                raw_items.append(item)
            return _ok({"prices": prices, "raw": raw_items}, "taobao")
        except ExternalAPIError as exc:
            logger.warning("淘宝价格查询失败: %s", exc)
            return _fail(str(exc), "taobao")

    async def fetch_inventory(self, num_iids: List[str], **creds) -> Dict[str, Any]:
        """taobao.item.get — 按 num_iid 查询库存（num 字段）"""
        ids = [str(i).strip() for i in num_iids if str(i).strip()][:20]
        try:
            inventory: Dict[str, Any] = {}
            for nid in ids:
                resp = await self.call(
                    "taobao.item.get",
                    {"num_iid": nid, "fields": "num_iid,title,num"},
                    **creds,
                )
                item = resp.get("item") or {}
                try:
                    qty = int(item.get("num") or 0)
                except (TypeError, ValueError):
                    qty = 0
                inventory[nid] = {"totalQuantity": qty, "title": item.get("title", "")}
            return _ok({"inventory": inventory}, "taobao")
        except ExternalAPIError as exc:
            logger.warning("淘宝库存查询失败: %s", exc)
            return _fail(str(exc), "taobao")

    async def fetch_sold_trades(
        self, start_created: str = "", end_created: str = "", **creds
    ) -> Dict[str, Any]:
        """taobao.trades.sold.get — 已卖出订单聚合（payment 单位元）"""
        try:
            resp = await self.call(
                "taobao.trades.sold.get",
                {
                    "start_created": start_created,
                    "end_created": end_created,
                    "fields": "tid,type,status,payment,created,pay_time,num_iids,num",
                    "page_no": "1",
                    "page_size": "100",
                },
                **creds,
            )
            trades_wrap = resp.get("trades") or {}
            trades = trades_wrap.get("trade") if isinstance(trades_wrap, dict) else trades_wrap
            trades = trades or []
            total_sales = 0.0
            units = 0
            for t in trades:
                if not isinstance(t, dict):
                    continue
                try:
                    total_sales += float(t.get("payment") or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    units += int(t.get("num") or 0)
                except (TypeError, ValueError):
                    pass
            orders = len(trades)
            return _ok(
                {
                    "sales": round(total_sales, 2),
                    "orders": orders,
                    "units": units or orders,
                    "avg_order_value": round(total_sales / orders, 2) if orders else 0.0,
                    "order_items": trades,
                    "currency": "CNY",
                },
                "taobao",
            )
        except ExternalAPIError as exc:
            logger.warning("淘宝订单查询失败: %s", exc)
            return _fail(str(exc), "taobao")

    async def fetch_rates(self, num_iid: str, **creds) -> Dict[str, Any]:
        """taobao.traderates.get — 按 num_iid 拉取商品评论（好评/中评/差评）"""
        try:
            resp = await self.call(
                "taobao.traderates.get",
                {"rate_type": "get", "num_iid": str(num_iid), "page_no": "1", "page_size": "100"},
                **creds,
            )
            rates_wrap = resp.get("rates") or {}
            rates = rates_wrap.get("rate") if isinstance(rates_wrap, dict) else rates_wrap
            items: List[Dict[str, Any]] = []
            for r in rates or []:
                if not isinstance(r, dict):
                    continue
                result = str(r.get("result") or "")
                items.append(
                    {
                        "id": r.get("id"),
                        "content": r.get("content", ""),
                        "sentiment": self._RATE_SENTIMENT.get(result, "positive"),
                        "rating": self._RATE_SCORE.get(result),
                    }
                )
            return _ok({"items": items, "num_iid": str(num_iid)}, "taobao")
        except ExternalAPIError as exc:
            logger.warning("淘宝评论查询失败: %s", exc)
            return _fail(str(exc), "taobao")


class JdOpenClient(_OpenGatewayClientBase):
    """京东开放平台客户端（open.jd.com）

    网关 POST https://api.jd.com/routerjson，业务参数置于 360buy_param_json，
    响应包装键 {method 点换下划线}_responce（京东历史拼写，兼容 _response）。
    业务 API：
    - 订单 jingdong.pop.order.search（orderPayment 单位元）
    - 商品 jingdong.ware.read.findSkuListPage（jdPrice/stockNum）
    京东开放平台不提供商品评论拉取 API。
    """

    KEY_NAMES = JD_KEY_NAMES
    OAUTH_REFRESH_URL = JD_OAUTH_TOKEN_URL
    OAUTH_ID_FIELD = "client_id"
    PROVIDER = "京东开放平台"

    async def call(
        self,
        method: str,
        biz_params: Optional[Dict[str, Any]] = None,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        from datetime import datetime

        ak, sk, _, _ = self._resolve_credentials(
            app_key, app_secret, access_token, refresh_token, store_creds=store_creds
        )
        if not (ak and sk):
            raise ExternalAPIError(
                "京东开放平台未配置：需要 NEUROVA_JD_APP_KEY / NEUROVA_JD_APP_SECRET"
            )
        token = await self._access_token(
            app_key, app_secret, access_token, refresh_token, store_id=store_id, store_creds=store_creds
        )
        params: Dict[str, Any] = {
            "method": method,
            "app_key": ak,
            "access_token": token,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "v": "1.0",
            "format": "json",
            "360buy_param_json": json.dumps(biz_params or {}, ensure_ascii=False, separators=(",", ":")),
        }
        params["sign"] = _router_sign_md5(sk, params)
        data = await _http_post(JD_GATEWAY_URL, data=params)
        if not isinstance(data, dict):
            raise ExternalAPIError(f"京东响应格式异常: {data}")
        if "error_response" in data:
            err = data.get("error_response") or {}
            raise ExternalAPIError(
                f"京东错误 {err.get('code')}: {err.get('zh_desc') or err.get('en_desc') or err.get('msg')}"
            )
        key = method.replace(".", "_")
        for suffix in ("_responce", "_response"):
            if key + suffix in data:
                return data[key + suffix] or {}
        for k, v in data.items():
            if k.endswith("_responce") or k.endswith("_response"):
                return v or {}
        raise ExternalAPIError(f"京东无法识别的响应: {data}")

    async def fetch_orders(self, start_date: str = "", end_date: str = "", **creds) -> Dict[str, Any]:
        """jingdong.pop.order.search — POP 订单聚合（orderPayment 单位元）"""
        try:
            resp = await self.call(
                "jingdong.pop.order.search",
                {"startDate": start_date, "endDate": end_date, "page": "1", "pageSize": "100"},
                **creds,
            )
            wrap = resp.get("orderInfoList") or {}
            orders = wrap.get("orderInfo") if isinstance(wrap, dict) else wrap
            orders = orders or []
            total_sales = 0.0
            units = 0
            for o in orders:
                if not isinstance(o, dict):
                    continue
                try:
                    total_sales += float(o.get("orderPayment") or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    units += int(o.get("itemTotal") or 0)
                except (TypeError, ValueError):
                    pass
            n = len(orders)
            return _ok(
                {
                    "sales": round(total_sales, 2),
                    "orders": n,
                    "units": units or n,
                    "avg_order_value": round(total_sales / n, 2) if n else 0.0,
                    "order_items": orders,
                    "currency": "CNY",
                },
                "jd",
            )
        except ExternalAPIError as exc:
            logger.warning("京东订单查询失败: %s", exc)
            return _fail(str(exc), "jd")

    async def fetch_skus(self, page: str = "1", page_size: str = "100", **creds) -> Dict[str, Any]:
        """jingdong.ware.read.findSkuListPage — SKU 列表（jdPrice/stockNum）"""
        try:
            resp = await self.call(
                "jingdong.ware.read.findSkuListPage",
                {"page": page, "pageSize": page_size},
                **creds,
            )
            wrap = resp.get("skuList") or {}
            skus_raw = wrap.get("sku") if isinstance(wrap, dict) else wrap
            skus: Dict[str, Any] = {}
            for s in skus_raw or []:
                if not isinstance(s, dict):
                    continue
                sku_id = str(s.get("skuId") or "")
                if not sku_id:
                    continue
                price = s.get("jdPrice") if s.get("jdPrice") is not None else s.get("price")
                try:
                    price_val = float(price) if price is not None else None
                except (TypeError, ValueError):
                    price_val = None
                stock_raw = s.get("stockNum") if s.get("stockNum") is not None else s.get("stock")
                try:
                    stock = int(stock_raw or 0)
                except (TypeError, ValueError):
                    stock = 0
                skus[sku_id] = {
                    "price": price_val,
                    "stock": stock,
                    "title": s.get("title") or s.get("skuName") or "",
                    "currency": "CNY",
                }
            return _ok({"skus": skus}, "jd")
        except ExternalAPIError as exc:
            logger.warning("京东 SKU 查询失败: %s", exc)
            return _fail(str(exc), "jd")

    async def fetch_prices(self, sku_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        """findSkuListPage 结果中筛选指定 skuId 的价格"""
        result = await self.fetch_skus(**creds)
        if result.get("status") != "success":
            return result
        skus = result["output"]["skus"]
        wanted = {str(s).strip() for s in (sku_ids or []) if str(s).strip()}
        prices = {
            sid: {"price": info["price"], "currency": "CNY", "title": info.get("title", "")}
            for sid, info in skus.items()
            if not wanted or sid in wanted
        }
        return _ok({"prices": prices}, "jd")

    async def fetch_inventory(self, sku_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        """findSkuListPage 结果中筛选指定 skuId 的库存（stockNum）"""
        result = await self.fetch_skus(**creds)
        if result.get("status") != "success":
            return result
        skus = result["output"]["skus"]
        wanted = {str(s).strip() for s in (sku_ids or []) if str(s).strip()}
        inventory = {
            sid: {"totalQuantity": info["stock"], "title": info.get("title", "")}
            for sid, info in skus.items()
            if not wanted or sid in wanted
        }
        return _ok({"inventory": inventory}, "jd")


class PddOpenClient(_OpenGatewayClientBase):
    """拼多多开放平台客户端（open.pinduoduo.com）

    网关 POST https://gw-api.pinduoduo.com/api/router，type 为 API 名，
    业务参数平铺为顶层表单字段，timestamp 为 unix 秒，金额单位为分。
    业务 API：
    - 订单 pdd.order.list.get（pay_amount 单位分）
    - 商品 pdd.goods.information.get（min_group_price 分 / goods_quantity 库存）
    拼多多开放平台不提供商品评论拉取 API。
    """

    KEY_NAMES = PDD_KEY_NAMES
    OAUTH_REFRESH_URL = PDD_OAUTH_TOKEN_URL
    OAUTH_ID_FIELD = "client_id"
    PROVIDER = "拼多多开放平台"

    async def call(
        self,
        api_type: str,
        biz_params: Optional[Dict[str, Any]] = None,
        client_id: str = "",
        client_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        cid, cs, _, _ = self._resolve_credentials(
            client_id, client_secret, access_token, refresh_token, store_creds=store_creds
        )
        if not (cid and cs):
            raise ExternalAPIError(
                "拼多多开放平台未配置：需要 NEUROVA_PDD_CLIENT_ID / NEUROVA_PDD_CLIENT_SECRET"
            )
        token = await self._access_token(
            client_id, client_secret, access_token, refresh_token, store_id=store_id, store_creds=store_creds
        )
        params: Dict[str, Any] = {
            "type": api_type,
            "client_id": cid,
            "access_token": token,
            "timestamp": str(int(time.time())),
            "data_type": "JSON",
        }
        for k, v in (biz_params or {}).items():
            params[k] = _stringify_param(v)
        params["sign"] = _router_sign_md5(cs, params)
        data = await _http_post(PDD_GATEWAY_URL, data=params)
        if not isinstance(data, dict):
            raise ExternalAPIError(f"拼多多响应格式异常: {data}")
        if "error_response" in data:
            err = data.get("error_response") or {}
            raise ExternalAPIError(
                f"拼多多错误 {err.get('error_code')}: {err.get('sub_msg') or err.get('error_msg')}"
            )
        key = api_type.replace(".", "_") + "_response"
        if key in data:
            return data[key] or {}
        for k, v in data.items():
            if k.endswith("_response"):
                return v or {}
        raise ExternalAPIError(f"拼多多无法识别的响应: {data}")

    async def fetch_orders(
        self, start_updated_at: int = 0, end_updated_at: int = 0, **creds
    ) -> Dict[str, Any]:
        """pdd.order.list.get — 订单聚合（pay_amount 单位分）"""
        try:
            resp = await self.call(
                "pdd.order.list.get",
                {
                    "start_updated_at": int(start_updated_at),
                    "end_updated_at": int(end_updated_at),
                    "page": 1,
                    "page_size": 100,
                },
                **creds,
            )
            orders = resp.get("order_list") or []
            total_fen = 0
            units = 0
            for o in orders:
                if not isinstance(o, dict):
                    continue
                try:
                    total_fen += int(o.get("pay_amount") or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    units += int(o.get("goods_amount") or 0)
                except (TypeError, ValueError):
                    pass
            n = len(orders)
            return _ok(
                {
                    "sales": round(total_fen / 100.0, 2),
                    "orders": n,
                    "units": units or n,
                    "avg_order_value": round(total_fen / 100.0 / n, 2) if n else 0.0,
                    "order_items": orders,
                    "currency": "CNY",
                },
                "pdd",
            )
        except ExternalAPIError as exc:
            logger.warning("拼多多订单查询失败: %s", exc)
            return _fail(str(exc), "pdd")

    async def fetch_goods(self, goods_ids: List[str], **creds) -> Dict[str, Any]:
        """pdd.goods.information.get — 按 goods_id 查价格（分）与库存（goods_quantity）"""
        ids = [str(g).strip() for g in goods_ids if str(g).strip()][:20]
        try:
            prices: Dict[str, Any] = {}
            inventory: Dict[str, Any] = {}
            for gid in ids:
                resp = await self.call("pdd.goods.information.get", {"goods_id": gid}, **creds)
                for detail in resp.get("goods_details") or []:
                    if not isinstance(detail, dict):
                        continue
                    key = str(detail.get("goods_id") or gid)
                    prices[key] = {
                        "price": _fen_to_yuan(detail.get("min_group_price")),
                        "currency": "CNY",
                        "title": detail.get("goods_name", ""),
                    }
                    try:
                        qty = int(detail.get("goods_quantity") or 0)
                    except (TypeError, ValueError):
                        qty = 0
                    inventory[key] = {"totalQuantity": qty}
            return _ok({"prices": prices, "inventory": inventory}, "pdd")
        except ExternalAPIError as exc:
            logger.warning("拼多多商品查询失败: %s", exc)
            return _fail(str(exc), "pdd")

    async def fetch_prices(self, goods_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        result = await self.fetch_goods(goods_ids or [], **creds)
        if result.get("status") != "success":
            return result
        return _ok({"prices": result["output"]["prices"]}, "pdd")

    async def fetch_inventory(self, goods_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        result = await self.fetch_goods(goods_ids or [], **creds)
        if result.get("status") != "success":
            return result
        return _ok({"inventory": result["output"]["inventory"]}, "pdd")


class DouyinEcomClient(_OpenGatewayClientBase):
    """抖店开放平台客户端（op.jinritemai.com）

    网关 POST https://openapi-fxg.jinritemai.com，业务参数置于 param_json（紧凑 JSON），
    签名仅 app_key/method/param_json/timestamp/v 五键参与，响应 {err_no, message, data}，
    金额单位为分。
    业务 API：
    - 订单 order.searchList（create_time_start/end unix 秒，pay_amount 分）
    - 商品 product.listV2（discount_price 分 / stock_num 库存）
    抖店开放平台不提供商品评论拉取 API。
    """

    KEY_NAMES = DOUYIN_ECOM_KEY_NAMES
    OAUTH_REFRESH_URL = DOUYIN_ECOM_OAUTH_REFRESH_URL
    OAUTH_ID_FIELD = "app_key"
    PROVIDER = "抖店开放平台"

    async def call(
        self,
        method: str,
        biz_params: Optional[Dict[str, Any]] = None,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        ak, sk, _, _ = self._resolve_credentials(
            app_key, app_secret, access_token, refresh_token, store_creds=store_creds
        )
        if not (ak and sk):
            raise ExternalAPIError(
                "抖店开放平台未配置：需要 NEUROVA_DOUYIN_ECOM_APP_KEY / NEUROVA_DOUYIN_ECOM_APP_SECRET"
            )
        token = await self._access_token(
            app_key, app_secret, access_token, refresh_token, store_id=store_id, store_creds=store_creds
        )
        param_json = json.dumps(biz_params or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        signable = {
            "app_key": ak,
            "method": method,
            "param_json": param_json,
            "timestamp": str(int(time.time())),
            "v": "2",
        }
        params = dict(signable)
        params["sign_method"] = "md5"
        params["access_token"] = token
        params["sign"] = _douyin_sign_md5(sk, signable)
        data = await _http_post(DOUYIN_ECOM_GATEWAY_URL, data=params)
        if not isinstance(data, dict):
            raise ExternalAPIError(f"抖店响应格式异常: {data}")
        err_no = data.get("err_no", data.get("code"))
        if err_no not in (0, None):
            raise ExternalAPIError(f"抖店错误 err_no={err_no}: {data.get('message')}")
        return data.get("data") or {}

    async def fetch_orders(
        self, create_time_start: int = 0, create_time_end: int = 0, **creds
    ) -> Dict[str, Any]:
        """order.searchList — 订单聚合（pay_amount 单位分）"""
        try:
            resp = await self.call(
                "order.searchList",
                {
                    "create_time_start": int(create_time_start),
                    "create_time_end": int(create_time_end),
                    "page": 0,
                    "size": 100,
                },
                **creds,
            )
            orders = resp.get("shop_order_list") or []
            total_fen = 0
            units = 0
            for o in orders:
                if not isinstance(o, dict):
                    continue
                try:
                    total_fen += int(o.get("pay_amount") or 0)
                except (TypeError, ValueError):
                    pass
                units += len(o.get("sku_order_list") or [])
            n = len(orders)
            return _ok(
                {
                    "sales": round(total_fen / 100.0, 2),
                    "orders": n,
                    "units": units or n,
                    "avg_order_value": round(total_fen / 100.0 / n, 2) if n else 0.0,
                    "order_items": orders,
                    "currency": "CNY",
                },
                "douyin-ecom",
            )
        except ExternalAPIError as exc:
            logger.warning("抖店订单查询失败: %s", exc)
            return _fail(str(exc), "douyin-ecom")

    async def fetch_products(self, page: int = 0, size: int = 100, **creds) -> Dict[str, Any]:
        """product.listV2 — 商品列表（discount_price 分 / stock_num 库存）"""
        try:
            resp = await self.call("product.listV2", {"page": page, "size": size}, **creds)
            products = resp.get("data") or resp.get("products") or []
            prices: Dict[str, Any] = {}
            inventory: Dict[str, Any] = {}
            for p in products:
                if not isinstance(p, dict):
                    continue
                pid = str(p.get("product_id") or "")
                if not pid:
                    continue
                price_fen = p.get("discount_price") if p.get("discount_price") is not None else p.get("market_price")
                prices[pid] = {
                    "price": _fen_to_yuan(price_fen),
                    "currency": "CNY",
                    "title": p.get("name", ""),
                }
                try:
                    stock = int(p.get("stock_num") or 0)
                except (TypeError, ValueError):
                    stock = 0
                inventory[pid] = {"totalQuantity": stock}
            return _ok({"prices": prices, "inventory": inventory}, "douyin-ecom")
        except ExternalAPIError as exc:
            logger.warning("抖店商品查询失败: %s", exc)
            return _fail(str(exc), "douyin-ecom")

    async def fetch_prices(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        result = await self.fetch_products(**creds)
        if result.get("status") != "success":
            return result
        prices = result["output"]["prices"]
        wanted = {str(p).strip() for p in (product_ids or []) if str(p).strip()}
        if wanted:
            prices = {k: v for k, v in prices.items() if k in wanted}
        return _ok({"prices": prices}, "douyin-ecom")

    async def fetch_inventory(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        result = await self.fetch_products(**creds)
        if result.get("status") != "success":
            return result
        inventory = result["output"]["inventory"]
        wanted = {str(p).strip() for p in (product_ids or []) if str(p).strip()}
        if wanted:
            inventory = {k: v for k, v in inventory.items() if k in wanted}
        return _ok({"inventory": inventory}, "douyin-ecom")


class TikTokShopClient(_OpenGatewayClientBase):
    """TikTok Shop Partner 客户端（partner.tiktokshop.com）

    REST 网关 https://open-api.tiktokglobalshop.com，版本在路径（/product/202309/...）。
    公共查询参数 app_key/access_token/timestamp(unix 秒)/sign；
    签名 SHA256(secret + 按 key 升序 key+value 拼接 + secret) 小写，POST 请求体参与签名。
    金额为最小货币单位（分）。响应 {code, message, data}。
    业务 API：
    - 商品 GET /product/202309/products（price.sale_price / skus.stock_infos）
    - 订单 POST /order/202309/orders/search（payment_amount）
    TikTok Shop 开放平台不提供商品评论拉取 API。
    """

    KEY_NAMES = TIKTOK_SHOP_KEY_NAMES
    OAUTH_REFRESH_URL = TIKTOK_SHOP_GATEWAY_URL + TIKTOK_SHOP_TOKEN_REFRESH_PATH
    OAUTH_ID_FIELD = "app_key"
    PROVIDER = "TikTok Shop 开放平台"

    async def _request(
        self,
        http_method: str,
        path: str,
        query: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        ak, sk, _, _ = self._resolve_credentials(
            app_key, app_secret, access_token, refresh_token, store_creds=store_creds
        )
        if not (ak and sk):
            raise ExternalAPIError(
                "TikTok Shop 未配置：需要 NEUROVA_TIKTOK_SHOP_APP_KEY / NEUROVA_TIKTOK_SHOP_APP_SECRET"
            )
        token = await self._access_token(
            app_key, app_secret, access_token, refresh_token, store_id=store_id, store_creds=store_creds
        )
        params: Dict[str, Any] = {
            "app_key": ak,
            "access_token": token,
            "timestamp": str(int(time.time())),
        }
        params.update(query or {})
        # shop_cipher：2024 起业务 API 强制字段，取自店铺注册表 extra
        shop_cipher = ""
        if store_creds is not None:
            shop_cipher = str((store_creds.extra or {}).get("shop_cipher") or "")
        if shop_cipher:
            params["shop_cipher"] = shop_cipher
        signable = dict(params)
        if body:
            signable.update({k: _stringify_param(v) for k, v in body.items()})
        params["sign"] = _tiktok_sign_sha256(sk, signable)
        url = TIKTOK_SHOP_GATEWAY_URL + path
        if http_method.upper() == "GET":
            data = await _http_get(url, params=params)
        else:
            data = await _http_post(url, params=params, json=body or {})
        if not isinstance(data, dict):
            raise ExternalAPIError(f"TikTok Shop 响应格式异常: {data}")
        code = data.get("code")
        if code not in (0, None):
            raise ExternalAPIError(f"TikTok Shop 错误 code={code}: {data.get('message')}")
        return data.get("data") or {}

    async def fetch_shop_cipher(self, **creds) -> Dict[str, Any]:
        """GET /authorization/202309/shops — 取回授权店铺与 shop_cipher（连接测试用）"""
        try:
            data = await self._request("GET", "/authorization/202309/shops", **creds)
            return _ok({"shops": data.get("shops") or []}, "tiktok")
        except ExternalAPIError as exc:
            logger.warning("TikTok Shop 店铺列表查询失败: %s", exc)
            return _fail(str(exc), "tiktok")

    async def fetch_products(self, page_size: int = 100, **creds) -> Dict[str, Any]:
        """GET /product/202309/products — 商品列表（金额为最小货币单位）"""
        try:
            data = await self._request(
                "GET", "/product/202309/products", query={"page_size": str(page_size)}, **creds
            )
            prices: Dict[str, Any] = {}
            inventory: Dict[str, Any] = {}
            for p in data.get("products") or []:
                if not isinstance(p, dict):
                    continue
                pid = str(p.get("id") or "")
                if not pid:
                    continue
                sale = ((p.get("price") or {}).get("sale_price")) or {}
                prices[pid] = {
                    "price": _fen_to_yuan(sale.get("amount")),
                    "currency": str(sale.get("currency_code") or ""),
                    "title": p.get("title", ""),
                }
                stock = 0
                for sku in p.get("skus") or []:
                    for info in (sku or {}).get("stock_infos") or []:
                        try:
                            stock += int((info or {}).get("available_stock") or 0)
                        except (TypeError, ValueError):
                            pass
                inventory[pid] = {"totalQuantity": stock}
            return _ok({"prices": prices, "inventory": inventory}, "tiktok")
        except ExternalAPIError as exc:
            logger.warning("TikTok Shop 商品查询失败: %s", exc)
            return _fail(str(exc), "tiktok")

    async def search_orders(
        self, create_time_ge: int = 0, create_time_lt: int = 0, **creds
    ) -> Dict[str, Any]:
        """POST /order/202309/orders/search — 订单聚合（payment_amount 最小货币单位）"""
        try:
            body = {
                "create_time_ge": int(create_time_ge),
                "create_time_lt": int(create_time_lt),
                "page_size": 100,
            }
            data = await self._request("POST", "/order/202309/orders/search", body=body, **creds)
            orders = data.get("orders") or []
            total_cents = 0
            units = 0
            for o in orders:
                if not isinstance(o, dict):
                    continue
                amount = (o.get("payment_amount") or {}).get("amount")
                try:
                    total_cents += int(float(amount or 0))
                except (TypeError, ValueError):
                    pass
                for line in o.get("line_items") or []:
                    try:
                        units += int((line or {}).get("quantity") or 0)
                    except (TypeError, ValueError):
                        pass
            n = len(orders)
            return _ok(
                {
                    "sales": round(total_cents / 100.0, 2),
                    "orders": n,
                    "units": units or n,
                    "avg_order_value": round(total_cents / 100.0 / n, 2) if n else 0.0,
                    "order_items": orders,
                    "currency": "USD",
                },
                "tiktok",
            )
        except ExternalAPIError as exc:
            logger.warning("TikTok Shop 订单查询失败: %s", exc)
            return _fail(str(exc), "tiktok")

    async def fetch_prices(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        result = await self.fetch_products(**creds)
        if result.get("status") != "success":
            return result
        prices = result["output"]["prices"]
        wanted = {str(p).strip() for p in (product_ids or []) if str(p).strip()}
        if wanted:
            prices = {k: v for k, v in prices.items() if k in wanted}
        return _ok({"prices": prices}, "tiktok")

    async def fetch_inventory(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        result = await self.fetch_products(**creds)
        if result.get("status") != "success":
            return result
        inventory = result["output"]["inventory"]
        wanted = {str(p).strip() for p in (product_ids or []) if str(p).strip()}
        if wanted:
            inventory = {k: v for k, v in inventory.items() if k in wanted}
        return _ok({"inventory": inventory}, "tiktok")


_cn_client_instances: Dict[str, Any] = {}


# ==================== 三平台客户端（1688 / 小红书 / 闲鱼） ====================
# 协议依据 docs/neurflow-store-connection-design.md §2.1-2.3（2026-08-29 复核）：
# - 1688：ocean 网关（路径式 URL + HMAC-SHA1 大写十六进制），与 TOP 协议独立
# - 小红书：ark 网关 + MD5 固定串签名（版本 2.0）
# - 闲鱼：不建新协议，复用淘宝 TOP（网关/MD5/OAuth），仅替换业务分类
# 以下 MD5/SHA1 签名均为平台协议强制算法（验签用途），非加密用途。

ALIBABA1688_GATEWAY_URL = "https://gw.open.1688.com/openapi"
ALIBABA1688_KEY_NAMES: Dict[str, List[str]] = {
    "app_key": ["NEUROVA_1688_API_KEY", "NEUROVA_1688_APP_KEY"],
    "app_secret": ["NEUROVA_1688_API_SECRET", "NEUROVA_1688_APP_SECRET"],
    "access_token": ["NEUROVA_1688_ACCESS_TOKEN"],
    "refresh_token": ["NEUROVA_1688_REFRESH_TOKEN"],
}

XHS_GATEWAY_URL = "https://ark.xiaohongshu.com/ark/open_api/v3/common_controller"
XHS_VERSION = "2.0"
XHS_KEY_NAMES: Dict[str, List[str]] = {
    "app_key": ["NEUROVA_XIAOHONGSHU_API_KEY", "NEUROVA_XIAOHONGSHU_APP_KEY"],
    "app_secret": ["NEUROVA_XIAOHONGSHU_APP_SECRET"],
    "access_token": ["NEUROVA_XIAOHONGSHU_ACCESS_TOKEN"],
    "refresh_token": ["NEUROVA_XIAOHONGSHU_REFRESH_TOKEN"],
}

XIANYU_KEY_NAMES: Dict[str, List[str]] = {
    "app_key": ["NEUROVA_XIANYU_API_KEY", "NEUROVA_XIANYU_APP_KEY"],
    "app_secret": ["NEUROVA_XIANYU_APP_SECRET"],
    "access_token": ["NEUROVA_XIANYU_ACCESS_TOKEN"],
    "refresh_token": ["NEUROVA_XIANYU_REFRESH_TOKEN"],
}


def _alibaba1688_sign(secret: str, path: str, params: Dict[str, Any]) -> str:
    """1688 ocean 签名：HMAC-SHA1(appSecret, 路径段 + 参数按 key 升序 key+value 连写)，大写十六进制。

    平台协议强制算法（接入验签），非加密用途。
    """
    parts = [f"{k}{_stringify_param(v)}" for k, v in params.items()]
    parts.sort()
    mac = hmac.new(secret.encode("utf-8"), (path + "".join(parts)).encode("utf-8"), hashlib.sha1)
    return mac.hexdigest().upper()


def _xiaohongshu_sign(method: str, app_id: str, app_secret: str, version: str, timestamp: int) -> str:
    """小红书签名：MD5("{method}?appId={app_id}&timestamp={ts}&version={version}{app_secret}") 小写。

    平台协议强制算法（接入验签），body 业务参数不参与签名。
    """
    raw = f"{method}?appId={app_id}&timestamp={timestamp}&version={version}{app_secret}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class Alibaba1688Client:
    """1688 阿里巴巴开放平台客户端（ocean 网关，协议独立于 TOP）

    - 调用 URL：{gateway}/param2/{version}/{namespace}/{apiName}/{appKey}
    - 签名：HMAC-SHA1（大写十六进制）→ _aop_signature
    - token：param2/1/system.oauth2/getToken/{appKey}（路径已网关探测确认）
    - access_token 作为普通业务参数提交
    """

    KEY_NAMES = ALIBABA1688_KEY_NAMES
    PROVIDER = "阿里巴巴开放平台（1688）"

    def __init__(self) -> None:
        self._token_cache: Dict[str, Any] = {}

    def _resolve(
        self,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> tuple:
        ak = app_key or (store_creds.app_key if store_creds else "") or (
            resolve_api_key(self.KEY_NAMES.get("app_key", []), "") or ""
        )
        sk = app_secret or (store_creds.app_secret if store_creds else "") or (
            resolve_api_key(self.KEY_NAMES.get("app_secret", []), "") or ""
        )
        at = access_token or (store_creds.access_token if store_creds else "") or (
            resolve_api_key(self.KEY_NAMES.get("access_token", []), "") or ""
        )
        rt = refresh_token or (store_creds.refresh_token if store_creds else "") or (
            resolve_api_key(self.KEY_NAMES.get("refresh_token", []), "") or ""
        )
        return ak, sk, at, rt

    def is_available(
        self,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> bool:
        ak, sk, at, rt = self._resolve(app_key, app_secret, access_token, refresh_token, store_creds)
        return bool(ak and sk and (at or rt))

    async def _access_token(
        self,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> str:
        ak, sk, _, rt = self._resolve(app_key, app_secret, access_token, refresh_token, store_creds)
        if access_token:
            return access_token
        cache_key = store_id or "default"
        cached = self._token_cache.get(cache_key) or {}
        if cached.get("token") and cached.get("expires_at", 0) > time.time() + 60:
            return str(cached["token"])
        if not rt:
            raise ExternalAPIError("1688 未配置 access_token / refresh_token")
        token = await self.fetch_token(app_key=ak, app_secret=sk, refresh_token=rt)
        self._token_cache[cache_key] = {"token": token, "expires_at": time.time() + 86400}
        return token

    async def fetch_token(
        self,
        app_key: str = "",
        app_secret: str = "",
        refresh_token: str = "",
        code: str = "",
        redirect_uri: str = "",
    ) -> str:
        """system.oauth2.getToken — 授权码换 token / refresh_token 刷新（路径已核实）"""
        path = f"param2/1/system.oauth2/getToken/{app_key}"
        params: Dict[str, Any] = {"grant_type": "refresh_token", "client_id": app_key, "client_secret": app_secret}
        if code:
            params["grant_type"] = "authorization_code"
            params["code"] = code
            if redirect_uri:
                params["redirect_uri"] = redirect_uri
        else:
            params["refresh_token"] = refresh_token
        params["_aop_signature"] = _alibaba1688_sign(app_secret, path, params)
        data = await _http_post(f"{ALIBABA1688_GATEWAY_URL}/{path}", data=params)
        payload = (data or {}).get("data") if isinstance(data, dict) else None
        token = (payload or {}).get("access_token") if isinstance(payload, dict) else None
        if not token and isinstance(data, dict):
            token = data.get("access_token")
        if not token:
            raise ExternalAPIError(f"1688 令牌获取失败: {data}")
        return str(token)

    async def call(
        self,
        namespace: str,
        api_name: str,
        biz_params: Optional[Dict[str, Any]] = None,
        version: str = "1",
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        ak, sk, at, rt = self._resolve(app_key, app_secret, access_token, refresh_token, store_creds)
        if not (ak and sk):
            raise ExternalAPIError("1688 未配置：需要 appKey/appSecret（NEUROVA_1688_API_KEY / 对应 SECRET 键）")
        token = at or await self._access_token(ak, sk, at, rt, store_id=store_id, store_creds=store_creds)
        path = f"param2/{version}/{namespace}/{api_name}/{ak}"
        params: Dict[str, Any] = dict(biz_params or {})
        if token:
            params["access_token"] = token
        params["_aop_signature"] = _alibaba1688_sign(sk, path, params)
        data = await _http_post(f"{ALIBABA1688_GATEWAY_URL}/{path}", data=params)
        if not isinstance(data, dict):
            raise ExternalAPIError(f"1688 响应格式异常: {data}")
        err = str(data.get("error_message") or data.get("errorMessage") or "") or str(data.get("error_code") or "")
        if err:
            raise ExternalAPIError(f"1688 错误: {err} {data}")
        return data

    async def fetch_prices(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        """com.alibaba.product/alibaba.product.get — 按 offerId 查询（字段名以官方文档核对为准，防御式提取）"""
        try:
            prices: Dict[str, Any] = {}
            for pid in [str(p).strip() for p in (product_ids or []) if str(p).strip()]:
                resp = await self.call("com.alibaba.product", "alibaba.product.get", {"offerId": pid}, **creds)
                body = resp if isinstance(resp, dict) else {}
                live = body.get("result") if isinstance(body.get("result"), dict) else body
                prices[pid] = {
                    "price": _first_float(live, ("price", "offerPrice", "salePrice", "priceInfo")),
                    "currency": "CNY",
                    "title": str(live.get("productName") or live.get("name") or "") if isinstance(live, dict) else "",
                    "raw": body,
                }
            return _ok({"prices": prices}, "ali1688")
        except ExternalAPIError as exc:
            logger.warning("1688 价格查询失败: %s", exc)
            return _fail(str(exc), "ali1688")

    async def fetch_inventory(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        try:
            inventory: Dict[str, Any] = {}
            for pid in [str(p).strip() for p in (product_ids or []) if str(p).strip()]:
                resp = await self.call("com.alibaba.product", "alibaba.product.get", {"offerId": pid}, **creds)
                body = resp if isinstance(resp, dict) else {}
                live = body.get("result") if isinstance(body.get("result"), dict) else body
                inventory[pid] = {
                    "totalQuantity": _first_int(live, ("amountOnSale", "quantity", "stock")),
                    "title": str(live.get("productName") or "") if isinstance(live, dict) else "",
                }
            return _ok({"inventory": inventory}, "ali1688")
        except ExternalAPIError as exc:
            logger.warning("1688 库存查询失败: %s", exc)
            return _fail(str(exc), "ali1688")


class XiaohongshuClient(_OpenGatewayClientBase):
    """小红书开放平台客户端（ark 网关）— 协议已复核

    - 网关 POST https://ark.xiaohongshu.com/ark/open_api/v3/common_controller（JSON）
    - 公共参数 method/appId/sign/timestamp(秒)/version=2.0/accessToken
    - 签名 MD5 固定串（小写），body 业务参数不参与
    - token：oauth.getAccessToken（code）/ oauth.refreshToken（refreshToken）同网关
    """

    KEY_NAMES = XHS_KEY_NAMES
    OAUTH_REFRESH_URL = XHS_GATEWAY_URL  # 仅用于语义对齐；实际刷新走 override 的 get_access_token
    OAUTH_ID_FIELD = "appId"
    PROVIDER = "小红书开放平台"

    async def get_access_token(
        self,
        app_key: str = "",
        app_secret: str = "",
        refresh_token: str = "",
        code: str = "",
    ) -> str:
        ak, sk, _, _ = self._resolve_credentials(app_key, app_secret, "", refresh_token, store_creds=None)
        if not (ak and sk):
            raise ExternalAPIError("小红书未配置：需要 appKey/appSecret")
        method = "oauth.getAccessToken" if code else "oauth.refreshToken"
        ts = int(time.time())
        body: Dict[str, Any] = {
            "method": method,
            "appId": ak,
            "sign": _xiaohongshu_sign(method, ak, sk, XHS_VERSION, ts),
            "timestamp": ts,
            "version": XHS_VERSION,
        }
        if code:
            body["code"] = code
        else:
            body["refreshToken"] = refresh_token
        data = await _http_post(XHS_GATEWAY_URL, json=body)
        payload = (data or {}).get("data") if isinstance(data, dict) else None
        token = (payload or {}).get("accessToken") if isinstance(payload, dict) else None
        if not token:
            raise ExternalAPIError(f"小红书令牌获取失败: {data}")
        return str(token)

    async def call(
        self,
        method: str,
        biz_params: Optional[Dict[str, Any]] = None,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        ak, sk, _, _ = self._resolve_credentials(app_key, app_secret, access_token, refresh_token, store_creds=store_creds)
        if not (ak and sk):
            raise ExternalAPIError("小红书未配置：需要 appKey/appSecret")
        token = await self._access_token(
            app_key, app_secret, access_token, refresh_token, store_id=store_id, store_creds=store_creds
        )
        ts = int(time.time())
        body: Dict[str, Any] = {
            "method": method,
            "appId": ak,
            "sign": _xiaohongshu_sign(method, ak, sk, XHS_VERSION, ts),
            "timestamp": ts,
            "version": XHS_VERSION,
            "accessToken": token,
        }
        body.update(biz_params or {})
        data = await _http_post(XHS_GATEWAY_URL, json=body)
        if not isinstance(data, dict):
            raise ExternalAPIError(f"小红书响应格式异常: {data}")
        if not data.get("success"):
            raise ExternalAPIError(f"小红书错误 {data.get('error_code')}: {data.get('error_msg')}")
        return data.get("data") or {}

    async def fetch_prices(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        """product.getItemInfo — 按 itemId 查询（字段名防御式提取，raw 保留供核对）"""
        try:
            prices: Dict[str, Any] = {}
            for pid in [str(p).strip() for p in (product_ids or []) if str(p).strip()]:
                data = await self.call("product.getItemInfo", {"itemId": pid}, **creds)
                live = data if isinstance(data, dict) else {}
                inner = live.get("itemInfo") if isinstance(live, dict) else None
                item = inner if isinstance(inner, dict) else live
                prices[pid] = {
                    "price": _first_float(item, ("salePrice", "price", "referencePrice")),
                    "currency": "CNY",
                    "title": str(item.get("itemName") or item.get("title") or "") if isinstance(item, dict) else "",
                    "raw": live,
                }
            return _ok({"prices": prices}, "xiaohongshu")
        except ExternalAPIError as exc:
            logger.warning("小红书价格查询失败: %s", exc)
            return _fail(str(exc), "xiaohongshu")

    async def fetch_inventory(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        """inventory.getSkuStockV2 — 按 skuId 查询库存"""
        try:
            inventory: Dict[str, Any] = {}
            for pid in [str(p).strip() for p in (product_ids or []) if str(p).strip()]:
                data = await self.call("inventory.getSkuStockV2", {"skuId": pid}, **creds)
                live = data if isinstance(data, dict) else {}
                inner = live.get("skuStock") if isinstance(live, dict) else None
                item = inner if isinstance(inner, dict) else live
                inventory[pid] = {
                    "totalQuantity": _first_int(item, ("quantity", "stock", "availableQuantity")),
                    "title": str(item.get("skuName") or "") if isinstance(item, dict) else "",
                    "raw": live,
                }
            return _ok({"inventory": inventory}, "xiaohongshu")
        except ExternalAPIError as exc:
            logger.warning("小红书库存查询失败: %s", exc)
            return _fail(str(exc), "xiaohongshu")

    async def fetch_orders(self, start_time: int = 0, end_time: int = 0, **creds) -> Dict[str, Any]:
        """order.getOrderList — 订单聚合（时间参数单位以官方文档为准，raw 保留）"""
        try:
            body: Dict[str, Any] = {"startTime": int(start_time), "endTime": int(end_time)}
            data = await self.call("order.getOrderList", body, **creds)
            orders_holder = data if isinstance(data, dict) else {}
            orders = orders_holder.get("orderList") or orders_holder.get("orders") or orders_holder.get("list") or []
            if isinstance(orders, dict):
                orders = orders.get("list") or orders.get("orders") or []
            orders = orders if isinstance(orders, list) else []
            total = 0.0
            units = 0
            for o in orders:
                if not isinstance(o, dict):
                    continue
                total += float(_first_float(o, ("payAmount", "payAmountFen", "amount")) or 0)
                units += _first_int(o, ("itemCount", "quantity", "itemQuantity"))
            n = len(orders)
            return _ok(
                {
                    "sales": round(total, 2),
                    "orders": n,
                    "units": units or n,
                    "avg_order_value": round(total / n, 2) if n else 0.0,
                    "order_items": orders,
                    "currency": "CNY",
                },
                "xiaohongshu",
            )
        except ExternalAPIError as exc:
            logger.warning("小红书订单查询失败: %s", exc)
            return _fail(str(exc), "xiaohongshu")


class XianyuClient(TaobaoTopClient):
    """闲鱼开放平台客户端 — 复用 TOP 协议（网关/MD5 签名/OAuth），业务分类为闲鱼

    官方文档（open.goofish.com/doc/quick-start.html）：
    服务端 TOPAPI 经淘宝开放平台"阿里生态API开发 → 闲鱼垂直行业-B端"申请；
    method 命名空间与权限包以"闲鱼开放平台 API 列表"为准。
    """

    KEY_NAMES = XIANYU_KEY_NAMES
    PROVIDER = "闲鱼开放平台（TOP 生态）"

    async def fetch_prices(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        return _fail(
            "闲鱼 TOP method 名待官方文档核对（设计 §2.3），协议层（网关/MD5/OAuth）已就绪",
            "xianyu",
        )


def get_alibaba1688_client() -> Alibaba1688Client:
    if _cn_client_instances.get("ali1688") is None:
        _cn_client_instances["ali1688"] = Alibaba1688Client()
    return _cn_client_instances["ali1688"]


def get_xiaohongshu_client() -> XiaohongshuClient:
    if _cn_client_instances.get("xiaohongshu") is None:
        _cn_client_instances["xiaohongshu"] = XiaohongshuClient()
    return _cn_client_instances["xiaohongshu"]


def get_xianyu_client() -> XianyuClient:
    if _cn_client_instances.get("xianyu") is None:
        _cn_client_instances["xianyu"] = XianyuClient()
    return _cn_client_instances["xianyu"]


def get_taobao_top_client() -> TaobaoTopClient:
    if _cn_client_instances.get("taobao") is None:
        _cn_client_instances["taobao"] = TaobaoTopClient()
    return _cn_client_instances["taobao"]


def get_jd_open_client() -> JdOpenClient:
    if _cn_client_instances.get("jd") is None:
        _cn_client_instances["jd"] = JdOpenClient()
    return _cn_client_instances["jd"]


def get_pdd_open_client() -> PddOpenClient:
    if _cn_client_instances.get("pdd") is None:
        _cn_client_instances["pdd"] = PddOpenClient()
    return _cn_client_instances["pdd"]


def get_douyin_ecom_client() -> DouyinEcomClient:
    if _cn_client_instances.get("douyin") is None:
        _cn_client_instances["douyin"] = DouyinEcomClient()
    return _cn_client_instances["douyin"]


def get_tiktok_shop_client() -> TikTokShopClient:
    if _cn_client_instances.get("tiktok") is None:
        _cn_client_instances["tiktok"] = TikTokShopClient()
    return _cn_client_instances["tiktok"]


def reset_cn_platform_clients() -> None:
    _cn_client_instances.clear()


# ==================== CommercePlatformClient ====================

class CommercePlatformClient:
    """电商平台数据客户端：价格 / 库存 / 评论 / 报表 / 竞品

    亚马逊路由到 AmazonSPAPIClient（真实 SP-API 流程）；
    淘宝/京东/拼多多/抖店/TikTok Shop 路由到各自开放平台网关客户端；
    其余平台保留通用 REST 调用形态。
    """

    _CN_REVIEW_UNSUPPORTED: Dict[str, str] = {
        "jd": "京东",
        "pdd": "拼多多",
        "douyin-ecom": "抖店",
        "tiktok": "TikTok Shop",
        "ali1688": "1688",
        "xiaohongshu": "小红书",
        "xianyu": "闲鱼",
    }

    def is_available(self, platform: str, api_key: str = "") -> bool:
        platform = str(platform or "").lower()
        if platform == "amazon":
            return get_amazon_sp_client().is_available()
        if platform == "taobao":
            return get_taobao_top_client().is_available()
        if platform == "jd":
            return get_jd_open_client().is_available()
        if platform == "pdd":
            return get_pdd_open_client().is_available()
        if platform == "douyin-ecom":
            return get_douyin_ecom_client().is_available()
        if platform == "tiktok":
            return get_tiktok_shop_client().is_available()
        if platform == "ali1688":
            return get_alibaba1688_client().is_available()
        if platform == "xiaohongshu":
            return get_xiaohongshu_client().is_available()
        if platform == "xianyu":
            return get_xianyu_client().is_available()
        names = COMMERCE_KEY_NAMES.get(platform, [])
        return bool(resolve_api_key(names, api_key))

    def _headers(self, platform: str, api_key: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _amazon_creds(store_creds: Optional["StoreCredentials"]) -> Dict[str, str]:
        """店铺注册表 → 亚马逊 LWA 显式凭据（refresh_token/client_id/client_secret）"""
        if store_creds is None:
            return {}
        return {
            "refresh_token": store_creds.refresh_token or "",
            "client_id": store_creds.app_key or "",
            "client_secret": store_creds.app_secret or "",
        }

    async def fetch_prices(
        self,
        platform: str,
        product_ids: List[str],
        api_key: str = "",
        base_url: str = "",
        marketplace_id: str = "",
        region: str = "na",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        platform = str(platform or "").lower()
        if platform == "amazon":
            return await get_amazon_sp_client().fetch_prices(
                product_ids,
                marketplace_id=marketplace_id,
                region=region,
                **self._amazon_creds(store_creds),
            )
        if platform == "taobao":
            return await get_taobao_top_client().fetch_prices(product_ids, store_id=store_id, store_creds=store_creds)
        if platform == "jd":
            return await get_jd_open_client().fetch_prices(product_ids, store_id=store_id, store_creds=store_creds)
        if platform == "pdd":
            return await get_pdd_open_client().fetch_prices(product_ids, store_id=store_id, store_creds=store_creds)
        if platform == "douyin-ecom":
            return await get_douyin_ecom_client().fetch_prices(product_ids, store_id=store_id, store_creds=store_creds)
        if platform == "tiktok":
            return await get_tiktok_shop_client().fetch_prices(product_ids, store_id=store_id, store_creds=store_creds)
        if platform == "ali1688":
            return await get_alibaba1688_client().fetch_prices(product_ids, store_id=store_id, store_creds=store_creds)
        if platform == "xiaohongshu":
            return await get_xiaohongshu_client().fetch_prices(product_ids, store_id=store_id, store_creds=store_creds)
        if platform == "xianyu":
            return await get_xianyu_client().fetch_prices(product_ids, store_id=store_id, store_creds=store_creds)
        if not self.is_available(platform, api_key):
            return _fail(f"电商平台 '{COMMERCE_PLATFORMS.get(platform, platform)}' 未配置 API Key", platform)
        key = resolve_api_key(COMMERCE_KEY_NAMES.get(platform, []), api_key)
        url = f"{_base_url(platform, base_url)}/prices"
        try:
            data = await _http_get(url, headers=self._headers(platform, key), params={"product_ids": ",".join(product_ids)})
            prices = _extract(data, ["prices", "data"])
            return _ok({"prices": prices if isinstance(prices, dict) else {}, "raw": data}, platform)
        except ExternalAPIError as exc:
            return _fail(str(exc), platform)

    async def fetch_inventory(
        self,
        platform: str,
        skus: List[str],
        api_key: str = "",
        base_url: str = "",
        marketplace_id: str = "",
        region: str = "na",
        seller_id: str = "",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        platform = str(platform or "").lower()
        if platform == "amazon":
            return await get_amazon_sp_client().fetch_inventory(
                skus,
                marketplace_id=marketplace_id,
                region=region,
                seller_id=seller_id,
                **self._amazon_creds(store_creds),
            )
        if platform == "taobao":
            return await get_taobao_top_client().fetch_inventory(skus, store_id=store_id, store_creds=store_creds)
        if platform == "jd":
            return await get_jd_open_client().fetch_inventory(skus, store_id=store_id, store_creds=store_creds)
        if platform == "pdd":
            return await get_pdd_open_client().fetch_inventory(skus, store_id=store_id, store_creds=store_creds)
        if platform == "douyin-ecom":
            return await get_douyin_ecom_client().fetch_inventory(skus, store_id=store_id, store_creds=store_creds)
        if platform == "tiktok":
            return await get_tiktok_shop_client().fetch_inventory(skus, store_id=store_id, store_creds=store_creds)
        if platform == "ali1688":
            return await get_alibaba1688_client().fetch_inventory(skus, store_id=store_id, store_creds=store_creds)
        if platform == "xiaohongshu":
            return await get_xiaohongshu_client().fetch_inventory(skus, store_id=store_id, store_creds=store_creds)
        if platform == "xianyu":
            return await get_xianyu_client().fetch_inventory(skus, store_id=store_id, store_creds=store_creds)
        if not self.is_available(platform, api_key):
            return _fail(f"电商平台 '{COMMERCE_PLATFORMS.get(platform, platform)}' 未配置 API Key", platform)
        key = resolve_api_key(COMMERCE_KEY_NAMES.get(platform, []), api_key)
        url = f"{_base_url(platform, base_url)}/inventory"
        try:
            data = await _http_get(url, headers=self._headers(platform, key), params={"skus": ",".join(skus)})
            inventory = _extract(data, ["inventory", "data"])
            return _ok({"inventory": inventory if isinstance(inventory, dict) else {}, "raw": data}, platform)
        except ExternalAPIError as exc:
            return _fail(str(exc), platform)

    async def fetch_reviews(
        self,
        platform: str,
        product_id: str,
        api_key: str = "",
        base_url: str = "",
        marketplace_id: str = "",
        region: str = "na",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        platform = str(platform or "").lower()
        if platform == "amazon":
            result = await get_amazon_sp_client().fetch_review_topics(
                product_id,
                marketplace_id=marketplace_id,
                region=region,
                **self._amazon_creds(store_creds),
            )
            if result.get("status") != "success":
                return result
            output = result.get("output") or {}
            items: List[Dict[str, Any]] = []
            for idx, topic in enumerate(output.get("negative_topics") or []):
                if isinstance(topic, dict):
                    items.append(
                        {
                            "id": f"topic-neg-{idx}",
                            "topic": topic.get("topic", ""),
                            "content": "; ".join(topic.get("reviewSnippets") or []),
                            "sentiment": "negative",
                            "rating": None,
                        }
                    )
            for idx, topic in enumerate(output.get("positive_topics") or []):
                if isinstance(topic, dict):
                    items.append(
                        {
                            "id": f"topic-pos-{idx}",
                            "topic": topic.get("topic", ""),
                            "content": "; ".join(topic.get("reviewSnippets") or []),
                            "sentiment": "positive",
                            "rating": None,
                        }
                    )
            return _ok(
                {
                    "items": items,
                    "asin": output.get("asin", product_id),
                    "marketplace_id": output.get("marketplace_id", ""),
                    "note": "SP-API Customer Feedback 仅提供评论主题洞察，不支持直接回复提交",
                },
                platform,
            )
        if platform == "taobao":
            return await get_taobao_top_client().fetch_rates(product_id, store_id=store_id, store_creds=store_creds)
        if platform in self._CN_REVIEW_UNSUPPORTED:
            return _fail(
                f"{self._CN_REVIEW_UNSUPPORTED[platform]}开放平台不提供商品评论拉取 API，"
                "请在节点配置中手工粘贴评论",
                platform,
            )
        if not self.is_available(platform, api_key):
            return _fail(f"电商平台 '{COMMERCE_PLATFORMS.get(platform, platform)}' 未配置 API Key", platform)
        key = resolve_api_key(COMMERCE_KEY_NAMES.get(platform, []), api_key)
        url = f"{_base_url(platform, base_url)}/reviews"
        try:
            data = await _http_get(url, headers=self._headers(platform, key), params={"product_id": product_id})
            items = _deep_extract(data, ["items", "reviews"])
            return _ok({"items": items if isinstance(items, list) else [], "raw": data}, platform)
        except ExternalAPIError as exc:
            return _fail(str(exc), platform)

    async def fetch_sales_report(
        self,
        platform: str,
        period: str = "",
        api_key: str = "",
        base_url: str = "",
        report_type: str = "",
        marketplace_id: str = "",
        region: str = "na",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        platform = str(platform or "").lower()
        if platform == "amazon":
            sp_client = get_amazon_sp_client()
            mid = sp_client.resolve_marketplace_id(marketplace_id)
            start, end = _period_to_iso_range(period)
            rt = str(report_type or "").strip() or "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL"
            return await sp_client.fetch_sales_report(
                report_type=rt,
                marketplace_ids=[mid],
                data_start_time=start,
                data_end_time=end,
                region=region,
                **self._amazon_creds(store_creds),
            )
        if platform in ("taobao", "jd", "pdd", "douyin-ecom", "tiktok", "ali1688", "xiaohongshu", "xianyu"):
            start_d, end_d = _period_to_date_range(period)
            if platform == "xiaohongshu":
                start_u = _date_to_unix(start_d)
                end_u = _date_to_unix(end_d, end_of_day=True)
                return await get_xiaohongshu_client().fetch_orders(
                    start_u, end_u, store_id=store_id, store_creds=store_creds
                )
            if platform in ("ali1688", "xianyu"):
                # 1688/闲鱼交易 API method 名与字段待官方文档核对（§2.1/§2.3 待核对项），协议层已就绪
                return _fail(
                    f"{COMMERCE_PLATFORMS.get(platform, platform)}订单 API 名与字段待官方文档核对"
                    "（docs/neurflow-store-connection-design.md）",
                    platform,
                )
            if platform == "taobao":
                return await get_taobao_top_client().fetch_sold_trades(
                    start_created=f"{start_d} 00:00:00",
                    end_created=f"{end_d} 23:59:59",
                    store_id=store_id,
                    store_creds=store_creds,
                )
            if platform == "jd":
                return await get_jd_open_client().fetch_orders(
                    start_date=f"{start_d} 00:00:00",
                    end_date=f"{end_d} 23:59:59",
                    store_id=store_id,
                    store_creds=store_creds,
                )
            start_u = _date_to_unix(start_d)
            end_u = _date_to_unix(end_d, end_of_day=True)
            if platform == "pdd":
                return await get_pdd_open_client().fetch_orders(
                    start_updated_at=start_u,
                    end_updated_at=end_u,
                    store_id=store_id,
                    store_creds=store_creds,
                )
            if platform == "douyin-ecom":
                return await get_douyin_ecom_client().fetch_orders(
                    create_time_start=start_u,
                    create_time_end=end_u,
                    store_id=store_id,
                    store_creds=store_creds,
                )
            return await get_tiktok_shop_client().search_orders(
                create_time_ge=start_u, create_time_lt=end_u + 1, store_id=store_id, store_creds=store_creds
            )
        if not self.is_available(platform, api_key):
            return _fail(f"电商平台 '{COMMERCE_PLATFORMS.get(platform, platform)}' 未配置 API Key", platform)
        key = resolve_api_key(COMMERCE_KEY_NAMES.get(platform, []), api_key)
        url = f"{_base_url(platform, base_url)}/sales-report"
        try:
            data = await _http_get(url, headers=self._headers(platform, key), params={"period": period})
            report = _extract(data, ["report", "data"])
            if isinstance(report, dict):
                return _ok(dict(report), platform)
            return _ok({"raw": data}, platform)
        except ExternalAPIError as exc:
            return _fail(str(exc), platform)

    async def fetch_competitors(
        self,
        platform: str,
        keyword: str,
        api_key: str = "",
        base_url: str = "",
        marketplace_id: str = "",
        region: str = "na",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        platform = str(platform or "").lower()
        if platform == "amazon":
            asins = [k.strip() for k in str(keyword).split(",") if k.strip()]
            return await get_amazon_sp_client().fetch_competitive_prices(
                asins,
                marketplace_id=marketplace_id,
                region=region,
                **self._amazon_creds(store_creds),
            )
        if platform in ("taobao", "jd", "pdd", "douyin-ecom", "tiktok", "ali1688", "xiaohongshu", "xianyu"):
            return _fail(
                f"{COMMERCE_PLATFORMS.get(platform, platform)}开放 API 仅提供自营数据，"
                "不提供竞品数据，请由 LLM 基于竞品清单完成分析",
                platform,
            )
        if not self.is_available(platform, api_key):
            return _fail(f"电商平台 '{COMMERCE_PLATFORMS.get(platform, platform)}' 未配置 API Key", platform)
        key = resolve_api_key(COMMERCE_KEY_NAMES.get(platform, []), api_key)
        url = f"{_base_url(platform, base_url)}/competitors"
        try:
            data = await _http_get(url, headers=self._headers(platform, key), params={"keyword": keyword})
            items = _deep_extract(data, ["items"])
            return _ok({"items": items if isinstance(items, list) else [], "raw": data}, platform)
        except ExternalAPIError as exc:
            return _fail(str(exc), platform)

    async def fetch_ad_metrics(
        self,
        platform: str,
        ad_ids: List[str],
        metrics: List[str],
        api_key: str = "",
        base_url: str = "",
        profile_id: str = "",
        region: str = "na",
    ) -> Dict[str, Any]:
        """获取广告活动投放指标（曝光/点击/转化/花费等）

        亚马逊走独立的 Amazon Ads API（需 profileId）；
        淘宝/京东/拼多多/抖店/TikTok 广告为各自独立广告平台，明确提示后由节点降级；
        其余平台走通用 REST。
        """
        platform = str(platform or "").lower()
        if platform == "amazon":
            from datetime import datetime, timedelta, timezone

            ads_client = get_amazon_ads_client()
            if not ads_client.is_available():
                return _fail(
                    "Amazon Ads API 未配置（需 NEUROVA_AMAZON_ADS_CLIENT_ID / "
                    "NEUROVA_AMAZON_ADS_CLIENT_SECRET 与 profileId）",
                    platform,
                )
            today = datetime.now(timezone.utc).date()
            start_date = (today - timedelta(days=7)).isoformat()
            end_date = today.isoformat()
            return await ads_client.fetch_campaign_metrics(
                campaign_ids=ad_ids,
                metrics=metrics,
                start_date=start_date,
                end_date=end_date,
                profile_id=profile_id,
                region=region,
            )
        if platform in CN_AD_PLATFORM_HINTS:
            return _fail(
                f"{COMMERCE_PLATFORMS.get(platform, platform)}广告需接入独立广告平台："
                f"{CN_AD_PLATFORM_HINTS[platform]}，与电商开放网关凭据不互通",
                platform,
            )
        if not self.is_available(platform, api_key):
            return _fail(f"电商平台 '{COMMERCE_PLATFORMS.get(platform, platform)}' 未配置 API Key", platform)
        key = resolve_api_key(COMMERCE_KEY_NAMES.get(platform, []), api_key)
        url = f"{_base_url(platform, base_url)}/ad-metrics"
        try:
            data = await _http_get(
                url,
                headers=self._headers(platform, key),
                params={"ad_ids": ",".join(ad_ids), "metrics": ",".join(metrics)},
            )
            items = _deep_extract(data, ["items", "metrics"])
            return _ok({"items": items if isinstance(items, list) else [], "raw": data}, platform)
        except ExternalAPIError as exc:
            return _fail(str(exc), platform)


_commerce_instance: Optional[CommercePlatformClient] = None


def get_commerce_platform_client() -> CommercePlatformClient:
    global _commerce_instance
    if _commerce_instance is None:
        _commerce_instance = CommercePlatformClient()
    return _commerce_instance


def reset_commerce_platform_client() -> None:
    global _commerce_instance
    _commerce_instance = None


# ==================== PublishPlatformClient ====================

class PublishPlatformClient:
    """视频发布客户端：上传并发布到短视频平台"""

    def is_available(self, platform: str, access_token: str = "") -> bool:
        platform = str(platform or "").lower()
        names = PUBLISH_KEY_NAMES.get(platform, [])
        return bool(resolve_api_key(names, access_token))

    async def publish(
        self,
        platform: str,
        video_url: str,
        title: str,
        tags: Optional[List[str]] = None,
        access_token: str = "",
        cover_url: str = "",
        description: str = "",
        base_url: str = "",
    ) -> Dict[str, Any]:
        platform = str(platform or "").lower()
        if platform not in PUBLISH_PLATFORMS:
            return _fail(f"不支持的发布平台: {platform}", platform)
        if not self.is_available(platform, access_token):
            return _fail(f"发布平台 '{PUBLISH_PLATFORMS[platform]}' 未配置 access_token", platform)
        token = resolve_api_key(PUBLISH_KEY_NAMES.get(platform, []), access_token)
        url = f"{_base_url(platform, base_url)}/video/publish"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {
            "video_url": video_url,
            "title": title,
            "tags": tags or [],
            "cover_url": cover_url,
            "description": description,
        }
        try:
            data = await _http_post(url, headers=headers, json=body)
            item_id = _extract(data, ["item_id", "video_id", "id"])
            published_url = _extract(data, ["url", "share_url", "item_url"])
            if not published_url and item_id:
                published_url = f"https://www.{platform}.com/video/{item_id}"
            return _ok({"item_id": item_id, "url": published_url, "raw": data}, platform)
        except ExternalAPIError as exc:
            return _fail(str(exc), platform)


_publish_instance: Optional[PublishPlatformClient] = None


def get_publish_platform_client() -> PublishPlatformClient:
    global _publish_instance
    if _publish_instance is None:
        _publish_instance = PublishPlatformClient()
    return _publish_instance


def reset_publish_platform_client() -> None:
    global _publish_instance
    _publish_instance = None
