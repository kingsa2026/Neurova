# Neurova vs QwenPaw 全方位对比 v4（2026-09-01/02，对手 2.2.0-beta.5）

> 方法：两轮并行只读代理——第一轮（09-01）五路深读双方**非核心工程面**（部署发行/插件生态/前端桌面e2e/数据层/文档DX），第二轮（09-02，同日并入本篇为第二部分）三路深读**前端功能面**（逐域盘点用户实际能做什么）。全部结论只采信代码实现（文件:行号级证据），不看宣传文档。
> 前序：v3（同日，核心代码维度，QP≈8.5 / NV≈8.4，差距 0.1）。本文不重复 v3 结论，聚焦核心代码之外的全部维度；合读本篇 + v3 即全貌。
> 阅读导航：§1-11 工程面；§12-18 前端功能面；§19 合并补课清单；§20 结论；§21-24 三大纵深能力域（语音对话/记忆系统/工具层，09-02 追加）。

## 总评

**三层口径：核心代码 QP ≈ 8.5 / NV ≈ 8.4（差 0.1）；全方位工程面 QP ≈ 8.5 / NV ≈ 7.6（差 0.9）；前端功能面 QP ≈ 8.4 / NV ≈ 7.1（差 1.3）。**

核心代码差距已压到 0.1，但把镜头拉远，差距呈"越往外越大"的梯度：工程交付面 0.9，前端功能面 1.3。QP 的领先不在引擎，在**交付**——可安装、可更新、有桌面端、有插件 CDN、有文档链的产品，外加 Coding IDE 与治理审批双通道；NV 是引擎优秀但"住毛坯房"的项目。NV 的结构性反超点同样清晰：可观测性（QP 全仓零 metrics）、测试真断言、LLM mock e2e，以及两个 QP 完全没有的功能域（NeurFlow 画布、心理认知五页）。

09-02 追加的三大纵深能力域（第三部分 §21-24）给出第四层口径：**语音对话 QP 7.3 / NV 4.6（QP 反超——电话级语音渠道 vs demo 级），记忆系统 QP 6.5 / NV 8、工具层 QP 6.8 / NV 8.2（NV 纵深优势区）**。NV 的认知层（情感引擎/成长/经验/反思/睡眠整理/遗忘/进化）是 QP 完全没有的版图——用户所列 13 个记忆子维度 QP 只真有 3 项；而 QP 的语音"耳朵+电话线路"（Twilio/SIP/LiveKit + barge-in）恰是 NV 的 demo 级短板，格局高度互补。

---

# 第一部分：非核心工程面（09-01）

## 1. 部署与发行形态

| | QP beta.5 | NV |
|---|---|---|
| Docker | 多阶段构建、supervisord 4 进程、端口只绑 127.0.0.1、无认证启动警告 | 66 行多阶段、非 root、compose 有 healthcheck ✅（QP 反而没有）|
| 安装器 | install.sh 376 行（uv 自管 Python）+ ps1 481 + bat 567 三平台齐备 | start.py 789 行（依赖检查/auto_install/20MB 日志轮转）|
| 依赖锁定 | **无锁文件**（60+ 依赖靠注释式上界驯服）| requirements.txt 宽区间 + `requirements-ci.lock`（uv 生成 98 pin）但**无 hashes** |
| 发行物 | 四件套：PyPI wheel + Docker + Tauri 桌面 + 插件 bundle（OSS CDN 分发）| 无打包发行，仅源码运行 |

**QP 7 / NV 6。** 双方各有亮点：QP 的四件套发布编排（RELEASING.md 定义单版本齐发）和三平台安装器是产品级；NV 的 compose healthcheck + start.py 一键启动是 DX 亮点。但双方共同软肋：QP 无锁文件、容器 root + Chromium --no-sandbox 双叠加；NV 运行时依赖不锁、**docker-compose.yml:39 挂载 `./neuUI` 而目录实为 `NeurUI`——开发 profile 必然失败**（实证 bug）。

## 2. 运维可观测性

**QP 4 / NV 6 — NV 反超。** 这是 QP 全方位最弱的一环：
- QP：`/healthz` readiness 探针（healthz.py:13）之外**全仓零 metrics**、无 Prometheus、日志仅 ColorFormatter+RotatingFileHandler（utils/logging.py:134），线上只能 grep 日志。亮点是 startup_profile/（import time+函数 trace→JSON→viewer.html）这种开发者启动性能分析工具。
- NV：`/metrics` Prometheus 文本端点（app.py:497-514）+ `core/metrics.py` Counter/Histogram + trace_recorder.py（509 行 trace/span 两级，按 trace_id/session/user 索引，落盘 trajectories/ JSON）+ LogManager 环形缓冲 10000 条 + export_json + /health/detailed + 三项健康检查注册（database/memory/disk 区分 READINESS/LIVENESS）。
- NV 坏味道：**database 健康检查是硬编码 `return (True, "SQLite OK")` 假检查**（app.py:103-108）；JSON 日志不含 trace_id，与 trace_recorder 各写各的；LogManager 仅内存态重启即失。

## 3. 插件生态（最大分差维度）

**QP 8 / NV 7，但体量差一个数量级。**
- QP：manifest 契约（17 个 plugin.json：id/version/entry/`qwenpaw_version.min/max`/permissions）+ loader.py 1473 行（semver 兼容检查/依赖解析+锁文件安装/生命周期 asyncio.Lock/install_lock 文件锁）+ api.py 1647 行（含 `register_middleware` **注入推理循环**的钩子）+ registry 1109 行 ≈ **4700 行框架**；生态上有 qwenpaw-creator（13338 行 agentic 视频创作平台）、cloudpaw 11844 行、qwenpaw-pet 3690 行、agent-kanban 2860 行；分发走 OSS CDN（download_catalog.py:21）。
- NV：插件框架完整（plugin_manager/manifest/lifecycle/api_registry + 15+ 端点 discover/install/unload）+ 技能市场 17 端点含发布/审核/多源同步（marketplace.py 896 行）+ NeurFlow 17854 行（DAG/subflow/触发器/自然语言设计器）。
- NV 真实劣势：**无第三方插件分发渠道**（QP 有 CDN+版本兼容门禁），NeurFlow 32 文件单层平铺，execution_engine.py 1290 行单文件。
- QP 坏味道：插件 pip 安装依赖+可注入推理循环但权限仅 chat/storage 两布尔——信任模型全靠 CDN；`/frontend_plugin` 刻意免鉴权；**gpt-image2 插件 manifest `max: 2.1.0` 已被自家 2.2.0 过期**——自带工具在自己新版本上失效，manifest 兼容检查打脸。

