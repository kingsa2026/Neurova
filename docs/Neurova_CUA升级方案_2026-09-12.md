# Neurova CUA 升级方案（整合 OCU × Cua 优点）

> 日期：2026-09-12
> 依据：[OpenComputerUse 对比报告](Neurova_OpenComputerUse代码级对比_2026-09-12.md) + [Cua 对比报告](Neurova_Cua代码级对比_2026-09-12.md)；2026-09-12 第二版：**远程会话平面（RS-1~5，原独立文档《云桌面池化远程桌面替代方案》已整合入第 6 节）**
> 性质：实施计划（未开工）。全文遵循 AGENTS.md 四原则 + 修复教义 + 增量式硬约束（只提升不下降，不动 agent_core.py 核心框架，接口扩展必须同步测试替身，测试文件一律进 tests/ 分类目录）。
> 分期总览：**Phase 0 桌面可用性根治（2 项 bug + 2 项能力补齐）→ Phase 1 语义桌面层 + ActionResult 契约层 → Phase 2 管线/评测/前端 → Phase 3 远期（SOM/MCP 导出/技能文档）+ 远程会话平面（RS-1~5，隔离桌面/云桌面的自建轻量路线）。每项自带 TDD 计划与验收标准。**

---

## 0. 目标终态（一段话）

桌面端拥有与浏览器端**对等的语义契约**：`computer_dom_snapshot`（UIA 控件树 + generation）→ `computer_click_element` / `computer_set_value`（语义寻址，像素坐标降级为第二档），所有 computer/browser 工具结果统一携带 **ActionResult 封闭结构**（route/effect/delivery/evidence），动作成功后**自动回传刷新截图**形成观察闭环，坐标经 **DPI/多屏换算链**精确映射，执行前经**归一化层**拦截畸形参数，能力边界由**证据台账**锁定，评测由 **simulated 假桌面**进 CI 护航；远期以来宾守护进程 + 池化托管的**远程会话平面**把隔离桌面（Windows Sandbox / Linux 容器 / RDP 直连）纳入同一工具契约。

## 1. 现状基线与病根（为什么按这个顺序修）

| 病根 | 位置 | 后果 |
|---|---|---|
| 桌面无元素枚举，盲坐标点击 | `builtin_tools.py:101-152`、`tool_executor.py:2612` | 点错无救济，复杂桌面任务成功率趋近 0 |
| 无 DPI/多屏处理 | `computer_use/__init__.py:81-96` | 缩放 150%/双屏环境坐标必错 |
| 动作只回元数据 | `tool_executor.py:2612-2684` | agent 盲操作，多一轮往返才"看" |
| scroll 丢方向 + dx 忽略 | `computer.py:419-427`、`tool_executor.py:2673` | 滚动语义错误（bug） |
| success:bool 无路由/证据 | `browser_manager.py:57`、`_normalize_browser_result:2714` | camofox ref 静默失配等假成功不可读 |
| 畸形 LLM 参数直接分发 | `tool_executor.py` dispatch 全线 | 幻觉坐标/词表外值直通 pyautogui |
| 桌面零测试、能力无台账 | tests/ 无 computer 桌面用例 | 假绿/回退不可知 |
| 死代码与死接线 | vision*.py 1,400 行、`_get_firewall` | 维护噪声，误导后续开发 |

## 2. Phase 0 — 桌面可用性根治（预计 1~2 天，全部先红后绿）

### R0-1 scroll 方向根修（bug 修复，净 LOC ≤ 0 验收）
- **设计**：新建单源换算函数 `_scroll_semantics(scroll_x, scroll_y) -> clicks, horizontal`（放 `computer_use/__init__.py`，pyautogui 契约：正 y=向上，负 y=向下；dx≠0 走 hscroll），三处消费方（`tool_executor.py:2673` agent 路径、`computer.py:424` HTTP 路径、manager.scroll 实现）全部改为消费它——放大视角一次修齐。
- **TDD**：`tests/unit/computer/test_scroll_semantics.py`（新目录）——红：断言 `scroll_y=3 向上/scroll_y=-3 向下/dx=5 走 hscroll/HTTP dy=-3 不再变向上`；修到绿。
- **验收**：live-verify 前端面板双向滚动方向正确。

