# reference_af（Agent-S）vs Neurova：Computer Use 与工具调用双域重点拆解评测

- **日期**：2026-11-25
- **对象**：simular-ai/Agent-S（main 快照 2026-11-24，Apache-2.0，约 5.5 万行）vs 本仓 Neurova（约 46.9 万行）
- **方法**：总评卡（`reference_af_vs_neurova_computer_use_interface_evolution_evaluation_2026-11-24.md`）的定向下钻——按 reference_ad 系列十轴细拆口径，对 **Computer Use** 与 **工具调用** 两域各拆十轴，逐轴给双方代码证据（file:line）与 10 分制评分。静态读数，未复跑对方基准。
- **结论先行**：
  - **Computer Use：Neurova 79.0 vs Agent-S 73.0**——本仓以观测通道广度、执行可靠性、安全护栏、多会话治理、产品化接入五处领先；对方以**公共基准实证**（OSWorld 72.6% 超人类 / V2 21.3% 开源 SOTA）、**VLM 指向接地**、**接口可进化**（S4 影子接口）三处领先。这是全场最接近的域：对方是"单点打穿基准的专精选手"，本仓是"全栈可控的工程体系"。
  - **工具调用：Neurova 88.5 vs Agent-S 66.0**——本仓大胜：146 工具单源注册表 + 参数白名单/能力声明、失败分级与不可重试抑制、执行记账与进程清算、MCP 双端与外部 agent 接入；对方亮点集中在**运行时工具自发现**（capabilities/doc，docstring 即检索面）与**接口可进化范式**。

---

## 1. 范围与证据基础

| 域 | Agent-S 证据面 | Neurova 证据面 |
|---|---|---|
| Computer Use | `gui_agents/s3/agents/grounding.py`（OSWorldACI，667 行）、`gui_agents/s1/aci/{Linux,Mac,Windows}OSACI.py`（平台 ACI）、`agent_s4/` 影子接口与 harness、`gui_agents/s3/bbon/`、各 README 基准数字 | `neurova/computer_use/`（actions/desktop_uia/som/guardrail/lane_mutex/session_pool/frame_registry/browser_manager/rdp_provider/ssh_runner 等 22 文件约 9.7K 行）、`tool_executor.py` 的 computer/browser 参数归一与执行段 |
| 工具调用 | S3 `@agent_action` 反射注入、S4 `seeds/combined`（capabilities/doc/call CLI）、`harness/`（prime/opencode）、`code_agent.py` | `neurova/tool_executor.py`（11155 行：execute 回退链、失败分级、重试闸、进程清算、park/恢复）、`builtin_tools.py`（单源注册表）、`core/tool_call_journal`、MCP 双端（`mcp_agent_tools_server.py` 等）、`skills/` |

双方公开基准数字（OSWorld 72.6%、OSWorld V2 21.3%、WAA 56.6%、AndroidWorld 71.6%、ScienceBoard 58.6%）引自对方 README/论文，未独立复跑。

## 2. 域 A：Computer Use（十轴，各 10 分）

### A1 观测通道 — Neurova 9.0 / Agent-S 7.5
- **Agent-S**：截图（缩放至最长边 2400，`s3/cli_app.py:326`）+ pytesseract OCR 词表（`grounding.py:249-283`）；S1 平台 ACI 另有无障碍树处理（`s1/aci/*OSACI.py`，约 48-51 个方法/平台），但 S3 主力形态已收敛为"截图+指向模型"。S4 影子接口补 atree（AT-SPI）/OOXML/gsettings 读面（`seeds/combined/helpers/`）。
- **Neurova**：截图 + **UIA 控件树快照**（`desktop_uia.py`：index/runtime_id/generation 分代、max_nodes/max_depth 观察预算）+ **SOM 编号标注图**（`som.py`：md5 量化稳定编号，跨进程一致）+ 浏览器 DOM 快照/分页读（`browser_dom_snapshot`/`browser_dom_read`）+ **操作后补拍**（`tool_executor.py:754` `computerActionRefreshTools` + ACTION_REFRESH_DELAY）。多通道互补，观测面更宽。
- **判定**：本仓通道更全（结构化树 + 像素标注 + 分页读 + 补拍闭环）；对方观测为基准特化、深度够但面窄。

