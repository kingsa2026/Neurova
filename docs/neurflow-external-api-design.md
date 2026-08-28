# Neurflow 节点库外部平台 API 接入设计

> 日期：2026-08-28
> 状态：设计稿（待评审后按 TDD 实施）
> 范围：分析 56 个 Neurflow 节点中需要接入外部平台 API（含视频/图像生成的 Curl 调用与 API Key 配置）的节点，并给出补充设计方案。

---

## 一、分析结论

### 1.1 节点库现状盘点（56 节点）

| 分类 | 节点数 | 现状 | 是否需要外部 API |
|------|--------|------|------------------|
| comfyui | 11 | ✅ 已接入 ComfyUIClient（`NEUROVA_COMFYUI_HOST`） | 已接入 |
| commerce（电商运营） | 8 | ⚠️ 全部为**模拟数据兜底** | **部分需要** |
| media（短剧视频） | 8 | ⚠️ 图像/视频/发布为**模拟兜底** | **部分需要** |
| tools / skills / mcp | 动态 | ✅ 动态同步真实工具 | 工具本身各自对接 |
| 其他内置（input/output/memory/tool 等） | ~28 | ✅ 本地能力 | 否 |

### 1.2 需要接入外部平台 API 的节点（7 个）

#### A. 短剧视频（media）分类 —— 3 个

| 节点 | 当前实现 | 需要的 API | 建议服务商 |
|------|----------|-----------|-----------|
| `builtin:scene-gen` 场景画面生成 | 仅生成**绘图提示词**（未真正出图） | **文生图** | ComfyUI（已接入）/ OpenAI Images / 通义万相 / 可灵 / Stability |
| `builtin:video-compose` 视频合成 | 返回模拟 `.mp4` 文件名 | **图生视频 / 视频合成** | 可灵 / 即梦 / Runway / Pika（本地合成可用 FFmpeg） |
| `builtin:video-publish` 短剧发布 | 返回模拟 URL（`douyin.com/video/...`） | **平台发布 API** | 抖音开放平台 / 快手 / B站 / TikTok |

#### B. 电商运营（commerce）分类 —— 4 个

| 节点 | 当前实现 | 需要的 API |
|------|----------|-----------|
| `builtin:price-monitor` 价格监控 | `mock_prices` 字典 | 亚马逊 SP-API / 淘宝开放平台 / 京东联盟 / 抖音电商开放平台 |
| `builtin:review-respond` 评论回复 | 负面词规则兜底 | 平台评论拉取 API（开放接口或爬虫） |
| `builtin:inventory-sync` 库存同步 | `mock_stock` 字典 | 平台库存读写 API（ERP 对接） |
| `builtin:sales-report` 销售报表 | 硬编码模拟报表 | 平台销售数据 API |

> `competitor-analysis` 竞品分析：当前为模拟，真实场景依赖第三方竞品数据服务/爬虫，属于"可选接入"（无标准化开放 API，暂列为低优先级）。

### 1.3 无需外部 API 的节点（纯 LLM / 本地即可）

| 分类 | 节点 | 说明 |
|------|------|------|
| 短剧 | `short-drama-script` 剧本 | Agent 生成文本 |
| 短剧 | `storyboard` 分镜 | 文本拆分规则 |
| 短剧 | `voice-over` 配音文案 | 纯文本整理 |
| 短剧 | `subtitle-gen` 字幕 | 规则生成 SRT |
| 短剧 | `tts` 语音合成 | ✅ **已接入 TTSManager**（本地/Edge） |
| 电商 | `ad-copy` 广告文案 | Agent 生成文本 |
| 电商 | `product-listing` 商品文案 | Agent 生成文本 |
| 电商 | `keyword-research` 关键词 | LLM 扩展即可（第三方工具可选） |

---

## 二、可复用的现有基础设施

| 基础设施 | 位置 | 接口 | 用途 |
|----------|------|------|------|
| **SecretStore** 密钥库 | `neurova/llm/providers/secret_store.py` | `get_secret_store()` → `set/get/has/delete/list_keys` | AES-256-GCM 加密存储所有平台 API Key |
| **ComfyUIClient 模式** | `neurova/collaboration/neurflow/comfyui_client.py` | `is_available()` + `execute_node()`，httpx 可选依赖 | 外部 API 客户端的**范本**（网络异常隔离为 failed） |
| **MediaManager** 媒体资产 | `neurova/media/manager.py` | `get_media_manager()`，记录 media_id/media_type/checksum | 保存生成图片/视频产物并登记 |
| **TTSManager** | `neurova/tts/manager.py` | `get_tts_manager()` → `synthesize()` | tts 节点已真实接入 |
| **ConfigManager** | `neurova/core/config.py` | 环境变量加载（`NEUROVA_*` 前缀） | 读取 host/base_url 等非敏感配置 |

