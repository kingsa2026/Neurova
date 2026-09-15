# Neurova × Infinite-Canvas 代码级对比与 AIGC 整合分析报告

- 日期：2026-09-14
- 研究对象：`basketikun/infinite-canvas`（GitHub 6.5k★，v0.18.0，MIT，官网 canvas.best）——即近期微信公众号推文所介绍的"面向 AI 创作的开源无限画布工作台"
- 次要参照：`hero8152/Infinite-Canvas`（3.1k★，Python，已于 2026-08-28 弃用，非商业许可）
- 研究方式：两仓库均 `--depth 1` 克隆至本机代码级通读（研究用临时目录 `~/ic-research`，报告发布后可删除）；微信原文因平台反爬未直接读取，经搜狗微信索引 7 篇同期文章交叉定位，功能描述（无限画布+生图/视频+自定义 API+提示词库+本地部署）与 basketikun 仓库逐条吻合，与 hero8152 的 ComfyUI/ModelScope 卖点零命中，故判定文章介绍对象为 basketikun。

---

## 0. 结论先行（TL;DR）

1. **整体架构不建议引入**。infinite-canvas 是"纯前端 + 浏览器直连各家 API + 密钥明文存浏览器"的单机工作台形态，与 Neurova"服务端凭据 + task_ledger 账本 + 属主隔离 + 审计"的 P0 治理成果（Dify P0-2 决策）方向相反；其 React 19 技术栈也无法进 Vue3 前端（无 iframe 价值——数据模型不兼容，见 §5.2）。
2. **它最有价值的不是"搬过来"，而是四块可移植的机制**：
   - **画布内核交互细节**：undo/redo 快照栈、结果节点自动摆放+自动连线、批量多图网格对比/设主图/逐张重试（Neurova 画布当前全部缺失）；
   - **Agent 操作画布的 op 协议**：8 种 op + 单一 undo 快照 + `run_generation` 也是 op，MCP 工具与插件共用同一 `applyOps`——Neurova 的 `canvas_ops.py` 已是同类物，差的是把它以 MCP 面暴露给外部 Codex/Claude Code 的"薄壳"；
   - **文档/Blob 分层存储模式**（storageKey + IndexedDB + 引用计数 GC + hydrate），可作 Neurova 画布媒体产物落盘与导出 zip 的参考设计；
   - **提示词库域**（7 开源源 + 自定义 JSON 源 + 1h TTL 缓存），Neurova 完全缺失，且是 AIGC 页与画布共用的低成本高感知增量。
3. **画布语义两者根本不同**：Neurova 画布=可执行工作流编辑器（draft/run/publish/debug/trigger 全链），infinite-canvas 画布=媒体产物创作摆图板（节点=图/视频/文本产物，边仅 `{from,to}` 无语义）。整合的正确姿势不是二选一，而是给 Neurova 画布补"产物节点"形态，让生成结果能直接落画布（当前产物只在 dock/记录面板，不在画布上——这是真差距）。
4. hero8152 已弃用且禁商用，**不具备整合价值**；仅其 ComfyUI"sidecar 参数描述符"（工作流旁挂 config 映射表单字段、不改原图）对 NeurFlow 模板表单化有一个值得借鉴的设计模式。

---

## 1. 项目本体识别

| | basketikun/infinite-canvas | hero8152/Infinite-Canvas |
|---|---|---|
| Stars / 状态 | 6,494★，活跃（push 2026-09-07） | 3,062★，**2026-08-28 弃用**，导流后继产品 DX-OS |
| 语言/栈 | TypeScript，Vite 7 + React 19 + AntD 6 + Zustand 5 + Bun | Python，单文件 FastAPI `main.py`（19,038 行）+ static 前端 |
| 定位 | AI 创作无限画布工作台：生图/参考编辑/视频/音频/对话/画布编排/Agent | ComfyUI/API/ModelScope 调用的画布壳 |
| 许可 | **MIT（可商用/闭源衍生，与 PRINTFILM 同级）** | 非商业许可（禁止打包商用） |
| 后端 | **无自建后端**（AGENTS.md 明文设计约束："不假设存在项目后端"） | 自建单文件后端 |

