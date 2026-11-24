# 移动端执行端（Device Execution End）落地实施计划（2026-11-23）

> **性质**：实施计划（备稿待拍板）。目标一句话：**把 Neurova 手机端从「用户的遥控器」升级为「agent 的手」**——后端 agent 经标准工具面向已配对手机下发设备动作并回收结构化结果，全程能力协商、审批治理、幂等账本、隐私红线。
> **方法**：本计划基于同日四路只读代码勘察（后端移动通道 / 后端工具管线 / 安卓原生端 / 鸿蒙端）逐条落到 file:line；机制参照同日对 aico-link（AidenAI-IO/aico-link，手机外挂 Agent 硬件）的研读——**该仓库为 AGPL 双许可，只借鉴机制与契约形态，不搬任何代码**。
> **纪律**：修复教义七条全适用。每卡先红后绿、live-verify 真后端/真机自证；单一事实源（帧型单源 `tunnel/protocol.py`、schema 单源 `builtin_tools.py`、租户单源 `core/tenant_scope.py`，不建平行体系）；全命中点扫荡；净 LOC 纪律。

---

## 1. 目标与非目标

**目标**
1. agent 通过 builtin 工具面（`device_*` 工具组）指挥已配对手机执行动作，首批覆盖：打开 URL/App、读写剪贴板、查应用列表、读设备环境（电量/屏幕/语言/网络）、读通知（安卓）、读屏与手势注入（安卓）。
2. 命令链路全程可靠：`(pairing_id, command_id)` 双向幂等、出站帧先落账再发、断线 `sync_resume` 重放、离线设备诚实报错并可经推送信令唤醒。
3. 全程治理：设备能力快照与运行前过滤、风险分级审批（复用 approval_chain）、步数/时长熔断、H-4 留痕、凭据四可见面零明文。
4. 两端定位按平台现实切分：**安卓端承载全部执行能力；鸿蒙端承载快路径子集 + 审批终端**（平台权限约束见 §3.4，非工程取舍）。

**非目标（本轮不做）**
- 不自研硬件/屏幕串流/ADB 驱动层。我们的链路是「后端 → 手机 App → 系统能力」，比「电脑 → 调试桥 → 手机」短，无需重资产。
- 不做 iOS。
- 不对抗应用的反自动化检测；金融/密码管理类应用默认隐身。
- 不做「通知 → 记忆沉淀」（另案评估，见 D6）。
- 鸿蒙端不做越权注入；权限不满足的能力诚实标 `not_supported`，退「审批终端 + 提醒」形态。

## 2. 总体架构

```
Agent 决策（ToolExecutor 单一转交点 tool_executor.py:1867）
   └─ device_* 工具组（schema 单源 builtin_tools.py + 执行包 neurova/device_bridge/）
         │ ① 选设备：在线设备 × 能力快照（device:hello 上报）
         │ ② 治理门：风险分级（runtime_policy）→ 审批 / 熔断 / 审计
         │ ③ 幂等登记：mobile_ws_ledger.beginCommand（mobile_ws_commands 表）
         ▼
移动 WS 通道 /api/v1/mobile/ws（出站帧先落账再发，断线 sync_resume 重放）
   ├─ 直连：手机 ↔ 后端
   └─ 中继：手机 ↔ relay ↔ TunnelAgent ↔ 127.0.0.1:9527（帧透明搬运，relay 零改动）
         ▼
手机端 DeviceBridge 模块
   ├─ 安卓：FGS 常驻连接 + 能力执行器层 + AccessibilityService 屏幕执行器 + NotificationListener
   └─ 鸿蒙：应用级连接管理器 + 快路径执行器（剪贴板/打开URL/设备信息）+ 审批卡
         │  device:result / device:event 回传（同帧族、同账本、同幂等）
         ▼
结构化结果（action_result 契约）→ 回写会话 + H-4 留痕 + 前端/移动端呈现
```

**职责切分**：后端只做决策与治理（选设备、选能力、判风险、记账、判定终态）；手机端只做执行与上报（不自判该不该做——风险判定单源在后端治理链）。

## 3. 现状剖析（代码级事实，四路勘察结论）

### 3.1 后端移动通道：设备桥底座已存在，缺的是「服务端主动下发」半边

- **WS 端点与鉴权**：`/api/v1/mobile/ws`（`neurova/api/endpoints/mobile_pairing.py:1841`）。三通道鉴权（:1841-1899）：一次性 `connect_ticket`（Bearer 头，HMAC 自定义格式，签发 `_issueConnectTicket` :444-458、三验 `_consumeConnectTicket` :461）→ 旧 `?token=` → 已确认配对码；凭证通道加在册判定 `isAdmissible(pairing_id, epoch)`（:1890，吊销即 4001 `device_deregistered`）。
- **账本三件套**（`neurova/api/mobile_ws_ledger.py`）：①连接 epoch（`mobile_ws_epochs`）；②出站事件账本（`mobile_ws_events`，帧**先落账再发送**并注入 `seq/epoch`，每设备保留 500 帧 :55，`sync_resume{last_seq}` 按游标补发 `replaySince` :282，越权 scope 403 fail-closed）；③**指令账本 `mobile_ws_commands`**（:94-104，复合主键 `(pairing_id, command_id)`，`beginCommand` :323 三态幂等——新指令登记 running / 同 id 运行中回 `command_already_running` 冲突帧 / 已收敛回放原终态帧附 `replayed:true`；`settleCommand` :369 落终态）。**当前只对入站 `chat:send` 记账**（mobile_pairing.py:2015-2032）——扩展为双向是设备桥最短的挂载路径。
- **服务端主动扇出点已存在但零调用**：`MobileConnectionManager.send_to_user`（mobile_pairing.py:597，按 user_id 向该用户全部连接发帧）与 `broadcast`（:611）现无外部调用方——正是 §2 断点条款意义上的「已接线能力、缺消费方」，设备桥接上即闭环。
- **设备表**：`mobile_devices`（`neurova/core/mobile_device_store.py:37-51`：pairing_id PK / user_id / device_name / device_type / device_id / state / token_epoch / paired_at / last_active / revoked_at / secret_hash v2）。**无 capabilities / platform / protocol_version 列**；v2 迁移范式现成（:55-67 callable ALTER TABLE + `register_migration`）。
- **身份链**：移动聊天轮次在 `_handle_chat_send` 内 `set_request_user_id(user_id)`（mobile_pairing.py:943-945）；会话属主经 `resolveSessionOwner`（post_chat_pipeline.py:138-164）落到设备属主。设备桥命令沿用同一身份通道，命令归属 = 配对设备属主。
- **推送**：`neurova/notifications/push_sender.py` 信令-only（`buildSignalingPayload` :93 只发 `{notificationId, notificationType}`），android→FCM、harmony→华为 Push Kit，`pushNotificationToUser` :225 按用户全部设备扇出；在线走 WS 直推、离线走推送信令、正文回拉。
- **现成缝隙**：`tool_executor._emit_computer_event`（tool_executor.py:9285-9406）把 `computer_action` 事件经 `SessionSyncManager.broadcast_event`（session_sync_manager.py:714）推给注册在 `/api/v1/sync/ws/{session_id}` 的渠道——**移动 WS 未注册为该管理器渠道，而安卓端已实现 `computer_action` 帧解析与主机确认/审批卡（MobileWsChannel.kt:412-432）**：客户端就绪、服务端未接线的典型断点。
- **中继零改动**：relay 对 WS 帧逐条透明搬运（`neurova/relay/app.py` proxyWs :468-510；`neurova/tunnel/agent.py` `_pumpWebSocket` :410 透传到本机环回），新增消息族不需要改 `neurova/relay/` 与 `neurova/tunnel/`。

