# Neurova × open-codex-computer-use 代码级对比报告

> 日期：2026-09-12
> 对象：[iFurySt/open-codex-computer-use](https://github.com/iFurySt/open-codex-computer-use)（下称 OCU，MIT，Swift≈15k 行 + Linux Python + Windows Go/PowerShell）
> 我方：`neurova/computer_use/`（≈4,000 行）+ `api/endpoints/computer.py`（803 行）+ `tool_executor.py` 计算机工具族 + 浏览器栈（`browser_manager.py` 1,117 行 / camofox 1,150 行）
> 结论速览：**OCU 没有浏览器栈，Neurova 反超；但 OCU 的桌面端 CUA 在"观察-行动契约、坐标换算、点击递降链、诚实降级、测试体系"五个维度全面领先，共提炼 17 条改进项（P0×4 / P1×8 / P2×5）。**

---

## 1. OCU 项目速览

定位：把 OpenAI Codex 的 Computer Use 能力做成开源等价物 —— 一个**非侵入式（non-intrusive）**的桌面控制服务，以 **stdio MCP server + CLI + agent 技能包** 三种形态分发。核心思路：**优先走 Accessibility（辅助功能）API 语义操作，默认永不移动用户真实鼠标指针、永不抢焦点**。

平台矩阵（同一套 9 工具契约，三平台各自实现运行时）：

| 平台 | 运行时 | 技术栈 | 非侵入手段 |
|---|---|---|---|
| macOS 14+ | Swift（`OpenComputerUseKit`） | AX API + ScreenCaptureKit + CGEvent + 私有 SkyLight SPI | AXPress / `CGEvent.postToPid` / sky_click 后台窗口路径 |
| Linux | Python（`apps/OpenComputerUseLinux/runtime.py`） | AT-SPI2（桌面会话 DBus） | AT-SPI 语义动作 |
| Windows | Go 壳 + PowerShell（`apps/OpenComputerUseWindows/`） | UIAutomationClient + Win32 `PostMessage`（WM_LBUTTONDOWN 等） | 消息直投目标窗口 |

工具面（`ToolDefinitions.swift`，仅 9 个，高度收敛）：
`list_apps` / `get_app_state`（截图+a11y树）/ `click` / `perform_secondary_action` / `scroll` / `drag` / `type_text` / `press_key` / `set_value`。

工程化亮点：2,437 行核心单测、Fixture 假目标 app（`OpenComputerUseFixture` + `FixtureBridge`）、smoke/stress/agent-smoke 三层测试（`run-agent-smoke-tests.mjs` 真实驱动 claude/codex/hermes 端到端跑场景）、Go 探针 CLI、`doctor` 权限自检、macOS 权限引导 onboarding app、npm 多平台二进制分发、SKILL.md 技能包教 agent 正确用法。

## 2. 架构对照

| 维度 | OCU | Neurova 现状 |
|---|---|---|
| 形态 | 独立 MCP 服务/CLI，单用户本地 | 服务内嵌模块 + REST `/v1/computer` + WS 流，多租户 |
| 桌面观察 | 窗口级截图 + a11y 树 + element index（一次 `get_app_state` 全给） | 全屏截图（PIL ImageGrab，仅主屏）+ 盲坐标点击；**桌面无元素枚举** |
| 浏览器 | 无 | Playwright/camofox 双后端 + aria snapshot + role 定位 + generation 防过期（Neurova 强项） |
| 动作契约 | 每个动作 tool 都带 `app` 参数；动作后**自动回传刷新快照** | 动作只回元数据，需 agent 手动再 snapshot |
| 坐标系 | 截图像素 → 窗口逻辑坐标 → 全局坐标，**DPI/Retina 精确换算** | 屏幕像素直传，无 DPI/多显示器处理 |
| 点击策略 | 五层递降链 + 合成侧动作过滤 + Electron web-row 特判 | 直接 pyautogui.click(x,y)，无递降 |
| 输入投递 | AX 语义 → app 直投（postToPid/PostMessage）→ 全局指针（env 门控） | pyautogui（全局指针，必抢焦点） |
| 降级诚实性 | 降级路径写入结果文本（drag delivery note） | camofox ref 正则失配静默失败 |
| 安全 | env 门控 + SKILL.md 行为纪律 | governance→sandbox(AppContainer等)→approval 状态机（Neurova 强项） |
| 观察预算 | text_limit(500/max) + max_tree_nodes(1200) + max_tree_depth(64) | 固定 8,000 字符截断 |
| 测试 | Fixture app + 2,437 行单测 + agent-smoke 三场景 | 浏览器端 39+35+20 绿；**桌面端零测试** |

## 3. OCU 可借鉴机制详解（源码锚点）

### 3.1 观察后行动状态机 + 动作自动回传刷新状态 ⭐ 最核心
- `ComputerUseService.snapshotsByApp`（`ComputerUseService.swift:450`）按 app 名/bundleId 缓存快照，element_index 跨动作复用；`click/scroll/type_text/set_value/drag` 全部执行完 `refreshSnapshot` 后以 `.actionResult` 样式返回**新截图 + 新 a11y 树**（同文件 :519/:648/:726/:769/:825）。
- 效果：agent 一个动作换来一次"看"，闭环密度翻倍，天然消解 UI 变化导致的索引失效。
- Neurova 差距：`tool_executor.py:2585` 起的动作只回 `size_bytes` 元数据，agent 想看结果必须再调一次 `computer_screenshot`（多一轮 LLM 往返 + 更容易放弃观察直接盲点）。

### 3.2 截图像素坐标精确换算（Retina/HiDPI）
- `screenshotPixelScale()`（`ComputerUseService.swift:222`）：用 PNG 实际像素尺寸 ÷ 窗口逻辑尺寸得 scale，`screenshotPixelToWindowPoint()`(:243) 把 LLM 给的截图像素坐标换算回窗口点，再 `windowPointToGlobalPoint()`(:1676) 加窗口偏移。
- Neurova 差距：`computer_use/__init__.py:81-96` `ImageGrab.grab(region)` 无 DPI 感知、无 `all_screens=True`，多显示器/缩放 150% 环境下坐标必错。

### 3.3 五层点击递降链 + 反幻觉过滤
`performAXClickSequence`（:993）顺序：
1. 元素自身 AXPress → AXConfirm → AXOpen（`performPreferredClick` :887，含"包含列表项选中"优化 :949）
2. 后代元素扫描（限深 3 层，按可点击优先级+面积排序）
3. 命中测试 + 邻近点扫描（中心点+前导点，`localClickActionPoints` :272）
4. **合成侧动作过滤**（`isLikelySyntheticSideActionCandidate` :290：过滤"完成/Archive"等隐藏滑出按钮，防点错）
5. activation fallback（Raise+Main+Focused）→ 非 AX 直投 → 全局指针（需 env 门控）
另有 Electron/飞书 web-row 特判（:406-447）与 static text 自动升级为所在行点击（`clickFrame` :1515）。
Neurova 差距：桌面 `computer_click` 就是 pyautogui 一发入魂，点错无任何救济；浏览器端有 role 定位但 camofox 的 ref 解析是正则匹配 YAML 行（`camofox_server_backend.py:614`），名字含引号/重复名静默失配。

### 3.4 诚实降级文案（假成功可读化）
`dragDeliveryNote`（:204）：app_post 拖拽**无法驱动窗口服务器拖拽会话**（窗口移动/划选文本/Finder 拖放会无效），结果文本明确写 "Drag delivered via app_post: ... 如果拖拽没效果，设置 env var 走全局指针路径"。**把系统限制讲给 agent 听，而不是装成功。**
Neurova 对照：camofox `_find_ref_in_yaml` 失配返回的不是结构化失败原因；`/status` 的 `desktop_available` 只反映截图后端（`computer.py:520-524`），点击能力（pyautogui）可能不可用却报可用。

### 3.5 智能文本输入
`typeText`（:751）两级：优先对 **focused 可编辑元素直接 set value**（带占位符识别/零宽字符清洗/子节点文本聚合 :1402-1478），失败才检查 role 是否文本域后走键盘投递。杜绝"焦点在哪打哪"。
Neurova 差距：`computer_type` = pyautogui.typewrite 盲打，焦点错误时把密码打进搜索框这类事故无法防。

### 3.6 观察预算参数化
`get_app_state` 的 `text_limit`（默认 500，支持 "max"）+ `max_tree_nodes`（1200）+ `max_tree_depth`（64），动作返回的刷新快照用默认预算防上下文膨胀（`usage.md` 明确"显式调用才可放大预算"）。
Neurova：`browser_dom_snapshot` 固定 8,000 字符截断（`tool_executor.py:2866`），无节点预算参数。

### 3.7 全局指针门控（env 三态）
`OPEN_COMPUTER_USE_ALLOW_GLOBAL_POINTER_FALLBACKS=1`（:177）显式开启后才允许可能移动真实指针/抢焦点的路径；`click_method` 显式指定时**绝不静默回退**（`validateClickMethod` :38）。"auto 可递降、explicit 不回退"是很好的契约。
Neurova：桌面动作全部走全局指针（pyautogui），没有"非侵入"档位；但 Neurova 有 governance/approval 链，粒度更细 —— 缺的是**投递路径维度**的分级，不是审批维度。

### 3.8 Fixture 测试体系 + agent-smoke
- `OpenComputerUseFixture`（477 行假目标 app）+ `FixtureBridge` 双向通信：所有 service 动作在 fixture 模式下走 bridge（`snapshot.mode == .fixture` 分支遍布 `ComputerUseService`），2,437 行单测可离线跑。
- `make agent-smoke`（`run-agent-smoke-tests.mjs`）：真实驱动 claude/codex/hermes 完成场景任务（list-apps / fixture / fixture-full），带预算上限（claude-budget-usd）与超时。
- Neurova：桌面端 0 测试；这是唯一无法靠"读代码+改代码"补齐的维度，需要自建 fixture。

### 3.9 软件光标可视化
`SoftwareCursorOverlay`（870 行）：在目标窗口上渲染合成光标移动 + 点击脉冲动画，用户可实时看到 agent 在操作哪里（可 env 关闭）。对"信任感"和演示价值极大。
Neurova：前端 `ComputerUsePanel.vue` 已有截图直播 + 点穿映射，缺的只是"agent 点击位置标记"这最后一层。

### 3.10 app 目录带使用频率
`AppDiscovery`（577 行）：`list_apps` 返回运行中 + 近 14 天用过的 app，带 last-used 与使用频率排序（macOS 走 Spotlight `kMDItemLastUsedDate_Ranking`），帮 agent 直接选对 app 名，减少解析失败。

## 4. Neurova 反超项（不要妄自菲薄）

1. **整个浏览器自动化栈 OCU 为零**：Playwright/camofox 双后端、aria snapshot、role+name+generation 新鲜度契约、分块读取（60k/8k + resume）、per-user camofox 池化隔离 —— 这些 OCU 完全没有。
2. **治理链完整度高一个量级**：skill 仲裁 → governance evaluate（多段 shell 全白名单）→ 真实沙箱（AppContainer/Seatbelt/Bubblewrap/Docker）→ approval SQLite 状态机 → 防火墙。OCU 只有 env 开关 + 文档纪律。
3. **多租户与流式**：per-user 会话隔离、WS `computer_action` 事件流 + seq gap 检测、前端实时面板。OCU 是单用户本地进程。
4. **截图双通道**：base64 永不进 LLM 上下文/会话存储（只走 WS 旁路），上下文经济性设计领先。
5. **PlanningTool + 计划模式**：OCU 无规划层。

## 5. 改进清单（按优先级）

### P0 — 桌面盲区根治
| # | 项 | 落地建议 | 关键锚点 |
|---|---|---|---|
| P0-1 | 桌面点击加 a11y 元素目标，消灭盲点击 | Windows 上引入 `uiautomation`/`pywinauto`：新增 `computer_dom_snapshot`（返回带 index 的控件树）与 `computer_click_element`；OCU Windows runtime.ps1（1,008 行，UIA+PostMessage）是现成参考实现，语义可直接翻译成 Python | `builtin_tools.py:101-267`、`tool_executor.py:2585` |
| P0-2 | DPI/多显示器坐标链 | `ImageGrab.grab(all_screens=True)` + 进程 DPI awareness + PNG 像素/逻辑尺寸 scale 换算（照抄 OCU 三函数语义）；前端 ComputerUsePanel 的 naturalWidth 换算已有，后端补齐即可 | `computer_use/__init__.py:81-96` |
| P0-3 | 动作后自动回传刷新截图 | `computer_click/type/scroll` 成功后随结果附 `(has_refreshed_screenshot=True)` 并走 `computer_action` WS 通道推新帧，LLM 结果里带一句 "已回传刷新截图"，形成 OCU 式观察闭环 | `tool_executor.py:2585-2610`、`_emit_computer_event:2733` |
| P0-4 | scroll 方向 bug 根修 | `computer.py:424` `abs(int(body.dy))` 丢符号 + dx 整体被忽略；agent 路径 `tool_executor.py:2673` 的 sign 语义同样是歧义源。按 pyautogui 契约（正=上）统一单源换算，两处消费方同步修（修复教义 #5 放大视角） | `computer.py:419-427`、`tool_executor.py:2673` |

### P1 — 协议与诚实性
| # | 项 | 落地建议 |
|---|---|---|
| P1-1 | 降级诚实化 | 浏览器/桌面所有 fallback 结果声明实际投递路径（学 drag delivery note）；camofox `_find_ref_in_yaml` 失配返回结构化错误（含最近似候选名），禁止静默 |
| P1-2 | 桌面能力自检 doctor 化 | `/status` 的 `desktop_available` 拆成 `screenshot_available` + `input_available`（pyautogui 真实探测），新增 `/doctor` 端点（权限/桌面会话/pyautogui/PIL 逐项） |
| P1-3 | 观察预算参数化 | `browser_dom_snapshot` 加 `max_nodes/max_depth`（Playwright aria snapshot 可裁剪），沿用"显式调用才放大"规则 |
| P1-4 | type_text 语义化 | 桌面路径先探 focused 可编辑控件（UIA ValuePattern）直接赋值，失败再键盘投递 |
| P1-5 | dispatch 三副本合并 | `computer.py:332/747` 重复注册 `/browser/execute` + 三份 if/elif 映射收敛到 `_dispatch_browser_command` 单源 |
| P1-6 | vision 三模块处置 | `vision.py/vision_basic.py/vision_lite.py`（1,400 行）生产零引用（仅 1 个测试文件引用）。二选一：接入 P0-1 作为元素检测兜底，或按反向清理先例（-1,485 行）删除 |
| P1-7 | 死接线收口 | `ComputerUseManager._get_firewall`（`__init__.py:59`）从未被调用：接入 shell/file 路径或删除 |
| P1-8 | 序列动作 | 借鉴 `call --calls`：`browser_execute`/computer 工具支持批量动作数组，单次往返完成 观察→点→打→观察 |

### P2 — 体系化
| # | 项 | 落地建议 |
|---|---|---|
| P2-1 | 桌面 Fixture 测试体系 | 自建最小 fixture 窗口（tkinter 假目标 + 命令桥），桌面动作单测离线化；对齐 OCU agent-smoke 的场景化评测（预算+超时+判分） |
| P2-2 | 前端点击位置可视化 | `ComputerUsePanel.vue` 加合成光标/点击脉冲图层（WS 已推 computer_action 坐标，纯前端活） |
| P2-3 | list_apps 使用频率 | Windows 上读注册表/壳近期文档记录，返回排序目录减少 app 名解析失败 |
| P2-4 | CUA 导出为 MCP server | Neurova 已有 MCP 生态；把 computer/browser 工具族包一层 stdio MCP，让外部 agent（ZCode 等）直接消费 Neurova 的 CUA —— OCU 的产品形态证明这条路成立 |
| P2-5 | SKILL.md 式使用纪律 | 给 Neurova CUA 写技能文档：观察先行/不要跨快照用 index/敏感 app 禁区/外部可见动作先问 —— 对 agent 成功率影响不亚于代码改进 |

### 不建议照搬
- **私有 SkyLight SPI（sky_click）**：非 API 稳定面，macOS 升级即碎，OCU 自己都标注 "re-validate after macOS upgrades"；Neurova 无 macOS 桌面主场景，不值得投入。
- **软件光标 overlay 全套（1,900 行）**：Neurova 用前端图层即可达到同效（P2-2），不需要系统级 overlay。
- **三平台运行时矩阵**：Neurova 生产主战场是 Windows，先做深 Windows（UIA 路线 P0-1）+ 浏览器双后端，Linux/macOS 桌面随需。

## 6. 一句话总结

OCU 用"**a11y 优先 + app 作用域 + 动作即观察 + 诚实降级 + fixture 全覆盖**"把桌面 CUA 做成了一套可测试、可信任的协议；Neurova 的浏览器栈和治理链反超，但桌面端还停在"全屏截图 + 盲点击 + 静默降级"的原始形态 —— **P0 四项做完，桌面端才第一次拥有和浏览器端对等的语义契约。**