微信推文对应对象：basketikun（功能描述逐条命中；hero8152 的 ComfyUI/ModelScope 卖点在全部相关推文中零命中）。

## 2. basketikun/infinite-canvas 架构深拆

### 2.1 仓库布局与规模（无后端的多子项目同仓）

| 目录 | 角色 | 规模 |
|---|---|---|
| `web/` | 主应用（唯一面向用户） | src 共 172 文件 32,778 行；`pages/canvas/project.tsx` 单文件 **3,384 行** god-component |
| `canvas-agent/` | 本地 Agent 服务 + MCP server（npm 包 `@basketikun/canvas-agent`） | 7,576 行，Express 5 + `@modelcontextprotocol/sdk`，spawn `@openai/codex` app-server |
| `canvas-proxy/` | 本机 CORS 转发 | 132 行纯 node:http |
| `plugins/canvas/` | 官方节点插件 + `sdk/`（`@infinite-canvas/plugin-sdk`）+ registry | 1,361 行 |
| 部署 | Docker（bun 构建→nginx 静态站 3000 端口）/Vercel/Render；canvas.best 即其托管版 | — |

关键依赖事实：**没有任何图形/画布库**（无 reactflow/konva/pixi/fabric/d3），画布全自研；持久化 localforage（IndexedDB）+ zustand persist。测试几乎只在 canvas-agent（7 个 test），web 前端无测试。

### 2.2 无限画布内核（纯 DOM+SVG）

- 渲染：世界层单 div `transform: translate(x,y) scale(k)`；节点=绝对定位 DOM（React.memo）；连线=一张 10000×10000 SVG，三次贝塞尔 + 16px 透明 hit-path；网格背景 CSS gradient 平移。（`web/src/components/canvas/infinite-canvas.tsx:223-256`、`canvas-connections.tsx:22-59`）
- 坐标：`ViewportTransform{x,y,k}` 单一变换；滚轮以鼠标为锚点 `k*1.1^(delta/100)`，clamp [0.05,5]；pointer capture + rAF 节流提交。
- 交互：世界坐标框选（AABB+shift 增选）、多选拖动 rAF、分组=普通 `type=group` 节点+子节点 `metadata.groupId`（**不支持嵌套组**）、连线拖出空白弹"创建并连接"、小地图 DOM 方块反算视口。
- 撤销/重做：手写双栈 `historyRef{past,future}` 上限 50，快照含 nodes/connections/chatSessions，拖动期暂停历史、去抖合并提交，viewport 不入历史。（project.tsx:477-522、1108-1144）
- 性能：视口裁剪 visibleNodes、memo + 稳定引用、rAF 合帧、`URL.createObjectURL` 缓存 Map。**无位图/WebGL 渲染，千级节点未验证**。

### 2.3 数据模型与存储

- `CanvasProject{id,title,nodes,connections,chatSessions,viewport,backgroundMode}`；节点 6 内置类型 `image/text/config/video/audio/group` + 开放插件类型 `"<pluginId>:<name>"`；**生成参数、批量结果数组、videoTaskId、references 全塞 `metadata`**；边仅 `{id,fromNodeId,toNodeId}`，无 handle/waypoint/条件语义。
- 文档与二进制分离：JSON 只存 `storageKey`（`image:<nanoid>`），Blob 进 IndexedDB（`image_files`/生成日志/`prompt_cache` 分 store），加载时 hydrate 批量解析 objectURL，**未引用图有引用计数式 GC**（`services/image-storage.ts:172`）；文档整包 JSON 400ms 去抖全量写。
- 导出 zip：`CanvasExportFile{app,version:3,projects:[{project,files}]}` 内嵌 blob；另有选中节点导出散文件。同步=WebDAV 全量 manifest+blobs 往返，**非增量非协作**。

### 2.4 AIGC 接入（纯前端直连）

