# ZCode 电脑操控（Computer Use）对照评测——Neurova 视角

- 日期：2026-11-17
- 对象：zai-org/ZCode（克隆件 `E:/Projects/_external_repos/zai-org-ZCode`，只读参照）
- 方法：代码级逐文件阅读（桌面 CUA 侧与 Neurova computer_use 侧各一个独立深读通道交叉验证），行号均为当日实测
- 关联：`reference_w_vs_neurova_harness_code_comparison_2026-11-14.md`（总评）、
  `reference_w_tool_inventory_comparison_2026-11-15.md`（工具清单）、
  `reference_w_agent_loop_comparison_2026-11-15.md`（loop 机制）

## 0. 评测口径与结论速览

口径三条：

1. **只认克隆件内可核验的代码与随仓契约文档。** ZCode 的 CUA 真实执行体
   （producer：MCP server、Helper 运行时、`ax_native.node`、PiP 面板）在开源构建中
   是 fail-closed 占位包（`packages/zcode-cua/index.js:1-14`，所有执行入口返回
   "Computer Use is not available in this build."）。其执行面按「消费侧完备度 +
   随仓契约文档」计分，不臆测私有实现质量。
2. **范围以桌面/原生应用操控为主。** 浏览器域两边都是独立面（ZCode 的
   browser-use-plugin、Neurova 的 `browser_*` 工具族），只在边界处说明，不重复计分。
3. Neurova 侧以 main 现状为准（含此前各批次已落地能力）。

**结论：ZCode 69/80（折合 8.6/10） vs Neurova 63.5/80（折合 7.9/10）。**
ZCode 赢在权限工程（TCC 授权主体＋验签＋凭据卫生＋防伪造应用身份）、循环集成纪律
（帧权威/媒体预算降级/重试三值语义）与 Helper 生命周期状态机；Neurova 赢在真实可跑的
全栈在仓实现、远程操控平面（沙箱/RDP/SSH/来宾代理）、能力诚实面（六轴三态＋/doctor）
与行为级 e2e 仿真。差距最大的三处：**观测帧权威、动作重试语义、子代理操控策略**。

## 1. 两边形态总览

| | ZCode | Neurova |
|---|---|---|
| 架构形态 | 模型侧无独立 CUA 工具；CUA 藏在 `node_repl` 的 `js` 工具里，经 `agent.computerUse` SDK 命名空间暴露 | 一等工具面：`computer_*` 11 个＋`browser_*` 31 个直接注册进 LLM 工具清单 |
| 执行链 | node_repl Worker SDK → `Symbol.for` 桥 → 主线程 broker（unix socket / named pipe）→ Helper 进程 → 私有 producer | `tool_executor` 分发咽喉（门控→身份注入→参数归一→运行档门→审计→沙箱域）→ 多后端管理器 |
| 本机后端 | macOS 签名 Helper app（TCC 主体）；Windows Electron Node 运行时＋`ax_native.node` 原生模块 | pyautogui＋PIL（本机）、`uiautomation`（桌面语义层）、Playwright/Scrapling/Camofox（浏览器） |
| 远程平面 | 无（desktop-attached-remote 仅 attachment，不装 Helper） | `RemoteComputerUseManager`（来宾代理 HTTP）＋ `DesktopSessionPool`（Windows 沙箱 .wsb / RDP 直连）＋ SSH |
| 开源可见性 | producer 私有（占位 fail-closed）；消费侧全链路在仓 | 全栈在仓，可直接运行与测试 |

ZCode 把「电脑操控」做成**独立权限主体＋进程隔离的系统能力**：Helper 是唯一的
输入注入/屏幕读取者，ZCode 主进程通过 broker 与之通信，凭据按调用签发。
Neurova 把「电脑操控」做成**工具族＋多后端管理器**：与文件、浏览器、shell 同层，
执行在服务进程内完成，靠运行档门与审计治理。

## 2. 逐维对照

### 2.1 桌面工具面（ZCode 8.5 / Neurova 7.5）

