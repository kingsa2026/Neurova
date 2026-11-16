# R4 修复台账 —— P2 清偿·API/技能/进化/协作/渠道/安全/其余后端（2026-11-17）

执行会话：R4。认领条目：审计报告 §3.1-7~20（除 1~6/12 已由 S1/S2 修复）、
§3.4-1~9/11/12（除已由 S7 退役项）、§3.5-3~12、url_guard 合一（S2 移交）。
门控与诚实化契约测试统一落 `tests/unit/api/test_r4_p2_gates.py`（38 用例）。

---

## §3.1 后端 API

### §3.1-7 logs.py 清空事件日志收 admin

- **根因**：`DELETE /api/v1/logs` 仅登录门，任意用户可清空全站事件日志（抹排障现场）。
- **修复点**：路由级 `Depends(require_admin())`（判据单源 `api/deps.require_admin`，与 S1 firewall 同形）。
- **红灯/绿灯**：`test_logs_delete_admin_gated`（路由依赖逐一以非 admin 身份试门）先红后绿。
- **live-verify**：`DELETE /api/v1/logs` 普通用户 → **403**；admin → **200**。

### §3.1-8 scheduler.py 任务 agent_id 属主门

- **根因**：建任务/改任务可指定任意 `agent_id`，等于借定时器驱动他人 agent
  （耗他人 LLM 额度、写他人工作区）。
- **修复点**：`create_task` 与 `update_task`（教义第 5 条：更新腿同批扫平）在 try 之外
  过 `requireAgentOwner`（agent_access 单源；门置 try 外防 500 兜底改写 403）。
  无主 agent（含 default）仅 admin——与 S1 console/agent 面同口径。
- **红灯/绿灯**：`test_scheduler_create_task_rejects_foreign_agent`、
  `test_scheduler_update_task_rejects_foreign_agent`、阳性对照
  `test_scheduler_create_task_allows_own_agent` 先红后绿。
- **测试同步**：`test_scheduler_api_auth.py` 的认证用户升为 admin（该套件考鉴权契约
  与调度行为，非属主语义；原 user 身份创建 default 任务钉的是旧放行形态）。
- **live-verify**：`POST /api/v1/scheduler/tasks`（agent_id=default）普通用户 → **403**。

### §3.1-9 mobile_push.py 注销推送令牌绑属主

- **根因**：`DELETE /push-tokens/{device_id}` 只凭 device_id，任何登录用户可注销
  他人设备推送（静默解除他人通知触达）。
- **修复点**：存储层新增 `remove_token_for_user(device_id, user_id)`（DELETE 加
  `AND user_id=?`，根因处收口）；端点对"未删除"统一回 404（不区分不存在/非属主，
  防枚举）；无属主判定的旧 `remove_token` 退役（教义第 6 条，不留第二份危险原语）。
- **红灯/绿灯**：`test_remove_rejects_foreign_owner`（push_store 层）+
  `test_mobile_push_delete_binds_owner`（端点层 404/200）先红后绿。
- **live-verify**：admin 上报 probe-dev-1 后，普通用户 DELETE → **404**。

### §3.1-10 tool_layers.py share_tool 死功能面退役

- **对比结论（教义第 7 条）**：`_shared_tools` 全仓零读者、`shared-with-me` 恒回 []，
  即"共享"功能无任何消费面；而写入面可被任意登录用户无限写入进程内存——
  只留风险不留功能，判定退役（非修复）。
- **修复点**：删除 `/tools/share`、`/tools/shared-with-me` 两端点、`ShareToolRequest`
  模型与 `_shared_tools` 字典；文件头注明退役原因。
- **红灯/绿灯**：`test_share_tool_routes_retired`（路由面不得复活）先红后绿。
- **live-verify**：`POST /api/v1/tool-layers/tools/share` → **404**。

### §3.1-11 memory_timeline_api.py 恒空装饰面诚实化

- **根因**：四端点（已实挂 /v1/memory-timeline）恒回空/零（`count += 0 # placeholder`），
  前端无法分辨"无记忆"与"未实现"。
- **修复点**：四端点统一显式 **501**，detail 点名未实现并指路真实数据面
  （/v1/memories、/v1/memory/stats）——对齐 P1-9 附件桩的 501 形态。
- **红灯/绿灯**：`test_memory_timeline_endpoints_are_501` 先红后绿。
- **live-verify**：`GET /api/v1/memory-timeline/recent` → **501**，detail 如上。

