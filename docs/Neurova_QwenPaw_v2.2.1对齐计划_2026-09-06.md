# Neurova × QwenPaw v2.2.1 对齐计划

> 日期：2026-09-06 ｜ 比对基线：QwenPaw `v2.2.1-beta.2`（HEAD `2b09de79`，2026-09-10，源码 `E:\项目\qwenpaw-latest`）vs Neurova main
> 比对方式：按 release notes 功能域在最新源码中定位实现（shallow clone 提交信息无 PR 号），逐项与 Neurova 现状对照
> 本文整合：模型与提供商 / Creator·AIGC / 控制台与工作区 / 渠道管理 四个圈定域 + P0 安全项 + 跨域快赢清单

---

## 0. 实施批次总览

| 批次 | 内容 | 规模 |
|---|---|---|
| **P0**（立即） | Shell 续行绕过修复（安全）+ `/console/chat/stop` 真取消（假停止 bug） | 各 ≤1 天 |
| **B1 模型与提供商** | §2 全部（含 4 个快赢） | 2-3 天 |
| **B2 Creator/AIGC** | §3 分四步（协议规则重写 → 凭据/传输/账本 → 前端参数面 → 智能特性） | 1-2 周 |
| **B3 控制台与工作区** | §4（stop 之外的控制台域） | 3-5 天 |
| **B4 渠道管理** | §5 分三步（管理能力面 → 群聊隔离可配置 → 渠道类型真实化） | 1-2 周 |
| P2 大工程 | §6（需基建先行，按产品规划排期） | — |

---

## 1. P0 安全与正确性（比对已定位，待实施）

### P0-1 Shell 续行写法绕过敏感路径保护（QP #7472 同款漏洞）

- **漏洞**：POSIX shell 在分词前移除行尾 `\`+换行。守卫对"检查时看到的命令"做正则，与"shell 实际执行的命令"存在解析差分——`cat /etc/pas\<LF>swd` 可绕过 `/etc/passwd` 拦截正则。
- **QwenPaw 修法**：`src/qwenpaw/utils/shell_normalization.py:15-80` `normalize_posix_line_continuations`——引号感知地剥离 `\<LF>` / `\<CRLF>` 续行（单引号内保留字面量；反斜杠转义不改变引号状态）；接入点 `security/tool_guard/engine.py:247-258`（guardian 收到归一化命令，result.params 保留原始值供日志）。
- **Neurova 现状**：`neurova/security/tool_guard.py:296-313` ShellEvasionGuardian 与 `:386-470` FilePathGuardian 均对原始拼接串做正则，无任何续行归一化。**存在同款绕过**。
- **实施**：移植归一化函数（~80 行）→ `ToolGuardEngine.guard`（tool_guard.py:592）入口对 `tool_input` 归一后再分发 guardians；evidence 保留原文。
- **附带发现（登记待拍板）**：`execution_engine/tool_engine.py:175-190` `_create_default_guard` 是**恒放行 stub**（`safe=True` 恒真），`ToolGuardEngine` 仅在显式注入时生效——需确认生产链路注入情况，否则守卫主线空转。

### P0-2 `/console/chat/stop` 空壳假停止（QP #7349）

- **Neurova 现状**：`api/endpoints/console.py:690-693` stop 端点直接返回 success，不取消任何任务；前端 `stopStreaming` 仅 abort SSE；后端照常跑完整轮并消耗 token，工具不响应取消。
- **QwenPaw 机制**：`app/task_tracker.py` 统一注册运行中任务 → `request_stop` → `asyncio Task.cancel()` 打断工具协程（`routers/console.py:481-519`）。
- **实施**：chat 流式 handler 注册 asyncio Task 到 per-session tracker → stop 端点 `task.cancel()` → CancelledError 在 pipeline/tool 层传播中断执行 → SSE 发 `stopped` 事件收尾。工具层长操作（沙箱执行/HTTP 轮询）检查 `asyncio.current_task().cancelled()` 或依赖 Task.cancel 天然传播。

---

## 2. 模型与提供商功能对齐

### 2.1 统一提供商发现 + 能力感知路由 + 回退策略 + 思考控制（#6302）

QwenPaw 四件套 vs Neurova 现状（骨架有、深度缺）：

| 组件 | QwenPaw 锚点 | Neurova 现状 | 差距动作 |
|---|---|---|---|
| 发现错误分类 | `providers/provider_discovery.py:23-49`（DiscoveryErrorKind 七类） | fetch 失败吞错返回空 | `discover_provider_models`（09-06 已加 error_kind）扩展对齐七类命名 |
| 声明式发现策略 | `provider_discovery_policy.py:29-36`（DiscoveryStrategy/ModelSyncMode） | 无 | 低优：启动期批量同步开关 |
| 能力基线+探测缓存 | `capability_baseline.py` 注册表 + `model_capability_cache.py`（learn/forget，provider_manager.py:570-614） | capability_detector 静态目录+启发式，无探测缓存 | 引入探测结果缓存层（provider:capability → bool，带 learn/forget） |
| 跨模型回退门控 | `fallback_chat_model.py:50-67`（输出可见前按 slots 回退）+ `model_error_policy.py`（回退资格分类） | multi_model_client failover：**任何错误都切下一个模型** | 增加"回退资格"判定：auth/bad_request 不触发跨模型回退（换模型无意义），仅 connection/rate_limit/timeout 触发 |
| 思考控制 | `routers/providers.py:243-251`（thinking_enabled/thinking_budget/reasoning_effort 三旋钮） | 仅 reasoning_effort 映射（provider_compat.py:45-59 + useThinkingEffort） | 补 thinking_enabled/budget 两级（按模型 capability 门控注入） |

### 2.2 火山引擎 Agent Plan / MiMo V2.5 提供商 + 模型目录更新（#6515）

- 新增 provider preset：火山引擎 Agent Plan、MiMo V2.5；更新火山引擎（Ark）模型目录（对照 QwenPaw `providers/model_catalog` 或 presets 目录的最新条目——实施时以 QwenPaw 最新目录为基准搬运模型清单/上下文窗口/能力标记）。
- Neurova 挂点：`neurova/llm/presets/`（种子 preset 目录）+ `ModelPreset` 机制；Ark base_url `https://ark.cn-beijing.volces.com/api/v3`。