**ZCode：14 个冻结底层工具**（`apps/zcode-cli/packages/zcode-cua-plugin/scripts/computer-use-client.mjs:30-45`）：
`list_apps`、`list_windows`、`get_app_state`、`left_click`（button×click_count 覆盖
双击/三击/右键/中键）、`left_click_drag`、`type`、`set_value`、`select_text`、`key`
（repeat/hold_seconds）、`perform_action`（仅执行 AX 树里声明过的动作）、`paste`
（原生剪贴板写入＋粘贴＋恢复）、`scroll`、`request_access`、`stop_computer_control`。
外加 Target 高层绑定 API（`elements()/click/drag/pressKey/scroll/selectText/setValue/
typeText/paste/performSecondaryAction`，SKILL.md:89-104）。设计取向是**刻意收缩**：
30→14 的裁剪有专文论证（`docs/cua/producer/cua-14-tool-e2e-validity.md:17-45`）——
删除了 mouse_move、mouse down/up、cursor_position、read_clipboard、wait、全屏截图、
zoom、显示器枚举/切换、open_application。所有工具 strict 拒绝未声明键
（`docs/computer-use.md:139-157`）。

**Neurova：11 个 `computer_*` 工具**（`neurova/builtin_tools.py:234-419`）：
`computer_screenshot`、`computer_click`、`computer_type`、`computer_scroll`、
`computer_dom_snapshot`（UIA 控件树）、`computer_click_element`、`computer_set_value`、
`computer_som_snapshot`（Set-of-Marks 编号图）、`computer_click_mark`、`computer_shell`
（本机命令）、`computer_ssh_exec`（远程命令）。参数归一单点
（`normalize_computer_params`，tool_executor.py:208-240）。

对比：ZCode 有而 Neurova 无——**应用/窗口枚举**（list_apps/list_windows）、
**组合键**（key）、**剪贴板**（paste）、**文本选择**（select_text）、**AX 声明动作**
（perform_action）、**拖拽**（left_click_drag）、**控制生命周期**（request_access/
stop_computer_control）。Neurova 有而 ZCode CUA 无——**shell/SSH 命令**、
**SOM 像素目标**（对自绘 UI/游戏/像素流）、**全虚拟屏截图**、**远程会话工具**
（ssh_exec）。两边都没有窗口移动/缩放/关闭类工具。

小评：ZCode 的工具面小而严，每个删减都有论证，语义深度（AX 声明动作、文本选择、
剪贴板恢复）更高；Neurova 胜在命令执行与像素空间兜底，但桌面交互动词偏少
（无 key/paste/drag/select_text），且 `__init__.py:9` docstring 声称的
「窗口管理」并无实现——工具面诚实度扣分。

### 2.2 观测回路（ZCode 9 / Neurova 8）

**ZCode**：观测核心是 `get_app_state`——单应用/单窗口栅格＋AX 元素表
（index/kind/title/value/actions）＋ `state_id`，支持 **diff 增量**（首树/截图后必为
整树；`tree_shown_to_model` 记账防「模型没看过的树」当基线，
computer-use-client.mjs:587-619），长树按优先级裁剪并标注 sparse，`elements()`
可取全表。**帧权威**是亮点：每张可动作栅格携带 `frame_id`
（`frameIdOf`，computer-use-client.mjs:204-218），模型坐标＝最近一次返回栅格的整数
像素，隐式绑定会话最近栅格、过期/替换 fail-closed（:342-360）；树里的 bounds 只是
诊断性全局坐标，禁止当动作坐标用（SKILL.md:190-201）。单帧内联上限 200KiB
（frame-contract.js:13）。还有**应用身份防伪造**：producer 在结果 `_meta` 附
app-associations，只有主线程 broker 的账本采信，Worker 自报一律丢弃
（cua-broker.ts:116-119,138-155）。

