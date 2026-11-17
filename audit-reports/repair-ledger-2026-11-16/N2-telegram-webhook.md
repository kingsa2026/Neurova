# N2 · Telegram webhook 端点挂出（2026-11-17）

任务：把从未挂出的 Telegram webhook 管理面接成真实端点。会话 N2（新建能力批）。

## 0. 根因与现状（动手前勘查）

- `neurova/channels/telegram_webhook.py` 的 `TelegramWebhookMixin` 四方法
  （set_webhook / delete_webhook / get_webhook_info / verify_webhook_signature）
  **全仓零调用**——管理面是死码，`verify_webhook_signature` 已 fail-closed
  （hmac.compare_digest，无密钥拒绝，BUG AUDIT C-10 修过）却无人消费。
- `neurova/api/endpoints/channels.py` 的 `POST /{channel_type}/webhook` 分派链只认
  feishu/dingtalk/wecom/wechat 四支，telegram 落 `400 Unsupported`——
  **Telegram 的推送进不了本仓**。
- 处理入口现成：`telegram_adapter.py` 的 `_process_update(upd)`（轮询路径在用）。

## 1. 设计决策（勘查后拍板，含依据）

### 1.1 挂载位置：复用 channels 域既有 router

`neurova/api/endpoints/channels.py` 的 router 挂载于 `/api/v1/channel-adapters`
（`endpoints/__init__.py` 注册表 `("neurova.api.endpoints.channels", "/v1/channel-adapters")`）。
全部新路由按同构挂在这里，不另起文件：

| 方法 | 路径 | 鉴权 | 作用 |
|------|------|------|------|
| POST | `/api/v1/channel-adapters/telegram/webhook` | 签名（无登录态） | 接收 Telegram update |
| POST | `/api/v1/channel-adapters/{channel_type}/webhook/set` | requireAgentOwner | setWebhook |
| DELETE | `/api/v1/channel-adapters/{channel_type}/webhook` | requireAgentOwner | deleteWebhook |
| GET | `/api/v1/channel-adapters/{channel_type}/webhook/info` | requireAgentOwner | getWebhookInfo |

管理面用通用 `{channel_type}` 形态（与 restart/clear-queue 同构），能力检查兜底：
实例没有 set/delete/get_webhook_info 三方法 → 400 点名（404=实例不存在、400=渠道不支持，分开）。

模块头路由清单 docstring 已同步补记（`test_channelManagementFaceTakesAgent` 对真路由表
双向核对，少记一条即红）。

### 1.2 接收面鉴权：验签一道门，两处都核

- 多实例歧义消解：`inboundCredentialPredicate` 加 telegram 分支，谓词 =
  `adapter.verify_webhook_signature(headers)`（未配密钥返回 False，天然按密钥归属落实例）。
- **关键旁路封堵**：`resolveInboundAdapter` 在"唯一候选"时**不问谓词**直接放行——
  所以 handler `_handle_telegram_webhook` 内**无条件**再核一次签名，单实例部署
  也没有"不验签直投"的旁路。fail-closed：无密钥/坏签名一律 `ValueError` →
  沿用分派链既有映射 → **403**（与 feishu/dingtalk 同口径）。

### 1.3 _process_update 派发策略：create_task + to_thread 后台派发（决策记录）

勘查结论：`_process_update` 是同步方法；轻路径（文本）微秒级，重路径
（voice/audio → `fetchVoiceBytes`）是**同步 HTTP 下载**；事件回投走
`asyncio.run_coroutine_threadsafe(..., self._main_loop)`（telegram_adapter.py，
轮询线程已在用的同一线程安全通道）。

三个候选：直调（重活阻塞 FastAPI 事件循环，否）；`await to_thread`（下载时长算进
Telegram 的 2xx 等待，可能触发平台重试，否）；**后台派发（选定）**——
`asyncio.create_task(asyncio.to_thread(adapter.processWebhookUpdate, upd))`，
立即回 `{"ok": true}`。任务登记在模块级 `_telegramWebhookTasks`（防 GC），
done 回调除名并把异常记 warning（诚实暴露，不静默吞）。