## 4. 前端与桌面端（工程指标面）

| | QP console | NV NeurUI |
|---|---|---|
| 栈 | React 18 + zustand 15 store + antd5 + 自研设计系统 @agentscope-ai/* + monaco + three | Vue 3.5 + Pinia 8 store + antd vue 4 + Vue Flow + ECharts |
| 规模 | 922 tsx 文件 / **298 测试文件** / 236 页面组件 / 7 语言 | 273 ts-vue 文件 / 62 测试 / 60 页面 / **11 语言** |
| 测试质量 | store 测试是行为断言；但 ChatPage.coverage.test.tsx 1941 行 73 it 自述"刷覆盖率"；vitest 阈值 5% 形同虚设 | **62/62 全行为断言**（locale-consistency 测试守卫 11 语言键完整）；无快照测试 |
| 工程化 | manualChunks 8 vendor + 路由懒加载+重试 + **构建门禁**（monaco CSS 检查/预压缩 brotli+gzip/初始 bundle ≤10MB 硬门禁+循环依赖检测） | manualChunks 4 vendor + **双主题契约测试**（themes.test.ts 全站禁硬编码色值）+ 11 语言 parity 测试守卫 |
| 桌面端 | **Tauri 2 完整产品**：自动更新（minisign 签名+版本比较器）、托盘（CloseRequested 拦截）、内嵌后端子进程管理 395 行、macOS computer_use 1279 行、WebView 崩溃恢复 284 行、CSP 白名单 capabilities 18 项 | **无桌面端** |

**QP 8 / NV 7.5。** NV 前端单位质量更高（测试真断言、i18n 守卫、主题契约），QP 工程化更重（构建门禁三件套、298 测试文件、桌面产品）。NV 坏味道：无路由级懒加载验证、chunkSizeWarningLimit 抬到 2000 掩盖大包、全仓仅 4 个 aria-*。QP 坏味道：5% 覆盖率阈值下的刷数文化、en.json 4298 行单文件、7 语言键同步仅 3 个专项测试兜底。

## 5. 数据层

**QP 7.5 / NV 5.5（勘误后）— 明显差距。** 两者同为 SQLite+裸 SQL，但成熟度不同：
- QP：历史库是全仓最精细模块——WAL+FTS5 external-content 全文索引+5 索引+`ux_dedup` 去重唯一索引+`_SearchBudget` 搜索行预算+`estimate_purge` dry-run 防误删+`purge`/`vacuum()` 保留清理（30 天默认可 0=永久）+IN 查询 500 分块；会话状态 SafeJSONSession 原子写；hub 库 10 索引含复合降序；配置 3862 行 pydantic v2+**热更新**（2s 轮询+原子 swap+fingerprint 双读校验）。坏味道：无连接池每次操作新开连接、FTS5 unicode61 对 CJK 召回弱降级 LIKE、purge 不 VACUUM。
- NV：28 模块遍布裸 SQLite，WAL 已开启（6 处实证），connection_pool.py 217 行有池化（**此点优于 QP**），schema.py 建表+db_indexes.py。坏味道：**无版本化迁移**（仅 IF NOT EXISTS+启动 add_indexes，无 schema_version）。温度渐进索引：**09-02 勘误——已实现**，`mem_core.py:285` `_background_index_memories` daemon 线程（温度降序 OFFSET 分页+预算 `vector_search.moe_index_limit`+游标无进展守卫+完成状态落盘 `data/moe_index_state_{md5}.json` 跳过重扫）；首版对比误判"承诺未落地"，系代理只 grep 了 unified_vector_store.py 漏掉跨模块实现。

## 6. 数据生命周期与治理

- QP：backup 子系统（zip tmp 原子发布+preflight/staging/提交三段恢复+版本校验）+ 软删除（hub 表 deleted_at 过滤）+ 保留期清理。坏味道：audit 表无 TTL 只增不减、软删数据永久残留。
- NV：**BackupOrchestrator（Ed25519 签名 zip、create/restore/import 信任三态）代码已写好，但全仓 grep 无任何调用方——孤儿代码，API/CLI 均不可触达**（实证：仅 backup/__init__.py 和 orchestrator.py 自身命中）。bdacaef"编排层接线"接的是信任模型内部编排，不是系统接线。
- 数据导出：QP export/import 齐备；NV 仅 LogManager.export_json（日志导出，非业务数据）。

## 7. 测试与 E2E（非核心面补充）

- QP e2e：26 个 Page Object 共 7995 行正经 PO 模式 + fixtures 435 行 + 三维 marker（run mode × 优先级 × 模块）+ test_id 元数据；239 个测试。**致命伤：mocks/ 只拦静态 JSON 不 mock LLM 流式——Chat 核心链路纯 mock 模式不可测，P0 用例强依赖真实 key**；E2E_COVERAGE_REPORT.md 宣称 172 用例但结果区永久 "pending"（2026-04-27 起滞留），实际 239 个测试 > 报告 172——文档防腐失效。catch-all mock 返回 `{}`+200 会静默掩盖前端容错缺陷。
- NV e2e：mock LLM chat e2e 端到端已落地（c9a46f1，NEUROVA_BOOTSTRAP_USER 引导+真实后端 SSE 2 用例）——**在"LLM mock e2e"这一具体点上 NV 领先**；但 NV 无 Playwright Page Object 体系，UI e2e 覆盖远小于 239 用例规模。

## 8. 渠道广度

**NV 14 个主渠道 vs QP 18 渠道。** NV 14 渠道架构更现代：feishu 281 行瘦核心拆 feishu_media/message/ai/auth 四模块 + Stream 长连接/Webhook 双模式；telegram_adapter 238 行组合 8 个 mixin（sender 支持 photo/voice/video/document/location + chat_management ban/unban/管理员列表）。QP 18 渠道含 IMAP IDLE 邮件子系统（monitor 2485 行+ACL+agent 唤醒+独立 MCP 包 22 工具）——邮件是 QP 独有广度。NV 坏味道：telegram 全链路无 reply_markup/inline_keyboard——无交互键盘能力；三套 skill 市场端点文件并存（skill_market/skills_market/marketplace）历史残留。

## 9. 文档与 DX

**QP 7 / NV 5.5。** QP：README 四语言、CONTRIBUTING 双语、SECURITY.md、RELEASING 双语、网站+离线文档（website/public/docs 反向 COPY 进 wheel）。NV：README 2290 行 14 章节但**拼写错误 "v1.0.0 bata1"**（README.md:1665）、docs/ 372 篇 md 编号分层（规模领先）但 06-bugfix/09-dev-progress 过程性文档未归档、**CONTRIBUTING.md 与 SECURITY.md 均不存在**、仓库根 40+ 散落日志/临时文件严重污染 DX、FastAPI /docs+/redoc 已开启。DX 这个维度 NV 输在"打扫"。

## 10. CI 工程文化（补遗）

QP 有两个罕见机制值得记录：**real_behavior_proof_check**（CI 门禁校验 PR 是否含"真实行为证明"，读 GitHub event payload，缺证据非零退出——反 AI 幻觉 PR 的流程门禁）和 **review-bot**（用本地 QwenPaw 实例自主审自己的 PR，review_runner.py 1154 行经 gh CLI 取数据出 verdict）。坏味道：这两个门禁脚本自身 2300 行零测试——门禁不经门禁。

## 11. 全方位工程面评分表

| 维度 | QP beta.5 | NV | 差值来源 |
|---|---|---|---|
| 部署与发行 | 7 | 6 | QP 四件套/三平台安装器；NV compose 挂载 bug+依赖不锁 |
| 可观测性 | 4 | 6 | **NV 反超**：Prometheus /metrics+trace 两级+健康注册；QP 零 metrics |
| 插件生态 | 8 | 7 | QP 4700 行框架+CDN 分发+creator 1.3 万行应用；NV 框架完整但无分发渠道 |
| 前端（工程指标） | 8 | 7.5 | QP 构建门禁三件套+298 测试文件；NV 测试真断言+11 语言守卫 |
| 桌面端 | 8 | 0 | QP Tauri 完整产品（自动更新/托盘/内嵌后端）；NV 无 |
| 数据层 | 7.5 | 5.5（勘误后） | QP FTS5+预算搜索+热更新配置+保留清理；NV 无版本化迁移（温度渐进索引已实现，勘误见 §5） |
| 数据治理 | 7 | 4 | QP backup 三段恢复+软删；**NV BackupOrchestrator 孤儿代码不可触达** |
| e2e | 6 | 5 | QP 239 用例 PO 模式但无 LLM mock；NV 有 mock chat e2e 但规模小 |
| 渠道 | 9 | 8 | QP 18 渠道+邮件子系统；NV 14 渠道架构更干净 |
| 文档/DX | 7 | 5.5 | QP 发行文档链完整；NV CONTRIBUTING/SECURITY 缺失+根目录脏 |
| **全方位加权** | **≈8.5** | **≈7.6** | 核心口径 8.4→全方位 7.6（桌面端 0 权重拖累+数据层差距；数据层勘误后 ≈7.65，按舍入维持 7.6） |

---

# 第二部分：前端功能面（09-02 并入）

> 与第一部分的分工：§4 比的是前端工程指标（测试/构建/i18n），本部分比的是**用户功能面**——每个页面域能做什么操作。结论速览：**功能面口径 QP ≈ 8.4 / NV ≈ 7.1（差 1.3）**。聊天体验双方面积接近但质感不同：QP 是"长任务可靠交互闭环"，NV 是"过程透明 + 轮次可干预"。QP 最大的功能护城河是 Coding IDE 与治理审批双通道；NV 最大的独有面是 NeurFlow 画布与五页心理域——这两个域 QP console 完全没有。

## 12. 路由与页面域对照

| | QP console | NV NeurUI |
|---|---|---|
| 顶层路由 | /login、/hub/admin、/* → MainLayout；isOsPath 时渲染 DesktopOS 壳（App.tsx:313-350） | guest 2 条 + MainLayout 嵌套约 57 条受保护路由（router/index.ts，478 行） |
| 内建路由 | 28 条经 routeRegistry 插件化注册（builtinRoutes.tsx:66-117） | 65 个页面：Agent 子页 21、协作 12、全局 11、系统 12 |
| 页面域 | Chat/Files/Control(渠道·会话·cron·心跳)/Inbox/Agent(技能·工具·MCP·ACP·检查点·配置)/Settings(12 子页)/Market/AppCenter/Hub/Login | Chat/Agent 子页×21/协作(工作流·画布·团队·项目)/记忆·知识库/市场×3/系统×12/心理域×5 |

结构差异：QP 把"配置"集中吃进 Settings 域（12 子页含 backups/offload-policy/env 变量）；NV 把 Agent 作用域页面展开成 21 个子页（memory/experience/emotion/personality/sleep/trajectory…），**功能广度反而更大但导航更深**。

## 13. 聊天体验（双方主战场）

| 能力 | QP | NV |
|---|---|---|
| 流式通道 | fetch POST /console/chat + customFetch 字节层抽 turn_usage；**断线重连 api.reconnect + replay 快进**（不重放打字动画，index.tsx:3416） | fetch + getReader() 手解 SSE（ChatPage.vue:1188-1247），AbortController 停止；**无断线快进** |
| 检索过程可见 | 无 | **memory_progress 事件→检索进度条**（MoE/缓存/兜底，1267-1294）——NV 独有 |
| 思考过程 | SDK 内置 | reasoning/thinking 可折叠块（首次自动展开）+ 思考程度三档随消息发送 |
| 工具调用展示 | **23 张领域卡+1 兜底（28 个工具名映射，明细见 §13.1）**（Shell/EditFile 带 diff 徽标/Browser/Grep/…）+ 统一折叠懒载 + **OffloadBanner 转后台/取消/延时** | 通用折叠卡片（🔧名称+状态 tag+JSON 参数+结果 pre，模板 168-204），无领域卡无 offload |
| 消息队列 | **完整队列状态机**：编辑/重排/插队/暂停/重试/跳过 + 跨标签 Web Locks 单发送者 + IME 防误发 + ↑↓历史回溯 | 无队列 |
| 附件 | 图片/视频/音频/文件 + 长文本转提示词 + 能力探测降级提示 | 📎+全页拖拽，15 类 accept，图片 lightbox；上传 /files/upload |
| 语音 | 仅 ASR（MediaRecorder→转写，5 分钟上限） | **ASR（Web Speech 连续识别+波形+重启熔断）+ TTS 播放器（/audio/synthesize blob，倍速 1x-2x）**——TTS QP 无 |
| 会话管理 | react-window 虚拟列表 + 日期/固定/子代理分组 + **拖拽移动分组** + 会话内搜索 + 草稿持久化 | 列表/搜索/重命名/**归档与恢复**；无置顶无分组无虚拟列表 |
| 轮次操作 | **无消息编辑重发**（队列消息可编辑≠历史消息） | **✎编辑覆写最后一条用户消息 + 🗑删除一轮（client_timestamp 定位）+ 👍👎**——NV 独有 |
| 审批 | **双通道**：2.5s 轮询→右下悬浮 ApprovalCard（倒计时/severity/findings/**Approve Pattern / Approve Exact 双档**）+ Inbox 独立 Tab；会话级审批等级开关注入请求体 | approval_required→模态框（工具名/命令/理由/加白名单 checkbox）；单通道 |
| 独有面 | 限流横幅一键切备选模型；多标签页互斥 | **蜂群子 Agent 浮动小窗（WS）+ 电脑操作分屏 ComputerUsePanel** |

小结：QP 的聊天是"可靠长任务工作台"（队列/offload/重连快进/工具卡体系），NV 的聊天是"过程透明+可干预"（检索进度/思考分档/轮次编辑/TTS）。**双方打平在骨架，QP 领先在可靠性工程，NV 领先在过程透明与轮次操作**。

### 13.1 QP 工具卡明细（registry 实测）

基建三层：**ToolCardShell** 统一 `<details>/<summary>` 折叠壳（shared/ToolCardShell.tsx:138——折叠态不渲染 body，懒挂载省开销）→ **BUILTIN_CARD_REGISTRY** 工具名→组件映射（cards/index.ts:81，28 个工具名）→ **v1Adapter**（adapters/v1Adapter.tsx:178）把整套 registry 适配进 SDK；**未注册工具一律落 GenericToolCard 兜底**（i18n 标题 + Output 块）。cards/ 目录 24 个组件共 1753 行（平均约 73 行/卡），其中 1 张（browser_use→BrowserUseCard）已标记弃用待随后端下线。

| 分类（registry 原注释） | 工具名 → 卡片 | 展示要点（实测） |
|---|---|---|
| File I/O | read_file→ReadFileCard；write_file→WriteFileCard；edit_file→EditFileCard；append_file→AppendFileCard | EditFileCard 带 **diff 增删行徽标**（diffAddBadge/diffDelBadge，EditFileCard.tsx:44-49）+ 逐行 diff 渲染（:70-75）；Write/Append 展示 Content 块 |
| Search | grep_search→GrepSearchCard；glob_search→GlobSearchCard | 参数摘要 + Output 块 |
| Media | view_image→ViewImageCard；view_video→ViewVideoCard；desktop_screenshot→DesktopScreenshotCard；send_file_to_user→SendFileCard | ViewImage 按路径内联图（短文件名，ViewImageCard.tsx:19-20）；SendFileCard 带发送/下载图标（:37） |
| Browser | browser→BrowserCard（browser_use→BrowserUseCard 弃用） | Code + Output 双块（脚本与结果分离） |
| Time | get_current_time→GetCurrentTimeCard；set_user_timezone→SetTimezoneCard | 轻量单行 |
| Token usage | get_token_usage→TokenUsageCard | Output 块 |
| Memory | memory_search→MemorySearchCard | 参数元信息行（limit/min_score，MemorySearchCard.tsx:26-28）+ Output |
| Agent 管理 | list_agents/chat_with_agent/submit_to_agent/check_agent_task/delegate_external_agent → 5 张专属卡 | 跨 agent 协作全可视：列 Agent/对话/提交任务/查状态/委派外部 Agent 各成卡 |
| Skills | materialize_skill→MaterializeSkillCard | Output 块 |
| Shell | execute_shell_command/shell/bash/terminal/run_command（5 别名）→ ShellCard | 命令 + Output 块 |
| Workflow | run_tool_batch→RunToolBatchCard | **Workflow + Steps 双块**（批处理步骤逐条可见） |
| 兜底 | 其余任意工具→GenericToolCard | i18n 标题 + Output 块 |

对 NV 的启示（对齐 §19 前端 P2-b）：NV 现为单一通用折叠卡。类型分化最高性价比三张 = **ShellCard（命令+输出）、EditFileCard（diff 徽标）、BrowserCard（Code/Output）**——正好覆盖 agent 最高频三类动作，可拿全套 80% 的质感；跨 agent 协作 5 卡与 run_tool_batch 批处理卡是差异化亮点，第二步再考虑。

## 14. QP 独有功能域（NV 没有的）

1. **Coding Mode IDE**（内嵌 Chat）：Monaco 多文件编辑（model-per-path 保 undo）+ agent 改文件自动切 inline DiffEditor + 每 hunk Keep/Undo + **SSE 订阅工作区文件变更自动刷新** + GitPanel（stage/diff/commit）+ 图片/PDF/CSV 预览 + Copy to Chat 注入 path:line（TabbedEditor.tsx/GitPanel.tsx）。
2. **DesktopOS 桌面壳**：窗口化承载既有页面（页面零改动）+ AppStore 应用装卸 + Dock/Launcher/MissionControl/壁纸；定性"壳仿真+真功能窗口"（src/os/，19 个 app 映射）。
3. **Hub 多租户管控面**（Hub/index.tsx 2442 行）：runtime 创建/启停/重建、用户管理、按 scope 存密、审计检索、注册开关、Docker 镜像拉取。
4. **Inbox 收割/杂志**：消息按 cron/heartbeat/memory/mail 源分类 + CreateHarvestModal 收割任务 + MagazineStackViewer 阅读视图 + 邮件 ACL 抽屉。
5. **Control 域四子页**：渠道扫码登录（QrcodeAuthBlock）+ 访问控制审批（pending/approve/deny/blacklist）；cron 带日历；heartbeat 手动运行。
6. 杂项：offload-policy 页、env 变量管理页、备份任务页、TokenUsage/AgentStats 趋势图、语音转写提供商切换。

## 15. NV 独有功能域（QP 没有的）

1. **NeurFlow 工作流画布**（CanvasDesignerPage.vue 2611 行）：节点拖拽/贝塞尔连线/属性面板/断点+Mock+单步调试/版本抽屉/触发器抽屉/MiniMap/**AI 自然语言生成画布**/ComfyUI 导入——QP console **没有任何画布**（omp_workflows 是插件 bundle）。
2. **心理认知域五页**：Emotion（主导情绪+分布+性格特质条，契约 bug 已修）、Metacognition 752 行、Reflection、Growth 973 行、Personality——对应 NV 后端认知层，QP 完全没有此域。
3. **轮次操作**：编辑覆写/删除一轮/赞踩（接记忆温度），QP 无消息编辑。
4. **TTS 播放链**：状态探测→合成→自定义播放器（进度/倍速）。
5. **知识库治理 UI**：可见性 public/private 标签 + 私有条目提交/撤回审核（submission.status）+ 拖拽导入。
6. **模型服务商管理**（ModelPage.vue 2303 行）：内置服务商卡片墙+发现模型+OpenRouter 专属筛选面板（系列/模态/免费）——QP providers CRUD+Key 校验但无发现/筛选面。
7. 渠道集成页：平台字段 schema 动态生成表单+连接测试；调度器任务卡（cron 标签+立即执行）；睡眠设置（梦境回放/记忆固化/冲突解决三开关）。