**Neurova**：本机截图走 PIL `ImageGrab.grab(all_screens=True)` 全虚拟屏
（computer_use/__init__.py:343-367），带进程级 DPI awareness；**坐标链**单点换算
`compute_screen_metadata`＋`screenshot_px_to_screen_point`（:69-101，多屏副屏原点
可为负）。桌面语义观测走 `DesktopUIAManager.snapshot()`——UIA 控件树
（index/role/name/rect/runtime_id/pattern 能力位，desktop_uia.py:83-125），
generation 按窗口缓存、动作成功即递增、过期拒绝 `stale_generation`（:275-298）。
无 UIA 树目标走 `som.py`：边缘幅值阈值＋连通域标注编号图（≤60 个，编号 md5 稳定，
:30-63），映射按会话隔离存储（tool_executor.py:6529-6545）。浏览器侧 aria 快照带
`[eN]` ref 标注＋预算裁剪/折叠诚实上报（browser_manager.py:885-934,1953,2132）。
截图 base64 **不直接进模型上下文**，经感知门（T-09）按 vision 能力三闸放行、
每轮至多一次、降采样防 413（loops/perception_gate.py:34-77）。

小评：ZCode 的帧权威＋diff 基线＋防伪造是**协议级**的严谨——模型永远只能对
「刚看过的那一帧」下坐标，陈旧帧点不了；Neurova 的坐标链/generation/ref 新鲜度
是**实现级**的严谨，缺一帧等同物：像素点击路径（computer_click/click_mark）没有
「必须对最近观测帧负责」的强约束，SOM 检测器还是启发式占位（som.py:6-7），
远程会话 `screen_metadata()` 恒返 None 使远程坐标链退化为恒等
（remote_backend.py:72-74）。

### 2.3 执行后端与平台覆盖（ZCode 6.5 / Neurova 8）

**ZCode**：producer 私有。消费侧可见的执行架构：macOS 独立签名 Helper app
（bundle `dev.zcode.cua-helper`，TCC 授权主体，验签＋同 UID 进程树校验，
zcode-cua-permission-broker.md:22-33）；Windows 由安装包内 Electron Node 运行时
fork＋`ax_native.node`，runtime-manifest 带 SHA-256 强校验
（windowsCuaDevRuntime.ts:78-228）。平台启用面 darwin＋win32
（node.ts:872），**Linux 不在范围**；无远程 Helper；浏览器域明确划给
Browser Use（computer-use-client.mjs:20-21）。Windows 侧 M8 缺 4 个 native peer
原语，现状 fail-closed（lazy spec:171-172）。

**Neurova**：全栈可跑。本机桌面 pyautogui/PIL（Windows DPI aware）；
桌面语义层 `DesktopUIAManager` **五级递降点击链**：UIA Invoke → Toggle →
ExpandCollapse → LegacyIAccessible.DoDefaultAction → PostMessage 直投（app_post，
不抢焦点不动真实光标）→ 全局 pyautogui（仅 `NEUROVA_ALLOW_GLOBAL_INPUT=1` 门控）
（desktop_uia.py:164-188,455-480）。浏览器三后端选路（Playwright > Camofox >
Scrapling，按 URL 正则路由，browser_manager.py:2410-2453）。远程平面：
Windows 沙箱 provider（.wsb 生成＋一次性拉起）、RDP 直连 provider（凭据分桶，
destroy no-op 绝不关用户真机）、Linux/macOS 走 paramiko SSH
（rdp_provider.py:21、sandbox_provider.py:44、ssh_runner.py:38）。

小评：ZCode 的执行架构（进程隔离＋签名校验＋清单强校验）是**产品级安全工程**，
但克隆件内不可验证、Windows 现状 fail-closed、无 Linux/远程；Neurova 的执行面
**真实、广、可测**，桌面语义仅在 Windows（Linux/macOS 本机无 GUI 操控，远程走
SSH），SOM 是启发式、沙箱真拉起未验收（sandbox_provider.py:8-9）。

### 2.4 权限与安全（ZCode 9.5 / Neurova 8）

**ZCode**（cua-permission-broker 全链）：
- 权限两轴：accessibility（granted/stale/denied）＋ screenRecording
  （cuaPermission.ts:5-27）；状态查询分两级——缺省只读绝不抓像素，功能探针
  仅在授权返回/Helper 重启后允许一次（zcode-cua-permission-broker.md:82-94）。
- **动态授权流**：模型 `request_access` → 观察归一化（zod 校验
  `zcode.cua/request-access-status-v1`）→ UI 去重串行化 → ConfirmDialog →
  按 Accessibility → Screen Recording 顺序引导系统设置 → 按需重启 Helper
  （CuaPermissionObservationAttachment.tsx:69-112,135-203）。macOS 还有
  **浮窗拖拽授权**（Helper app 拖入系统 TCC 列表，拖拽前验签比对）。
