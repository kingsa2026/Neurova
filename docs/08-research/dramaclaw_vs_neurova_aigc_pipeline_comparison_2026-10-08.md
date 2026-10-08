# Neurova × dramaclaw 代码级对比（2026-10-08）

> **对象**：https://github.com/dramaclaw/dramaclaw （6711★ / 819 fork / 109 open issues；后端包名
> `src/novelvideo/`；Python + FastAPI + React；self-hosted）。克隆快照 commit **`e133316`**（2026-10-08），
> 浅稀疏检出 `src/ frontend/ docs/ tests/`；下文对方锚点一律相对 `src/novelvideo/`。
> **本方基线**：`neurova/aigc_studio*`、`neurova/collaboration*`（画布 + neurflow）、
> `neurova/llm/generators*`、`neurova/api/endpoints/{studio_api,neurflow_api,collaboration_api,generation}.py`、
> `NeurUI/src/modules/collaboration*`。
>
> **文档定位**：研究参考类，仅作背景，**不可作事实源**（`AGENTS.md` §2 原创性与自主性条款）。
> 本文**不授权任何代码搬运**——对方全仓默认 Elastic License 2.0（§2.1），且 §2 禁止引用、模仿或对齐
> 第三方实现。文中「对方有 X」只用于**提问**，不用于**规定本仓怎么做**；所有候选项的立项理由
> 一律写成本仓自身可核实的断点或缺口。
>
> **证据分级**：本仓侧每条锚点由主代理 `grep`/`Read` 亲验；对方侧锚点来自同一克隆内四个只读子代理实读，
> 主代理抽验了影响结论的方向性条目、**未逐行复算**（三态清单见 §8）。
>
> **本文取代同日早先那份单侧盘点**（差集结论与候选清单已按代码级证据刷新，见 §6、§7）。

---

## 0. 一页结论

1. **代码整合不可行，三道闸都是关的**：Elastic-2.0 许可证、本仓 §2 原创性条款、§6/§7 双源纪律。
   这与代码质量无关，先于一切评估成立（§2）。
2. **「本仓缺前端无限画布」的判断已被代码级证据推翻并更正**：本仓画布前后端齐备且已接线（§3.2），
   且在多数编排维度上**领先**对方（§3.4–§3.7）。
3. **格局一句话**：本仓胜在**闭环纪律与治理面**（重启续拉、类型校验、单一写入口、密钥加解密、
   归属 404 同构、自动选路、发布/渠道/11 语言）；对方胜在**影视域的物质化深度**（真三维导演场景、
   VLM 一致性校验套件、情感配音通道、画布文件持久性）。「有没有代码」这层对方常胜，
   **「代码有没有被消费」这层本仓常胜——而对方恰好也在多处栽在同一条上**（§5）。
4. **两条差集结论被刷新**：`持久三维场景` 从「暂缓」上调（它不依赖外部服务商端点，是
   「我方几何数据 + 消费链」）；`配音情感通道` 门槛低于原判（对方也只是文本提示透传，无 SSML/prosody）。
5. **本次对比新抓出本仓三条自有断点**（与对方无关、独立成立）：`negative_prompt` 三层只写不读、
   画布写盘无 fsync 且 `.tmp` 名固定、以及同日已记的 `@vue-flow/*` 零 import 与孤儿 viewport 路由（§5、§6）。
6. 本文只出报告与候选清单，**未改任何代码**；C1–C9 待拍板。
   **2026-10-08 当日追记**：C1 已按用户两项拍板（闸强度取「硬阻断点名」、`atmosphere` 本批注入）
   落地为 `5336b6f5`，判据入受保护子集为 `077ce3fd`，落账见台账 §6-81；C2–C9 仍待拍板。

**逐维评分（10 分制，仅覆盖本文比到的维度）**

| 维度 | Neurova | dramaclaw | 胜负手 |
|---|---|---|---|
| 任务编排与重启恢复 | 9.0 | 6.5 | 对方 `on_startup` NoOp，重启不接管远程任务 |
| 生成协议接入 | 8.5 | 7.0 | 本仓原生面广 + 纯函数可测；对方端点内联巨型类 |
| 画布编排与校验 | 8.5 | 7.0 | 对方无编译桥、保存不校验节点类型 |
| 画布数据持久性 | 6.0 | 9.0 | 对方 fsync+fence+排他锁+幂等键+100 份历史，本仓全缺 |
| 影视物质化（3D/校验/风格） | 3.0 | 8.0 | 本仓此项为真空 |
| 配音与情感 | 5.0 | 7.0 | 本仓无 emotion 通道 |
| 检索增强注入 | 7.5 | 8.0 | 对方按项目图谱集直供生成提示词 |
| 凭据与安全治理 | 8.5 | 5.5 | 对方 api_key 明文落库、无日志脱敏 |
| 归属与多租户 | 8.0 | 7.0 | 对方 403 语义可枚举项目名 |
| 交付与运营面 | 9.0 | 4.0 | 对方无发布、无 IM 渠道、3 语言、备份无调度 |
| 测试与可测性 | 8.5 | 6.5 | 测:源 本仓 1.16 : 对方 0.72 |

---

## 1. 规模口径（双侧 `find` + `wc -l` 实测，先说清可比性）

**本仓全仓**：后端 `neurova/` 1032 py / 354,428 行；测试 `tests/` 2142 py / 411,276 行
（**测:源 = 1.16:1**）；前端 `NeurUI/src` 329 文件 / 118,162 行（不含测试）。

**本仓同域切片**（AIGC 视频引擎这一域）：`aigc_studio` 5/1,289 + `collaboration` 65/25,458 +
`llm/generators` 8/2,442 + 四个 REST 面 4,005 ≈ **33,194 行**；画布前端 `modules/collaboration`
19 文件 / 5,291 行；同域测试 78 个 py 文件。

**对方**：后端 374 py / 182,808 行；测试 356 py / 132,286 行（**测:源 = 0.72:1**）；
前端 743 ts/tsx / 218,066 行 + 469 个前端测试文件。域内分布（py 文件/行）：
`api/` 38/39,098 · `generators/` 26/27,825 · `seedance2_i2v/` 14/6,198 ·
`freezone/` + `api/routes/freezone.py` 30,594（**单个路由文件 14,814 行**）· `task_backend/` 30/10,317 ·
`verification/` 41/8,847 · `director_world/` 19/9,178 · `chat/` 9/8,147 · `agents/` 12/6,905 ·
`utils/` 27/6,534 · `ports/` 31/3,573 · `audio/` 2/649 · **`assets/` 1/6（空壳）** · `styles/` 0 py。

**读法**：整仓本仓更大、测试比更高；但对方整个项目基本就是这一个域，故**同域投入约为本仓 5.5 倍**。
这既解释了「物质化深度」对方有而我们没有，也解释了对方巨型单文件问题为何比我们突出。

---

## 2. 三道闸（为什么不能整合代码）

### 2.1 许可证硬闸
- 该仓**根目录没有 `LICENSE`**；`REUSE.toml` 对通配 `"**"` 打 `SPDX-License-Identifier = "Elastic-2.0"`、
  `precedence = "aggregate"`，版权行 `2026 SuperTale contributors`；