### A2 元素定位与接地 — Agent-S 8.5 / Neurova 8.0
- **Agent-S**：专用指向模型通道（`generate_coords`，UI-TARS 式"Query→坐标"，`grounding.py:230-246`）+ OCR 词表 LLM 选词（`generate_text_coords`，:286-327）+ 坐标系缩放（:337-344）。覆盖"无结构化树也可定位"的面，是其基准战绩的根基；弱点：坐标解析 `re.findall(r"\d+")` 取前两数、`assert len>=2` 无重试（:244-246），文本选词失败静默落 id=0（:311-314）。
- **Neurova**：UIA 语义树定位 + **五级递降执行链**（Invoke→Toggle→ExpandCollapse→LegacyIAccessible.DoDefaultAction→PostMessage 直投→全局输入 env 门控，`desktop_uia.py:1-25`）+ SOM 稳定编号点击（`computer_click_mark`）。确定性高、可审计；**缺口：无 VLM 指向模型集成**（`som.py` 的 detector 协议留位，ONNX/OCR 检测器未接真模型），对"无树无标记"的像素面定位弱于对方。
- **判定**：接地是对方主战场且有专用模型；本仓结构化定位更稳但像素级接地缺 VLM 通道。对方小胜。

### A3 动作空间广度 — Neurova 9.0 / Agent-S 7.5
- **Agent-S**：S3 ACI 14 个 `@agent_action`（click/type/scroll/hotkey/hold_and_press/drag_and_drop/open/switch_applications/save_to_knowledge/set_cell_values/call_code_agent/wait/done/fail，`grounding.py:346-665`）；S4 影子接口另含浏览器 CDP/gsettings/OOXML 助手（可进化扩展）。set_cell_values 走 LibreOffice UNO 直连（:51-176）是表格特化亮点。
- **Neurova**：16 个 `computer_*`（screenshot/click/type/scroll/shell/dom_snapshot/click_element/set_value/som_snapshot/click_mark/list_windows/key/paste/drag/ssh_exec…，`tool_executor.py:767-790`）+ **27 个 `browser_*`**（导航/点击/填表/标签页/cookies/storage/console/download/upload/pdf/eval/drag/hover/select/check…，:791-835）。动作面显著更宽，浏览器族尤其全。
- **判定**：本仓动作空间与浏览器覆盖更广；对方的 code agent 通道与 UNO 表格直写是特色单点。

### A4 平台与远程覆盖 — Neurova 8.5 / Agent-S 8.0
- **Agent-S**：三平台 ACI（S1 Linux/Mac/Windows）+ 云 VM（AWS + OSWorld DesktopEnv，`vm/`）+ AndroidWorld 适配；S3 主力跑 Ubuntu VM。
- **Neurova**：Windows 宿主 UIA + 跨平台浏览器 + macOS/Linux backends + **RDP/SSH 远程执行**（`rdp_provider.py`/`ssh_runner.py`）+ 沙箱 provider + 移动端 relay。
- **判定**：双方都跨三平台；对方有云 VM 弹性供给与移动基准实证，本仓有远程多形态（RDP/SSH/沙箱）与产品化部署面。接近，本仓以形态广度小胜。