配套两个小决策：
- `telegram_adapter.py` 增加公开入口 `processWebhookUpdate(upd)`（委托
  `_process_update`，单一实现两个名字都没有——就一个实现一个委托），把
  "可在任意线程调用"的线程安全契约写在公开入口的 docstring 里，也给测试
  稳定的 monkeypatch 面。
- `_main_loop` 缺失/未运行时，handler 借当前事件循环兜底绑定——webhook 模式
  不依赖 `connect()` 启动的 getUpdates 轮询（connect 失败的实例也能收推送）。

### 1.4 管理面取实例方式

`get_channel_manager().get_adapter(channel_type, agent_id=agent_id)`——实例表主键
`(agent_id, channel_type)`，`agent_id` 走 Query（缺省 default，`_norm_agent` 归一）。
门用 `requireAgentOwner`（agent_access 单源；default 无主 → 仅 admin），
与同 router 的 restart/clear-queue 完全同源，不新造第二把门。
mixin 三方法是同步 requests HTTP → `asyncio.to_thread` 下沉（S5 范本同款）。

## 2. 修复点（文件与行数）

| 文件 | 改动 |
|------|------|
| `neurova/api/endpoints/channels.py` | +151/−2：docstring 路由清单补 4 条；predicate telegram 分支；handle_webhook telegram 分派；`_handle_telegram_webhook` + 后台任务登记/回调；`WebhookSetRequest`；`_requireWebhookCapableAdapter`；管理三端点 |
| `neurova/channels/telegram_adapter.py` | +10/−0：公开入口 `processWebhookUpdate`（委托 `_process_update`，写明线程安全契约） |
| `neurova/channels/telegram_webhook.py` | +4/−3：`set_webhook` 的 `_webhook_url/_webhook_secret` 改为**仅 Telegram 侧 ok 后落地**（此前 API 失败仍写本地密钥，留下"本端验簘认、平台没配"的假状态） |
| `tests/unit/api/test_telegramWebhookEndpoints.py` | 新增 293 行：接收面 6 例 + 管理面 9 例 |
| `tests/unit/channels/test_telegramWebhookSetStateOnSuccess.py` | 新增 58 行：mixin 状态落点 4 例 |

净 LOC：生产池 +165/−5（仅 neurova/ 前缀口径）；测试 +351 行不计生产池。

## 3. 红绿证据（先红后绿）

**红灯**（实现前，`tests/unit/api/test_telegramWebhookEndpoints.py` +
`tests/unit/channels/test_telegramWebhookSetStateOnSuccess.py`）：

```
FAILED .../test_telegramWebhookEndpoints.py::TestTelegramWebhookReceive::testUnsignedPushRejectedAndNeverDispatched
FAILED .../test_telegramWebhookEndpoints.py::TestTelegramWebhookReceive::testBadSecretPushRejected
FAILED .../test_telegramWebhookEndpoints.py::TestTelegramWebhookReceive::testFailClosedWhenSecretNotConfigured
FAILED .../test_telegramWebhookEndpoints.py::TestTelegramWebhookReceive::testValidSignatureReachesProcessUpdateAndAnswersFast
FAILED .../test_telegramWebhookEndpoints.py::TestTelegramWebhookManagement::testNormalUserForbiddenOnAllThree
FAILED .../test_telegramWebhookEndpoints.py::TestTelegramWebhookManagement::testAnonymousForbiddenOnManagementFace
FAILED .../test_telegramWebhookEndpoints.py::TestTelegramWebhookManagement::testSetWebhookPassesArgsAndSuccessThrough
FAILED .../test_telegramWebhookEndpoints.py::TestTelegramWebhookManagement::testSetWebhookFailurePassesThrough
FAILED .../test_telegramWebhookEndpoints.py::TestTelegramWebhookManagement::testDeleteWebhookPassesFlagAndResultThrough
FAILED .../test_telegramWebhookEndpoints.py::TestTelegramWebhookManagement::testWebhookInfoPassesResultThrough
FAILED .../test_telegramWebhookEndpoints.py::TestTelegramWebhookManagement::testWebhookInfoNoneMeansFailure
FAILED .../test_telegramWebhookEndpoints.py::TestTelegramWebhookManagement::testUnsupportedChannelGets400Not500
FAILED .../test_telegramWebhookSetStateOnSuccess.py::...::testFailureKeepsPreviousState
13 failed, 6 passed
```