- 配置形态：`channels[] = {baseUrl, apiKey, apiFormat:"openai"|"gemini", models:[{name, capability, script?}]}`，模型值编码 `channelId::model`，按模态设默认。
- 协议矩阵（`services/api/image.ts` 921 行、`video.ts` 428 行）：生图 `/images/generations`（b64 归一、gpt-image 特判）；图生图/参考编辑 `/images/edits`（multipart 多 `image[]`）；对话/生文走 **OpenAI Responses API**（SSE + function tools——画布助手的工具循环底座）；Gemini `generateContent`/`streamGenerateContent`；音频 `/audio/speech`；视频 OpenAI 任务式三段 `POST /videos → GET /videos/{id} → /content`，Gemini `predictLongRunning` operations 轮询。
- 可靠性细节：**`videoTaskId` 落节点，刷新后恢复续轮询**；批量 `Promise.all(count)` 部分失败逐图重试；文本 SSE 增量直写节点 metadata。
- **自定义 model script 逃生舱**：`new Function` 注入 `prompt/images/params/http/request/poll/signal/onDelta`，中转站非标协议无需改码即适配（`model-plugin.ts:106-140`，poll 内置 2.5s/5min）。
- 画布↔生成联动：生成前**沿入边 BFS 收集上游 text/image/video/audio 作参考**（`canvas-node-generation.ts:43-66`）；config 节点用 `@[node:id]` mention 精确装配提示词；结果新节点固定摆源节点右侧 +96px 并自动连线；批量共享节点可展开网格对比/设主图；**局部重绘=画笔 mask 生成第二参考图节点显式留在画布上**（可解释、可重放）；另有前端 crop/九宫格 split/纯前端 upscale。
- 安全模型：密钥/画布/素材**全部明文存浏览器**；插件=同源任意 JS 无沙箱；canvas-agent 仅 127.0.0.1 + 随机 token + Origin 首绑，但 token 走 query string。

### 2.5 插件系统与 Agent/MCP 桥

- 插件：`CanvasPlugin{id,name,version,minAppVersion?,css?,nodes[],setup?(app)}`，节点定义声明 Content/Panel/toolbar/resource/useBuiltinPanel；URL fetch→动态 `import()`→注册 node-registry；宿主 React 单例经 `getPluginRuntime()` 注入避免双 React；ctx 提供 `applyOps/ai/storage/emit-on`。分发=官方插件发孤儿分支 `plugins-dist` + jsDelivr 一键安装。
- MCP 桥三段式：**MCP(stdio) ↔ 本机 HTTP(17371) ↔ 浏览器画布（SSE 下行 + POST 回传）**。34 个工具（`canvas-agent/src/canvas/schemas.ts:10-46`）：读类 `canvas_get_state/get_selection/export_snapshot`；写类统一 `canvas_apply_ops`——**op 仅 8 种**（add/update/delete_node、delete_connections、connect_nodes、set_viewport、select_nodes、**run_generation**，zod discriminatedUnion）；便捷糖 `create_generation_flow/create_image_prompt_flow/generate_*`；站点工具（prompts_search/assets_add/workbench_image_generate）由浏览器端执行。**op 协议与插件 `applyOps` 共用一份实现**（`lib/canvas/canvas-agent-ops.ts`），Agent 动作前存单一 undo 快照可一键回滚。

### 2.6 提示词库

7 内置源全部是 GitHub raw JSON（yukkcat/image-prompts 系 banana/davidwu/freestylefly/awesome-gpt-image/gpt4o/youmind×2），同构 JSON 即可加自定义源；抓取即缓存 IndexedDB，TTL 1h + signature 失效 + lastError 保留；检索为纯前端 keyword/tag/category 过滤；画布侧 prompt chip 消费。

### 2.7 亮点/短板（整合视角）