### A5 执行可靠性 — Neurova 8.5 / Agent-S 6.5
- **Agent-S**：计划代码 `eval` 失败仅 `wait(1.333)` 跳过一步（`worker.py:329-335`）；DONE/FAIL 靠子串误判（`cli_app.py:186-201`）；code agent 有 20 步预算与完成原因三分（DONE/FAIL/BUDGET_EXHAUSTED，`procedural_memory.py:39-49`）+ 强制 GUI 核验（:51-54）是亮点；BBoN 从 N 条 rollout 里选优兜底单次失败。
- **Neurova**：失败分级 `classifyToolFailure` + 重试决策 `retryDecisionFor`（`tool_executor.py:124-228`）、不可重试抑制窗（U11，:1917-1942）、**进程树清算** `reapToolProcessTree`（:255）、park/恢复（:392-462）、操作后补拍确认。
- **判定**：本仓的失败处理与资源清算明显更工程化；对方靠"多 rollout 选择"对冲单次失败，成本高且不解决根因。

### A6 安全护栏 — Neurova 8.5 / Agent-S 5.0
- **Agent-S**：S4 Builder 侧有 Landlock 沙箱 + 网络守卫（`builder_sandbox.py:214-217`、`shadow_evol_test_network_guard.py`）——这部分很硬；但 task agent 侧 `eval()` 裸执行模型输出（`common_utils.py:31`）、sudo 密码硬编码进系统提示（`procedural_memory.py:110,163`）、无动作确认门。
- **Neurova**：**车道互斥**（desktop/browser 车道，`lane_mutex.py`）+ **跨会话前台输入租约**（CONTROLLER_BUSY，`tool_executor.py:763-770`）+ 全局输入 env 门控（`desktop_uia.py` 五级链末级）+ 审批管理器挂接（:975）+ 动作确认档（`action_result.py`）。
- **判定**：对方 Builder 沙箱是亮点，但执行面裸奔；本仓护栏成体系。

### A7 会话与状态管理 — Neurova 8.5 / Agent-S 5.5
- **Agent-S**：单任务单会话顺序执行（基准形态），无并发会话互斥概念；S4 靠全新 VM 保证无状态。
- **Neurova**：会话池（`session_pool.py`）、帧登记（`frame_registry.py`）、跨会话前台租约、浏览器标签页 generation 代际（防陈旧引用）、SOM 会话键。
- **判定**：本仓面向"多会话共用一台真实机器"的产品形态，状态治理是刚需已做；对方研究形态无此问题。

### A8 公共基准实证 — Agent-S 9.5 / Neurova 4.0
- **Agent-S**：OSWorld 66%→**72.6%（超人类）**、OSWorld V2 **21.3% 开源 SOTA**、WAA 50.2→56.6%、AndroidWorld 68.1→71.6%、ScienceBoard 41.4→58.6%（S4 接口进化增益）。硬战绩，且判分口径诚实（V2 严格二值）。
- **Neurova**：无公共 CUA 基准接入记录；有内部盘点、真机验证与真模型基线，但缺第三方可复现锚点。
- **判定**：这是对方最强的单轴，也是本仓最该补的一块——把 computer_use 接进 OSWorld 类公共判据。

### A9 可演进性 — Agent-S 9.0 / Neurova 6.5
- **Agent-S**：S4 影子接口进化——工具库本身是被优化对象（变异/交叉/迁移/锦标赛，适应度=留出集得分），连上下文压缩策略都可进化；同一模型 3.8× 提升。**范式级创新**。
- **Neurova**：技能体系（封装/改进/生命周期）+ 肌肉记忆可沉淀工具使用经验，但 computer-use 动作面本身不可进化。
- **判定**：对方把"工具接口"变成进化对象，本仓进化对象是"技能/参数"——对方更彻底。

### A10 产品化接入面 — Neurova 8.5 / Agent-S 6.0
- **Agent-S**：pip 包 + macOS 原生 App（Virtualization.framework）+ Simular 商业 API；无操作面板/审批 UI（研究优先）。
- **Neurova**：工具结果实时回传操作面板、审批卡、移动端、渠道接入、多用户。
- **判定**：本仓的 computer use 是产品能力，对方是研究能力。