## 16. 双方共有但深度差距明显的

- **可视化**：QP MemoryGraphView 是真 3D 力导向图（three+3d-force-graph+ACES 色调）+ CheckpointGraph SVG 泳道图+previewRestore；NV 的 KnowledgeGraphPage（382 行）**实为节点卡片网格而非图渲染**（node-grid class，无 graph 库），NeuronPage 依赖关系也是列表——名实不符是 NV 短板。
- **技能/工具/MCP 配置**：QP MCP 客户端 CRUD+策略+stdio/http/sse 三协议 UI、技能 Hub 安装+池管理+上传安装插件；NV tool-layers/skill-pool/marketplace 三页覆盖相近面，但 MCP 策略 UI 与插件上传安装面较薄。
- **实时性**：QP 无全局 WS，靠 2.5s ConsolePollService+文件 SSE 单例（保守但全覆盖）；NV 只有聊天单点 WS（useSessionSync），通知铃铛 60s 轮询。

## 17. 前端深读发现的 NV 功能性 bug

1. **MemoryPage 语义搜索断链**：`MemoryPage.vue:585` 代码注释自证 `POST /memory/search 405`，真端点是 `/enhanced-memory-search/search`——语义搜索开关打开后功能实际不可用（UI 存在但调错端点）。
2. KnowledgeGraphPage/NeuronPage 图谱页无图渲染（名实不符，见 §16）。