- `LICENSES/` 仅两份全文：`Apache-2.0.txt`（10,926 B）与 `Elastic-2.0.txt`（3,860 B）；Apache override
  只覆盖 `LICENSES/Apache-2.0.txt` 自身与 `deploy/sandbox/**/codex-linux-sandbox` 两个 vendored 二进制；
- GitHub API 的 `license.spdx_id` 因此返回 `NOASSERTION`（name: Other）。

**推论**：ELv2 是 source-available、**不是开源许可证**，限制项含「不得将软件作为托管服务提供给第三方」
与「不得分发提供同类功能的修改作品」。本仓是对外交付产品（`create_github_release.py`、
`docs/03-user-guide/` 11 语言、`helm/` + `docker-compose.yml`）：搬代码进本仓并分发即撞后者，
把它当服务连出去即撞前者。**没有「注明出处即可用」的口子。**
对方自身 `ce-allowlist.toml` 的 `ee-terms` 守栏、`scripts/lint_ce_imports.py` 与
`scripts/check_ce_port_closure.py`（注释明示「刻意零豁免——命中即失败，无放行口子」）也印证边界是有意划的。

### 2.2 本仓原创性闸
`AGENTS.md` §2：严禁在代码注释、技术文档或提交信息中引用、模仿或对齐任何第三方项目；外部依赖只作
功能依赖登记（版本、许可、用途），不引入其设计标准；研究参考类文档仅作背景、不可作事实源。
**本文即按此条款而写，其本身不构成落地依据。**

### 2.3 双源闸
§6 单一事实源（发现第二份定义时收口并删另一份，而不是两边都留）、§7 同功能先比后合
（判据：该功能仓内只剩一处被消费）。本仓该链路**已交付且已接线**（§3.1），再引入一套＝造双源，
且新那套自带许可证污染。**这条闸在 §2.1 之外独立成立**——即便对方某日改 Apache，
§7 仍要求「只剩一处被消费」而非并存。

---

## 3. 本仓侧存量基线（对比的分母，全部实测）

### 3.1 AIGC 流水线：剧本 → 成片，端到端已在
- 域声明：`neurova/aigc_studio/__init__.py:2-11`（小说→分集剧本→资产→分镜→批量图/视频→TTS/字幕→
  FFmpeg 导出；生成通道复用 `llm.generators.protocols` 单源）
- 四段提示词：`aigc_studio/llm.py:13,20,27,35`（`SCRIPT_REWRITER`/`EXTRACTOR`/`STORYBOARD_BREAKER`/`PROMPT_GENERATOR`）
- 编排：`services.py:63` `split_script`、`extract_assets`、`break_storyboards`、`:305` `generate_shot_images`
  （@角色参考图注入）、`:379` `generate_shot_videos`（i2v 提交 + 账本 `batch_key=episode`）、
  `:501` `synthesize_narration`、`:569` `merge_episode`
- 风格与画幅项目锁：`services.py:295` `_inject_style`（调用点 338、482）
- 持久层：`aigc_studio/store.py:26-97` 十表（projects/episodes/characters/scenes/props/storyboards/
  assets/merges/runs）；定妆 seed `:46`、氛围/音效 `:66`
- REST：`api/endpoints/studio_api.py:2` `/api/v1/studio/*`；`:121` `_spawn_run`
  （一次请求＝一行台账＝一个生命周期拥有者）；`:172` 取消双路收口
- 协议单源：`llm/generators/protocols.py:1-30`，图像 3 条（openai_compat/ark/dashscope）+ 视频 5 条
  （wan/seedance2/veo/agnes/sora，`:55-72`）；`:3-4` 原文「六条真实协议接入地址规则（禁止虚构端点）」
- 降级诚实：缺 FFmpeg 落连播清单 manifest；BGM 无实测服务商则维持台账 blocked（`services.py:571-575` 注释自证）
- 节点化：`neurflow/drama_nodes.py` 八节点（`:1121-1129` 执行器表，实测 `"type": "builtin:` 计数＝8）、
  一键成片模板 `templates/short_drama.py:16-29`、启动期预注册 `api/app.py:1111-1130`
- 批次0 曾删除六个「从未真实产出的虚构端点」（`llm/generators/__init__.py:11-12`）——
  本仓协议矩阵的准入纪律是**实测**，任何新能力不得绕过

### 3.2 无限画布：前后端齐备（§0.2 更正的依据）
- 页面本体 `NeurUI/src/modules/collaboration/CanvasDesignerPage.vue` **2,803 行**；实现方式是
  **手写 viewport 平移+缩放**，非渲染库：`:105` 注释自证、`:625` `viewport = reactive({zoom,panX,panY})`、
  `:626-627` 缩放界 0.25–3、`:634` `screenToCanvas`、`:644` `zoomAt`（锚点缩放）、`:669` `onWheel`
  （Ctrl/Cmd 缩放、Shift 换向平移）、`:710-718` 空格拖拽、`:676-679` `fitView`、
  `:742` `transform: translate() scale()`、`:747-752` 网格底纹随缩放改格子尺寸并随平移移相位、
  `:237` 缩放百分比、`:248-250` MiniMap（纯函数 `canvasMinimap.ts:40` + `MiniMap.vue`）
- 视口持久化已闭环：`:2013`/`:2054` 保存 `{x,y,zoom}`、`:2290-2297` 恢复；写入通路两条——画布快照侧
  `PUT /v1/collaboration/canvas/{id}`（`collaboration_api.py:630`，viewport 随 payload 进 store，
  `canvas_store.py`/`canvas_ops.py`/`canvas_bridge.py` 对 viewport **零语义**、纯透传）；
  从「定义」打开侧 `collaboration_api.py:590-592` 从 `wf.metadata.viewport` 回带，写点是
  `neurflow_api.py:1000-1005`。前端类型 `api/modules/collaboration.ts:147-148,404-405`
- 编辑 affordance 同目录实测存在：`canvasClipboard.ts`、`canvasFullscreen.ts`、`canvasSelection.ts`、
  `canvasPan.ts`、`canvasSubBlocks.ts`、`canvasRunErrors.ts`、`canvasStores.ts`、`MiniMap.vue`、
  `CanvasNLDesigner.vue`（自然语言生画布）、`AnnotationDrawer.vue`、`DebugPanel.vue`、`MockEditor.vue`、
  `TriggerManagerDrawer.vue`、`WorkflowVersionsDrawer.vue`
- 路由已接线：`router/index.ts:262-272`
- 后端三层全有消费者：`canvas_store.py:1-15`（快照文件持久化 + 乐观锁）、
  `canvas_ops.py:1-15`（**Agent 交互式操作画布的唯一写入口**：语义 op + `base_version` 乐观锁实时抢占 +
  `canvas_op` 事件广播）、`canvas_bridge.py:1-10,71,168-171`（双向桥；`:171` 明示
  「工作流＝无限画布工作流，画布快照是用户数据的唯一可编辑形态」）