**域 A 小计：Neurova 79.0 vs Agent-S 73.0**（十轴：9+8+9+8.5+8.5+8.5+8.5+4+6.5+8.5 vs 7.5+8.5+7.5+8+6.5+5+5.5+9.5+9+6）

## 3. 域 B：工具调用（十轴，各 10 分）

### B1 生态规模与覆盖 — Neurova 9.5 / Agent-S 6.0
146 个内置工具单源注册表（`builtin_tools.py` `_BUILTIN_SCHEMAS`，实测 len=146）覆盖知识/记忆/文件/网络/AIGC/协作/治理；对方 14 个 ACI 动作 + 影子接口 14 个种子函数 + code agent（python/bash）。规模差一个量级。

### B2 注册与 schema 纪律 — Neurova 9.0 / Agent-S 7.0
- **Neurova**：单源注册表 + 每工具参数白名单（`_COMPUTER_TOOL_PARAM_KEYS` 43 组，`tool_executor.py:767-835`）+ button 词表别名归一 + 数值强转（R1-3 归一化层）+ 能力声明（readOnly/concurrentSafe/writeScopes）。
- **Agent-S**：`@agent_action` 装饰器 + `inspect.signature` 反射生成 API 文档（`procedural_memory.py:74-85`）——优雅且零维护；但参数无白名单、最终 `eval` 直传执行。

### B3 工具发现机制 — Agent-S 8.5 / Neurova 8.0
- **Agent-S（S4）**：`python -m shadow_interface capabilities | doc <name>` 运行时自发现，**docstring 即检索面**，Builder 提示词明确要求可发现性（无 docstring 的工具会被 agent 略过）——工具检索的"自描述"范式，值得本仓借鉴。
- **Neurova**：静态 schema 注入 + A6 工具搜索（控制工具拦截 + 调用账本，`core/tool_call_journal`）。
- **判定**：对方的运行时自发现对"工具库动态进化"是必要件；本仓静态注入在工具集固定时更稳。

### B4 执行管道治理 — Neurova 9.5 / Agent-S 5.5
- **Neurova**：`execute` 回退链（工作流→内置分派表→Skill→ToolRouter，`tool_executor.py:1877-1915`）+ tool_call_journal 先记账再执行 + 超时/预算 + **进程树清算** + park/恢复。
- **Agent-S**：`eval(code)` 直接执行（`common_utils.py:31`）；code agent 有步数预算；S4 任务 agent 侧有 VM 级隔离与步数上限，但单步工具调用无超时/清算概念。

### B5 失败处理与重试纪律 — Neurova 9.0 / Agent-S 6.5
- **Neurova**：失败分级（classifyToolFailure）→ 重试决策（retryDecisionFor，变异类默认不重试）→ **不可重试抑制窗**（同参指纹拒绝重复真执行，:1917-1942）→ 并发重入防护（变异类拒绝双执行，:1930-1937）。
- **Agent-S**：LLM 面三层容错（backoff/safe/格式重问）扎实；工具执行面失败=跳过一步，无分级、无抑制。

### B6 安全治理 — Neurova 9.0 / Agent-S 5.5
本仓：审批链、租户隔离、SSRF url_guard、凭据后缀+脱敏、审计；对方：Landlock+网络守卫（Builder 侧）之外，task agent 工具执行无审批/无审计，sudo 口令进提示词。

### B7 记忆与学习 — Neurova 8.5 / Agent-S 6.0
- **Neurova**：肌肉记忆三级（指纹+语义+成功率匹配，高置信自动执行不绕治理）+ 工具统计 + 进化反馈闭环。
- **Agent-S**：`save_to_knowledge` 回合内 notes + S4 `notebook.jsonl` 跨变异观察（进化代际间持久），但无使用统计驱动的自动执行。

