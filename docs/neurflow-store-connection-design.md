# NeurFlow 店铺连接与授权层设计（Store Connection Layer）

> 日期：2026-08-28
> 状态：设计稿（待评审，评审通过后按红绿灯 TDD 实施）
> 前序文档：`docs/neurflow-external-api-design.md`（统一外部 API 客户端层，已实施）
> 范围：为电商节点补充"先连接店铺、再使用节点"的前置能力层；节点属性面板以"已连接店铺"为入口联动平台参数。

---

## 一、背景与目标

### 1.1 评估结论回顾

对 `external_api.py`（2705 行）与 `commerce_nodes.py`（1878 行）的逐行审查结论：

1. **协议层基本忠实**：各平台网关地址、签名算法（TOP/JD/PDD 的 MD5、抖店五键 MD5、TikTok SHA256）、OAuth refresh 流程、API 方法名、金额单位（元/分）均按官方文档实现。
2. **凭据模型是根本缺口**：每个平台只有一套环境变量凭据（`NEUROVA_TAOBAO_APP_KEY` 等），经 `resolve_api_key()` 解析；每客户端单例 token 缓存（`_OpenGatewayClientBase._token_cache`）；**没有 OAuth 授权码流程、没有店铺注册表、节点上没有店铺选择器**。一个平台只能服务一个店铺，且 token 必须由用户手工从平台后台取出填进 `.env`。
3. **具体参数硬伤**：TikTok Shop 客户端未携带 `shop_cipher`（2024 年起商品/订单等业务 API 强制要求，经 `GET /authorization/202309/shops` 获取），真实调用大概率被拒。
4. **失败不可见**：执行器在 API 失败/未配置时静默降级为模拟数据（仅 `fallback: True` 标记），用户无法分辨数据真假。

### 1.2 目标

| # | 目标 | 验收标准 |
|---|------|---------|
| G1 | 建立店铺连接层：一个平台可连接多个店铺，各自独立凭据与 token 生命周期 | 同平台创建 2 个店铺，节点分别选用，互不串数据 |
| G2 | 节点属性面板以"已连接店铺"为入口，与现有平台联动下拉叠加 | 选平台 → 店铺下拉只列该平台已连接店铺；未连接时给出"去连接"入口 |
| G3 | 修复 TikTok `shop_cipher` 缺失 | TikTok 商品/订单请求携带店铺对应 `shop_cipher` |
| G4 | 降级显性化 | 模拟兜底时节点结果携带明确 `note`，前端可展示警示 |
| G5 | 向后兼容 | 现有 `.env` 凭据与无 `store_id` 的旧工作流行为不变 |

非目标（本期不做）：竞品数据接入、国内广告平台（阿里妈妈/京准通/多多推广/巨量千川）接入、多用户店铺隔离（见 §11 待确认）。

---

## 二、各平台店铺授权模型（设计依据）

各平台"店铺"的绑定方式不同，这是联动设计的事实基础：

| 平台 | 应用级凭据 | 店铺级凭据 | 店铺绑定方式 | 特殊参数 |
|------|-----------|-----------|-------------|---------|
| 亚马逊 SP-API | LWA client_id / client_secret | refresh_token（**一个卖家一个**） | 卖家中心"自授权"直接生成长期 refresh_token（无跳转）；或第三方 LWA OAuth 跳转 | MarketplaceId（站点，非店铺）、region 端点 |
| 淘宝 TOP | app_key / app_secret | session_key（即 access_token，**一店一个**） | OAuth 授权码跳转，店铺主账号登录授权 | — |
| 京东 | app_key / app_secret | access_token（一店一个） | OAuth 授权码跳转（open-oauth.jd.com） | 响应键 `_responce` 历史拼写 |
| 拼多多 | client_id / client_secret | access_token（一店一个） | OAuth 授权码跳转（open-api.pinduoduo.com） | 金额单位分 |
| 抖店 | app_key / app_secret | shop_access_token（一店一个） | OAuth 授权码跳转（op.jinritemai.com） | 金额单位分 |
| TikTok Shop | app_key / app_secret | shop_access_token（一店一个） | Partner Center OAuth 跳转 | **shop_cipher**（授权后经 `GET /authorization/202309/shops` 取回，业务 API 强制携带） |
| 1688 | appKey / appSecret | access_token（一店一个） | 阿里巴巴开放平台 OAuth 跳转（auth.1688.com） | 网关为 ocean 协议（路径式 URL + HMAC-SHA1 签名，见 §2.1） |
| 小红书 | appKey / appSecret | access_token（一店一个） | 小红书开放平台商家 OAuth（**准入受限**，见 §2.2） | 金额单位分（以文档为准） |
| 闲鱼 | appKey / appSecret | access_token（一店一个） | 闲鱼开放平台 OAuth（**定向准入**，普通个人卖家无自助开放 API，见 §2.3） | 金额单位分（以文档为准） |

> ⚠️ 各平台 token 有效期/刷新窗口数值随平台策略调整（小红书已核实：OAuth 响应直接返回 `accessTokenExpiresAt`/`refreshTokenExpiresAt` 字段）。实现上统一策略：**不硬编码有效期，一律以平台返回值为准入库；调用前 60 秒预刷新**。