### 2.3 Token 用量页 Prompt Cache 命中与写入（#7342）

Neurova 全链零 cache 字段，对齐四步：

1. **采集**：`core/usage_accounting.py` record() 加 `cache_read_tokens`/`cache_write_tokens`/`cache_eligible_tokens`（从 provider usage 响应的 `prompt_tokens_details.cached_tokens` / `cache_creation_input_tokens` 提取；multi_model_client 入账处透传）。
2. **落盘**：`core/usage_history.py` SQLite 表加列（带 from_dict 容错）。
3. **API**：`api/endpoints/analytics.py` 汇总接口加 cache_hit_rate。
4. **前端**：UsageStatsPage 摘要卡加命中/写入两张卡（对照 QwenPaw `token_usage/model_wrapper.py:113-144` 采集 + `console/src/pages/Settings/TokenUsage/` 展示）。

### 2.4 快赢四件（各 ≤半天）

| 项 | QwenPaw 锚点 | Neurova 动作 |
|---|---|---|
| 标题生成剥思考内容（#7187） | `app/chats/title_generator.py:46-51`（正则剥 `<think>/<thinking>/<analysis>/<reasoning>`） | `utils/session_title.py` 加剥离（几十行） |
| 流式重试遵守服务端上限（#6617） | `retry_chat_model.py:310-322` Retry-After 解析 + `:480-494` 429 超上限时上报全局暂停 | `rate_limiter.py` 解析 Retry-After 头，退避尊重服务端值 |
| 模型超时独立类别（#7268/#7308） | `exceptions.py:95-107` MODEL_TIMEOUT 独立错误码 | error_mapping 加 TIMEOUT 类别（或 ErrorCategory 扩展），前端可显示"模型超时" |
| 输出能力 vs 请求限制（#7337） | `provider.py:150-208` max_output_length + source 跟踪 | model_limits 区分"模型输出能力上限"与"单次请求限制"，用户覆盖不被发现值覆盖 |