### B8 扩展协议 — Neurova 9.0 / Agent-S 7.5
- **Neurova**：MCP client+server 双端、外部编码 agent（neuacp/ACP）、技能市场与治理。
- **Agent-S**：S4 影子接口 = **可进化的 Python 工具库**（范式创新，接口即进化对象）；但无 MCP/外部 agent 协议面。
- **判定**：本仓协议生态全；对方的"接口可进化"是独特贡献（已在 P0 借鉴中吸收其纪律）。

### B9 可观测性 — Neurova 8.5 / Agent-S 7.0
本仓：span trace、tool_call_journal 调用账本、轨迹效率判据；对方：trajectory jsonl、builder logs、cost events（S4 SQLite 记账很完整），但 S3 单步执行缺结构化 span。

### B10 工程稳健性 — Neurova 8.5 / Agent-S 6.5
本仓：并发重入防护、幂等声明、尺寸棘轮、参数归一化层、大测试面；对方：S4 侧 SQLite/原子 transit/Landlock 很硬，S3 执行面 eval 裸奔、单机假设、硬编码口令。

**域 B 小计：Neurova 88.5 vs Agent-S 66.0**（十轴：9.5+9+8+9.5+9+9+8.5+9+8.5+8.5 vs 6+7+8.5+5.5+6.5+5.5+6+7.5+7+6.5）

## 4. 汇总与校准说明

| 域 | Neurova | Agent-S | 差距 |
|---|---|---|---|
| A. Computer Use（百分制折算） | **79.0** | 73.0 | 本仓 +6.0 |
| B. 工具调用（百分制折算） | **88.5** | 66.0 | 本仓 +22.5 |

与总评卡的校准：总评卡"感知与接地 7.5 vs 8.5、工具与接口 9.0 vs 8.0"是十维粗粒度；本细拆下钻后——观测通道（A1）本仓实际更宽（UIA 树+SOM+补拍+分页读此前被低估），接地单轴（A2）对方仍领先；工具域把"接口体系"拆开后对方的发现机制（B3）与可进化范式（B8/A9）是真亮点，但治理/纪律/生态差距被细拆放大。两处读数不矛盾：粗卡看的是"域综合",细拆看的是"轴分布"。

## 5. 聚焦两域的借鉴实施卡（细化版，不与总评卡 P0 重复）

> 每卡五要素：对方证据（file:line）→ 本仓落点（file:line）→ 方案要点 → 验收敛据（先红后绿）→ 优先级与边界。

### 卡 T1 · 工具运行时自发现目录（来自 B3，P1）

- **对方证据**：S4 任务 agent 用 `python -m shadow_interface capabilities`（列全部工具+签名）与 `doc <name>`（单工具文档）自发现工具（`osworld_setup/s4/seeds/combined/cli.py:48-110`，`_discover_modules/_public_fns` 自动枚举）；Builder 提示词把"可发现性"定为纪律——无 docstring 的工具会被 agent 略过（`prompts/combined.md` Discoverability 节）。
- **本仓落点**：`neurova/builtin_tools.py`（`_BUILTIN_SCHEMAS` 单源注册表，实测 146 个）+ `neurova/tool_executor.py`（`ToolExecutor.execute` 分派）。新增只读工具 `tool_catalog_search(keyword="", tag="", limit=20)` 与 `tool_doc(tool_name)`：从注册表按名称/描述/能力标记（readOnly/writeScopes/interactive_desktop 等）检索，返回名称、描述、参数 schema 摘要；`tool_doc` 返回单工具全量 schema+docstring。
- **方案要点**：① 只读、无副作用、不进变异类重试抑制；② 按 agent 租户/权限过滤可见面（与既有工具可见性同源，不新增第二套权限判定）；③ 输出有界（limit 上限+描述截断），防目录刷爆上下文；④ 与 A6 工具搜索互补：A6 管"控制与记账"，本卡管"agent 主动检索"。
- **验收判据**：红灯——用例调用 `tool_catalog_search` 时工具不存在（TypeError/unknown tool）；绿灯——`tool_catalog_search(keyword="screenshot")` 命中 computer_screenshot 等并含参数 schema；`tool_doc("computer_click")` 返回白名单键说明；未注册名返回结构化 not_found（不抛裸异常）；无权限工具不出现在目录。
- **优先级/边界**：P1。不做工具自动执行推荐（那是肌肉记忆的职责），目录只做"发现"。