- **凭据卫生**：broker token 每次调用由账本签发、不进 Worker globals、
  `sanitizeZCodeRuntimeEnv` 从所有子进程 env 剥离
  （runtimeEnv.ts:69-76,109-111）；launch 前重验签防 TOCTOU。
- **审计**：凡到达 broker 的请求无论成败记 `facts.computerUse`，应用身份记
  `facts.cuaApps`（cua-broker.ts:98-119）；权威判定/收据/权限错误透传均有
  专文契约。
- 项目级权限规则 `zcode:permission-capability:official_cua`
  （app-approval.ts:64-76）；kill switch `stop_computer_control`。

**Neurova**：
- **四档运行模式** `full/sandbox/review/auto`（runtime_policy.py:115-161），
  持久化于 app_settings；裁决是纯函数 `decide_desktop`；风险三档成员
  **从工具声明投影**而非手写名单（test_desktop_policy_projection.py 背书）。
- **执行门**：`_desktop_runtime_gate`——REQUIRE_SANDBOX 无活动会话即拒；
  REQUIRE_APPROVAL 走 `ApprovalManager` 铸审批、批准后带 bypass 重放
  （tool_executor.py:2688-2755,1542-1548）；browser 侧 profile 授权门
  fail-closed（:2757-2788）。
- **能力诚实面**：`capability_state.py` 六轴（screenshot/input/uia/aria/camofox/
  vision）三态＋unknown 一等读数，TTL 缓存＋显式失效，camofox 探针真打 /health，
  消费于 `/v1/computer/status`、`/doctor`（:214-227、computer.py:683-749）。
- **审计**：所有 computer_*/browser_* 动作在分发咽喉单点写
  `DesktopAuditStore.record_computer_action`（tool_executor.py:2614-2633）。
- **ActionResult 封闭契约**：route×delivery×effect＋evidence 词表＋11 个拒绝码，
  构造器强制不变式（action_result.py:20-117）。
- REST 面强制登录，`/shell`、`/file/*` 再加 admin，路径穿越防护
  （computer.py:30-42,457,481,497）。

小评：两边都是**双层治理**（策略裁决＋执行门）。ZCode 多出的是**系统级信任链**：
TCC 主体、代码签名、进程树校验、token 一次性签发与 env 消毒、应用身份防伪造；
Neurova 多出的是**运营级诚实面**：四档模式、审批落盘、能力三态读数、/doctor
真探、ActionResult 证据链。方向不同，ZCode 在「防恶意与防伪」上更深，
Neurova 在「可观测与可运维」上更深。

### 2.5 会话与生命周期（ZCode 9 / Neurova 7）

**ZCode**：懒启动不变量（Host 启动/Agent spawn/session create 零 Helper IO，
合法触发仅三类，lazy spec:29-36）；稳定 socket/pipe 名，Helper 重启/换代不换发
凭据；darwin standalone Helper 300s 空闲自退；调用中死亡按 `possibly_sent` 收口
禁止自动重放；**Windows 宿主状态机**：lifecycle tail 线性化所有 start/stop/
restart、两阶段 ready、epoch 防旧 start 复活、shutdown→kill→termination blocker
（windowsCuaDevHelperHost.ts:48-130,304-509）；**跨会话输入互斥** `CONTROLLER_BUSY`
（另一 live 会话持输入时拒绝且不可重试，SKILL.md:252-254）；多会话 ghost-cursor
叠加规范。

**Neurova**：`DesktopSessionPool` claim/release/reap_idle（同用户优先复用，
容量上限 8，空闲 TTL 600s，session_pool.py:43-103）；provider 按名构造
（env > 设置 > 空＝无池），改设置即重建池免重启；无池时 sandbox/auto 档
fail-closed 拒绝变更动作；`use_remote_session` 保证异常必解绑＋归还
（remote_backend.py:91-115）。

小评：ZCode 的生命周期是**多租户守护进程**级别的工程（状态机、epoch、互斥、
叠加光标规范）；Neurova 的池是**单进程资源池**级别的工程——够用、有 fail-closed
底线，但没有跨会话输入互斥、没有「正在操控者」的租约概念。