### 2.5 P1 中（模型域）

- **卡住的模型流检测与恢复（#7150）**：QwenPaw `retry_chat_model.py:505-640` 两阶段 watchdog（首 chunk 30s + idle 预算，独立 task + asyncio.wait，空控制 chunk 不续期）→ 取消上游 → 走重试/failover。Neurova `_warn_stream_silence`（multi_model_client.py:1160-1206）仅日志遥测。**升级现有看门狗为检测+取消+复用既有 failover**。
- **稳定 Prompt Cache 前缀（#7346）**：QwenPaw 压缩时冻结历史为 stable prefix + 工具消息连续性重排（model_factory.py:1126-1164）。Neurova 无对应逻辑；低优（依赖上下文压缩链路）。

---

## 3. Creator 与 AIGC 对齐（生成图片/生成视频 API 接入地址规则）

> QwenPaw Creator 当前 1.2.0（plugin.json），AIGC 全部在插件内；宿主侧无生成支撑。
> **Neurova 现状关键事实**：`POST /generation/image` 与 `/video` 均返回 **501**（generation.py:148-154, 233-239）；AIGCPage 视频轮询的 `GET /generation/video/{task_id}` 后端不存在；`neurova/llm/generators/` 六类生成器的端点规则是**虚构近似路径**（kling/runway/pika 端点不匹配任何官方 API），且全部共享单一默认凭据。

### 3.1 图片生成：六协议接入地址规则（QwenPaw 实测矩阵）

| 提供商协议 | 默认 base_url | 端点拼接规则 | 鉴权 | 模式 |
|---|---|---|---|---|
| OPENAI（gpt-image） | 任意 OpenAI 兼容 | `{base}[/v1]/images/generations`（base 含 /v1 不重复加）；参考图走 `images/edits` multipart（1 张 `image`、多张 `image[]`） | Bearer | 同步 |
| DASHSCOPE（qwen-image） | base_url 即完整端点 `…/api/v1/services/aigc/multimodal-generation/generation` | 生成/编辑共用；body=`{model, input.messages[content:[{image},{text}]], parameters}`；**异步**：头 `X-DashScope-Async: enable` → `output.task_id` → 轮询 `{api_root}/tasks/{task_id}`；403 回退同步；本地参考图经百炼临时上传 `oss://` + 头 `X-DashScope-OssResourceResolve: enable` | Bearer | 异步优先/同步回退 |
| GEMINI（Nano Banana） | `https://generativelanguage.googleapis.com/v1beta` | `{base}/models/{model}:generateContent`；裸 googleapis 主机自动补 `/v1beta`；参考图 inlineData base64 在前、text 在后；`generationConfig.imageConfig.aspectRatio/imageSize` | `x-goog-api-key` 头 | 同步 |
| ARK（doubao-seedream） | `https://ark.cn-beijing.volces.com` | `{base}/api/v3/images/generations`；参考图 `image` 字段（URL 直传/本地转 data URL）；比例→像素映射 | Bearer | 同步 |
| BFL（FLUX） | `https://api.bfl.ai` | `POST {base}/v1/{model}` → `{id, polling_url}` → 轮询 polling_url 至 `status=="Ready"`；参考图 `input_image`..`input_image_8` | `x-key` 头 | 异步（polling_url） |
| IDEOGRAM | `https://api.ideogram.ai` | `POST {base}/v1/{model}/generate` multipart；v3 有 aspect_ratio+参考图、v4 仅 text_prompt | `Api-Key` 头 | 同步 |

协议选择：显式协议标签 → 后端映射（支持中文标签"百炼/火山"）→ model_name/base_url 兜底探测（seedream/volces→ARK、flux/bfl.ai→BFL、qwen-image/dashscope→DASHSCOPE、gemini→GEMINI）。

### 3.2 视频生成：七协议接入地址规则

