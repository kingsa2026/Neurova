# Neurova Agent 工具生态对比与扩展计划

日期：2026-09-12 ｜ 状态：计划文档（未开工） ｜ 调研法：GitHub API 实测 star（当日）× Neurova 工具现状盘点

---

## 1. 背景与方法

用户诉求：以 GitHub star 为参考条件，找 agent 可用的工具，结合 Neurova 工具现状做补充与扩展。本轮交付计划文档，不实施。

调研口径：
- star 数据当日实测自 GitHub REST API（search + repos 两路），未做历史回溯；
- "agent 能用的工具"限定为可被 agent 直接调用的能力面（工具/MCP server/可编排管线），排除模型、框架、UI 产品本体；
- 与 Neurova 现状逐类比对后分三档结论：**已有**（不重复造）/ **可升级**（换更强引擎）/ **缺失**（新增）。

## 2. Neurova 工具现状（实测基线）

### 2.1 内置工具：56 个（`neurova/builtin_tools.py`）

| 分类 | 工具 | 数量 |
|------|------|------|
| 文件 | file_read / file_write / file_create / file_delete / file_edit / file_list / file_search | 7 |
| 桌面 CUA | computer_screenshot / click / type / scroll / dom_snapshot / click_element / set_value / shell | 8 |
| 浏览器 | browser_navigate / click / type / screenshot / extract_text / dom_snapshot / dom_read / click_role / fill_role / read | 10 |
| 画布工作流 | canvas_create / read / add_node / connect / set_config / move_node / remove_node / layout / run / list_nodes | 10 |
| 网络/垂直 | web_search / web_fetch / weather / youtube_transcript / bilibili_search / rss_read / social_search | 7 |
| 记忆/上下文 | recall_history / memory_search / voice_memory_search | 3 |
| 子代理 | spawn_subagent / subagent_status / list_agents | 3 |
| 音视频 | asr_transcribe / tts_synthesize | 2 |
| 规划/元 | planning / emotion_analyze / calculator / get_datetime / create_skill | 5 |
| 代码执行 | run_code（沙箱 `neurova/sandbox/exec_sandbox.py` + allow/deny/ask/sandbox 治理） | 1 |

### 2.2 三条扩展通道（均已在位，扩工具不炸上下文）

1. **MCP 客户端层**：`neurova/tool_layers/mcp_client.py`（MCPToolClient）+ `mcp_bootstrap`（启动即连）+ `mcp_config`（stdio/http/sse，transport 推断，**shell 命令拒绝表 P0-1 已建**）+ `mcp_oauth` + `mcp_resilience`。外部高星 MCP server 是**零核心改动的接入路径**。
2. **元工具懒加载**：`tool_search / tool_describe / tool_call` 三件套（tool_executor.py:942）——工具面再扩百倍，system prompt 仍只载三件套契约。
3. **技能层**：`create_skill` 工具 + skillhub.cn 市场已接（ADR0013 迁移收口 09-09）；组合型能力（如趋势监控）优先做技能，不动内置面。

### 2.3 本次扫描确认的硬缺口（代码级）

- `file_read` 不解析 PDF/Office 二进制（tool_executor 无 pdf/docx/xlsx 路径）——**文档理解是工具面第一缺口**；
- 无 git/GitHub 协作工具（仅 web_reach/credentials.py 含社媒凭据，无代码托管）；
- web_search 依赖外部搜索 API key，无自托管免 key 兜底。

## 3. GitHub 高星 agent 工具生态（当日实测）

### 3.1 网页获取与抓取

| 项目 | star | 能力 | 对 Neurova 判定 |
|------|------|------|----------------|
| firecrawl/firecrawl | 179,238 | 搜索+爬取+结构化，API 服务 | **可升级**（重，不内置） |
| D4Vinci/Scrapling | 80,319 | 自适应反爬框架（单请求→全站） | 可升级候选（web_fetch 后端） |
| unclecode/crawl4ai | 82,188 | LLM 友好爬虫 | **已有结论不内置**（08-31 调研，browser_read 轻量版替代，见记忆 [[neurova-browser-read-tool]]） |
| browser-use/browser-use | 114,261 | 浏览器 agent | 已对位：camofox + browser_* 10 工具 |
| microsoft/playwright-mcp | 37,024 | 官方 Playwright MCP | **可接入**（补 browser_* 交互长尾，走 MCP 通道） |
| ChromeDevTools/chrome-devtools-mcp | 51,686 | 浏览器调试/性能面向 coding agent | 登记观察（P2） |
| apify/crawlee-python | 9,514 | 抓取+浏览器自动化库 | 登记观察 |
| searxng/searxng | 36,792 | 自托管元搜索引擎（聚合多引擎，免 key） | **缺失→P1**（web_search 自托管 provider） |
| nickclyde/duckduckgo-mcp-server | 1,474 | DDG 搜索 MCP | P1 顺带（searxng 失败时的轻量兜底） |