### 2.6 与 Agent 循环的集成（ZCode 9.5 / Neurova 8）

**ZCode**：观察方法自动经结构化结果展示（模型无需手写回灌），动作静默成功；
单结果单栅格规则由宿主强制（二次 raster 整帧移除，SKILL.md:179-186）；
**媒体预算耗尽时 CUA 栅格被替换为文本指令**「本请求看不到栅格，禁止发坐标目标，
先重新观察」（official-cua-media.ts:4-28、media-budget.ts:225-238）——降级不撒谎；
**重试三值语义**：错误附 `actionSent`（是否可能已下发）与
`retry: reobserve|retry|never`，NEVER_RETRY_CODES 八个、REOBSERVE_CODES 强制先观察
（computer-use-client.mjs:113-131）；Helper 冷启动 `CUA_NOT_READY` 信封
250→1500ms 退避自动重试至多 6 次（:247-274）；**子代理双层拒绝**
（Worker assertAvailable＋主线程 broker 兜底，cua-bridge.ts:43-52、cua-broker.ts:106-107）；
参考文档不主动推送、按需 `agent.documentation.get` 拉取。

**Neurova**：分发链依次过 build 门→身份注入→参数归一→运行档门→审计→沙箱域
（tool_executor.py:2570-2648）；结果经 `_normalize_browser_result` 压成紧凑 dict
（摘掉截图大对象留 `has_image`）并附加 ActionResult（:6630-6669）；失败带精确
拒绝码（stale_generation、ref-not-found、歧义 409 候选列表）；截图/SOM 图经
感知门进本轮请求（vision 三闸＋每轮一次＋降采样，perception_gate.py:34-77）；
成功动作后 0.5s 自动补拍刷新截图广播前端（:6752+）。

小评：ZCode 的集成纪律更「防呆」——模型被协议约束着「先观察后行动、预算没了
不许盲点、非幂等动作不许盲重试」；Neurova 的集成更「透明」——紧凑结果、精确
拒绝码、409 候选、感知门都是好设计，但缺 actionSent/never-retry 这一层：
一次「PostMessage 已投出但结果未知」的失败，模型可能对同一坐标盲点第二次。

### 2.7 前端 UI（ZCode 9 / Neurova 8.5）

**ZCode**：`CuaToolCallBlock` 渲染器按动作投影摘要＋目标 App 图标＋截图＋错误＋
request_access 权限状态（ui/src/ToolCallBlocks/renderers/cua.tsx:332-504）；
macOS **Auto-PiP 实时画面**（producer 拥有面板策略，ZCode 只发布 focus/turn
生命周期事实，cua-pip-session-consumer-integration.md:3-40）；Windows 顶部
操作指示条（30s 兜底隐藏，windowsCuaOperationIndicator.ts:16-30）；权限 UI 三件套
（设置页两行开关＋浮窗拖拽面板＋live ConfirmDialog）；TUI 审批面板对 official_cua
专门展示（app-approval-panel.tsx:150）；sideband `computer-use/operation-event`
不进会话快照/重放（computer-use-operation-event.ts:43-88）。

**Neurova**：dock 分屏 `ComputerTab`＋`ComputerUsePanel.vue`（522 行）＋
`useComputerPanel` 模块级单例状态机（424 行）；**双通道驱动**——WS
`computer_action` 实时事件（主）＋ SSE tool_call/tool_result 兜底开屏；渲染实时
截图、操作日志（i18n 摘要 40+ 动作）、ActionResult 徽标（route/delivery/effect/
refusalCode/evidence/escalation，「无抢占」在 dock 上可证伪）、SSH 终端视口
（命令＋stdout/stderr＋exit）、点击位置标记（2s 淡出）、浏览器 URL；Agent 动手
时自动展开分屏（useComputerPanel.ts:289-363）。

小评：两边都是第一梯队。ZCode 多实时画面（PiP）与授权流 UI；Neurova 多
ActionResult 证据徽标、终端视口与点击标记，且事件契约（含 escalation 跳级去向）
在 UI 上更透明。