（6 个通过的是控制组：未注册 404、垃圾体拒收等既有行为；mixin 成功路径。）

**绿灯**（实现后同套件 + 邻居渠道契约/鉴权/路由冲突守卫）：

```
tests/unit/api/test_telegramWebhookEndpoints.py
tests/unit/channels/test_telegramWebhookSetStateOnSuccess.py
tests/unit/api/test_channelWebhookAuthBeforeDispatch.py
tests/unit/api/test_channelWebhookResolvesAdapterByAgentTable.py
tests/unit/api/test_channelManagementFaceTakesAgent.py     ← 路由清单双向核对
tests/unit/channels/test_telegram_split.py
→ 72 passed
tests/test_api/test_api_route_conflicts.py + _v2 + test_simple_route_fix.py
→ 14 passed
```

**A/B 自证**（预存失败不算回归）：`git stash push` 三个源码文件后同套件复跑
= **原 13 红逐一复现**（13 failed, 59 passed），`git stash pop` 弹回后 0 新增失败。
失败集合修复前后逐行一致，本笔零新增失败。

## 4. live-verify（真后端 9567，curl 十步原文）

起服：`NEUROVA_PORT=9567 NEUROVA_HOST=127.0.0.1 .venv/Scripts/python.exe start_server.py`
（代理变量已清）；判据过：`Application startup complete`、`Registered router: /v1/providers`
在案（日志仅有的 [ERROR] 是环境 MCP filesystem 连接失败，与本笔无关）。
token 用本仓 `neurova.api.auth.create_access_token` 同口签发（admin / 普通用户各一）。

```
== 1) 接收端点·telegram 未注册时 ==> 404
== 2) 建telegram渠道配置(admin) ==>
{"success":true,"channel_type":"telegram","agent_id":"default","message":"Channel 'telegram' configured and registered (agent=default)","needs_scan":false}  http:200
== 3) 接收·无签名头(未配密钥,fail-closed) ==>
{"detail":"Telegram webhook rejected: missing or bad X-Telegram-Bot-Api-Secret-Token"}  http:403
== 4) 接收·坏签名头 ==> 同上 403
== 5) 管理info·无token ==> 401
== 6) 管理info·admin ==>
{"success":false,"data":null,"channel_type":"telegram","agent_id":"default"}  http:200
== 7) 管理set·admin ==>
{"success":false,"channel_type":"telegram","agent_id":"default"}  http:200
== 8) 管理delete·admin ==> 同上 http:200
== 9) 管理info·普通用户(非属主) ==>
{"detail":"无权查询 Webhook智能体『default』（仅属主或管理员可操作）"}  http:403
== 10) 清理：删telegram渠道配置 ==> {"success":true,...} http:200
```

读数：接收面 fail-closed 门在真链路生效（3/4 拒绝）；管理面 admin 门（5 匿名 401、
9 非属主 403）与 mixin 真调用透传（6/7/8 对真 api.telegram.org 的失败诚实回
`success:false`，dummy token 打不上去是预期）；末步即测即清。
**200 接收正路径**需要 Telegram 侧真实接受 setWebhook（真 bot token），本环境
不具备 → 由单测 `testValidSignatureReachesProcessUpdateAndAnswersFast`
（monkeypatch 捕获 + 2xx 断言）覆盖，留作待真凭据批的双向自证。

## 5. 遗留与移交

- 无本笔范围内的断链遗留。`verify_webhook_signature` 的既有 fail-closed 单测
  （test_telegram_split.py）仍在守护，未重复造。
- 提交说明：feat(channels)，红灯/绿灯/净 LOC 去向段齐备；单笔单任务，
  `git commit --only` 逐文件点名，未触碰工作树其他会话在途文件
  （swarm.py / benchmark.py / agent_run_ledger.py 等均不在本笔）。