## 18. 前端功能面评分表

| 功能域（权重） | QP | NV | 差距主因 |
|---|---|---|---|
| 聊天体验（20%） | 9 | 8.5 | QP 队列/offload/重连快进；NV 检索进度/轮次编辑/TTS——各有独门 |
| 会话管理（8%） | 8.5 | 7 | QP 分组拖拽+虚拟列表+会话内搜索；NV 有归档 |
| 文件/编码（10%） | 9 | 5.5 | QP 全套 IDE；NV 仅文件管理页 |
| 工具/MCP/技能（12%） | 9 | 7.5 | QP MCP 策略+插件上传安装+Hub 导入 |
| 治理审批（10%） | 9 | 7 | QP 双通道+双档批准+会话级等级；NV 单模态框 |
| 可视化（8%） | 8 | 6 | QP 真 3D/泳道图；NV 图谱页无图 |
| 系统管理（12%） | 9 | 7.5 | QP Hub 多租户/心跳/cron 日历/备份页 |
| 心理认知域（5%） | 1 | 8 | NV 独有五页 |
| 工作流（8%） | 2 | 8.5 | NV 独有画布全套 |
| 桌面壳（4%） | 8 | 0 | QP DesktopOS |
| 实时性（3%） | 7.5 | 6.5 | QP 轮询+文件 SSE 全覆盖；NV 单点 WS |
| **加权** | **≈8.4** | **≈7.1** | |

