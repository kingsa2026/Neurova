# reference_ad 安全域追平实施方案（D9 借鉴清单落地）

- 日期：2026-11-22
- 来源：源自同日 D9 专项细拆《[reference_ad_data_tenant_auth_security_teardown_2026-11-22.md](../08-research/reference_ad_data_tenant_auth_security_teardown_2026-11-22.md)》（十轴 L 72.5 / N 70.0）——把其 §5 借鉴与追平清单细化为可实施卡位
- 口径：与《2026-11-22-reference-ad-llm-routing-catchup-implementation-plan.md》《2026-11-22-reference-ad-multimodal-catchup-implementation-plan.md》同构——三批走、每卡带动机/改动点/红绿判据/验收/影响面/回滚，待拍板项显式列出
- 性质：**竞品/外部对标，研究参考**——只借鉴机制思路，不引入对方命名/结构与措辞

## 0. 总原则与红线

1. **租户来源保持 JWT 派生**（auth.py:744），不引入对方"信任 X-Workspace-Id 头"的形态（对方代码自认不可信，market/creds.ts:50-53）。
2. **任何自动执行不绕治理/审批**（肌肉记忆自动执行、外部代理执行现有红线不动）。
3. **审计以调用方为准**："审计函数存在"不等于"已接线"（本仓 log_auth_* 五函数零调用的教训）。
4. 新逻辑落独立模块（core/tenant_scope.py 等），不回填巨型文件；不引 ORM、不建 RLS（SQLite 单机形态 + 既有 192 处字段过滤）。

## 1. 现状锚点（2026-11-22 实测）

- 审计：`security/audit_logger.py` log_auth_login:306 / log_auth_logout:318 / log_config_change:329 / log_user_change:344 / log_role_change:359 / log_api_key_change:372 **全仓零调用**；audit_logs 表 :222-238；已接线的仅审批/工具执行/治理拒绝/桌面动作/最高权重口令。
- 登录失败路径：`api/endpoints/auth.py` login 失败 :263(401)/:268(403 inactive)/:273(403 locked)/:304(500)，成功 :286（现只写 login_logs，不走 audit_logger）；refresh 失败 :468/:473/:477/:486/:490、成功 :497；logout 成功 :857-861。
- 角色变更：`api/endpoints/enhanced_users_api.py:129` PUT /{user_id} → :144-145 写 role（无审计）；RBAC 模块（security/rbac.py）当前在 api/agent 层零 import、无审批端点（未接线状态，本计划不在其上叠加）。
- SSRF：`security/url_guard.py` 单源（私网/环回/链路本地 fail-closed）；webhook 创建/更新/投递前三处已校验（webhooks.py:99/:135/:167/:196）——**出站投递前复检已存在**，剩余风险=其余出站点位是否全走单源。
- API key：`api/api_key_manager.py:357` 已用 `secrets.token_urlsafe`、key_id `secrets.token_hex(16)`（:363），openplatform_keys.py:207 同源——**CSPRNG 已达标**。
- 安全响应头：`SecurityHeadersMiddleware` 已存在（api/middleware.py:110-122，四只头）但注册在 GlobalAuth/RateLimit **内层**（装配顺序 middleware.py:218-273：CORS→SecurityHeaders→RequestID→Logging→RateLimit→GlobalAuth→HttpMetrics）——401/429 短路响应不经过它。
- 租户过滤三形态：SQL 拼接（agent_run_store.py:537-539）/内存谓词（teams_api.py:341-342）/行级比较（knowledge_core.py:74-81），租户源统一 `current_user["tenant_id"]` 缺省 "default"。
- users 表（auth/user_model.py:104-118）：password_hash/role/status/failed_attempts/locked_until 等，**无 2FA 列**；前端登录面 = NeurUI/src/pages/LoginPage.vue + src/api/auth.ts（login:25/logout:41/refresh:47）。

## 2. 批次与卡位

### 批一 P0（低成本闭环，先行）

**S1 认证审计接线**
- 动机：登录失败审计双方缺位（对方零实现；本仓函数在而零调用）——接上即 A9 轴补齐，也是本专项四个判定题里最便宜的一格。
- 改动点：auth.py login 失败三支（:263/:268/:273）+ 成功（:286 旁）、refresh 失败五支+成功、logout 成功 → `log_auth_login(user_id, ip, ua, success=…)` / `log_auth_logout`；enhanced_users_api.py:144-145 角色写入 → `log_role_change(actor, target, old, new)`。IP/UA 取 request.client.host 与 headers。角色写入口实施时全仓 grep 复核（admin 面等其他端点）。
- 红绿判据：新增 `tests/unit/security/test_auth_audit_wiring.py`——断言「错误密码登录→audit_logs 出现 AUTH_FAILED 行」「成功登录→AUTH_LOGIN」「登出→AUTH_LOGOUT」「PUT 改角色→ROLE_CHANGE」；现状全红，接线后转绿。
- 验收：live-verify 真后端——错误密码连试 3 次 → GET /api/v1/audit 可见 3 条 FAILED；正常登录/登出/改角色各 1 条。
- 影响面：auth.py / enhanced_users_api.py 两文件小改；审计行数增加（每次登录 1 行）。
- 回滚：单 commit revert 即可，无 schema 变更。

