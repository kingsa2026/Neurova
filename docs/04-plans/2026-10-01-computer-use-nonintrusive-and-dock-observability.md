# 无抢占 Computer-Use 与右侧 Dock 可观测性设计

> 2026-10-01 · 计算机使用（CUA）升级设计稿 · 状态：**已评审（2026-10-02 四条拍板落账，见 §0）**
> 范围：**Windows / Linux / macOS × GUI 动作 / CLI 命令全兼容**；CLI 命令是天然无抢占通道，
> 但必须以"终端态"形态接入 dock 可观测（见 §4.3）。
> 目标读者：CUA/会话链路实施者；关联：`docs/04-plans/2026-09-30-computer-use-repair-tickets.md`、
> 拆片后的执行源 `docs/04-plans/2026-10-02-computer-use-nonintrusive-tickets.md`、
> 远程桌面会话池方案（RS-1~5，见 memory `neurova-remote-desktop-session-plane`）。
> §2 与 §7 的第三方条目**仅作调研背景，不作事实源**（`AGENTS.md` 协作红线·原创性条款）；
> 本稿所有落点以仓库现值为唯一依据。

## 0. 评审结论与事实源校准（2026-10-02）

开稿标"待评审"且全仓零引用，拆片前对全部承重假设做了取证。**结论：原稿的通道词表、
终端态载体、回执通道三处与本仓单源事实冲突，照抄会同时撞 `AGENTS.md` 修复教义第 6 条
（单一事实源）与第 2 条（禁止伪装成功）**。四条拍板与实测落点如下。

### 0.1 四条拍板

| 决策 | 拍板 | 对原稿的改动 |
|------|------|-------------|
| 通道字段口径 | **收口进既有 `route`（`ROUTES` 封闭词表）与 `delivery`** | §4.2 删 `channel`/`plane` 两个新键，改为扩值不扩键 |
| 终端态载体 | **复用 `shell_sessions.py`，新增 WS 推送口** | §4.3 删 PTY/ConPTY 从零新造，改为消费既有常驻会话 |
| 让位回执通道 | **接活 `AGENT_COMMAND` 建双向 WS 命令通道** | §3/§4.3 "走既有 WS 命令总线"改为"新建" |
| 交付范围 | **W1–W4 全链，跨平台按代码交付** | §6 每批加"验证边界"列，诚实区分本机活体与单测覆盖 |

### 0.2 实测校准表（拆片依据，实施者不必重取）

