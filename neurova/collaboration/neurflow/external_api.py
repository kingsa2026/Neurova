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












_cn_client_instances: Dict[str, Any] = {}


# ==================== 三平台客户端（1688 / 小红书 / 闲鱼） ====================
# 协议依据 §2.1-2.3（2026-08-29 复核）：
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


# Bases, constants and shared state must be ready before importing leaf clients.
from .external_clients.image import ImageGenClient  # noqa: E402
from .external_clients.video import VideoGenClient  # noqa: E402
from .external_clients.amazon_sp import AmazonSPAPIClient  # noqa: E402
from .external_clients.amazon_ads import AmazonAdsClient  # noqa: E402
from .external_clients.taobao import TaobaoTopClient, XianyuClient  # noqa: E402
from .external_clients.jd import JdOpenClient  # noqa: E402
from .external_clients.pdd import PddOpenClient  # noqa: E402
from .external_clients.douyin import DouyinEcomClient  # noqa: E402
from .external_clients.tiktok import TikTokShopClient  # noqa: E402
from .external_clients.alibaba1688 import Alibaba1688Client  # noqa: E402
from .external_clients.xiaohongshu import XiaohongshuClient  # noqa: E402