| 协议 | 提交端点 | 轮询端点 | 鉴权 |
|---|---|---|---|
| wan（百炼 Wan2.x/Wan3.0；Bailian 托管 Kling/Vidu 同通道） | `{base}/services/aigc/video-generation/video-synthesis`，base 默认 `https://dashscope.aliyuncs.com/api/v1`，头 `X-DashScope-Async: enable` + OssResourceResolve；body=`{model, input{prompt, media[]}, parameters{resolution,ratio,duration,audio,prompt_extend}}` | `{api_root}/tasks/{task_id}` | Bearer |
| seedance2（火山 Ark Seedance） | `{base}/api/v3/contents/generations/tasks`，content 数组 text / image_url(role=first_frame\|reference_image) / video_url / audio_url | `{base}/api/v3/contents/generations/tasks/{task_id}` | Bearer |
| veo（Gemini Veo） | `{base}/models/{model}:predictLongRunning`，参考媒体全 inlineData base64 | `GET {base}/{operation_name}` | x-goog-api-key |
| minimax（海螺官方） | H3：`{base}/v2/video_generation`；旧模型 `{base}/v1/video_generation` | H3：`{base}/v2/query/video_generation/{task_id}`；旧：`{base}/v1/query/video_generation?task_id=`；HTTP 200 里 `base_resp` 包错误需解包 | Bearer |
| minimax_sglang（自托管） | `{base}/v1/videos`（默认 localhost:30010，可无鉴权） | `GET {base}/v1/videos/{task_id}`，成片 `{base}/v1/videos/{task_id}/content` | 可选 |
| kling（可灵官方） | t2v `{base}/text-to-video/{model}`；i2v `{base}/image-to-video/{model}`；r2v `{base}/omni-video/{model}`；HTTP 200 包 `code!=0` 错误 | `GET {base}/tasks?task_ids={task_id}` | Bearer |
| vidu | `{base}/ent/v2/{text2video\|img2video\|reference2video}` | `GET {base}/ent/v2/tasks/{task_id}/creations` | `Authorization: Token {key}` |

通用工程（QwenPaw 有、Neurova 全缺）：
- **参考媒体按协议分流传输层**（wan→百炼临时上传 oss://；seedance/minimax/kling/vidu→公网 URL 直传+本地图片内联 data URL、本地视频拒绝；veo→全内联 base64）
- **已提交任务持久账本**（provider task_id 落盘，重启恢复轮询；结果 URL 临时有效——Ark 24h/BFL 10min——立即下载持久化）
- 429 退避重试 ×3；各模型官方能力窗口校验（参考图预算/时长/分辨率/比例）
- 协议→后端映射 + host 一致性强校验 + 中文协议标签

### 3.3 对齐批次（Neurova AIGC 重写路线）

- **B2-a 协议规则重写**（核心）：`neurova/llm/generators/` 六类生成器按上述矩阵重写端点规则——image 三协议起步（DASHSCOPE qwen-image / ARK seedream / OPENAI 兼容），video 三协议起步（wan / seedance2 / veo）；废弃虚构端点；统一 `submit + poll` 抽象（异步任务型）/ `sync` 抽象。
- **B2-b 工程层**：按提供商独立凭据/base_url/协议标签配置（现在全部共享默认凭据）；参考媒体传输层；任务持久账本+重启恢复。
- **B2-c REST+前端**：`/generation/image`、`/video` 从 501 变真实现（含 submit/poll/status 三端点）；AIGCPage 暴露尺寸/时长/比例/参考图参数；生成历史持久化。
- **B2-d 智能特性**（对齐 #7167/#7274）：对白→提示词同步（narrative 台词提取 + 逐字校验守卫 `missing_narrative_dialogue`）；三层可配置视频质量自动检查（同步文本评审 / 媒体异步检查（ffprobe 客观门+VLM defect bank）/ 终剪评审，env 显式设置压制 UI 开关）；带录制的网页与桌面操作（录制对 SDK 透明的 wire 层 RecordingControlLink，网页 CDP screencast / 桌面系统级录制）。

---

## 4. 控制台与工作区对齐