### 2.8 可靠性工程与测试（ZCode 8 / Neurova 8.5）

**ZCode**：消费侧测试扎实——桥可信转发/伪造 context 拒绝/subagent 双层拒绝/
kernel 重置失效/token 伪造拒绝（cua-bridge.test.ts）、帧契约产物表面
（frame-contract-artifact.test.ts）、伪造帧防护（image-normalization-forged-frame.test.ts）、
展示投影元数据（tool-result-display.test.ts:292-343）、占位 producer 判定
（placeholderProducerDetection.test.ts）。20 个错误码构成封闭错误契约。
但 producer 测试与真机 e2e 不在克隆件（`docs/cua/evidence/` 只留契约与验收目录）。

**Neurova**：`tests/unit/computer_use/` **52 个测试文件**——坐标链、滚动语义、
SOM 会话隔离、UIA、运行档投影、ref 寻址、快照预算/折叠/诚实度、SSH 凭据、
远程平面、camofox 隔离/ref 加固、契约单源（route 词表/工具面对账/无幻影参数）、
能力三态；integration 5 件；agent 侧事件与感知门测试；**e2e/cua_sim 行为级仿真**
——假桌面 HTML＋生产 PlaywrightBackend 走「观察后行动」协议，3 个任务断言
reward==1.0（harness.py＋test_cua_sim_tasks.py）。

小评：Neurova 测试面更宽（含行为级仿真与契约单源守卫）；ZCode 错误契约更完整
（20 码封闭清单 vs Neurova 11 拒绝码＋自由文本 error）。两边都有「契约即测试」
的自觉。

## 3. 评分表

| 维度 | ZCode | Neurova | 说明 |
|---|---|---|---|
| 2.1 桌面工具面 | 8.5 | 7.5 | ZCode 语义动词更深；Neurova 有 shell/SSH/SOM 但缺 key/paste/drag/枚举 |
| 2.2 观测回路 | 9 | 8 | ZCode 帧权威＋diff＋防伪造；Neurova 坐标链/generation/ref 强但像素面无帧约束 |
| 2.3 执行后端与平台 | 6.5 | 8 | ZCode 架构严但克隆内不可验证、无 Linux/远程；Neurova 真实广谱可测 |
| 2.4 权限与安全 | 9.5 | 8 | ZCode 系统信任链；Neurova 运营诚实面＋审批链 |
| 2.5 会话与生命周期 | 9 | 7 | ZCode 守护进程级；Neurova 单进程池级 |
| 2.6 循环集成 | 9.5 | 8 | ZCode 防呆协议（帧权威/预算降级/重试三值）；Neurova 透明但缺 actionSent |
| 2.7 前端 UI | 9 | 8.5 | 两边第一梯队；ZCode 有 PiP 实时画面，Neurova 有证据徽标＋终端视口 |
| 2.8 可靠性与测试 | 8 | 8.5 | Neurova 52 单测文件＋行为级 e2e；ZCode 消费侧扎实但 producer 不在仓 |
| **合计（/80）** | **69** | **63.5** | 折合 8.6 vs 7.9 |

## 4. Neurova 已领先、无需照搬

- **浏览器与桌面同族**：`browser_*` 31 工具与 `computer_*` 同包治理、同一 ActionResult
  契约、同一审计咽喉；ZCode 刻意把浏览器划出 CUA 另立 plugin。
- **远程操控平面**：沙箱/RDP/来宾代理/SSH 四路，ZCode 完全没有。
- **能力诚实面**：六轴三态＋`/doctor` 真探＋`not-configured/configured-unreachable`
  具名原因；ZCode 的能力面藏在私有 producer 里。
- ** ActionResult 证据链前端化**：route/delivery/effect/evidence/escalation 直接
  上 dock，用户可证伪「有没有碰真实输入设备」。
- **行为级 e2e 仿真**（cua_sim）：假桌面＋生产后端跑 reward 断言，ZCode 真机 e2e
  不在开源仓。

## 5. 可补充候选（按优先级，待点单）

**P1（直接补最大差距）**

