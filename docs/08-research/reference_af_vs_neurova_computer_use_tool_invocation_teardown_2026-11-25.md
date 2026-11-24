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

## 5. 聚焦两域的新借鉴点（不与总评卡 P0 重复）

1. **工具运行时自发现（B3，P1）**：本仓工具面大，可给 agent 增加只读"工具目录"自描述通道（按能力/关键字检索工具 docstring 与参数 schema），降低长尾工具的发现成本——对方的 capabilities/doc 是现成范式。
2. **VLM 指向接地通道（A2，P1）**：som.py 的 detector 协议已留位，接一个指向模型（或复用现有 VLM 通道）补齐"无树无标记"像素面定位，与 UIA/SOM 形成三档互补。
3. **公共 CUA 基准接入（A8，P1）**：把 computer_use 动作面接 OSWorld 类判据做一次诚实实测，建立第三方可复现锚点（对方判分纪律：严格二值+基建失败≠零分，与本仓 P0-② 同向）。
4. **表格/文档结构化直写（A3，P2）**：对方的 set_cell_values（UNO 直连）思路可迁移为"office 文档结构化读写工具"，绕开逐格 GUI 点击。
5. **动作后补拍确认标准化（A1，已有，保持）**：本仓 ACTION_REFRESH 已做，对方的"操作前后帧+局部放大"（BBoN narrator 的 zoomed view，`behavior_narrator.py:106-168`）可增强确认读数，供审批/回放复用。

**不学清单（两域）**：`eval()` 裸执行模型输出；DONE/FAIL 子串终止判定；坐标正则取数无重试；sudo 口令进提示词；为基准分数牺牲多会话治理。

## 6. 局限

- 静态代码读数，未复跑 OSWorld/WAA；对方分数系其 README/论文口径。
- 本仓侧 computer use 未接公共基准，A8 的 4.0 反映的是"缺第三方锚点"而非"实测更差"。
- Agent-S 的 S1 平台 ACI（Windows/Mac）与 S3 主力形态差异较大， Platform 覆盖评分按"仓库具备该能力"计。
