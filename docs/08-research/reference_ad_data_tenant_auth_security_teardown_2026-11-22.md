# reference_ad D9 专项：数据/租户/认证/安全细拆（teardown）

- 日期：2026-11-22
- 母报告：《[reference_ad_vs_neurova_fullstack_evaluation_2026-11-21.md](reference_ad_vs_neurova_fullstack_evaluation_2026-11-21.md)》D9 维（粗评 L 9.0 / N 8.0，/12）——本专项应评审要求单独摘出细化
- 方法：两路只读深读（lobehub 数据/认证/租户/安全十组 vs Neurova 同十组），结论全部落 file:line 或可复现计数；未运行任何代码
- 对象快照：lobehub canary@2026-11-21（v2.3.4）；Neurova main（44396334f 前后）
- 性质：**竞品/外部对标，研究参考**——不作产品事实源

## 0. 总判定

**专项总分（十轴 /100）：LobeHub 72.5 vs Neurova 70.0。**

- 粗评口径（/12 归一到 /100）为 L 75.0 / N 66.7；细拆后差距从 8.3 分收窄到 **2.5 分**——对方领先靠认证登录矩阵与数据层工程体量；本仓在身份通道纪律、租户执行真实性、网络边界、秘密保护四轴反超，把总分追到近身。
- 主报告 D9 合计维持 **L 9.0 / N 8.0（/12）不变**，四个子项分据实重排：认证 L 3.0→2.5 / N 1.5→2.0；租户与权限执行 N 2.5→2.0；运行安全 L 1.5→2.0（数据层 3.0/2.0 不变）。
- 双方共同的诚实短板：**审计都不覆盖登录失败**（对方零实现、本仓函数在而零调用）；**都无 2FA 可用**（对方连库表迁移都建了、插件没挂）；**都无数据库行级安全（RLS）**；对方的 secret-channel（HPKE）与 2FA 均为"有实现/有表、无消费"状态。

## 1. 十轴评分卡

| 轴 | 权重 | LobeHub | Neurova | 判定 |
|---|---:|---:|---:|---|
| A1 数据层工程 | 12 | 11.0 | 8.5 | L 胜 |
| A2 登录方式矩阵 | 12 | 10.5 | 6.0 | L 大胜 |
| A3 会话与凭据生命周期 | 10 | 9.0 | 7.0 | L 胜 |
| A4 身份通道架构 | 8 | 5.5 | 7.0 | **N 胜** |
| A5 多租户隔离模型与执行 | 14 | 7.0 | 9.5 | **N 胜** |
| A6 授权与 ACL 细粒度 | 10 | 8.0 | 7.0 | L 小胜 |
| A7 网络边界安全 | 12 | 7.5 | 9.0 | **N 胜** |
| A8 秘密与凭据保护 | 8 | 5.0 | 6.5 | **N 胜** |
| A9 审计与可追责 | 8 | 5.0 | 5.5 | N 小胜 |
| A10 端点/进程/设备面 | 6 | 4.0 | 4.0 | 平 |
| **合计** | **100** | **72.5** | **70.0** | |

## 2. 逐轴详评

### A1 数据层工程（L 11 / N 8.5，权 12）

