# 无抢占 CUA 与 dock 可观测性 · 工单集（W1–W5 拆片）

> 2026-10-02 · 执行源唯一。上游设计：
> [`2026-10-01-computer-use-nonintrusive-and-dock-observability.md`](2026-10-01-computer-use-nonintrusive-and-dock-observability.md)
> ——其 §0.2 校准表与 §0.3 通道映射是本工单的**事实源前提**，§6 判据已在本文件落成可跑断言。
> 纪律依据 `AGENTS.md` 修复教义第 3 条（先红后绿）、第 4 条（live-verify）、第 5 条（同根因全命中点扫荡）、
> 第 6 条（单一事实源）。

**编号空间声明**：本集的 `T-01…T-09` 属于**无抢占升级批次**，与
`2026-09-30-computer-use-repair-tickets.md`（电脑操控面修正，`T-01…T-20`）、
Issue #90 上下文批次（`T-03b`/`T-07`/`T-09`）、Issue #197 等**不是同一编号空间**——
本仓已有四个批次复用 `T-` 前缀，跨文件引用一律须带批次名。
本集内部引用旧批时保留其原号并写明出处（如本集 T-07 所引"T-08 的语义"指电脑操控面批次的
ref 寻址工单，不是本集编号）。

## 0. 拆片原则与验证档

**垂直切片**：每片从后端事实源打到 dock 面板可见，不做"先建后端层再建前端层"的横切。

三档验证边界（本机为 Windows，教义第 4 条不可妥协，故诚实分档）：

| 档 | 含义 | 交付要求 |
|----|------|---------|
| **A 本机活体** | Windows 全链路可实测 | 单测全绿 + 真后端真端点/真动作自证，证据进提交说明 |
| **B 代码交付** | Linux/macOS 通道本机无从活体 | 单测覆盖路由与降级 + 显式 `unsupported_method`/三态读数 + 真机验收待办登记，**不得声称已 live-verify** |
| **C 阻塞待外部** | 依赖测试机/会话池落地 | 只登记，不开工 |

## 1. 工单

### T-01 投递事实可读（route/delivery 收口）· 档 A · 无阻塞

**动机**：`action_result.route`/`delivery`/`evidence`/`escalation` 后端已产出并整体透传，
但前端 `extractActionResult`（`useComputerPanel.ts:134-145`）**只抽三键、把 delivery 与
evidence 丢弃**——用户看得见"点了什么"，看不见"走哪条通道、有没有验证、是否碰了用户桌面"。
无抢占这件事，当前在 dock 上不可证伪。

**落点**：`action_result.py:20-32`（`ROUTES` 加 `shell`/`atspi`/`xdotool`，`DELIVERIES` 加
`isolated_plane`）→ `useComputerPanel.ts` 抽取面 → `ComputerUsePanel.vue:190-198` 徽标 →
`ComputerTab.vue:41-48` 的 `:deep` 压制收口。

**红灯判据**：
1. `build("shell","confirmed","not_applicable",["delivery_ack"])` 现抛 `route 越界` → 断言扩值后不抛；
2. `build("uia","confirmed","isolated_plane",[...])` 现抛 delivery 越界 → 断言转绿；
3. `refused` 仍不得携带 `isolated_plane`（既有不变式在扩值后依然咬合，防"扩值顺手放宽"）；
4. `extractActionResult({action_result:{route:"app_post",delivery:"background",evidence:["delivery_ack"],escalation:{target:"pixel"}}})`
   现丢后两键 → 断言抽出；
5. 词表守卫：`ROUTES`/`DELIVERIES` 每个值都必须在文档 §0.3 映射表出现，新值无映射即红
   （防第二份通道词表回流，教义第 6 条）。
6. 同根因扫荡（教义第 5 条）：`desktop_uia.py:9` docstring 自称"全局 SendInput"而实现为
   pyautogui（全仓 `SendInput` 零命中）→ 断言该文件源码不含 `SendInput` 字样，
   失实自述根修为诚实表述。