### 2.1 1688（阿里巴巴开放平台 ocean 网关，已核实 ✅）

1688 的开放网关与淘宝 TOP **不是同一套协议**（TOP 是表单 + MD5，1688 是路径式 URL + HMAC-SHA1），必须单独实现客户端，不能复用 `_router_sign_md5`。以下要点经 SDK 源码 + 网关直接探测双重核实：

| 要素 | 规格（核实结果） |
|------|--------------------------------------|
| 门户 | open.1688.com |
| 网关基址 | `https://gw.open.1688.com/openapi` |
| 调用 URL | `{基址}/param2/{version}/{namespace}/{apiName}/{appKey}`（如 `param2/1/com.alibaba.product/alibaba.product.get/{appKey}`） |
| 签名算法 | **HMAC-SHA1**，规范串 = `/openapi` 之后的 URL 路径段 + 全部参数按 key 升序拼接（`key+value` 连写），结果 **十六进制字符串（大写）** 作为 `_aop_signature` 参数提交。⚠️ 注意：**不是 Base64**，本稿早期版本笔误已修正 |
| 鉴权 | 应用级 appKey/appSecret；需用户授权的 API 额外携带 `access_token`（作为普通参数） |
| OAuth | 授权 URL 核实为 `https://auth.1688.com/oauth/authorize?client_id={appKey}&site=1688&redirect_uri={uri}`；token 经网关 `param2/1/system.oauth2/getToken/{appKey}` 获取/刷新 |
| 业务命名空间 | `com.alibaba.product`（商品）/ `com.alibaba.trade`（交易订单）/ `com.alibaba.account`（账户）等 |

**网关探测证据**（无凭据时返回 `gw.AppKeyNotFound` 说明路径与 API 名有效；返回 `gw.APIUnsupported` 说明路径错误）：
- ✅ `param2/1/system.oauth2/getToken/123456` → `gw.AppKeyNotFound`（token API 路径有效）
- ✅ `param2/1/com.alibaba.product/alibaba.product.get/123456` → `gw.AppKeyNotFound`（业务 API 路径有效）
- ❌ `param2/1/system.oauth2.getToken/123456`（apiName 用点拼接）→ `gw.APIUnsupported`

**能力边界**：1688 为 B2B 批发平台，开放 API 提供**自营**商品/订单/库存数据；价格监控语义为"我供应的商品价格"，与 C 端电商的竞品监控不同。

### 2.2 小红书开放平台（已核实 ✅，准入受限）

以下要点经官方 portal 接口（open.xiaohongshu.com 文档 API + 应用管理接口）与维护中的社区 Go SDK（zsmhub/xhs-sdk）双重核实：

| 要素 | 规格（核实结果） |
|------|------|
| 门户 | open.xiaohongshu.com（开发者后台）；商家后台 ark.xiaohongshu.com（千帆，customer.xiaohongshu.com 登录） |
| 接入形态 | **双路径**：商家自研（submitAuditArk）/ ISV 服务商（submitAuditIsv），均需资质审核准入 |
| 网关 URL | `https://ark.xiaohongshu.com/ark/open_api/v3/common_controller`，POST + JSON；OpenAPI 文档中路径呈 `/ark/{method}` |
| 版本 | `version = "2.0"`（OAuth 授权后统一 2.0） |
| 公共参数 | JSON 体：`method`、`appId`、`sign`、`timestamp`（Unix 秒）、`version`、`accessToken` |
| 签名算法 | **MD5 小写十六进制**：对固定串 `{method}?appId={appId}&timestamp={ts}&version={version}{appSecret}` 取 MD5；body 业务参数**不参与**签名 |
| 应用级凭据 | appKey（即 appId）/ appSecret |
| OAuth 授权 URL | `https://ark.xiaohongshu.com/ark/authorization?appId={appId}&redirectUri={uri}&state={state}` |
| 店铺级凭据 | access_token（一店一个） |
| token API | 同网关，`method=oauth.getAccessToken`（参数 `code`）/ `method=oauth.refreshToken`（参数 `refreshToken`）；响应含 `accessToken/accessTokenExpiresAt/refreshToken/refreshTokenExpiresAt/sellerId/sellerName`，**有效期由平台返回，不硬编码** |
| API 分类 | 公共（common.getCategories 等）/ 订单 / 售后 / 商品 / 库存 / 素材中心 / 物流 / 财务 / 即时零售 / 会员通 / 供货商 |

**设计含义**：小红书接入路径成立的前提是用户已通过开放平台准入（商家自研或服务商身份，提交资质审核）。未准入用户连接店铺时，"测试连接"会返回权限错误，节点按降级路径处理。帮助文案需写明准入申请入口。

### 2.3 闲鱼开放平台（已核实 ✅，定向准入）

**事实陈述（官方文档原文）**：闲鱼小程序/三方开发能力"目前**不对外公开开放申请**，只面向闲鱼运营小二**定向邀请的服务商**，未经邀请的注册将不予通过"。闲鱼**没有面向普通个人卖家的自助开放 API**。