| 原稿假设 | 仓库实测落点 | 处置 |
|---------|-------------|------|
| §4.2 新增 `channel` 列，值域 `uia\|post_message\|vm_plane\|send_input\|browser_cdp\|atspi\|xdotool\|ax\|shell` | `neurova/computer_use/action_result.py:20-31` `ROUTES` 封闭词表，键名是 **`route`**，`build()` 越界即抛 `ActionResultError`；`channel` 在 `neurova/computer_use/` 零命中 | 按 §0.3 映射表收口，**净新增只 2 个值** |
| §4.2 新增 `plane`（`agent\|user`） | 同文件 `:32` `DELIVERIES = {background, foreground, not_applicable}` 已在表达"是否触用户桌面" | 扩 `DELIVERIES` 一个值 `isolated_plane`，不新造键 |
| §4.3 后端以 PTY 执行（POSIX `pty` / Windows ConPTY），逐行经 WS 按 `streamId` 推送 | 全仓 PTY **零实现**；`neurova/execution_engine/shell_sessions.py:13` 把"非 PTY"写成显式跨平台设计选择，同文件已有 `start_session`/`poll_session`/`session_id`/`exit_code`/`truncated`/进程组杀灭与取消令牌注册全套 | 复用之，流身份用 `session_id`（`streamId` 语义并入）；**非 PTY 后果按 §4.3 显式声明** |
| §4.2 shell 通道新增顶层 `command`/`streamId`/`exitCode` 三键 | `NeurUI/src/composables/useComputerPanel.ts:170,197` 已消费 `payload.terminal.{command,stdout,stderr,host,exit}` | 收口进 `terminal` 结构内扩列，**顶层零新键** |
| §4.1 "骨架保留不动，只扩展事件契约与渲染形态" | 同文件 `:206` `latestScreenshot` 是**单值覆写**，`actions` 上限 50 且为扁平倒序列表（`ComputerUsePanel.vue:183`）；帧对态需 per-action 前/后双帧 | 帧对态**必须改状态结构**，"骨架不动"不成立；`:174-183` 既有 `refreshed` 补帧机制可直接承载"动作后帧" |
| §3/§4.3 回执"走既有 WS 命令总线" | `neurova/sync/session_sync_manager.py:48` `AGENT_COMMAND` 全仓**仅此一行定义**，零生产者零消费者；WS 入站实处理 4 类（`api/endpoints/session_sync.py:206/215/228` + `sync_request`）；出站回帧范式是 `{"type":"*_ack"}` | 死枚举接活为**新建**双向口，不再称"既有总线" |
| §3 桌面侧"沿用 T-08 一等寻址的失败点名口径" | T-08 `RefTarget`（`browser_manager.py:382-393`）**只在浏览器侧**；桌面侧寻址是 `index`/`runtime_id`（`desktop_uia.py:301-326`），无 ref | 失败点名口径可复用，**桌面 ref 另立工单**（§6 T-07） |
| §3 `channel=send_input` 直注通道"已有" | `desktop_uia.py:470-480/503-510` `global_click`/`global_type` 实为 **pyautogui**；全仓 `SendInput` 除 `:9` 那句 docstring 外零命中——**docstring 与实现不符** | 通道名从 `send_input` 收口为 `global_input`；docstring 的失实自述列入 T-01 一并根修 |
| §4.1 面板锚点写作 `RightDock.vue → ComputerTab.vue → ComputerUsePanel.vue`（未标目录） | 实际在 `NeurUI/src/components/chat/dock/RightDock.vue`、`dock/panels/ComputerTab.vue`、`chat/ComputerUsePanel.vue`；仓内 `web/` 是官网源码，**不是主前端** | 路径已在下表补全；`ComputerTab.vue:41-48` 现靠 `:deep` 压制旧固定宽，样式语言未统一（W1 内收） |

### 0.3 通道 → `route` 值收口映射

`ROUTES` 现值已覆盖大半，**净新增只 `shell` 与 `atspi` 两个值**：

| 原稿通道名 | 收口到 `route` | 状态 |
|-----------|---------------|------|
| `uia` | `uia` | 现值 |
| `post_message` | `app_post` | 现值 |
| `send_input` | `global_input` | 现值（注释已点名"会移动真实光标、抢前台"） |
| `vm_plane` | `remote` | 现值（注释"远程会话平面（RS 批次预留）"正是此批） |
| `browser_cdp` | `playwright_role` / `camofox_ref` / `dom` | 现值，三值比单一别名更精确，**不新造别名** |
| `ax`（macOS） | `accessibility` | 现值（注释即"AX/UIA 语义动作"） |
| `atspi`（Linux） | **`atspi`** | 新增——`uia` 既已单列，Linux 侧对称单列 |
| `xdotool`（X11） | **`xdotool`** | 新增 |
| `shell`（CLI） | **`shell`** | 新增 |

`shell` 动作不涉输入设备，`delivery` 取 `not_applicable`；隔离平面取新增的 `isolated_plane`。

## 1. 问题定义

两条硬需求同时成立：

1. **无抢占（Non-intrusive）**：agent 操作计算机时不得抢用户的鼠标键盘——
   用户正在用的光标、焦点、剪贴板不被 agent 的 SendInput 级注入夺走。
2. **可观测（Observable）**：agent 的每一步操作必须能被用户在
   **会话页右侧 dock 的 computer tab**（`RightDock.vue` → `ComputerTab.vue` →
   `ComputerUsePanel.vue`）里实时看到——agent 在哪、刚做了什么、画面长什么样。

两条需求的张力在于：**越不抢占，画面越难看**。隔离平面里 agent 操作的是虚拟屏，
用户桌面纹丝不动，但画面源变成了虚拟平面；同机后台动作（UIA/消息级）根本
没有"整屏动效"可看。所以可观测性必须按动作通道分别设计，而不是假设永远有
一张会动的全屏截图。