### 卡 T2 · VLM 指向接地通道（来自 A2，P1）

- **对方证据**：`grounding.py:230-246` `generate_coords`——"Query+截图→指向模型→坐标"，配 `resize_coordinates`（:337-344）做坐标系换算；OCR 词表+LLM 选词兜文本定位（:286-327）。弱点也明确：正则取前两数、`assert len>=2` 无重试。
- **本仓落点**：`neurova/computer_use/som.py` 的 `SomDetector` 协议与 `SOM_DETECTOR_ENV` 选型位（P3-10 已留）——新增 `vlm_pointing.py`：实现 `callable(png_bytes, target_description) -> (x, y)` 指向器，走既有 LLM/VLM 通道（`llm_client`，视觉输入同 `image_pipeline` 现有装配），输出经界内 clamp 与置信不足诚实降级。
- **方案要点**：① 定位为 **第三档接地**：UIA 树（有结构化元素）→ SOM（无树可标注）→ VLM 指向（无树无标记的像素面）；② 解析容错比照对方弱点反向做：多格式解析（纯数字对/JSON/markdown）+ 1 次重问 + 失败返回结构化 `grounding_failed`（不编坐标）；③ 每次指向记审计（耗时/模型/命中与否），成本手动档口径。
- **验收判据**：红灯——`vlm_pointing` 模块不存在的导入失败；绿灯——桩 VLM 返回坐标 → 指向器输出界内坐标；桩返回乱码 → 结构化失败而非异常上抛；fallback 链单测：UIA 可用时不调 VLM。
- **优先级/边界**：P1。仅作定位兜底档，不替代 UIA/SOM 主路径（确定性优先）；默认关（env 灰度），防评测/生产成本意外。

### 卡 T3 · 公共 CUA 基准接入（来自 A8，P1，与总评 P0-① 同向）

- **对方证据**：`agent_s4/eval/osworld.py`（共享评测 worker：备 VM→跑 episode→`env.evaluate()`，`persist_evaluation_result` 归一 [0,1]）；判分纪律=严格二值+**基建失败≠零分**（`tournament.py:67-77`）。
- **本仓落点**：`neurova/benchmark/` 新增 `cua_eval.py`：任务=「指令+初始状态准备+判据 check(终态观测)」；执行=computer_use 动作循环（复用 `ToolExecutor.execute` 管线，含护栏/审计）+ 终态取证（UIA 快照/截图/文件读回）；判分沿用 `suite_eval` 口径（judged/infra 分类，P0-② 已铺）。评测对象先做**本机桌面受控任务**（记事本/文件管理器/浏览器），OSWorld 全量接入另批。
- **方案要点**：① 判据注入式（与 suite_eval 同构，执行器只产事实）；② **评测手动跑+成本标注**（D-H 纪律，CI 不接真桌面跑）；③ 每任务失败分类：task_failed vs infra_failure（评测器/驱动崩溃不计任务失败）；④ 产出直接可作 P0-① 的外部适应度源（进化适应度锚定的数据接口对齐 `evolution/eval/fitness.py`）。
- **验收判据**：红灯——`cua_eval` 模块不存在；绿灯——桩 agent+临时桌面任务（如"在记事本写入 X"）跑通一题，报告含 tasks_judged/tasks_infra_failed/failure_class；驱动异常记 infra 不记任务失败；无 desktop 权限时诚实 skip。
- **优先级/边界**：P1。先本机受控任务建立判据与口径，公共基准（OSWorld VM 供给）依赖外部环境，另批立项。