**净 LOC**：词表 +4 行，前端抽取 +若干；docstring 改写净 ≈0。

### T-01b UIA pattern 探测根修（T-01 活体抓出，已落地）· 档 A · 随 T-01

**这不是新需求，是 T-01 的投递事实第一次被看见之后当场抓出的谎**：把 `delivery/evidence`
抽到面板的前提是"后端产出的通道事实是真的"，一验就不真。

**根因**：`desktop_uia.py` 用 `getattr(ctrl, "IsInvokePatternAvailable", None)` 一族探测五轴
pattern，而该库的 `Control` **没有这一族成员**（活体实测 `dir(auto.Control)` 里 `Available`
零命中，真按钮上 `GetInvokePattern()` 返回 `InvokePattern`、`edit.GetValuePattern()` 返回
`ValuePattern`）。`getattr` 恒 `None` → 五轴恒 `False`。

**爆炸半径**（同根因全部命中点，`grep Is[A-Za-z]*PatternAvailable` 实测共 6 处）：
五级链 ①Invoke ②Toggle ③Expand ④LegacyDefault 永不可达 → 桌面点击全部落到 ⑤`app_post`
（PostMessage，保真度更低、命中测试不可靠）；`set_value` 的 ValuePattern 路径恒
`refused:background_unavailable` → 语义输入唯一出路是开 `NEUROVA_ALLOW_GLOBAL_INPUT`
= 抢焦点，**与"无抢占"这个本批主题正面冲突**。第二命中点：`:544` 读 `value` 走了同一个
不存在的 API，被 `except` 吞成恒 `None`，即快照里所有元素的 value 一直是空的。

**为什么潜伏至今**：`test_desktop_uia.py` 的 `FakeUIABackend` **直接注入**
`invokable=True` 的 element dict——夹具替生产码回答了"探测得到吗"，于是"真控件 → flag"
这一跳从来没被测过。本批新增的 `TestLiveControlShapeDiscovery` 夹具严格照活体取到的形状
构造（只给 `Get*Pattern`，不给 `Is*Available`），钉的正是这一跳。

**判据**（5 条，先红后绿）：真形状按钮 `invokable is True`；`legacy_default is True`；
edit 有 ValuePattern → `settable is True` 且 `value` 读回非空；控件压根不暴露该口
（window 无 `GetInvokePattern`）→ `False` 且不抛；**探测本身抛错时不得静默当作"控件不支持"，
必须留 warning**（教义第 2 条——把"我们探测失败"写成"目标不支持"是本仓最忌的谎形）。

**活体前后对照**（真 WinForms 探针窗口，非用户应用；用完即关）：

| 读数 | 修复前 | 修复后 |
|------|--------|--------|
| ProbeButton | `invokable:false` | `invokable:true` |
| ProbeField | `settable:false` | `settable:true` |
| menuitem | `expandable:false` | `expandable:true` |
| 点击 action_result | `route:app_post` | `route:uia` + `evidence:["delivery_ack"]` |
| set_value action_result | `refused:background_unavailable` | `route:uia` + `evidence:["value_readback"]`，读回 `t01-live-verify` |

**动机**：后台通道（`uia`/`app_post`/`atspi`/`xdotool`/`accessibility`）没有连续画面流，
"不抢屏"的代价必须用 before→after 帧对偿还，否则用户只看到一张孤零零的事后图。

**落点**：`desktop_uia.py` 动作前采集（`PrintWindow` 到目标 hwnd，非全屏）→
`tool_executor.py:4983-5009` payload 加 `beforeScreenshot`/`target` →
`useComputerPanel.ts` 状态结构（**`latestScreenshot` 单值装不下双帧，state 必须改**，
"骨架不动"仅对组件树成立）→ `ComputerUsePanel.vue:146-164` 帧对渲染 +
`:183` 扁平日志改纵向时间轴，复用 `MessageSteps.vue` 形状语言。