## 2. 业界路线谱系（调研结论）

| 路线 | 抢占程度 | 可观测素材 | 代表 |
|------|---------|-----------|------|
| 独立虚拟平面（VM/容器/Xvfb） | 零抢占 | 整屏画面流天然可得 | [anthropic computer-use-demo](https://github.com/anthropics/anthropic-quickstarts/blob/main/computer-use-demo/README.md)（Docker+Xvfb+x11vnc）、[trycua/cua](https://github.com/trycua/cua)、[OSWorld](https://github.com/xlang-ai/OSWorld) |
| API 级动作（UIA Invoke / Android Accessibility performAction / 浏览器 CDP） | 不动光标不抢焦点 | 无全屏动效，靠"元素+前后帧" | [AutoIt UIA 实践](https://www.autoitscript.com/forum/topic/207701-help-sending-clicks-to-window-_winapi_postmessage/)、[Android 官方文档](https://developer.android.com/guide/topics/ui/accessibility/service)、pywinauto [issue #1153](https://github.com/pywinauto/pywinauto/issues/1153) |
| 消息级后台（PostMessage WM_LBUTTON* / AHK ControlClick） | 不抢焦点，但命中测试不可靠 | 同上，且成功率更低 | [PostMessage 后台点击](https://stackoverflow.com/questions/28431173/postmessage-mouse-click-to-background-window) |
| 共屏共存 + 仲裁 | 与用户共享输入设备 | 天然可见，但互相干扰 | [CHI 2025 意外后果刻画](https://arxiv.org/html/2505.09875v2)、[RecAgent 不确定性让位](https://arxiv.org/abs/2508.04025) |

**结论**：默认走前两条路线的组合，第四条只作为兜底仲裁存在（用户一动 agent 即挂起），
第三条只作 UIA 之后的降级 fallback。这与 RS 会话池方案（显示/控制面分离）同构。

## 3. 动作路由降级链（后端，跨平台）

动作经 `target_resolver` 解析后，按目标类型与平台路由，**逐级降级，通道随 ActionResult 的
`route` 上报**（值域见 §0.3，`build()` 越界即抛，故不可能出现自由文本通道名）：

```
CLI 命令目标 ──► shell 通道（天然无抢占，不走输入设备；在哪跑由 runtime_policy 裁决）  route=shell
浏览器类目标 ──► CDP 独立 profile 实例（browser_manager，已有，三平台通用）           route=playwright_role|camofox_ref|dom
桌面类目标(Win) ─► ① desktop_uia Invoke/DoDefaultAction（不抢焦点）                  route=uia
                 ├─ ② PostMessage WM_LBUTTON* 后台消息（控件不支持 Invoke）           route=app_post
                 ├─ ③ 会话池虚拟平面执行（rdp_provider/remote_backend）               route=remote
                 └─ ④ 全局输入直注用户桌面（pyautogui；仅用户显式"附身"授权）          route=global_input
桌面类目标(Linux) ─► ① AT-SPI2 doAction（UIA 的 Linux 等价物，不移动光标不抢焦点）    route=atspi
                   ├─ ② xdotool --window 定窗投递（仅 X11；Wayland 拒绝全局注入）     route=xdotool
                   └─ ③ 会话池虚拟平面（Xvfb / headless 合成器），见 §5               route=remote
桌面类目标(macOS) ─► ① AXUIElement PerformAction（Accessibility API 等价通道）       route=accessibility
                   └─ ② 会话池虚拟平面                                               route=remote
```

- 每级尝试失败的原因写进 ActionResult（沿用 T-08 一等寻址的失败点名口径），不静默跳级。
  既有实现已是这个形状：`desktop_uia.py:165-189` 五级链在不可投时返回
  `refused("uia", "background_unavailable", escalation={...})` 而非静默降级——
  **本条是"扩到 Linux/macOS"，不是"从零建立"**。
- ⚠ **本仓第一级（UIA Invoke/Value）在 2026-10-02 之前实测不可达**，且是以"控件不支持"的
  形态伪装的：pattern 探测调的是该库并不存在的 `IsXxxPatternAvailable` 一族
  （`getattr` 恒 `None` → 五轴恒 `False`），于是点击全部落到第五级 `app_post`、
  `set_value` 恒 `refused:background_unavailable`——而"语义输入不可达"的唯一出路是开
  `NEUROVA_ALLOW_GLOBAL_INPUT`，即**抢用户焦点**，与本稿主题正面冲突。
  根修与活体前后读数见工单集 **T-01b**。是 T-01 把 `delivery/evidence` 抽到面板这件事
  把它照出来的：投递事实不可见，就会长期以这种形态存在。
  **推论适用于 W3**：新增通道必须同批带上"真控件形状"的探测判据，只注入 flag 值的
  假后端测不到这一跳。
- **Wayland 特例**：Wayland 协议从设计上禁止客户端注入全局输入与读取他窗画面，
  所以 Linux + Wayland 下 ② 直接判 `unsupported_method`（`REFUSAL_CODES` 现值，
  诚实降级不伪装），GUI 动作只走 AT-SPI 或虚拟平面——与 `_refuseUnimplemented`
  （`api/endpoints/computer.py:478`）与 `capability_state.py:64` 三态口径一致。
- `route=global_input` 前置闸门：现状是**环境变量**放行
  （`desktop_uia.py:26-34`，`NEUROVA_ALLOW_GLOBAL_INPUT`），本设计把它升级为
  **用户在 dock 面板显式点击"接管执行"后放行**，并把该闸从 env 收口到审批面
  （`runtime_policy` 的 REVIEW 档已有 `require_approval` 语义可复用）。
  ⚠ 同批必须根修 `desktop_uia.py:9` 的 docstring——它自称"全局 SendInput"，
  实现实为 pyautogui（全仓无 `SendInput` 调用），属教义第 2 条禁止的失实自述。
- **CLI 命令通道（`route=shell`）**：本机执行受 `runtime_policy.py` 既有四档闸
  （full/sandbox/review/auto）裁决落点——full 走本地 runner，sandbox 走
  `sandbox_provider`/会话池，远程 Linux 走 `ssh_runner`（已有，paramiko 惰性加载）。
  工具面 `computer_shell`（`builtin_tools.py:349-361`）与 `computer_ssh_exec` 已在，
  且其 `arbitrary_command` 声明位已自动投影进 `desktopHighRiskTools()`
  ——**新增通道不需要改 `runtime_policy` 名单**（该模块 `:42-58` 已废弃手写名单）。
  shell 动作**不经过任何输入设备**，天然满足无抢占；可观测方案见 §4.3 终端态。
- 输入仲裁器（新增，`neurova/computer_use/input_arbiter.py`，三平台统一语义）：
  **当前该模块不存在**，唯一守卫是上面的 env 闸与五级链次序本身，即"谁能碰真实输入"
  目前无集中闸——这正是 W2 要补的缺口。三平台读数源：
  - Windows：Raw Input / WH_MOUSE_LL+WH_KEYBOARD_LL 低级钩子；
    Linux：evdev 只读监听 `/dev/input/event*`（pyevdev，需 input 组权限，失败则降级为
    仅 `global_input` 通道暂停前提示）；macOS：CGEventTap（需辅助功能授权，未授权则同上降级）；
  - **用户一动 → agent 暂停**：注入级通道（`global_input`）执行期间收到真实输入事件，
    立即挂起动作流并向 WS 广播 `paused=true`，恢复需用户在 dock 面板确认
    （回执通道见 §4.3 第 4 项，**为新建**）；
  - RecAgent 式"不确定即让位"（arXiv 2508.04025，背景参考）落在决策层：置信度低于阈值时
    不执行动作，而是把候选动作作为待确认卡片推给 dock。
  - `target_resolver` 现有形态已是"不唯一即报歧义、绝不代模型挑"
    （`target_resolver.py:78-96` 返回 `ambiguous` 三态），低置信度让位在语义上与之同构，
    W5 接入时不得新造第二套歧义口径。

## 4. 可观测性设计（前端 dock）

### 4.1 现状锚点（2026-10-02 实测校正）

- 主通道：WS `computer_action` 事件（`NeurUI/src/composables/useComputerPanel.ts` 处理），
  构造与广播口在 `neurova/tool_executor.py:4942-5021` `_emit_computer_event`；
- 兜底：SSE `tool_call`/`tool_result` 中 `computer_*`/`browser_*` 工具名自动开屏
  （名单单源 `tool_executor.py:60` `COMPUTER_USE_TOOLS`）；
- 开屏：`openComputerDockTab()`（`useComputerPanel.ts:242`）统一走 `stores/rightDock`，
  `state.open` 仅是兼容位；
- 画面：动作 payload 内 base64 截图 → `state.latestScreenshot`（**单值覆写**，`:206`），
  日志数组上限 50 条（`maxActions`，`:203`），dock tab 自动打开；
- **既有可复用的三个机制**（原稿未识别，直接决定本批改动量比设想小）：
  ① `payload.refreshed` 补帧（`:174-183`）——不新开日志行，把画面补到最近一条同工具动作上，
  天然承载"动作后帧"；② `payload.terminal.{command,stdout,stderr,host,exit}` 前端已在消费
  （`:170,197`），shell 可观测不必新造顶层键；③ `payload.action_result` 已整体透传，
  而 `extractActionResult`（`:134-145`）**只抽 `route`/`effect`/`refusal_code` 三键，
  把 `delivery`/`evidence`/`escalation` 丢弃了**——显示投递模式只需扩这个函数，零契约变更；
- 广播口前置守卫顺序不可动（`:4956-4972`）：感知槽记账必须在 WS 早退**之前**，
  这是 T-09 已定的生产者接缝；
- 面板骨架按原稿保留，但**状态结构必须改**（帧对态需 per-action 前/后双帧，
  `latestScreenshot` 单值装不下）——原稿"骨架保留不动"仅对组件树成立，对 state 不成立；
  `ComputerTab.vue:41-48` 现以 `:deep` 压制 `ComputerUsePanel` 旧固定宽，样式语言未统一，
  本批一并收口到 `MessageSteps` 形状。

### 4.2 事件契约扩展（向后兼容，旧字段不动，**不新造通道词表**）

`computer_action` payload 增列如下。`route`/`delivery` **不加顶层键**——它们已在
`payload.action_result` 内透传，本批只扩前端抽取面：

```jsonc
{
  "tool": "computer_smart_click",     // 已有；CLI 动作为 computer_shell / computer_ssh_exec
  "screenshot": "<base64>",           // 已有：动作后帧
  "action_result": {                  // 已有透传，本批只扩前端抽取的键集
    "route": "uia",                   //   值域见 §0.3（ROUTES 净新增 shell|atspi|xdotool）
    "delivery": "background",         //   新增被消费：background|foreground|isolated_plane
    "evidence": ["delivery_ack"],     //   新增被消费：据此渲染"已验证/未验证"档位
    "refusal_code": "…",              //   已有
    "escalation": {}                  //   新增被消费：点名"为何跳到下一级"
  },
  "beforeScreenshot": "<base64>",     // 新增：动作前帧（后台通道没有连续流时的最小可观测素材）
  "target": { "ref": "…或 index/runtime_id", "name": "确定 按钮", "app": "chrome.exe" },
  "paused": false,                    // 新增：true 时前端渲染"已让位"横幅
  "terminal": {                       // 已有结构内扩列（顶层零新键）
    "command": "pip install -r …",    //   已有：命令原文（脱敏后）
    "stdout": "…", "stderr": "…",     //   已有（聚合形态，一次性终帧）
    "host": "…",                      //   已有（远程目标主机）
    "exit": 0,                        //   已有：退出码（ssh_runner 侧键名为 returncode，
                                      //   广播时归一到前端既有的 exit，不留第二份拼写）
    "sessionId": 12,                  // 新增：承载原稿 streamId 语义，取自 shell_sessions
    "delta": "…",                     // 新增：流式增量行（有 delta 时不重复发 stdout）
    "final": false,                   // 新增：true 表示会话结束，随 exit/elapsedMs 同帧下发
    "elapsedMs": 1200                 // 新增：耗时徽标
  }
}
```

- `DELIVERIES` 新增一个值 `isolated_plane`（`action_result.py:32`），与 `background`/`foreground`
  互斥；`refused` 仍不得声明 delivery——`build()` 既有不变式已钉，扩值不破守卫。
- `shell` 动作不涉输入设备，`delivery` 取 `not_applicable`。
- **不引入**原稿的 `channel`/`plane`/顶层 `command`/`streamId`/`exitCode` 五键——
  它们分别与 `route`/`delivery`/`terminal.command`/`terminal.sessionId`/`terminal.exit` 同义，
  并存即教义第 6 条的第二份定义。

### 4.3 四级预览形态（按 `action_result.route` 自动切换）

dock computer tab 内按最近动作的 `route` 渲染形态，`useComputerPanel` 扩展一个
`previewMode` 计算属性：

1. **流态（`remote` / 浏览器三值）**：隔离平面有整屏画面流——
   P0 直接沿用"每动作一帧"节流刷新；P1 后端起 MJPEG/WS 帧流端点
   （虚拟屏端帧抽取），面板换成流式 canvas，观感接近看直播。
2. **帧对态（`uia` / `app_post` / `atspi` / `xdotool` / `accessibility`）**：用户桌面后台动作
   没有连续流，面板渲染 **before → after 帧对 + 动作卡**：目标元素名、命中控件、
   投递模式徽标（`delivery`）、验证档位徽标（`evidence` 有无）；连续动作按时间轴纵向排列
   （复用 `MessageSteps.vue` 的步骤化样式语言），帧对点击可放大。
   这是本设计的核心补丁——**"不抢屏"的代价用"帧对+时间轴"偿还**。
   ⚠ `post_click` 现状投的是元素 rect 中心换算到 hwnd 客户区，且 down/up 之间
   `time.sleep(0.02)` 硬编码（`desktop_uia.py:443-468`），无 move/hover、无拖拽、
   无时延参数——帧对态可观测，但**动作保真度不等于用户操作**，
   此项登记为 T-06 待办而非静默隐藏。
3. **终端态（`shell`）**：CLI 命令没有画面，可观测素材是**会话输出流**。
   **载体拍板：复用 `neurova/execution_engine/shell_sessions.py`，不从零新造 PTY 体系**——
   它已有常驻进程、`session_id`、`exit_code`、head+tail 双端缓冲、token 预算截断、
   进程组杀灭与取消令牌注册全套（`:86-167`）。本批要补的是**推送口**：现状是模型调
   `poll_session` 才拿到输出（拉模型，`:291-308`），改为读线程把增量经 WS 按
   `terminal.sessionId` 推给面板（推模型），终帧带 `final`/`exit`/`elapsedMs`。
   面板渲染终端卡：命令原文、流式输出区、退出码与耗时徽标；同会话多条命令纵向时间轴排列，
   每条可展开/折叠、可复制输出。`ssh_runner` 远程执行同走此形态（`terminal.host` 标注主机）。
   ⚠ **诚实边界**：沿用非 PTY 实现意味着**没有真伪终端**——TUI 程序（vim/top 等）
   与依赖 tty 的行缓冲行为不保真；ANSI 着色可后置，但不等于终端保真。
   该限制必须写进终端卡提示与工具 description，**不得以"终端态"名义暗示 PTY 等价**。
   可选 P2：输出留档供面板内回放（自有事件格式，不复用第三方存档格式）。
4. **暂停/让位态**：仲裁器让位或低置信度待确认时，tab 标题加呼吸点，
   面板顶部横幅显示"已让位给用户 / 待你确认下一步"，卡片带"继续/取消"按钮。
   **回执通道为新建**（原稿所称"既有 WS 命令总线"不存在，见 §0.2）：
   接活 `EventType.AGENT_COMMAND`（`session_sync_manager.py:48`，现为死枚举）作为入站
   `type="agent_command"`，消息体 `{action: resume|cancel|takeover, session_id, request_id}`，
   在 `api/endpoints/session_sync.py:192` 消息循环内新增分支；出站按仓内既有回帧范式
   返回 `{"type":"agent_command_ack", …}`；后端挂起点等该 ack，
   超时/放弃沿用 `_await_ssh_credential`（`tool_executor.py:4692-4710`）同族的
   有限轮询范式兜底，不新造等待语义。

三平台通道 → 形态归一：GUI 注入类动作一律不进用户输入设备；Linux 下无 GUI 的
服务器形态整个退化为 终端态 + 浏览器态（`ssh_runner` + CDP），这是
`ssh_runner.py`"Linux/macOS 远程 = SSH 命令，无 GUI"既有定位的自然延伸。

### 4.4 隐私与权限

- `delivery=isolated_plane` 的隔离平面画面**全量可看**（本来就是给用户看的）；
- 用户桌面的 `beforeScreenshot` 只截目标窗口（`PrintWindow` 到目标 hwnd，非全屏），
  避免把用户桌面无关内容流进会话记录；
- dock 面板加"暂停观测"开关（只停画面推送，事件时间轴照记），
  对应后端截图采集节流为 0；
- 采集节流必须与 §4.1 的感知槽记账（`offerTurnPerceptionImage`）**解耦**——
  用户关掉的是**推送**，不是**模型侧看图**，二者早退点不同（`:4956-4972` 已钉此顺序）。

## 5. 平台兼容矩阵

通道名一律用 `route` 值（§0.3）；CLI 列的载体已按拍板改为既有非 PTY 常驻会话。

| 平台 | 无抢占 GUI 动作 | 降级 fallback | 虚拟平面 | CLI | 仲裁器 |
|------|----------------|---------------|----------|-----|--------|
| Windows + Win32/WinUI | `uia` Invoke（`desktop_uia.py` 已有） | `app_post` → `remote` | RDP 二级会话/会话池（`rdp_provider`/`remote_backend` 已有骨架） | `shell_sessions` 本地 + `sandbox_provider` | 低级钩子 |
| Linux + X11 | `atspi` doAction（依赖 AT-SPI2 绑定） | `xdotool` --window → `remote` | Xvfb / 容器 | `shell_sessions` 本地 + `ssh_runner` 远程 | evdev 只读 |
| Linux + Wayland | `atspi` doAction | **`xdotool` 判 `unsupported_method`**（协议禁止注入），直接 `remote` | Xvfb（XWayland）或 headless 合成器 | 同 X11 | evdev 只读 |
| macOS | `accessibility` PerformAction（AXUIElement） | `remote` | 虚拟机 | `shell_sessions` 本地 + `ssh_runner` 远程 | CGEventTap（需辅助功能授权） |
| 无 GUI 服务器（Linux） | — | — | 会话池按需起 Xvfb | **`ssh_runner`（已有）+ `shell_sessions`**，dock 走终端态 | 不适用（无输入设备） |

浏览器动作三平台统一走 CDP 独立实例（`browser_manager` 已有，`route` 为
`playwright_role`/`camofox_ref`/`dom` 三值之一），不进矩阵。

**本机验证边界**：当前实施机为 Windows。Linux/macOS 三行、以及"无 GUI 服务器"行的
`atspi`/`xdotool`/`accessibility`/evdev/CGEventTap 五条通道**在本机无法 live-verify**，
按 §6 的"代码交付"档处置（实现 + 单测 + 显式 `unsupported_method`/`capability` 三态降级，
真机活体待测试机）；本仓已有同档先例——`sandbox_provider.py:7-9` 就诚实声明了
"真机拉起留待人工真机验收"。

## 6. 实施切分（含验证边界与判据）

| 批次 | 内容 | 依赖 | 本机可 live-verify |
|------|------|------|-------------------|
| W1 | `ROUTES`/`DELIVERIES` 扩值 + ActionResult 点名通道 + WS 契约扩展（`beforeScreenshot`/`target`/`paused`/`terminal` 扩列）+ 前端抽 `delivery`/`evidence`/`escalation` + **帧对态**与**终端态**渲染（`shell_sessions` 推送口接线） | 无（`desktop_uia`、`ssh_runner`、`runtime_policy`、`shell_sessions` 均已在） | 是（Win 全链） |
| W2 | `input_arbiter.py` 三平台（低级钩子 / evdev / CGEventTap）+ `paused` 广播 + **接活 `AGENT_COMMAND` 双向命令通道** + 让位横幅/确认卡 + `global_input` 闸门由 env 收口到审批面 | W1 | 仅 Windows 钩子；Linux/macOS 代码交付 |
| W3 | `atspi` 与 `accessibility`(AX) 通道接入 + Wayland `unsupported_method` 诚实降级 + 桌面侧一等寻址（对齐浏览器侧 T-08 的语义，非移植其实现） | W1；Linux/macOS 测试机 | 否（代码交付） |
| W4 | 隔离平面帧流端点 + 面板流态 canvas（`route=remote` 归入流态） | RS 会话池骨架（`rdp_provider`/`remote_backend` 已有） | 部分（本机 RDP 二级会话可试） |
| W5 | 低置信度待确认卡片（决策层接入，复用 `target_resolver` 歧义口径）+ 输出留档回放（可选） | W1，非阻塞 | 是（决策层与平台无关） |

每批先红后绿，判据（§0 校准后已去掉"PTY 逐行"这类不可达判据）：

- **W1**：① 无 Invoke 支持的控件走 `app_post` 时 `action_result.route` 落 `app_post`
  且 WS 事件带 `beforeScreenshot`；② `computer_shell` 经 `shell_sessions` 执行时，
  WS 按 `terminal.sessionId` 逐段到达 `terminal.delta`，终帧带 `final`+`exit`+`elapsedMs`，
  且断言终帧聚合输出与工具返回值内容一致（**不再断言"与 PTY 流一致"**）；
  ③ `extractActionResult` 抽出 `delivery`/`evidence`/`escalation`，前端徽标随 `route`
  切换形态；④ 任何新 route 值越界仍被 `build()` 抛住（守卫既有不变式）。
- **W2**：合成输入期间注入真实输入事件 → 动作流挂起且 `paused=true` 广播到达；
  `agent_command` 入站 `resume`/`cancel` 均得到 `*_ack` 回帧且后端挂起点被唤醒。
  Windows 判据用本机低级钩子实测；Linux 侧按文档原案应"uinput 注入假设备做红灯"，
  本机无从执行 ⇒ 该判据降级为**单测 + 待测试机**，在工单里显式标注，不谎称已验。
- **W3**：Wayland 下 `xdotool` 路由返回显式 `unsupported_method` 且不静默跳级；
  非 Windows 平台 `availabilityDetail()` 三态读数不塌成笼统 `False`
  （`desktop_uia.py:40-42` 已说明二者自救动作相反，不可合并）。
- **W4**：`route=remote` 时 `delivery=isolated_plane`，面板切流态；帧流端点不可达时
  退回"每动作一帧"且面板显式标注当前非流态。

## 7. 参考资料（仅作调研背景，**不作事实源**）

平台 API 与依赖只按本仓功能依赖登记（版本、许可、用途）；下列条目不构成设计标准，
本仓所有通道形态以 §0.2 实测落点为唯一依据（`AGENTS.md` 协作红线·原创性与自主性）。

- AT-SPI2 / pyatspi2 —— Linux 无障碍动作接口（`route=atspi` 的平台 API）
- xdotool —— X11 窗口级合成事件投递（`route=xdotool` 的平台工具）
- WM_LBUTTONDOWN / PostMessageA —— Windows 消息级投递（`route=app_post` 的平台 API）
- Android AccessibilityService —— 跨平台对照：API 级动作不接管触摸
- [Characterizing Unintended Consequences of GUI Agents (CHI 2025)](https://arxiv.org/html/2505.09875v2)
- [RecAgent: Uncertainty-Aware GUI Agent](https://arxiv.org/abs/2508.04025)
- [Toward a Human-Centered Evaluation Framework for GUI Agents](https://arxiv.org/abs/2504.17934)
- 隔离平面路线的业界形态综述见 §2 表格；本仓 `remote`/`isolated_plane` 的落地形态
  由 RS 会话池方案（`rdp_provider`/`remote_backend`）决定，不引入外部实现的设计标准。