| 要素 | 规格（核实结果） |
|------|------|
| 门户 | open.goofish.com（"闲鱼三方开发平台"）；文档 open.goofish.com/doc/（闲鱼小程序） |
| 面向对象 | 定向邀请的 ISV 服务商 + 其签约企业（淘宝企业账号），普通卖家不可自助接入 |
| 服务端 API 生态 | **挂在淘宝开放平台 TOP 下**：在 TOP 创建应用，业务分类"阿里生态API开发"→"闲鱼垂直行业-**B端**"（商家端 appKey；"闲鱼垂直行业-**C端**"为小程序 appKey）——即闲鱼服务端接口**复用 TOP 网关与 TOP MD5 签名**（与淘宝同构），并非独立网关 |
| 权限包示例 | `orderQuery`（订单查询）、`orderShip`（实物物流发货）、`orderCreateTopApi`（创建订单）、`orderVirtualDelivery`（无物流虚拟发货）、`orderClose`、`refundQuery`、`partRefundBySeller`、`refundBySellerAfterSendGoods`、`userInfoQuery`、`userPhoneQuery`、`userAgeQuery`、`userIsBindAccountQuery` |
| 凭据 | TOP appKey / appSecret + TOP OAuth 授权后的 session（access_token），一店一个 |

**设计含义**：闲鱼客户端**不新建协议**——复用淘宝 TOP 客户端的网关、MD5 签名与 OAuth 刷新实现，仅替换 API 命名空间/权限包与提示文案；具体 TOP method 名（如 `goofish.order.query` 形态）与字段以实施时"闲鱼开放平台 API 列表"核对为准。UI 上需明确标注"闲鱼开放能力为定向邀请，个人卖家暂无开放 API"，避免用户误以为可自助接入。这是产品层面的诚实披露，不是技术缺陷。

> 📋 **文档核实状态（2026-08-29 复核）**
>
> | 平台 | 已核实（数据来源） | 实施前仍需核对 |
> |------|-------------------|----------------|
> | 1688 | 网关 URL、param2 路径格式、token API 路径、OAuth 授权 URL、HMAC-SHA1 大写十六进制签名（SDK 源码 + gw.open.1688.com 网关探测：AppKeyNotFound/APIUnsupported） | com.alibaba.product/trade 具体 API 参数与字段名 |
> | 小红书 | 网关 ark.xiaohongshu.com/ark/open_api/v3/common_controller、version 2.0、MD5 签名固定串、OAuth 授权 URL、oauth.getAccessToken/refreshToken 方法、token 响应字段（官方 portal 接口 + zsmhub/xhs-sdk Go 源码） | 订单/商品具体 method 与金额单位、accessToken 有效期数值 |
> | 闲鱼 | 门户 open.goofish.com、定向邀请准入（官方 quick-start 原文）、服务端 API 走 TOP 生态（"阿里生态API开发-闲鱼垂直行业-B端"）、README 权限包清单（官方文档页 + ISV 控制台 bundle） | 具体 TOP method 名（建议实施时读"闲鱼开放平台 API 列表"页面） |

**关键约束（影响方案分期）**：国内八个平台（淘宝/京东/拼多多/抖店/TikTok/1688/小红书/闲鱼）的 OAuth 授权码流程都要求在平台后台配置**回调地址**，且多数要求公网可达域名（本地 `localhost` 回调仅部分平台开发模式可用）。因此凭据获取分两级：

- **Tier 1（MVP，手工录入）**：用户在自己创建的平台应用后台完成店铺授权，把取得的店铺级凭据（refresh_token / session_key / access_token，及 shop_cipher 等）粘贴到 Neurova 的"连接店铺"表单。亚马逊自授权 refresh_token 也走此路径。**当天即可用，不依赖公网回调。**
- **Tier 2（后续，OAuth 直连）**：NeurFlow 提供 `/oauth/authorize` 构造授权 URL + `/oauth/callback` 回调收码换 token。需要部署具备公网回调地址，逐平台开通。

---

## 三、总体架构

```
┌────────────────────────────────────────────────────────────┐
│ 画布节点属性面板                                              │
│  platform 下拉 ──联动──▶ store-select 下拉（已连接店铺）       │
└───────────────┬────────────────────────────────────────────┘
                │ config: {platform, store_id, ...}
┌───────────────▼────────────────────────────────────────────┐
│ 节点执行器 exec_price_monitor / exec_sales_report / ...      │
│   store_id ──▶ StoreConnectionManager.resolve_credentials() │
└───────────────┬────────────────────────────────────────────┘
                │ StoreCredentials（店铺级凭据 + 扩展参数）
┌───────────────▼────────────────────────────────────────────┐
│ external_api.py 各平台客户端                                 │
│  凭据解析优先级：显式传参 > store_id > 环境变量（向后兼容）      │
│  token 缓存：单例 Dict[store_id → {token, expires_at}]       │
└───────┬───────────────────┬────────────────────────────────┘
        ▼                   ▼
  SecretStore            connected_stores 表
  （令牌密文，            （店铺注册表：平台/名称/状态/
   按 store_id 命名空间）   到期时间/扩展参数，无明文密钥）
```

新增深模块 `neurova/collaboration/neurflow/store_connections.py`，遵循现有 `agent_ref`/单例工厂/懒导入规则；节点执行器经 `store_id` 字符串解耦，不直接依赖该模块内部结构。

---

## 四、数据模型