**LobeHub【完善】**：`packages/database/src/schemas/` 94 个 schema 文件、**238 个 pgTable 定义**（agent 系 17 文件、workspace 域 7 表、userMemories/ 12 文件、rbac 4 表、oidc 10 表）；migrations 实数 **227 个 SQL**（0000_init→0226_agent_share_grants，meta/ 存 drizzle snapshot）；`drizzle.config.ts:19` strict 模式；软删 helper（`_helpers.ts:32` softDeleteColumns，读侧 `IS NOT TRUE` 约定）+ trash 回收站登记表（多态 root_id/resource_type，过期清扫）；**FTS outbox** 设计讲究——`fts_search_sync_revision_seq` 单调序列供触发器取版本，`fts_search_sync_outbox` 队列表带 attempts/availableAt/lockedUntil/deadAt/priority + claim/dead/lease 三个部分索引，触发器捕获变更、worker 异步刷投影；`0026_add_autovacuum_tuning.sql` 对 embeddings/chunks 设 autovacuum 参数。扣分：**仅前向迁移、无 down/回滚手段**（grep down 无命中）。
**Neurova**：`core/db_migration.py:34` register_migration 按域 PRAGMA user_version（防降级 SchemaVersionError :94），全仓 **62 处注册、分布 30 文件**（含 security/approval_manager.py:50 独立域）；**170 条 CREATE TABLE / 155 个唯一表名**；`core/connection_pool.py` WAL（:78）+busy_timeout（:80,:262-265 归还时校准）+RLock（:84）+归还前强制 rollback（:11,:210）；`core/data_root.py:37` 数据根单源（NEUROVA_DATA_DIR 必须绝对路径否则抛错 :44-48），`agent_workspaces.py:144-214` 按 agent 派生目录。SQLite 外落盘面：肌肉记忆 JSON 原子写（muscle_memory.py:794-802）、eviction ledger 独立 SQLite（context/eviction_ledger_db.py:427 自带 v1/v3 迁移）、MCP 授权 JSON（security/mcp_grants.py:23）。扣分：体量与机制丰富度小于对方；无回收站/FTS outbox 这类完整性配套设施。
**判定**：对方数据层是 PostgreSQL 级工程完备度（软删/回收站/outbox/调优四位一体），本仓是 SQLite 级的干净单源（迁移按域+连接池纪律+数据根派生）。A1 L 胜。

### A2 登录方式矩阵（L 10.5 / N 6，权 12）

**LobeHub【完善，2FA 缺】**：SSO/OAuth **17 个提供商**（apple/auth0/authelia/authentik/casdoor/cloudflare-zero-trust/cognito/feishu/generic-oidc/github/google/keycloak/logto/microsoft/okta/wechat/zitadel，`src/libs/better-auth/sso/providers/`，由 AUTH_SSO_PROVIDERS 按需启用，define-config.ts:117-119）；任意 OIDC 走 genericOAuth 插件（:356-362）；邮箱密码（8-64 位，`revokeSessionsOnPasswordReset: true` :155）；magic link（900s，:363-381）；Email OTP（300s/6 位/3 次尝试，:322-344，按 `x-client-type: mobile` 走短信式）；**Passkey/WebAuthn**（:345-355，rpID 取 APP_URL hostname、origin 对齐 Android DAL）；设备授权流（oidc_device_codes 表，schemas/oidc.ts:81）。**2FA 不可用**：two_factor 表（betterAuth.ts:87）、two_factor_enabled 列（user.ts:44）、迁移 0054 都在，但 define-config.ts 插件表（:314-382）未挂 twoFactor 插件、应用代码零引用——**有表无功能**。
**Neurova**：用户名密码（`api/auth.py:473-501` bcrypt 优先、回退 PBKDF2-SHA256 260k 随机盐；verify 拒绝无盐 SHA-256 :530-533）；注册/邀请注册/验证码/找回（recover-password 走 env 注入的最高权重口令，命中记 CRITICAL 审计 endpoints/auth.py:430-449）；JWT 对（HS256，access 60min/refresh 7d，:32-33）；mobile pairing 设备配对（高熵 ref+6 位码 300s TTL、每 IP 滑窗限流 :416-435、epoch 递增使旧凭证失效）。**无任何 SSO/OAuth/Passkey/magic link/2FA**。
**判定**：对方登录矩阵是产品级全谱（仅缺 2FA），本仓是单租户自托管够用面。A2 L 大胜。

### A3 会话与凭据生命周期（L 9 / N 7，权 10）