### §3.1-13 登出黑名单持久化单源

- **根因**：双份进程内存黑名单（`api/auth.py` 全局 + `endpoints/auth.py` 局部），
  多 worker/重启全部失效；容量满时整表 `clear()` 连**未过期**撤销项一起放行；
  且 `blacklist_token(token)` 缺省 exp=0.0 的条目永不清理。
- **修复点（最小根修，方案=SQLite 持久化）**：
  - `api/auth.py`：黑名单落 SQLite（数据根 `auth_blacklist.db`，schema 注册
    db_migration `domain="auth_blacklist"` v1，多 worker 共享同一库文件）；
    `blacklist_token` 缺省 exp 时从 token 自身解码，写入顺带清已过期行
    （表内只存未过期撤销项，容量自然有界，不再有整表 clear）；
  - `endpoints/auth.py`：第二份内存黑名单（`_token_blacklist`/`_blacklist_token_local`/
    `_purge_expired_blacklist`）退役，`is_token_blacklisted`/`logout` 全部走单源。
- **红灯/绿灯**：`test_blacklist_register_and_hit`、`test_blacklist_persists_in_sqlite`、
  `test_blacklist_expired_row_purged_on_write`（替换原钉内存实现的
  `TestTokenBlacklist`）先红后绿。
- **live-verify**：`POST /auth/logout` → 200；同 token 再打 `/auth/me` → **401**；
  事后直查 `data/auth_blacklist.db`：revoked_tokens 1 行、user_version=1。

### §3.1-14 mobile_pairing.py 硬编码 WS 密钥

- **根因**：`_DEFAULT_WS_SECRET = "neurova-ws-secret-key-2026"` 写在源码里，
  未配 `NEUROVA_WS_SECRET` 的部署上，读过源码者可伪造 legacy `?token=` 凭证
  （有界：24h 绝对期 + 在册判定）。
- **修复点**：删除硬编码常量；开发环境未配置时改用**每进程随机密钥**
  （`secrets.token_urlsafe(48)`）并显式告警（开发形态显式化）；生产未配置仍拒绝启动。
  legacy `?token=` 通道保留（旧客户端兼容一版）——密钥不可预知后伪造面已闭，
  通道本身处置见"遗留"。
- **红灯/绿灯**：`test_ws_secret_not_hardcoded`（无常量/无字面量/同进程取值稳定且
  非旧常量）先红后绿。
- **遗留（记台账）**：legacy 通道与 ticket 通道并存到旧客户端迁移完成；
  后续可按 §10.2 拍板直接摘除 `?token=` 分支。

### §3.1-15 mobile_pairing.py cancel/status 属主门

- **根因**：撤码/查状态仅要求登录，不校验配对记录属主——任何登录用户可撤他人
  进行中的配对、读他人配对状态（配对码只有 10^6 取值，等枚举预言机的读侧）。
- **修复点**：两端点改 `user_id: str = Depends(_get_current_user_id)`，取记录后比对
  `pairing["user_id"]`；非属主与码不存在**同形 404**（不向非属主确认存在性）。
- **红灯/绿灯**：`test_pairing_cancel_rejects_foreign_user`、
  `test_pairing_status_rejects_foreign_user` 先红后绿（既有 pairing 端点测试
  以属主身份访问，阳性不受伤）。
- **live-verify**：admin 生成配对码后，普通用户 status/cancel → **404**；admin 本人 → 200。

### §3.1-16 computer.py 浏览器状态分用户 + 限量

- **根因**：`_browser_state` 全局单份（A 用户导航 URL 串进 B 用户读数）且
  history 无界增长。
- **修复点**：改按 user_id 隔离（`_browserStateFor`，懒创建 + 用户数 LRU 封顶 64），
  每用户 history 封顶 50；`/computer/status` 的全局 `browser_url` 读数移除
  （无用户上下文的面回任何人 URL 都是串读；前端 URL 展示吃动作流 payload.url，
  不依赖该字段——已核 NeurUI 消费面）。
- **红灯/绿灯**：`test_browser_state_isolated_and_bounded`（隔离 + 双限量）先红后绿。

### §3.1-17 console.py 假成功与死 TTL

- **根因**：①agent 未装配时聊天回 200 + `"Echo: <消息>"`（流式）/200 + 空 reply
  （非流式）——前端把没发生过的回合当成功；②`_get_replay_tail` 先写
  `last_active=now` 再拿它判 TTL，`now-last_active≈0` 恒小于 TTL，过期判定死代码。