### 3.2 后端工具管线：新工具组有固定接入路径，治理件全部现成

- **schema 单源**：`neurova/builtin_tools.py:31` `_BUILTIN_SCHEMAS`；声明位键：`capability`（readOnly/concurrentSafe/writeScopes，:263-265）、`interactive_desktop`（:263）、`sandbox_required`（:2518）、`arbitrary_command`/`remote_execution`（:2832-2836）、`runtime` 超时（:2418-2458）。
- **执行咽喉**：`ToolExecutor.execute`（tool_executor.py:1867）→ `tool_call_journal.executeWithJournal`（:1895；SQLite 表 `core/tool_call_journal.py:52`，天然留痕）→ `_execute_single_tool` :2184（子代理白名单门 :2193-2218 → PreToolUse hooks :2220-2245 → span）→ `_execute_tool_core` :2591 → `_builtin_dispatch` 方法表（:1014-1138）→ `_execute_builtin_tool` :3768（门序：参数归一 → 运行档门 → 租约 → 审计）。
- **结果契约现成**：`neurova/computer_use/action_result.py:106` `build(route, effect, delivery, evidence, refusal_code, action_sent, retry)`，封闭词表越界即抛；便捷档 `confirmed` :171 / `refused` :175 / `unverifiable` :186。设备桥结果直接复用该契约（新增 route 字面量 `device`）。
- **治理门现成**：`neurova/computer_use/runtime_policy.py:137` `decide_desktop(mode, tool_name)`（风险三档 `classify_risk` :128 由声明面投影 × 运行档 full/sandbox/review/auto → proceed/require_sandbox/require_approval）；车道互斥 `get_lane_mutex().hold(DESKTOP_LANE, …)`（computer_use/actions.py:33-37，被拒返回结构化 `lane_busy`）；桌面审计 `_record_desktop_audit`（tool_executor.py:3840）。
- **成员过滤**：`MAIN_AGENT_ONLY_TOOLS`（builtin_tools.py:2631-2636）→ 派生期剔除（swarm.py:194-226 `computeSubagentToolAllowlist`）+ 执行期结构化拒绝（tool_executor.py:2205-2218）+ 目录投影（tools/catalog.py:87-109）三处自动生效。
- **H-4 留痕**：逐 run JSONL `neurova/agent/swarm_event_log.py:83-109` `appendRunEvent`（per-file 单调 seq）+ 全局 SQLite 镜像 `neurova/agent/swarm_event_store.py`（`swarm_events` 表 :59-79 带 `tenant_id`，`append` :174，按 event_id 幂等双写）。
- **租户判据**：`neurova/core/tenant_scope.py`（`resolve_tenant` :19 / `tenant_matches` :32 / `tenant_sql_where` :43）；设备端点注册表先例 `neurova/remote_exec/registry.py`（自然键 `(tenantId, ownerId, kind, name)` :8,:71）；WS 订阅腿校验 `_scopeKeyAdmissible`（mobile_pairing.py:1809，键必须在本设备账本帧中出现过，否则 403）。
- **迁移范式**：`neurova/core/db_migration.py:34` `register_migration(version, step, domain)`，PRAGMA user_version 递增点 :132/:142；范本 `core/mobile_device_store.py:37-67`。

### 3.3 安卓端（Mobile/android-native）：连接层成熟，执行面完全空白

- **可复用**：`core/net/MobileWsChannel.kt` OkHttp WS（:16-20）+ 应用层心跳 30s/pong 超时 10s（:232-259）+ 退避重连 base 1s/cap 16s/上限 10 次（:261-296, :522-531）+ **4001 续签自愈**（`MobileWsClosePolicy.kt:23-24` REFRESH_AND_RETRY，执行 :275-287）+ relay `nv1` HMAC 首帧（:505-518，`TunnelTokenSigner.kt:36-46`）+ `sync_resume` 游标补拉（:215-226）。密封事件 Flow 分发大 `when`（:346-451）；审批/确认卡结构 `core/protocol/ToolActionEvents.kt:20-37`；凭据 EncryptedSharedPreferences（`core/store/CredentialStore.kt:18-29`，SecureVaultCredentialStore :37-87）；配对双入口闭环（扫码 `neurova://pair?ref=` + 6 位码，`PairingStore.kt`）。
- **空白**：全仓**无** Foreground Service / WorkManager / AlarmManager / AccessibilityService / NotificationListenerService / 通知渠道 / FCM / 剪贴板 / 日历 / 联系人 / 应用列表代码；Manifest 仅 `INTERNET`+`CAMERA`（AndroidManifest.xml:3-4）。WS 是「发消息才连」的惰性连接（ChatSessionController.kt:131,221-233），退后台无常驻保障。
- **既有先例**：打开 URL 的 `ACTION_VIEW` 用法一处（feature/aigc/AigcScreen.kt:516）；「我的」页设备分区 InfoRow 模式（ProfileTabScreen.kt:133-138）；`neurova://pair` 深链在 Manifest 声明但 MainActivity 未消费（MainActivity.kt:17-32 无 onNewIntent）——扫码授权能力需先补上。

### 3.4 鸿蒙端（Mobile/harmony）：连接可靠性设施完整但挂错位置，平台权限更紧