**S2 出站点位 SSRF 复检扫荡**
- 动机：url_guard 单源已存在且 webhook 链路三处已校验；剩余风险=名单外出站点位（模型侧图片下载、web_reach、集成回调等）是否全走单源。D4 v7 专项的"专用 SSRF 包收敛"管实现形态，本卡做 D9 视角的**点位全覆盖核验+补漏**。
- 改动点：全仓 grep 出站 HTTP 点位（httpx/aiohttp/urllib 的 POST/GET）→ 建立点位清单 → 逐一对照 url_guard 消费名单 → 缺失处补 `validate_public_http_url`（含重试前复检）。
- 红绿判据：新增测试硬编码"出站点位清单"断言每处所在模块 import url_guard（或经统一收敛函数）——清单内任一缺失即红；补齐后转绿。
- 验收：live-verify 向 127.0.0.1/169.254 地址发起 webhook test 与抓取 → 一律拒绝且零出网。
- 影响面：出站集成模块小改（逐点 1-2 行）。
- 回滚：按点位逐 commit。

**S3 API key CSPRNG 核销（零码改）**
- 动机：对方 API key 生成用 timestamp+Math.random（utils/apiKey.ts:25-52，弱）；核验本仓是否同病。
- 核验结论：**已达标**——api_key_manager.py:357 `secrets.token_urlsafe`、:363 `secrets.token_hex(16)`，openplatform_keys.py:207 同源单份。**本卡闭案不写码**，核验记录留档。

### 批二 P1（结构加固）

**S4 审计防篡改哈希链**
- 动机：双方审计库均为普通 INSERT、可被静默改写；做了即双向反超。
- 改动点：新迁移（core/db_migration.py 注册，audit_logs 加 prev_hash/entry_hash 两列，或邻接链表 audit_chain 表）；audit_logger 写入时 `entry_hash = sha256(prev_hash ‖ canonical_json(entry))`；新增 `verify_audit_chain()`；endpoints/audit.py 增 GET /integrity。
- 红绿判据：测试「写入 3 条→链校验通过」「手改中间行→校验失败并定位断点」——现状无链全红，实现后绿。
- 验收：live-verify 写 3 条审计 → 直接改 SQLite 中间行 → /integrity 报断裂。
- 影响面：audit_logger 写入路径+一次迁移；每条 1 次 sha256，性能可忽略。
- 待拍板：**D-S2** 哈希链覆盖范围——全量事件 vs 仅 SECURITY_EVENT/APPROVAL 级（建议全量，写入路径单点改）。

**S5 租户过滤集中化（试点三处）**
- 动机：31 文件 192 处散落三种形态，漏一处即越权；对方 buildWorkspaceWhere 的集中 builder 形态可借鉴（语义保持本仓 JWT 源+缺省 default）。
- 改动点：新增 `core/tenant_scope.py`：`resolve_tenant(user)->str`、`tenant_sql_where(alias)->tuple[sql,params]`、`tenant_matches(user,row)->bool`；试点迁移 agent_run_store.py:537-539（SQL 拼接形态）、teams_api.py:341-342（内存谓词形态）、knowledge_core.py:74-81（行级比较形态）；其余 28 文件增量迁移另批（D-S3）。
- 红绿判据：试点三处改走助手后**行为逐字节一致**（同输入同结果，既有跨租户 403/不可见测试全数保持绿）+ 助手自身单测（缺省 default/None 用户/未知租户）。
- 验收：全量租户相关回归零新增失败；knowledge/teams/agent_runs 跨租户探测仍 403/空。
- 影响面：新模块+3 文件试点；不引 ORM、不改表。
- 待拍板：**D-S3** 全量迁移节奏（建议试点先行，回归稳定后分两批扫余量）。