**红灯判据**：
1. 走 `app_post` 的点击动作（无 Invoke 支持的控件）→ WS 事件带 `beforeScreenshot` 且
   `action_result.route == "app_post"`；
2. `beforeScreenshot` 与 `screenshot` 在面板归并到**同一条**动作条目（不新开日志行）；
3. 目标窗口采集而非全屏（隐私判据：断言截图路径走 hwnd 而非屏幕区域，见 T-02 实现注）；
4. `paused`/帧对/终端三种形态由 `route` 驱动切换，`previewMode` 有单一判定源。

**登记为待办而非隐藏**：`post_click` 现投 rect 中心 + `time.sleep(0.02)` 硬编码
（`desktop_uia.py:443-468`），无 move/hover/拖拽/时延参数——帧对态可观测 ≠ 动作保真，
保真度缺口另立 **T-06b**。

### T-03 命令有终端（终端态 + shell_sessions 推送口）· 档 A · 阻塞于 T-01

**动机**：`computer_shell`/`computer_ssh_exec` 现状是**聚合后一次广播**（模型 `poll_session`
才拿输出），长命令期间 dock 空白——CLI 明明是天然无抢占的主通道，却是可观测最差的一条。

**落点**：`shell_sessions.py` 读线程（`:125-143`）加增量回调 → `tool_executor.py` 按
`terminal.sessionId` 推 `delta`、终帧 `final`/`exit`/`elapsedMs` → 前端终端卡流式渲染。
**不从零新造 PTY**（拍板：复用既有常驻会话，`streamId` 语义并入 `terminal.sessionId`）。

**红灯判据**：
1. 一条分多段输出的命令执行期间，WS 按同一 `terminal.sessionId` 到达 ≥2 帧 `delta`，
   且**未**出现重复的聚合 `stdout`；
2. 终帧 `final=true` 带 `exit` 与 `elapsedMs`，且**终帧聚合内容 == 工具返回值内容**
   （推送与拉取不两源，教义第 6 条）；
3. `exit` 键名归一：后端 `ssh_runner` 侧 `returncode` 到广播处必须落成 `exit`，
   断言 payload 不出现 `exitCode`/`returncode`（防第三种拼写）；
4. 会话取消/进程组杀灭路径仍生效（`spawnKwargsForKill` 那条不可选注释是承重的，
   加推送口不得绕过）；
5. 非 PTY 诚实边界：终端卡与工具 description 均含"TUI/tty 行为不保真"表述，
   断言 description 不含暗示真终端的措辞。

### T-04 暂停能被看见（input_arbiter · Windows 侧）· 档 A(Windows)/B(evdev·CGEventTap) · 阻塞于 T-01

**动机**：`neurova/computer_use/input_arbiter.py` **不存在**，"谁能碰真实输入"目前
只有 env 闸（`NEUROVA_ALLOW_GLOBAL_INPUT`）与五级链次序，无集中闸。

**落点**：新建 `input_arbiter.py`（Windows 低级钩子 WH_MOUSE_LL/WH_KEYBOARD_LL；
Linux evdev 只读、macOS CGEventTap 按档 B 交付）→ `global_input` 通道执行期挂起 →
`paused=true` 广播 → 面板让位横幅 + tab 呼吸点 → **闸门由 env 收口到审批面**
（复用 `runtime_policy` REVIEW 档 `require_approval`，env 退役）。

**红灯判据**：
1. `global_input` 执行期间注入一次真实输入事件 → 动作流挂起且 `paused=true` 到达；
   非注入通道（`uia`/`app_post`）期间同样的真实输入**不**触发挂起（不误伤后台通道）；
2. env 闸退役后，`NEUROVA_ALLOW_GLOBAL_INPUT=1` 单独存在**不得**再放行全局注入
   ——必须经审批面（把"配置即授权"改成"用户显式授权"，这是本设计的硬要求）；