- **可复用**：`libs/adapters/WebSocketAdapter.ets` 单例——Bearer ticket 头（:217-221）、relay `/t/` 判定与 auth 首帧（:179, :529-552）、心跳 30s 可被 `connection_runtime` 契约覆盖（:447-449, :639-650）、退避 `min(0.5s*2^n,30s)`±20% 上限 10 次（:668-708）、4001 续签 / 4401·4403 停连（:341-363）、`sync_resume` 补拉与快照重同步（:558-632）。帧型单源 `libs/types/index.ets`（`WSMessageType` :220-238；信封 `WSMessage` :241-247 带 `seq/epoch/replay`；`WSChatSend` 已有 `command_id` 幂等 :281-292）；EventBus 发布-订阅分发（`typeToEvent` :409-515）。已有能力：剪贴板 pasteboard（PlatformAdapter.ets:202-248）、扫码 ScanKit、deviceInfo（:102-134）、网络状态。配对闭环完整（深链 `neurova://pair` 已消费，EntryAbility.ets:22-46 PendingDeepLink；`TunnelToken.ets`/`TunnelTokenCrypto.ets` relay 认证帧）。
- **缺口**：WS 生命周期挂在 ChatPage（ChatPage.ets:336-361 `aboutToDisappear` 断连）——无应用级连接管理器；无 backgroundTaskManager/长时任务（module.json5:43-76 仅 INTERNET/GET_NETWORK_INFO/CAMERA/MICROPHONE 四权限）；无 NotificationKit/Push Kit/Live View Kit（PushApi.ets:25-37 仅令牌上报桩）；无 startAbility 打开 URL/App、日历、联系人、应用列表代码。
- **平台硬约束（勘察实证，非推测）**：监听他应用通知需 `NOTIFICATION_CONTROLLER` 等 system_basic 级权限，三方应用拿不到——**通知读取能力在鸿蒙端不可行**；后台常驻需按「数据传输」场景申报长时任务且受系统管控；后台 `startAbility` 唤起他应用受限；后台读剪贴板有前台判定限制。⇒ 鸿蒙端执行能力 = 快路径子集（前台优先）+ 审批终端。

### 3.5 参照机制（aico-link，只借鉴机制不搬代码）

1. **能力协商 + 运行前过滤**：每次 agent 运行前按设备实时能力过滤工具目录；后台不可靠能力显式降级并返回结构化错误（其 `app_backgrounded` 语义）。
2. **持久化命令队列 + 唤醒信令分离**：命令先持久化入队，唤醒通道只传「有活干」的提示，不携业务内容；唤醒失败不丢已入队命令。
3. **本地任务面板**：任务状态经系统级卡片透出（其 Live Activity/灵动岛；我们对应安卓 FGS 通知 / 鸿蒙 Live View Kit）。
4. **通知事件环 → 空闲沉淀**：通知先进内存环，空闲窗口批量持久化与抽取（本计划只做「采集上报」，沉淀入库另案 D6）。

## 4. 目标协议：设备桥帧族（单源落 `neurova/tunnel/protocol.py`）

新增帧类型（命名对齐既有 `chat:*` 风格，字面量加入 protocol.py 帧型清单 :149-163 同层）：

| 方向 | 帧型 | 关键字段 | 说明 |
| --- | --- | --- | --- |
| 手机→后端 | `device:hello` | `platform, os_version, app_version, capabilities[], app_state, device_env` | 连接建立后与能力变化时上报（能力快照 + 运行态） |
| 后端→手机 | `device:execute` | `command_id, action, payload, timeout_ms, intent, risk` | 单条设备命令；`command_id` 全局幂等键 |
| 后端→手机 | `device:cancel` | `command_id` | 取消在途命令 |
| 手机→后端 | `device:result` | `command_id, status, data, error, action_result` | 命令终态回执；驱动 `settleCommand` |
| 手机→后端 | `device:event` | `event_kind, items[], seq` | 主动上报：通知批次 / 执行过程事件（有界） |

- **能力词表（封闭集，单源定义）**：`open_url / open_app / clipboard_read / clipboard_write / app_list / device_env / notification_read / screen_observe / screen_gesture / calendar_read / calendar_write / contacts_read`。安卓端宣称全集（除日历/联系人首批不做）；鸿蒙端宣称 `open_url / clipboard_read / clipboard_write / device_env`（快路径子集）。
- **app_state 协商语义**：`foreground` / `background`。后台不可靠能力（`clipboard_read`、`open_app`、`screen_*`）在 `app_state=background` 时端上直接回结构化 `capability_unavailable_in_background`，后端运行前过滤器据此把对应工具从本轮目录剔除——对齐 aico 的「运行前能力过滤」。
- **可靠性**：出站 `device:execute` 走 `LedgerWs` 同一出口先落账获 `seq`（断线重放天然覆盖）；`device:result` 驱动 `settleCommand` 落终态；同 `command_id` 重发由 `beginCommand` 三态幂等拦截；端上另做一层近期 `command_id` LRU 去重（防重连重放导致重复执行）。

## 5. 实施卡

### 批一 P0：通道与快路径闭环（后端 B1–B3 + 安卓 A1–A3 + 鸿蒙 H1–H3）

**B1 设备能力注册与快照（后端，S）**
- 断点：`mobile_devices` 无 capabilities/platform 列（mobile_device_store.py:37-51）；服务端不了解设备能做什么。
- 改什么：v3 迁移加 `platform / protocol_version / capabilities_json / app_state / last_hello_at` 列（`register_migration(3, …, domain="mobile_devices")`，范式 :55-67）；WS 循环（mobile_pairing.py:1920-2062）新增 `device:hello` 处理分支，更新设备行；REST 只读面 `GET /api/v1/mobile/pairing/devices/{pairing_id}/capabilities`（JWT+属主）。
- 验收：红灯=连接后不报 hello 时 capabilities 列为空、工具目录过滤后 device_* 全部不可见；绿灯=hello 后能力按端型正确落库、REST 可读、跨用户 403。live-verify：真后端 9527 两台模拟端分别报不同能力。
- 工作量：S（1 天）。

**B2 设备桥帧族与双向幂等账本（后端，M）**
- 断点：帧型清单无 device:*（tunnel/protocol.py:149-163）；`beginCommand/settleCommand` 只服务入站 chat:send（mobile_pairing.py:2015-2032）；`send_to_user` 零调用方（:597）。
- 改什么：protocol.py 加五帧型与能力词表常量（单一事实源）；`mobile_ws_ledger` 增 `beginOutboundCommand(pairing_id, command_id, cmd_type, payload)`（复用同表，status 语义不变）与 `settleFromResult`；WS 下行循环加 `device:result`/`device:event` 分发（回执 → settleCommand → 唤醒等待中的工具协程；事件 → 通知读取暂存）。`device:execute` 经 `send_to_user` 下发前先落账。
- 验收：红灯=同 command_id 二次下发被 `command_already_running` 拦截；回执到达后命令终态落库；断线重连 `sync_resume` 能补到未送达的 execute 帧；绿灯=上述全绿且既有 chat:send 幂等回归零变化。live-verify：模拟 WS 客户端全链对拍。
- 工作量：M（2–3 天）。