### 3.2 文档理解（最大缺口品类，头部星极高）

| 项目 | star | 能力 | 判定 |
|------|------|------|------|
| microsoft/markitdown | 182,693 | Office/PDF/图片→Markdown，纯 Python、本地可跑 | **缺失→P0 首选** |
| docling-project/docling | 66,283 | 版式感知文档解析（表格/阅读序），偏重 | P1（markitdown 啃不动的复杂版式） |
| datalab-to/marker | 39,676 | PDF→markdown/JSON 高精度 | 登记（与 docling 同生态位，二选一） |
| firecrawl/anydoc | 21,191 | Word/PPT/Excel→内容 | 登记 |
| zcaceres/markdownify-mcp | 2,989 | markitdown 的 MCP 包装 | P0-1 交付形态参考 |

### 3.3 代码协作与库知识

| 项目 | star | 能力 | 判定 |
|------|------|------|------|
| upstash/context7 | 61,899 | 各库**最新版**文档实时检索（MCP） | **缺失→P0-2 首批** |
| DeusData/codebase-memory-mcp | 42,990 | 代码库索引化语义检索 MCP | P1（NeurFlow IDE 化配对评估） |
| oraios/serena | 29,194 | 语义代码检索/编辑工具包（LSP） | 同上合并评估 |
| github/github-mcp-server | 32,880 | GitHub 官方 MCP（repo/PR/issue/CI） | **缺失→P0-2 首批** |
| modelcontextprotocol/servers | 90,257 | 官方参考 server 集（filesystem/git/fetch/memory 等） | P0-2 白名单来源 |
| punkpeye/awesome-mcp-servers | 94,800 | MCP 目录 | 白名单来源 |

### 3.4 研究与知识

| 项目 | star | 能力 | 判定 |
|------|------|------|------|
| khoj-ai/khoj | 37,278 | 自托管"第二大脑"检索问答 | 登记（与 KB/RAG 重叠） |
| assafelovic/gpt-researcher | 29,414 | 深度研究管线（规划→多轮检索→引用报告） | **缺失→P1**（做成 deep_research 工具，复用 planning+web_search+artifact） |
| virattt/dexter | 27,594 | 金融深度研究 agent | P2 |
| Alibaba-NLP/DeepResearch | 19,931 | 开源深研模型+管线 | P2（管线结构参考） |
| sansan0/TrendRadar | 62,189 | 舆情/趋势聚合（多平台+RSS+推送） | **缺失→P1**（rss_read×scheduler×通知的组合技能，不引本体） |

### 3.5 执行环境与其他

| 项目 | star | 能力 | 判定 |
|------|------|------|------|
| e2b-dev/E2B | 13,758 | 云端沙箱执行环境 | 已有 run_code 本地沙箱，登记 |
| mem0ai/mem0 | 65,141 | 外部记忆层 | **不引入**：自研 17 维记忆+09-05 暴增事故，外部记忆层是倒退（§6） |
| getzep/graphiti | 30,821 | 实时知识图谱记忆 | 同上，登记观察 |
| bytedance/UI-TARS-desktop | 38,935 | 多模态桌面 agent | 已对位：09-12 CUA 升级（desktop_uia+ActionResult） |
| LibreTranslate/LibreTranslate | 16,350 | 自托管翻译 API | P2 可选 provider |
| modelscope/FunASR | 20,282 | ASR 工具包 | **已用**（模型栈 1.4.13） |
| bytebase/dbhub | 3,499 | token 友好数据库 MCP（90+ 库） | P1（结构化数据查询入口） |
| homeassistant-ai/ha-mcp | 4,693 | 智能家居 MCP | P2 登记（生态位小） |
| n8n-io/n8n | 204,042 | 工作流自动化平台（含 MCP） | **不引入**：与 canvas/NeurFlow 平台级重叠（§6） |

## 4. 差距分析结论