- REST 面 `/v1/collaboration`（`api/endpoints/__init__.py:249`）：`collaboration_api.py:517` 创建、
  `:536` 列表（personal/project/agent 三视图）、`:599` 读、`:630` 全量存（带 `base_version`）、
  `:664` from-nl、`:709` 语义 ops、`:807` 删、`:874` run、`:1019` 运行结果；`/v1/neurflow`（`:298`）
- Agent 同一写入口的工具族（实测符号）：`canvas_create`/`canvas_read`/`canvas_add_node`/
  `canvas_connect`/`canvas_move_node`/`canvas_remove_node`/`canvas_set_config`/`canvas_layout`/
  `canvas_list_nodes`/`canvas_run`；前端 `CanvasDesignerPage.vue:2304-2322` 订阅 `canvas_op` 增量应用
- 图模型：`neurflow/models.py:94` `NodePort`、`:105` `NodeDefinition`、`:129-141` `WorkflowNode.position`
  与节点级 `mock_output`、`:145` `WorkflowEdge`（handle + condition）、`:169` `WorkflowDefinition`
- 画布可跑短剧节点：`canvas_bridge.py:46-53` 批次4 根因修复（校验前 `sync_all()`，否则新进程里含
  drama 节点的画布被按「未注册类型」拒）
- ComfyUI 定位：`neurflow/comfyui_nodes.py:1-9` 把 ComfyUI 核心节点注册进本仓 NodeRegistry
  （`comfyui:` 前缀），`canvas_bridge.py:170-171` 是「把 ComfyUI 定义落成画布」——**不提供独立图形编排器**
- 测试厚度：Python 侧画布主题 41 文件命中（`tests/unit/api/test_collaboration_canvas.py`、
  `test_canvas_ownership_api.py`、`test_canvas_ops_api.py`、`test_canvas_definition_bridge_api.py`、
  `test_canvas_from_nl_isolation.py`、`tests/unit/neurflow/test_canvas_bridge.py`、
  `tests/unit/collaboration/test_canvas_ops.py` 等）；前端 vitest 三份
  （`canvasRunDispose.test.ts`、`canvasEdgesStyle.test.ts`、`CanvasDesignerTheme.test.ts`）
- **须与另一功能区分**：`docs/03-user-guide/MIND_EXPANDER_USAGE.md:5` 也写「无限画布」，那指
  Mind Expander（代码库可视化工作区），与 neurflow 画布**不同域**，本次不判为双源。

---

## 4. 逐机制对比（双侧锚点）

### 4.1 任务编排与重启恢复 ★★★ —— 本仓胜
- **对方**：阶段＝按 `task_type` 注册的 runner（ingest/script/identity/episode_assets/character_image/
  prop_reference/scene_reference/sketch/render/video/audio/stage_asset…，`task_backend/registry.py:26-52`、
  `run_core.py:680-697`），无集中阶段枚举；完成度**反推**（`api/routes/pipeline.py:75-204` 以
  `status==completed` 或产物文件齐全推下一步）；状态机＝裸字符串 `task_states.status`
  （`task_state.py:52-53,226`），**无转移校验守卫**。载体 Celery（`shared/runtime_env.py:16`，
  队列分道 default/video/world/ffmpeg，`queues.py:5`）。
  **重启恢复：无续拉/重轮询**——`on_startup` 是 NoOp（`ports/local/lifecycle.py:6-11`），仅惰性僵尸清扫
  把 inline 早于启动的行与 celery 超 `CELERY_STALE_TTL=40min` 未更新的行**一律判 failed** 并提示重新发起
  （`task_state.py:1340-1395`，:1367,1383）。即远程已提交任务重启即丢。
- **本仓**：未决任务重启续拉循环 `recovery_tick` + `start/stop_generation_recovery`
  （`llm/generators/recovery.py:10-12,111,128,145`），**随服务启动接线**（`api/app.py:1093-1095`）；
  provider 凭据缺失的旧任务诚实标失败而非静默；终态口径 `RUN_TERMINAL_STATUSES` 与
  「一次请求＝一行台账＝一个生命周期拥有者」（`studio_api.py:121-169`）。
- **判**：「长跑生成任务跨重启不丢」本仓有真实机制，对方没有。对方胜在队列分道（§6-C9）。

### 4.2 生成协议接入与原生覆盖面 ★★★ —— 本仓胜
- **对方**：图像 OpenAI 兼容 `POST {endpoint}/images/generations`（`image_generator.py:408,569,767,893`）
  + NanoBanana(Gemini 图像)；视频五后端＝火山 Ark Seedance 原生提交/轮询
  （`video_generator.py:437/664/703`、865/1051/1085）、HuiMeng 网关（`generators/huimengi.py:346/362`，
  wait :371-398）、NewAPI/DramaClawAPI 网关（`video_generator.py:1985/3441/3528`）、Grok xAI
  （:1170/1293/1324）、ComfyUI 本地 `/prompt`+`/history`（:4222/4230）。
  **dashscope/WAN 仅作 TTS 与 NewAPI「ali」渠道**（`tts_generator.py:523`、`newapi_provisioner.py:60`），
  WAN 视频走 ComfyUI 本地 workflow JSON（`video_generator.py:4091-4093`）——**无原生 dashscope 视频端点；
  Veo 全仓无提交/轮询端点**（grep veo/gemini 仅命中 API Key 名）。
  可测性混合：`build_seedance2_huimeng_params`（`seedance2_i2v/request.py:122`）是薄层且有单测
  （`tests/test_seedance2_request.py:71-158`），但 Ark/Grok/NewAPI 端点构造**内联在数千行生成器方法体内**
  （行号至 4222/4091），测试仅打桩 `submit_task`。
- **本仓**：`protocols.py:1-30` 单源，图像 3 + 视频 5（**WAN/Veo/Sora/Agnes 原生**），URL/请求体构建为
  **纯函数**，单文件 43 个用例（`tests/unit/llm/test_generation_protocols.py`）；不支持的参数显式记入
  台账 `ignored_params`（`task_ledger.py:53`）。
- **判**：原生服务商矩阵本仓更宽，且可测性是结构性的而非打桩式的。对方「全算力外推网关」与其 README
  自述一致，代价是协议面变窄。对方强项是**单一供应商做成独立子系统**（`seedance2_i2v/` 14 py/6,198 行）——
  深度差异是选择不是缺陷。

### 4.3 台账粒度与参数留痕 ★★ —— 本仓胜
- **对方**：`task_states` 表（`task_state.py:94-121`：task_id/project_id/requester_user_id/
  owner_username/status/result_json…），**无独立列存 `poll_url`/`base_url`/`batch_key`**，
  `provider_task_id` 折进 `result_json.task_metadata`（`task_state.py:274-287`、`run_core.py:664-677`）。
- **本仓**：`TaskRecord` 逐列（`task_ledger.py:31-53`：protocol/model/base_url/remote_task_id/poll_url/
  result_url/local_path/owner_user_id/source/execution_id/ignored_params），来源三入口同池区分
  （rest/channel/workflow）。
- **判**：可查询性与「参数被静默丢弃是否留痕」两点本仓更强；后者直接影响教义第 2 条的诚实形态要求。