- **修复点**：①未装配/查询异常统一 **503** 点名（echo_stream 死分支随之删除）；
  ②TTL 判定改先读旧值、未过期才触碰 last_active。
- **红灯/绿灯**：`test_replay_tail_ttl_check_is_alive`、
  `test_console_echo_fake_success_removed`（源码级钉死）；S1 既有用例
  `test_console_chat_nonexistent_agent_keeps_echo_path` 同步改钉 503 契约
  （更名 `test_console_chat_nonexistent_agent_is_503`）。
- **命中点**：流式与非流式两条腿同批收口。

### §3.1-18 agent_enhancement.py 模拟状态标注

- **修复点**：`AgentStatus` 增 `simulated: bool = False`；agent 无 `get_status` 的
  占位读数回 `simulated=True`（缓存读数同样补标）。
- **红灯/绿灯**：`test_agent_status_simulated_flag` 先红后绿。

### §3.1-19 middleware.py 访问日志 query 脱敏

- **根因**：`"query": str(request.query_params)` 把 `?access_token=` 类令牌整串落日志。
- **修复点**：新增 `redactQuery()`——参数名含 token/secret/password/credential/
  authorization/signature/key 片段（子串匹配，覆盖 access_token/api_key 等）即记
  `名字=<masked:长度>`，非敏感参数原样保留（排障可读性不降）。
- **红灯/绿灯**：`test_redact_query_masks_tokens_keeps_plain` 先红后绿。

### §3.1-20 app.py _get_default_llm 吞异常

- **修复点**：`except Exception: pass` → WARNING 点名原因（兜底返回值保留，
  影响限于默认模型选择，但故障可见可归因）。
- **红灯/绿灯**：随批编译与域测试回归覆盖（日志行为，无独立断言）。

---

## §3.4 技能 / 进化 / 协作 / 渠道

### §3.4-1 neurflow 四节点执行器假成功 → 诚实失败

- **根因**：`exec_evolution` 的 evaluate/optimize 模式、`exec_tdd`、`exec_human_input`
  是 TODO 桩，却回 `score=0.0`/`pass_rate=1.0`/恒 timeout（引擎把 timeout 记正常终结）
  ——编程主链与人工审核踩在占位值上。
- **修复点**：四处改 `status="failed"` + `not_implemented` 错误点名（引擎对 failed
  走与异常相同的失败路径，工作流不再拿假读数继续跑）；learn 模式（真实现）不动。
- **红灯/绿灯**：`test_evolution_evaluate_optimize_not_implemented`、
  `test_tdd_node_not_implemented`、既有 `test_exec_human_input` 同步改钉 failed 契约。

### §3.4-2 collaboration_isolation.py 管理面权限 + 路径 containment + 列表过滤

- **根因**：①`admin_list_all_projects`/`admin_delete_user_projects` 自注"简化处理"
  零权限校验；②`get_project_file_path`/`get_project_workflow_path` 无 containment
  （`../` 逃逸任意文件读写）；③`list_projects` 无 requester 过滤，被
  collaboration_api 四处消费（多用户横向信息泄露）。
- **修复点**：
  - 管理面：构造器增 `admin_checker` 注入口，缺省走 users 表 `role=='admin'`
    （查无此人/非数字 id/库故障一律 fail-closed）；
  - 路径：新增 `_contained_path()`（resolve 后必须落在 base 之下，越界与解析失败
    一律 None，与"不存在"同形防试探），文件/工作流两个取路径口同批接上；
  - 列表：`list_projects` 增 `requester_id` 形参，给定即按"成员或公开"过滤；
    不传保持全量（仅限内部/已鉴权调用方）。
- **红灯/绿灯**：`test_admin_list_rejects_non_admin`、`test_admin_delete_rejects_non_admin`、
  `test_admin_gate_defaults_to_role_lookup`（真实 users 表三分支）、
  `test_list_projects_filters_by_requester`、`test_get_project_file_path_containment`
  先红后绿；既有 admin 用例注入测试替身 checker 保持原意。
- **遗留移交（R1）**：`collaboration_api.py:88/381/426/459` 四个 HTTP 消费点与
  `projects_api.py:153` 传 `requester_id`（isolation 层能力已备好，HTTP 面接线归 R1）。

### §3.4-3 channels/xiaoyi.py 与基类契约修通