### R0-2 DPI/多屏坐标链
- **设计**：① 进程级 DPI awareness（`ctypes.windll.shcore.SetProcessDpiAwareness(2)`，在 manager 初始化一次）；② `ImageGrab.grab(all_screens=True)` + 虚拟屏幕原点偏移；③ 截图与点击间坐标换算函数 `screen_px_to_logical / logical_to_screen_px`（语义照抄 OCU `screenshotPixelScale` 三函数：PNG 实际像素 ÷ 逻辑尺寸 = scale）；④ manager 暴露 `screen_metadata() -> {virtual_origin, logical_size, pixel_size, scale}`，点击前把 LLM 给的**截图像素坐标**换算成逻辑坐标。
- **TDD**：`tests/unit/computer/test_coordinate_chain.py`——用注入的假 metadata 测换算纯函数（不依赖真屏）；scale=1.0/1.5/2.0 与多屏偏移用例。
- **验收**：150% 缩放真机上点"开始菜单"命中（live-verify）。

### R0-3 动作后自动回传刷新截图
- **设计**：`_execute_computer_click/type/scroll` 成功且 `screenshot_delay`（默认 0.5s，常量）后自动再截一张，经 `_emit_computer_event` 推 `computer_action`（payload 加 `refreshed: true`）；LLM 结果只加一个轻量字段 `refreshed_screenshot: true` + 文案"已回传操作后画面，如需确认结果请调用 computer_screenshot 或观察面板"——**保持截图不进 LLM 上下文的双通道契约不变**（比 Cua ImageRetention 更优的设计不回退）。
- **TDD**：`tests/unit/computer/test_action_refresh.py`——mock manager 断言 click 成功后二次 screenshot 被调用、事件 payload 带 refreshed、LLM 结果无 base64。
- **验收**：前端面板在点击后自动切到新帧。

### R0-4 /status 真实化 + /doctor 端点
- **设计**：`desktop_available` 拆为 `screenshot_available`（PIL 后端）与 `input_available`（pyautogui 真实导入 + 首次 `position()` 探测）；新增 `GET /v1/computer/doctor` 返回逐项 {pillow, pyautogui, uia(Phase 1 起), dpi_aware, screen_metadata}，登录即可读。
- **TDD**：`tests/unit/computer/test_status_doctor.py`——注入假 import 状态断言四象限组合。
- **验收**：pyautogui 卸载环境 /status 不再假报可用。

## 3. Phase 1 — 语义桌面层 + ActionResult 契约（预计 4~6 天，本方案核心）

### R1-1 桌面 a11y 树与语义寻址（对标 OCU Windows runtime + Cua AX/PX 分离）
- **新文件**：`neurova/computer_use/desktop_uia.py`（Windows 优先；`uiautomation` 库，fallback pywinauto；非 Windows 返回 unsupported 拒绝码）。OCU `apps/OpenComputerUseWindows/runtime.ps1`（UIA+PostMessage，1,008 行）为翻译参考。
- **核心契约**（与浏览器侧 generation 语义对齐，复用同一新鲜度心智）：
  - `snapshot(target) -> {generation, window: {title, rect}, elements: [{index, role, name, rect, enabled, value?, focused?, settable?}]}`——element 标识 = `index`（快照内稳定）+ 可选 `runtime_id`（UIA 原生，跨快照更稳）；预算 `max_nodes(默认 400)/max_depth(默认 32)/text_limit(默认 120)`。
  - `click_element(target, index|runtime_id, button)` 递降链：UIA Invoke → Toggle/Expand（按 role）→ LegacyIAccessible DoDefaultAction → **PostMessage 直投窗口矩形中心**（app_post 等价，不抢焦点）→ 全局 SendInput（仅 `NEUROVA_ALLOW_GLOBAL_INPUT=1` 门控，默认关）。每级结果写 route + 失败写精确拒绝码。
  - `set_value(target, index|runtime_id, value)`：ValuePattern 优先 → 键盘投递兜底。
  - generation 语义：快照后窗口拓扑变化 → 递增 → 旧 index 拒绝（拒绝码 `stale_generation`），与 browser 侧 `_check_active_generation` 同构。
- **新工具**（`builtin_tools.py` 追加，中文 description 沿用现有风格）：
  - `computer_dom_snapshot` {window_title?（缺省=前台窗口）, max_nodes?, max_depth?}
  - `computer_click_element` {window_title?, index 或 runtime_id, button?}
  - `computer_set_value` {window_title?, index 或 runtime_id, value}
  - `computer_click` 保留（像素坐标成为递降第二档，description 改写引导先快照）。