## 19. 合并补课清单（工程面 + 前端功能面，按性价比）

> **✅ 执行完毕（2026-09-02 自动长任务 21 commits + 第二轮补课 5 commits）**：除"明确排除"外全部落地——含第二轮补齐的 CONTRIBUTING/SECURITY（48f48ab）、telegram inline_keyboard（62a7aa9）、情感分析入口收敛（4e3d9d5）、**断线重连+replay 快进（d66c28d）**。仅剩 P3-a Tauri 桌面与 P3-b 消息队列两个大工程。执行明细见 `docs/04-plans/2026-09-02-noncore-upgrade-autorun-plan.md` 执行结果节。

> 工程面 9 项已细化为可执行计划：`docs/04-plans/2026-09-02-noncore-cleanup-plan.md`（含 MoE 索引勘误 Task——勘误注记已于本次合并写入 §5/§11）。Tauri 桌面（工程 P3-a）需独立立项，不入细化计划。

| 面 | 优先 | 项 | 成本 | 预期 |
|---|---|---|---|---|
| 前端 | P1-a | **修 MemoryPage 语义搜索断链**（换端点 /enhanced-memory-search/search） | 极小 | 现有功能实际不可用 |
| 工程 | P1-a | **BackupOrchestrator 接线**：挂 admin API 端点 + CLI（能力已在，只差触达） | 小 | 数据治理 4→7 |
| 工程 | P1-b | 修 docker-compose.yml:39 `neuUI`→`NeurUI` | 极小 | 部署链路可用 |
| 工程 | P1-c | database 健康检查假 lambda 换真连库（app.py:103-108） | 极小 | 可观测性去水分 |
| 工程 | P1-d | README "bata1" 拼写+根目录 40+ 临时文件清理 | 极小 | DX 面子工程 |
| 前端 | P1-b | 通知改 SSE 推送（复用聊天 SSE 基建，去 60s 轮询） | 小 | 实时性补课 |
| 前端 | P1-c | 会话置顶 + 会话内消息搜索 | 小 | 会话管理追平 |
| 工程 | P2-a | SQLite 版本化迁移（user_version 或轻量 migration 表） | 中 | 数据层追平 |
| 工程 | P2-b | CONTRIBUTING.md + SECURITY.md（安全审计发现已有内容可写） | 小 | 文档补课 |
| 工程 | P2-c | JSON 日志注入 trace_id（logger↔trace_recorder 打通） | 小 | 可观测性闭环 |
| 前端 | P2-a | 知识图谱真渲染（ECharts graph 已在依赖内，替换 node-grid） | 中 | 名实相符 |
| 前端 | P2-b | 工具卡按类型分化（shell/file/browser 三类起步，不必 23 张全量；明细见 §13.1） | 中 | 聊天质感 |
| 前端 | P2-c | 审批卡双档（EXACT/模式）+ severity 展示（后端审批记忆已支持） | 小 | 治理前端对齐 |
| 工程 | P3-a | Tauri 桌面壳评估（Tauri 2 + 现有 Vite 前端可复用） | 大 | 广度补课 |
| 工程 | P3-b | ~~温度渐进索引真实现~~ → **已实现（勘误），仅需行为锁定测试**（计划 Task 8） | 小 | 认知修正 |
| 工程 | P3-c | telegram inline_keyboard 交互键盘 | 中 | 渠道深度 |
| 前端 | P3-a | 断线重连+replay 快进 | 中 | 长会话可靠性 |
| 前端 | P3-b | 消息队列（编辑/重排/暂停） | 大 | QP 可靠性闭环的核心，工程量大 |