**LobeHub【完善，一处弱】**：会话 cookie 缓存 120s + `deferSessionRefresh` 仅 POST 滑动续期（session-options.ts）+ DB/Redis 双写（Redis secondaryStorage，utils/config.ts:113-127）；改密撤销全部会话（define-config.ts:155）；密码哈希新口令走 better-auth 默认 scrypt、verify 钩子兼容 Clerk 迁移的 bcrypt（:157-171）；**API key 纪律严**——`sk-lh-` 前缀+格式/启用位/过期校验（trpc/src/lambda/context.ts:42-73）、personal key 禁入 workspace、workspace key 绑定唯一 workspace、另需在职 membership+entitlement（:285-339）；自建 OIDC IdP 10 张表（authorization_codes/access_tokens/refresh_tokens/device_codes/interactions/grants/clients/sessions/consents/oauth_handoffs，schemas/oidc.ts）。**扣分**：API key 生成用 timestamp+Math.random+counter，**非 CSPRNG**（packages/utils/src/apiKey.ts:25-52）。
**Neurova**：JWT HS256 + access 60min/refresh 7d + refresh 端点（endpoints/auth.py:460）；`revoked_tokens` 黑名单表带 exp 清理（auth.py:370-420）+ 全局黑名单校验（:426）；JWT 密钥链 env→data/.jwt_secret→自动生成，最短 32 字节、拦常见弱默认（:115）、**写入即 chmod 0600**（:124-132）；服务令牌 X-Service-Token 常量时间比较（:630-656）；API key manager DCL 单例（:668）。扣分：无会话滑动续期细节、无 OIDC IdP 面。
**判定**：对方会话工程更细（滑动续期/双写/兼容迁移），本仓黑名单+密钥文件纪律扎实。A3 L 胜。

### A4 身份通道架构（L 5.5 / N 7，权 8）——本仓反超

**LobeHub**：tRPC context 四通道优先级（`trpc/src/lambda/context.ts`）：dev 后门（:222-232，NODE_ENV=development+特定 header→MOCK_DEV_USER_ID）→ X-API-Key（:265-350，命中即返回、失败不回退）→ OIDC JWT（:357-423，含封禁用户 active 复检）→ 会话 cookie 兜底（:425-448）。**缺口**：workspaceId 取自原始 `X-Workspace-Id` 头且**不校验成员资格**——代码自证（`routers/lambda/market/creds.ts:50-53`："ctx.workspaceId from the raw X-Workspace-Id header is NOT trustworthy on its own…cloudWorkspaceAuth verifies"），而 OSS 的 cloudWorkspaceAuth 即直通 stub ⇒ 会话用户带任意 workspace UUID 头即可按该 workspace 读过滤（写路径由 creator 校验兜底）。
**Neurova**：`core/identity_context.py:28` 全仓唯一身份 ContextVar，**15 个边界写入点**逐一核对（chat/agent/console/mobile_pairing/mcp_server_api/external_agents_api/computer/mcp_agent_tools_server/tool_executor/mcp_server/channel_router/resume/approval_continuation），未发现第二通道；`GlobalAuthMiddleware`（global_auth.py:98）包**全部 ASGI 路径**，off/shadow/enforce 三模式（:68-73），无鉴权端点显式白名单（:34-66），/metrics 环回限定；会话属主分流 resolveSessionOwner（post_chat_pipeline.py:135-165）+空属主判管理员（:189-210）。
**判定**：本仓"身份只有一条通道+中间件全路径包抄"是结构性优势；对方的头信任缺口在 OSS 真实存在（自家注释承认）。A4 N 胜。

### A5 多租户隔离模型与执行（L 7 / N 9.5，权 14）——本仓反超