**B3 `device_*` 工具组与执行包（后端，L）**
- 断点：agent 无任何指挥手机的工具面。
- 改什么：新包 `neurova/device_bridge/`——`router.py`（按 user_id→在线设备选择 + 能力校验 + `send_to_user` 派发 + 带超时等待 `device:result` 的 asyncio Future 表）、`actions.py`（open_url/open_app/clipboard_read/clipboard_write/app_list/device_env/notification_read 的载荷构造与结果归一）、`errors.py`（`device_offline / device_timeout / capability_unsupported / capability_unavailable_in_background / device_busy` 结构化错误）。builtin_tools.py 声明 `device_open_url / device_open_app / device_clipboard_read / device_clipboard_write / device_app_list / device_device_env / device_notification_read` 七工具（带 `remote_execution`、`runtime.default_timeout_ms`、只读类标 `capability.readOnly`）；`_builtin_dispatch` 加方法表；结果统一附 `action_result`（action_result.py `build` 新增 route 字面量 `device`）。设备离线→诚实 `device_offline`（不重试沉默失败）。
- 验收：红灯=七工具在无设备/离线设备/能力未宣称三种情况下分别返回结构化错误而非挂起；绿灯=在线设备往返成功且结果进会话 tool_result。live-verify：真后端 + 模拟手机 WS 客户端跑通 `device_open_url` 全链。
- 工作量：L（3–4 天）。

**A1 安卓 DeviceBridgeService 常驻连接（安卓，M）**
- 断点：WS 惰性连接、退后台无保障（ChatSessionController.kt:131,221-233）；无任何 Service（§3.3）。
- 改什么：新增 `core/service/DeviceBridgeService.kt`（Foreground Service，`dataSync` 类型）持有 MobileWsChannel 常连；常驻通知渠道 + 通知；Manifest 加 `FOREGROUND_SERVICE`/`FOREGROUND_SERVICE_DATA_SYNC`/`POST_NOTIFICATIONS`；ProcessLifecycleOwner 前后台切换策略（后台不断连，靠 FGS 存活）。
- 验收：App 退后台 5 分钟后 WS 仍在线（心跳帧持续）；杀服务后重连恢复；绿灯=既有聊天链路零回归。
- 工作量：M（2 天）。

**A2 安卓设备桥协议接入（安卓，S）**
- 改什么：新增 `core/protocol/DeviceBridgeEvents.kt`（仿 ToolActionEvents.kt 承载 `device:execute/cancel` 解析与 `device:result` 构造）；`MobileWsChannel` 的 when（:346-451）加分支与上行发送 API；执行器侧 `command_id` LRU 去重（防重连重放重复执行）。
- 验收：单测覆盖帧解析往返；重放同一 execute 帧只执行一次。
- 工作量：S（1 天）。

**A3 安卓快路径能力执行器（安卓，M）**
- 改什么：新包 `core/capability/`——`CapabilityExecutor` 接口（`canHandle(action)/execute(payload): Result`）+ `OpenUrlExecutor`（Intent ACTION_VIEW/深链，先例 AigcScreen.kt:516）+ `OpenAppExecutor`（包名/Intent，getLaunchIntent）+ `AppListExecutor`（PackageManager 查询，应用名/包名白名单过滤）+ `DeviceEnvExecutor`（电量/屏幕/语言/网络）+ `ClipboardExecutor`（ClipboardManager）。`DeviceBridgeDispatcher` 按 action 路由、按 `app_state` 预判后台不可靠能力并直接回 `capability_unavailable_in_background`。能力清单经 `device:hello` 上报。
- 验收：模拟器上 agent 下发 `open_url`（打开设置）与 `device_env`（读电量）往返成功；后台态剪贴板读取返回结构化不可用而非挂起。
- 工作量：M（2–3 天）。

**H1 鸿蒙应用级连接管理器（鸿蒙，M）**
- 断点：WS 挂在 ChatPage 生命周期，离页即断（ChatPage.ets:336-361）。
- 改什么：抽 App 级 `DeviceBridgeConnection.ets`（单例，EntryAbility onCreate 启动 / onForeground-onBackground 管理，EntryAbility.ets:108-114 现仅打日志）；ChatPage 改为订阅该单例而非自持（连接参数仍取 AuthStore，ChatPage.ets:771-790 同源）。
- 验收：离开聊天页 WS 不断；重进页面不重建连接；既有聊天功能零回归。
- 工作量：M（2 天）。

**H2 鸿蒙设备桥协议接入（鸿蒙，S）**
- 改什么：`libs/types/index.ets` `WSMessageType` 加 device:* 族（:220-238 同层）；`WebSocketAdapter.typeToEvent`（:409-515）加映射；EventBus 新事件；`command_id` 去重。
- 验收：帧解析单测；与后端联调往返成功。
- 工作量：S（1 天）。

**H3 鸿蒙快路径执行器（鸿蒙，M）**
- 改什么：`libs/capability/` 新包——Clipboard（已有 pasteboard 封装 PlatformAdapter.ets:202-248，直接复用）、OpenUrl（`context.startAbility` + want http/https；后台限制→前台态才执行，否则 `capability_unavailable_in_background`）、DeviceEnv（deviceInfo + 网络状态，PlatformAdapter.ets:102-196 复用）；应用列表经 bundleManager 探测，受 `GET_BUNDLE_INFO_PRIVILEGED` 限制时能力探测失败→**宣称能力时即不含 `app_list`**（诚实边界，不做假实现）。能力清单经 `device:hello` 上报。
- 验收：真机/模拟器 open_url、clipboard 往返成功；未宣称能力被后端过滤（目录里不出现）。
- 工作量：M（2 天）。

**批一验收总门**：真后端 + 真机（安卓模拟器起步）端到端——agent 一句话「打开设置，把屏幕亮度调低前先告诉我电量」→ `device_device_env` 返回电量 → `device_open_url` 打开设置；全程命令幂等、断线重放不重复执行、离线设备报 `device_offline`。

### 批二 P1：屏幕执行器与治理（安卓 A4–A7 + 后端 B4–B5 + 鸿蒙 H4–H5）