- **根因**：①7 处 `self.config.config`（ChannelConfig 无此字段 → AttributeError）；
  ②工厂 `ChannelConfig(channel=…, config=…)` 非法 kwargs；③类未实现基类抽象方法
  `connect`/`disconnect`（实例化即 TypeError）——三条腿加起来渠道每次配置必失败；
  ④未连接发送回 True 假成功。
- **修复点**：`self.config.config`→`self.config.extra`（含 `update_config` 写入腿）；
  工厂改 `channel_type=`/`extra=`；补 `connect()`（走既有 `_init_connection`）与
  `disconnect()`（关 ws + 停接收循环）；未连接发送改如实 False。
- **红灯/绿灯**：`test_xiaoyi_factory_and_signature_use_extra`、
  `test_xiaoyi_send_message_not_connected_is_false` 先红后绿。
- **备注**：ChannelConfig 双定义根因已由 S7 收口，本条基于现状续修。

### §3.4-4 三模板引用的未注册节点类型 → 补齐真实现

- **根因**：document/data_analysis/web_maintenance 三模板引用 7 个 `builtin:*`
  类型（doc-read/doc-write/web-scrape/seo-optimize/broken-link-check/data-analyze/
  data-visualize）在全包零注册，实例化必"未知节点类型"。
- **修复点**：builtin.py 按既有执行器契约补齐 **7 个真实现** + 节点定义 +
  注册表项：
  - doc-read/doc-write：文本类格式直读/落盘（2MB 上限；DOCX/PDF 等二进制如实
    failed not_implemented；写出落数据根 `neurflow_outputs/`，文件名 containment）；
  - web-scrape：出网过 `_validate_outbound_url`（SSRF 单源）+ `_safe_request`，
    抽标题/正文（限量），阻塞 IO 下沉 `asyncio.to_thread`；
  - seo-optimize：启发式体检（title/meta/h1/img alt/词频）出评分与建议清单；
  - broken-link-check：抽链接去重限量（默认 20）逐个探测，出不可达清单；
  - data-analyze：行数据描述统计（计数/缺失/数值字段 min/max/sum/mean）；
  - data-visualize：数值列渲染内联 SVG 柱状图（无第三方图表依赖）。
  复核扩查（教义第 5 条）：media 模板的 `builtin:tts`、ecommerce 模板三类型
  在 drama_nodes/commerce_nodes 节点包已注册（app.py 启动挂载），非缺口。
- **红灯/绿灯**：`test_template_node_types_all_registered`（全模板节点类型对照
  三处注册源并集）先红后绿；`test_web_scrape_blocks_ssrf_target`、
  `test_doc_write_rejects_path_escape` 钉安全边界。
- **决策记录**：选"注册真实现"而非"退役模板"——模板是已发布的用户可点目录，
  退役等于砍掉三类场景；薄实现每一步要么真做、要么如实 failed，不引入假成功。

### §3.4-5 qqbot.py get_channel_config 掩码

- **修复点**：`access_token` 回显改 `"***" if self.access_token else ""`
  （对照 base.py ChannelConfig.to_dict 的 app_secret 掩码约定）。
- **红灯/绿灯**：`test_qqbot_config_masks_access_token`（源码级）先红后绿。

### §3.4-6 wechat_auth.py 签名恒时比较

- **修复点**：`verify_signature` 改 `hmac.compare_digest`（对照同仓
  wechat_kf_crypto/telegram_webhook 范本），入参 `str(msg_signature or "")` 防类型意外。
- **红灯/绿灯**：`test_wechat_signature_uses_constant_time_compare` 先红后绿。

### §3.4-7 skills 静默吞异常 → 诚实暴露

- **修复点**：`executor._get_parameters` 解析失败记 WARNING（空参退化可观察）；
  `skill_install_gate` 注册表读不到时不再当无事发生——fail-closed 记入阻断错误
  （"工具注册表不可用"），安装方据此修环境而非猜白名单。
- **红灯/绿灯**：`test_install_gate_blocks_when_registry_unavailable` 先红后绿。

### §3.4-8 ValidationResult 同名双实现 → 改名消歧

- **处置**：evolution 侧（self_improvement_proposer.py，提案校验，含 warnings）
  更名 `ProposalValidationResult`；dag.py 的 DAG 校验 `ValidationResult` 保留。
  全仓无跨模块同名导入（仅本文件与对应测试），干净改名不留别名。