**LobeHub**：workspace 7 表（workspaces/members/invitations/audit_logs/user_settings/teams/team_members）；**71 个 schema 文件带 userId+workspaceId 双列**；`buildWorkspaceWhere`（database/src/utils/workspace.ts:88）集中过滤 builder（private 可见性过滤）；`assertWorkspaceRowManageable` 70 处调用（owner/admin/creator 三级行校验，:38-60）。**核心扣分**：① tRPC 面角色门**全部是 no-op stub**——`business-server/src/trpc-middlewares/workspaceAuth.ts:18-23` 直通、`rbacPermission.ts:16-30` 四个中间件全 no-op，注释自述 "No-op stub for OSS builds. Cloud overrides this entire module via tsconfig path priority"；生效机制=根 tsconfig.json:28 路径映射让 packages 侧 stub 优先命中（apps/server 各 router 挂的门槛在 OSS 全放行）；② **RBAC 真实执行点仅 4 处**：openapi base.controller.ts:259-265/283-284/323-324、openapi middleware/permission-check.ts:131-143、agentShare.ts:375、模型层 models/rbac.ts:311/327/362/378；③ migrations 中 "ROW LEVEL SECURITY" **0 处**，无 RLS。
**Neurova**：tenant_id 从 **JWT** 提取（auth.py:744，非客户端头）；消费面 **192 处、31 个文件**（knowledge 12 端点/teams/external_agents/chat/console/mobile_pairing/quality/generation/openplatform_keys/auth/agent_communication + agent 侧 chat_pipeline/approval_chain/swarm/3 retriever/neuacp 4 文件）；neuacp 四缺口已收口（teams_api 建队戳印+列表过滤 :318-342、agent_runs 租户列+索引 agent_run_store.py:157-160、裁决人租户校验 approval_chain.py:873-884、WS 按 user_id 分桶 mobile_pairing.py:582-609）；外部代理进程池键含租户段（acp_executor.py:48,61,85-88）+ 凭据=HMAC(run_id+tenant) 作用域令牌 env 注入（child_env.py:53-61）。扣分：**散落式字段级过滤**——无 ORM、无集中 scope，各 SQL 自写 `WHERE tenant_id=?`；租户缺省 "default"。
**判定**：对方的模型面（双列+builder+行校验）铺得广，但 OSS 执行面被 stub 掏空+头信任缺口；本仓执行真实（JWT 源+192 处+外部代理红线），但散落式维护风险高。综合 A5 N 胜——"真执行的中等强度"压过"强模型+弱执行"。

### A6 授权与 ACL 细粒度（L 8 / N 7，权 10）