**A4 安卓 AccessibilityService 屏幕执行器（安卓，L）**——本计划核心卡
- 改什么：`core/accessibility/ExecutorAccessibilityService.kt`（读屏：节点树→`{ref, role, label, bounds, state}` 投影；动作：`performAction`/`dispatchGesture` 实现 tap/swipe/type）；Manifest 声明 + `BIND_ACCESSIBILITY_SERVICE` + `accessibility-service.xml`；**按需开关**（任务窗口开启 / 结束·接管·闲置 60s 关闭，状态经 `device:event` 上报）；**凭据防线**：密码/验证码输入框类型识别→拒绝注入（`credential_field_blocked`），验证码文本出端前打码（关键词+数字形态，排除电话/金额/日期），敏感应用名单隐身（无元素、无截图、通知遮罩）。
- 验收（红线判据）：密码/验证码在 屏幕投影、截图、H-4 账本、后端日志 四处均不可见；任务结束后无障碍服务自动关闭；模拟器跑通「读屏→点击→回报」。
- 工作量：L（4–5 天）。

**A5 安卓 NotificationListenerService（安卓，M）**
- 改什么：`core/notification/NeurovaNotificationListener.kt` + `BIND_NOTIFICATION_LISTENER_SERVICE` 权限；通知事件环（内存有界）→ `device:event{event_kind:"notification_batch"}` 有界批次上报（脱敏：默认只报 app 包名/标题/时间，正文按能力开关）；用户可按应用白名单。
- 验收：通知到达→后端收到批次；白名单外应用不上报；账本无敏感正文明文。
- 工作量：M（2 天）。

**B4 治理接线：风险分级 / 审批 / 熔断（后端，L）**
- 改什么：①`runtime_policy` 增加 device 域风险投影（`screen_gesture`/`notification_read`=high，`clipboard_read`/`app_list`=medium，`open_url`/`device_env`=low；复用 `classify_risk` :128 的声明面投影，不另起分类器）；②`require_approval` 走既有 approval_chain，审批请求经 `chat:approval_required` 帧到手机审批卡（两端卡片组件已有：安卓 ToolActionEvents.kt:20-37、鸿蒙审批卡）+ 桌面 SSE（console.py:675），**超时即拒**；③熔断：每 run 维护步数/时长计数（内存 + run 台账），超限结构化拒绝 `device_budget_exhausted`，理由入账。
- 验收：一次高风险动作被扣住→手机批准→仅该次放行；超时自动拒；人为触顶熔断即停且手机端无残留操作。
- 工作量：L（3–4 天）。

**B5 留痕与审计（后端，S）**
- 改什么：`device:execute/result` 落 H-4（`appendRunEvent` swarm_event_log.py:83-109 + `SwarmEventStore.append` 镜像带 `lineage.tenant_id`）；工具级 span 与 `tool_call_journal` 经执行咽喉自动覆盖（零额外代码）；新增 `device_audit` 事件型（动作/目标/风险/审批 id，不含敏感明文）。
- 验收：任意一步可事后回放；账本抽查无凭据明文；跨租户读不到他租户事件（tenant_id 段）。
- 工作量：S（1 天）。

**A6 授权与体检页（安卓，M）**
- 改什么：「我的」页设备分区（ProfileTabScreen.kt:133-138）新增「设备桥」入口→`feature/devicebridge/DeviceBridgeScreen.kt`：逐能力授权开关（持久化，默认全关）、无障碍/通知监听/电池优化体检引导（分品牌 ROM 菜单名）、实时连接与能力状态显示。
- 验收：新装机按体检页指引一次走通；关闭某能力后后端目录即时收敛（hello 重报）。
- 工作量：M（2 天）。

**A7 执行进度通知（安卓，S）**
- 改什么：FGS 常驻通知承载任务进度（标题/步骤/状态，复用 `device:event` 进度事件），对齐 aico「高价值转换才提醒、普通进度静默更新」。
- 验收：任务进行中通知栏可见进度；完成/失败/待审批三态有区分。
- 工作量：S（1 天）。

**H4 鸿蒙审批终端强化（鸿蒙，M）**
- 改什么：审批卡接 device 域审批请求（复用既有审批卡组件与 `chat:approval_required` 链路）；通知触达评估（本地通知 NotificationKit 起步；Push Kit 真接入与 AGC 配置列为评估项，PushApi.ets:25-37 桩位就绪）。
- 验收：安卓侧发起的高风险操作，鸿蒙端可收到审批卡并完成批准/拒绝往返。
- 工作量：M（2 天）。

**H5 鸿蒙授权入口（鸿蒙，S）**
- 改什么：SettingPage 分组（:170-255）新增「设备桥」组：能力授权状态展示 + 连接状态；不做执行器能力（平台约束）。
- 工作量：S（1 天）。

**批二验收总门**：安卓真机完整任务「打开设置→读屏找到电池项→点击→截图回报」全程 审批+留痕+熔断待命+凭据零明文；鸿蒙端完成同一 run 的审批往返。

### 批三 P2：触达与扩展（B6–B7 + A8 + H6 + 两项评估）

- **B6 REST/MCP 读面（S）**：`GET /mobile/pairing/devices/{id}/capabilities`（B1 已含）+ MCP 只读 `device_status`（mcp_agent_tools_server.py 加 `@_SERVER.tool`，复用 `_resolveIdentity`/`_boundedPayload`，挂载点 app.py:1844 现成）——给外部编码代理查询设备能力用。
- **B7 离线唤醒闭环（M）**：命令下发遇设备离线→命令入账待执行 + `push_sender` 发信令（push_sender.py:225 现成）→ 端上收到信令拉起连接 → `sync_resume` 补拉到 execute 帧 → 执行回执。验收：离线手机收到 FCM 信令后自动补执行队列中的命令。
- **A8 深链消费补全（S）**：MainActivity `onNewIntent` 处理 `neurova://pair`（现状声明未消费，MainActivity.kt:17-32）——扫码授权/重新配对场景。
- **H6 鸿蒙 Live View Kit 任务面板（评估卡）**：评估接入成本与上架约束，产出结论后再决定是否实施。
- **日历/联系人（评估卡）**：两端权限敏感（安卓 runtime 权限、鸿蒙 CalendarKit/ContactKit），产出权限代价与产品价值评估后拍板。

## 6. 安全与隐私红线（贯穿三批，任何一卡回归都复测）