### 4.1 `connected_stores` 表（加入 `NeurflowStorage._create_tables`，同 neurflow.db，受现有 RLock 保护）

```sql
CREATE TABLE IF NOT EXISTS connected_stores (
    store_id        TEXT PRIMARY KEY,            -- store_xxxxxxxx
    platform        TEXT NOT NULL,               -- amazon/taobao/jd/pdd/douyin-ecom/tiktok/ali1688/xiaohongshu/xianyu
    store_name      TEXT NOT NULL,               -- 显示名（用户填写或授权后回填）
    seller_id       TEXT DEFAULT '',             -- 平台侧卖家/店铺 ID（已知则填）
    marketplace_id  TEXT DEFAULT '',             -- 亚马逊站点
    region          TEXT DEFAULT '',             -- 亚马逊 SP-API 区域端点
    status          TEXT DEFAULT 'pending',      -- pending/active/expired/error
    last_error      TEXT DEFAULT '',             -- 最近一次连接测试/刷新失败信息
    token_expires_at REAL DEFAULT 0,             -- epoch 秒；0=长期（如亚马逊自授权 refresh_token）
    extra_json      TEXT DEFAULT '{}',           -- shop_cipher、profile_id、app_key 引用等（非密钥）
    created_at      REAL NOT NULL,               -- 时间戳沿用本模块 REAL 惯例
    updated_at      REAL NOT NULL,
    last_used_at    REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_connected_stores_platform ON connected_stores(platform);
```

> 实施注记（2026-08-29）：时间戳按代码库既有约定采用 REAL epoch（设计草图原为 TEXT ISO，实施时对齐了 storage.py 惯例）；实现在 `NeurflowStorage._create_tables` + `store_connections.py`，字段与本表一致。

**原则：表里不存任何明文密钥。** 密钥全部进 SecretStore；`extra_json` 只放非敏感扩展参数（shop_cipher 属于公开派生参数，可入库；app_secret/access_token/refresh_token 不入库）。

### 4.2 SecretStore 命名空间

按 `store_id` 隔离（复用现有 AES-256-GCM `SecretStore.set/get/delete`）：

| 内容 | Key 约定 |
|------|---------|
| 应用 Key | `STORE_{store_id}_APP_KEY`（亚马逊=LWA client_id；拼多多=client_id） |
| 应用 Secret | `STORE_{store_id}_APP_SECRET` |
| 店铺 access_token | `STORE_{store_id}_ACCESS_TOKEN`（可空，有 refresh_token 即可） |
| 店铺 refresh_token | `STORE_{store_id}_REFRESH_TOKEN` |

删除店铺时同步 `delete()` 四个 key。上述约定对 1688（appKey/appSecret）、小红书（appKey/appSecret）、闲鱼（appKey/appSecret）同样适用，无需新增 key 形态。

---

## 五、后端设计

### 5.1 新模块 `store_connections.py`

```python
@dataclass
class StoreConnection:          # 表行映射（无密钥字段）
    store_id: str; platform: str; store_name: str
    seller_id: str = ""; marketplace_id: str = ""; region: str = ""
    status: str = "pending"; last_error: str = ""
    token_expires_at: str = ""; extra: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""; updated_at: str = ""; last_used_at: str = ""

@dataclass
class StoreCredentials:         # 运行时凭据（仅内存传递，不落盘/不打日志）
    app_key: str = ""; app_secret: str = ""
    access_token: str = ""; refresh_token: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)   # shop_cipher 等

class StoreConnectionManager:
    def create_store(platform, store_name, credentials: dict, **fields) -> StoreConnection
    def update_store(store_id, **fields) -> Optional[StoreConnection]
    def delete_store(store_id) -> bool                    # 同步清 SecretStore
    def get_store(store_id) -> Optional[StoreConnection]
    def list_stores(platform: str = "") -> List[StoreConnection]
    def resolve_credentials(platform, store_id="") -> StoreCredentials
        # 优先级：store_id 命中 → 组装 StoreCredentials；
        # 未命中且平台有环境变量凭据 → 回落到旧 KEY_NAMES（向后兼容）；
        # 都没有 → 抛 ExternalAPIError（由执行器决定降级）
    async def test_connection(store_id) -> Dict[str, Any]
        # 每平台一个轻量只读探针：amazon=getPricing(任意已知ASIN) 或 getReportSchedule；
        # taobao=taobao.item.get；jd=findSkuListPage(page=1,size=1)；
        # pdd=goods查询；douyin=product.listV2(size=1)；tiktok=GET /authorization/202309/shops
        #（TikTok 探针顺带取回 shop_cipher 写入 extra_json）；
        # ali1688=com.alibaba.product 商品列表/账户只读 API；
        # xiaohongshu/xianyu=只读商品或账户探针（准入受限平台：未准入账号会得到权限错误，
        # 原样写入 last_error 并提示准入申请入口，不吞错）
        # 成功→status=active；失败→status=error + last_error
    async def refresh_token(store_id) -> bool             # 强制刷新并更新 token_expires_at
    def mask(self, store: StoreConnection) -> Dict        # API 输出脱敏：密钥仅显示后 4 位

def get_store_connection_manager() -> StoreConnectionManager: ...
def reset_store_connection_manager(): ...
```

### 5.2 `external_api.py` 客户端层改造（最小侵入）