**LobeHub【完善】**：agent_shares 的 ACL 粒度细——visibility（默认 private，:173）/shareConfig（:175）/**toolGrants（:141）/skillGrants（:127）白名单**/dismissedTools（:38）/deviceAccess 三态+allowUserIds（:13,:56,:71）/**每 Agent 月度花费上限（:93）/maxFileStorage（:86,:151）**；shareVisitorTargetGuard+防滥用服务（shareVisitorAbuseGuards）；五族分享表（agent/goal/document/file/topic）。扣分：分享链接**无签名 token/HMAC**（grep 无命中），靠不可枚举 ID+服务端状态开关。
**Neurova**：RBAC 三表+ROLE_PERMISSIONS 常量（security/rbac.py:57,161-249）+权限变更申请单（:455）；require_admin/require_role/requireAgentOwner/can_access_agent 消费 16 个 api 文件；MAIN_AGENT_ONLY_TOOLS 12 个（builtin_tools.py:2544-2551）+成员白名单派生（swarm.py:193-225）+**执行期二次拦截**（tool_executor.py:1527-1532）；MCP 按 server+tool 粒度授予（security/mcp_grants.py mint/has/revoke :61-88），MCP server 入口强制三选一鉴权否则 401（mcp_agent_tools_server.py:344-350）。
**判定**：对方分享 ACL 的"工具级授权+花费/存储上限"是产品级细度；本仓的工具面治理（主代理专用工具+白名单派生+执行期拦截+MCP 按工具授予）在 agent 场景更对口。A6 L 小胜。

### A7 网络边界安全（L 7.5 / N 9，权 12）——本仓反超

**LobeHub**：主站 **CSP 默认关**（shouldUseCSP=ENABLED_CSP==='1'，define-config.ts:28；开启也仅 X-Frame-Options+frame-ancestors，:106-117）——弱；MCPApp iframe CSP 严格（default-src 'none'/base-uri 'none'/form-action 'none'+禁 camera/mic/geo/clipboard，MCPApp/utils.ts:55-79）——强；**限流一半有**：OpenAPI REST 面全局 Redis 固定窗口（openapi/src/app.ts:50 rateLimit()，keys.ts:396-400）、better-auth 登录面仅 2 端点 3 次/分钟（define-config.ts:308-313）、**tRPC/hono 业务面无限流**；webhook 验签：github HMAC（github.ts:46-55）、video/llmRelay/artboard timingSafeEqual、inbound per-hook Bearer/MCP 签名，但 **logto 用 `===` 非 timingSafe（logtoValidateRequest.ts:31-36）、casdoor 明文 `===` 比较（casdoorValidateRequest.ts:19-30）**；ssrf-safe-fetch 强（私网/环回/链路本地+重定向逐跳+SSRF_ALLOW_PRIVATE_IP_ADDRESS 放开阀，index.ts:170-223）。
**Neurova**：CORS 单源（api/cors_policy.py，曾双写 8 处已收口）；**API 级限流存在**——RateLimitMiddleware（middleware.py:132,:255 注册，429/code 4290，匿名按 IP）+API key rate_limit 字段（api_key_manager.py:49）+注册/配对专用限流；webhook 验签 **9 文件**（dingtalk HMAC+compare_digest :487-491、feishu :728、**qq Ed25519** :513-548、telegram/wecom/wechat_auth/wechat_kf(+crypto)/qclaw）；SSRF：security/url_guard.py 全仓单源（拦 0.0.0.0/8、10/8、127/8、169.254/16、172.16/12、192.168/16，fail-closed 解析 :50-58）+13+ 消费方（webhooks.py:99 创建时校验；**投递执行期是否复检待核实**）；三面 WS 鉴权（console JWT :2939-2941、mobile HMAC 凭证、relay enrollment token 失败 4401 relay/app.py:159,196）。
**判定**：本仓"全路径限流中间件+9 处验签+SSRF 单源"整体更完整；对方有 OpenAPI 面限流与强 SSRF 包，但 CSP 关闭、两处非 timingSafe 比较、tRPC 面裸奔。A7 N 胜。

### A8 秘密与凭据保护（L 5 / N 6.5，权 8）——本仓反超

**LobeHub**：secret-channel（ASC/1 HPKE）实现精良但**全仓零消费方**（grep "secret-channel" 仅命中其自身 package.json）——未接线；桌面端 electron safeStorage 加解密 access/refresh token（RemoteServerConfigCtr.ts:205-206,253,270-274）；alint no-secret-exposure 仅 **warn 级**（alint.config.toml:541-555）效力弱；.env.example 无硬编码默认密钥；凭据脱敏（creds 注入结果只含变量名+`******`，不进模型上下文，builtin-tool-creds/src/injectResult.ts:34-58）。
**Neurova**：keyring 密钥链（env NEUROVA_SECRET_KEY→keyring 条目按数据根哈希派生+旧条目灰度迁移 :31-62，C5 已落地）→文件自动生成兜底；渠道/模型凭据 sealSecrets/unsealSecrets 加解密（channel_config.py:136、shared_config.py:75-80,174-177）；脱敏三件套 sensitive_info（detect/sanitize/mask）14 处消费+trace_recorder 对 password 键脱敏（:38）+令牌尾 4 位掩码（tunnel/connection_config.py:67-70）；JWT 密钥文件 0600+弱默认拦截；硬编码密钥粗查未命中。
**判定**：本仓秘密链路（派生 keyring+加密封装+三层脱敏+文件权限）成体系；对方有 safeStorage 与凭据脱敏，但旗舰加密通道是摆设、lint 效力弱。A8 N 胜。

### A9 审计与可追责（L 5 / N 5.5，权 8）

**LobeHub**：workspace_audit_logs 动作枚举 **89 个事件**（models/workspaceAuditLog.ts:7-96：workspace 12/member 10/invitation 4/budget 9/team 5/top_up 6/provider 8/api_key 5/resource 8/security 2/integration 4/webhook 3/market 3/subscription 6）；channel_audit 表用于渠道路由；**但落审计面窄**——非测试消费方仅 6 个文件（apiKey/connector/topicComment/topic share/mcpEvents/inboundWebhook manage），多数工作区写操作不落审计；登录/鉴权失败**无审计**（grep recordLogin/loginAudit 0 命中，失败仅日志+响应头 authFailure.ts）。
**Neurova**：audit_logger SQLite audit_logs（:256-303），事件枚举含 AUTH_LOGIN/FAILED/LOGOUT/TOOL_EXECUTION/APPROVAL/SECURITY_EVENT/DATA_ACCESS（:34-47）；**已接线**：审批裁决（approval_chain.py:168-240,700,717,746,887）、工具执行与治理拒绝（tool_executor.py:140-152,2510-2528）、桌面动作独立库 desktop_audit（tool_executor.py:2880-2897）、最高权重口令命中 CRITICAL（endpoints/auth.py:430-449）；查询/导出面（endpoints/audit.py:140-198 GET /search /stats /export）。**两个诚实缺口**：① log_auth_login/log_auth_logout/log_role_change/log_config_change/log_api_key_change（audit_logger.py:306-385）**全仓零调用**——登录/登出/角色变更实际不入审计，正常登录失败也不入；② 审计库普通 INSERT，**无哈希链/防篡改**。
**判定**：对方枚举广而接线窄，本仓枚举中而安全侧接线实（审批/工具/治理拒绝），但认证侧审计双方都缺、本仓还是"有函数无调用"。A9 N 小胜。

### A10 端点/进程/设备面（L 4 / N 4，权 6）

**LobeHub**：**Electron IPC 裸 socket**——net.createServer 直接收命令，无 token/peer 校验（electron-server-ipc/ipcServer.ts:25,51-57），socket 信息文件写 os.tmpdir()（:52-56），Unix 侧未设 chmod、Windows 命名管道未见 DACL ⇒ 本机任意进程可连；设备链路强：deviceId=sha256(seedId|principal|SALT) 截 32（device-identity/index.ts:43,70）、WS 首条消息携 token 不进 URL+等 auth_success（device-gateway-client/client.ts:446-466）、服务端 DO 复验声明（:413-415）、assertDeviceOperable（guards.ts:49-80 public=成员可用/private=登记人或 owner）、**设备端 realpath 防 symlink 逃逸**（workspaceGuard.ts:28-63）；供应链：patches 仅 3 个+renovate+codeql，**无 dependency-review workflow**。
**Neurova**：无 Electron（NeurUI 经 HTTP/WS 访问本机后端，start_server 缺省绑 127.0.0.1）；沙箱四件套（code_sandbox/exec_sandbox/**restricted_token Windows SRP/SAFER CreateProcessAsUserW deny-only**/appcontainer Low integrity）——进程级隔离手段比对方 local-system 直执行强（此点归 D4，不重复计）；relay 强制 enrollment token（relay/app.py:144）+HMAC 派生路由 id（:57-64）+常量时间比较（:102）；tunnel 无 token 拒绝配置（connection_config.py:122-123）；/metrics 三档 local/token/public 默认环回（metrics_access.py:63-70）；子进程凭据仅经 env 显式注入+代理变量剥离（child_env.py:45-61）。
**判定**：对方设备链路纵深（身份哈希/首消息鉴权/服务端复验/symlink 防护）是亮点，但 IPC 裸 socket 是硬伤；本仓本地面默认环回+relay 鉴权+子进程凭据纪律干净，无对等设备网关链。A10 平。