**不应追清单**：DesktopOS 桌面壳（仿真属性大于功能价值）、23 张工具卡全量复制（3-5 张类型卡可拿 80% 质感，明细见 §13.1）、QP 的 vitest 刷覆盖率文化。

## 20. 结论

核心代码口径 NV 已追到 8.4 vs 8.5（差 0.1），全方位工程面 7.6 vs 8.5（差 0.9），前端功能面 7.1 vs 8.4（差 1.3）——**差距不在引擎，在交付，且越往外差距越大**。QP 的护城河是"配置面全 + Coding IDE + 治理双通道 + 发行四件套"；NV 则握有两个 QP 完全没有的域（NeurFlow 画布、心理认知五页）和三个聊天独门（检索进度、轮次编辑、TTS），以及在可观测性、测试真断言、LLM mock e2e 上的结构性优势。

补课路径清晰：极小成本项（修断链/接线 backup/修 compose/换真健康检查/清根目录）合计约把全方位推到 7.9、前端功能推到 7.4；中成本项（版本化迁移/真图谱渲染/工具卡分化/审批双档）到 8.1/7.7；重工程项（Tauri 桌面、消息队列、重连快进）按需立项。NV 应保持自己的结构性优势（测试真断言、11 语言、Prometheus metrics、有 LLM mock 的 e2e），不向东家的刷数文化看齐。三大纵深能力域（语音对话/记忆系统/工具层）的逐项对比见第三部分 §21-24。

---

# 第三部分：三大纵深能力域（09-02 追加）

> 方法：六路只读代理（QP 语音/记忆认知/工具层 + NV 语音/记忆认知/工具层），13 个记忆子维度逐项核查"有/无/骨架"。本部分修正了两个旧认知：①AGENTS.md "记忆 17 维分类"实为**情感四层 17 种**（emotion_hub_engine.py:104），记忆分类是 CategoryType 7 值（auto_classifier.py:27）；②AGENTS.md "evolution/ 部分骨架"已过时——genetic_engine.py 全文件 **0 处 pass 占位**，进化四件套是真实算法。

## 21. 语音对话（用户与 agent）

| 环节 | QP beta.5 | NV |
|---|---|---|
| TTS 引擎 | **5**：仅 SIP 渠道内阿里云 cosyvoice-v1（stt_tts.py:47，流式 :90），与渠道耦合、无独立 TTS 服务；前端 Audios 卡只下载不播放（MediaDownload/index.tsx:135） | **8**：4 引擎兜底链 moss-nano 本地 ONNX（models/tts/ 6 个 onnx，HuggingFace 自下载）→edge-tts→sapi5→mock（manager.py:32）；/synthesize+/status+/engines 端点；长文本 sanitize 2000；声音克隆参数入口（audio.py:38） |
| ASR | **8**：本地 whisper + OpenAI 兼容远端**双模**（audio_transcription.py:155/236），provider 可配置 UI；wechat/qq/dingtalk 渠道语音消息转文字 | **4**：**后端空转**——funasr 占位（funasr_engine.py:116 `_model=None`）、whisper 模型目录不存在（whisper_engine.py:30）；真实识别全靠浏览器 Web Speech API（ChatPage.vue:1399）；/transcribe 兜底大概率落 mock |
| 桌面语音闭环 | **5**：录音→/workspace/transcribe→填框（WhisperSpeechButton）；回复语音=下载卡；半自动 | **5**：录音→Web Speech/兜底→填框手动发（:1424-1426）；TTS 点按钮后自动播（:1577）；后端 enable_tts 自动 TTS 存在（post_chat_pipeline.py:660）但与前端两套路径不联动；无"语音模式" |
| 电话/实时渠道 | **9**：Twilio（twiml/voice/incoming + /voice/ws）+ SIP（pyvoip/LiveKit）三后端 | **4**：voice.py=Twilio 浅封装 178 行（TwiML 固定 alice 英文音色）；sip.py 552 行 dev 真/production 空壳（:392 仅 warning）；硬编码凭据 |
| 流式/打断 | **7**：Twilio ConversationRelay 流式+**barge-in 打断**（conversation_relay.py:144）；SIP 流式 STT（partial 结果）+流式 TTS+LiveKit 丢旧帧 | **2**：/synthesize-stream 有引擎无消费者（前端零调用）；无 WebRTC/无打断 |