1. `_OpenGatewayClientBase`：
   - `_token_cache` 由单条 dict 改为 `Dict[str, Dict]`，以 `store_id`（或凭据指纹）为键——解决多店铺 token 互踩。
   - `call()/fetch_*()` 增加可选 `store_id: str = ""` 与 `store_creds: Optional[StoreCredentials] = None`；`_resolve_credentials` 解析顺序变为：**显式传参 > store_creds > 环境变量 KEY_NAMES**。
2. `AmazonSPAPIClient` 同样增加 `store_id` 维度缓存；`marketplace_id/region` 已支持按调用传入，无需结构改动。
3. `TikTokShopClient`：
   - `_request()` 查询参数注入 `shop_cipher`（取自 `store_creds.extra["shop_cipher"]`），参与签名（现有 `_tiktok_sign_sha256` 对全部查询参数签名，天然覆盖）。
   - 新增 `fetch_shop_cipher()`：`GET /authorization/202309/shops` 取回店铺列表与 cipher（供 test_connection 使用）。
4. `CommercePlatformClient` 各 `fetch_*` 透传 `store_id`。
5. **新增三个平台客户端**（替换现有通用 REST 兜底路由）：
   - `Alibaba1688Client`（ocean 网关，**协议独立，不得复用 `_router_sign_md5`**）：
     - 请求 URL：`https://gw.open.1688.com/openapi/param2/{version}/{namespace}/{apiName}/{appKey}`（namespace 与 apiName 间用 `/` 分隔，如 `param2/1/com.alibaba.product/alibaba.product.get/{appKey}`；`system.oauth2/getToken/{appKey}` 作 token 端点）；
     - 签名：HMAC-SHA1(appSecret, `/openapi` 后路径段 + 全部参数按 key 升序 `key+value` 连写)，结果 **大写十六进制** 作为 `_aop_signature`（⚠️ 非 Base64）；
     - OAuth：授权 URL `https://auth.1688.com/oauth/authorize?client_id={appKey}&site=1688&redirect_uri={uri}`；token 经网关 `system.oauth2.getToken` 获取/刷新，缓存键按 `store_id` 维度；
     - 首批 API：`com.alibaba.product` 商品列表/详情（价格监控）、`com.alibaba.trade` 订单（销售报表）——具体 API 名与字段按 §2.1 待核对项定稿。
   - `XiaohongshuClient`：协议已核实，可直接落地——POST JSON 到 `https://ark.xiaohongshu.com/ark/open_api/v3/common_controller`，体含 `method/appId/sign/timestamp/version=2.0/accessToken`，签名 = MD5(`{method}?appId={appId}&timestamp={ts}&version={ver}{appSecret}`) 小写十六进制；token 经 `oauth.getAccessToken`/`oauth.refreshToken` 同网关获取。
   - `XianyuClient`：**复用淘宝 TOP 客户端实现**（网关 eco.taobao.com、TOP MD5 签名、TOP OAuth），仅替换 method 命名空间/权限包（§2.3 清单）与错误提示（含定向邀请准入说明）；权限错误或凭据缺失时返回显性错误，不做静默兜底。
   - `CommercePlatformClient` 路由更新：`ali1688 → Alibaba1688Client`、`xiaohongshu → XiaohongshuClient`、`xianyu → XianyuClient`；无凭据时仍走现有降级路径（G4 显性 note）。
6. **环境变量旧通道保留不动**（G5）：`NEUROVA_1688_API_KEY` / `NEUROVA_XIAOHONGSHU_API_KEY` / `NEUROVA_XIANYU_API_KEY` 继续作为无店铺时的回落凭据。

### 5.3 API 端点（`neurflow_api.py` 追加，挂载路径沿用 `/api/v1/neurflow`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/stores` | 列表，`?platform=` 过滤；密钥脱敏 |
| POST | `/stores` | 创建（Tier 1 手工录入凭据） |
| GET | `/stores/{store_id}` | 详情（脱敏） |
| PUT | `/stores/{store_id}` | 更新名称/凭据/站点参数 |
| DELETE | `/stores/{store_id}` | 删除（含 SecretStore 清理） |
| POST | `/stores/{store_id}/test` | 连接测试（§5.1 探针），返回平台原始错误摘要 |
| POST | `/stores/{store_id}/refresh` | 强制刷新 token |
| GET | `/stores/oauth/authorize` | （Tier 2）构造平台授权 URL 并 302 |
| GET | `/stores/oauth/callback` | （Tier 2）收授权码换 token、落库、回跳前端 |

请求/响应模型沿用 FastAPI Pydantic 风格；鉴权沿用现有路由守卫（与 neurflow 其他端点一致）。

### 5.4 节点层改造（`commerce_nodes.py`）

1. **新增 sub_block 类型 `store-select`**（`models.py` SubBlockConfig.type 注释追加该类型）：

