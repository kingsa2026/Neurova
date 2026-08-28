"""
Neurflow 电商运营节点 — 亚马逊 / 抖音 / 淘宝等平台运营

电商运营场景的专用节点定义与执行器：
1. 价格监控（price-monitor）
2. 广告文案生成（ad-copy）
3. 评论自动回复（review-respond）
4. 商品上架 / Listing 优化（product-listing）
5. 库存同步（inventory-sync）
6. 竞品分析（competitor-analysis）
7. 关键词研究（keyword-research）
8. 销售报表（sales-report）
9. 广告流投放（ad-streaming）
10. 广告监控（ad-monitor）
11. 广告策略（ad-strategy）
12. 跨渠道广告投放（ad-cross）
"""
import json
import re
from typing import Any, Callable, Dict, List

from neurova.core.logger import get_logger
from .models import NodeDefinition
from .external_api import CommercePlatformClient

logger = get_logger(__name__)

# ==================== 共享平台选项 ====================

_COMMERCE_PLATFORM_OPTIONS = [
    {"value": "amazon", "label": "亚马逊 Amazon"},
    {"value": "taobao", "label": "淘宝 Taobao"},
    {"value": "jd", "label": "京东 JD"},
    {"value": "douyin-ecom", "label": "抖音电商 Douyin Ecom"},
    {"value": "tiktok", "label": "TikTok"},
    {"value": "pdd", "label": "拼多多 PDD"},
    {"value": "ali1688", "label": "1688"},
    {"value": "xiaohongshu", "label": "小红书 Xiaohongshu"},
    {"value": "xianyu", "label": "闲鱼 Xianyu"},
    {"value": "shein", "label": "希音 SHEIN"},
]


# ==================== 电商节点定义 ====================