### 4.4 取消语义 ★★ —— 平手
- **对方**：分段检查点读意图（`cancel.py:72-147` `await_with_cancel_watch` + 非 async 边界
  `raise_if_envelope_cancel_requested`:248-271）；捕获 `TaskCancelled` 落 `status="cancelled"`
  并**结算退款**（`run_core.py:1003-1022`、:854-869、:415-428）。
- **本仓**：分片边界 `guardCancel` + **专用 `RunCancelled` 类型**（防被遍地 `except Exception` 把「取消」
  降级成「这一镜失败了」，`services.py:44-60`）；端点直打断走 `CancelledError` 且**原样上抛**
  （`studio_api.py:153-162`）。
- **判**：两侧同型（都是分片边界而非硬打断）。退款属其商业模型，不记为工程缺口。

### 4.5 画布数据模型、校验与编译桥 ★★ —— 本仓胜
- **对方**：节点/边是**裸 `list[dict]`**，无逐节点 schema，`CanvasPayload` 只约束数量上限
  （`api/schemas.py:1921-1952`）；节点类型是**散落硬编码字符串**（21 种，`freezone/presets.py:1469-1800`、
  `skill_registry.py:155-166`），非枚举非注册表（`skill_registry` 是**技能**注册表）；
  **保存时对 node type 无任何校验**（只在读时做体积诊断，`canvas_store.py:298`）；
  **无画布→可执行图编译桥**（grep `to_workflow|topolog|in_degree|compile.*canvas` 无实质命中）、
  无拓扑排序/环检测，执行按单节点/单技能派发。
- **本仓**：`neurflow/models.py:94-178` 端口/节点/边/变量全部有类型；`canvas_bridge.py:71` 双向编译 +
  `:42-68,90` 编译前类型校验拒未知；`:46-53` 保证 drama/comfyui/commerce 节点跨进程可识别。
- **判**：本仓「画布是编辑形态、执行前再校验」成闭环；对方画布更像**素材板**（能摆能看），
  不是一张可编译执行的图。

### 4.6 agent 写画布与实时直播 ★★ —— 本仓胜
- **对方**：agent **只能提议、不能直接写**（`can_apply_canvas_patch=False`，workflow 类
  `requires_apply=True` 且「不自动应用」，`skill_registry.py:215-220,571-599`）；`CanvasGraphPatch`
  模型存在但**无后端 apply 端点**（grep `graph_patch.*apply` 无命中）＝死码。
  所有写入确实收在同一 `save_canvas_async` → `revision+1`（版本语义统一，`freezone.py:12308/12505/13175`，
  **这点与本仓口径相同**）。**无 agent 搭建实时事件广播**——`_append_canvas_event` 只追加 JSONL 审计，
  除备份外无消费者（`freezone.py:2880-2902`，读方仅 `backup/files_sync.py:45`）。
- **本仓**：见 §3.2——agent 与用户共用 `canvas_ops` 同一语义 op 写入口，`canvas_op` 事件广播、
  前端增量应用（`CanvasDesignerPage.vue:2304-2322`）。
- **判**：「写入口单一 + agent 可写 + 事件有消费者」三件套本仓齐，对方只有第一件。

### 4.7 画布单节点重试 / 断点 / 调试 ★★ —— 本仓胜
- **对方**：画布层**无单节点重试、无断点续跑**（`freezone/` grep `retry|resume|checkpoint` 无命中，
  仅错误信封带 `retryable` 标志）；取消在项目任务层（`api/routes/tasks.py:628`）。
- **本仓**：step-run（`execution_engine.py:1257`，REST `neurflow_api.py:1564`）、断点命中态
  （`execution_engine.py:41,51,103,252,674,783`）、执行取消（`:1332` + `CANCELLED`:85）、
  节点级 Mock（`neurflow/models.py:139-141`）、版本/回滚与 checkpoint-retry 端点
  （`neurflow_api.py:1664,1675,1696,1714`）。

### 4.8 画布文件持久性与幂等 ★★ —— **对方胜，本仓实测缺四项**
- **对方**：`revision` + `base_revision` 抛 `CanvasRevisionConflict`（拒绝后写、返 `current_revision`、
  不合并，`freezone/canvas_store.py:613-623,100-121`）；**portalocker 文件级排他锁**（`canvas_lock.py:40-81`）；
  **原子写 tmp+fsync+rename+fence**（`canvas_store.py:234-272`）；**幂等缓存 `client_save_id`**
  （重复保存去重，防网络重试虚增版本，`:714-734`）；**`_history/` 保留 100 份历史快照**（`:22,391-398`）。
- **本仓**：乐观锁齐（`canvas_store.py:142-160`）；写盘 `_write_json` 实读只有 `tmp.write_text()` +
  `tmp.replace(path)`（`:69-72`）——**原子替换有，fsync 无**，且 **`.tmp` 后缀名按画布固定**
  （同画布两个并发写者撞同一临时文件，`threading.RLock` 只挡进程内）；排他锁、幂等键、历史保留
  **三项 grep 零命中**。
- **判**：本仓该域最实的技术债。掉电/崩溃可致 rename 后内容未落盘；多进程部署下同画布并发写有覆盖风险。
  须与 §4.6 分开看：本仓「语义 op + 事件」强，「字节持久化」弱。

### 4.9 三维导演场景与镜头调度 —— **对方独有**
- **对方**（`director_world/` 19 py/9,178 行）：`Vector3` 位置/yaw/scale（`models.py:28-46`）、带 fov 的
  相机 preset（`block_world_builder.py:722-769`）、Node 体素世界构建（`:17,224`）、
  全景→cubemap→SHARP→**PLY/3DGS**（`pano_sharp.py:2,133`）、碰撞 GLB（`paths.py:55`）、PlayCanvas 出
  控制帧（`control_frame_compose.py:7,17` → `control_frame_to_sketch.py:5`）；持久化
  `director_worlds/<scene>/world.json` + 每集每 beat `director_blockings/epNNN/beat_MM.json`
  （`paths.py:18,91`、`store.py:17-43`）；**有真实消费者**（`freezone.py:100,13936`、`generation.py:3886`、
  `scenes.py:38`）；全局道具同步（`sync_global_props.py:92`）。
- **本仓**：grep `三维|3D\b` 在 `aigc_studio/`、`llm/generators/` 的 `.py` 中**零命中**
  （仅陈旧 `__pycache__` 命中，不作证据）；场景是 2D 提示词资产（`store.py:49-54`：
  location/time/prompt/lighting）。
- **判**：**上一轮「必须先有可实测端点才立项」的门槛判断对它不成立**——该能力是
  「我方几何与机位数据 + 消费链」，不是服务商调用。但 9,178 行是真实子系统量级，投入产出仍需单独拍板。