1. **桌面帧权威/防陈旧点击**：`computer_screenshot`/`computer_som_snapshot` 返回
   轮次内 `frame_id`；`computer_click`/`computer_click_mark` 校验坐标所属帧＝
   最近观测帧，过期返回结构化 `stale_frame` 强制重观察；感知预算紧张时降级为
   「禁止坐标动作、先重新观察」（对齐 ZCode official-cua-media 的降级指令）。
   影响面：tool_executor 桌面分支、desktop_uia generation 机制推广到像素面、
   ActionResult 拒绝码表＋1。
2. **动作错误三元组 `actionSent`/`retry`**：ActionResult 增加
   `action_sent: bool` 与 `retry: reobserve|retry|never`；PostMessage/全局输入
   已下发但结果未知的场景如实标注，NEVER_RETRY 集合封死非幂等动作的盲重放。
   影响面：action_result.py、desktop_uia.py、browser_manager 错误路径。
3. **route 词表漏登修复**：PlaywrightBackend ref 路径自报 `route="playwright_ref"`
   （browser_manager.py:1003,1034）不在 `ROUTES` 词表（action_result.py:29-30），
   `derive_from_browser_result` 对其返回 None——ref 点击/输入目前不携带
   ActionResult 契约。一词入表＋对账测试，先红后绿。

**P2（对齐 ZCode 的治理深度）**

4. **子代理电脑操控策略**：对齐 ZCode「CUA 仅主代理」——swarm 工具面收窄时对
   子代理默认剔除 foreground 桌面动作（或仅留只读观察类），防多代理抢真实
   输入设备。影响面：swarm.computeSubagentToolAllowlist、permissions 归类。
5. **跨会话前台输入互斥**：foreground 档动作持全局锁，第二会话请求返回
   `controller_busy`（等价 CONTROLLER_BUSY，不可重试）。
6. **应用/窗口枚举工具＋文档诚实化**：UIA 已能枚举（desktop_uia snapshot 按
   window_title 过滤），补 `computer_list_windows`（可含 list_apps）工具面；
   同步修 `__init__.py:9` 的「窗口管理」虚假 docstring（要么实现要么删声明）。
7. **桌面 key/paste 动作**：`computer_key`（组合键＋repeat）与剪贴板粘贴
   （写入＋粘贴，win32 API），对齐 ZCode 的 key/paste；drag 视需求登记。

**P3（收尾与兜底）**

8. **等待语义钉死**：现有成功动作后 0.5s 自动补拍已承担「观察内 settle」；
   二选一收口——补显式 `computer_wait` 工具，或把「动作后必补拍」写成契约
   测试钉死（ZCode 选择删除 wait，两边都有道理，但要成文）。
9. **远程会话 screen_metadata 补齐**：RDP/沙箱会话回传 DPI/scale，消除远程
   坐标链恒等退化（remote_backend.py:72-74）。
10. **SOM 检测器升级点固化**：detector 抽成接口＋能力面标注 heuristic 档
    （capability_state 六轴可加 som 子轴），为将来 ONNX/OCR 替换留单点。

## 6. 局限

- ZCode producer 私有，本报告对其执行质量的一切判断止于消费侧代码与随仓契约
  文档；不排除私有实现与文档存在出入。
- 浏览器域未展开计分（另有 agent-browser 对照在案）；若把 ZCode browser-use-plugin
  纳入，其工具面需单独盘点。
- 评分是静态代码评测，不含实机成功率/延迟等运行时指标；Neurova 侧的 cua_sim
  reward 与 ZCode 侧的真机 e2e 不在同一尺度，未做跨仓换算。

## 7. 实施记录（2026-11-17，§5 候选全部落地）

用户拍板「全部修复」后，十项候选当日全部实施（先红后绿，单任务单提交）：