## 3. 四个关键判定题（双方对照）

| 判定题 | LobeHub | Neurova |
|---|---|---|
| RBAC/权限真实执行点 | **OSS 仅 4 处**（openapi REST 两处+agentShare+模型层）；tRPC 面全 stub（tsconfig path 优先级放行），assertWorkspaceRowManageable 70 处仅做 creator 行校验 | RBAC 表+常量+16 个 api 文件依赖项+MAIN_AGENT_ONLY_TOOLS 执行期二次拦截——**全部真实执行**，但散落无集中 scope |
| 业务 API 限流 | **一半有**：OpenAPI REST 全局 Redis 窗口；better-auth 仅 2 端点；**tRPC/hono 面无** | **有**：全局 RateLimitMiddleware（429/4290，匿名按 IP）+API key 配额+注册/配对专用限流 |
| 2FA | **不可用**（two_factor 表+迁移 0054 在，better-auth 插件未挂、代码零引用） | 无 |
| 专项加密通道接线 | secret-channel（HPKE）**零消费方** | —（无对应物；凭据走 keyring+sealSecrets 实链路） |

## 4. 结论

- **对方强项**：认证登录矩阵（17 SSO+Passkey+magic link+OTP+自建 OIDC IdP）、数据层工程体量（238 表/227 迁移/FTS outbox/回收站）、分享 ACL 产品级细度（工具级授权+花费/存储上限）、设备链路纵深。
- **本仓强项**：身份单通道纪律+全路径鉴权中间件、租户隔离真实执行（JWT 源+192 处+外部代理红线+作用域凭据）、网络边界完整度（全局限流+9 处验签+SSRF 单源+三面 WS 鉴权）、秘密保护成体系（keyring 派生+加密封装+三层脱敏+0600）。
- **共同短板**：登录失败审计双双缺位（本仓还是"有函数零调用"）；2FA 双双不可用；均无 RLS；对方两处验签非 timingSafe、本仓 webhook 投递期复检待核实——这些是双方都能被同类渗透手法打到的面。