Neurova 工具面在**网页获取、浏览器/桌面 CUA、记忆、音视频、工作流画布**五域已达或接近头部水位；差距集中在三处：

1. **文档理解**（markitdown 183k 品类 vs 本地 file_read 只会读文本）——用户把 PDF/Word 丢进对话，agent 现在只能看文件名；这是最高星、最易补、最贴主场景的一条。
2. **代码协作**（github-mcp-server 33k / context7 62k 品类 vs 本地 git/GitHub 零工具）——编码场景是桌面 agent 主战场，NeurUI 已在 IDE 化，工具面却没接上。
3. **研究编排**（gpt-researcher 29k / TrendRadar 62k 品类 vs 只有散装检索工具）——planning+web_search+artifact 三件都在，缺一条把它们串成"引用可溯源报告"的管线。

另有一条横切红利：**MCP 精选白名单**。Neurova 的 MCP 通道成熟（含安全拒绝表+身份注入+防火墙），上述多数能力（github/context7/dbhub/playwright）以 MCP 形态接入**零改核心**，与原生工具互补不冲突。

## 5. 扩展计划

> 全程纪律（AGENTS.md 修复教义）：先红绿灯补契约测试；MCP 接入不得绕 `mcp_config` shell 拒绝表与 `tool_layers` 防火墙；身份注入走真实 `_current_user_id`（09-11 tool_executor 根修契约）；净 LOC>0 需在提交说明列出超出行数去向。

### P0（补硬缺口，复用现有机制）

| # | 项 | 落地方式 | 涉及文件 | 验收 |
|---|----|----------|----------|------|
| P0-1 | `file_parse` 文档理解工具（pdf/docx/xlsx/pptx→markdown） | 原生工具，引擎=markitdown（纯 Python 轻依赖；图片走 vision 模型已有通道）；与 file_read 分工=文本 vs 二进制，互引 description 写"何时不用" | builtin_tools.py、tool_executor.py（分发）、`neurova/file_parse/`（新模块）、依赖入 requirements | PDF/DOCX/XLSX/PPTX 四类样本先红后绿；大文件分段；编码/损坏文件错误诚实 |
| P0-2 | **精选 MCP 白名单**（首批：github-mcp-server、context7、dbhub、官方 servers 的 git/fetch） | 不改核心：内置一份默认 MCP 配置模板（命令/包名/凭据槽），安装时用户确认；凭据分桶复用 web_reach credentials 模式 | mcp_config.py、新 `neurova/tool_layers/mcp_catalog.py`、前端渠道/MCP 管理页增"工具包"入口 | 白名单 server 起得来、工具出现在 tool_search 可发现集、防火墙与 OAuth 契约不破 |
| P0-3 | `git_*` 本地 git 工具族（status/diff/commit 经治理） | 原生工具，复用 run_code 同套沙箱+allow/deny/ask 治理（写操作默认 ask）；GitHub 远程操作交给 P0-2 github-mcp-server，不重造 | tool_executor.py（复用 exec_sandbox 通道） | clone 外目录守卫复用 workspace_path 契约（09-08 relpath 根修）；写命令治理拦截测试 |

### P1（能力面扩展）

| # | 项 | 落地方式 | 验收 |
|---|----|----------|------|
| P1-1 | `deep_research` 管线工具 | 编排既有件：planning 拆解→web_search/web_fetch（或 browser_read）多轮→产出带引用报告（artifact 卡片通道）；结构参照 gpt-researcher 的 plan→iterate→report，不引其代码 | 给定研究主题产出含 URL 引用的 MD 报告；中途工具失败降级诚实（不静默截半） |
| P1-2 | web_search 自托管 provider（searxng） | llm/搜索 provider 管理已有，加 searxng provider（本地 URL 配置）；失败回退现有 key provider | 无 key 配置下搜索可用；provider 元数据（能力检测六类）同步 |
| P1-3 | 趋势/舆情监控组合技能 | rss_read×AgentScheduler×站内通知 组合为出厂技能模板（参照 TrendRadar 聚合形态，不引本体） | 定时→聚合→推送全链 live 过 |
| P1-4 | 结构化数据查询 | dbhub MCP（P0-2 白名单内）+ 只读 SQL 治理（写一律 deny） | 查询返回 token 友好截断 |

### P2（登记观察，不排期）