**S6 安全响应头移层+补全**
- 动机：SecurityHeadersMiddleware 已存在但被 GlobalAuth/RateLimit 短路绕过（401/429 响应不带安全头）；对方主站 CSP 默认关——补齐即反超。
- 改动点：middleware.py 装配顺序把 SecurityHeaders 移到最外层（HttpMetrics 之外）；补 Referrer-Policy/Permissions-Policy，HSTS 仅 HTTPS 部署启用（**D-S4**）；CSP 说明：本仓 API 侧无 HTML 路由面（NeurUI 为独立 8100 服务），CSP 责任在前端服务/部署层（nginx 等），本卡只在 API 响应补 `Content-Security-Policy: frame-ancestors 'none'` 类防嵌入头。
- 红绿判据：测试断言「未带 token 打受保护端点→401 响应含现有四头+新增头」——现状 401 不带→红；移层后绿。
- 验收：live-verify 无 token 请求 /api/v1/teams → 401 响应含全部安全头。
- 影响面：middleware.py 装配顺序+头集合；对外响应增加数只头。
- 待拍板：**D-S4** HSTS 启用条件（建议 `NEUROVA_FORCE_HTTPS=1` 时才加，避免本地明文误发）。

### 批三 P2（产品向，需拍板后立项）

**S7 通用 OIDC SSO 接入**
- 动机：对方 17 SSO+generic-oidc 任意 IdP；本仓 0。自托管友好型（Keycloak/Authelia）一个 generic OIDC 客户端即可覆盖多数企业场景。
- 改动点：新增 `api/endpoints/auth_oidc.py`（/authorize 重定向+state/nonce+callback 换 token+按 sub 供应/映射本仓用户与角色）+ users 表加 oidc_sub 列（走 db_migration 注册表）+ env NEUROVA_OIDC_*（issuer/client_id/client_secret/scopes，缺配置端点 503 诚实）+ 前端 LoginPage 登录按钮与 auth api 扩展（参照现成 QrcodeAuthBlock 形态）。
- 红绿判据：测试内建极简假 IdP（签 RSA JWT 的 authorize/token 端点）走通 authorization code 全流程→本仓 JWT 签发成功；未配置→503；sub 变化→新用户隔离。
- 验收：live-verify 对接本地 Keycloak 容器（或任一真 IdP）完成一次真实登录进 console。
- 影响面：后端新端点+1 迁移+前端登录页；既有密码链不动。
- 待拍板：**D-S5** 是否立项（需 IdP 环境与运维配合）。

**S8 TOTP 2FA**
- 动机：双方均缺（对方有表无功能）；全功能落地即双反超。
- 改动点：迁移 users 加 totp_secret/two_factor_enabled 列（user_model.py:104-118 现无）；启用/解绑端点（登录后自服务）；登录链二步挑战——密码过→若启用返回短时 challenge_token→/auth/2fa/verify 校验 TOTP 换正式 token；恢复码单次有效；pyotp 作可选依赖惰性 import（仓库规约：可选依赖不得顶层裸 import）；前端 LoginPage 二步态+设置页开关。
- 红绿判据：固定时钟+固定 seed 单测——正确 OTP 通过/错误拒绝/同码重放拒绝/恢复码单次有效/未启用用户不受影响；现状全红。
- 验收：live-verify 开启 2FA 后密码登录返回 challenge，真 TOTP（手机器或 mock clock）验证后放行。
- 影响面：认证链+1 迁移+前端登录/设置页；**需用户迁移说明**（存量用户默认关闭，逐户自启用）。
- 待拍板：**D-S6** 是否立项与上线节奏。

## 3. 待拍板项汇总

| 项 | 问题 | 选项与影响 | 建议 |
|---|---|---|---|
| D-S2 | 哈希链覆盖范围 | 全量事件（写入单点改，审计量增加哈希计算）/仅安全级事件（改动面小但链有空洞） | 全量 |
| D-S3 | 租户助手迁移节奏 | 试点三处后停（收益有限）/分两批扫全部 31 文件（彻底但回归面大） | 试点先行，绿后扫余量 |
| D-S4 | HSTS 启用条件 | 恒发（本地明文会误发）/NEUROVA_FORCE_HTTPS 才发 | 后者 |
| D-S5 | OIDC SSO 立项 | 立项（需 IdP 环境）/暂缓 | 视企业部署需求 |
| D-S6 | TOTP 2FA 立项 | 立项（认证链改动+前端二步态）/暂缓 | 视产品需求 |

明确不做：不引 ORM、不建数据库 RLS（SQLite 单机+字段过滤已覆盖当前形态）；不改 JWT 单通道身份架构；不引入对方"信任工作区头"模式；不为 SSO 弱化既有密码链（bcrypt/PBKDF2 与锁定策略保留）。

## 4. 验收总目标

- D9 专项复评：70.0 → **≥76.0**（A9 审计 5.5→≥7.0：登录失败接线+防篡改；A7 网络边界 9.0→≥9.5：SSRF 扫荡补漏；A2/A3 视批三立项再计）。
- 主报告 D9 维：8.0 → **≥8.5**/12，D9 判定维持 L 小胜或转平。
- 每卡独立红→绿证据 + live-verify，分域回归零新增失败（教义第 3/4 条）。

## 5. 执行记录

（待实施回填：逐卡 commit、红绿实测输出、live-verify 证据、复评读数。）