## 5. 借鉴与追平清单（D9 域，待拍板）

P0（本仓低成本闭环）：
1. **认证审计接线**：log_auth_login/log_auth_logout/log_role_change 等函数已存在（audit_logger.py:306-385）但零调用——把 login/refresh 失败/登出/角色变更接上，审计三事件判定题即转全绿。
2. **webhook 投递执行期 SSRF 复检**：url_guard 已单源，创建时校验（webhooks.py:99）之外，投递与重试执行前补二次校验，堵 TOCTOU。

P1：
3. **SSO 最小矩阵**：对方 generic-oidc 插件证明"接任意 OIDC IdP"成本低；本仓可先做通用 OIDC 接入（Keycloak/Authelia 等自托管友好型），SSO 矩阵从 0 到 1。
4. **审计防篡改**：审计库加哈希链（prev_hash 进链）或定期外部沉降——对方也未做，做成即差异点。
5. **租户过滤集中化**：本仓 31 文件 192 处散落 `WHERE tenant_id=?`，可收口为统一查询助手（对方 buildWorkspaceWhere 的集中 builder 形态可借鉴，但执行语义以本仓 JWT 源为准）。

P2：
6. **CSP 响应头**：本仓服务端可直接下发基础 CSP（对方主站都没开，做了即反超）。
7. **TOTP 2FA**：双方都缺；本仓做即双反超（对方有表无功能，本仓可全功能）。
8. **API key 生成 CSPRNG**：对方 timestamp+Math.random 被自家标注弱；本仓对应生成面统一走 secrets 模块即可防患。

守卫提示（勿在"对齐"中丢掉）：
- 租户来源必须保持 JWT 派生，不得引入对方"信任 X-Workspace-Id 头"的形态；
- 肌肉记忆自动执行、外部代理执行均不得绕过治理/审批（现有红线）；
- "审计函数存在"不等于"已接线"——盘点以调用方为准（本仓已有零调用先例）。

## 6. 局限

- 静态只读，未做运行时验证（限流阈值、CSP 实际下发头、配对限流窗口均以代码为准）；
- lobehub 为 canary 单日快照（v2.3.4），其 RBAC stub 的云版覆盖不可见，"云版更强"无法证实也无法计入；
- 本仓"投递执行期 SSRF 复检""Gemini 链路收图"等两项标"待核实"，未据此扣分；
- Electron IPC 的 Windows DACL、share URL 具体形态两处标"待核实"，未据此加分。