- **红灯/绿灯**：`test_self_improvement_proposer.py` import 同步更名后全绿。

### §3.4-9 AgentSkillManager 零消费方法退役

- **对比结论**：`acquire_skill`/`suggest_skills_for_task` 生产零调用，仅测试以
  inspect 源码断言引用（审计原话）——死码形态。`search_skill`/`get_skill_status`/
  `analyze_task` 有真实调用面，保留。
- **修复点**：两方法与其专属助手 `marketSourceOf`、失伴 import 一并删除；
  `test_agent_skill_manager.py`/`test_agent_skill_manager_init.py`/
  `test_skill_import_architecture.py` 的 inspect 断言用例改钉"不复活"。
- **红灯/绿灯**：三处 `test_*retired*` 用例先红后绿。

### §3.4-11 collaboration/computer_manager.py 归属判定

- **根因**：`get_computer` 的 admin 判定是 TODO，落成"user_id 以 `@{company_id}`
  结尾即放行"——可伪造后缀绕过属主门。
- **修复点**：收口为**属主或管理员**（users 表 role 判据，fail-closed）；公司后缀
  旁路删除；`user_id` 缺省保留为内部取数通道（daemon 心跳先取数后验配对令牌，
  调用方自行鉴权——已核唯一无 user 调用点 computer_api.py:286 即此形态）。
- **红灯/绿灯**：`test_computer_manager_owner_or_admin`（属主放行/数字非属主拒/
  后缀伪装拒）先红后绿。

### §3.4-12 evolution 静默降级 + channels/manager.py

- **修复点**：
  - `evolution/__init__.py`：四个子模块导入失败除 warning 外登记进
    `_LOAD_FAILURES`，新增 `moduleLoadFailures()` 读数（哪半个包活着有据可查）；
  - `channels/manager.py`：`_instanceLock` 连续两行定义删一（第二份静默遮蔽第一份）；
  - `resolve_session_scope_id`：share=False 分支补 `agent:` 前缀
    （原 `chat_id:sender_id` 把不同 agent 的同群私聊撞进同一会话）。
- **红灯/绿灯**：`test_evolution_module_load_failures_accessor`、
  `test_channel_scope_id_keeps_agent_prefix` 先红后绿。

---

## §3.5 其余后端

### §3.5-3 tool_layers 兜底 ToolOrchestrator 假成功

- **修复点**：导入失败兜底类的 `execute` 改回 `success=False` + 点名
  "真实实现未加载"（该类是 agent_core.py:903 生产实例化来源，中招即全线假成功）。
- **红灯/绿灯**：`test_r4_p2_gates` 源码级断言 + 域回归。

### §3.5-4 同步阻塞调用下沉线程

- **修复点**：`exec_sandbox.executeInSandbox` 非 docker 路径
  `execute_in_sandbox` → `asyncio.to_thread`（subprocess 最长等满 timeout 不再堵
  事件循环）；`browser_manager.ScraplingBackend.navigate` 的同步
  `fetcher.get` → `asyncio.to_thread`。
- **红灯/绿灯**：`test_sandbox_and_browser_use_to_thread`（两处源码级）先红后绿。

### §3.5-5 asr/__init__.py FunASREngine

- **根因**：`try: pass; __all__.append("FunASREngine")`——名字进了 `__all__`
  却从未 import，`from neurova.asr import FunASREngine` 必 ImportError。
- **修复点**：改为真条件导入（funasr_engine.py 顶层无重依赖，numpy 仅
  TYPE_CHECKING）；导入失败不把不存在的名字留在 `__all__`。
- **红灯/绿灯**：`test_asr_exports_funasr_engine` 先红后绿（基线 ImportError）。

### §3.5-6 user_model.py 更新日志泄字段值

- **修复点**：`logger.info("Updated user %d: %s", user_id, kwargs)` → 只记
  `sorted(kwargs.keys())`（kwargs 可含 password_hash）。
- **红灯/绿灯**：`test_user_model_update_log_only_field_names`（源码级）先红后绿。

### §3.5-7 qclaw app_secret Base64 可逆落库 → Fernet 加密

- **根因**：生产构造 `QClawBindingModel()` 不传 encryption_key → `_encrypt_secret`
  走 Base64"加密"（可逆编码）落库。