办公邮件/日历（**无高星开源标杆**，最大者仅 ~320 star；等生态成熟或走整合平台，不裸写）、财经数据（dexter 模式）、LibreTranslate、chrome-devtools-mcp、UI-TARS 对标回访、ha-mcp、Scrapling（web_fetch 反爬升级候选）。

## 6. 明确不做（防镀金）

1. **不引入外部记忆层**（mem0 65k / graphiti 31k / letta）：自研 17 维记忆体系 + 09-05 睡眠巩固暴增事故刚收口，外挂记忆层=口径分裂。
2. **不内置 firecrawl/crawl4ai**：08-31 调研结论仍成立（crawl4ai 重依赖、自建服务运维成本>收益，browser_read 轻量版覆盖主场景）；firecrawl 同理。
3. **不引入 n8n/activepieces**：平台级重叠 NeurFlow/canvas，违背"采纳只提升不下降、不影响核心框架"约束。
4. **不抄 UI-TARS 模型方案**：09-12 CUA 升级（desktop_uia+ActionResult 契约）已对位。
5. **P0-2 白名单不是"全都接"**：每个 server 须过 mcp_config 安全拒绝表 + 工具层防火墙 + 身份注入三关，接不进的不接。

## 7. 实施顺序建议

P0-1 → P0-3 → P0-2（依赖用户安装确认交互）→ P1-1 → P1-2 → P1-3 → P1-4。P0 三项互不依赖，可并行但 P0-2 前端入口放最后收口（渠道页/MCP 页已多线改动中，避并行冲突——09-11 并行会话教训）。

---

## 8. 实施记录（2026-09-12 P0~P1 开工轮）

红绿灯 TDD 全项落地，交付明细与**对计划的三处收敛修正**（均为实施时实测代码后的修正，非简化）：

| 项 | 状态 | 测试锚点 | 对计划的修正与理由 |
|----|------|----------|-------------------|
| P0-1 file_parse | ✅ 12/12 | tests/unit/tools/test_file_parse.py | **引擎修正**：markitdown 未装且引新依赖；实测 `neurova/attachment_parser.py` 已实现 PDF/DOCX/XLSX/PPTX/RTF/ODF/HTML 全谱解析（附件链路在用）→ 工具做其薄封装，零新依赖（只提升不下降） |
| P0-2 catalog 后端 | ✅ 17/17 | tests/unit/tools/test_mcp_catalog.py | **首批收敛**：官方 servers 的 git/fetch 与 P0-3 原生 git + web_fetch 重叠→剔除；保留 github(Docker)/context7(npx)/dbhub(npx) 三真缺口。**安全门根修**：抽 `_register_mcp_server` 共享入口，connect 与 install 单路径（防两条注册链漂移，同 schema↔分派表历史教训） |
| P0-2 前端入口 | ✅ vue-tsc+1353 全绿 | ToolLayerPage「工具包」页签 | 安装弹窗按条目 required_secrets 动态收凭据；docker/只读警示；i18n 4 键×11 语言同步 |
| P0-3 git 工具族 | ✅ 31/31 | tests/unit/tools/test_git_tool.py | **形态收敛**：`git_*` 十族→单 `git` 工具（command 含前缀）。省 10 个 schema 位、治理规则按命令文本命中与 computer_shell 一致；写动词 HIGH→ASK、RCE 形态 CRITICAL→DENY 加在 **tool_guard 规则源**（裁决根因位），执行体只守输入域契约（子命令白名单/仓库锚点唯一入口 path） |
| P1-1 deep_research | ✅ 7/7 | tests/unit/tools/test_deep_research.py | **设计修正**：不做重型 LLM 编排引擎（阻塞整轮+重复 spawn_subagent）→ 有界多源采集器（检索→去重→抓正文→编号引用料包），综合交回在环主 LLM；工具内零 LLM 调用 |
| P1-2 searxng provider | ✅ 5/5 + 既有 web_search 32/32 | tests/unit/tools/test_web_search_searxng.py | **假设修正**：计划"搜索 provider 管理已有"不成立（web_search 系硬编码 Bing 抓取）→ 落为 settings.searxng_url 单配置源优先 + 失败回退 Bing，backend 字段诚实标注 |
| P1-4 只读 SQL | ✅ 契约测试并入 catalog | 同上 read_only_required | **反剧场落点**：dbhub 无 `--readonly` CLI（官方文档证实）；代理层正则匹配 SQL 写关键字=误伤所有 MCP 文本+mcp_config 注释点名的安全剧场 → 只读契约固化到 DSN 必须只读账号 + `read_only_required` 标记供前端强提示 |
| P1-3 趋势监控 | ⏸ 延期 | — | 依赖 AgentScheduler 暴露 LLM 可调用工具（现状调度器无工具面，[[neurova-scheduler-status]] 为 delicade 子系统）；组合技能需先补 scheduler_create 工具 + 通知链实测，独立排期避免与 MCP 重构并行冲突 |