| 项 | QwenPaw 锚点 | Neurova 现状 | 差距/动作 |
|---|---|---|---|
| 子代理分组+完成/未读状态（#7035/#7275） | `chatGroups.ts:22-31` source=subagent 固定组；`SessionItem:87-99` running 转圈/New result 未读点 | SubAgentPanel 仅浮窗任务文案；侧栏无分组无徽标 | 侧栏 subagents 固定分组 + WS 事件驱动的完成/未读标记 |
| 后台任务面板（#7083/#7319） | `BackgroundTaskPanel.tsx` + `task_tracker.py`（365 行统一跟踪） | 仅"后台运行中"徽章，task_id 无跟踪/取消 UI | 依赖 P0-2 的任务 tracker，加面板（running/finished 分组+时长+批量清理+取消） |
| 产物展示+媒体直接下载（#7161） | `ResponseArtifactList` + `MediaDownload` 鉴权下载 | dock 图/音频可下载；ArtifactCard 无下载、无视频 | ArtifactCard 加下载；dock 补视频面板 |
| 已完成过程消息自动折叠（#7374） | `messageDisplay.ts:60-95` finished→defaultOpen:false | chatSteps.ts（09-07）已做封口自动收起 | 仅剩 legacy reasoningOpen 旧消息例外，小修 |
| 复制不含思考（#7448） | REASONING 独立消息类型 | copyMessage 只取 content，reasoning 独立字段 | **无差距** |
| 项目目录按会话隔离（#6976） | SessionProjectDirectory per-session ≤10 目录 + chatId 头 | workspace 锚定 agent 级（tool_executor:2385），全会话共享 | 大改：per-session 目录绑定 + 文件工具携带会话上下文 |
| 工作区文件管理（#7078/#7151） | 提示词文件选择 + 上传冲突处理 + zip 下载 | AgentFilePage 仅上传/下载/删除 | 建文件夹/复制/移动 + 系统提示词文件选择 UI |
| Token 用量趋势页（#7207/#7219） | llm/tool 日趋势 + 按 agent + 总览 | 有模型/日趋势；by_agent 仅会话数；无工具趋势 | usage_history 加 agent_id 列（token 按 agent 记账）+ 工具调用趋势 |
| Markdown 密集历史提速（#7176） | DeferredMarkdown（useDeferredValue）+ React.memo | renderMarkdown 每次调用 new Marked+hljs+DOMPurify 无缓存；ChatPage 3457 行单文件全量重渲 | 按 content hash 缓存渲染 HTML + 消息气泡子组件化 |
| 新对话页重开唯一会话（#7104） | preferredChatId 恢复最近会话 | loadSessions 自动选第一个，效果部分等价 | 低优小入口 |
| 长回复流式开销（#7244） | channels/base.py:594-810 buffer+最小间隔节流+单 flush | SSE 无节流，delta 逐条 json.dumps | 流式 buffer + 最小间隔合并 flush |

---

## 5. 渠道管理对齐

### 5.1 渠道类型清单对照

| 状态 | 渠道 |
|---|---|
| 双方都有（Neurova 真实实现） | feishu、dingtalk、wecom、wechat、telegram、voice |
| Neurova 半真实/骨架模拟 | qq（发送回退模拟）、xiaoyi（降级模拟）、discord、mqtt、qqbot、sip、websocket、qclaw |
| **Neurova 缺 adapter**（仅前端卡片/枚举占位） | **matrix、mattermost、slack、imessage、yuanbao、onebot**、console 作为可配置渠道 |
| QwenPaw 独有形态 | 插件自定义渠道（register_channel + config_fields 动态 schema） |

### 5.2 渠道管理功能面缺口

1. **运行管理**：QwenPaw 有 per-channel `restart`（config.py:253）/ `replace`（manager.py:713）/ `clear_queue`（:689）/ 健康检查；Neurova 只有 connect/disconnect/health，**无 restart 端点**。
2. **机器人身份冲突检测**（conflict-check，config.py:379）：无。
3. **扫码登录流程**（qrcode 端点 + status 轮询）：无。
4. **插件化渠道体系**：`register_channel` + config_fields 动态表单 schema（`/channels/schemas`）+ Console 自定义渠道键值编辑器；Neurova `_create_adapter`（channel_config.py:282）对 matrix/mattermost 等落通用兜底。
5. **CLI 交互式配置器**（#6943，channels_cmd.py:631-733）：无。
6. **消息工程**：防抖合并（QP base.py:172-299）、流式 per-channel 事件分发（:600-889）、统一出站渲染器（renderer.py）；Neurova 直发。
7. **MCP 访问规则渠道维度**（#7225）：QP MCPAccessRule source_type=channel；Neurova governance 无 channel 上下文。