**小结（QP ≈7.3 / NV ≈4.6，QP 反超）**：格局互补——QP 强"耳朵+电话线路"（ASR 双模、Twilio/SIP/LiveKit、barge-in），NV 强"嗓子"（TTS 引擎栈是双方唯一完整本地化 TTS）；双方桌面语音对话都是半自动（录音转写填框，无语音模式）。NV 最优先修复：①ASR 后端空转（funasr 占位+whisper 目录缺失=/transcribe 假兜底，诚实性问题）②流式 TTS 接前端消费者（引擎已备，死路径激活）③后端 enable_tts 与前端播放联动。

## 22. 记忆系统（13 子维度逐项）

| 子维度 | QP beta.5 | NV |
|---|---|---|
| 情感引擎 | **1 无**（grep emotion/mood/affect 全空命中） | **8 双引擎**：EmotionModule 每记忆情感状态 SQLite 持久化+规则分析+温度修正（emotion_module.py:65/247/338）；emotion_hub 四层 17 种情感+传导规则（emotion_hub_engine.py:104/68）；影响 MoE 漏斗过滤（moe_router.py:237）与上下文注入（injector.py:199）。坏味道：两套情感体系并存语义重复 |
| 记忆检索 | **8**：ReMe 三后端注册表+RRF 0.7/0.3+攒轮 flush（默认 5 轮，middlewares.py:200-219） | **8**：MemoryRetrievalChain 三适配器优先级链（memory_retrieval_chain.py:157）+unified_retriever 内部三路（MoE+RecallEngine+HebbManager）合并 |
| 向量模型参与检索 | **8**：远端 provider（openai/dashscope/ollama 免 key）+local embedding cache 3000；未启用降 BM25；向量空间指纹触发 reindex（reme_embedding.py:235） | **8.5**：**本地四级降级链** faiss→fastembed→ONNX→tfidf（unified_vector_store.py:96/173）；MoE VectorGatingNetwork 专家质心余弦激活（阈值 0.3）+专家内 L0 精确→L1 结构化→L2 重排→L3 向量兜底四层漏斗（moe_router.py:48/196） |
| 认知（元认知） | **1 无** | **7**：MetaCognition 认知负载/状态追踪（meta_cognition.py:100）；与 meta_cognition_layer/ 目录职责重叠 |
| 成长 | **1 无** | **7**：GrowthAnalyzer 多维成长记录（growth_layer/analyzer.py:91），前端 GrowthPage 973 行 |
| 经验 | **2**（近似物=技能沉淀流程知识） | **7**：CrystallizedExperienceManager+检索指标（crystallized_experience_manager.py:86）+经验-记忆融合（experience_memory_fusion.py:27） |
| 反思 | **1 无** | **6**：reflection 以 category 机制承载（五功能闭环修复后），无独立反思引擎 |
| 进化 | **1 无**（记忆语境） | **7.5**：evolution/ 四件套真实现（详见 §23 进化行） |
| 个性 | **1 无** | **5 部分**：前端 AgentPersonalityPage 有页；后端 personality 独立模块证据弱（性格特质条数据源待核） |
| 睡眠节奏 | **5**：heartbeat 定时唤醒 agent（HEARTBEAT.md 为 query，active_hours 08-22，crons/heartbeat.py）+ dream cron 每晚 23 点 LLM 整理（config.py:923）；heartbeat 双语义坏味道（runtime/heartbeat.py 是另一个 SSE 保活 tick） | **8.5**：SleepConsolidation 三职责（余弦聚类合并/温度衰减/整合，sleep.py:130/272/357/387）+auto_sleep_enabled 门控+浅睡/深睡阈值+梦境报告 CRUD（dream_mixin.py:15）；API 层 4 个 _generate_mock_* 残留 |
| 记忆合并 | **7**：auto_dream 四步 LLM 批处理（reme_config.py:419-457）——无增量保证 | **8**：聚类合并+MergeResult 写回（sleep.py:229/272；sleep_writeback.py:19）——同样只挂睡眠期，无在线合并 |
| 记忆冲突解决 | **2 无**（dream 隐式合并冗余，全靠 LLM 自觉） | **6**：ConflictDetector 否定词+相似度矛盾（conflict.py:18）+V2 实体重叠/演化链判定（conflict_detector_v2.py:30）；但 resolve 端点 **mock 兜底**（api/endpoints/sleep.py:237）——检测真、解决半成品 |
| 知识图谱 | **2**：仅 wikilink 文件引用图（file_graph），**但前端 3D MemoryGraphView 有真数据源** | **6.5**：TemporalKnowledgeGraph 时效事实（is_valid_at/supersede/expire+FactConflict，temporal_knowledge_graph.py:172/82）+DependencyGraph 真实现——**但 TKG 无人消费是孤岛**，前端图谱页无渲染：两头不通 |
| 遗忘（补充） | **1 无**：无衰减/TTL，daily 文件只增不减 | **8**：温度衰减 on_decay+温度分期（≥60 活跃，temperature.py:203/345）+睡眠衰减+遗忘档案 archive/recover（forgetting_recovery.py:37） |
| 隔离（补充） | **7**：每 agent workspace 独立 memory/ 目录；adbpg 后端默认 shared 静默跨 agent 泄漏（adbpg_memory_manager.py:46） | **8.5**：三层 SQL WHERE 强制+per-agent 实例索引（隔离审计已修） |

**小结（QP ≈6.5 / NV ≈8，NV 纵深优势）**：用户所列 13 个子维度中，**QP 只真有 3 项（检索/向量/合并）+睡眠部分项，NV 有 11 项**——情感引擎、认知、成长、经验、反思、进化、遗忘这套认知纵深是 QP 完全没有的版图。两个值得记住的反转：①**记忆哲学差异**——QP 是"文件中心"（MEMORY.md 核心+daily 日记+digest 抽象，wikilink 图），NV 是"SQLite+温度模型"；②**可视化反转**——QP 后端无 KG 但前端 3D 图有真数据（wikilink 文件图），NV 后端 TKG/DependencyGraph 真实现但前端不渲染、TKG 无人消费：NV 的图谱两头不通，QP 的图谱两头都通（尽管语义更浅）。坏味道对称：QP 有注册表静默回退、50 字符查询硬截断、adbpg 默认共享；NV 有 mock 端点残留、双引擎/双检测器/双元认知未收敛、衰减入口分散两处。