### 卡 T4 · Office/文档结构化直写（来自 A3，P2）

- **对方证据**：`grounding.py:51-176` `SET_CELL_VALUES_CMD`——经 LibreOffice UNO 接口直写单元格（值/公式/类型分派），绕开逐格 GUI 点击；配套"code agent 改完必须 GUI 复核"纪律（`procedural_memory.py:51-54`）。
- **本仓落点**：`neurova/computer_use/` 新增 `structured_edit.py` + 注册 `computer_doc_edit` 工具：对**沙箱工作区内**的 xlsx/docx/csv 用 openpyxl/python-docx 直写（单元格区间/段落替换），返回改前/改后摘要；GUI 侧再以 UIA 读回核验（两段式：直写+复核）。
- **方案要点**：① 路径白名单（仅沙箱工作区，复用既有沙箱 provider 纪律）；② 写后必须回读校验（写→读→比对→结果带 diff 摘要），失败如实报；③ 与 GUI 动作互斥（取得 desktop 车道后再动文件，防同时改）。
- **验收判据**：红灯——工具不存在；绿灯——临时 xlsx 设 A1:C3 值 → 回读一致、结果含 diff 摘要；路径越界 → 结构化拒绝；文件被占用 → 诚实失败不半写。
- **优先级/边界**：P2。先 xlsx/csv（openpyxl 成熟），docx 次之；不做 UNO/进程注入（维护面大），走文件直写+GUI 复核两段式。

### 卡 T5 · 动作前后帧+局部放大确认读数（来自 A1/A5，P2）

- **对方证据**：`bbon/behavior_narrator.py:36-168`——动作前帧画标记（红圈 Click/蓝圈 MoveTo/绿圈 DragTo）、动作点 300×300 裁剪 + 4× Lanczos 放大 + 原图红框，喂给 VLM 产出"事实变化清单"；这是 BBoN 裁决与调试的读数基础。
- **本仓落点**：`neurova/computer_use/frame_registry.py`（帧登记）+ `actions.py` 执行段：前台动作执行**前取帧、后补拍**（既有 ACTION_REFRESH 机制）基础上，增加**动作点局部裁剪**（以 (x,y) 为中心 300×300，可配）作为 `action_result` 的附带证据帧（有界尺寸、可关）。
- **方案要点**：① 证据帧进 ActionResult 的 `evidence` 段（截断/压缩，防上下文膨胀）；② 供三处消费：操作面板人工复核、审批证据、失败归因（配合 T3 判据的终态取证）；③ 隐私边界：证据帧留存遵循既有会话归档纪律，不新增第二套留存策略。
- **验收判据**：红灯——ActionResult 无 evidence 帧；绿灯——click 后结果含 before/after 引用与 crop 元数据（坐标+尺寸）；guardrail 拒绝的动作不产帧；关闭开关时零变化。
- **优先级/边界**：P2。仅前台输入族动作启用（点击/拖拽/按键），滚动/截图类不产帧。

**优先级汇总**：T1/T2/T3 = P1（T3 与总评 P0-① 同向，建议合并立项）；T4/T5 = P2。五卡均为增量工具/证据面，不动既有动作语义；默认关或按灰度接入的项（T2/T5）须带开关测试。

**不学清单（两域）**：`eval()` 裸执行模型输出；DONE/FAIL 子串终止判定；坐标正则取数无重试；sudo 口令进提示词；为基准分数牺牲多会话治理。

## 6. 局限

- 静态代码读数，未复跑 OSWorld/WAA；对方分数系其 README/论文口径。
- 本仓侧 computer use 未接公共基准，A8 的 4.0 反映的是"缺第三方锚点"而非"实测更差"。
- Agent-S 的 S1 平台 ACI（Windows/Mac）与 S3 主力形态差异较大， Platform 覆盖评分按"仓库具备该能力"计。