| 候选 | 提交 | 要点 |
|---|---|---|
| P1-3 route 词表 | `3e5abeefa` | `playwright_ref` 入 ROUTES＋设计稿 §0.3 同步登记，ref 动作恢复 ActionResult 契约 |
| P1-2 actionSent/retry | `5e88e5dd6`（断言对齐 `955ff30ae`） | 契约新增两字段＋每拒绝码重试建议单源＋NEVER_RETRY 集；三类门控拒绝统一携带契约 |
| P1-1 帧权威 | `f5cb4fe6a` | `frame_registry.py` 单源：观测发帧/变更失效/陈旧帧拒点（stale_frame，retry=reobserve）；frame_id 省略=既有行为零回归 |
| P2-6 窗口枚举 | `c412919f8` | `computer_list_windows`（UIA 同源枚举）＋包 docstring「窗口管理-模拟实现」失实声明清除；远程/guest 同契约 |
| P2-7 三动词 | `76414d258`（剪贴板根修 `a41c9a507`） | `computer_key/paste/drag`：KEY_ALIASES 单源+键表校验；win32 剪贴板（活体抓出 64 位句柄截断真缺陷并根修）；坐标链换算拖拽 |
| P2-4 子代理策略 | `b42f32919` | `FOREGROUND_DESKTOP_TOOLS` 单源，swarm general 面整族剔除（对齐 ZCode「CUA 仅主代理」）；观察/命令面保留 |
| P2-5 前台互斥 | `9f0dca718` | 进程级前台输入租约：跨会话 controller_busy（retry=never），同会话重入放行，finally 必释放 |
| P3-8 等待语义 | `67e4defde` | 「动作后必补拍」钉成契约：前台输入族必须声明补拍、观察/命令面不得补拍 |
| P3-9 远程元数据 | `3e5e48d63` | guest agent `screen_metadata` 动作＋宿主侧代理缓存，消除远程坐标链恒等退化 |
| P3-10 SOM 接口化 | `ad5fb4f4c` | `SomDetector` 协议＋`get_som_detector()` 选型单点（env）＋capability_state 第 7 轴 som（如实标注启发式档） |

**验证证据**：computer_use 全量 778 passed（唯一失败 `test_reprobeRebuildsBackend`
经基线 worktree A/B 实证为预存环境失败——本机缺 Chromium 内核，零新增）；关联面
（蜂群收窄/guest agent/api computer/security）1263 passed；前端全量 vitest
2546 passed＋vue-tsc 0 错。活体（真后端 9577 实例）：`/api/v1/computer/status`
七轴含 som（诚实标注启发式档）、`/doctor` 全项真探、截图 200；帧权威全链
（发帧→新鲜→变更失效→stale_frame）、剪贴板写读回逐字一致（并当场抓出 64 位
句柄截断缺陷，见 `a41c9a507`）、UIA 缺失时 list_windows 诚实拒绝
（unsupported_method）。附带：同名函数盘点台账按守卫重生成（`e275a4f33`）。

## 8. 增强项实施（2026-11-17，评测三项可选增强全部落地）

用户追加拍板「实施增强项」，三项当日完成：

| 增强 | 提交 | 要点 |
|---|---|---|
| ① 重试建议上徽标 | `609a5a6f9` | `actionBadgeText` 追加 retry 提示（↻reobserve/↻retry/⛔never），`extractActionResult` 同步抽取 |
| ② 拒绝可见性 | `2228572bb`（后端）＋`609a5a6f9`（前端） | controller_busy/运行档/审核待批三类门控拒绝在分发咽喉统一广播 computer_action——分屏面板看得见"为什么没动" |
| ③ 窗口清单表格 | `2228572bb`（载荷）＋`609a5a6f9`（表格） | `windows` 进事件载荷（按需出现），ComputerUsePanel 渲染窗口表格（标题/类名/PID/前台高亮），i18n 五键×11 |

**验证**：新增后端测试 5 例（拒绝广播 3＋载荷 2）与前端测试 6 例（徽标 4＋状态 2）
均先红后绿（前端红灯以「换回 HEAD 版 composable 实跑 4 failed」取证）；全量
vitest 2555 passed＋vue-tsc 0 错。附带清偿：并行批次 e47943b24 新增的三处裸
rgba 触发色守卫，机械改令牌（`065f72f6a`）。

**过程记录（并行会话撞车处置）**：取红灯证据时 `git stash push` 与并行会话
的 stash 操作撞车（stash@{0} 成为对方 neurova WIP，我的前端改动未受影响仍留在
工作树）——改用「checkout HEAD 版单文件→实跑红灯→恢复实现→绿灯」的换文件法
取证，未触碰他人 stash。