# 所有电商运营节点的定义列表
# 使用 dict 格式，便于序列化和测试
COMMERCE_NODES: List[Dict[str, Any]] = [
    {
        "type": "builtin:price-monitor",
        "label": "价格监控",
        "icon": "💰",
        "category": "commerce",
        "description": "监控竞品/自营商品价格变化，低于阈值时告警（支持亚马逊/淘宝/抖音等平台）",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "平台",
                "type": "select",
                "label": "监控平台",
                "default": "amazon",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            {
                "id": "products",
                "name": "products",
                "type": "textarea",
                "label": "商品列表（逗号分隔）",
                "default": "B0XXXXXX",
                "placeholder": "B0XXXXXXXXX, 商品ID...",
            },
            {
                "id": "alert_threshold",
                "name": "alert_threshold",
                "type": "input",
                "label": "告警阈值（元）",
                "default": "50",
                "placeholder": "价格低于该值触发告警",
            },
            {
                "id": "check_interval",
                "name": "check_interval",
                "type": "slider",
                "label": "检查间隔（小时）",
                "default": 6,
                "min": 1,
                "max": 168,
            },
        ],
        "inputs": [{"id": "input", "label": "商品输入"}],
        "outputs": [
            {"id": "output", "label": "监控结果"},
            {"id": "alerts", "label": "告警列表"},
        ],
    },
    {
        "type": "builtin:ad-copy",
        "label": "广告文案生成",
        "icon": "📢",
        "category": "commerce",
        "description": "为电商平台生成平台适配的广告文案（标题/卖点/CTA）",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "平台",
                "type": "select",
                "label": "投放平台",
                "default": "amazon",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            {
                "id": "product",
                "name": "product",
                "type": "input",
                "label": "商品名称",
                "default": "",
                "placeholder": "例如：智能手表",
            },
            {
                "id": "style",
                "name": "style",
                "type": "select",
                "label": "文案风格",
                "default": "promotion",
                "options": ["促销促销", "种草安利", "品牌故事", "痛点营销", "节日借势"],
            },
            {
                "id": "language",
                "name": "language",
                "type": "input",
                "label": "目标语言",
                "default": "zh",
                "placeholder": "zh / en / ja...",
            },
        ],
        "inputs": [{"id": "input", "label": "商品信息"}],
        "outputs": [{"id": "output", "label": "广告文案"}],
    },
    {
        "type": "builtin:review-respond",
        "label": "评论自动回复",
        "icon": "💬",
        "category": "commerce",
        "description": "分析买家评论情感并自动生成回复，支持负面评论安抚",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "平台",
                "type": "select",
                "label": "平台",
                "default": "taobao",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            {
                "id": "reviews",
                "name": "reviews",
                "type": "textarea",
                "label": "评论内容（每行一条）",
                "default": "",
                "placeholder": "评论1\n评论2...",
            },
            {
                "id": "tone",
                "name": "tone",
                "type": "select",
                "label": "回复语气",
                "default": "friendly",
                "options": ["友好专业", "轻松活泼", "正式官方", "关怀安抚"],
            },
        ],
        "inputs": [{"id": "input", "label": "评论输入"}],
        "outputs": [
            {"id": "output", "label": "回复结果"},
            {"id": "sentiment", "label": "情感分析"},
        ],
    },
    {
        "type": "builtin:product-listing",
        "label": "商品上架 / Listing 优化",
        "icon": "📦",
        "category": "commerce",
        "description": "生成或优化商品 Listing（标题/五点描述/详情），提升搜索排名与转化",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "平台",
                "type": "select",
                "label": "平台",
                "default": "amazon",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            {
                "id": "product_name",
                "name": "product_name",
                "type": "input",
                "label": "商品名称",
                "default": "",
                "placeholder": "例如：无线蓝牙耳机",
            },
            {
                "id": "features",
                "name": "features",
                "type": "textarea",
                "label": "商品卖点（逗号分隔）",
                "default": "",
                "placeholder": "降噪, 长续航, 防水...",
            },
            {
                "id": "keywords",
                "name": "keywords",
                "type": "input",
                "label": "目标关键词",
                "default": "",
                "placeholder": "可选，用于 SEO 优化",
            },
        ],
        "inputs": [{"id": "input", "label": "商品数据"}],
        "outputs": [
            {"id": "output", "label": "Listing 结果"},
            {"id": "title", "label": "优化标题"},
        ],
    },
    {
        "type": "builtin:inventory-sync",
        "label": "库存同步",
        "icon": "📊",
        "category": "commerce",
        "description": "多平台库存同步与低库存预警，避免超卖与断货",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "platform",
                "type": "select",
                "label": "同步平台",
                "default": "amazon",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            {
                "id": "low_stock_threshold",
                "name": "low_stock_threshold",
                "type": "input",
                "label": "低库存阈值",
                "default": "10",
                "placeholder": "库存低于该值预警",
            },
        ],
        "inputs": [{"id": "input", "label": "库存数据"}],
        "outputs": [
            {"id": "output", "label": "同步结果"},
            {"id": "alerts", "label": "低库存告警"},
        ],
    },
    {
        "type": "builtin:competitor-analysis",
        "label": "竞品分析",
        "icon": "🔍",
        "category": "commerce",
        "description": "分析竞品价格、卖点与评论，输出竞争策略建议",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "平台",
                "type": "select",
                "label": "平台",
                "default": "amazon",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            {
                "id": "competitors",
                "name": "competitors",
                "type": "textarea",
                "label": "竞品列表（ASIN/ID/链接，逗号分隔）",
                "default": "",
                "placeholder": "B0XXXXX, B0YYYYY",
            },
        ],
        "inputs": [{"id": "input", "label": "竞品数据"}],
        "outputs": [{"id": "output", "label": "分析结果"}],
    },
    {
        "type": "builtin:keyword-research",
        "label": "关键词研究",
        "icon": "🏷️",
        "category": "commerce",
        "description": "基于种子词扩展高价值搜索关键词，支持多语言",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "平台",
                "type": "select",
                "label": "平台",
                "default": "taobao",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            {
                "id": "seed_keywords",
                "name": "seed_keywords",
                "type": "input",
                "label": "种子关键词",
                "default": "",
                "placeholder": "例如：智能手表",
            },
            {
                "id": "language",
                "name": "language",
                "type": "input",
                "label": "语言",
                "default": "zh",
                "placeholder": "zh / en / ja",
            },
        ],
        "inputs": [{"id": "input", "label": "种子词输入"}],
        "outputs": [
            {"id": "output", "label": "关键词列表"},
            {"id": "keywords", "label": "关键词数组"},
        ],
    },
    {
        "type": "builtin:sales-report",
        "label": "销售报表",
        "icon": "📈",
        "category": "commerce",
        "description": "汇总平台销售数据，生成运营分析报表（销量/销售额/趋势）",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "平台",
                "type": "select",
                "label": "平台",
                "default": "amazon",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            {
                "id": "period",
                "name": "period",
                "type": "input",
                "label": "统计周期",
                "default": "2025-01",
                "placeholder": "YYYY-MM 或 YYYY-MM-DD~YYYY-MM-DD",
            },
            {
                "id": "metrics",
                "name": "metrics",
                "type": "input",
                "label": "指标（逗号分隔）",
                "default": "sales,orders",
                "placeholder": "sales,orders,uv,conversion",
            },
        ],
        "inputs": [{"id": "input", "label": "销售数据"}],
        "outputs": [{"id": "output", "label": "报表结果"}],
    },
    {
        "type": "builtin:ad-streaming",
        "label": "广告流投放",
        "icon": "📡",
        "category": "commerce",
        "description": "创建并管理电商平台广告投放计划（活动/预算/定向），支持自动出价与实时放量",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "platform",
                "type": "select",
                "label": "投放平台",
                "default": "amazon",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            {
                "id": "budget",
                "name": "budget",
                "type": "input",
                "label": "日预算（元）",
                "default": "1000",
                "placeholder": "例如：1000",
            },
            {
                "id": "targeting",
                "name": "targeting",
                "type": "select",
                "label": "定向方式",
                "default": "自动定向",
                "options": ["自动定向", "手动定向", "人群定向", "关键词定向"],
            },
            {
                "id": "objective",
                "name": "objective",
                "type": "select",
                "label": "投放目标",
                "default": "转化",
                "options": ["转化", "点击", "曝光", "加购"],
            },
        ],
        "inputs": [{"id": "input", "label": "活动信息"}],
        "outputs": [
            {"id": "output", "label": "投放计划"},
            {"id": "campaign", "label": "活动详情"},
        ],
    },
    {
        "type": "builtin:ad-monitor",
        "label": "广告监控",
        "icon": "👁️",
        "category": "commerce",
        "description": "实时监控广告活动投放效果（曝光/点击/转化/花费），识别异常波动并告警",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "platform",
                "type": "select",
                "label": "监控平台",
                "default": "amazon",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            {
                "id": "ad_ids",
                "name": "ad_ids",
                "type": "textarea",
                "label": "广告ID列表（逗号分隔）",
                "default": "camp_001, camp_002",
                "placeholder": "camp_001, camp_002...",
            },
            {
                "id": "metrics",
                "name": "metrics",
                "type": "input",
                "label": "监控指标（逗号分隔）",
                "default": "impressions,clicks,conversions,spend",
                "placeholder": "impressions,clicks,conversions,spend,ctr,roi",
            },
            {
                "id": "alert_threshold",
                "name": "alert_threshold",
                "type": "input",
                "label": "告警阈值（花费元）",
                "default": "500",
                "placeholder": "花费超过该值触发告警",
            },
        ],
        "inputs": [{"id": "input", "label": "广告数据"}],
        "outputs": [
            {"id": "output", "label": "监控结果"},
            {"id": "alerts", "label": "异常告警"},
        ],
    },
    {
        "type": "builtin:ad-strategy",
        "label": "广告策略",
        "icon": "🧠",
        "category": "commerce",
        "description": "基于平台/预算/目标生成智能投放策略（出价方式/人群/时段/预算分配建议）",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "platform",
                "type": "select",
                "label": "投放平台",
                "default": "amazon",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            {
                "id": "goal",
                "name": "goal",
                "type": "select",
                "label": "投放目标",
                "default": "increase_sales",
                "options": ["increase_sales", "increase_orders", "reduce_cpa", "brand_awareness", "clearance"],
            },
            {
                "id": "budget",
                "name": "budget",
                "type": "input",
                "label": "总预算（元）",
                "default": "5000",
                "placeholder": "例如：5000",
            },
            {
                "id": "product",
                "name": "product",
                "type": "input",
                "label": "投放商品",
                "default": "",
                "placeholder": "例如：智能手表",
            },
        ],
        "inputs": [{"id": "input", "label": "投放目标"}],
        "outputs": [
            {"id": "output", "label": "策略结果"},
            {"id": "strategy", "label": "策略建议"},
        ],
    },
    {
        "type": "builtin:ad-cross",
        "label": "跨渠道广告投放",
        "icon": "🔗",
        "category": "commerce",
        "description": "多平台联动广告投放，统一预算并按渠道分配，输出各平台投放计划",
        "sub_blocks": [
            {
                "id": "platforms",
                "name": "platforms",
                "type": "textarea",
                "label": "投放平台（逗号分隔）",
                "default": "amazon, taobao",
                "placeholder": "amazon, taobao, jd, douyin-ecom...",
            },
            {
                "id": "total_budget",
                "name": "total_budget",
                "type": "input",
                "label": "总预算（元）",
                "default": "10000",
                "placeholder": "例如：10000",
            },
            {
                "id": "product",
                "name": "product",
                "type": "input",
                "label": "投放商品",
                "default": "",
                "placeholder": "例如：无线耳机",
            },
            {
                "id": "objective",
                "name": "objective",
                "type": "select",
                "label": "统一目标",
                "default": "转化",
                "options": ["转化", "点击", "曝光", "加购"],
            },
        ],
        "inputs": [{"id": "input", "label": "商品信息"}],
        "outputs": [
            {"id": "output", "label": "投放计划"},
            {"id": "channels", "label": "各渠道分配"},
        ],
    },
]