3. Linux/macOS 无授权/无权限时 `availabilityDetail()` 三态不塌成笼统 `False`
   （`desktop_uia.py:40-42`：二者自救动作相反，不可合并）——档 B，单测覆盖。

### T-05 用户能发话（AGENT_COMMAND 双向命令通道）· 档 A · 阻塞于 T-04

**动机**：原稿称"回执走既有 WS 命令总线"，实测 `EventType.AGENT_COMMAND`
（`session_sync_manager.py:48`）是全仓**只有一行定义的死枚举**——总线不存在，本片是新建。

**落点**：`api/endpoints/session_sync.py:192` 消息循环加 `agent_command` 分支 →
回帧 `{"type":"agent_command_ack"}`（沿用仓内既有 `*_ack` 范式）→ 后端挂起点等 ack，
超时沿用 `_await_ssh_credential`（`tool_executor.py:4692-4710`）同族有限轮询兜底 →
面板"继续/取消"按钮接线。

**红灯判据**：
1. 入站 `{type:"agent_command",action:"resume"}` → 收到 ack 且挂起的动作流被唤醒；
2. `action:"cancel"` → ack + 会话内动作流终止且不留悬挂进程（复用 T-03 的杀灭单源）；
3. 未知 `action` → 显式拒绝并点名，不静默吞（教义第 2 条）；
4. `AGENT_COMMAND` 不再是死枚举：断言全仓存在 ≥1 生产者与 ≥1 消费者
   （把"接活"本身钉成守卫，防回退成占位）。

### T-06 Linux/macOS 通道接入 · 档 B · 阻塞于 T-01

`atspi`(Linux) / `accessibility`(macOS AX) 动作通道 + `xdotool` X11 定窗投递 +
**Wayland 判 `unsupported_method` 且不静默跳级**。
判据：路由表在 Wayland 下返回显式拒绝码；`ROUTES` 新值均有产出点（无"词表可用但永不产出"的空值）。
真机活体待测试机 ⇒ 本档**不声称 live-verify**，登记 RS/T 台账。
**T-06b**（同批登记）：`post_click` 保真度缺口——move/hover/拖拽/时延参数。

### T-07 桌面侧一等寻址 · 档 A(部分) · 阻塞于 T-01

原稿 §3 假设"桌面侧沿用 T-08 ref"，实测 **T-08 的 `RefTarget` 只在浏览器侧**
（`browser_manager.py:382-393`），桌面寻址是 `index`/`runtime_id`（`desktop_uia.py:301-326`）。
本片按 T-08 的**语义**（跨快照句柄 + 解不到即点名 + 对不上即拒且不发动作）在桌面侧立等价的
寻址面，非移植浏览器实现。判据复用 `ref-not-found`/`ref-mismatch` 两式的形状：
解不到必须给表大小与"先快照"指引；身份不符必须**拒且未发出任何动作**。

### T-08 隔离平面帧流 + 流态 canvas · 档 C → B · 阻塞于 RS 会话池

`route=remote` + `delivery=isolated_plane` 归入流态；P0 沿用每动作一帧，
P1 帧流端点不可达时退回每动作一帧并**显式标注当前非流态**。档 C：依赖会话池落地，
本机仅 RDP 二级会话可部分验。

### T-09 低置信度让位（决策层）· 档 A · 阻塞于 T-05，非阻塞排期

`target_resolver.py:78-96` 已是"不唯一即 `ambiguous`、绝不代模型挑"——
低置信度让位**复用该歧义口径**，不得新造第二套（教义第 6 条）。候选动作推待确认卡片。

## 2. 阻塞图

```
T-01 ─┬─ T-02 ──────────────────┐
      ├─ T-03 ──────────────────┼─(dock 三形态齐)
      ├─ T-04 ── T-05 ── T-09   │
      ├─ T-06 (B) ── T-06b      │
      └─ T-07 ──────────────────┘
T-08 ← RS 会话池（档 C，本轮不开工）
```