- **治理**：三新工具纳入 `governance.py` 评估（click_element 默认 ALLOW-review 档，set_value 同级；PostMessage 直投不越权——UIA 语义动作本身受 UIPI 约束）。
- **TDD**：`tests/unit/computer/test_desktop_uia.py`——用假 UIA 后端（测试替身与真实契约逐字段对齐，吸取 09-11 接口扩展事故）测快照裁剪/generation 失效/递降链逐级 fallback/拒绝码；`tests/unit/agent/test_builtin_tools_schema.py` 补三工具 schema 校验。
- **验收**：live-verify——记事本场景：snapshot→click_element 菜单→set_value 编辑区，全程前台窗口保持焦点（不抢焦点即 PostMessage 路径生效的直接证据）。

### R1-2 ActionResult 封闭契约（Cua C-1 × OCU 诚实降级，合并实施）
- **新文件**：`neurova/computer_use/action_result.py`：
  ```python
  ActionResult = {
    "route": "accessibility|uia|app_post|global_input|playwright_role|camofox_ref|dom|remote",
    "delivery": "background|foreground|not_applicable",
    "effect": "confirmed|partial|unverifiable|suspected_noop|refused",
    "evidence": ["value_readback"|"window_change"|"screenshot_diff"],  # confirmed 必填≥1
    "refusal_code": "stale_generation|ref_not_found|background_unavailable|background_occluded|permission_required|unsupported_method|...",  # refused 必填
    "escalation": {"target": "pixel|foreground|page", "reason": "..."}  # 可选
  }
  ```
  **不变式**（构造器强制）：`confirmed ⇒ evidence≥1 且无 refusal_code`；`refused ⇒ 无 evidence/delivery`；`suspected_noop` 用于"已投递但无验证手段"（camofox ref 正则命中的唯一性存疑、app_post 无 readback 等）。`route=remote` 为第 6 节远程会话平面预留。
- **接入点**：① `_normalize_browser_result`（`tool_executor.py:2714`）为 BrowserResult 补 action_result 字段；② camofox `_find_ref_in_yaml` 失配改为返回 `refused/ref_not_found` + 最近似候选名（消灭静默失配）；③ Playwright role 点击 route=`playwright_role`/delivery=`background`；④ R1-1 桌面递降链逐级写 route；⑤ pyautogui 路径 route=`global_input`/delivery=`foreground`（诚实声明必抢焦点）。
- **前端**（可延至 R2-5）：ComputerUsePanel 动作日志行显示 `route/effect` 徽标。
- **TDD**：`tests/unit/computer/test_action_result.py`——不变式逐条红绿 + 各工具结果样本快照测试；`tests/unit/browser/`（既有 camofox 测试文件）补 ref_not_found 结构化断言。
- **验收**：任意 computer/browser 工具结果都含 action_result 字段；grep 全库无"静默 False"返回路径（放大视角收口）。
- **伴生重构（RS-2 前置）**：提取 `neurova/computer_use/actions.py`——把 tool_executor 中 computer 动作实现体抽为可独立调用的模块，宿主本地执行与 R2-4/R1-1/来宾守护进程共用同一份实现（本批仅做提取，不改行为）。

### R1-3 执行前归一化层（Cua OperatorNormalizer）
- **设计**：`tool_executor.py` 增 `_normalize_computer_params(tool, params)`，在 dispatch 表前统一执行：坐标数值化+clamp 到屏幕范围、button 词表归一（"middle-click"→"middle"）、scroll 语义过 R0-1 单源函数、generation/index 强转 int、未知键拒绝（HTTP 侧 `extra="forbid"` 精神推广到 agent 侧）。
- **TDD**：`tests/unit/agent/test_action_normalizer.py`——畸形样本表驱动。

### R1-4 dispatch 三副本单源化（OCU P1-5，净 LOC 预期大幅为负）
- **设计**：`computer.py:332` 与 `:747` 的重复注册删除，两路由都走 `_dispatch_browser_command`（:283）单源；顺带核验 `_browser_state`（:344）死变量删除。

### R1-5 观察预算参数化
- **设计**：`browser_dom_snapshot` 加 `max_nodes/max_depth`（Playwright aria snapshot 后裁剪），沿用"显式调用才可放大，动作刷新快照用默认预算"规则（OCU 契约）。