## 23. 工具层

| 维度 | QP beta.5 | NV |
|---|---|---|
| 体系全貌 | **8**：28 内置工具，`@tool_descriptor` 导入期自动注册（tool_registry.py:216）+子代理白名单装配；技能≠工具（元数据挂 toolkit，斜杠调用）。坏味道：装饰器+手动 import 两道工序与"免维护"自述矛盾 | **8**：**53 内置工具**，schema 单一真源+_builtin_dispatch 分派表+不变量测试机械拦截三次漂移史（tool_executor.py:123-130）；技能/MCP 经 tool_router 包装成可调用 |
| 主动使用 | **8**：ReAct 模型驱动+治理接线（三阶段引擎/审批记忆 v3 已详比，QP 领先） | **9**：治理四级裁决（v3 已比）+**肌肉记忆**：check_tool_memory 动态阈值三分裁决（≥阈值 auto_execute/≥0.7× suggest），命中≠成功防回声室（tool_memory_integration.py:220-287）——按历史成功率影响工具选择 |
| 主动创造技能/工具 | **7**：materialize_skill——agent 造技能（归一化名/冲突检查/安全扫描可拒/即时启用，make_skill_tools.py:174-330）；hub 安装仅人触发；**无运行时工具工厂** | **7**：_execute_create_skill——LLM 封装工具序列→即时注册→持久化冷启动可恢复（tool_executor.py:1068-1141）+skill_packer 从执行记录被动打包+nl_synthesizer；坏味道：create_skill name 无注入扫描、持久化失败静默分叉 |
| computer use | **7**：插件 25 文件（Windows/macOS，**无 Linux**）；observe_window 截图+可访问性树；每分钟限速；macOS Tauri helper 经命名管道传密钥（computer_use_runtime.rs） | **8**：ComputerUseManager 13 工具（截图/点击/键入/滚动/shell/文件）；**aria 语义点击** click_role/fill_role+generation 快照新鲜度令牌；WS computer_action 实时广播+前端分屏 ComputerUsePanel |
| 浏览器 | **8**：唯一 browser(code) 工具，代码在**会话级 kernel 子进程隔离面**执行（browser/execution/kernel.py）；SDK facade 全能力（click/goto/snapshot/locator）；handoff 终止信号是进程级全局（坏味道）；deprecated 双轨随包分发 | **9**：分层栈 url_guard（**16 网段** SSRF，逐 DNS 解析校验）←web_reach 5 工具（youtube 字幕/B站/RSS/V2EX/social）+browser_read（Playwright JS→Markdown）←camofox REST+Supervisor（语义快照/操作）；坏味道：Clash fake-ip 网段豁免与环境耦合 |
| **棘轮剪枝递归进化** | **1 无**：grep evolve/genetic/ratchet/fitness 全 src 零命中（仅 2 处无关注释） | **8 真实现**：genetic_engine.py evolve（精英保留+交叉+四种变异，**全文件 0 处 pass**）+棘轮闸门 validate/register_if_valid（:432/458——适应度不达标不注册，只进不退）+tool_lifecycle 用进废退状态机（ACTIVE→衰减→删除→复活，:108-193）+closed_loop 喂序列+post_chat 管线挂 _step_genetic_evolution；坏味道：进化失败软降级无人知、子代适应度取父代均值虚高 |
| 异步工具 | **8**：offload_on_deadline 超时转后台+延长死线+kill+hint 注回对话（_coordinator.py:87/266/442） | **8**：run_with_timeout 转后台**持引用防 GC**（注释明言工厂重建会双跑副作用）+pending hints 闭环+200 条上限 |
| MCP 接入 | **8**：治理白名单+沙箱要求（v3 已比：QP MCP 旁路 governance 深扫是弱点） | **8**：熔断（5 次开/300s 半开）+指数退避 1→60s+OAuth PKCE/DCR+ToolRouter 双注册同步；坏味道：MCP 工具在治理中硬拦沙箱致能力面受限 |

**小结（QP ≈6.8 / NV ≈8.2，NV 纵深优势）**："棘轮剪枝递归进化"这个词在 QP 全仓 grep 零命中——它是 NV 独有域：遗传引擎（精英保留/交叉/变异）+棘轮闸门（适应度不达标不注册）+用进废退状态机构成完整的工具进化回路，且 post_chat 管线真实挂载。NV 另一独有是肌肉记忆（工具选择受历史成败反馈）。QP 强在**执行隔离**（浏览器代码跑在会话级 kernel 子进程面）与**桌面宿主**（Tauri computer_use helper 命名管道），以及 agent 造技能的安全扫描闸（NV 的 create_skill 恰缺注入扫描——QP 这一点值得抄）。

## 24. 三域评分与补课要点

| 能力域 | QP | NV | 格局 |
|---|---|---|---|
| 语音对话 | **7.3** | 4.6 | **QP 反超**：电话/实时渠道+ASR 双模+barge-in；NV 仅 TTS 引擎栈领先 |
| 记忆系统 | 6.5 | **8** | **NV 纵深优势**：13 项中 11 项在握；QP 强在检索工程与文件图谱可视化 |
| 工具层 | 6.8 | **8.2** | **NV 纵深优势**：肌肉记忆+进化引擎+语义浏览器+安全分层；QP 强在执行隔离与桌面宿主 |

NV 三域补课要点（按性价比）：
1. **ASR 后端空转修复**（funasr 占位→真模型，或删假兜底改诚实降级）——诚实性问题，P0 级
2. **流式 TTS 激活**（/synthesize-stream 引擎已备，前端接消费者即得流式播报）
3. **conflict resolve 端点去 mock** + sleep API 四个 mock 生成器清理（后端检测器是真的，只差接线）
4. **TKG 图谱接线**（后端孤岛→检索消费+前端渲染，与前端补课 P2-a 真图谱渲染合并做）
5. 认知模块收敛（双情感引擎/双冲突检测器/双元认知/双遗忘入口——架构债，渐进）
6. 可抄 QP 两点：ASR provider 双模架构（本地+远端可配）、create_skill 的安全扫描闸