1. **凭据四可见面零明文**：屏幕投影、截图、事件账本、后端日志四处均不得出现密码/验证码明文；验证码出端前打码。
2. **无障碍服务绝不常开**：任务窗口开启、结束/接管/闲置 60s 关闭；后台唤醒仅限任务窗口。
3. **操作可归因**：所有高风险执行必须能追溯到一次审批决定；无审批的高风险执行视为事故。
4. **数据最小化**：截图按需索取、账本存引用不存原图、保留期对齐 S17 归档策略。
5. **用户随时接管**：两端提供「停止/接管」入口，接管后 agent 侧调用立即挂起。
6. **租户隔离**：命令归属 = `(tenant_id, user_id, pairing_id)` 三段；`send_to_user` 按 user 扇出天然隔离；账本行带 `tenant_id`；跨用户/跨租户访问一律 403/404，不泄露存在性（对齐 `_scopeKeyAdmissible` :1809 判据）。
7. **能力默认关**：后端总闸 `NEUROVA_DEVICE_BRIDGE_ENABLED`（默认 off）× 端上逐能力授权（默认全关）双闸；未配对/未授权设备在工具目录中不可见。
8. **AGPL 边界**：aico-link 为 AGPL 双许可，只借鉴机制与契约形态，禁止搬运其代码与注释。

## 7. 待拍板（每项含影响面与推荐项）

> **拍板记录（2026-11-23）**：用户指令「严格按照教义，开始施工」——D1–D7 全部**按推荐项执行**（D1=A 复用移动 WS 帧族 / D2=A 屏幕执行器仅安卓 / D3=A 全量读取+端上白名单授权 / D4=能力默认关双闸+审批档按建议 / D5=50 步·10 分钟·token 保证金口径 / D6=通知记忆另案 / D7=鸿蒙后台保活先不申报、推送信令兜底）。本节保留原文备查。

| # | 问题 | 选项与影响面 | 推荐 |
| --- | --- | --- | --- |
| D1 | 命令通道形态 | A. 复用移动 WS 帧族：账本/重放/鉴权/中继全部现成，改动最小；代价=端上必须维持常连（A1/H1 已解）。B. 独立 HTTP 命令队列端点（aico 形态）：后台存活更稳、可独立扩容；代价=新端点+新鉴权+端上轮询器，与 WS 账本形成两套命令事实源，违背单一事实源 | **A** |
| D2 | 屏幕执行器范围 | A. 仅安卓（鸿蒙 AccessibilityExtensionAbility 对三方收口，平台不可得）。B. 两端强行对齐=鸿蒙做假实现或越权，违背诚实边界 | **A** |
| D3 | 安卓通知读取范围 | A. 全量读取+端上白名单过滤。B. 仅白名单应用。影响面：A 覆盖广但隐私面大；B 隐私最小但需用户逐个配置 | **A（默认全关+白名单授权，隐私控制放在授权层）** |
| D4 | 默认开关与审批档 | 设备桥总闸默认 off + 端上能力默认全关；审批档：screen_* 一律 require_approval、clipboard_read/notification_read 默认 require_approval、open_url/device_env auto | **按此默认，灰度期不改** |
| D5 | 熔断阈值 | 步数/时长/费用三上限默认值（建议 50 步 / 10 分钟 / 沿用 token 保证金口径），可被 run 参数覆盖但不超 admin 上限 | **按建议值落地，阈值进配置单源** |
| D6 | 通知→记忆沉淀 | 本期只做采集上报；「通知事件环→空闲窗口→记忆抽取」是否立项（对齐 aico 机制 4）。影响面：涉及记忆准入与夜间引擎路线，另案评审更稳 | **另案，不在本计划立项** |
| D7 | 鸿蒙后台保活 | 按「数据传输」场景申报长时任务（KEEP_BACKGROUND_RUNNING）vs 不申报（退后台即断、靠推送信令唤醒）。影响面：前者体验好但需申报且可能被系统回收；后者实现轻但执行实时性差 | **先不申报，P1 用推送信令兜底；真机验证后若实时性不足再申报** |

## 8. 里程碑与总验收

- **P0（批一，约 1.5 周）**：B1→B2→B3→A1→A2→A3→H1→H2→H3。验收=快路径端到端演示（§5 批一验收总门）。
- **P1（批二，约 2 周）**：A4→A5→B4→B5→A6→A7→H4→H5。验收=屏幕执行器全链 + 安全红线判据全过。
- **P2（批三，按需）**：B6→B7→A8→H6/日历联系人评估。
- **总验收门**：①端到端演示任务（含一次被扣住→批准→放行的高风险操作、一次熔断触发）；②凭据四可见面零明文抽测；③断线重放不重复执行；④全量回归 A/B 零新增失败 + 真后端 9527 live-verify 证据入提交说明；⑤两端能力宣称与实际执行一致（无假能力）。

## 9. 与既有设施的关系（不新造平行体系）

- **审批**：复用 approval_chain L0–L2 与既有审批卡组件；手机端只是新增一种审批呈现与作答渠道。
- **留痕**：复用 H-4（swarm_event_log + swarm_event_store 镜像）与 tool_call_journal；设备命令是新的事件生产者。
- **幂等**：复用 mobile_ws_commands 账本与 beginCommand/settleCommand 原语（扩展方向，不改语义）。
- **推送**：复用 push_sender 信令-only 通道与 push_store 令牌库。
- **车道互斥/结果契约**：复用 lane_mutex（新增 DEVICE_LANE）与 action_result 词表（新增 route=device）。
- **帧型/schema/租户**：单源仍在 tunnel/protocol.py、builtin_tools.py、core/tenant_scope.py——本计划不新增任何第二事实源。

## 10. 执行记录

### 批一 P0（2026-11-23 当日实施完毕，三端全绿）

| 卡 | 落点 | 提交 |
| --- | --- | --- |
| B1/B2/B3 后端 | device_bridge 包、帧族单源、双向幂等账本、七工具、能力快照 v3 迁移、REST 读面 | 5d9da0a36（并行会话落地）+ 93f3405de（守卫收口：capability 声明/不可重现见证集/两份契约快照重生成） |
| A1-A3 安卓 | DeviceBridgeService 前台服务、DeviceBridgeEvents 协议、DeviceCommandDispatcher、六件执行器、DCL 单例装配 | 35785f760 |
| H1-H3 鸿蒙 | ChatPage 离页不再断连、device 帧族入总线、DeviceBridgeDispatcher、四件执行器、EntryAbility 装配 | e453b3b07 |

**验证证据**：
- 后端：device_bridge 47 用例全绿；守卫收口后 device_bridge+tools+computer_use+契约门+移动 WS 定向套件 2529 passed；live-verify 真后端全链 PASS（配对三步走→hello→账本 seq→ping/pong 契约→refresh 换票重连 sync_resume 补拉→REST 能力读面，启动日志 [ERROR] 计数 0）。
- 安卓：新增 11 用例（4+7）全绿；`:app:testDebugUnitTest` 全量 BUILD SUCCESSFUL（既有 WS 契约/心跳/续签/中继鉴权回归零新增失败）。
- 鸿蒙：hvigor assembleHap BUILD SUCCESSFUL（含既有 65 页全量编译）。