---

## 三、补充设计方案

### 3.1 总体架构

新增**统一外部 API 客户端层** `neurova/collaboration/neurflow/external_api.py`（深模块，遵循 ComfyUIClient 模式），节点执行器按需调用；**未配置 API Key 时保留现有模拟兜底**，确保工作流始终可运行。

```
┌─────────────────────────────────────────────────────────┐
│                  Neurflow 节点执行器                       │
│  scene-gen / video-compose / video-publish /             │
│  price-monitor / inventory-sync / sales-report / ...     │
└──────────────┬──────────────────────────┬───────────────┘
               │                          │
       有 Key / 已配置              无 Key / 未配置
               ▼                          ▼
   external_api.py 统一客户端层        现有模拟兜底
   ├── ImageGenClient      (文生图)      (不破坏现有工作流)
   ├── VideoGenClient      (图生视频)
   ├── CommercePlatformClient (电商数据)
   └── PublishPlatformClient  (视频发布)
               │
        ┌──────┴───────────────┐
        ▼                      ▼
  SecretStore (API Key)   MediaManager (产物登记)
   get_secret_store()     get_media_manager()
```

### 3.2 统一外部 API 客户端层（新建 `external_api.py`）

所有客户端统一约定（对齐 ComfyUIClient 深模块模式）：

```python
class ImageGenClient:
    """文生图客户端：支持多 provider，通过 httpx 调用"""
    def is_available(self) -> bool: ...          # 检查 key/host 是否已配置
    async def generate(self, prompt, size, provider) -> ImageResult: ...
    # 失败抛异常，由调用方隔离为 failed 结果

def get_image_gen_client() -> ImageGenClient: ...
def reset_image_gen_client(): ...
```

客户端清单与 API 形态：

| 客户端 | 服务商（provider） | 请求形态（Curl 概要） | Key 来源 |
|--------|-------------------|----------------------|----------|
| `ImageGenClient` | `openai` / `kolors`(可灵) / `wanx`(通义万相) / `stability` / `comfyui`(复用现有) | `POST {base}/images/generations` 带 `Authorization: Bearer {key}`，body 含 `{prompt, size, n}` | SecretStore |
| `VideoGenClient` | `kling`(可灵) / `jimeng`(即梦) / `runway` / `pika` | `POST {base}/videos/generations`（图生视频：multipart 上传首帧 + `{prompt, duration}`），轮询任务状态 | SecretStore |
| `CommercePlatformClient` | `amazon` / `taobao` / `jd` / `douyin-ecom` | 各平台开放 API 的价格/库存/评论/报表查询 | SecretStore |
| `PublishPlatformClient` | `douyin` / `kuaishou` / `bilibili` / `tiktok` | `POST {base}/video/publish` 携带 `{video_url, title, tags}` + access_token | SecretStore |

### 3.3 API Key 配置约定

**统一走 SecretStore 加密存储**（不写入明文代码/JSON），`get_secret_store()` 读取。key 命名约定（同步登记到 `.env.example` 注释）：

| 配置项 | SecretStore Key | 说明 |
|--------|----------------|------|
| 图像生成 | `NEUROVA_IMAGE_API_KEY` | OpenAI / 可灵 / 通义万相等图像生成 Key |
| 图像服务地址 | `NEUROVA_IMAGE_API_BASE`（ConfigManager） | 可选，默认官方端点 |
| 视频生成 | `NEUROVA_VIDEO_API_KEY` | 可灵 / 即梦 / Runway 等视频生成 Key |
| 视频服务地址 | `NEUROVA_VIDEO_API_BASE`（ConfigManager） | 可选 |
| 抖音发布 | `NEUROVA_DOUYIN_ACCESS_TOKEN` | 抖音开放平台 access_token |
| 快手发布 | `NEUROVA_KUAISHOU_ACCESS_TOKEN` | 快手开放平台 access_token |
| 亚马逊电商 | `NEUROVA_AMAZON_SP_API_KEY` | Amazon SP-API |
| 淘宝电商 | `NEUROVA_TAOBAO_APP_KEY` + `NEUROVA_TAOBAO_APP_SECRET` | 淘宝开放平台 |
| 主密钥 | `NEUROVA_MASTER_KEY`（已有） | SecretStore 自身加解密主密钥 |

### 3.4 节点层改造

#### drama_nodes.py（3 个节点）

1. **`builtin:scene-gen`**
   - sub_blocks 新增：`provider`（select：ComfyUI / OpenAI / 可灵 / 通义万相 / 仅提示词）、`image_size`（select）、`image_api_key`（可选，留空则用 SecretStore）
   - 执行器：`provider != 仅提示词` 且 `is_available()` → 调 `ImageGenClient.generate()`，产物登记到 MediaManager，输出 `image_url`/`media_id`；否则保留现有提示词兜底