```python
{
    "id": "store_id",
    "name": "store_id",
    "type": "store-select",
    "label": "已连接店铺",
    "default": "",
    "condition": _platform_in(["amazon", "taobao", "jd", "pdd", "douyin-ecom", "tiktok", "ali1688", "xiaohongshu", "xianyu"]),
}
```

   添加到 5 个真实调用平台 API 的节点：`price-monitor`（fetch_prices）、`review-respond`（fetch_reviews）、`inventory-sync`（fetch_inventory）、`sales-report`（fetch_sales_report）、`competitor-analysis`（fetch_competitors）。`product-listing` 仅生成提交载荷文本、不实际调用平台 API，不加店铺字段；广告类节点（ad-streaming/ad-monitor）依赖独立的 Amazon Ads 凭据，本期仅保留 profileId 字段，不接店铺层。

2. **平台专属 ID 标签补齐**：`_platform_scoped_id_blocks` 现为六个平台提供专属标签、其余回落"商品 ID/链接"。为三个新平台补专属标签：1688 → "offer ID（1688 商品 ID）"、小红书 → "商品 ID（item_id）"、闲鱼 → "商品 ID"（SHEIN 维持通用回落）。

3. **执行器**：`store_id = str(config.get("store_id") or "")` 透传给 `CommercePlatformClient.fetch_*`；解析失败（无店铺且无环境变量）时按现有降级路径走，但输出携带显性 `note`（见 §7.2）。

4. **新增店铺授权节点 `builtin:store-auth`**（2026-08-29 应话术确认新增，节点总数 12→13）：店铺管理页升级为画布节点，店铺作为该节点的下属对象；节点含无条件 store-select（无平台上下文始终可见，空平台下拉展示全部店铺），执行时对所选店铺做只读连接测试探针并回显授权状态，未选店铺输出引导（指向店铺管理页）。属性面板为该节点提供"店铺管理（授权）"一体入口（状态徽章/测试连接/打开店铺管理抽屉）。既有 condition 契约 `{field, operator, value}` 不变。

---

## 六、前端设计（NeurUI）

### 6.0 新增 API 封装（`src/api/modules/neurflow.ts` 追加）

沿用现有 `api from '@/api'` + `ApiResponse` 模式，新增店铺端点封装（契约对齐 §5.3）：

- `listStores(platform)` → `GET /api/v1/neurflow/stores?platform=`
- `createStore(payload)` → `POST /api/v1/neurflow/stores`
- `getStore(id)` / `updateStore(id, payload)` / `deleteStore(id)`
- `testStore(id)` → `POST /stores/{id}/test`；`refreshStore(id)` → `POST /stores/{id}/refresh`

**后端未部署时降级**：请求 404/网络失败 → 店铺下拉隐藏并提示"店铺服务不可用"，节点执行走原有降级路径（工作流不中断）——前端先行落地不阻塞（G5）。

### 6.1 属性面板：`store-select` 渲染（`CanvasDesignerPage.vue`）

- `mapSubBlock` **无需改动**：现实现已把任意 `type` 原样透传（`type: (b.type as string) || 'input'`），`store-select` 自然进入 configFields；
- 模板新增分支（插入现有 select 分支之后）：

```html
<a-select
  v-else-if="field.type === 'store-select'"
  v-model:value="selectedNode.config[field.key]"
  :options="storeOptions"
  size="small"
  allow-clear
  show-search
  option-filter-prop="label"
  placeholder="选择已连接店铺"
  :loading="storeOptionsLoading"
/>
<p v-if="!storeOptionsLoading && storeOptions.length === 0" class="store-connect-hint">
  暂无可用店铺，<a @click="openStoreDrawer">去连接店铺</a>
</p>
```

- 数据流（新增 watch，模式对齐现有 `platform` 联动）：
  - `watch(() => selectedNode.value?.config.platform)` → `loadStores(platform)` 拉取该平台店铺列表；
  - 平台变化后若当前 `store_id` 不在新列表 → 清空（引用不存在店铺会在执行时报错，必须显式清空，与"隐藏字段值保留"的联动策略不同——后者保留是为了不影响执行器，前者是防脏引用）；
  - 节点切换时重放（watch `selectedNodeId`）；
- `filterVisibleSubBlocks` 无需改动（`store-select` 走通用 condition 过滤）。

### 6.2 店铺管理抽屉 `CanvasStoreDrawer.vue`（新组件）

画布工具栏新增"店铺"按钮（`ShopOutlined`）唤起，内容：

- **店铺列表**：按平台分组，显示名称/状态徽章（active/error/expired/pending）/最近使用；操作：测试连接、刷新令牌、编辑、删除（删除二次确认并提示"将同步删除该店铺的 SecretStore 凭据"）；
- **添加/编辑表单**：平台下拉 → 按平台动态渲染凭据字段，与 §2 已核实模型一一对应：