**批一遗留**：真机端到端演示（后端+安卓真机+真 agent 调用 device_env/open_url 全链）待 P1 首卡一并验；鸿蒙端 hello 上报依赖 ws:connected 事件，连接保活策略按 D7 先不申报长时任务。

### 批二 P1（2026-11-23 当日实施完毕，后端+安卓全绿、鸿蒙编译绿）

| 卡 | 落点 | 提交 |
| --- | --- | --- |
| B4/B5 后端治理 | device_bridge/governance.py（风险分级门/审批扣住/熔断）、tool_executor 设备治理分支、device_budget_exhausted 拒绝码、desktop_audit+H-4 device_action 留痕 | bb287d1e5 |
| A5 后端半边 | device:event 按设备 JSONL 入库 + 属主 REST 读面（notification-events） | 9142fc21b |
| A4/A5/A6/A7 安卓 | ExecutorAccessibilityService（读屏投影/手势注入/ref 寻址）、纯逻辑四件（ScreenModel/Guards/ExecutorGate/GesturePlanner）、NeurovaNotificationListener+事件环+白名单、DeviceAuthStore（默认全关）+DeviceBridgeScreen 授权体检页+Profile 入口、常驻通知进度 | 819572495 |
| H5 鸿蒙 | SettingPage 设备桥分组（连接状态+能力子集如实呈现）；H4 审批卡复用既有 chat:approval_required 链路（批五卡面，零新增代码） | e78a676b2 |

**验证证据**：
- 后端：治理 14 用例（策略映射/审批扣住/拒绝/超时/熔断步数与会话隔离/审计两落点）+ ingest 4 用例 + WS 集成（device:event→REST 读回）——device_bridge 全套 67 passed；device_bridge+tools 回归 1501 passed。
- 安卓：accessibility 13 用例 + notification 6 用例 + auth 4 用例全绿；`:app:testDebugUnitTest` 全量 BUILD SUCCESSFUL。
- 鸿蒙：hvigor assembleHap BUILD SUCCESSFUL。

**批二遗留**：A4 无障碍执行器的真机验证（系统设置授权→读屏→点击→凭据防线四可见面抽测）待真机批次；审批等待期间 WS 断线重连的审批单仍可经桌面端裁决（两通道同源，待联调验证）。

### 批三 P2（2026-11-23 当日实施完毕：后端+安卓全绿，模拟器真链路验证）

| 卡 | 落点 | 提交 |
| --- | --- | --- |
| 验证期根修 | 设备桥 WS 通道进程重启无法自愈（空票即 FAILED 且无重试来源）→ 空票自举（与 4001 同一收敛点先续签再握手）+ connect 幂等入口 + connectIfIdle + 配对就绪即连（snapshotFlow）+ hello 单源出口（AppRuntime.sendDeviceHello）+ 授权开关即时重报 | df8fc1668 |
| A8 安卓 | 深链 neurova://pair 消费：MainActivity singleTask + onCreate/onNewIntent 统一解析 → PairingStore.pendingDeepLinkRef → 配对页自动提交（扫码授权/重配对免手输） | 66715c06b |
| B6 MCP | 只读 device_status 工具（外部编码代理派发设备动作前的可达性读面）：listDevicesForUser 单源收口（REST /pairing/list 与 MCP 同一属主过滤与在线态投影） | 2315c47b5 |
| B7 后端 | 离线唤醒闭环：无在线连接 → 命令 beginCommand 入账 + execute 帧落设备账本（currentEpoch）+ push_sender 唤醒信令（device_command_pending，信令-only）→ 新拒绝码 device_offline_queued（retry=never）；hello 重投递 running 命令；回执经 settleRunningCommand 收敛（仅 running 收敛，迟到回执不改写终态） | c04d59e5f |
| B7 安卓 | WS 游标跨进程持久化（lastSeqRestore/lastSeqPersist 回调 + neurova.ws.last_server_seq 偏好）——进程被杀重建后 sync_resume 仍从断点补拉离线入队帧 | 839369f3d |
| 批二遗留清偿 | 审批扣住期间设备断线：WS 收尸对在途审批等待免取消（governance.hasInFlightApproval），批准后经离线入队 → 回连 hello 重投递照常执行；TestApprovalDisconnectResume 集成用例钉住 | b1f8671f9 |
| 批三遗留清偿 | 安卓 FCM 推送接收（NeurovaFirebaseMessagingService 只消费信令 → connectIfIdle 唤醒）+ PushTokenRegistrar 令牌注册（PUT /mobile/push/push-tokens）+ 登录态触发；Firebase 未配置时如实降级零崩溃 | ed9a5713b |

**验证证据（模拟器真链路，AVD neurova-tablet + 隔离数据根真后端 9527）**：
- 登录→六位码配对→WS 常连→hello 能力上报→能力授权页开关即时同步（免重连）全链走通；pairing/list 读得在线态与能力目录一致。
- 真 agent（nex-n2.6/moss）经 /v1/chat 调 device_env 全链：WS 账本 device:execute → App 16ms 回 device:result（电量/系统版本/屏幕/语言均为模拟器真值）→ 应答落会话归档；desktop_action_audit 落 device_env success=1。
- 无障碍执行器系统级启用（dumpsys accessibility Enabled services 在册），授权页体检三项全 ✓。
- B7：App force-stop（离线）→ 真 agent 调 device_env → 回复「命令已入队+唤醒信号已发」（device_offline_queued）→ App 重连 → hello 重投递 → 命令执行收敛（mobile_ws_commands running→settled，终态为设备真值）。游标跨进程持久化经 run-as 读 shared_prefs 实证。
- 后端：device_bridge 全套 72 passed；WS 账本/订阅/远程驾驶回归 75 passed；MCP 面测试 26 passed。安卓：`:app:testDebugUnitTest` 全量通过。