### R1-6 死代码与死接线处置（修复教义反向清理）
- `vision*.py`：**保留到 Phase 3 R3-1 决策点**，但先在模块头加显式弃用注记防误接入；若 R3-1 立项则其 OmniParser 语义被吸收，删除旧实现。
- `_get_firewall`（`computer_use/__init__.py:59`）：接入 `shell`/file 读写路径作为 precheck（真接线），或删除——实施时二选一，禁止保留第三态。

## 4. Phase 2 — 管线/评测/前端（预计 3~5 天）

### R2-1 type_text 语义化（OCU 智能输入，依赖 R1-1）
- 先探 focused editable 控件（UIA ValuePattern）直接赋值（含占位符识别），失败再键盘投递；结果 route 如实标注。

### R2-2 simulated 评测台（cua-bench 简化版，零 VM 进 CI）
- **新目录**：`tests/e2e/cua_sim/`——Playwright 驱动 HTML 假桌面（任务栏+窗口+按钮/输入框），任务契约 `setup()/solve()(参考解)/evaluate()->reward`；先落 3 个任务：点击按钮改状态、表单填写提交、滚动后读取列表项。pytest 集成，作为桌面/浏览器回归的**行为级**护栏（断言 reward==1.0，不是"不崩"）。

### R2-3 能力台账最小版（Cua 证据台账思想）
- **新文件**：`docs/CUA能力台账.md` + `tests/e2e/cua_sim/ledger_test.py`——按"后端 × 投递路径 × 验证 oracle"登记 delivered/refused(码)/gap；每个 refused 断言精确拒绝码。台账与 R2-2 测试互为证据。

### R2-4 历史图片保留回调（Cua ImageRetention，成对删除）
- **设计**：消息历史组装处（ChatPipeline 上下文装配段）加策略：仅保留最近 N=4 张图片轮，更早的图片轮**连同其 reasoning/工具对**一并置空占位。先做只读统计测试（上下文 token 降幅），再启用。
- **TDD**：`tests/unit/agent/test_image_retention.py`。

### R2-5 前端增强
- ComputerUsePanel：route/effect 徽标 + agent 点击位置标记图层（WS payload 已含坐标，纯前端）；新 UI 文案走 i18n 11 语言键位一致性测试（locale guard）。

### R2-6 camofox ref 解析加固
- 名含引号/括号场景的解析修正 + 非唯一匹配返回候选列表（并入 R1-2 的 refused 结构）。

## 5. Phase 3 — 远期选项（独立立项，不在本批）

| 项 | 触发条件 | 说明 |
|---|---|---|
| R3-1 SOM 视觉复活 | 桌面任务需要无 a11y 目标（游戏/自绘 UI） | OmniParser 式编号标注图+id2xy，吸收 vision.py；历史截图替换保 id 一致 |
| R3-2 远程会话平面 | 需要隔离桌面/无人值守桌面任务 | **已并入第 6 节 RS-1~5，不再单列** |
| R3-3 CUA 双层 MCP 导出 | 外部 agent 生态接入需求 | agent 面 MCP（run_task）+ 工具面 MCP（computer_* 全量） |
| R3-4 profile 附身授权 + 动作审计 | 治理完善批次 | camofox 登录态 profile 使用前显式 grant；审计只存元数据白名单（永不存截图/键入文本） |
| R3-5 CUA 使用纪律技能文档 | 随 R1 一起小幅先行 | 观察→语义点击→像素兜底的阶梯、敏感 app 禁区、外部可见动作先问（写入系统提示技能段） |

## 6. Phase 3 扩展 — 远程会话平面（RS-1~5，隔离桌面的自建轻量路线）

> 定位：取代 Cua Fleet 式云桌面池化的自建方案。核心判断：**Fleet 的本质不是"远程桌面协议"，而是"容器/VM 托管 + 来宾内控制守护进程 + 显示流"三层**；远程桌面协议只承担"人看"层，**agent 的动作永远走控制面（HTTP/WS），不走显示协议**——显示层的延迟/画质/协议差异对 agent 成功率零影响。控制面 Neurova 已有（computer_* 契约），缺的只是把它搬进来宾 + 一个进程内池管理器。

### 6.1 候选项目盘点（2026-09-12 GitHub 实核）

**会话托管层（"一台计算机"从哪来）**