**亮点**：① 画布内核极小（<700 行核心数学与交互模式可抄）；② Agent op 协议干净且"生成也是 op"；③ 文档/Blob 分层+GC+hydrate+zip 导出；④ 断点续轮询/部分失败逐图重试/mask 留痕等生成体验细节；⑤ model script 逃生舱；⑥ 插件 URL 安装轻分发管线。
**短板**：① 零协作零服务端零鉴权零审计，存储层不可复用；② 边无语义、组不嵌套，与工作流引擎差距大；③ project.tsx 3,384 行 React 绑定死，**Vue 只能重写不能搬**；④ 密钥明文+插件无沙箱，企业/多用户环境不可接受；⑤ 本地格式无迁移承诺、web 无测试、千节点性能未验证。

## 3. Neurova 现状口径（对照底稿）

详细锚点见研究纪要，此处列承重事实：

- **AIGC 后端**：`neurova/llm/generators/`（protocols.py 实测协议矩阵 OPENAI_COMPAT/ARK/DASHSCOPE × WAN/SEEDANCE2/VEO；runtime.py 凭据三级解析+产物落盘；task_ledger.py 统一账本含 source=rest|channel|workflow、R2 ignored_params 诚实可见、R3 batch_key/project_id；recovery.py 启动恢复续拉）——协议覆盖与任务可靠性**强于** infinite-canvas（后者无服务端账本，仅 videoTaskId 续轮询一招相似）。缺：BGM/音效、尾帧 keyframe、v2v（均已台账缓后）。
- **创作专区**：`neurova/aigc_studio/` 9 表短剧域 + `/api/v1/studio` 四 Phase 向导（R3/R4/R5 已落地）；生成通道全部复用上述单源。
- **画布**：`CanvasDesignerPage.vue`（2,804 行，同为**自研 DOM+SVG**：CSS transform viewport、贝塞尔 SVG 边、框选、小地图——技术路线与 basketikun 撞了个正着，证明双方独立收敛到同一形态）；边带端口 `{nodeId,portId}` 语义强于其 `{from,to}`；**缺：undo/redo（grep 零命中）、画布 JSON 导出、媒体产物节点摆图闭环**；`canvas_ops.py` op 层（11 种 op+版本递增+SessionSync 广播，agent 工具与 HTTP 共用写入口）与 basketikun 的 `canvas_apply_ops` 同构。
- **NeurFlow**：draft/publish/run/checkpoint/debug/trigger/subflow 全生命周期、`canvas_bridge` 双向编辑、自定义节点 L1/L2/L3（后端能力面强于其前端插件系统）。
- **MCP**：Neurova 同时是 MCP server（`mcp_server_api.py`）与 client；外部 Agent 经 `builtin_tools.py canvas_*` 已可操作画布——与 basketikun 的 canvas-agent 相比只缺"本地拉起器壳 + 浏览器内执行回传链"。
- **缺口确认**：提示词库域=完全缺失；浏览器直连=刻意不做（P0-2 服务端凭据决策，不回退）。

## 4. 功能面对比矩阵

| 功能面 | infinite-canvas | Neurova | 判定 |
|---|---|---|---|
| 无限画布（拖拽/缩放/框选/小地图/分组） | 自研 DOM+SVG | 自研 DOM+SVG，边带端口 | 持平（NV 语义更强） |
| 撤销/重做 | 双栈快照 undo（50 步） | **无** | IC 胜 |
| 画布文档导入导出 zip | 有（含 blob） | 仅 ComfyUI 导入 | IC 胜 |
| 节点式可执行工作流（run/publish/debug/trigger/版本回滚） | **无**（画布不可执行） | 全链 | **NV 胜** |
| 生图/图生图/参考编辑 | OpenAI/Gemini 直连 + mask 涂抹 | 三协议矩阵+服务端凭据+seed/strength | 形态 IC 胜、底座 NV 胜 |
| 视频生成 | OpenAI 任务式/Gemini LRO + 断点续轮询 | wan/seedance2/veo + task_ledger + 启动恢复 | NV 略胜（缺尾帧/v2v 在案） |
| 音频 | TTS `/audio/speech` | TTS 双通道+真实音色枚举 | 持平（双方均无 BGM） |
| 画布助手（对话驱动生成+圈选） | Responses API function tools + mask | CanvasNLDesigner（NL→整图）+ 框选 | IC 交互胜，NV 无产物落画布闭环 |
| Agent 操作画布 | canvas-agent MCP（34 工具/8 op） | canvas_* 工具 + MCP server | 机制等价，NV 缺浏览器回传壳 |
| 前端插件热载（URL+SDK） | 有（无沙箱） | 后端 L1/L2/L3 自定义节点 | 各胜一面 |
| 提示词库 | 7 源+自定义+缓存 | **无** | IC 胜 |
| 多项目/归属/协作实时 | 单人本地；WebDAV 全量同步 | project/agent 归属 v2 + SessionSync 广播 + 乐观锁 | **NV 胜** |
| 凭据安全/审计/配额 | 明文浏览器、无审计 | provider 管理+能力检测+账本 | **NV 胜** |