## 3. 收口清单（做完必须逐项打钩，防断点遗留）

- [x] `channel`/`plane`/顶层 `command`/`streamId`/`exitCode` 五键**全仓零出现**
      （W1-T01 键位级守卫在位，已入 `protected_tests.txt`；只扫带引号字面量会漏
      `channel?: string` 这种类型声明形态，判据已按变异实测升级）
- [ ] `ROUTES`/`DELIVERIES` 每个值都有产出点且有映射（无空值、无自由文本通道名）
      —— **映射半边已成守卫，产出半边未完成**：`shell` 等 W1-T03、`atspi`/`xdotool` 等 W1-T06。
      即当前这三个新值正是 W1-T06 判据里禁止的那种"词表可用但永不产出"的空值，
      本批刻意保留（词表先收口可防设计稿那四键回流），但**不许当成已交付**——
      若 W1-T03/W1-T06 最终不做，必须回头摘掉对应值，不许留空词表。
- [ ] `NEUROVA_ALLOW_GLOBAL_INPUT` env 闸退役，`global_input` 只经审批面放行（W1-T04）
- [ ] `AGENT_COMMAND` 有生产者与消费者（死枚举接活守卫在位）（W1-T05）
- [ ] 终端态的"非 PTY"限制在 description 与面板两处都可见（W1-T03）
- [ ] 档 B 各条在提交说明与台账中显式标注"未做真机活体"，不以单测全绿冒充端到端
- [x] 新判据逐文件跑绿后同批进 `scripts/ci/protected_tests.txt`（W1-T01/T-01b 四个文件已登）；
      本批未新增耗时断言，故时钟/墙钟台账无需新登（三道登记守卫 57 passed 为证）
- [ ] dock 渲染的浏览器内肉眼验收（W1-T01 以组件级判据 `actionBadgeText` + 模板接线代替，
      **未声称已在浏览器里看过**）

## 4. 本批取证顺手撞见的相邻断点（登记，不在本批顺手修）

1. **`NeurUI/package.json` 的 `lint` 脚本不可用**：命令调 `eslint`，但 eslint 既不在
   `dependencies`/`devDependencies`，也不在 `node_modules/.bin`，实跑报
   "eslint 不是内部或外部命令"。而 `AGENTS.md` 第 4 节把 `npm run lint` 列为前端必跑三项之一
   ——即该纪律项在本机**一直无法满足**，且失败形态是 shell 层报错，容易被当成环境问题跳过。
   处置需另拍：补依赖并全量过一遍既有代码（会翻红一大片，属独立决定），
   或如实把该项从纪律里摘掉。**不在本批顺手改**（会动 lock 与既有代码面）。
2. `tests/unit/api` + `agent/test_computer_browser_tools.py` + `integration/test_computer_use_integration.py`
   共 **20 条预存红**（W1-T01 做过 HEAD 回退 A/B，失败集合逐行相同 ⇒ 非本批引入）。
   大头：`test_transfers_wave_h4` 8 条、`test_files_store_persistence` 4 条、
   `test_route_mount_contract_guard` 3 条；广播那条是 MagicMock 冒充 user_id 拼进 Windows
   路径的 `<>` 非法字符（`sandbox_provider.py:91` 写 `.wsb` 时 OSError）。
3. `NeurUI/src/tests/duplicate-function-inventory.guard.test.ts` 收集期 SyntaxError（套件级 ERROR，
   "no tests"），`node --check` 过、不引用本批任何文件 ⇒ 预存。属 Issue #192 守卫域，未顺手修。
4. `desktop_uia.py:443-468` `post_click` 保真度缺口（rect 中心 + `sleep(0.02)` 硬编码、
   无 move/hover/拖拽/时延参数）→ 已列为 **W1-T06b**，不静默隐藏。