| 项目 | 星数/协议 | 是什么 | 角色 |
|---|---|---|---|
| [dockur/windows](https://github.com/dockur/windows) | 53.2k★ MIT | Windows 10/11 跑在 Docker（QEMU/KVM），ISO 自动下载免手装，Web viewer(:8006)+RDP(:3389)，Win95~Win11/Server 全版本、`/oem` 装后脚本 | **Linux 主机**上的一次性 Windows 桌面首选。⚠️ 需 Linux 主机 KVM，Windows 主机不可用 |
| [linuxserver/docker-webtop](https://github.com/linuxserver/docker-webtop) | 4.4k★ GPL-3.0 | 浏览器直开的 Linux 桌面容器：XFCE/KDE/MATE/i3 × Alpine/Arch/Debian/Fedora/Ubuntu；**2025-06 起流媒体层全面切到 Selkies**（WebCodecs 需 HTTPS :3001） | **Linux 一次性桌面**首选，秒级拉起 |
| [m1k1o/neko](https://github.com/m1k1o/neko) | 22.3k★ Apache-2.0 | WebRTC 虚拟浏览器/桌面（v3），完整 XFCE/KDE 桌面 + **多人协同控制** + 会话录制 | 审批现场多人围观 agent 操作时用；单 agent 场景 webtop 更轻 |
| [sickcodes/Docker-OSX](https://github.com/sickcodes/Docker-OSX) | GPL-3.0 | Docker 里的 macOS（VNC） | 主战场非 macOS，暂不纳入 |

**显示流层（人怎么看）**

| 项 | 取舍 |
|---|---|
| **现有 WS 截图流** | **MVP 即够**：agent 面板本来就在收 `computer_action` 截图帧，来宾模式零新增前端工作 |
| [noVNC](https://github.com/novnc/noVNC) | 行业默认，embed 进 Vue 最易；帧率画质一般 |
| [Selkies](https://github.com/selkies-project/selkies) | 2.1k★ MPL-2.0，WS 默认 + WebRTC 可选，GPU/CPU 加速，X11+Wayland，60fps@FHD；低延迟人类接管再上；需 HTTPS 安全上下文 |
| KasmVNC | webtop 已迁走，新项目不选 |
| [Apache Guacamole](https://guacamole.apache.org/) | 1.6.0（2025-06）Apache-2.0，RDP/VNC/SSH 聚合网关 + **会话录制**（治理审计联动）；代价 Java 栈，可选项 |
| [Sunshine](https://github.com/LizardByte/Sunshine)+Moonlight | 硬编最低延迟，但客户端是终端 App，web 嵌入弱；仅当"人远程重度操作"成需求 |

**协议直连与排除项**

- **RDP 直连**（xrdp/FreeRDP 生态）：连用户既有真实 Windows 机器/VM——不造池子，把授权过的远程机器当会话后端；凭据走现有凭据分桶。
- **RustDesk / Sunshine 客户端路线明确排除**：面向人工远控设计，不适合 agent 程序化控制通道。
- Scrapybara 类闭源 SaaS 不纳入（repo 已 404，且方向是 SaaS）。

**按主机类型的 Windows 桌面来源（关键 nuance）**

| 宿主 | 一次性 Windows 来源 | 显示/控制 |
|---|---|---|
| Windows 主机（生产现状） | **Windows Sandbox**（Win Pro 内置，秒级，用完即毁）；Hyper-V Quick Create VM 池（PowerShell 管理，差分盘/checkpoint）；RDP 直连既有机器 | 控制走来宾守护进程（Sandbox 开网络即可）；显示走截图流（Sandbox 内 RDP host 默认关，不必强求 VNC） |
| Linux 主机（服务器部署） | dockur/windows 容器（KVM） | RDP :3389 + Web viewer :8006，人可看可接管 |
| 纯轻量需求 | Linux 桌面容器（webtop）直接跑任务 | 浏览器直开 |

### 6.2 整合架构（工具面零改动）

```
聊天页 Agent                    Neurova 服务端                     远程会话平面（新增）
───────                        ──────────                        ──────────────
computer_* 工具  ──工具调用──▶  tool_executor（dispatch 不变）
                               ├─ governance/approval（不变）
                               └─ ComputerUseManager 扩展
                                   ├─ backend=local（现状，pyautogui/UIA）
                                   └─ backend=remote ★新
                                        │ claim() 来自池管理器
                                        ▼
                              ┌─ 池管理器 DesktopSessionPool（进程内，非 K8s）
                              │    预热容器/VM、claim/release、空闲 TTL、
                              │    差分盘/checkpoint 重置、per-user 标记
                              ▼
                       来宾守护进程 neurova-guest-agent ★新
                        （复用 R1-2 提取的 actions.py，端口 8765，WS+REST）
                        + 显示流：截图帧(现有 WS) / noVNC / Selkies / RDP
                              ▼
                       容器：webtop(Linux) / dockur-windows(Linux宿主)
                       VM：Windows Sandbox / Hyper-V(Windows宿主)
```

三个设计要点：

1. **控制面与显示面分离**（抄 Cua 不抄 Fleet）：agent 动作 = HTTP/WS 到来宾守护进程；显示协议只给人看。"远程桌面"的延迟/画质差异对 agent 链路零影响——相对"用 RDP/VNC 注入输入事件"路线的决定性优势。
2. **来宾守护进程复用现有契约**：R1-2 伴生重构已把动作实现提取到 `actions.py`，宿主本地与来宾守护进程共用同一份 → `computer_*` schema、ActionResult、governance 语义一字不改，仅 route 增加 `remote` 档、delivery 天然 `background`——**本地模式"非侵入"难题在远程模式自动消失**（来宾是隔离计算机，抢不到用户真机焦点）。
3. **池管理器是进程内的，不是 K8s**：`DesktopSessionPool`（预热 N 个、claim/release、空闲 TTL、Windows 差分盘/Sandbox 天然重置、per-user 标签沿用现有隔离心智）≈ 数百行；Fleet 的 WarmPool/Claim CRD 概念直接翻译，运行在单服务进程里。

### 6.3 分级落地批次

| 批次 | 内容 | 依赖 |
|---|---|---|
| RS-1 | **Windows Sandbox 后端**：本机一次性桌面，截图流复用现有面板，控制走 guest agent | R1-2（ActionResult + actions.py 提取）+ R1-1（来宾内复用 UIA 动作实现） |
| RS-2 | **来宾守护进程** `neurova-guest-agent`：端口 8765 WS+REST，暴露与本地一致的 computer_* 动作；Sandbox/容器内同一守护进程 | RS-1 |
| RS-3 | **Linux 容器后端**：webtop 镜像 + 内置 guest agent 的定制 Dockerfile + DesktopSessionPool | RS-2 |
| RS-4 | **RDP 直连后端**：用户授权的既有机器，凭据走现有凭据分桶 | RS-2 |
| RS-5 | 可选增强：dockur/windows（Linux 宿主一次性 Windows，预热池+差分盘缓解拉起慢）、Guacamole 网关（多协议聚合+会话录制审计）、neko（多人围观）、Selkies（低延迟人类接管） | 按需 |

### 6.4 该平面同时解决的三个老问题

1. **"非侵入"从难题变默认**：本地 pyautogui/UIA 永远纠结抢不抢用户焦点；远程会话 `delivery=background` 天然成立，ActionResult 在远程档最干净。
2. **沙箱一致性**：governance 的 `_platform_has_enforced_sandbox()`"诚实升级"规则（无真隔离时 SANDBOX→DENY）在远程后端拿到真隔离，HIGH 风险动作从"拒"变"可跑"——agent 能力上限直接提升。
3. **审批现场可视化**：approval 流 + 来宾桌面截图流（或 noVNC/Selkies 接管）让"人工确认再执行"有了操作现场，不只是看参数列表。

### 6.5 取舍与风险（诚实清单）

| 代价 | 说明 | 缓解 |
|---|---|---|
| Windows Sandbox 局限 | 每次全重置（无持久态）、需 Win Pro+、嵌套内存开销 | 持久态走 Hyper-V 差分盘或 RDP 直连；Sandbox 定位=高风险一次性任务 |
| dockur/windows 拉起慢 | 首次 ISO 下载+安装分钟级 | 预热池 + 差分盘快照；`/oem` 脚本预置 guest agent |
| Windows 许可 | dockur/windows 不分发 Windows，需自备 license | 生产部署前法务确认；Sandbox 无此问题 |
| 镜像维护 | webtop/guest agent 镜像跟版本 | 固定 tag + 月度重建；镜像构建脚本入库 |
| 显示流 HTTPS | Selkies/WebCodecs 需安全上下文（前端 :8100 是 http） | MVP 用现有截图流；上 Selkies 走反代 https |
| 多一层运维 | Docker/KVM/Hyper-V 依赖 | 全部可选项，local 后端始终兜底——**远程会话是增强不是替换**，local 坏了系统照常跑 |
| 安全边界 | webtop 容器内默认 passwordless sudo、网络可达性 | 容器网络隔离（无 INET 需求断网模式）、凭据不进镜像、per-user 容器沿用现有隔离审计 |

## 7. 依赖图与排期

```
R0-1 ─┐
R0-2 ─┼─ 并行 ─→ R0-3/R0-4 ─→ Phase 1
R1-1 ──→ R2-1(type_text语义化)
R1-2 ←── R1-1/R1-5/R2-6 都向它写 action_result
        R1-2 伴生 actions.py 提取 ──→ RS-2（来宾守护进程）
R1-3/R1-4 独立可先行
Phase 2 评测台(R2-2/R2-3) 依赖 Phase 1 契约定型（批次A契约约束下两次定型沿用）
RS-1 → RS-2 → RS-3/RS-4 → RS-5（会话平面独立成线，可与 Phase 2 并行启动）
```
建议合入节奏：Phase 0 一个提交批 → R1-1 单独批（新文件为主，风险隔离）→ R1-2+R1-3+R1-5+R1-6 一批 → R1-4 清理批 → Phase 2 两批 → RS-1/RS-2 一批 → RS-3/RS-4 一批。每批跑受影响套件回归（注意统一回归中预存 40F+17E 甄别口径，勿把预存红当新增回归）。

## 8. 风险与缓解（本批通用项）

| 风险 | 缓解 |
|---|---|
| `uiautomation`/`pywinauto` 依赖与被控应用兼容性差异 | 拒绝码体系兜底（unsupported→指引像素路径）；doctor 端点暴露探测结果；台账登记 gap |
| UIA 枚举大窗口性能（WinForms 老应用控件树爆炸） | max_nodes/max_depth 硬顶 + 懒展开（先子层后深挖）；快照超时熔断 |
| 新工具诱导 LLM 绕过治理 | 三新工具全量入 governance 评估与 fail-closed 白名单；skill 声明仲裁链不豁免；remote 后端沿用同一评估（风险等级不变，隔离变强只会放宽 sandbox 判定） |
| 测试替身与真实 UIA 契约漂移 | 09-11 事故新规：替身字段逐一对齐真实实现 + 一条 smoke 用例跑真 UIA（记事本 fixture） |
| 前端契约变化破坏 ComputerUsePanel | action_result 为**新增字段**，旧渲染不受影响（增量式）；i18n 键位一致性测试护航 |
| PostMessage 直投被误读为绕过治理 | route=app_post 全程可见于 ActionResult；治理评估在工具入口而非投递层，权限语义不变 |

（远程会话平面特有风险见 6.5。）

## 9. 明确不做（防范围蔓延）

Fleet 的 **K8s/SaaS 形态**（多租户控制面、预热池 CRD、Stripe 计费——RS 批次已用进程内池管理器覆盖其真实价值）、RL 训练环与轨迹转训练格式、Cua 全量 fixture GUI 矩阵、MCP skills 扩展（SEP-2640 未定稿）、macOS SkyLight 私有 SPI、系统级软件光标 overlay（用 R2-5 前端图层替代）、多平台桌面运行时矩阵（先做深 Windows）、RustDesk/Sunshine 作为 agent 控制通道。

## 10. 验收总门（Definition of Done）

1. Phase 0/1/2 每项 TDD 红→绿记录在案；bug 类（R0-1、R1-4、R1-6、R2-6）净 LOC ≤ 0，功能类超出行数在提交说明列出去向。
2. live-verify 三场景录证：① 150% 缩放真机语义点击记事本全流程（不抢焦点）；② 浏览器 ref 失配返回结构化 refusal；③ simulated 评测 3 任务 reward=1.0。
3. RS 批次追加验收：Windows Sandbox 一次性会话全流程（拉起→guest agent 动作→ ActionResult `route=remote/delivery=background`→ 销毁重置），HIGH 风险动作在远程后端从 DENY 变可跑的治理判据生效。
4. 受影响回归套件全绿（预存甄别除外）；ActionResult 不变式全量单测锁死；台账首批 ≥ 后端数 × 主要动作 的矩阵覆盖。