## 5. 整合可行性分析

### 5.1 候选路径评估

**路径 A：引入其代码/组件** — 不可行。React 19 + AntD 6 + zustand 与 Vue3 + AntD Vue + Pinia 栈不相通；3,384 行 god-component 状态/交互/生成编排全耦合；且其"浏览器直连明文密钥"形态违反 Neurova P0-2 决策。收益仅为"抄交互形态与设计模式"，不是引入。

**路径 B：iframe/子应用嵌入其 web 静态站** — 不推荐。需解决鉴权打通（Neurova 全 API `get_current_user` + 文件 token，而其配置体系独立存浏览器）、数据桥（节点 schema 与 `CanvasSnapshot` 不兼容、产物无法回流账本）、Tauri 单入口构建冲突；付出集成成本，得到的是无归属/无审计的平行数据孤岛。

**路径 C：对接其 canvas-agent（MCP 桥）** — 技术可行且近零改造（Neurova 已有 MCP server + canvas_* op 工具面），**但方向是反向输出**：不是让 Codex 操作他们的画布，而是借鉴其"op 协议 + 浏览器内执行 + SSE 回传 + 单快照回滚"形态，把 Neurova 画布的 canvas_ops 以同等质量暴露为外部 Agent 可驱动的 MCP 工具（§6 P1-2）。其 op 集里 **`run_generation` 也是 op** 这一点最值得吸收。

**路径 D（推荐）：机制择优移植** — MIT 许可允许"参考实现、Neurova 重写"（与 PRINTFILM 同级先例），把 §2.7 亮点逐条落进现有 Vue 画布与 AIGC 域。不动架构、不动凭据模型、不动核心框架，纯增量。

### 5.2 为什么"合并两个画布"是错误的整合问题

两边画布解决的是不同问题：Neurova 画布=**执行面**（工作流编辑器，节点是能力单元，产物进 dock/账本）；infinite-canvas 画布=**创作面**（产物即节点，边只是引用关系）。正确的整合是让 Neurova 画布**长出媒体产物节点形态**（image/video/audio 产物节点 + 从生成结果一键摆上画布），使创作面与执行面共用同一张 canvas_store/ops/归属底座——而不是替换或并存两个画布产品。

## 6. 可落地清单（P0/P1/P2）

> 均为"机制参考 + Neurova 自研"，MIT 合规声明按对标研究 §6 先例写入。测试先行（TDD），不改变核心框架。

**P0（高收益低成本，直接补 AIGC 画布体验差距）**
1. **画布 undo/redo**：移植其双栈快照+拖动期暂停+去抖合并+viewport 不入栈的形态（`project.tsx:477-522` 思路），落点 `CanvasDesignerPage.vue` + `canvasStores.ts`；与既有乐观锁 version 共存（undo 是会话内栈，不跨端）。
2. **媒体产物节点落画布**：新增 `image/video/audio` 产物节点类型（内容=账本产物引用，非 Blob），四生成页/Studio 镜头产物加"摆到画布"动作；生成结果自动摆放（源节点右侧偏移+自动连线）+批量网格对比/设主图形态。打通 `useWorkflowRun.ts` 既有的 SSE 点亮链。
3. **提示词库域**：后端新增只读源管理（内置源 JSON 代理拉取+SQLite 缓存+TTL，规避浏览器 CORS 与明文 key 模式），前端并入"模型与工具"菜单组 + AIGC 四页/画布 prompt chip 消费。源列表可直接收录其 7 个公开 JSON 源。