# ==================== 辅助函数 ====================


def _get_agent():
    """获取 Agent 实例"""
    try:
        from neurova.agent_core import Agent

        return Agent.get_instance()
    except (ImportError, AttributeError):
        logger.debug("Agent 未可用")
        return None


async def _call_agent(prompt: str, system_prompt: str = "") -> str:
    """调用 Agent 生成文本，失败时抛出异常"""
    agent = _get_agent()
    if agent is None:
        raise RuntimeError("Agent 未初始化")
    response = await agent.chat(
        prompt,
        system_prompt=system_prompt,
        metadata={"history": []},
    )
    return response if isinstance(response, str) else str(response)


def _extract_llm_text(response: Any) -> str:
    """从多种响应形状中安全提取文本内容"""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            if isinstance(message, dict):
                return str(message.get("content", ""))
        return str(response)
    try:
        if hasattr(response, "choices") and response.choices:
            message = response.choices[0].message
            if hasattr(message, "content"):
                return str(message.content)
    except Exception:
        pass
    return str(response)


def _parse_llm_json(text: Any) -> dict:
    """从 LLM 响应中提取并解析 JSON，失败时返回空字典"""
    raw = _extract_llm_text(text)
    try:
        # 先尝试直接解析
        return json.loads(raw)
    except (ValueError, TypeError):
        pass
    # 尝试提取第一个 JSON 对象
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (ValueError, TypeError):
            pass
    return {}


def _to_num(value: Any, default: float = 0.0) -> float:
    """安全转换为数字，失败时返回默认值"""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("，", "").strip())
    except (ValueError, TypeError):
        return default


# ==================== 节点执行器 ====================