| 平台 | 凭据字段 | 帮助文案要点（含准入披露） |
|------|---------|---------------------------|
| 亚马逊 | LWA client_id / client_secret / refresh_token + 站点（MarketplaceId）+ 区域 | 卖家中心"自授权"生成 refresh_token；或 LWA 授权 |
| 淘宝 | app_key / app_secret + session_key（或 refresh_token） | open.taobao.com 创建应用，TOP OAuth 授权 |
| 京东 | app_key / app_secret + access_token | open-oauth.jd.com 授权 |
| 拼多多 | client_id / client_secret + access_token | open-api.pinduoduo.com 授权 |
| 抖店 | app_key / app_secret + shop_access_token | op.jinritemai.com 授权 |
| TikTok | app_key / app_secret + shop_access_token；shop_cipher 可留空，测试连接自动取回 | Partner Center 授权 |
| 1688 | appKey / appSecret + access_token（OAuth 授权取得） | open.1688.com 控制台创建应用（ocean 网关），授权跳转 auth.1688.com |
| 小红书 | appKey / appSecret + access_token | open.xiaohongshu.com 注册应用（商家自研 submitAuditArk / ISV submitAuditIsv 双路径，**均需资质审核**）；授权跳转 ark.xiaohongshu.com/ark/authorization；token 过期时间随响应返回 |
| 闲鱼 | TOP appKey / appSecret + session | 淘宝开放平台申请"阿里生态API开发 → 闲鱼垂直行业-B端"；**官方定向邀请准入，未经邀请注册不予通过，个人卖家无自助开放 API**——UI 明示，避免误判可自助接入 |

- 提交 → `POST /stores` → 自动触发 `test` → 状态回显；测试失败时展示状态为 error 的平台原始错误与准入提示；
- 空列表引导：绘制"无可用店铺 → 去连接店铺"入口。

### 6.3 降级警示（G4）

节点结果 `output.note` 含 `fallback` 字样时，画布节点**标题右侧角标显示 ⚠️**（复用现有 run-status 徽章样式），悬浮提示 note 内容；执行详情面板已展示 output，可复用。角标为纯展示，不改节点行为。

### 6.4 编辑画布全屏（新增能力）

**结论：可以全屏，设计如下。**

- **入口**：工具栏右侧新增"全屏"图标按钮（`FullscreenOutlined`，全屏中切换为 `FullscreenExitOutlined`，图标随 `fullscreenchange` 事件同步），放在"执行"按钮右侧；
- **实现**：浏览器原生 Fullscreen API，目标元素为画布根节点 `.canvas-designer`：
  ```ts
  function toggleFullscreen() {
    if (document.fullscreenElement) void document.exitFullscreen()
    else void canvasRoot.value?.requestFullscreen()
  }
  ```
  监听 `document.fullscreenchange` 更新 `isFullscreen` 状态；Esc 退出由浏览器原生支持（无需处理）；组件 `beforeUnmount` 时若仍处全屏则主动 `exitFullscreen`；
- **CSS**：`.canvas-designer:fullscreen { height: 100vh; width: 100vw; }` 覆盖常规态 `height: calc(100vh - 64px)`（64px 为全局头部高度），补 `background` 兜底，避免全屏时透出页面底色；
- **体验细节**：进入全屏时自动 `fitView()` 一次（画布比例变化后聚焦内容）；首次进入在画布左下角显示短暂提示"按 Esc 退出全屏"（3s 自动消失）；
- **兼容与降级**：Safari 旧版本需 `webkitRequestFullscreen` 前缀，封装 `requestFullscreenCompat()` 探测；两者皆不可用时按钮禁用并 tooltip 说明"当前浏览器不支持全屏"（可选 P2 降级：全局头部折叠的"沉浸模式"，本期不做）；
- **可测试性**：全屏逻辑抽为纯函数模块 `canvasFullscreen.ts`（`isFullscreenTarget()`/`toggleFullscreen()` 依赖注入 document），vitest 以 mock document/fullscreenElement 做红绿灯 TDD；连接店铺选项生成同样抽纯函数 `canvasStores.ts`（`buildStoreSelectOptions(stores, platform)` 过滤+格式化 label `店铺名（平台 · active）`）。

---

## 七、附带修复

### 7.1 TikTok shop_cipher（G3）

- `TikTokShopClient._request` 注入 `shop_cipher`（§5.2）；
- 店铺录入时若未填 shop_cipher，`test_connection` 经 `/authorization/202309/shops` 自动取回并写入 `extra_json`；
- 无 shop_cipher 时业务调用返回明确错误（不再静默降级掩盖）。

### 7.2 降级显性化（G4）

执行器降级分支统一追加：

```python
"note": "未连接店铺或平台 API 调用失败（原因: ...），当前输出为本地模拟数据，仅用于流程演示"
```

行为不变（工作流不中断），仅把"假数据"事实显性化。

---

## 八、向后兼容（G5）

| 场景 | 行为 |
|------|------|
| 旧工作流节点无 `store_id` | 执行器照常运行：环境变量凭据可用则走真实 API，否则原降级路径 |
| `.env` 已配置平台凭据 | `resolve_credentials` 的第三优先级，继续生效 |
| 节点定义新增字段 | 前端按 condition 渲染，旧画布 config 无该键不受影响 |
| 数据库 | 仅 `CREATE TABLE IF NOT EXISTS` 追加，无迁移 |

---

## 九、安全

- 密钥仅存 SecretStore（AES-256-GCM，主密钥 `NEUROVA_MASTER_KEY`）；`connected_stores` 表与 API 响应均不含明文密钥；
- API 列表/详情输出经 `mask()` 脱敏（仅后 4 位）；
- 日志禁记 token/secret（`StoreCredentials.__repr__` 覆写为掩码）；
- `test_connection` 仅调用只读探针 API，不产生订单/改价等副作用；
- 删除店铺即删全部关联 SecretStore key；
- Tier 2 回调端点校验 `state` 参数防 CSRF（实施时随 OAuth 一并落地）。