- **修复点**：新增 `_resolve_default_encryption_key()`——env
  `NEUROVA_QCLAW_ENCRYPTION_KEY` 优先，否则数据根专属密钥文件
  `.qclaw_secret_key`（首次生成、0600 持久化、重启稳定）；构造器缺省即取，
  Fernet 成为生产默认路径；解密侧保留 Base64 回退（旧行可读，向后兼容）。
- **红灯/绿灯**：`test_qclaw_secret_encrypted_at_rest`（密钥自动解析、密文非
  Base64 明文、往返一致、旧 Base64 行可读）先红后绿；既有
  `test_encrypt_is_deterministic` 同步改钉"同文异码"（Fernet 随机 IV 是安全属性，
  旧确定性恰是可逆编码的罪证）。

### §3.5-8 cost_budget.py 空实现告警通道谎报已通知

- **修复点**：`_slack_alert`/`_email_alert` 如实抛 NotImplementedError；
  `_send_alert` 逐通道记录 `channel_status`（sent/not_implemented/failed）进告警
  历史（/alerts 读者可分辨"送达"与"未实现"）；DEFAULT_ALERT_THRESHOLDS 摘除
  SLACK/EMAIL（未实现不默认注册，LOG 通道真实可用）。
- **红灯/绿灯**：`test_cost_budget_alert_channel_status_honest` 先红后绿。

### §3.5-9 cost_tracking.py CostTracker（PostgreSQL 形态）退役

- **对比结论**：`CostTracker`（db_pool.acquire/`$N` 占位符）生产零消费，在役记账
  是 cost_store.py SQLite 实现（`record_llm_cost` 单一入口）；零调用仅测试引用。
- **修复点**：删 `CostTracker` 类与 `get_cost_tracker`/`reset_cost_tracker` 单例；
  `test_cost_tracking.py`（整文件仅测该类）删除；
  `test_cost_persistence.py`/`test_cost_budget_ledger_boundary.py` 摘除
  reset 调用（其余断言不动，protected 清单内文件保持绿）。
- **红灯/绿灯**：`test_cost_tracker_retired` 先红后绿。

### §3.5-10 mcp_oauth.py DCR 传输形态统一

- **修复点**：注入 transport 分支 `data=payload` → `json=payload`（RFC 7591
  注册体是 JSON，与 httpx 生产分支同形；token 端点的表单 `data=` 不动）；
  测试桩 `_FakeTransport`/`_FailingTransport` 同步收 `json=`，DCR 断言改读
  `["json"]`。其间修正桩内形参名遮蔽模块 `json` 的连带伤。
- **红灯/绿灯**：`test_mcp_dcr.py`/`test_mcp_oauth.py` 33 用例全绿。

### §3.5-11 mcp_client.py 防火墙 fail-open → fail-closed

- **修复点**：`_check_firewall` 对非 PermissionError 异常改抛
  `PermissionError(..., fail-closed)`（带原因链）——内部 bug 不再变成"允许执行"。
- **红灯/绿灯**：`test_mcp_firewall_fail_closed` 先红后绿。

### §3.5-12 aigc_studio/services.py 硬编码管理员旁路

- **根因**：`store.get_project(pid, "admin", is_admin=True)` 两处——服务层绕开
  HTTP 面已做的属主校验（纵深缺口）。
- **修复点**：`generate_shot_images`/`generate_asset_images` 增 `user_id`/`is_admin`
  形参按真实请求者取项目；studio_api 三处调用点（generate-images、asset-images、
  retry-storyboard）透传 `_uid(current_user)`/`_is_admin(current_user)`。
- **红灯/绿灯**：`test_aigc_services_no_hardcoded_admin_bypass`（源码级）+
  `test_studio_api.py` 替身签名同步、`test_studio_core.py` 直调补身份，先红后绿。

### url_guard 合一（S2 移交，教义第 6/7 条）

- **对比结论**：security 版（抛异常、显式阻断网段表、DNS fail-closed、allow_private）
  判据更完整；knowledge 版（布尔 API、trusted_hosts 信任名单、localhost 快速拒绝）
  有两个独有能力；两份都不处理 IPv4-mapped IPv6（`::ffff:127.0.0.1` 可绕）——
  neurflow builtin 的第三份实现反而有归一处理。