### 4.10 一致性 / 叙事校验套件 —— 双方各缺半条闭环
- **对方**（`verification/` 41 py/8,847 行）：主体是 **VLM 判分**而非相似度——单 beat 草图
  （`image_verifier.py:65`）、首帧 vs 草图畸变与风格偏移（`frame_verifier.py:39`）、**跨 beat 角色一致性
  8 维** face/hair/skin_tone/clothing…（`consistency_verifier.py:77`，通过判据 face≥7 且 clothing≥7
  且无 critical，`models.py:66`）、叙事连贯 total<6 判弱（`continuity_verifier.py:108`）、整集总览
  （`episode_reviewer.py:158`）；唯一算法类是 pHash 16×16 + 汉明相似度阈值 0.85
  （`similarity_detector.py:15,35`）；阈值仅请求体可传、无全局配置（`schemas.py:15,50`）；
  grep `clip|insightface|arcface|faiss|face_embedding` **无**人脸嵌入/CLIP。
  **但消费侧是断的**：路由已注册（`api/__init__.py:128`、`app.py:99`）而前端 grep
  `verify|consistency|sketch-select` **零引用**；`needs_regeneration` 只进响应体
  （`sketch_selector.py:311`）；`gate_candidate_cells` 只被 CLI 调（`cli/run_gate.py:87`）；
  `render_repair_context.py:122,197` 全仓**零调用点**；`export/` grep `verif|gate` 零命中——**不阻断导出**。
  唯一自动闭环是失败模式命中统计回填负面提示词（`failure_registry.py:397` →
  `generators/nanobanana_grid.py:4664,5939`）。
- **本仓**：无任何回读校验；实测 `seed_value`（`store.py:46`）、`atmosphere`（`store.py:66`）、
  @角色参考图（`services.py:339-341`）**只写不读**，`merge_episode` 直接拼接（`:598-601`）。
- **判**：**「有校验代码」≠「有质量闸」**。对方有计算无消费者（VLM 额度白烧、结果不阻断），本仓两者都无——
  同一条回路的两半各缺一块。故本项立项理由只能是本仓自己的「只写不读」，**不能引用「对方有」**：
  对方这份恰好示范了只做计算侧会长成什么样（§5.6）。

### 4.11 配音与情感通道 —— 对方有、本仓无，门槛低于原判
- **对方**：`emotion_prompt` 一路透传进 TTS 请求体并置 `should_use_prompt_for_emotion=True`
  （`generators/indextts2_fal.py:181,218,243,331`）。情绪来源三层默认：对话取剧本引号外情绪文本
  （`voice_clone.py:118-132`）、旁白取两条静态 `narration_style` prompt（`:24-33,387`）、用户手选
  （`api/schemas.py:1634` → `freezone.py:7068`）。**无 SSML/prosody/speed**
  （grep `ssml|prosody|speech_rate|speed` 于该文件为空）。
- **本仓**：grep `emotion|情感|情绪` 在 `neurova/tts/`、`voice_engine.py`、`api/endpoints/audio.py`
  **零命中**；全仓命中仅落在 `agent/builder.py:25-166`（**Agent 情感记忆配置，与 TTS 无关，不可混谈**）。
  旁白只透 `voice` + `speed`（`services.py:528-531`、`tts/manager.py:48`）。
- **判**：对方是**文本情绪提示通道**而非韵律控制，施工门槛远低于「接 SSML」。本仓已有 `atmosphere`
  可作情绪源（现无人消费，§4.10）。

### 4.12 检索增强生成 —— 双方都有，对方更「专供提示词」
- **对方**：真知识图谱 + 向量（`cognee/store.py:4-6` Cognee/Kuzu，每项目一数据集），
  `search(mode=graph/chunks/triplet/summaries/cot, top_k)`（`store.py:1452-1466`）；注入点
  `GRAPH_COMPLETION` + `only_context` top_k=30 取人物/别名/外貌（`cognee/pipeline.py:344-366`）、`:384`
  再拼原文设定；身份规划 top_k=20 → 拼进选角 prompt（`agents/identity_planner.py:640-649,692-694`）；
  无图谱时降级走 SQLite 别名索引（`knowledge_pipeline.py:38,64`、`identity_planner.py:683-688`）。
  chat 侧是文件式记忆非向量（`chat/service.py:231-251,258-267`、`chat/hermes_workspace.py:337-346`）。
- **本仓**：`NeurovaRecallEngine`（多维融合召回 + 意图钻取 + 插件化通道，
  `cognitive_layers/memory_layer/neurova_recall.py`，消费点 `mem_core.py`）、`ContextPool` 三层隔离 +
  WAL/FTS5 台账（`context_pool.py`、`context_pool_registry.py`）。
- **判**：本仓召回面更广；对方在「**按项目隔离的知识集直接喂给生成提示词**」这条具体链上更专，
  尤其「别名/外貌」作身份锚——是 §4.10 缺口的**问题解法参照**，不是代码解法。

### 4.13 凭据治理与归属拒绝 —— 本仓胜（对方两处实缺陷）
- **对方**：CE 从 env 读各家 Key（`config.py:436,443-444,532,673,798,871-874`）；EE 有
  `CredentialReference{source∈platform|organization|local, key_version, org_id}`
  （`ports/model_credentials.py:26-40`）、`RequestCredential.api_key` 标 `repr=False`（:43-53）、
  错误类型明示 secret-free（:17-23）、envelope 拒收含 token/apikey 的 payload（`envelope.py:109-120`）
  + `utils/error_redaction.py:9-21`。
  **缺陷**：网关 `api_key` **明文落库无加密**（`model_gateway_settings.py:216-246`）；无通用日志脱敏
  （`utils/logging.py` 无 redact/mask）；非属主语义**不是 404 同构**——项目不存在→404、存在但角色不足→
  **403**（`project_context.py:133`、`ports/project.py:50-52`、`api/auth.py:60`），**项目名可被枚举**。
  角色四级 viewer<editor<admin<owner（`ports/project.py:10-21`）；任务表按 (username, project) 分库
  （`task_state.py:1322`）。
- **本仓**：密钥**加解密落库**（`llm/providers/secret_store.py` 的 `encrypt_api_key/decrypt_api_key`、
  字段 `encrypted_api_key`（`llm_routing_overlay.py:122`）、使用前解密（`generators/runtime.py:121-123`）、
  解密失败有显式恢复口径（`provider_manager.py:34`））；`_mask_secrets` 套在**每一类** ProviderError 上
  （`providers/error_mapping.py:199,217-251`，`:172` 专治 `sk-` 形态），错误响应固定三键且 `user_hint`
  恒脱敏（`multi_model_client.py:1493`）；另有 L0 输出脱敏网关（`core/firewall.py:4,123,410`）；
  归属拒绝全链 404 同构（`canvas_store.py:157-158`、`studio_api.py:4`、`collaboration_api.py:721-723`）。
- **判**：静态加密 + 全量掩码 + 枚举防护，本仓成体系；对方明文落库且泄露存在性。对方胜在**归属维度
  可追溯**（`key_version`/`org_id`），本仓零命中——记 §6-C8。

### 4.14 自动选路 —— 本仓独有
- **对方**：**无**按请求特征自动挑模型/服务商，无成本或延迟排序
  （grep `auto_select|choose_model|pick_provider|fallback|cheapest|latency|rerank|weight`）。实际是
  「用途→模型静态表 + 用户显式选 + 不匹配即抛错」（`official_defaults.py:18-40`、`config.py:147-151`、
  `stage_asset_tasks.py:254-283`）。
- **本仓**：`LLMRouter` 十类 `RequestType` + `ModelCapability` + `select_model_for_request`
  （`llm/llm_router.py:1-35`）；创作专区无显式选型时走 `_auto_route("image"/"video")`（`services.py:322,396`）。