2. **`builtin:video-compose`**
   - sub_blocks 新增：`provider`（select：可灵 / 即梦 / Runway / 本地 FFmpeg / 模拟）、`first_frame`（首帧图 URL，图生视频用）、`duration`、`video_api_key`
   - 执行器：配置了云视频服务 → 调 `VideoGenClient`（上传首帧 → 提交任务 → 轮询完成），产物登记 MediaManager；否则保留模拟兜底（`note` 中注明）

3. **`builtin:video-publish`**
   - sub_blocks 新增：`access_token`（可选）、`cover_url`、`description`
   - 执行器：`platform` + token 已配置 → 调 `PublishPlatformClient.publish()` 返回真实作品 URL；否则保留模拟 URL 兜底

#### commerce_nodes.py（4 个节点）

4. **`builtin:price-monitor`**：新增 `api_key` 子块；已配置 → `CommercePlatformClient` 按 platform 拉真实价格；否则 mock 兜底
5. **`builtin:review-respond`**：新增 `api_key`；已配置 → 拉真实评论再 LLM 回复；否则规则兜底
6. **`builtin:inventory-sync`**：新增 `api_key`；已配置 → 真实读写平台库存；否则 mock 兜底
7. **`builtin:sales-report`**：新增 `api_key`；已配置 → 拉销售数据汇总；否则模拟报表兜底

### 3.5 安全与失败策略

- **永不硬编码 Key**：全部经 SecretStore 加密存储；节点 sub_blocks 的 key 字段仅作覆盖入口，留空自动回落 SecretStore
- **网络异常隔离**：httpx 请求失败 → 捕获异常 → 返回 `status: failed` + 明确错误信息 + `fallback: true` 的模拟结果（对齐 ComfyUI 节点现有行为），保证工作流不中断
- **可选依赖**：httpx 用 `try/except` 包裹；未安装时报错明确提示
- **超时与重试**：图像/视频生成任务超时 120s，发布/数据查询 30s；视频任务轮询上限 10 次

### 3.6 配置项新增（`.env.example` 补充）

```bash
# ---- Neurflow 外部 API（图像/视频/电商/发布）----
NEUROVA_IMAGE_API_BASE=            # 图像生成服务地址（可选）
NEUROVA_VIDEO_API_BASE=            # 视频生成服务地址（可选）
# 以上 API Key 统一通过 SecretStore 存储，key 名见 3.3 节
```

---

## 四、TDD 实施计划

按 AGENTS.md 红绿灯 TDD 方法，先写测试再实现：

### Phase 1：统一客户端层（`external_api.py`）
- 测试 `tests/unit/test_external_api_clients.py`：
  - ImageGenClient：`is_available()` 有/无 key 判定、httpx mock 调用与响应解析、网络异常隔离
  - VideoGenClient：任务提交 + 轮询完成状态机、超时处理
  - CommercePlatformClient / PublishPlatformClient：请求构造 + 异常隔离
  - SecretStore 集成：key 写入 → 读取 → 供客户端使用

### Phase 2：drama 节点接入
- 测试 `tests/unit/test_drama_nodes_api.py`：
  - `exec_scene_gen`：有 key → 真实出图 + MediaManager 登记；无 key → 提示词兜底（不破坏现有 8 节点测试）
  - `exec_video_compose`：图生视频任务流 + 模拟兜底
  - `exec_video_publish`：真实发布 + 模拟 URL 兜底

### Phase 3：commerce 节点接入
- 测试 `tests/unit/test_commerce_nodes_api.py`：
  - price-monitor / inventory-sync / sales-report / review-respond：有 key 拉真实数据、无 key mock 兜底

### Phase 4：回归与收尾
- 运行全量 `pytest tests/unit/collaboration -v` + 节点库 `get_nodes()` 计数回归（预期 56 → 仍 56，仅增强执行器，不新增/删减节点）
- 更新 `.env.example` 与 `CONTEXT.md` 说明

---

## 五、待确认事项

1. 视频/图像生成**首选服务商**是哪个？（ComfyUI 自建 / OpenAI / 可灵 Kling / 即梦 / 通义万相 / Stability）—— 决定 ImageGenClient/VideoGenClient 默认 provider
2. 电商平台**优先对接哪个**？（亚马逊 SP-API / 淘宝开放平台 / 京东 / 抖音电商）—— 决定 CommercePlatformClient 首个实现
3. 视频发布**优先平台**？（抖音 / 快手 / B站 / TikTok）
4. 是否先落地 **Phase 1（统一客户端层）** 即可，还是直接完整实施 Phase 1-4？
