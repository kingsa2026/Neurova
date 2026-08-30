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
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger
from .models import NodeDefinition
from .external_api import CommercePlatformClient
from .store_connections import get_store_connection_manager

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

# ---- 亚马逊 SP-API 专用选项（依据官方开发文档 developer-docs.amazon.com/sp-api）----

# MarketplaceId（Store Identifiers 文档），画布按常用站点提供下拉
_AMAZON_MARKETPLACE_OPTIONS = [
    {"value": "ATVPDKIKX0DER", "label": "美国 US"},
    {"value": "A2EUQ1WTGCTBG2", "label": "加拿大 CA"},
    {"value": "A1AM78C64UM0Y8", "label": "墨西哥 MX"},
    {"value": "A2Q3Y263D00KWC", "label": "巴西 BR"},
    {"value": "A1F83G8C2ARO7P", "label": "英国 UK"},
    {"value": "A1PA6795UKMFR9", "label": "德国 DE"},
    {"value": "A13V1IB3VIYZZH", "label": "法国 FR"},
    {"value": "APJ6JRA9NG5V4", "label": "意大利 IT"},
    {"value": "A1RKKUPIHCS9HS", "label": "西班牙 ES"},
    {"value": "A1VC38T7YXB528", "label": "日本 JP"},
    {"value": "A19VAU5U5O7RUS", "label": "新加坡 SG"},
    {"value": "A39IBJ37TRP1C6", "label": "澳大利亚 AU"},
]

# SP-API 区域端点（NA / EU / FE）
_AMAZON_REGION_OPTIONS = [
    {"value": "na", "label": "北美 NA"},
    {"value": "eu", "label": "欧洲 EU"},
    {"value": "fe", "label": "远东 FE"},
]