**批三遗留（如实登记，2026-11-23 二次更新：两项已清偿）**：
- ~~B7 的安卓端 FCM 接收器未实现~~ → **已实现**（ed9a5713b）：NeurovaFirebaseMessagingService 只消费信令（device_command_pending → connectIfIdle 唤醒）+ PushTokenRegistrar 令牌注册（PUT /mobile/push/push-tokens）+ 登录态触发。仓库尚无 google-services.json，运行期激活待 Firebase 凭据到位（到位即生效，无需改码）。
- ~~审批等待期间 WS 断线重连的审批单仍可经桌面端裁决~~ → **已验证**（b1f8671f9）：WS 收尸对在途审批等待免取消（governance.hasInFlightApproval 单源判据），批准后命令经离线入队 → 回连 hello 重投递 → 执行收敛；新增 TestApprovalDisconnectResume 集成用例钉住。
- A4 无障碍执行器的真机（非模拟器）验证仍待真机批次。
- ~~鸿蒙模拟器 HAP 装机验证~~ → **已完成**（2026-11-24）：Mate 90 Pro 模拟器全链走通（详见下方三次更新），深链配对→WS 常连→真 agent device_env 账本 settled 全部实证。

**批三遗留（2026-11-24 三次更新：鸿蒙真机验证进行中）**：
- **鸿蒙真机（HUAWEI SGT-AL10，5MT0226408057400）已走通**：HAP 构建+签名+安装+深链配对全链成功（hilog 实证「冷启动携带配对深链→直达配对页→消费配对深链→resolve 成功→配对成功」），App 登录 admin 后落在对话页；ledger 中两条 harmony 配对（pair-fea2967596fd / pair-c4665d0abaa5）均上报 caps=[open_url, clipboard_read, clipboard_write, device_env]。
- **验证环境事故已处置（非产品缺陷）**：隔离验证数据根（nv-e2e-root）的 `llm/providers.json` 被并行会话的后端进程改写，moss 服务商条目丢失（24→16 个），新拉起的后端读到无键服务商集，agent 对话即失败「[LLM Error] No client available」。处置：从真数据根回填 moss 条目（`enc:v2:` 密文自包含，`decrypt_api_key` 缺省空 master key 可解，无需迁移密钥文件）并重启后端；复验 `/v1/providers` moss `api_key_configured=true`，真 LLM 对话返回正常（LLM-OK 冒烟通过）。教训：跨会话共享的隔离数据根要么每会话独立复制，要么对 `llm/providers.json` 这类可变配置做写保护。
- **验证环境**：隔离根 admin 口令失忆，已在 users.db 重置 bcrypt 哈希恢复登录（测试夹具，非用户资产）。B6 MCP `device_status` 在重启后的后端复验通过（`/v1/mcp/agent-tools/` 注意尾斜杠，307 重定向）。
- **鸿蒙端真机发现的产品缺口（待修）**：WS 断线重连依赖 `WebSocketAdapter.reauthAndReconnect`（maxReconnect=10 指数退避），但 (a) App 退后台时 JS 定时器挂起，重连暂停；(b) 重试耗尽后适配器永久停摆，仅 `ChatPage.aboutToAppear` 重建页面才会重连——对比安卓端已有 snapshotFlow 就绪即连 + connectIfIdle 幂等入口，鸿蒙端缺前台恢复触发（候选：EntryAbility.onForeground → 适配器重连入口）。真机实测：App 退后台后 WS 断开，设备 offline 不再自愈。待真机在手时红绿修复。
- **当前阻塞**：真机 USB 连接掉线（hdc list targets=[Empty]，PnP 无 Huawei/Android 设备），device_env 真机执行待手机重新插线/亮屏。后端侧已全部就绪（LLM/登录/MCP/配对账本）。
- **鸿蒙模拟器真链路验证已完成（2026-11-24，用户指引用模拟器续做）**：Mate 90 Pro 实例（HarmonyOS 7.0.0.107，QEMU NAT，宿主经 10.0.2.2 可达）→ 签名 HAP 装机 → 深链配对（`neurova://pair?ref=…&host=http%3A%2F%2F10.0.2.2%3A9631`，hilog 实证「消费配对深链→终端档案就绪→resolve 成功→配对成功」）→ App 登录 admin 进对话页 → 进入会话视图触发 connectWs → 设备 online 且 hello 上报 caps=[open_url, clipboard_read, clipboard_write, device_env] → 真 agent（moss）chat 调 device_env → device:execute → 模拟器 3ms 回 device:result（os_version=OpenHarmony-7.0.0.105 / model=emulator / battery=1 / network_online=true）→ 账本 settled 终态 + desktop_action_audit success=1。**批三遗留「鸿蒙模拟器 HAP 装机验证」就此清偿**。
- **签名坑（值金）**：hap-sign-tool 参数为**全小写 `-keystoreFile/-keystorePwd`**；写 `-keystorePasswd`（大写 S/多写 ss）即报 `11011005 Param is not trusted`——连 `-h` 都会因参数校验次序先炸，须以无参调用看 `Check param num failed` 区分。已回写 `docs/10-configuration/MOBILE_APP_SIGNING.md` 同款命令。
- **待办移交**：鸿蒙端前台重连缺口（上述产品缺口）待真机在手时红绿修复；真机 device_env 待手机回插 USB 后补验（预期与模拟器同链路）。

### 评估结论（批三两项评估卡，2026-11-23）

**H6 鸿蒙 Live View Kit 任务面板：不实施。**
- 场景白名单是硬约束：实况窗仅支持即时配送/打车出行/排队/计时/航班/高铁/共享租赁/运动锻炼/导航九类场景，且取餐/打卡/快递等明确排除。「Agent 任务执行进度」不在白名单内，套用白名单场景属违规接 入，上架审核必拒。
- 权益约束：需先在华为开发者侧开通实况窗权益（liveview-rights），设备侧还需用户打开实况窗开关——引入一个非技术的外部审批依赖。
- 替代已覆盖：任务进度可见性由批二 A7 的常驻通知进度（含步数更新）承担，鸿蒙端走同一通知形态，无需实况窗。
- 后续如确要上：先过权益申请，再以白名单内场景形态（如导航式任务进度）另案评估。

**日历/联系人执行能力：有产品价值，隐私敏感度高，本期不实施，建议 P3 按设备桥既有模式另案立项。**
- 价值：agent 可答「明天有什么安排」「张三的电话」并代建日程——工作台场景的真实增量。
- 代价：安卓需 READ/WRITE_CALENDAR、READ/WRITE_CONTACTS 危险权限（运行时授权+商店申报）；鸿蒙 CalendarKit/ContactKit 需 user_grant 权限且部分接口属受限开放范围（需 ACL 申请）。
- 控制面：若立项，完全复用设备桥既有四层控制（总闸默认关 + 端上逐能力授权页 + 后端风险分级审批（读取类一律 require_approval）+ 审计留痕），新增成本集中在两端执行器与授权页扩项。
- 拍板建议：安卓日历读取先行试点，联系人与写入类能力次之，鸿蒙随平台权限可得性跟进。