回归结论：后端 tools 套件 comm-diff HEAD 基线**零新增失败**（49 项预存债不变，含并行会话 MCP 重构删除 mcp_client_manager 所致）；security 910 全绿（tool_guard 新规则无涟漪）；前端 1555+1353 全绿；`vue-tsc --noEmit` 干净。

净 LOC 说明（修复教义第 2 条要求列去向）：本批为**新功能实施**非 bug fix，净增=7 个工具/端点页签的正当实现体 + 计划文档 §8 修正记录；无表面抹除、无降级断言。

---

## 9. 复核轮（2026-09-12 收口，用户要求"确保无 bug/无断点/闭环/前端 UI 匹配"）

端到端复核抓出并修复 5 处，其中 3 处为**实施轮未覆盖到的预存/衍生缺陷**（红绿灯补齐）：

| # | 缺陷 | 性质 | 修复 | 回归测试 |
|---|------|------|------|----------|
| 1 | `POST /mcp-servers/{id}/test` 后端**从未实现**，前端"刷新"按钮一直 404 | 预存契约断裂（ToolLayerPage 早已调用） | 实现端点：按持久化配置重连并返回实时状态 MCPServerInfo | test_mcp_catalog 未知→404 |
| 2 | 前端 `MCPServer` 读 `id`/`tool_count`，后端 `MCPServerInfo` 实际返回 `server_id`/`tools_count` | 预存契约错位（servers 卡片 key/测试/删除全打空） | interface + 模板 6 处对齐真实字段；卡片显 transport（stdio 工具包 url 空不再空白） | 见 §8 P0-2 前端 |
| 3 | register 弹窗按 URL 注册恒 400：后端 `MCPServerConnectRequest.transport` 默认 `stdio`→validate 要 command | 预存（非我改动引入，但在扩展页上） | 前端 URL 注册显式 `transport:"http"` | test_register_http_url_not_rejected_as_stdio |
| 4 | `deep_research` 串行扇出最坏 275s，撞 `run_with_timeout` 默认 60s **中途转后台**（整轮断点） | 实施轮缺陷 | 检索并发 + 抓取信号量(6)并发；表内超时 deep_research=180/file_parse=120/git=120；file_parse 入并发安全名单 | TestToolTimeouts；git e2e 写→ASK/读→放行经真实 `_execute_single_tool` |
| 5 | 治理闭环此前仅测 `_execute_builtin_tool`（绕过预检） | 实施轮测试盲区 | 补端到端：`_execute_single_tool("git", commit)` 经 tool_guard 真实单例→pending_approval；确认审批重放 `skip_governance` 不再二次 ASK（无审批死循环） | TestGitGovernanceEndToEnd |
| 6 | register 弹窗 auth_token 输入框不起作用（复核轮报告如实披露的遗留项，用户指示修复） | 预存断点：后端 `MCPServerConnectRequest` 无承载字段，前端载荷的 auth_token 被 pydantic 静默丢弃；协议层 `_open_session`（httpx/sse_client）本已消费 `config.headers`，断点仅在请求体 | 后端补 `headers` 字段贯通（validate/持久化/连接实参全链）；前端 `buildMCPRegisterPayload` 纯函数：token→`Authorization: Bearer`，空值不发；token 不回显于 MCPServerInfo | tool-layers-register.test.ts(4) + test_register_with_auth_token_headers_persisted_and_used（持久化实参+连接实参+不回显三点锁死） |

闭环确认（复核通过项）：新工具经统一 `execute→_governance_precheck`（治理/审批/肌肉记忆全链生效）；schema↔分派不变量 60/60；审批重放不循环；deep_research/file_parse 无 shell 注入、只读语义。

终态：后端 tools comm-diff HEAD 零新增失败（49 预存不变），security+我的用例 1007 绿；前端 vue-tsc 净、vitest 1353 绿。P1-3 趋势监控维持延期（依赖 scheduler 工具面，非本轮改动可闭环）。