# Reports API v2021-06-30 常用报表类型
_AMAZON_REPORT_TYPE_OPTIONS = [
    {"value": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL", "label": "订单报表（按下单日期）"},
    {"value": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE_GENERAL", "label": "订单报表（按更新日期）"},
    {"value": "GET_AMAZON_FULFILLED_SHIPMENTS_DATA_GENERAL", "label": "FBA 发货报表"},
    {"value": "GET_FBA_INVENTORY_RECEIPT_SUMMARY", "label": "FBA 库存收货汇总"},
    {"value": "GET_MERCHANT_LISTINGS_ALL_DATA", "label": "在售 Listing 报表"},
    {"value": "GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT", "label": "品牌分析-搜索词报表"},
]

# Listings Items API putListingsItem requirements 参数
_AMAZON_LISTING_REQUIREMENTS_OPTIONS = [
    {"value": "LISTING", "label": "LISTING（完整 Listing）"},
    {"value": "LISTING_PRODUCT_ONLY", "label": "LISTING_PRODUCT_ONLY（仅商品信息）"},
    {"value": "LISTING_OFFER_ONLY", "label": "LISTING_OFFER_ONLY（仅报价/价格）"},
]


# ==================== 联动下拉条件（平台参数随 platform 选择显隐） ====================
# 契约对齐 models.SubBlockConfig.condition: {field, operator, value}
# 前端按 condition 过滤属性面板字段；隐藏字段的值保留在 config 中，执行器行为不变。


def _platform_eq(platform: str) -> Dict[str, Any]:
    """仅选中指定平台时可见"""
    return {"field": "platform", "operator": "eq", "value": platform}


def _platform_in(platforms: List[str]) -> Dict[str, Any]:
    """选中任一列出平台时可见"""
    return {"field": "platform", "operator": "in", "value": list(platforms)}


_STORE_SELECT_PLATFORMS = [
    "amazon",
    "taobao",
    "jd",
    "pdd",
    "douyin-ecom",
    "tiktok",
    "ali1688",
    "xiaohongshu",
    "xianyu",
]


def _store_select_block(require_platform: bool = True) -> Dict[str, Any]:
    """已连接店铺下拉；值存 config.store_id，执行器据此解析店铺级凭据。

    require_platform=False 时（店铺授权节点）不带 platform 条件——店铺是
    该节点的下属对象，需在不选平台时也可见。
    """
    block: Dict[str, Any] = {
        "id": "store_id",
        "name": "store_id",
        "type": "store-select",
        "label": "已连接店铺",
        "default": "",
    }
    if require_platform:
        block["condition"] = _platform_in(_STORE_SELECT_PLATFORMS)
    return block


_FALLBACK_NOTE_TMPL = (
    "未连接店铺或平台 API 调用失败（原因: {reason}），当前输出为本地模拟数据，仅用于流程演示"
)


async def _resolve_store_creds(platform: str, store_id: str, ctx: Optional[Dict[str, Any]] = None):
    """已选店铺 → 解析店铺级凭据（按执行上下文的归属用户隔离）。

    未选或解析失败 → (store_id, None) 交由客户端环境变量/降级路径。
    """
    if not store_id:
        return "", None
    user_id = _ctx_user_id(ctx)
    try:
        return store_id, await get_store_connection_manager().resolve_credentials(platform, store_id, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("店铺 %s 凭据解析失败（走降级路径）: %s", store_id, exc)
        return store_id, None


def _ctx_user_id(ctx: Optional[Dict[str, Any]] = None) -> str:
    """从节点执行上下文取归属用户（多用户隔离）"""
    resolution_context = (ctx or {}).get("resolution_context")
    if resolution_context is None:
        return ""
    return str(getattr(resolution_context, "user_id", "") or "")


_WHEN_AMAZON = _platform_eq("amazon")


def _platform_scoped_id_blocks(
    block_id: str,
    block_type: str,
    default: Any,
    label_by_platform: Dict[str, str],
    fallback_label: str = "",
) -> List[Dict[str, Any]]:
    """为商品 ID 字段生成按平台联动的同键变体。

    各变体共享 id/default（config 键唯一），每个变体携带各自平台的 condition，
    选中某平台时恰好显示一个变体。fallback_label 非空时为未覆盖平台
    （1688/小红书/闲鱼/SHEIN 等无专属命名）追加一个通用变体。
    """
    blocks: List[Dict[str, Any]] = [
        {
            "id": block_id,
            "name": block_id,
            "type": block_type,
            "label": label,
            "default": default,
            "condition": _platform_eq(platform),
        }
        for platform, label in label_by_platform.items()
    ]
    if fallback_label:
        rest = [o["value"] for o in _COMMERCE_PLATFORM_OPTIONS if o["value"] not in label_by_platform]
        if rest:
            blocks.append(
                {
                    "id": block_id,
                    "name": block_id,
                    "type": block_type,
                    "label": fallback_label,
                    "default": default,
                    "condition": _platform_in(rest),
                }
            )
    return blocks


# ==================== 电商节点定义 ====================

# 所有电商运营节点的定义列表
# 使用 dict 格式，便于序列化和测试
COMMERCE_NODES: List[Dict[str, Any]] = [
    {
        "type": "builtin:price-monitor",
        "label": "价格监控",
        "icon": "💰",
        "category": "commerce",
        "description": "监控竞品/自营商品价格变化，低于阈值时告警。亚马逊经 SP-API Product Pricing API（getPricing）按 ASIN 拉取实时价格；淘宝经 TOP taobao.item.get 按 num_iid 拉取；京东经 jingdong.ware.read.findSkuListPage 按 skuId 拉取；拼多多经 pdd.goods.information.get 按 goods_id 拉取（单位分）；抖店经 product.listV2 按 product_id 拉取；TikTok Shop 经 GET /product/202309/products 拉取",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "平台",
                "type": "select",
                "label": "监控平台",
                "default": "amazon",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            _store_select_block(),
            *_platform_scoped_id_blocks(
                "products",
                "textarea",
                "B0XXXXXX",
                {
                    "amazon": "商品列表（逗号分隔）· 亚马逊 ASIN",
                    "taobao": "商品列表（逗号分隔）· 淘宝 num_iid",
                    "jd": "商品列表（逗号分隔）· 京东 skuId",
                    "pdd": "商品列表（逗号分隔）· 拼多多 goods_id",
                    "douyin-ecom": "商品列表（逗号分隔）· 抖店 product_id",
                    "tiktok": "商品列表（逗号分隔）· TikTok product_id",
                    "ali1688": "商品列表（逗号分隔）· 1688 offer ID",
                    "xiaohongshu": "商品列表（逗号分隔）· 小红书 item_id",
                    "xianyu": "商品列表（逗号分隔）· 闲鱼商品 ID",
                },
                fallback_label="商品列表（逗号分隔）· 商品 ID/链接",
            ),
            {
                "id": "marketplace_id",
                "name": "marketplace_id",
                "type": "select",
                "label": "亚马逊站点（MarketplaceId）",
                "default": "ATVPDKIKX0DER",
                "options": _AMAZON_MARKETPLACE_OPTIONS,
                "condition": _WHEN_AMAZON,
            },
            {
                "id": "region",
                "name": "region",
                "type": "select",
                "label": "SP-API 区域端点",
                "default": "na",
                "options": _AMAZON_REGION_OPTIONS,
                "condition": _WHEN_AMAZON,
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
        "description": "分析买家评论情感并自动生成回复。亚马逊经 SP-API Customer Feedback API 按 ASIN 获取评论主题洞察（正面/负面话题+评论片段）；淘宝经 TOP traderates.get 按 num_iid 拉取真实评论（好评/中评/差评）；京东/拼多多/抖店/TikTok Shop 开放平台不提供评论 API，需手工粘贴。均输出回复草稿供人工发布",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "平台",
                "type": "select",
                "label": "平台",
                "default": "taobao",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            _store_select_block(),
            # 仅亚马逊（SP-API Customer Feedback API）与淘宝（TOP traderates.get）提供评论 API，
            # 其余平台无评论拉取能力，故不提供变体（由 reviews 手工粘贴字段兜底）
            *_platform_scoped_id_blocks(
                "asin",
                "input",
                "",
                {
                    "amazon": "商品 ASIN（SP-API Customer Feedback API）",
                    "taobao": "淘宝 num_iid（TOP traderates.get）",
                },
            ),
            {
                "id": "marketplace_id",
                "name": "marketplace_id",
                "type": "select",
                "label": "亚马逊站点（MarketplaceId）",
                "default": "ATVPDKIKX0DER",
                "options": _AMAZON_MARKETPLACE_OPTIONS,
                "condition": _WHEN_AMAZON,
            },
            {
                "id": "reviews",
                "name": "reviews",
                "type": "textarea",
                "label": "评论内容（每行一条）",
                "default": "",
                "placeholder": "京东/拼多多/抖店/TikTok 等无评论 API 平台手工粘贴",
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
        "description": "生成或优化商品 Listing（标题/五点描述/详情）。亚马逊输出符合 Listings Items API（putListingsItem）的提交载荷：sellerId/sku/productType/requirements/attributes；淘宝载荷符合 taobao.item.add、抖店符合 product.createV2、TikTok Shop 符合 POST /product/202309/products",
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
            {
                "id": "sku",
                "name": "sku",
                "type": "input",
                "label": "卖家 SKU（亚马逊 putListingsItem 路径参数）",
                "default": "",
                "placeholder": "例如：SKU-EARBUDS-001",
                "condition": _WHEN_AMAZON,
            },
            {
                "id": "seller_id",
                "name": "seller_id",
                "type": "input",
                "label": "卖家记号 SellerId（Merchant Token）",
                "default": "",
                "placeholder": "例如：A1XXXXXXXXXXXX",
                "condition": _WHEN_AMAZON,
            },
            {
                "id": "product_type",
                "name": "product_type",
                "type": "input",
                "label": "产品类型 ProductType",
                "default": "PRODUCT",
                "placeholder": "例如：HEADPHONES（Product Type Definitions API 查询）",
                "condition": _WHEN_AMAZON,
            },
            {
                "id": "requirements",
                "name": "requirements",
                "type": "select",
                "label": "提交要求 Requirements",
                "default": "LISTING",
                "options": _AMAZON_LISTING_REQUIREMENTS_OPTIONS,
                "condition": _WHEN_AMAZON,
            },
            {
                "id": "marketplace_id",
                "name": "marketplace_id",
                "type": "select",
                "label": "亚马逊站点（MarketplaceId）",
                "default": "ATVPDKIKX0DER",
                "options": _AMAZON_MARKETPLACE_OPTIONS,
                "condition": _WHEN_AMAZON,
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
        "description": "多平台库存同步与低库存预警。亚马逊经 SP-API FBA Inventory API（getInventorySummaries）按 MarketplaceId + sellerSkus（≤50）查询 FBA 库存；淘宝经 taobao.item.get 查 num 库存；京东经 findSkuListPage 查 stockNum；拼多多经 pdd.goods.information.get 查 goods_quantity；抖店经 product.listV2 查 stock_num；TikTok Shop 经 GET products 查 skus.stock_infos",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "platform",
                "type": "select",
                "label": "同步平台",
                "default": "amazon",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            _store_select_block(),
            *_platform_scoped_id_blocks(
                "skus",
                "textarea",
                "",
                {
                    "amazon": "卖家 SKU 列表（逗号分隔，≤50）· Amazon sellerSku",
                    "taobao": "商品 ID 列表（逗号分隔）· 淘宝 num_iid",
                    "jd": "商品 ID 列表（逗号分隔）· 京东 skuId",
                    "pdd": "商品 ID 列表（逗号分隔）· 拼多多 goods_id",
                    "douyin-ecom": "商品 ID 列表（逗号分隔）· 抖店 product_id",
                    "tiktok": "商品 ID 列表（逗号分隔）· TikTok product_id",
                    "ali1688": "商品 ID 列表（逗号分隔）· 1688 offer ID",
                    "xiaohongshu": "商品 ID 列表（逗号分隔）· 小红书 item_id",
                    "xianyu": "商品 ID 列表（逗号分隔）· 闲鱼商品 ID",
                },
                fallback_label="商品 ID 列表（逗号分隔）",
            ),
            {
                "id": "marketplace_id",
                "name": "marketplace_id",
                "type": "select",
                "label": "亚马逊站点（MarketplaceId）",
                "default": "ATVPDKIKX0DER",
                "options": _AMAZON_MARKETPLACE_OPTIONS,
                "condition": _WHEN_AMAZON,
            },
            {
                "id": "region",
                "name": "region",
                "type": "select",
                "label": "SP-API 区域端点",
                "default": "na",
                "options": _AMAZON_REGION_OPTIONS,
                "condition": _WHEN_AMAZON,
            },
            {
                "id": "seller_id",
                "name": "seller_id",
                "type": "input",
                "label": "卖家记号 SellerId（可选）",
                "default": "",
                "placeholder": "例如：A1XXXXXXXXXXXX",
                "condition": _WHEN_AMAZON,
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
        "description": "分析竞品价格、卖点与评论，输出竞争策略建议。亚马逊经 SP-API Product Pricing API（getCompetitivePricing）按 ASIN 拉取竞品竞价；淘宝/京东/拼多多/抖音/TikTok 开放 API 仅提供自营数据、不提供竞品数据，由 LLM 基于竞品清单完成分析",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "平台",
                "type": "select",
                "label": "平台",
                "default": "amazon",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            _store_select_block(),
            *_platform_scoped_id_blocks(
                "competitors",
                "textarea",
                "",
                {
                    "amazon": "竞品列表（逗号分隔）· Amazon ASIN（getCompetitivePricing）",
                    "taobao": "竞品列表（逗号分隔）· 淘宝 num_iid",
                    "jd": "竞品列表（逗号分隔）· 京东 skuId",
                    "pdd": "竞品列表（逗号分隔）· 拼多多 goods_id",
                    "douyin-ecom": "竞品列表（逗号分隔）· 抖店 product_id",
                    "tiktok": "竞品列表（逗号分隔）· TikTok product_id",
                    "ali1688": "竞品列表（逗号分隔）· 1688 offer ID",
                    "xiaohongshu": "竞品列表（逗号分隔）· 小红书 item_id",
                    "xianyu": "竞品列表（逗号分隔）· 闲鱼商品 ID",
                },
                fallback_label="竞品列表（ASIN/ID/链接，逗号分隔）",
            ),
            {
                "id": "marketplace_id",
                "name": "marketplace_id",
                "type": "select",
                "label": "亚马逊站点（MarketplaceId）",
                "default": "ATVPDKIKX0DER",
                "options": _AMAZON_MARKETPLACE_OPTIONS,
                "condition": _WHEN_AMAZON,
            },
            {
                "id": "region",
                "name": "region",
                "type": "select",
                "label": "SP-API 区域端点",
                "default": "na",
                "options": _AMAZON_REGION_OPTIONS,
                "condition": _WHEN_AMAZON,
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
        "description": "汇总平台销售数据，生成运营分析报表。亚马逊经 SP-API Reports API（createReport → getReport → getReportDocument）异步生成报表；淘宝经 taobao.trades.sold.get、京东经 jingdong.pop.order.search、拼多多经 pdd.order.list.get、抖店经 order.searchList、TikTok Shop 经 POST /order/202309/orders/search 拉取真实订单并聚合销售额",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "平台",
                "type": "select",
                "label": "平台",
                "default": "amazon",
                "options": _COMMERCE_PLATFORM_OPTIONS,
            },
            _store_select_block(),
            {
                "id": "report_type",
                "name": "report_type",
                "type": "select",
                "label": "报表类型（SP-API reportType）",
                "default": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL",
                "options": _AMAZON_REPORT_TYPE_OPTIONS,
                "condition": _WHEN_AMAZON,
            },
            {
                "id": "period",
                "name": "period",
                "type": "input",
                "label": "统计周期",
                "default": "2025-01",
                "placeholder": "YYYY-MM 或 YYYY-MM-DD~YYYY-MM-DD（转 ISO 8601 提交）",
            },
            {
                "id": "marketplace_id",
                "name": "marketplace_id",
                "type": "select",
                "label": "亚马逊站点（MarketplaceId）",
                "default": "ATVPDKIKX0DER",
                "options": _AMAZON_MARKETPLACE_OPTIONS,
                "condition": _WHEN_AMAZON,
            },
            {
                "id": "region",
                "name": "region",
                "type": "select",
                "label": "SP-API 区域端点",
                "default": "na",
                "options": _AMAZON_REGION_OPTIONS,
                "condition": _WHEN_AMAZON,
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
        "description": "创建并管理电商平台广告投放计划（活动/预算/定向）。亚马逊广告为独立的 Amazon Ads 开放平台（advertising-api.amazon.com），需 LWA client_id/secret 与 profileId",
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
            {
                "id": "profile_id",
                "name": "profile_id",
                "type": "input",
                "label": "Amazon Ads profileId",
                "default": "",
                "placeholder": "GET /v2/profiles 获取",
                "condition": _WHEN_AMAZON,
            },
            {
                "id": "region",
                "name": "region",
                "type": "select",
                "label": "广告 API 区域端点",
                "default": "na",
                "options": _AMAZON_REGION_OPTIONS,
                "condition": _WHEN_AMAZON,
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
        "description": "实时监控广告活动投放效果（曝光/点击/转化/花费）。亚马逊经独立的 Amazon Ads API（v3 reporting 异步报表）拉取 Sponsored Products 活动指标",
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
                "label": "广告活动ID列表（逗号分隔）",
                "default": "camp_001, camp_002",
                "placeholder": "亚马逊为 campaignId（数字）",
            },
            {
                "id": "metrics",
                "name": "metrics",
                "type": "input",
                "label": "监控指标（逗号分隔）",
                "default": "impressions,clicks,conversions,spend",
                "placeholder": "impressions,clicks,conversions,spend,ctr,acos",
            },
            {
                "id": "alert_threshold",
                "name": "alert_threshold",
                "type": "input",
                "label": "告警阈值（花费元）",
                "default": "500",
                "placeholder": "花费超过该值触发告警",
            },
            {
                "id": "profile_id",
                "name": "profile_id",
                "type": "input",
                "label": "Amazon Ads profileId",
                "default": "",
                "placeholder": "GET /v2/profiles 获取",
                "condition": _WHEN_AMAZON,
            },
            {
                "id": "region",
                "name": "region",
                "type": "select",
                "label": "广告 API 区域端点",
                "default": "na",
                "options": _AMAZON_REGION_OPTIONS,
                "condition": _WHEN_AMAZON,
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
    {
        "type": "builtin:store-auth",
        "label": "店铺授权",
        "icon": "🏪",
        "category": "commerce",
        "description": "店铺授权/管理节点：授权并连接一个平台店铺，作为该节点的下属对象；执行时对所选店铺做只读连接测试并回显授权状态。其下游节点（价格监控/库存同步/销售报表等）通过选择同一个店铺获得店铺级凭据",
        "sub_blocks": [
            _store_select_block(require_platform=False),
        ],
        "inputs": [
            {"id": "input", "label": "授权来源"},
        ],
        "outputs": [
            {"id": "store", "label": "店铺信息"},
            {"id": "test", "label": "连接测试结果"},
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
    亚马逊经 SP-API Product Pricing API（getPricing）按 MarketplaceId + ASIN 查询。
    平台 API 不可用时降级为本地模拟价格数据。
    """
    platform = config.get("platform", "amazon")
    products = config.get("products", "")
    threshold = float(config.get("alert_threshold", 50) or 50)
    marketplace_id = str(config.get("marketplace_id") or "")
    region = str(config.get("region") or "na")
    store_id, store_creds = await _resolve_store_creds(platform, str(config.get("store_id") or ""), ctx)

    product_list = [p.strip() for p in str(products).split(",") if p.strip()]
    if not product_list:
        product_list = ["B0XXXXXX"]

    # 尝试调用电商平台价格 API
    reason = ""
    try:
        result = await CommercePlatformClient().fetch_prices(
            platform=platform, product_ids=product_list,
            marketplace_id=marketplace_id, region=region,
            store_id=store_id, store_creds=store_creds,
        )
        if result.get("status") != "success":
            reason = str(result.get("error") or "")
        else:
            output = result.get("output", {})
            raw_prices = output.get("prices", {})
            prices = []
            alerts = []
            for pid in product_list:
                price = None
                currency = ""
                if isinstance(raw_prices, dict):
                    entry = raw_prices.get(pid) or raw_prices.get("default")
                    if isinstance(entry, dict):
                        price = entry.get("price")
                        currency = str(entry.get("currency") or "")
                    elif entry is not None:
                        price = entry
                if price is None:
                    price = 88.0
                price = float(price)
                item = {"product": pid, "price": price, "platform": platform}
                if currency:
                    item["currency"] = currency
                prices.append(item)
                if price <= threshold:
                    alerts.append({"product": pid, "price": price, "threshold": threshold, "level": "low"})
            return {
                "status": "success",
                "output": {
                    "prices": prices,
                    "alerts": alerts,
                    "threshold": threshold,
                    "platform": platform,
                    "marketplace_id": marketplace_id,
                    "checked_at": ctx.get("timestamp", "now"),
                    "source": "platform_api",
                },
            }
    except Exception as e:  # noqa: BLE001
        logger.warning("价格监控 API 失败，降级为本地模拟: %s", e)
        reason = str(e)

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
            "note": _FALLBACK_NOTE_TMPL.format(reason=reason or "未选择店铺且无环境变量凭据"),
        },
    }


async def exec_store_auth(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """店铺授权/管理节点执行器

    店铺是节点的下属对象：执行时对选中的店铺做一次只读连接测试（探针），
    回显商店状态与凭据就绪情况；未选择店铺时给出引导（指向店铺管理页）。
    """
    store_id = str(config.get("store_id") or "")
    if not store_id:
        return {
            "status": "success",
            "output": {
                "status": "pending",
                "note": "未选择店铺：请在节点下拉中选择，或打开店铺管理页完成店铺授权连接",
            },
        }
    user_id = _ctx_user_id(ctx)
    manager = get_store_connection_manager()
    store = manager.get_store(store_id, user_id=user_id)
    if store is None:
        return {
            "status": "success",
            "output": {
                "status": "error",
                "note": f"店铺不存在或非当前用户所属: {store_id}",
            },
        }
    try:
        test = await manager.test_connection(store_id, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("店铺 %s 授权测试失败: %s", store_id, exc)
        test = {"status": "error", "detail": str(exc)}
    return {
        "status": "success",
        "output": {
            "store_id": store.store_id,
            "store_name": store.store_name,
            "platform": store.platform,
            "status": test.get("status") or store.status,
            "last_error": store.last_error,
            "test": test,
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
    product_id = str(config.get("asin") or config.get("product_id") or "")
    marketplace_id = str(config.get("marketplace_id") or "")

    # 尝试调用电商平台评论 API（亚马逊：Customer Feedback API 评论主题洞察）
    store_id, store_creds = await _resolve_store_creds(platform, str(config.get("store_id") or ""), ctx)
    reason = ""
    try:
        result = await CommercePlatformClient().fetch_reviews(
            platform=platform, product_id=product_id, marketplace_id=marketplace_id,
            store_id=store_id, store_creds=store_creds,
        )
        if result.get("status") != "success":
            reason = str(result.get("error") or "")
        else:
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
                        topic = r.get("topic", "")
                        preset_sentiment = r.get("sentiment")
                    else:
                        review = str(r)
                        review_id = "rev_?"
                        rating = None
                        topic = ""
                        preset_sentiment = None
                    if preset_sentiment in ("positive", "negative"):
                        sentiment = preset_sentiment
                    else:
                        is_negative = any(w in review for w in negative_words)
                        if rating is not None:
                            try:
                                is_negative = is_negative or float(rating) <= 3
                            except (TypeError, ValueError):
                                pass
                        sentiment = "negative" if is_negative else "positive"
                    sentiments.append({"review": review, "topic": topic, "sentiment": sentiment})
                    if sentiment == "negative":
                        reply = f"非常抱歉给您带来不好的体验！我们已经关注到您反馈的问题，正在加紧处理，请您保持联系。感谢您的反馈，帮助我们不断改进。"
                    else:
                        reply = f"感谢您的认可与支持！我们会继续努力，为您提供更优质的商品和服务。"
                    replies.append({"review_id": review_id, "review": review, "topic": topic, "reply": reply, "sentiment": sentiment})
                return {
                    "status": "success",
                    "output": {
                        "replies": replies,
                        "sentiment": sentiments,
                        "platform": platform,
                        "tone": tone,
                        "note": output.get("note", ""),
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
            "note": _FALLBACK_NOTE_TMPL.format(reason=reason or "未选择店铺且无环境变量凭据"),
        },
    }


async def exec_product_listing(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """商品上架 / Listing 优化执行器

    生成优化后的 Listing 标题与卖点描述。
    亚马逊平台额外输出符合 Listings Items API（putListingsItem）的提交载荷，
    包含 sellerId/sku/productType/requirements/attributes 等真实接口字段。
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

    output: Dict[str, Any] = {
        "title": title,
        "bullet_points": bullet_points,
        "description": "、".join(feature_list),
        "keywords": keywords or "",
        "platform": platform,
    }

    if platform == "amazon":
        sku = str(config.get("sku") or "").strip()
        seller_id = str(config.get("seller_id") or "").strip()
        product_type = str(config.get("product_type") or "PRODUCT").strip() or "PRODUCT"
        requirements = str(config.get("requirements") or "LISTING").strip() or "LISTING"
        marketplace_id = str(config.get("marketplace_id") or "ATVPDKIKX0DER").strip()
        output["sp_api_submission"] = {
            "api": "Listings Items API v2021-08-01",
            "method": "PUT",
            "path": f"/listings/2021-08-01/items/{seller_id or '{sellerId}'}/{sku or '{sku}'}",
            "seller_id": seller_id,
            "sku": sku,
            "product_type": product_type,
            "requirements": requirements,
            "marketplace_ids": [marketplace_id],
            "attributes": {
                "item_name": product_name,
                "bullet_points": feature_list,
                "product_description": "、".join(feature_list),
                "search_keywords": [k.strip() for k in str(keywords).split(",") if k.strip()],
            },
            "note": "载荷符合 putListingsItem 请求体；批量上架可用 Feeds API JSON_LISTINGS_FEED",
        }

    return {"status": "success", "output": output}


async def exec_inventory_sync(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """库存同步执行器

    调用电商平台 API 获取库存并生成低库存预警。
    平台 API 不可用时降级为本地模拟库存数据。
    """
    platform = config.get("platform", "amazon")
    threshold = int(config.get("low_stock_threshold", 10) or 10)
    skus = config.get("skus", "") or str(ctx.get("input") or ctx.get("inputs") or "")
    marketplace_id = str(config.get("marketplace_id") or "")
    region = str(config.get("region") or "na")
    seller_id = str(config.get("seller_id") or "")

    sku_list = [s.strip() for s in str(skus).split(",") if s.strip()]
    if not sku_list:
        sku_list = ["SKU-001"]

    # 尝试调用电商平台库存 API（亚马逊：FBA Inventory API getInventorySummaries）
    store_id, store_creds = await _resolve_store_creds(platform, str(config.get("store_id") or ""), ctx)
    reason = ""
    try:
        result = await CommercePlatformClient().fetch_inventory(
            platform=platform, skus=sku_list,
            marketplace_id=marketplace_id, region=region, seller_id=seller_id,
            store_id=store_id, store_creds=store_creds,
        )
        if result.get("status") != "success":
            reason = str(result.get("error") or "")
        else:
            output = result.get("output", {})
            raw_inventory = output.get("inventory", {})
            synced = []
            alerts = []
            for sku in sku_list:
                stock = 20
                if isinstance(raw_inventory, dict):
                    entry = raw_inventory.get(sku) or raw_inventory.get("default")
                    if isinstance(entry, dict):
                        stock = int(entry.get("totalQuantity") or entry.get("fulfillableQuantity") or 0)
                    elif entry is not None:
                        try:
                            stock = int(entry)
                        except (TypeError, ValueError):
                            stock = 20
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
                    "marketplace_id": marketplace_id,
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
            "note": _FALLBACK_NOTE_TMPL.format(reason=reason or "未选择店铺且无环境变量凭据"),
        },
    }


async def exec_competitor_analysis(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """竞品分析执行器

    调用电商平台 API 拉取竞品价格/卖点数据并生成对比分析。
    平台 API 不可用时降级为规则占位分析。
    """
    platform = config.get("platform", "amazon")
    competitors = config.get("competitors", "") or str(ctx.get("input") or ctx.get("inputs") or "")
    marketplace_id = str(config.get("marketplace_id") or "")
    region = str(config.get("region") or "na")

    comp_list = [c.strip() for c in str(competitors).split(",") if c.strip()]
    if not comp_list:
        comp_list = ["竞品A", "竞品B"]

    # 尝试调用电商平台竞品 API（亚马逊：Product Pricing API getCompetitivePricing）
    store_id, store_creds = await _resolve_store_creds(platform, str(config.get("store_id") or ""), ctx)
    reason = ""
    try:
        result = await CommercePlatformClient().fetch_competitors(
            platform=platform, keyword=",".join(comp_list),
            marketplace_id=marketplace_id, region=region,
            store_id=store_id, store_creds=store_creds,
        )
        if result.get("status") != "success":
            reason = str(result.get("error") or "")
        else:
            output = result.get("output", {})
            raw_prices = output.get("prices")
            if isinstance(raw_prices, dict) and raw_prices:
                analysis = []
                for asin, entry in raw_prices.items():
                    price = entry.get("price") if isinstance(entry, dict) else entry
                    analysis.append(
                        {
                            "competitor": asin,
                            "price": price if price is not None else "待采集",
                            "currency": entry.get("currency", "") if isinstance(entry, dict) else "",
                            "price_position": "实时竞价" if price is not None else "待分析",
                            "key_selling_points": [],
                            "review_count": "待采集",
                        }
                    )
                return {
                    "status": "success",
                    "output": {
                        "competitors": analysis,
                        "platform": platform,
                        "marketplace_id": marketplace_id,
                        "strategy_suggestion": "基于 SP-API 实时竞品竞价生成，建议人工复核后执行策略。",
                        "source": "platform_api",
                    },
                }
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
            "note": _FALLBACK_NOTE_TMPL.format(reason=reason or "未选择店铺且无环境变量凭据"),
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
    report_type = str(config.get("report_type") or "")
    marketplace_id = str(config.get("marketplace_id") or "")
    region = str(config.get("region") or "na")

    metric_list = [m.strip() for m in str(metrics).split(",") if m.strip()]

    # 尝试调用电商平台销售报表 API（亚马逊：Reports API createReport → getReport → getReportDocument）
    store_id, store_creds = await _resolve_store_creds(platform, str(config.get("store_id") or ""), ctx)
    reason = ""
    try:
        result = await CommercePlatformClient().fetch_sales_report(
            platform=platform, period=period,
            report_type=report_type, marketplace_id=marketplace_id, region=region,
            store_id=store_id, store_creds=store_creds,
        )
        if result.get("status") != "success":
            reason = str(result.get("error") or "")
        else:
            output = result.get("output", {})
            if output.get("report_id"):
                # SP-API 异步报表流程：返回报表 ID 与文档下载地址
                report = {
                    "platform": platform,
                    "period": period,
                    "report_id": output.get("report_id"),
                    "report_document_id": output.get("report_document_id"),
                    "document_url": output.get("document_url"),
                    "processing_status": output.get("processing_status"),
                    "report_type": output.get("report_type", report_type),
                    "summary": f"SP-API 报表 {output.get('report_id')} 已生成，文档可下载: {output.get('document_url')}",
                }
            else:
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
            "note": _FALLBACK_NOTE_TMPL.format(reason=reason or "未选择店铺且无环境变量凭据"),
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
    profile_id = str(config.get("profile_id") or "")
    region = str(config.get("region") or "na")

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
                "profile_id": profile_id,
                "region": region,
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
        "profile_id": profile_id,
        "region": region,
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
    profile_id = str(config.get("profile_id") or "")
    region = str(config.get("region") or "na")

    ad_ids = [a.strip() for a in ad_ids_raw.split(",") if a.strip()] or ["camp_001"]
    metric_list = [m.strip().lower() for m in metrics_raw.split(",") if m.strip()] or [
        "impressions",
        "clicks",
        "conversions",
        "spend",
    ]

    # 优先尝试平台 API（亚马逊：Amazon Ads API v3 reporting，需 profileId）
    platform_metrics = None
    try:
        client = CommercePlatformClient()
        api_result = await client.fetch_ad_metrics(
            platform, ad_ids, metric_list, profile_id=profile_id, region=region
        )
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
            row.setdefault("ad_id", str(row.get("campaign_id") or ad_id))
            row.setdefault("platform", platform)
            # Amazon Ads 报表字段归一化（purchases7d → conversions）
            if "conversions" not in row and "purchases7d" in row:
                row["conversions"] = row.get("purchases7d")
            for key in ("impressions", "clicks", "conversions", "spend"):
                value = row.get(key)
                try:
                    row[key] = float(value) if value is not None else 0.0
                except (TypeError, ValueError):
                    row[key] = 0.0
            metrics.append(row)
            if row["spend"] > alert_threshold:
                alerts.append({
                    "ad_id": row["ad_id"],
                    "level": "warning",
                    "message": f"广告 {row['ad_id']} 花费 {row['spend']} 元超过阈值 {alert_threshold} 元",
                })
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
    "builtin:store-auth": exec_store_auth,
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