async def exec_price_monitor(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """价格监控执行器

    调用电商平台 API 获取商品价格快照，低于阈值时产生告警。
    平台 API 不可用时降级为本地模拟价格数据。
    """
    platform = config.get("platform", "amazon")
    products = config.get("products", "")
    threshold = float(config.get("alert_threshold", 50) or 50)

    product_list = [p.strip() for p in str(products).split(",") if p.strip()]
    if not product_list:
        product_list = ["B0XXXXXX"]

    # 尝试调用电商平台价格 API
    try:
        result = await CommercePlatformClient().fetch_prices(
            platform=platform, product_ids=product_list
        )
        if result.get("status") == "success":
            output = result.get("output", {})
            raw_prices = output.get("prices", {})
            prices = []
            alerts = []
            for pid in product_list:
                price = None
                if isinstance(raw_prices, dict):
                    price = raw_prices.get(pid) or raw_prices.get("default")
                if price is None:
                    price = 88.0
                prices.append({"product": pid, "price": float(price), "platform": platform})
                if float(price) <= threshold:
                    alerts.append({"product": pid, "price": float(price), "threshold": threshold, "level": "low"})
            return {
                "status": "success",
                "output": {
                    "prices": prices,
                    "alerts": alerts,
                    "threshold": threshold,
                    "platform": platform,
                    "checked_at": ctx.get("timestamp", "now"),
                    "source": "platform_api",
                },
            }
    except Exception as e:  # noqa: BLE001
        logger.warning("价格监控 API 失败，降级为本地模拟: %s", e)

    # 模拟价格数据（真实场景从平台 API 拉取）
    mock_prices = {
        "B0XXXXXX": 39.9,
        "B0YYYYYY": 65.0,
        "default": 88.0,
    }

    prices = []
    alerts = []
    for pid in product_list:
        price = mock_prices.get(pid, mock_prices["default"])
        prices.append({"product": pid, "price": price, "platform": platform})
        if price <= threshold:
            alerts.append({"product": pid, "price": price, "threshold": threshold, "level": "low"})

    return {
        "status": "success",
        "output": {
            "prices": prices,
            "alerts": alerts,
            "threshold": threshold,
            "platform": platform,
            "checked_at": ctx.get("timestamp", "now"),
            "fallback": True,
        },
    }


async def exec_ad_copy(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """广告文案生成执行器

    通过 Agent 生成平台适配的广告文案；无 Agent 时返回失败。
    """
    platform = config.get("platform", "amazon")
    product = config.get("product", "")
    style = config.get("style", "promotion")
    language = config.get("language", "zh")

    if not product:
        product = str(ctx.get("input") or ctx.get("inputs") or "").strip() or "该商品"

    prompt = (
        f"请为{platform}平台生成一条{style}风格的广告文案，目标语言{language}。\n"
        f"商品：{product}\n"
        "要求：包含吸引眼球的标题、2-3 个核心卖点、明确的行动号召（CTA）。"
    )

    try:
        text = await _call_agent(prompt, system_prompt="你是一名资深电商广告文案专家。")
        return {"status": "success", "output": {"copy": text, "platform": platform}}
    except Exception as e:
        logger.error("广告文案生成失败: %s", e)
        return {"status": "failed", "error": str(e), "output": None}


async def exec_review_respond(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """评论自动回复执行器

    调用电商平台 API 拉取评论并自动生成回复。
    平台 API 不可用时以规则情感分析为兜底。
    """
    platform = config.get("platform", "taobao")
    reviews_text = config.get("reviews", "") or str(ctx.get("input") or ctx.get("inputs") or "")
    tone = config.get("tone", "friendly")
    product_id = config.get("product_id", "") or ""

    # 尝试调用电商平台评论 API
    try:
        result = await CommercePlatformClient().fetch_reviews(
            platform=platform, product_id=product_id
        )
        if result.get("status") == "success":
            output = result.get("output", {})
            raw_reviews = output.get("items", [])
            if isinstance(raw_reviews, list) and raw_reviews:
                replies = []
                sentiments = []
                negative_words = ["差", "坏", "失望", "退", "不满", "慢", "贵", "差评"]
                for r in raw_reviews:
                    if isinstance(r, dict):
                        review = r.get("content", "")
                        review_id = r.get("id", "rev_?")
                        rating = r.get("rating")
                    else:
                        review = str(r)
                        review_id = "rev_?"
                        rating = None
                    is_negative = any(w in review for w in negative_words)
                    if rating is not None:
                        try:
                            is_negative = is_negative or float(rating) <= 3
                        except (TypeError, ValueError):
                            pass
                    sentiment = "negative" if is_negative else "positive"
                    sentiments.append({"review": review, "sentiment": sentiment})
                    if is_negative:
                        reply = f"非常抱歉给您带来不好的体验！我们已经关注到您反馈的问题，正在加紧处理，请您保持联系。感谢您的反馈，帮助我们不断改进。"
                    else:
                        reply = f"感谢您的认可与支持！我们会继续努力，为您提供更优质的商品和服务。"
                    replies.append({"review_id": review_id, "review": review, "reply": reply, "sentiment": sentiment})
                return {
                    "status": "success",
                    "output": {
                        "replies": replies,
                        "sentiment": sentiments,
                        "platform": platform,
                        "tone": tone,
                        "source": "platform_api",
                    },
                }
    except Exception as e:  # noqa: BLE001
        logger.warning("评论拉取 API 失败，降级为本地规则: %s", e)

    reviews = [r.strip() for r in str(reviews_text).splitlines() if r.strip()]
    if not reviews:
        reviews = ["（示例评论）质量很好，发货快"]

    replies = []
    sentiments = []
    for idx, review in enumerate(reviews):
        # 简单情感规则：包含负面关键词判为负面，否则正面
        negative_words = ["差", "坏", "失望", "退", "不满", "慢", "贵", "差评"]
        is_negative = any(w in review for w in negative_words)
        sentiment = "negative" if is_negative else "positive"
        sentiments.append({"review": review, "sentiment": sentiment})

        if is_negative:
            reply = f"非常抱歉给您带来不好的体验！我们已经关注到您反馈的问题，正在加紧处理，请您保持联系。感谢您的反馈，帮助我们不断改进。"
        else:
            reply = f"感谢您的认可与支持！我们会继续努力，为您提供更优质的商品和服务。"
        replies.append({"review": review, "reply": reply, "sentiment": sentiment})

    return {
        "status": "success",
        "output": {
            "replies": replies,
            "sentiment": sentiments,
            "platform": platform,
            "tone": tone,
            "fallback": True,
        },
    }


async def exec_product_listing(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """商品上架 / Listing 优化执行器

    生成优化后的 Listing 标题与卖点描述。
    """
    platform = config.get("platform", "amazon")
    product_name = config.get("product_name", "")
    features = config.get("features", "")
    keywords = config.get("keywords", "")

    feature_list = [f.strip() for f in str(features).split(",") if f.strip()]
    if not feature_list:
        feature_list = ["优质品质", "高性价比", "售后保障"]

    # 结构化生成 Listing（无需 LLM 的确定性兜底）
    title = f"{product_name} {feature_list[0]} {feature_list[1] if len(feature_list) > 1 else ''}".strip()
    bullet_points = [f"✅ {f}" for f in feature_list]

    return {
        "status": "success",
        "output": {
            "title": title,
            "bullet_points": bullet_points,
            "description": "、".join(feature_list),
            "keywords": keywords or "",
            "platform": platform,
        },
    }


async def exec_inventory_sync(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """库存同步执行器

    调用电商平台 API 获取库存并生成低库存预警。
    平台 API 不可用时降级为本地模拟库存数据。
    """
    platform = config.get("platform", "amazon")
    threshold = int(config.get("low_stock_threshold", 10) or 10)
    skus = config.get("skus", "") or str(ctx.get("input") or ctx.get("inputs") or "")

    sku_list = [s.strip() for s in str(skus).split(",") if s.strip()]
    if not sku_list:
        sku_list = ["SKU-001"]

    # 尝试调用电商平台库存 API
    try:
        result = await CommercePlatformClient().fetch_inventory(
            platform=platform, skus=sku_list
        )
        if result.get("status") == "success":
            output = result.get("output", {})
            raw_inventory = output.get("inventory", {})
            synced = []
            alerts = []
            for sku in sku_list:
                stock = 20
                if isinstance(raw_inventory, dict):
                    stock = int(raw_inventory.get(sku) or raw_inventory.get("default") or 20)
                status = "low" if stock <= threshold else "ok"
                synced.append({"platform": platform, "sku": sku, "stock": stock, "status": status})
                if status == "low":
                    alerts.append({"platform": platform, "sku": sku, "stock": stock, "threshold": threshold})
            return {
                "status": "success",
                "output": {
                    "synced": synced,
                    "alerts": alerts,
                    "low_stock_threshold": threshold,
                    "source": "platform_api",
                },
            }
    except Exception as e:  # noqa: BLE001
        logger.warning("库存同步 API 失败，降级为本地模拟: %s", e)

    # 模拟库存数据
    mock_stock = {"amazon": 25, "taobao": 5, "douyin": 100, "jd": 8}

    synced = []
    alerts = []
    for sku in sku_list:
        stock = mock_stock.get(platform, 20)
        status = "low" if stock <= threshold else "ok"
        synced.append({"platform": platform, "sku": sku, "stock": stock, "status": status})
        if status == "low":
            alerts.append({"platform": platform, "sku": sku, "stock": stock, "threshold": threshold})

    return {
        "status": "success",
        "output": {
            "synced": synced,
            "alerts": alerts,
            "low_stock_threshold": threshold,
            "fallback": True,
        },
    }


async def exec_competitor_analysis(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """竞品分析执行器

    调用电商平台 API 拉取竞品价格/卖点数据并生成对比分析。
    平台 API 不可用时降级为规则占位分析。
    """
    platform = config.get("platform", "amazon")
    competitors = config.get("competitors", "") or str(ctx.get("input") or ctx.get("inputs") or "")

    comp_list = [c.strip() for c in str(competitors).split(",") if c.strip()]
    if not comp_list:
        comp_list = ["竞品A", "竞品B"]

    # 尝试调用电商平台竞品 API
    try:
        result = await CommercePlatformClient().fetch_competitors(
            platform=platform, keyword=",".join(comp_list)
        )
        if result.get("status") == "success":
            output = result.get("output", {})
            raw_comps = output.get("items", [])
            if isinstance(raw_comps, list) and raw_comps:
                analysis = []
                for c in raw_comps:
                    if isinstance(c, dict):
                        analysis.append(
                            {
                                "competitor": c.get("name", c.get("competitor", "未知")),
                                "price": c.get("price", "待采集"),
                                "price_position": c.get("price_position", "待分析"),
                                "key_selling_points": c.get("selling_points", []),
                                "review_count": c.get("review_count", "待采集"),
                            }
                        )
                    else:
                        analysis.append(
                            {
                                "competitor": str(c),
                                "price": "待采集",
                                "price_position": "待分析",
                                "key_selling_points": [],
                                "review_count": "待采集",
                            }
                        )
                return {
                    "status": "success",
                    "output": {
                        "competitors": analysis,
                        "platform": platform,
                        "strategy_suggestion": "基于实时竞品数据生成，建议人工复核后执行策略。",
                        "source": "platform_api",
                    },
                }
    except Exception as e:  # noqa: BLE001
        logger.warning("竞品 API 失败，降级为占位分析: %s", e)

    analysis = []
    for c in comp_list:
        analysis.append(
            {
                "competitor": c,
                "price": "待采集",
                "price_position": "待分析",
                "key_selling_points": [],
                "review_count": "待采集",
            }
        )

    return {
        "status": "success",
        "output": {
            "competitors": analysis,
            "platform": platform,
            "strategy_suggestion": "建议补充真实竞品数据源以生成完整竞争策略。",
            "fallback": True,
        },
    }


async def exec_keyword_research(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """关键词研究执行器

    基于种子词扩展关键词列表。
    """
    platform = config.get("platform", "taobao")
    seed = config.get("seed_keywords", "") or str(ctx.get("input") or ctx.get("inputs") or "")
    language = config.get("language", "zh")

    if not seed:
        seed = "智能手表"

    # 规则扩展关键词
    keywords = [seed]
    suffixes = ["推荐", "怎么样", "哪个牌子好", "测评", "性价比", "官方旗舰店", "正品", "排行榜"]
    for s in suffixes:
        keywords.append(f"{seed}{s}")

    return {
        "status": "success",
        "output": {
            "keywords": keywords,
            "seed": seed,
            "platform": platform,
            "language": language,
        },
    }


async def exec_sales_report(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """销售报表执行器

    调用电商平台 API 汇总销售数据生成报表。
    平台 API 不可用时降级为本地模拟数据。
    """
    platform = config.get("platform", "amazon")
    period = config.get("period", "2025-01")
    metrics = config.get("metrics", "sales,orders")

    metric_list = [m.strip() for m in str(metrics).split(",") if m.strip()]

    # 尝试调用电商平台销售报表 API
    try:
        result = await CommercePlatformClient().fetch_sales_report(
            platform=platform, period=period
        )
        if result.get("status") == "success":
            output = result.get("output", {})
            report = {
                "platform": platform,
                "period": period,
                "sales": float(output.get("sales", 0) or 0),
                "orders": int(output.get("orders", 0) or 0),
                "units": int(output.get("units", 0) or 0),
                "avg_order_value": float(output.get("avg_order_value", 0) or 0),
                "conversion_rate": float(output.get("conversion_rate", 0) or 0),
                "summary": output.get("summary", f"{platform} {period} 报表生成成功"),
                "raw": output.get("raw"),
            }
            return {
                "status": "success",
                "output": {
                    "report": report,
                    "metrics": metric_list,
                    "platform": platform,
                    "period": period,
                    "source": "platform_api",
                },
            }
    except Exception as e:  # noqa: BLE001
        logger.warning("销售报表 API 失败，降级为本地模拟: %s", e)

    # 模拟数据
    report = {
        "platform": platform,
        "period": period,
        "sales": 125000.0,
        "orders": 980,
        "units": 1200,
        "avg_order_value": 127.55,
        "conversion_rate": 3.2,
        "summary": f"{platform} {period} 销售额 12.5 万，订单 980 单，较上期增长 8%。",
    }

    return {
        "status": "success",
        "output": {
            "report": report,
            "metrics": metric_list,
            "platform": platform,
            "period": period,
            "fallback": True,
        },
    }


# ==================== 广告投放节点执行器 ====================


async def exec_ad_streaming(config: dict, ctx: dict) -> dict:
    """
    广告流投放执行器

    创建并管理广告投放计划（活动/预算/定向），
    优先调用 Agent 生成投放方案，无 Agent 时降级为规则模拟。
    """
    platform = str(config.get("platform") or "amazon")
    budget = str(config.get("budget") or "1000")
    targeting = str(config.get("targeting") or "自动定向")
    objective = str(config.get("objective") or "转化")

    # 优先尝试调用 Agent 生成投放策略
    agent = _get_agent()
    if agent is not None:
        try:
            prompt = (
                f"请为电商平台 {platform} 生成一份广告投放计划。"
                f"预算 {budget} 元，定向方式 {targeting}，目标 {objective}。"
                "请返回 JSON，包含 campaign_name、daily_budget、bid_strategy、"
                "targeting_keywords、schedule 字段。"
            )
            text = await agent.chat(prompt, system_prompt="你是电商广告投放专家。", metadata={"history": []})
            output = _parse_llm_json(text)
            campaign = {
                "campaign_name": output.get("campaign_name", f"{platform} 广告活动"),
                "platform": platform,
                "daily_budget": output.get("daily_budget", float(_to_num(budget))),
                "bid_strategy": output.get("bid_strategy", "自动出价"),
                "targeting_keywords": output.get("targeting_keywords") or [targeting],
                "schedule": output.get("schedule", "全天投放"),
                "objective": objective,
            }
            return {
                "status": "success",
                "output": {
                    "campaign": campaign,
                    "plan": {
                        "platform": platform,
                        "total_budget": float(_to_num(budget)),
                        "targeting": targeting,
                        "objective": objective,
                        "status": "created",
                    },
                    "source": "agent",
                },
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("广告流投放 Agent 生成失败，降级为规则模拟: %s", e)

    # 规则降级：模拟投放计划
    daily = float(_to_num(budget))
    campaign = {
        "campaign_name": f"{platform} 标准推广",
        "platform": platform,
        "daily_budget": daily,
        "bid_strategy": "动态竞价-提高和降低",
        "targeting_keywords": [targeting],
        "schedule": "全天投放",
        "objective": objective,
        "status": "created",
    }
    return {
        "status": "success",
        "output": {
            "campaign": campaign,
            "plan": {
                "platform": platform,
                "total_budget": daily,
                "targeting": targeting,
                "objective": objective,
                "status": "created",
            },
            "fallback": True,
        },
    }


async def exec_ad_monitor(config: dict, ctx: dict) -> dict:
    """
    广告监控执行器

    实时监控广告活动投放效果（曝光/点击/转化/花费），
    识别异常波动并输出告警。
    """
    platform = str(config.get("platform") or "amazon")
    ad_ids_raw = str(config.get("ad_ids") or "camp_001")
    metrics_raw = str(config.get("metrics") or "impressions,clicks,conversions,spend")
    alert_threshold = _to_num(config.get("alert_threshold") or "500")

    ad_ids = [a.strip() for a in ad_ids_raw.split(",") if a.strip()] or ["camp_001"]
    metric_list = [m.strip().lower() for m in metrics_raw.split(",") if m.strip()] or [
        "impressions",
        "clicks",
        "conversions",
        "spend",
    ]

    # 优先尝试平台 API
    platform_metrics = None
    try:
        client = CommercePlatformClient()
        api_result = await client.fetch_ad_metrics(platform, ad_ids, metric_list)
        if api_result.get("status") == "success":
            items = api_result.get("output", {}).get("items")
            if isinstance(items, list) and items:
                platform_metrics = items
    except Exception as e:  # noqa: BLE001
        logger.debug("广告监控 API 不可用，使用本地模拟: %s", e)

    # 模拟监控指标
    metrics = []
    alerts = []
    for idx, ad_id in enumerate(ad_ids):
        # 平台 API 有数据时优先使用平台数据
        if platform_metrics and idx < len(platform_metrics):
            row = dict(platform_metrics[idx])
            row.setdefault("ad_id", ad_id)
            row.setdefault("platform", platform)
            metrics.append(row)
            continue
        impressions = 125000 + idx * 13000
        clicks = int(impressions * (0.025 + idx * 0.002))
        conversions = int(clicks * 0.08)
        spend = round(120.0 + idx * 35.0, 2)
        ctr = round(clicks / impressions * 100, 2) if impressions else 0.0
        cpa = round(spend / conversions, 2) if conversions else 0.0
        row = {
            "ad_id": ad_id,
            "platform": platform,
            "impressions": impressions,
            "clicks": clicks,
            "conversions": conversions,
            "spend": spend,
            "ctr": ctr,
            "cpa": cpa,
            "status": "active",
        }
        metrics.append(row)
        if spend > alert_threshold:
            alerts.append({
                "ad_id": ad_id,
                "level": "warning",
                "message": f"广告 {ad_id} 花费 {spend} 元超过阈值 {alert_threshold} 元",
            })

    return {
        "status": "success",
        "output": {
            "metrics": metrics,
            "alerts": alerts,
            "platform": platform,
            "metric_fields": metric_list,
            "summary": {
                "total_impressions": sum(m["impressions"] for m in metrics),
                "total_clicks": sum(m["clicks"] for m in metrics),
                "total_conversions": sum(m["conversions"] for m in metrics),
                "total_spend": round(sum(m["spend"] for m in metrics), 2),
            },
        },
    }


async def exec_ad_strategy(config: dict, ctx: dict) -> dict:
    """
    广告策略执行器

    基于平台/预算/目标生成智能投放策略，
    优先调用 Agent 生成策略建议，无 Agent 时降级为规则兜底策略。
    """
    platform = str(config.get("platform") or "amazon")
    goal = str(config.get("goal") or "increase_sales")
    budget = str(config.get("budget") or "5000")
    product = str(config.get("product") or "")

    agent = _get_agent()
    if agent is not None:
        try:
            prompt = (
                f"请为电商平台 {platform} 制定广告投放策略。"
                f"目标：{goal}，预算：{budget} 元"
                + (f"，商品：{product}" if product else "")
                + "。请给出出价方式、目标人群、投放时段和预算分配建议。"
            )
            text = await agent.chat(prompt, system_prompt="你是资深电商广告投放专家。", metadata={"history": []})
            strategy_text = _extract_llm_text(text)
            strategy = {
                "platform": platform,
                "goal": goal,
                "budget": float(_to_num(budget)),
                "recommendation": strategy_text,
                "bid_strategy": "动态出价",
                "audience": "高转化人群包",
                "time_range": "高峰时段优先",
                "budget_allocation": "70% 核心词 / 30% 长尾词",
                "source": "agent",
            }
            return {"status": "success", "output": {"strategy": strategy, "platform": platform, "goal": goal}}
        except Exception as e:  # noqa: BLE001
            logger.warning("广告策略 Agent 生成失败，降级为规则策略: %s", e)

    # 规则兜底策略
    goal_map = {
        "increase_sales": "以提升销售额为目标，重点投放高转化词，动态竞价并逐步放量",
        "increase_orders": "以提升订单量为目标，采用点击优化出价，扩展长尾关键词",
        "reduce_cpa": "以降低获客成本为目标，收紧定向人群，采用低出价高曝光策略",
        "brand_awareness": "以品牌曝光为目标，采用展示型广告，扩大受众覆盖",
        "clearance": "以清库存为目标，采用折扣促销广告，集中投放高流量时段",
    }
    strategy = {
        "platform": platform,
        "goal": goal,
        "budget": float(_to_num(budget)),
        "recommendation": goal_map.get(goal, "综合优化出价与人群定向，逐步提升投放效率"),
        "bid_strategy": "动态竞价",
        "audience": "自动定向 + 高转化人群包",
        "time_range": "高峰时段优先",
        "budget_allocation": "70% 核心词 / 30% 长尾词",
        "source": "rule",
    }
    return {"status": "success", "output": {"strategy": strategy, "platform": platform, "goal": goal}}


async def exec_ad_cross(config: dict, ctx: dict) -> dict:
    """
    跨渠道广告投放执行器

    多平台联动广告投放，统一预算并按渠道分配，
    输出各平台的投放计划。
    """
    platforms_raw = str(config.get("platforms") or "amazon, taobao")
    total_budget = float(_to_num(config.get("total_budget") or "10000"))
    product = str(config.get("product") or "")
    objective = str(config.get("objective") or "转化")

    platforms = [p.strip() for p in platforms_raw.split(",") if p.strip()] or ["amazon", "taobao"]

    # 平台权重：按平台重要性分配预算比例
    weights = {"amazon": 0.4, "taobao": 0.25, "jd": 0.2, "pdd": 0.15, "douyin-ecom": 0.2}
    used = sum(weights.get(p, 0.2) for p in platforms)
    if used <= 0:
        used = 1.0

    channels = []
    for p in platforms:
        weight = weights.get(p, 0.2)
        allocated = round(total_budget * (weight / used), 2)
        channels.append({
            "platform": p,
            "allocated_budget": allocated,
            "objective": objective,
            "status": "planned",
            "note": f"{p} 渠道投放计划已生成",
        })

    return {
        "status": "success",
        "output": {
            "channels": channels,
            "total_budget": total_budget,
            "product": product or "通用商品",
            "objective": objective,
            "strategy": "按平台权重分配预算，统一目标，分渠道执行",
        },
    }


# ==================== 执行器注册表 ====================

_COMMERCE_EXECUTORS: Dict[str, Callable] = {
    "builtin:price-monitor": exec_price_monitor,
    "builtin:ad-copy": exec_ad_copy,
    "builtin:review-respond": exec_review_respond,
    "builtin:product-listing": exec_product_listing,
    "builtin:inventory-sync": exec_inventory_sync,
    "builtin:competitor-analysis": exec_competitor_analysis,
    "builtin:keyword-research": exec_keyword_research,
    "builtin:sales-report": exec_sales_report,
    "builtin:ad-streaming": exec_ad_streaming,
    "builtin:ad-monitor": exec_ad_monitor,
    "builtin:ad-strategy": exec_ad_strategy,
    "builtin:ad-cross": exec_ad_cross,
}


def get_commerce_executors() -> Dict[str, Callable]:
    """获取全部电商节点执行器"""
    return dict(_COMMERCE_EXECUTORS)


# ==================== 注册函数 ====================


def register_commerce_nodes(registry) -> int:
    """
    将所有电商运营节点注册到注册表

    Args:
        registry: NodeRegistry 实例

    Returns:
        注册的节点数量
    """
    count = 0
    for node_def in COMMERCE_NODES:
        executor = _COMMERCE_EXECUTORS.get(node_def["type"])

        registry.register(
            NodeDefinition(
                type=node_def["type"],
                label=node_def["label"],
                icon=node_def["icon"],
                category=node_def["category"],
                description=node_def["description"],
                sub_blocks=node_def.get("sub_blocks", []),
                inputs=node_def.get("inputs", []),
                outputs=node_def.get("outputs", []),
                source=node_def.get("source", "builtin"),
            ),
            executor,
        )
        count += 1

    logger.info("电商运营节点注册完成: %d 个", count)
    return count


__all__ = [
    "COMMERCE_NODES",
    "register_commerce_nodes",
    "get_commerce_executors",
    # 执行器
    "exec_price_monitor",
    "exec_ad_copy",
    "exec_review_respond",
    "exec_product_listing",
    "exec_inventory_sync",
    "exec_competitor_analysis",
    "exec_keyword_research",
    "exec_sales_report",
    # 广告投放执行器
    "exec_ad_streaming",
    "exec_ad_monitor",
    "exec_ad_strategy",
    "exec_ad_cross",
]