### 5.3 群聊会话隔离/共享可配置化（#7208/#7001）

- **钉钉群聊共享会话上下文**（#7208）：QP `share_session_in_group` 参数（channel.py:186/229）+ env `DINGTALK_SHARE_SESSION_IN_GROUP` + 共享时跳过按用户拆分。Neurova `dingtalk.py` 无此配置（仅 sessionWebhook 回复）。
- **Matrix 群聊按发送者隔离**（#7001）：QP 不共享时用 `sender_id` 作请求 user_id（channel.py:3050-3054）+ 防抖 key 按群内 sender 串行化。Neurova 无 matrix adapter。
- **Neurova 现状**：仅 qq.py/qqbot.py 有 `group_share_session`（默认共享）；前端给 feishu 暴露了开关但**后端 feishu.py 未实现**（契约断链）；跨渠道共享走全局 channel_sharing.py，粒度比 per-channel 粗。
- **对齐动作**：统一 `share_session_in_group` 配置语义落到 feishu/dingtalk/wecom/telegram；隔离模式 = sender_id 作 user_id。

### 5.4 渠道专项对齐（release notes 六项）

| 项 | QwenPaw 实现 | Neurova 动作 |
|---|---|---|
| OneBot 媒体先下载本地（#6715） | `onebot/media.py` 并发下载 ≤50MB → 本地化 content part | onebot adapter 真实化时一并做 |
| 钉钉宽屏卡片自动布局（#7416） | `card_auto_layout` 配置 → 发卡注入 `{"autoLayout": true}`（channel.py:3130） | dingtalk.py AI 卡片链路加开关 |
| 自定义渠道纳入 MCP 规则（#7225） | MCPAccessRule source_type=channel | governance 加渠道维度 |
| CLI 配置器（#6943） | channels_cmd.py 交互式 | neurova cli.py 补渠道命令 |

### 5.5 对齐批次

- **B4-a 管理能力面**：restart/replace/clear_queue 端点 + conflict-check + feishu group_share_session 后端补实现（契约断链修复）。
- **B4-b 群聊隔离统一**：share_session_in_group 语义四渠道落地 + per-channel 配置粒度。
- **B4-c 渠道真实化**：按用户渠道使用频率排序真实化骨架 adapter（discord/mqtt/qqbot/sip），matrix/mattermost/slack/onebot 新建（对照 QwenPaw 各 channel.py 移植协议层）。
- **B4-d 插件化渠道 + 扫码登录 + CLI**。

---

## 6. P2 大工程（需基建先行）

- 沙箱挂载路径声明式配置与展开（QP bubblewrap/macos/linux sandbox 的 mounts/deny_paths + expanduser；Neurova 沙箱机制性缺位）
- 文件变化监视+内联 diff 编辑器（QP TabbedEditor useWorkspaceWatch；Neurova 无代码编辑器基建）
- 统一市场（app/plugin/skills 三类目 + provider 抽象；Neurova 四套市场端点并存待整合）
- Embedding 切换显式可撤销 + 重建成功前 BM25 回退（QP 双指纹门控；Neurova 仅缓存失效+自动降级）
- Ollama Embedding 后端；并发启动初始化（app.py 顺序 → gather）
- 媒体标准化保留本地 file:// URL（现在一律内联 base64，历史膨胀）
- Windows CRLF 文本工具层约定（二进制写天然保留，低优）

---

## 7. 附：已确认无差距项（比对过、无需动）

复制不含思考内容、图片发送前按需缩放（`attachment_parser.normalize_image_for_llm` 3MB+2048 长边已有）、非 ASCII 上传文件名保留、CRLF 二进制写天然保留、记忆不依赖 LLM 配置（`llm_client=None` 合法）、Data URL 图片恢复（sanitizeUrl 白名单放行）、Hub/Data/Mail/Creator 产品线本体（Neurova 无对应产品，仅对齐其 AIGC 协议规则）。