### 4.15 成片合成 —— 本仓胜
- **对方**：`export/` 只做 SRT 文本与 ZIP（2 py/126 行），**无 FFmpeg/烧录/混音**；真合成在
  `generators/video_composer.py`（FFmpeg 子进程 + 可选 MoviePy，`config.py:744` FFMPEG_PATH），
  `add_subtitles` 默认 True、`add_bgm` 默认 False（`api/schemas.py:255-256`），主链只有 MoviePy
  `set_audio` 贴旁白（`video_composer.py:634`），**BGM amix 不在主链路**
  （grep `amix|bgm|set_audio` 仅 `freezone/jobs.py:1146`）；缺依赖诚实暴露（MoviePy 未装 →
  `success=False, "moviepy not installed"`，`:596-599`）。
- **本仓**：`merge_episode` 三级 concat → `mix_bgm` → 字幕烧录，每级失败回退上一级并留 warning，
  无 FFmpeg 落 manifest 连播清单（`services.py:569-620` + `core/ffmpeg.py` 的
  `burn_subtitles/has_cjk_font/mix_bgm/probe_has_audio`）；BGM 生成无实测服务商即维持台账 blocked。

### 4.16 端口与 Edition 抽象 —— 对方独有
- **对方**：`ports/` 是真六边形端口层——进程级注册表 `get_port/register_port`，`ensure_bootstrap` 按
  edition 注入（CE→`ports/local/*`，EE→entry_point 组 `novelvideo.ports_bootstrap`，
  `ports/registry.py:59-90`；EE 必需端口清单 :26-45）；接口用 `Protocol`（`ports/tasks.py:103-149`、
  `model_credentials.py:56-57`），CE 各 1 实现，调用侧 `get_port(...)` 注入（`cancel.py:10`、`app.py:380`）。
  抽象对象含 model_credentials / tasks+cancellation / lifecycle / egress / credit_quote+usage / project /
  audit / video_delivery。31 py/3,573 行。
- **本仓**：**无 `neurova/ports` 目录**，`get_port`/`register_port`/`entry_points(group=` 全仓零命中。
  等价能力散在 `llm/provider_manager.py`、`llm/generators/`、`plugins/`、`skill_system/` 与
  `neurflow/adapters.py` 六类注册汇聚。
- **判**：对方胜在**可替换边界**。但这是**产品发行形态**决策而非代码卫生问题——本仓若无 CE/EE 双版本
  计划，引入端口层即空转抽象（§6-C7 判「需人裁」）。

### 4.17 身份一致性与风格注入 —— 各有侧重
- **对方**：`styles/` 无 py，是纯 JSON 预设（`style_instructions` / **`avoid_instructions`** / `style_tag`），
  注入靠字符串前拼 + 负面词（`image_generator.py:364,376`、`prompt_builder.py:169`、
  `nanobanana_grid.py:7573-7586`）；项目级单值风格锁 `visual_style`（`scenes.py:114`）+ 枚举校验
  （`projects.py:737`）；身份锁定靠 `identity_id`（`models.py:971,1052`）、`character_tag`（`models.py:977`、
  `nanobanana_character.py:840`）、`reference_images`（`models.py:988`）、身份标记色不漂移
  （`episode_optimizer.py:67-69`）。**无 seed 固定**：生图 seed 仅 Optional 透传
  （`image_generator.py:123,384`），**视频 seed 每次随机**（`video_generator.py:4431`）——同脸靠参考图 +
  文本 tag。**`assets/` 目录是空壳**（1 py/6 行），真身份机制散在 `models.py` 与各家生成器内。
- **本仓**：`_inject_style` 项目风格/画幅锁（`services.py:295,338,482`）；身份锚定更确定——定妆 seed 落库
  （`store.py:46`）+ @角色参考图注入（`services.py:339-341`），角色按 project 作用域天然跨集。
- **判**：确定性身份锚本仓形态更好（seed 可复现 vs 文本 tag）；但对方的 `identity_id` 显式身份列、
  全局道具同步（§4.9）与「漂移检测」是本仓没有的**跨集调度**维度。

### 4.18 交付运营面（发布 / 渠道 / i18n / 备份）—— 本仓胜
- **对方**：**无对外发布**（grep douyin/抖音/tiktok/youtube/bilibili/b站/快手/xiaohongshu/publish_to
  仅命中 README 外链），仅 OSS/CDN 中转（`utils/oss_client.py:1`、`storage/media_relay.py:1`）与硬编码
  片单展示页（`frontend/src/lib/login-community.ts:16`）；**无 IM 渠道**
  （grep wechat/weixin/wecom/feishu/lark/dingtalk/slack/telegram/discord/whatsapp/matrix/ntfy/webhook
  仅命中文档链接与「商务微信二维码」文案），机器入口是 MCP/CLI（`chat/dramaclaw_mcp.py:1`、
  `skills/director_skill.py:1-9`）；i18n **3 语言** zh/en/vi（`frontend/src/i18n/languages.ts:14`，各 1 文件、
  顶层 64 键，有键集双向对齐守卫 `src/__tests__/i18n/locales-json.test.ts:31-40`）、后端 code+中文兜底
  （`i18n_message.py:9-16`）；备份三通道（SQLite `VACUUM INTO` 每日 `backup/db_daily.py:1,16-45`、
  rclone 镜像 OSS `files_sync.py:1,111`、litestream WAL）**但无调度器**——全库 grep
  cron/apscheduler/celery beat/systemd timer 无命中，只有手动 typer 组（`cli.py:13,26`、
  `files_sync.main():581`），文档改教 docker volume tar（`docs/en/guides/self-hosting.md:72-105`）；
  还原路径存在（`backup/cli.py:86-168 restore-cell`）。
- **本仓**：发布节点 `builtin:video-publish` + 店铺连接面（`neurflow/commerce_nodes.py`、
  `api/endpoints/neurflow_stores.py:32-272` 含 OAuth 授权回调）；IM 渠道微信/飞书/QQ 机器人直连 AIGC
  生成（`neurova/channels/`）；i18n **11 语言**与 zh-CN 严格对齐
  （`src/i18n/__tests__/locale-consistency.test.ts`，`AGENTS.md` §3 已钉）；配额账本单一事实源
  （`admin/resource_quota_manager.py:2-8`，`admin_service.py:85-100`）+ 用量记账
  （`core/aigc_usage.py`，消费点 `services.py`/`generation.py`/`recovery.py`）。

---

## 5. 本仓存量断点（本次抓出，与对方无关）

### 5.1 `negative_prompt` 三层只写、协议层零发（**新**）
- 写侧：REST 收字段（`api/endpoints/generation.py:150`）、IM 渠道透传
  （`channels/feishu_ai.py:29,60`、`channels/qqbot.py:870,927,977,1033,1091,1149`）、
  facade 组进 `GenerationConfig`（`llm/generators/base.py:39`、`runtime.py:419`）。
- 读侧：**`protocols.py` 全文零 `negative` 命中**，统一入口
  `generate_image(creds, prompt, size, n, ref_images, timeout, seed, strength)`（`:564-573`）
  **签名里没有这个参数**；`GenerationConfig` 的其余消费点（`channels/qqbot.py` 多处、
  `llm/generators/manager.py`）也未把它发给任何协议。