**P1（中等成本，强化平台长板）**
4. **画布 JSON 导入/导出 zip**：schema 对齐 `CanvasExportFile{app,version,projects}` 的"文档+二进制分离"形态，但 blob 走 Neurova 文件服务与属主隔离，不走 IndexedDB。
5. **对外画布 MCP 面升级**：以 `canvas_apply_ops` 单工具收敛（8→扩展 `run_generation` op），补"浏览器内执行+结果回传+单快照回滚"链（现有 `canvasOp` 广播已具备传输底座）。
6. **参考编辑交互**：mask 涂抹作为显式参考图节点进 `/images/edits` multipart 链（protocols 侧已支持多参考角色，缺前端涂抹工具与 mask 节点形态）。
7. **provider 逃生舱脚本位**：ModelPreset/provider 增加可选自定义请求脚本槽（对齐其 model script 的 `http/poll/onDelta` 注入语义），服务端执行需沙箱评审（不放 `new Function` 裸执行，登记安全边界后再做）。

**P2（观察项/暂缓）**
8. 前端远程 URL 节点插件热载：**不建议做**（无沙箱同源 JS，风险>收益；L1/L2/L3 后端自定义节点已是更强替代）。
9. 嵌套分组、WebGL 渲染层：等画布千级节点真实诉求出现再立项。
10. 视频尾帧/BGM：与其无关，维持既有缓后台账。

**hero8152 唯一吸收点**：ComfyUI sidecar 参数描述符（工作流旁挂 `<name>.config.json` 声明 `fields[]→节点输入映射`）——对 NeurFlow 模板/ComfyUI 导入的"表单化不改原图"有参考价值，可并入其缓后清单。

## 7. 风险与非目标

- **不回退治理成果**：任何整合不得引入浏览器持有密钥、无审计直连（P0-2）；其 IndexedDB 明文存储模式一律不采。
- **双画布语义漂移风险**：产物节点若实现为"可执行节点别名"会污染工作流语义；须以 `metadata.source` 区分展示型产物节点与执行节点（归属模型 v2 的"三分类=过滤视图"先例适用）。
- **React 栈惯性**：移植其代码片段时注意其依赖 zustand/localforage 的写法，一律翻译为 Pinia/后端存储，不接受新前端依赖。
- **hero8152 非商业许可**：仅读设计，禁复制任何代码。
- 其千级节点性能与无测试状况意味着：**抄形态，不背质量债**——每条移植项必须自带回归测试。

## 8. 附录

- 研究基线：basketikun v0.18.0（commit @ clone 2026-09-14，push 2026-09-07）；hero8152 main（弃用于 2026-08-28）。
- 关键锚点（infinite-canvas）：`web/src/components/canvas/infinite-canvas.tsx`（内核）、`web/src/pages/canvas/project.tsx`（编排/undo/生成链）、`web/src/services/api/{image,video,audio,prompts,model-plugin}.ts`（协议）、`canvas-agent/src/canvas/schemas.ts`（op/MCP 契约）、`web/src/lib/canvas/canvas-agent-ops.ts`、`plugins/canvas/sdk/`。
- 关键锚点（Neurova）：`neurova/llm/generators/{protocols,runtime,task_ledger,recovery}.py`、`neurova/aigc_studio/`、`neurova/collaboration/{canvas_store,canvas_ops,canvas_bridge}.py`、`NeurUI/src/modules/collaboration/CanvasDesignerPage.vue`、`NeurUI/src/composables/useWorkflowRun.ts`、`neurova/api/endpoints/{generation,studio,collaboration}_api.py`。
- 临时克隆目录 `~/ic-research`（basketikun/、hero8152/）仅供本报告研究，可随时删除。