---

## 十、TDD 实施计划（红绿灯）

每阶段：先写失败测试（红）→ 最小实现（绿）→ 重构。新测试放 `tests/unit/collaboration/`（沿用现有组织层级，不放 tests 根目录）。

| 阶段 | 测试文件（先行） | 实现内容 |
|------|-----------------|---------|
| P1 存储与模型 | `test_store_connections.py`：CRUD、脱敏、删除联动清密钥、platform 过滤 | `connected_stores` 表 + `StoreConnectionManager` 基础 CRUD |
| P2 凭据解析 | `test_store_credentials_resolution.py`：优先级（显式>店铺>env）、无凭据报错、多店铺 token 缓存隔离 | `resolve_credentials` + `_token_cache` 多键化 |
| P3 客户端注入 | `test_external_api_store_creds.py`：各客户端接受 store_creds、TikTok shop_cipher 进签名、TikTok fetch_shop_cipher | §5.2 客户端改造（1-4 项） |
| P3b 三平台客户端 | `test_new_platform_clients.py`：1688 param2 路径构造、HMAC-SHA1 签名（**大写十六进制**）固定向量（用公开示例 key/value 离线验签）、`system.oauth2/getToken` 路径、小红书 MD5 签名固定串 `{method}?appId=...&timestamp=...&version=...{appSecret}` 向量 + `common_controller` 请求体结构、闲鱼复用 TOP 签名与 method 命名空间；CommercePlatformClient 路由三分支 | `Alibaba1688Client` / `XiaohongshuClient` / `XianyuClient` + 路由更新（§5.2 第 5 项） |
| P4 API 端点 | `test_store_api.py`：REST 增删改查、脱敏断言、test/refresh 路由 | neurflow_api 追加 `/stores` 路由 |
| P5 节点集成 | `test_commerce_nodes_store.py`：5 节点含 store-select 字段与 9 平台 condition、三平台专属 ID 标签、执行器透传 store_id、降级 note | commerce_nodes 改造 |
| P6 前端 | `canvasStores.test.ts`（buildStoreSelectOptions 过滤/标签格式/空列表）、`canvasFullscreen.test.ts`（mock document 的 toggle/退出/卸载清理）、stores API 封装测试（mock axios：404 降级）；E2E 浏览器验证抽屉+联动+全屏按钮 | CanvasDesignerPage + CanvasStoreDrawer + canvasStores.ts/canvasFullscreen.ts + neurflow.ts 追加 |
| P7 回归 | 全量 `pytest tests/unit/collaboration -v` + `npm run test`（NeurUI 全量 vitest）+ 节点计数与改动前基线一致 + 既有 condition 测试不回归 | 收尾、更新 `.env.example` 注释与 CONTEXT.md |

Tier 2（OAuth 直连）单独立项，不在本期排期。

---

## 十一、风险与待确认

1. **token 有效期数值**随平台策略变化（小红书等响应内直接返回过期时间字段），实现一律以平台返回值为准入库，不硬编码——无阻塞。
2. **回调地址约束**：国内平台 OAuth 多要求公网回调，本地部署只能走 Tier 1 手工录入——已在分期中规避，但帮助文案需写清各平台后台操作路径。
3. **店铺归属（已确认：多用户隔离）**：`connected_stores` 增加 `user_id` 列（默认归属"default"），Storage/Manager/`/stores` 路由全线按归属用户过滤（`Depends(get_current_user_or_default)`），跨用户 get/update/delete 均 404；删除仅行命中时清理密钥（防跨用户误清）。节点执行凭据解析经执行上下文 `resolution_context.user_id` 取归属用户。实现日期 2026-08-29。
4. **亚马逊 Customer Feedback API 为受限访问级别**（需开发者资料申请受限角色），评论节点在亚马逊平台的能力边界维持现状（主题洞察），不在本方案扩展。
5. **三平台覆盖边界**：1688 走 Alibaba Ocean 网关，协议成熟可具体实现（§2.1）；小红书/闲鱼店铺层与客户端按结构同构设计落地，但两平台开放能力**准入受限**（小红书需资质审核，闲鱼为运营定向邀请，官方原文"未经邀请的注册将不予通过"）——未准入用户的连接测试会返回权限错误，节点走显性降级，这是平台政策约束而非实现缺陷。SHEIN 无面向卖家的开放 API，本期不覆盖，继续走通用降级路径。
6. **文档核实状态**（2026-08-29 复核）：1688 网关/路径/token/签名（大写 HEX）、小红书网关/MD5 签名/OAuth、闲鱼门户与 TOP 生态均已完成闭环核实（来源见 §2 状态表，含网关探测与 SDK 源码证据）；剩余待核对项仅为**具体业务 API 参数与字段名**（1688 商品/订单、小红书订单/商品方法与金额单位、闲鱼 TOP method 名），实施 P3b 时逐项对照官方文档补齐，签名向量测试可先行落地（算法已定）。
7. **前端次序**：P6 前端可先行（店铺 API 封装对后端 404 降级、store-select/全屏不依赖后端），正式联调随 P4 后端端点落地；全屏依赖浏览器 Fullscreen API，Safari 旧版需前缀封装，不支持时按钮禁用（§6.4）。