- 影响面（按核心原则第 7 条）：接了能实现什么——生图可按各家协议形态带上负面词（各协议字段名/是否支持
  须逐一实测，不能假设）；不接留下什么——对外可传而实际静默丢弃，既是 §2「只写不读」断点，也是
  **诚实性问题**（教义第 2 条要求失败以显式形态暴露，而非无声吞掉）。
- 两条出路：逐协议实测负面词形态后接入（则 `ignored_params` 须同步记录不支持的协议），或净删三层字段。

### 5.2 `@vue-flow/*` 四包声明零消费
- `NeurUI/package.json:17-20` 声明 `@vue-flow/background ^1.3.2` / `controls ^1.1.3` / `core ^1.41.5` /
  `minimap ^1.5.2`；实测 `grep -rn "@vue-flow" NeurUI/src` → **命中数 1 且落在注释**
  （`CanvasDesignerPage.vue:480`「后续可升级为 Vue Flow」）。画布实际是 §3.2 的手写 viewport。
- 接了什么：没接。四包只进 `node_modules`、进 `npm run build` 依赖解析、进桌面端打包体积
  （`NeurUI/src-tauri/` 在活），零消费者；不接零功能损失，但 `:480` 构成**悬空意图**——
  读到的人都会以为画布跑在 Vue Flow 上。
- 出路：删包 + 删注释（承认手写为终态），或真迁移（`:480` 升级为待办走红绿灯）。按教义第 6 条，
  留着「第二份潜在实现」不闭合是更差的选择。

### 5.3 孤儿 viewport 写入口，零消费者、零行为断言
- 现役写点：`neurflow_api.py:957` definition PUT 内嵌（`:1000-1005` 写 `metadata["viewport"]`），
  其上方注释原文自证**「B2：视口随定义回写落 metadata.viewport（省去单独 PUT viewport 往返）」**。
- 孤儿写点：`neurflow_api.py:1021-1033` `save_workflow_viewport`，同写 `metadata["viewport"]`，
  但独立往返已被上面那句宣布省去，路由未随之退役。
- 三面查消费者：前端 `grep -rn "/viewport" NeurUI/src` **零命中**；后端 `grep --include=*.py neurova/`
  仅命中路由自身；测试仅 `tests/unit/neurflow/test_workflow_ownership.py:140`，且形态是
  `assert c.put("/workflows/wf_a/viewport", json={"x": 1}).status_code == 404`
  ——**只证归属门拒陌生人，全仓无一处断言它写成功**。
- 影响面：定义 PUT 已带 viewport，读侧 `collaboration_api.py:590-592` 不区分谁写；`Body` 的
  `{x,y,zoom}` → `wf.metadata.viewport` → 编辑器恢复，与现役路径同一终点同一形状，删之不丢读数。
  不删则两份写口径长期并存（任一处改校验/取整/字段名即漂移），且该路由归属门**无正向证据**。
- 撞：§6 单一事实源、§7 老路径未与退役同批、§2 注册无消费者的模块。

### 5.4 画布写盘无 fsync 且 `.tmp` 名固定
见 §4.8。`canvas_store.py:69-72` 是本仓用户数据的唯一落盘路径，而 `canvas_bridge.py:171` 明示
「画布快照是用户数据的唯一可编辑形态」——丢一份即不可恢复。`.tmp` 固定名一项可即刻修（改唯一后缀）。

---

## 6. 候选清单（刷新版，只读产出、未动码）

> 每条**立项理由只允许是本仓自身可核实的断点/缺口**，「对方有」不作理由（§2.2）。
> 状态：`净删/接线`（可自主）｜`需人裁`（要产品或架构决策）。

| 编号 | 项 | 本仓现状（实测锚点） | 立项理由（本仓侧） | 状态/优先 |
|---|---|---|---|---|
| C1 | 跨集资产连续性**读数与消费** | ~~只写不读~~（登记时锚点：`store.py:46,66`、`services.py:339-341`、`:598-601`）→ **已接线**：`resolveShotContinuity` 一处读四路，两道硬阻断闸 + `persist_media` 空件闸 | §2 只写不读 + 无「写入→读取→反馈」闭环。**须连消费侧（阻断/回炉）一起建**，否则重演 §5.6 式断链——本批按此建闸 | ✅ 已落地 `5336b6f5`（判据入册 `077ce3fd`，台账 §6-81）；拍板＝硬阻断点名 + 氛围本批注入 |
| C2 | 旁白情绪通道 | TTS 仅 `voice`/`speed`（`manager.py:48`、`services.py:528-531`），`atmosphere` 未用于配音 | §2 只写不读；门槛低于原判（文本提示通道即可，非 SSML） | 需人裁 / P1 |
| C3 | 场景空间与机位复用 | 场景仅 2D 提示词字段（`store.py:49-54`），全仓 `.py` 无三维命中 | 原「必须先有实测端点」**已作废**：不依赖服务商，是自有数据 + 消费链 | 需人裁 / P1（原 P2 上调） |
| C4 | 清理 `@vue-flow/*` 断点 | 四包零 import + 悬空注释（§5.2） | §2 注册无消费者的模块 | 净删/接线 / **P0** |
| C5 | 退役孤儿 viewport 写入口 | `neurflow_api.py:1021-1033`（§5.3） | §6/§7 老路径未与退役同批 | 需人裁 / **P0**（先确认非对外契约） |
| **C6** | `negative_prompt` 接线或净删 | 三层写、协议层零发（§5.1） | §2 只写不读 + 教义第 2 条诚实形态 | 需人裁 / **P0** |
| **C7** | 画布文件持久性四项 | `canvas_store.py:69-72` 无 fsync；`.tmp` 名固定；无排他锁/幂等键/历史保留（§4.8、§5.4） | 画布快照是用户数据唯一可编辑形态，不可回滚即不可接受 | 需人裁 / **P0**（`.tmp` 唯一化名可即刻修，余三项需设计） |
| **C8** | 凭据归属可追溯 | 有静态加密与掩码（§4.13），但 `key_version`/`org_id` 零命中 | 轮换与泄露追溯缺维度；**先确认本仓有无多租户计费/轮换诉求** | 需人裁 / P2 |
| **C9** | 长任务与 ffmpeg 互不饿死 | 进程内 asyncio + `task_tracker`（`studio_api.py:167`），无队列分道 | **架构级**议题：引入外部队列＝新增必选依赖，撞 §3 可选依赖惰性 import 纪律 | 需人裁 / P2（不轻率） |

**推荐次序**：C4 → C6 → C7（仅 `.tmp` 唯一化名一项）→ C5 → C1 → C2 → C3 → C8 → C9。
理由：前四项是**净删除或净接线**，不新增依赖、不改产品形态，可各自独立成批走红绿灯（教义第 3 条）；
C1/C2/C3 是新能力，需各自独立口径设计与实测端点，不可与清理混批。