- **修复点**：三份能力并进 `neurova/security/url_guard.py` 单源：
  `assert_public_url(url, *, allow_private, trusted_hosts)` 为主判据
  （新增 trusted_hosts 豁免、localhost 快速拒绝、mapped-IPv6 归一）；
  `validate_public_http_url(url, trusted_hosts)` 作为 knowledge 域兼容布尔 API
  落在同一份判定上；阻断网段表保持唯一口径（含 198.18.0.0/15 fake-ip 刻意放行，
  不叠加宽泛 is_private 属性判定——那会把该例外一起拦掉）。
  消费方接线：knowledge_ingestion/knowledge_mcp_source/webhooks/ingest_bridge/
  knowledge.py（re-export 别名）五处 import 改指单源；
  `neurova/knowledge/url_guard.py` 退役删除。
- **红灯/绿灯**：`test_url_guard_single_source_and_semantics`（旧模块 find_spec=None、
  九类语义含 mapped-IPv6 与 DNS fail-closed）先红后绿；既有
  `test_url_guard.py`（含 fake-ip 例外）与 `test_s2_webhook_ssrf_guard.py` 全绿。

---

## 自证汇总

- **红灯**：`tests/unit/api/test_r4_p2_gates.py` 对基线代码（git stash 本批源码后）
  实测 **36 failed / 2 passed**；恢复修复后 **38/38 全绿**。
- **绿灯（域回归）**：tests/unit/{api,notifications,security,channels,skills,evolution,
  models,tools,collaboration,neurflow,aigc_studio} + tests/execution_engine 共
  11000+ 用例；本批引入的失败 0；测试同步修正 14 处（钉旧放行/旧桩形态的用例
  改钉新契约，详见上文明细）。
- **live-verify**：真后端（start_server.py，127.0.0.1:9531，启动日志除环境性
  MCP filesystem 重连外无 [ERROR]，`Registered router: /v1/providers` 在位）上以
  服务端同口签发的普通/管理员令牌实测 **14/14 PASS**：logs 403/200、
  memory-timeline 501、scheduler 403、pairing 404/404/200、share 404、
  logout→me 401（黑名单 SQLite 落库实证 revoked_tokens=1 行）、push 404。
- **净 LOC**：生产池 +1315/−715（净 +600），测试 +951/−901。
  去向：①neurflow 7 节点真实现 +613（模板可用性，见 §3.4-4 决策记录）；
  ②url_guard 三合一净 +65（含退役 knowledge 份 −64）；③属主/管理员门与
  containment 约 +180；④黑名单 SQLite 单源净 +65（删第二份内存实现 −27）；
  ⑤诚实化（501/failed/掩码/脱敏/标注）约 +60；⑥退役清理 −360
  （CostTracker −227、agent_skill_manager −134、share_tool −25、memory_timeline
  旧占位 −47 等）；⑦qclaw 密钥通道 +41；⑧其余修复与注释散布。

## 遗留与移交

1. **collaboration_api.py 四处 + projects_api.py 一处 `list_projects` 未传
   requester_id**：isolation 层过滤能力已落地（默认不传保持旧口径），HTTP 面接线
   归 R1（collaboration_api.py 属其文件域）；projects_api.py 无属主会话，建议总控分派。
2. **legacy `?token=` WS 通道**：伪造面已因每进程随机密钥闭合；通道摘除待旧客户端
   迁移后按 §10.2 拍板。
3. **预存失败（非本批引入，A/B 与代码归属佐证）**：
   - R1 在途（neurflow_api 鉴权/属主门）：test_cancel_execution_success、
     test_draft_run_publish×2、test_domain_split_contract、test_store_oauth×4；
   - S1 已合入门控的连带（default agent 收紧）：test_ekb_user_outcome_attach×3
     （feedback 以非属主打 default 现回 403，建议测试身份升 admin，归 S1/总控）；
   - R3 域：test_model_connection_contract（anthropic check_connection 真连
     127.0.0.1:1 环境性失败）；
   - 其他：test_webhooks_persistence×4、test_evolveRealArmPathAndBudgetGate×4、
     test_authSurfaceFreshness×2、test_route_mount_contract_guard×2、
     test_mobilePairingQrSameOrigin、test_model_capability_endpoints、
     test_metrics_http_and_exposure（S1 台账既有清单）、
     test_llmClientCarriesTheThreeCallSiteWrites（llm_client 装饰器数漂移，非本批）、
     test_tool_closed_loop（tool_executor 技能打包触发，非本批）、
     test_scripts_start（环境性）。
4. **evolution 降级读数**：`moduleLoadFailures()` 已可查；接入健康面（/health 或
   诊断脚本）留给后续小批。