**红灯方向**（按 §3 先红后绿 + 记忆「红灯要红在行为上」）：C1 断「参考图/提示词缺失或非空产物未落时该镜
标 failed」这类行为，不测落库存在性；C2 断「给定 `atmosphere` 时合成请求参数随之改变」，不能只断参数能传；
C6 断「负面词进入实际发出的请求体（或在不支持时被记入 `ignored_params`）」；C7 断「并发写不产生半写文件、
同 `client_save_id` 重复保存不递增版本」。

**不采纳（成文）**：对方的 CE/EE 端口分层（本仓无对应发行形态，接即空转抽象）、退款/credit 结算
（绑其商业模型）、Celery 作为默认必选依赖（撞 §3 惰性可选依赖纪律）、`verification/` 的 VLM 判分形态
（**先建消费者再建计算**，否则复制 §5.6 那条断链）。

---

## 7. 对方自身弱点台账（取其能力时须避开的形态）

1. **重启不接管远程任务**：僵尸清扫直接判 failed（`task_state.py:1340-1395`），TTL 内用户重发即重复计费。
2. **状态机无转移校验**：裸字符串 status（`task_state.py:52-53,226`）。
3. **协议端点内联巨型类**：`video_generator.py` 行号至 4222、`api/routes/freezone.py` 单文件 14,814 行，
   测试靠打桩 `submit_task`——**不可逐端点证伪**。
4. **画布保存不校验节点类型 + 无编译桥**：21 种类型散落硬编码字符串，执行按单节点派发。
5. **`CanvasGraphPatch` 无 apply 端点**＝死码；**`_append_canvas_event` JSONL 只被备份消费**＝只写不读。
6. **`verification/` 8,847 行计算套件，前端零引用、不阻断导出、`render_repair_context` 零调用点**——
   **本台账最重要一条**：把「写了校验」当成「有质量闸」，实际白烧 VLM 额度。
7. **`assets/` 是空壳**（1 py/6 行），真身份机制散在 `models.py` 与生成器内——命名与落点不符。
8. **网关 api_key 明文落库**（`model_gateway_settings.py:216-246`）+ 无通用日志脱敏。
9. **403 语义可枚举项目名**（`ports/project.py:50-52`）——归属面泄露。
10. **备份三通道齐全却无调度器**（grep cron/apscheduler/celery beat/systemd timer 全空）——机制在、
    触发不在。**本仓巡检自身备份/恢复链路时应按同一标准自查。**

---

## 8. 与既往文档的关系

- 本文**取代**同日早先那份《DramaClaw 参照下的能力盘点》：刷新的两处是 C3 的「暂缓」门槛判断、
  C1 的立项理由（去掉「对方有」成分）；保留并吸收其「三道闸」「画布更正」「`@vue-flow`/viewport 断点」。
  同一主题在 `docs/08-research/` 只留本文一份事实源（§6 不新造平行体系）。
- `docs/08-research/AIGC生成端点矩阵_2026-09-14.md`：本仓协议矩阵的权威记载，§4.2 结论以其为准。
- `docs/04-plans/2026-09-14-canvas-workflow-打通与归属模型.md`：画布 B0–B5 断点表的历史记录，
  其「viewport 前端不调」「画布无用户隔离」两项**现已闭环**（本文 §3.2/§4.13 实测），引用须注明时效。
- `docs/Neurova_OpenSpace代码级对比_2026-09-14.md`：本文件骨架的同域先例（该文档位于 `docs/` 根，
  与 §5「过程性分析不留 docs/ 根目录」现行口径不一致；迁移与否属另一议题，本文不擅动他人文档）。

---

## 9. Verification Status（三态清单）

### 已核实——本仓侧（主代理 `grep`/`Read` 亲验）
- [x] 无限画布前后端齐备且接线 — `CanvasDesignerPage.vue`(2,803 行) 逐点、`router/index.ts:262-272`、`canvas_{store,ops,bridge}.py`、`collaboration_api.py:517-1019`
- [x] 重启续拉循环随启动接线 — `recovery.py:111,145` ← `app.py:1093-1095`
- [x] 台账字段形状 — `task_ledger.py:31-53`
- [x] 协议层**不吃** `negative_prompt` — `protocols.py` 零命中 + `generate_image` 签名 `:564-573`；写侧 `generation.py:150`/`feishu_ai.py:29,60`/`runtime.py:419`
- [x] 画布写盘无 fsync、`.tmp` 名固定 — `canvas_store.py:69-72` 实读；portalocker/idempot/history 零命中
- [x] 密钥静态加解密 + 掩码 — `secret_store.py`、`runtime.py:121-123`、`error_mapping.py:199-251`、`firewall.py:410`
- [x] 无端口/Edition 抽象 — 无 `neurova/ports`，`get_port`/`register_port`/`entry_points(group=` 零命中
- [x] 无 `key_version`/`org_id`、无跨集全局道具同步、无 emotion TTS、无三维
- [x] `@vue-flow/*` 四包零 import；孤儿 viewport 路由及其唯一测试引用只断 404
- [x] 双侧规模与测试比 — `find` + `wc -l`（§1）
- [x] 许可证 Elastic-2.0 — 对方 `REUSE.toml` 通配 + `LICENSES/Elastic-2.0.txt` + API `NOASSERTION`
- [x] 克隆可复现性 — commit `e133316`（`git log -1` 亲验）

### 未逐行复算——对方侧（同一快照内四个只读子代理实读，锚点可复核）
- [ ] §4 对方侧全部行号。主代理抽验了影响结论的方向性条目，未逐条 `sed` 复读。
  **复核方式**：`git clone --depth 1 --filter=blob:none --sparse` 至 commit `e133316`，按锚点复读。
- [ ] 对方前端是否真的完全不消费 `verification/` 结果——依据是 grep 零引用，未读组件树全文。
  **这条若错会抬高 §4.10 对对方的评价**，风险中等；影响 C1 的形态参照，不影响其立项理由。
- [ ] 对方 `freezone` 21 种节点类型的完整清单与各自实现深度——只取了 presets 行段。
- [ ] 对方 `pyproject.toml` 依赖矩阵（本次仅见「58 行声明、3 处 `==` 钉版」，未用于结论）。

### 剩余风险
1. **把「对方有」当成本仓必做项**（违反 §2.2）。C1/C2/C3 的立项理由已改写为本仓自有断点；若后续讨论
   出现「因为对方有校验套件所以必须做校验」，应回到 §7.6 的反例继续质询。
2. **对方行号会漂**：该仓 `pushed_at` 2026-10-01、本次快照 commit 即 2026-10-08，仍在推。
   任何后续引用必须带 commit 号，或改按符号定位。
3. **本文未比对方前端代码结构**。§4.8 的持久性结论全部来自其后端 `canvas_store`/`canvas_lock`，
   与本仓 `canvas_store.py` 是同层对比、口径一致；但「幂等是否被挪到前端做」这一层未比。
4. **本文无一条来自「跑起来看」**。落地 C1/C2/C3 前任一项，都须按教义第 4 条 live-verify，
   不能以本文代替实测。
5. **许可证结论止步于「不整合」**。若将来需要「仅调用其对外 HTTP 面做互操作」，ELv2 的「托管服务」条款
   仍需法务判断，本文不构成该判断。
