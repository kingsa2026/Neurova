# Neurova 全库代码审计报告（2026-11-16）

> **基线**：`main` @ `3923d218e`（2026-11-16）。工作树含 2 处未提交改动（Mobile/harmony 两文件，专审见 §9）。
> **范围**：全库逐文件——`neurova/` 后端 25 个子包、`NeurUI/src/` 前端、`Mobile/harmony/`（ArkTS）、`Mobile/android-native/`（Kotlin）、`tests/`、`scripts/`、CI/部署配置（`.cnb.yml`、`.github/`、`helm/`、docker）、根脚本。
> **方法**：10 个域切片并行只读审计（逐文件 Read ＋ 全量机械 grep 扫描）；**P0/P1 发现由主审逐条复验，13/13 抽验全部坐实**；凡"零调用/死码"断言一律附全仓 grep 证据（排除 tests/、docs/、路由注册、getattr/字符串动态引用）。全程零写入、零安装、零测试执行。
> **与上轮关系**：对 [全库断点断链与死码审计_2026-11-12.md](../docs/全库断点断链与死码审计_2026-11-12.md) 全部 50 条逐条复核（§6）：**51 条已修复、3 条部分修复、0 条仍存在**。本报告 = 上轮旧账复核 ＋ 11-12 之后的全库增量扫描 ＋ 移动双端首次全量审计。
> **复核状态（2026-11-16 第二轮独立复核）**：已按 10 个只读核查组分域逐条复核＋P0 逐行复验——**137/147 属实、9 部分属实（核心问题仍在，细节已就地修订）、1 条含不实子项**；统计数字全部精确复现。勘误已回写正文，汇总与新增命中点见 §11。

---

## 0. 总览

### 0.1 分级统计

| 级别 | 数量 | 判定口径 |
|---|---|---|
| P0 | 2 | 安全漏洞 / 核心功能确定性全废 |
| P1 | 39 | 功能错误、断链、鉴权敞口、事件循环阻塞、死码群、CI 引用失效 |
| P2 | 106 | 次要缺陷、诚实性、规范偏离、仓库卫生 |
| **合计** | **147** | |

类型分布（约）：鉴权/越权 16、契约错位 16、断链/死码群 14、bug 13、事件循环阻塞 4、诚实性/假成功 11、仓库卫生/资源 9、并发 6、规范/其余 58。

### 0.2 覆盖统计

| 域 | 清单文件数 | 精读 | 机械扫描/抽查 | 未覆盖 |
|---|---|---|---|---|
| neurova/api | 150 | 150 | — | 0 |
| neurova core/agent/llm/context ＋ 顶层 .py | 277 | 277 | — | 0 |
| neurova knowledge/memory/memory_ingest/cognitive_layers | 272 | 35 全读＋31 段读 | 272 全量 9 类风险模式扫描 | 中小文件未逐字读（grep 兜底） |
| neurova skills/evolution/collaboration/channels/security | 307 | 301（全部 .py） | 6 资源归类 | 0 |
| neurova 其余 16 子包＋models/embedding/config＋根脚本 | 184 | 125 | 全量 grep | 0（2 个大文件读关键段） |
| NeurUI 页面/组件/路由/布局 | 320 | 112 | 208 全量七维扫描 | 0 |
| NeurUI 基础设施（api/stores/utils/i18n…） | 371 | 27 精读＋12 抽查 | 237 个 API 调用点全量比对 | i18n 词典正文（由守卫测试代理） |
| Mobile harmony＋android＋signing | 362 | 145＋5 段读 | 67 抽查 | 87 个 ohosTest 未逐字读 |
| tests/scripts/CI/部署 | 3100+ | scripts 82 全部 ast 校验＋19 测试抽样 | tests 导入面 100%（743 行/223 模块）、protected 清单 100% comm | tests 正文未逐字读 |
| 上轮 50 条复核 | 54 项 | 全部重新取证 | — | 0 |

代码文件总量约 5227 个（py 4230 / ts 522 / ets 248 / vue 169 / kt 58）。〔复核实测吻合：排除 node_modules/.git/.venv/build 与 `src-tauri/resources` 打包副本、`data/` 运行数据后逐项精确命中。〕

### 0.3 修复路线建议（按批次；动手前需拍板项见 §0.4）

1. **安全批**：P1-1～P1-7（console/agent/防火墙/插件/media 属主与 admin 门、webhook SSRF、验证码形态门控）；P0-1 主密码构建期注入（§6-171 裁定在案，需拍板）；P1-14 温度通道隔离补齐。复核增补同批：neurflow SSE `/executions/{id}/events` 匿名订阅敞口、plugin uninstall/disable、console.py 其余约 8 处无属主门 `get_agent_instance` 命中点（见 §11）。
2. **移动端契约批**：P0-2（安卓心跳 JSON 化＋pong 跟踪）→ P1-28/29（HttpAdapter 边界统一信封归一，一处基建修十页）→ P1-30/31/32（双 /v1 路径、settings 形状、pin 字段）→ P1-36（凭证持久化）。
3. **稳定性批**：P1-8（benchmark 500；`/benchmark/compare` 同款 None 求和同批修）、P1-16/17（渠道与技能装配的事件循环阻塞，7＋1 个命中点按教义第 5 条一次扫平）、P2 并发群（锁外迭代、check-then-act、非原子写）。
4. **前端功能批**：P1-22/24/25/26（FilePage/ModelPage/KnowledgePage/EnterpriseSources 四处功能错误）、P1-23＋P1-27（健康域词汇收口＋死店处置；P1-23 验收判据按"消除恒 healthy 假绿"）。
5. **死码退役批**（教义第 7 条：对比→取长补短→接线→退役）：P1-11/12/13/18/20/33/37 死码群约 1.6 万行（复核修订后口径；P1-12 原列 initialization_manager/preset_templates/subagent 三个活码已剔除，**不得整批删**）；P2 死码散点同批（`tests/cognitive_body_store.py` 系活 fixture，不在其列）。
6. **仓库卫生批**：P1-19（import tests 下沉）、P1-21（双份模型二进制）、P1-38/39（CI 失效引用）、P2 gitignore 三目录、node 版本、死 npm script。

### 0.4 待拍板项（均需决策影响面后执行）

| 项 | 选项与影响 |
|---|---|
| P0-1 主恢复密码 | 维持 §6-171 裁定（源码含密码，靠"不发版"兜底）vs 构建期环境注入（分发包不再含密码；需改构建链）。建议后者。 |
| P1-6 验证码 dev_code | 桌面形态已裁定诚实返回（上轮 P2-3 修复）；服务端形态是否强制 SMTP/关闭自注册。不改则服务器部署可脚本化造号。 |
| P1-11/12/13/18/20/33/37 死码群 | 逐个"接线 or 退役"。鸿蒙 15 个死页面后端端点大多存在，接线可换来真实功能；不接线应连测试一并退役。复核注：P1-12 剩 matrix/、capability_discovery、legacy_stream_reader、MessageQueue/MessageSerializer；initialization_manager/preset_templates/subagent 为活码已剔除。 |
| api-P2-1 skill_pool/marketplace 共享 agent 资产 | 文件头自述"agent 是登录用户共享的运行时资产"，与 H-W0 属主单源口径冲突；需产品裁定后统一。 |
| fe-P2-4 渠道启用/禁用按钮只翻本地 | 两页一致、注释自述"保存时落盘"——改文案或改点击即落库，二选一。 |
| core-P2-11 crash_report 默认外发 | 默认关（对齐设置页 telemetry 口径）或维持默认开并明示。 |

---

## 1. P0（2 条）

### P0-1 [安全-后门凭据] 硬编码管理员恢复密码挂在免鉴权公开端点上

- **位置**：`neurova/api/endpoints/auth.py:73`（`MASTER_RECOVERY_PASSWORD = "neurovamakehappy"`）、`neurova/api/global_auth.py:40`（`/api/v1/auth/recover-password` 在免 JWT 白名单）、`auth.py:351-404`（实现）。
- **证据**（主审已验；复核逐行再证）：命中双条件即可重置任意 admin 密码并返回成功；限流仅按 (username|ip) 5 次/15 分钟。
- **影响面**：源码与打包产物分发即等于管理员凭据分发。
- **裁定背景**：文件内 §6-171（2026-10-13 用户裁定）明确接回此形态并注明"不要把这份构建放出去"——裁定在案，但风险本身成立。
- **修复建议**：保留裁定语义的前提下改构建期环境注入（分发包不含密码常量）；命中后强制改密＋通知全部管理员＋审计事件升 CRITICAL。

### P0-2 [功能全废-移动] 安卓 WS 心跳双缺陷：流式对话每次跨越心跳边界必断

- **位置**：`Mobile/android-native/app/src/main/java/top/neurova/mobile/core/net/MobileWsChannel.kt:116-128`；后端 `neurova/api/endpoints/mobile_pairing.py:1396-1405`。
- **证据**（主审已验；复核逐行再证）：客户端发**裸文本** `ping`；后端 `json.loads(data)` 后才判 `message.get("type") == "ping"`——`json.loads("ping")` 抛异常落入 except，连接被服务端拆掉。且客户端发完 ping 无 pong 跟踪，`delay(10s)` 后**无条件** `close(1006, "pong-timeout")`。复核补充佐证：后端 pong 为 JSON 帧 `{"type":"pong",...}`，安卓端 `text == "pong"`（:178）即便收到也匹配不上。
- **影响面**：安卓端聊天流式在任何超过 ~30s 的回合必被掐断重连，`chat:chunk` 流中断；确定性复现。鸿蒙端发的是 `{"type":"ping"}`（WebSocketAdapter.ets:47），两端心跳协议不同源。
- **修复建议**：客户端改发 `{"type":"ping"}` JSON 帧；心跳循环按 pong 收到标记判定超时；两端心跳报文统一到同一契约。

---

## 2. P1（39 条，按域）

### 2.1 后端 API（9 条）

**P1-1 [鉴权敞口] console 聊天面（HTTP+WS）绕过 Agent 属主执行门**
`endpoints/console.py:776`（POST /api/v1/console/chat 直接 `get_agent_instance(agent_id=body.agent_id)`）、`:2514`（WS 腿固定默认 agent）。全文件 grep `can_access_agent|requireAgentOwner` 0 命中（主审已验；复核再证）；对照 `chat.py:313` 的属主门。任何登录用户可驱动他人私有 agent（工具/工作区/额度），WS 腿则把无主默认 agent 供任意非 admin 用户对话——同一 agent 走 `/v1/chat` 403、走 console 200。修复：两入口复用 `agent_access` 属主门。复核补充：全文件另有约 8 处无属主门 `get_agent_instance`（chat/review:1292、auto-title:1726、回合操作 :1912/:2013/:2046/:2079、feedback :2257/:2272），文件内已有 `_check_session_ownership` 可复用，应同批收口。

**P1-2 [鉴权敞口] agent.py 五个 agent 级端点缺属主门**
`agent.py:879`（POST /{id}/switch，改**全局**默认 agent）、`:944`（decision，驱动任意 agent 跑 LLM）、`:989`（rebuild-loop）、`:923`（PUT constitution）、`:846`（GET stats）。均仅 `get_current_user`；同文件 list/get/update/delete 已有 `can_access_agent`。修复：同批补门，switch 仅 admin。复核补充：`/switch` 改的进程级全局默认 agent 正是 console WS 腿 `get_agent_instance()` 的取值源——与 P1-1 构成"任意用户把全局默认切到他人私有 agent 再供 WS 用户对话"的越权链，量级上调。

**P1-3 [鉴权敞口] 防火墙/限流规则任意登录用户可改**
`endpoints/firewall.py:25,172,254,347`。router 无 `require_admin`；普通用户可封禁他人 IP/路径、把全站限流改成 1/min（DoS）、给自身加白。修复：整个 router 换 `require_admin()`。

**P1-4 [鉴权敞口/代码执行] 插件装载面未限管理员**
`endpoints/plugin.py:59,331,381,393,404`。文件头自述"这套**不是沙箱**：能装载即能在进程内执行任意代码"，而 install/load/unload/enable 仅登录门；授权/路由挂载（:489/:525）却收 admin——两道门不一致。修复：装载面全升 admin；远程源 fetch 加人工确认。复核补充：`uninstall`(:368)、`disable`(:419) 同为仅登录门，应同批收口；远程安装实际被 `_REASON_TO_STATUS["remote_source"]=501` 拦死，"远程源人工确认"属前瞻项而非现存敞口。

**P1-5 [SSRF] webhook 测试端点向任意 URL 发起服务端 POST**
`endpoints/webhooks.py:153-192`。url 由 create/update 任意指定，无 `validate_public_http_url`（对照 `knowledge_ingestion.py:241` 同名校验、`tool_layers.py:246-259` 的 `assert_public_url` 均有）。可探测内网（169.254.169.254、localhost），响应码回显构成预言机。修复：三处统一过 url_guard（收口到 `neurova/knowledge/url_guard.py` 单源）。

**P1-6 [鉴权绕过] 注册验证码明文随响应返回，服务端部署形态可脚本化造号**
`endpoints/auth.py:705-714`（主审已验；复核再证：`data.dev_code` 无条件返回，全文件无 SMTP/发信代码路径）。桌面形态是上轮 P2-3 的既定修复（诚实返回、不落日志）；敞口在服务端形态：先取码再注册即可绕过邮箱验证，仅剩 IP 限流屏障。修复：按 `_isServerFacingDeployment()` 门控——服务端不回 dev_code、接 SMTP 或关闭自注册（:605 首账号引导令牌门已用同一判定，落点现成）。

**P1-7 [IDOR/鉴权敞口] media.py 全面缺属主校验，配置面未限管理员**
`endpoints/media.py:40`（router 仅登录）、`:579/:654`（按 id 读任意媒体）、`:674/:516`（删/批量删任意媒体）、`:494`（PUT /config 可改 `storage_path` 决定后续落盘根）、`:769`（清空索引）。写入侧记录了 `user_id`（:420），读删侧从不比对（对照 `files_api.py:206` 属主 404 同构）。修复：复用 files_api 属主单源；config/cache 收 admin。复核补充：`storage_path` 收绝对路径后 `/save` 的防逃逸检查以新根为基准，配合可控 filename 具备"任意写"要件，修复优先级建议按偏上处理。

**P1-8 [功能错误] benchmark 运行历史聚合端点必 500**
`endpoints/benchmark.py:214-217`（主审已验）：每次 run 的 `score` 恒为 `None`（:130），`sum(r["score"] for r in runs)` 对 None 求和抛 TypeError，无 try 包裹。只要有过一次运行记录，`GET /api/v1/benchmark/agents/{id}` 必 500（精确说：对该用户名下该 agent 有运行记录的本人必现）。修复：过滤 None，全 None 时如实返回 `avg_score: None`。复核补充：`POST /benchmark/compare`（:255-256）有同款 `sum(r["score"] ...)`/`max(...)`，且 `r.get("avg_latency_ms", 0)` 因键存在值为 None 同样炸——同根因第二命中点，须同批修。

**P1-9 [假成功] 附件端点 TODO 桩谎报"已添加"**
`endpoints/chat.py:884-913`：`# TODO: 实现附件处理` 后直接返回 `{"code": 0, "message": "Attachment added"}`——不校验、不落库、不处理。同文件 DELETE /history 已改为显式 501（raise 在 :874）〔复核注：原引 :851 为 docstring 起句，行号微漂〕，本端点漏改。修复：改 501 并点名未实现，或接 files_api 附件登记链。

### 2.2 core / agent / llm / context（4 条）

**P1-10 [断链/假成功] LLM 分诊门是"永远放行的坏探针"**
`neurova/llm/triage.py:318`（`_fetch_conversation_history` 直接 `return []  # Mock`，主审已验；复核再证）；根因之一 `neurova/llm/sandbox/security_sandbox.py:73` 日志引用**不存在的字段** `self.quota.rate_limit_requests_per_minute`（实际 `max_requests_per_minute`）→ 每次构造 `OpenAIAdapter` 必 AttributeError → `triage_message` 统一吞成 `actionable=True, reason="triage_error"`。且 `OpenAIAdapter._execute_openai_call` 是 `"Mock response from OpenAI"` 假实现。影响面：`/v1/coordination/triage/*` 恒走异常分支，开启 actionability 门控后分诊恒"可行动"、门控等于不存在（默认门控关闭，现网无行为损害）。修复：补字段名/接真实历史源/接真客户端，修不动的分支以诚实错误暴露而非 fail-open。复核补充：fail-open 不止异常分支——`no_history` 分支（triage.py:154-161）同样恒放行，`:171-172` 用 `'true' in result.content.lower()[:50]` 判定属第三重脆弱点，修探针时应一并收口。

**P1-11 [死码群] core 包零消费方模块簇约 3,100 行**〔复核修订：原列 `+ConfigManager+LogManager` 实为 `core/config.py`、`core/logger.py` 的全仓活依赖（get_logger 满仓在用），已剔除；行数按 8 个死码模块实测重算〕
`core/api_router.py`(323)、`module_tracker.py`(552)、`api_standard.py`(420)、`workspace.py`(304)、`user_workspace.py`(451)、`service_manager.py`(360)、`state_manager.py`(395)、`settings_manager.py`(332)。全仓 grep（排除 tests/docs/路由注册/动态引用，含绝对/相对导入、importlib 字符串、`core/__init__.py` 转出核查）生产命中 0（唯一命中 `base_module.py:33` 为注释提及）。与在役实现构成第二份定义（教义第 6 条），部分还带测试形成"有测试但生产不接线"的假保障。修复：按教义第 7 条逐个对比后退役，有用能力并入现役出口。

**P1-12 [死码群] agent 包零消费方模块簇约 1,375 行**〔复核修订：原列 `initialization_manager.py`、`preset_templates.py`、`subagent.py` 经复核实为**活码**——分别被 `agent_core.py` `init_all()` 链、`agent/templates/`（collaboration_template→`/teams/orchestrate` 活链）、`spawn_subagent`→tool_executor 消费，已剔除，**不得退役**〕
`agent/matrix/`(561)、`protocols/capability_discovery.py`(449，文件内自证未接线，唯一消费者是已死的 matrix，连带死码)、`legacy_stream_reader.py`(123)、`MessageQueue`/`MessageSerializer`（`message_protocol.py:315/366`，类级零消费，含 `get_message_queue` 工厂无人调）。与在役 swarm/subagent 语义重叠，最易造成"改了不生效"。修复：同教义第 7 条。

**P1-13 [死码] llm 包离线孤岛与孤儿类型**
`llm/providers/capability_cache.py`(253 行，文件头自述生产零消费，仅测试引用)；`llm/providers/types.py` 的 `ProviderInfo` 与 API 层同名 DTO 双定义（生产代码无 `from ...providers.types import ProviderInfo`；仅 tests/unit/api/test_pydantic_v1_compat_helper.py:141 一处测试 import）。修复：接线或与测试同退；`ProviderInfo` 收口为一份。

### 2.3 知识 / 记忆 / 认知（1 条）

**P1-14 [鉴权敞口/跨人串忆] 温度通道绕过三层隔离，同 agent 库内跨 neuser/user 记忆可被任意登录用户检索**
- **位置**：`neurova/cognitive_layers/memory_layer/manager.py:3009-3012`（`get_top_memories_by_temperature`）；消费链 `neurova/cognitive_layers/memory_layer/neurova_recall.py:1194-1206`（`_channel_temperature`）→ `neurova/api/endpoints/enhanced_memory_search_api.py:98-101`（`POST /api/v1/enhanced-memory-search/search`，仅登录门）。
- **证据**（主审已验；复核再证）：`SELECT * FROM memories ORDER BY temperature DESC LIMIT ?`——SQL 无 `agent_id/neuser_id/user_id` 条件、无 `lifecycle_stage` 条件；对照同文件 `searchMemoriesFulltext`（:770-793）显式带三元组并经 `isOwnedByRequestScope` 仲裁。`recall_flat` 默认全通道（含 TEMPERATURE），结果未再过请求作用域过滤。
- **影响面**：同 agent 库内用户 A 可检索到用户 B 的高温记忆**原文**（返回 content 全文）；已遗忘记忆也进 Top-N。聊天主路（`memory_manager.recall`）不受影响；泄漏以 agent 库为界。
- **修复建议**：在 SQL 生产侧补三元组过滤＋`lifecycle_stage != 'forgotten'`，取出后仍经 `isOwnedByRequestScope` 仲裁（教义第 1 条：根因处修，不在端点补丁）。该函数全仓仅 neurova_recall.py:1195 一个消费方，SQL 侧单点闭环即可。

### 2.4 技能 / 进化 / 协作 / 渠道 / 安全（4 条）

**P1-15 [路径穿越/任意写] 技能市场安装链对 skill_name/文件名缺统一校验**
`neurova/skills/hub_client.py:686`（`skill_dir = self._installed_dir / skill_name`，skill_name 来自远端市场数据，主审已验）、`neurova/skills/skill_service.py:846`（URL 安装名直拼路径，:855 登记清单同用该名）；对照同文件本地安装已有 `_SAFE_SKILL_ID_RE` 闸（:27,:685）——URL 分支漏掉同一道闸（教义第 5 条同契约未扫平）。另 `api/endpoints/skill_pool_api.py` `install_from_zip` 用未消毒的 `file.filename` 拼路径（:954/:961）。缓解项：zip/tar 解包已有 `safe_extract_zip/tar` 防 slip，但目录名本身仍可 `..` 越界。修复：校验下沉为 `hub_client.install_skill` 入口统一闸（目录名与登记路径同批覆盖）；zip 落盘名改服务端随机名。

**P1-16 [事件循环阻塞·群] 七个渠道适配器在 async 发送路径直调同步 HTTP**
`channels/discord.py:278`（主审已验）、`qq.py:332/341/354`、`qqbot.py:225→260`、`wechat.py:135→wechat_messaging.py:98/121/168/227`、`qclaw.py:159→qclaw_service.py:193`、`telegram_adapter.py:334→telegram_sender.py:70→telegram_api_client.py:32`、`voice.py:89`。`ChannelManager.send_message` 是所有渠道回复与工作流审批通知的唯一出口，跑在主事件循环上——上述渠道每发一条消息可阻塞主循环 10-30 秒，全进程请求排队（工作流审批通知链路同被放大）。同仓 `feishu.py:611`、`qq_ws.py:391`、`mqtt.py:420`、`wecom.py:342` 已用 `asyncio.to_thread` 修好同病。修复：按教义第 5 条一次扫平 7 个命中点（voice.py 的 sms 分支与 calls 分支同方法，一并覆盖）。

**P1-17 [事件循环阻塞] 技能自动装配链在聊天主链上同步执行（18s+）**
`neurova/skills/agent_skill_manager.py:145`（async `analyze_task` 直调同步 `analyzer.analyze_and_acquire`）→ 消费点 `neurova/agent/chat_pipeline.py:1461`；底层 `market_searcher.py` 同步 urllib 聚合搜索（`MARKET_SEARCH_AGGREGATE_SECONDS=18`）＋`hub_client.py:217` `time.sleep` 重试。每轮聊天可阻塞主循环 18s+。`search_all_markets_async` 已备而未用。修复：`await asyncio.to_thread(...)` 或改接 async 搜索。

**P1-18 [死码群·安全包] security 包三个治理模块零生产消费方约 1,770 行**
`security/constitution.py`(416)、`autonomous_assessor.py`(560)、`compliance_reporter.py`(794)；另 `approval_manager.py:958` `generate_approval_html` 无路由无调用（仅测试引用；approval_manager.py 本体是活码，`agent_core.py:731-738`、`tool_executor.py:347,2211,2244` 在用）。读者会误以为宪章/自治评估/合规报表功能存在。修复：接线或连测试一并退役。

### 2.5 其余后端与仓库资源（3 条）

**P1-19 [断链/部署风险] 生产核心代码 import tests/ 包**
`neurova/tool_executor.py:43`、`neurova/security/safe_expr.py:37`、`neurova/workflow/scripted/validator.py:67`（主审已验；复核再证）：`from tests.ast_scan import parseSource`。`tool_executor` 是全部工具执行的咽喉；任何不打包 tests/ 的发布形态（wheel、仅含 neurova/ 的镜像）在 import 期即崩——工具执行、安全表达式、受限脚本工作流三条链一起废；且 tests/ 整根 gitignore 豁免（AGENTS §4），测试根反向成为运行时事实源。修复：`ast_scan` 下沉到 `neurova/`（如 `neurova/core/ast_scan.py`），tests 留薄转发，三处 import 同批改。复核注：`tests/ast_scan.py` 仅依赖 stdlib、文件头自述"全仓解析唯一出口"且有守卫测试——属有意设计，真实代价是打包/部署面（分层倒置），根修是迁移共享模块而非在调用点加 try/except；另 scripts/ 下还有 6 处同契约 import（ci_static_gate、generate_api_inventory、ci/architecture_check、ci/cognitive_component_table、ci/context_deadline_ledger、ci/tool_loop_deadline_ledger），收口时一并裁定。

**P1-20 [死码群/双实现] EnhancedUserModel 整文件零消费，与 UserModel 构成第二套用户体系**
`neurova/auth/enhanced_user_model.py`(533 行)：`get_enhanced_user_model()` 生产代码 0 消费（仅 tests/auth/test_enhanced_user_model.py:170-172 引用）；`enhanced_users_api.py` 实际用 `neurova.auth.user_model.UserModel`。一套完整独立用户存储（users.json＋PBKDF2-100k＋锁定逻辑）无运行时消费者，密码哈希格式与在役库互不兼容。修复：按教义第 7 条退役（含 `auth/__init__.py` re-export）；若有存量数据先落迁移脚本。

**P1-21 [仓库健康/资源] 模型二进制双份跟踪重复，另有第三份打包副本**〔复核修订：原"LFS 从未真正接管"表述不成立〕
`embedding/bge-small-zh-v1.5/`（184M）与 `models/embedding/bge-small-zh-v1.5/`（274M，主审 du 已验）内容重复——复核实证：两份大文件 LFS OID 相同（safetensors `354763b9b1`、bin `7c5fe667bb`），字节级一致；git 历史中是 **LFS 指针**（`.gitattributes` filter=lfs 已生效、`.git/lfs` 按 OID 去重 277M），工作树二进制是 LFS checkout 的正常形态。另 `NeurUI/src-tauri/resources/backend/models/embedding/bge-small-zh-v1.5/` 有 274M 未跟踪打包副本（target/debug、target/release 同）。影响：工作树体积无谓膨胀（两份跟踪＋一份打包副本）；双份落点违反单一事实源（`model_downloader.py` 口径是 `models/embedding/`）。修复：删除顶层 `embedding/`，并清点 src-tauri 侧副本来源（防再生长）；评估 release 附件承载，配合 `model_integrity.py` sha256 清单。

### 2.6 前端（6 条）

**P1-22 [逻辑错误] FilePage「打开」按钮把 ref 当函数调用，预览功能全废**
`NeurUI/src/pages/FilePage.vue:55` 模板 `@click="previewFile(record)"`、`:111` `const previewFile = ref<any>(null)`、`:174` 真实现叫 `previewFileFn`（全文件无引用，主审已验）。点击必抛 TypeError，预览不可用；`previewFileFn` 成死码。修复：模板改绑 `previewFileFn`（或函数改名 `previewFile`、ref 改名 `previewTarget`）。

**P1-23 [契约错位] 健康域状态词汇前后端错位——健康页/总览页读数失真**
后端枚举 `healthy/degraded/unhealthy/unknown`（`neurova/core/health_checker.py:36-40`）；前端类型却是 `'pass'|'warn'|'fail'`（`NeurUI/src/api/modules/health.ts:17`，主审已验）。后果（复核修订：axios 拦截器已解包信封，页面拿到的 `res` 是裸数据，`res?.data` 为 undefined → `checks=[]` → `[].every()` 恒真 → HealthPage 总体状态**恒 'healthy' 假绿**、检查列表恒空——无数据也亮绿灯，比"恒 degraded"更危险，属掩盖故障；原"恒 degraded"表述不成立）；`DashboardPage.vue:159-164` 徽章判据 `pass/warn` 永不命中 → 所有检查项（含健康项）恒红 error。连带：`HealthStatus`/`HealthReport` 字段名错位（`uptime_seconds/timestamp:string/checks:数组` vs 后端 `uptime:float/timestamp:float/checks:Dict`）；「刷新检查/恢复」两按钮均打 `POST /health/recover`（后端恒 501），真正的 `POST /health/checks/{name}/run` 无前端消费者。修复：类型与判定改按后端枚举单源；runCheck 改接 `/checks/{name}/run`；恢复按钮在实现前置灰。

**P1-24 [逻辑错误] ModelPage 新增模型把同一对象 unshift 两次，列表重复、计数虚高**
`NeurUI/src/pages/ModelPage.vue:1534-1541`（主审已验；复核再证：`openModelManagement` :1328 将 `modelTarget.value` 指向 v-for 元素本体，`live` 与之同对象）：`modelTarget.value.models.unshift(newModel); modelTarget.value.model_count++` 后又对 `live` 重复 unshift/++——弹窗列表出现两条、卡片 `model_count` 多加 1，刷新后与后端对账又变回一条。修复：删除 `live` 冗余分支。

**P1-25 [死码/断链] KnowledgePage「MCP 信息源」按钮点击无任何效果，整块 MCP 管理面成死码**
`NeurUI/src/pages/KnowledgePage.vue:66-68` 按钮 `@click="mcpVisible = true; ..."`，但 `mcpVisible/mcpSources/mcpForm` 在模板**零挂载点**——无任何弹层渲染；script :1140-1260 一整套逻辑与 `.kb-mcp-*` 样式(:2591-2653)不可达。修复：补回 MCP 弹层模板，或按钮+script+CSS+api 模块一并退役。

**P1-26 [死码/断链] EnterpriseSourcesPage webhook 抽屉不可达**
`NeurUI/src/pages/EnterpriseSourcesPage.vue:411-449` 抽屉、`:664-678` `openWebhookDrawer` 仅定义无调用；`webhookDrawerOpen` 无入口置 true。U5 webhook 接收面（密钥指纹/轮换/模拟推送/幂等去重）对用户完全不可达。修复：操作列补「Webhook」入口，或整块退役。

**P1-27 [死码+断链] stores/health.ts 整店零消费，且内部按错误信封裸读**
`NeurUI/src/stores/health.ts:33-58`：全仓 grep `useHealthStore`（排除定义与测试）0 命中（主审已验；复核再证）；文件头注释宣称"Used by the health page and layout status indicator"失实——两页面均直连 API。且后端 `/api/v1/health` 返回**裸** Pydantic 模型、axios 拦截器已解包一层，store 却裸读 `res.data`（恒 undefined），`fetchReport` 里 `res.data.checks` 必 TypeError 被吞（fetchStatus/fetchChecks 同样静默空转）；单测用错误信封 mock 把错位钉成了绿灯。修复：删除该 store 及测试（页面直连已覆盖需求）；若要保留先修信封再接真实消费方。

### 2.7 移动端（10 条）

**P1-28 [断链] 鸿蒙端把"裸数组/裸对象"端点按 {code,data} 信封解包，整族页面运行时必败**
`Mobile/harmony/.../libs/api/modules/CapabilityApi.ets:150-155,245-252`（`unwrapOne` 判 `res.code!==0`，主审已验；复核再证：HttpClient.ets:186/HttpAdapter.ets:142 原样透传响应体，后端 `rules_api.py:176` 返回裸数组）、`RuntimeApi.ets`（scheduler/trace/firewall/sleep 各法，对应后端 `scheduler.py:117/224`、`trace.py:155/193`、`sleep.py:205/294`、`firewall.py:64/172/254` 均裸返回）。`res.data` 恒 undefined → `unwrapOne` 恒抛"xx失败"、`for (const dto of arr)` 恒 TypeError。影响面：AgentRulePage、AgentFilePage、AgentMediaPage、AgentSchedulerPage、AgentTracePage、AgentTrajectoryPage、SleepStatusPage、SleepSettingsPage、AgentFirewallPage、ContextChannelPage 全部只显示错误态。修复：比照 AuthApi/MobilePairingApi 的 `isBareShape` 边界归一法在模块边界统一归一（不得在页面层补丁）。复核补充：后端返回形状三种并存（裸数组/裸对象、`{code,data}` 信封、`{success,...}` 裸 dict），移动端 23 个 API 模块统一按 `{code,data}` 解包——修 P1-28/29 须全量盘点 23 个模块的"方法↔后端 handler 返回形状"，不许两边各改一半。

**P1-29 [断链] `res.data ?? []` 静默空：渠道/会话同步/文件/神经元/看板列表永远为空、写操作永远"失败"**
`AgentChannelsApi.ets:38,69-74`、`ChannelIntegrationApi.ets:90,106-113,126-132`、`SessionSyncApi.ets:67-74`、`MonitorApi.ets:229,259-262,277-280`、`CollaborationApi.ets:206-232,237-252,282-289`。后端同返裸形状（`channel_config.py:407-430`、`session_sync.py`、`tasks_api.py:173/191`）。（复核注：原列 `MonitorApi.ets:189-191` notifications 经查后端 `notifications.py:196-205` 实返回 `{code,data}` 信封，**不属静默空**，已剔除；其余抽验 7 处成立。）影响面：两个渠道页永远"暂无渠道"、保存与测试连接永远报失败；SessionSyncPage、FilePage、NeuronPage、TaskPage 永远空/创建失败。修复：同 P1-28，模块边界归一。

**P1-30 [断链] 路径双 `/v1` 与挂载点不符 → 404**
`PushApi.ets:36`（DELETE `/v1/mobile/push/push-tokens/{id}` → 实际 `/api/v1/v1/...`）、`HealthApi.ets:30,35`（双 v1 且后端无 /services、/metrics 路由）、`SettingsApi.ets:41,47,54`（双 v1；/settings/reset 后端无此路由）、`MonitorApi.ets:259-284`（`/neuron/*` 实挂 `/api/neuron`，移动端拼出 `/api/v1/neuron/*`；`app.py:602` 注释自认"缺 /v1"）。影响面：登出推送注销、健康详情、设置读写与重置、NeuronPage 全部 404。复核注：全模块扫 `/v1` 字面量仅此 4 处，无漏网。修复：按后端挂载表（`endpoints/__init__.py`）逐条校正路径，并把"路径不重复写 /v1"钉进模块守卫。

**P1-31 [契约] 设置列表形状不符：移动端设置读写整体失效**
后端 `settings.py:98-102` 返回 `{settings: Dict}`；`SettingsApi.ets:35-37` 期望 `SettingGroup[]`——`res.data.length > 0` 恒假 → SettingPage 永远渲染本地默认分组；叠加 P1-30 的 update 404，任何修改都不落库。修复：按真实形状解析＋路径修正。

**P1-32 [契约] 会话置顶请求体缺必填字段 → 422**
`SessionsApi.ets:77-80` pin 发空 body `{}`；后端 `console.py:1772-1790` `PinSessionRequest{pinned: bool}` 必填。鸿蒙端置顶/取消置顶必 422（安卓端正确传 `{pinned}`）。影响面：SessionListPage/DashboardPage 置顶失效。修复：补 body。

**P1-33 [死码群] 15 个鸿蒙页面零引用、路由名无 PageMap 分支（约 8.1k 行）**
`Mobile/harmony/.../pages/` 下 AIGCPage、AgentSkillPage、AnalyticsPage、AuditPage、BenchmarkPage、EnhancedUserPage、FirewallPage、GroupPage、MarketplacePage、MemorySearchSettingsPage、MemorySettingsPage、SandboxPage、SkillMarketPage、SkillPoolPage、ToolLayerPage。全仓 grep 零引用（页面外仅自身注释）；`Router.ets:67-104` 定义了对应路由名并列入 PROTECTED_ROUTES，但 `PageMap.ets:76-197` 无分支（唯一 "FirewallPage" 命中是 `AgentFirewallPage` 子串误配）——即使跳转也只显示"页面未注册"。这些页面还引用不存在的 API 域并内置 mock。修复：能对上后端真实端点的（SkillPool↔/v1/skills、Audit↔/v1/audit、Benchmark↔/v1/benchmark、Marketplace↔/v1/marketplace、Sandbox↔/v1/sandbox、Group↔/v1/groups、EnhancedUser↔/v1/enhanced-users、Firewall↔/v1/firewall、AIGC↔/v1/generation）接线进 PageMap，其余连测试退役——需拍板。

**P1-34 [假数据] 已路由页面渲染静态 mock，真实端点被注释**
`WebhookPage.ets:263-267`（mock＋注释掉真实调用，后端 `/v1/webhooks` 存在但移动端无该 API 模块）、`CollaborationTemplatePage.ets:257`、`CollaborationHistoryPage.ets:247`、`CollaborationInitiatePage.ets:300`（真实 `CollaborationApi` 方法存在却未用）。修复：切到既有真实方法或补 WebhookApi，删除 mock。

**P1-35 [断链] "后端无此端点即 throw"的 API 挂在已路由页面上，页面永远错误态**
`MonitorApi.ets:144-181`（stats/metrics/logs 八法恒 throw）、`CollaborationApi.ets:294-367`（projects/teams/workflows **十五法**恒 throw，复核更正原"九法"）、`RuntimeApi.ets:267-310,380-399`（context/computer/trajectory 十法恒 throw）——合计 33 个方法，多数带 `@deprecated`。影响面：StatsPage、LogPage、ProjectPage、TeamPage、WorkflowPage、ContextChannelPage、AgentComputerPage、AgentTrajectoryPage 进入即错误。属诚实失败，但路由仍可达——需拍板：下线路由或接真实面（logs→/v1/logs、audit→/v1/audit、analytics→/v1/analytics 均存在于后端）。

**P1-36 [安全/功能] 鸿蒙端凭证与设备身份零持久化，冷启动即失联**
`libs/state/StateManager.ets`（纯内存 Map）、`libs/state/stores/AuthStore.ets:12-108`；对照安卓 `CredentialStore.kt:37-87`（EncryptedSharedPreferences 落盘）。access/refresh token、wsToken/wsUrl、pairingId/deviceSecret 全部只存内存；`StorageAdapter.ets` 全仓零生产引用。`Index.ets:30-49` 冷启动 `isAuthenticated` 恒 false → 必回登录页；WS 续签依赖的 pairingId/deviceSecret 重启后为空。影响面：鸿蒙端每次冷启动都要重新登录＋重新扫码配对。修复：refresh_token/deviceSecret 走安全持久化，access_token 内存优先；StorageAdapter 正式接线或退役。

**P1-37 [契约漂移] Android `Contracts.kt` 的 `PairingConfirmed` 是零引用死模型且字段名错误**
`Mobile/android-native/.../core/model/Contracts.kt:114-121`（`@SerialName("ws_token")`）全仓无使用；真实解耦走 `core/protocol/PairingWire.kt:23-29` 的 `ConfirmedWire`（`connect_ticket`，与后端一致）。留着会诱导下一人用错字段。修复：删除未引用的重复配对模型。

### 2.8 测试 / 脚本 / CI（2 条）

**P1-38 [CI 引用失效] `.cnb.yml` 引用的 `.cnb/win-installer.json` 不存在**
`.cnb.yml:1552-1555`（触发说明 `--config "$(cat .cnb/win-installer.json)"`）。`git ls-files .cnb/` 与磁盘均仅 4 件，`.gitignore` 对 `.cnb/**` 显式放行——排除"被忽略"解释，文件从未入库。Windows 安装包手动触发流程按文档执行会在 `cat` 处失败（非门禁路径，不影响合并放行）。修复：补交载体或改说明。

**P1-39 [CI 引用失效] `.cnb.yml` 附件清单引用 `scripts/desktop/win_installer_kit-init.ps1` 不存在**
`.cnb.yml:1570` 与 `:1585`（attachments 列表项）。`git ls-files scripts/desktop/`（11 件）无此文件。`api_trigger_win_installer_provision` 的附件物化步骤对不存在文件声明附件，打包机机包缺件。修复：若已并入 `win_installer_kit.py` 删该附件项，否则补件。

---

## 3. P2（106 条，按域压缩条目）

### 3.1 后端 API（20 条）

1. `skill_pool_api.py:254-461` /private CRUD/push/execute 与 `marketplace.py:331,495` install/uninstall 接受任意 `agent_id` 无属主门（文件头 :52-55 自述"共享运行时资产"，与 H-W0 口径冲突——**待拍板**）。
2. `neurflow_triggers.py:136,254,278` 触发器 list/delete/fire 无 workflow 属主校验；fire 等于以调用者身份执行他人已发布工作流（create :182 已用 `_owned_workflow_or_404`，同文件现成修法）。
3. `neurflow_api.py:550,577,1559,1166` 执行记录列表/详情/变量/resume 无属主过滤，inputs/outputs 跨用户可读。复核补充：SSE `/executions/{id}/events`（:601-626）是全文件唯一带属主检查的口径，但 `get_current_user_or_default`＋`if owner and user_id and owner != user_id` 对匿名短路放行——匿名可订阅他人执行事件流，应随本条同批修。
4. `collaboration_api.py:185,246` 模板 update/delete 无属主校验。
5. `collaboration_room_api.py:88` 房间发言无成员校验（update_room :124 有）——可向任意房间写入并消耗他人 agent token。
6. `shared_config.py:135,154,421,368` llm-providers CRUD/import 与删除 MCP server 仅登录门（内存平行配置面仍可被普通用户整体改写，:140 `_shared_config = body` 整体替换）。
7. `logs.py:153` DELETE /api/v1/logs 任意登录用户可清空事件日志。
8. `scheduler.py:167` 建任务可指定任意 `agent_id`，无属主校验。
9. `mobile_push.py:57` 删除推送令牌仅凭 device_id，不校验属主。
10. `tool_layers.py:627,638` share_tool 写入的 `_shared_tools` 全仓无读者、shared-with-me 恒回 []（死功能面；但可被任意登录用户无限写入内存 dict）。
11. `memory_timeline_api.py:15-77` 四端点恒回空/零（:58 `count += 0 # placeholder`）——装饰性数据面（复核注：已实挂 /v1/memory-timeline，endpoints/__init__.py:290，属"活的装饰面"而非纯死码）。
12. `endpoints/auth.py` 多处 500 detail 携带 `str(e)`（S-11 只修了 login）——复核实测 7 处：:410,468,536,551,676,720,758。
13. 登出黑名单为进程内存（`auth.py:47`、`endpoints/auth.py:47`）：多 worker/重启失效；超 2 万条时 `auth.py:371-372` 整表 clear 连未过期项一起放行。
14. `mobile_pairing.py:229` `_DEFAULT_WS_SECRET` 硬编码开发密钥；legacy `?token=` 通道（:1350）在未配 `NEUROVA_WS_SECRET` 的部署可伪造凭证（有界）。
15. `mobile_pairing.py:1168,1214` cancel/status 仅要求登录，不校验配对记录属主。
16. `computer.py:327` `_browser_state["history"]` 无界增长，浏览器状态全局共享跨用户串读。
17. `console.py:778` agent 未装配时聊天回 200 + `"Echo: <消息>"`（应 503）；`:250-258` `_get_replay_tail` TTL 判断恒假（死代码）。
18. `agent_enhancement.py:114-121` agent 无 `get_status` 时回"模拟状态"未标注 simulated。
19. `middleware.py:58` 访问日志记录完整 query string，`?access_token=` 类令牌会进日志——建议脱敏。
20. `app.py:228-229` `_get_default_llm` `except Exception: pass`（有兜底返回值，影响限于默认模型选择）。

### 3.2 core / agent / llm / context（15 条）

1. **check_connection 对死服务报成功**：`ollama_provider.py:158-171,336-368`（探测失败回退静态清单判活）、`lm_studio_provider.py:70-83`（静态兜底 `success=True`）、`anthropic_provider.py`（`check_connection` :202-234 恒 True）。对齐 `gemini_provider` 已修口径。
2. **约 30 处 DCL 单例用 `threading.Lock` 而非 RLock**（AGENTS §3 规格偏离；capability_detector.py:515、multimodal_prober.py:279、provider_manager.py:2095 等；当前无重入路径、未证实死锁）。机械替换（建议统一收口到 `core/lazy_singleton.py` DCL+RLock 单源）。
3. `llm_client.py` 的 mock 出口 4 方法（:763,802,818,847）零生产消费——与"诚实报错"相悖，删。
4. `neurova/context.py`(851B) 被同名**包**遮蔽（主审已验存在）——任何 import 都到不了它，包 `__init__` 已导出其全部名字。删。
5. `core/usage_history.py:113-114` `_init_db` 建表失败 `except Exception: pass`——写入持续失败且启动无读数。
6. `agent/protocols/dead_letter_queue.py:269-275` `_is_processed` 恒 `return False`——死信重放重复投递（acp_runtime.py 在用，属活伤）。
7. `core/turn_context.py:648-672` `clear_turn_state` 漏清 `_subagent_tool_allowlist_var` 与 `_tool_call_id_var`——跨回合残留。
8. `agent/retriever_adapters.py:246,284`（复核更正目录：实位于 agent/ 下）`CacheRetrieverAdapter._simple_cache` 只写不淘汰——长驻进程内存单向增长。
9. **三处 SQLite 建表绕过 db_migration 注册表**：`core/usage_history.py`、`core/aigc_usage.py`、`core/annotation_store.py`（对照 `context/eviction_ledger_db.py` 合规范本）。
10. **竞态**：`agent/swarm.py:369 vs :456` MAX_ACTIVE_CHILDREN 检查与 spawn 落账无锁；`agent/scheduler.py:1103-1115` input_override 读改写未持锁。
11. **弱默认密钥与默认遥测**：`core/secret_store_clean.py` 空主密钥走仅混淆路径＋:81 模块级绑定 dataPath；`core/crash_report.py` 崩溃上报默认开启外发 `neurova.top`（**待拍板**）。
12. **非原子写**：`core/file_utils.py` files.json 读改写无锁；`core/app_settings.py:154` 裸 `write_text`（对照 session_manager 的 tmp+replace+fsync 范本）。
13. `context/semantic_drawer.py:193,239` 两个一模一样的 `_setReadout`（后者遮蔽前者）；`context/orchestrator.py:653-657` 重复判定块（第二遍不可达）；`context/builder.py:390` 取值后弃用。
14. `tool_executor.py:19` 未用导入；`core/resilience.py:3`、`agent/hooks_engine.py:31,227`、`agent/swarm.py:572`、`core/turn_phase.py` "对照/对齐第三方"措辞触碰 §2 原创性红线。
15. `voice_pipeline.py:82-116` 依赖装配失败仅 debug 级吞——语音链路静默失能时线索不足。

### 3.3 知识 / 记忆 / 认知（6 条）

1. **锁外迭代 `_memories`**：`memory_layer/manager.py:3265`（get_emotion_timeline）、`:4777`（compress_low_value_memories 候选构建）、`:4562-4563`（get_memories_by_emotion）——并发写下偶发 RuntimeError；M-06 修复的漏网点。复核注：修时应按 M-06 注释口径全扫 `_memories` 无锁读，不止点名三处。
2. `memory/pending_memory.py:30-128,197-214` schema 演进未注册 db_migration（PRAGMA user_version）。
3. `enhanced_memory_search_api.py:71,548-554` `/activation/{id}` 读一个全仓无写入方的全局字典，恒 200 空壳（应 404/501）。
4. `knowledge/storage.py:116-118` API Key 哈希固定盐 `"neurova-knowledge-salt"`——改随机盐或走已有 Fernet 通道。
5. `MemorySecurity`（`memory_layer/security.py` 731 行）主链路未消费：遗忘走 `memory_enhancement.py:168` 直调 manager，加密/敏感检测零生产调用（**待拍板**：接线进 remember 咽喉或退役）。
6. `memory_layer/storage.py:445-465` `_passesIsolation` 对未传上下文放行（JSON 旁路存储；主检索不经它）——None 语义建议 fail-closed。复核注：其上游 `query/list_by_tags` 未发现生产调用方，影响面有限。

### 3.4 技能 / 进化 / 协作 / 渠道 / 安全（12 条）

1. **neurflow 四个节点执行器假成功**：`neurflow/builtin.py:1204,1210,1236,1663`（eval/optimize/tdd/human_input TODO 桩，返回 `score:0.0`/`pass_rate:1.0`/恒超时）——编程主链与人工审核节点踩在占位值上。
2. `collaboration_isolation.py:1122,1147,951,1089` 管理面无权限校验（自注"简化处理"）、`get_project_file_path` 无 containment；`list_projects` 被 `collaboration_api.py:88,361,406,439` 消费且无 requester 过滤——多用户部署横向信息泄露（四个 HTTP 暴露面，两层同批收口）。
3. `channels/xiaoyi.py` 与基类契约脱节（:130 等 `self.config.config` AttributeError、:372 工厂非法 kwargs、:238 未连接假成功）——渠道**每次配置都失败**（`channel_config.py:991-999` 捕获后 warning+HTTP 400；复核修正原"静默失败"表述：有告警有 400，但渠道确实永远配不通）。根因之一是 ChannelConfig 双定义（base.py:49 与 models.py:167 均无 `.config` 字段）。
4. **三个内置工作流模板引用未注册节点类型**：`templates/document.py`、`data_analysis.py`、`web_maintenance.py` 共 7 个 `builtin:*` 类型在全包零注册——实例化必"未知节点类型"。
5. `channels/qqbot.py:771` `get_channel_config` 明文返回 access_token（对照 base.py:215 掩码约定；当前零调用，属潜伏泄露面）。
6. `channels/wechat_auth.py:323` 签名比较未用 `hmac.compare_digest`（同仓 wechat_kf_crypto/telegram_webhook 均用）。
7. `skills/executor.py:101-102` 入参解析失败静默空参；`skills/skill_install_gate.py:104-105` 吞异常。
8. **同名双实现**：`approval_manager.py` 两个等价 `get_request`（:550/:577）；`channels/base.py:49` 与 `channels/models.py:167` 两个 `ChannelConfig`（models 版近乎无引用）；两处 `ValidationResult`（语义不同，建议改名消歧）。
9. **零消费方**：`channels/websocket.py`(548 行，自注"这一支今天在生产里构造不出来")、`skills/manifest.py`、`AgentSkillManager.acquire_skill/suggest_skills_for_task`（生产零调用，仅测试以 inspect 源码断言引用）。
10. **db_migration 注册覆盖不全**：`channels/user_identity.py`、`channels/outbound_ledger.py`、`security/approval_manager.py`、evolution job_queue 自建表未注册（已注册的 3 处：ekb、channel_ingress_queue、wecom_archive）。与 §3.3-2 pending_memories 同根因，合计 6 个域应一批登记。
11. `collaboration/computer_manager.py:198-204` 公司归属判定 `# TODO: Check admin role`——非属主仅凭 `user_id.endswith("@{company_id}")` 后缀放行。
12. `evolution/__init__.py` 整段静默降级（哪半个包活着只能靠猜）；`channels/manager.py:92-94` `_instanceLock` 连续定义两次、`:1050-1051` resolve_session_scope_id 丢 `agent:` 前缀（边缘配置相撞）；`api/endpoints/collaboration_api.py:259` `delete_project(template_id)` 缺 `user_id` 实参必 TypeError→500（删除模板端点当前不可用）、`:228` 直调私有 `_save_project`。

### 3.5 其余后端（13 条）

1. `auth/auth_protocol.py`(29 行) AuthProtocol 零实现零消费，却被 `interfaces/__init__.py:22` 当"已接真"导出。
2. `sandbox/thought_sandbox.py`(432 行) 零消费；默认分支返回假成功 `{"processed": True}`。
3. `tool_layers/__init__.py:89-131` import 失败兜底类 `ToolOrchestrator.execute` 恒 `{"success": True}`（与 execution_engine §6-224 弃用同款兜底的口径矛盾；agent_core.py:903 生产实例化，中招即全线假成功）。
4. **async 内同步调用**：`sandbox/exec_sandbox.py:411`（非 docker 路径同步 subprocess 最长等满 timeout）、`computer_use/browser_manager.py:1848`（ScraplingBackend.navigate 同步 fetch）——事件循环被堵至 30s。
5. `asr/__init__.py:26-32` 声明从未导入的 `FunASREngine`（`from neurova.asr import FunASREngine` 会 ImportError）。
6. `auth/user_model.py:492` 更新字段整包进日志——`kwargs` 可含 `password_hash`。日志只记字段名。
7. `auth/qclaw_binding_model.py:516-522`＋`channels/qclaw_service.py:58`：生产构造不传 encryption_key，app_secret 走 Base64 可逆落库。
8. `models/cost_budget.py:317-325,370` Slack/Email 告警通道空实现却默认注册（读数显示"已通知"）；llm_budgets 表加载 TODO——预算体系当前无持久配置入口。
9. `models/cost_tracking.py:135-335` CostTracker 的 PostgreSQL/asyncpg 形态零消费（在役的是 cost_store.py SQLite 实现）。
10. `tool_layers/mcp_oauth.py:408-412` DCR transport 注入分支 `data=payload`（表单）vs httpx 分支 `json=payload`——桩测形态与生产不一。
11. `tool_layers/mcp_client.py:551-559` 防火墙校验对非 PermissionError 异常 fail-open——内部 bug 也会放行。
12. `aigc_studio/services.py:457,647` 服务层硬编码 `("admin", is_admin=True)` 旁路取项目——纵深缺口（HTTP 面有前置校验）。
13. `auth/invitation_code.py:371-415`、`auth/verification_code.py` read-then-write 非原子——并发下 `max_uses=1` 邀请码可被双人同时使用；改单条条件 UPDATE。

### 3.6 前端页面/组件（16 条）

1. `SkillPoolPage.vue:209,256-316` 待审批面整块不可达（activeTab `'pending'` 无对应 tab-pane）；`:152-154` 技能代码输入框内容在 payload 中被丢弃。
2. `KnowledgeInteropPage.vue:252-257` `isAdmin` computed 定义后零引用——管理员门未接线，导出/导入按钮对所有用户可见。
3. `GraphWorkbenchPage.vue:440-444` 布局降级警示只置位不复位，且在 computed 内写 ref。
4. `ChannelIntegrationPage.vue:442-448`、`AgentChannelPage.vue:358-364` 「启用/禁用」按钮只翻本地状态不落库（**待拍板**：改文案或点击即落库）。
5. `AgentFirewallPage.vue:343-358` 网关/隔离开关与保护路径全为本地硬编码装饰态（无取数无保存）。
6. `VoiceTranscriptionSettingsPage.vue:31-42,109-113` 远程 Whisper 表单无保存链路；链路文案写死。
7. `DataHubPage.vue:83-161` GROUPS 常量内 agent 深链在 setup 期固化——切 Agent 后链接仍指旧 agent。
8. `MemoryPage.vue:940-943,875-879` 分页为装饰（翻页不发分页参数，第 2 页起数据不变；注释自认）。
9. `ChatPage.vue:507-508,518-519,594,852-859,2530,874,2700,2709` 死导入/死变量群（GlassButton/ContextUsageIndicator/groupedSessions/historyUp 等，复核实测 8 处）。
10. 其余死导入/死样式：`MainLayout.vue:373-374`、`ModelPage.vue:492`、`StudioRelationsSection.vue:88`、`SettingPage.vue:1232-1238`。
11. **i18n 硬编码约 24 处**：MemoryPage（' Results'、'Storage' 等 8 处）、GrowthPage（`t(key) || fallback` 在 vue-i18n 缺键时恒不触发，应复用 `resolveI18nMessage`）、FactExplorerPage、KnowledgeEvalPage、ForgotPasswordPage:204（用后端中文原文做字符串比对）等。
12. `AgentSwitcher.vue:186-192` Escape 监听在面板开启时组件卸载会残留——补 onUnmounted。
13. `StudioReasoningSection.vue:91-95` 策略切换纯本地翻转，无持久化。
14. `NeuronPage.vue:248-318` 5 处错误只进 console，无用户提示。
15. `ContextChannelPage.vue:117,124` `catch { /* handled */ }` 实际未处理。
16. `console.log` 纯调试残留（复核实测约 8 处存活调用，ModelPage 6 处等；原记 17 处，部分在审计落盘后已清理，AgentListPage 现无残留）。

### 3.7 前端基础设施（5 条）

1. `npm run lint` 不可运行：eslint 无依赖无配置（AGENTS §4 已记载；恢复须另批补 flat config＋依赖并接入 CI）。
2. 硬编码色值 484 处/98 文件——处于 `hardcodedColorRatchet.guard.test.ts` 基线棘轮之下，只降不升的受控遗产债（复核 raw grep 约 569 处/99 文件，量级相符、口径差异在兜底剥离）。
3. `vite.config.ts:44-47` 代理 `/ws` 无前端消费方（实际 WS 走 `/api` 代理）——死配置。
4. `useSessionSync.ts:161-168` WS 4401 后永久停止重连（有意设计：凭据刷新由 axios 拦截器统一处理；需知悉）。
5. `types/response.ts` `ApiResponse<T>` 是约定型声明，后端真返回该信封的仅部分端点——全仓约 20+ 处 `res?.data ?? res` 兼容写（复核实测 95 处/46 文件，"20+"为下限口径）；唯 health store 裸读出错（P1-27）。

### 3.8 移动端（11 条）

1. `KnowledgeApi.ets:69-70` 时间戳未按秒→毫秒换算——渲染成 1970 年（根因在后端 knowledge_core.py:217 产秒级 timestamp；安卓侧同契约目前无渲染消费点，属潜伏）。
2. 不存在的颜色 token `status_success/status_error/status_warning` → `getColor` 回退黑色：ChannelIntegrationPage、SessionSyncPage、MonitorPage、StatsPage 四处命中（复核注：还被 5 个 ohosTest 断言，修 token 时测试同批改；应在 StyleManager 增补三个真 token 单源）。
3. `SessionListPage.ets:69-76` 排序比较器只返回 0/1 从不返回负数——置顶优先/最新在前不成立（对照安卓 `compareByDescending` 正确）。
4. `SettingPage.ets:514-531` 选择器是空壳对话框；`applyTheme('auto')` 直接落 light。
5. `SettingPage.ets:477` 登出推送注销 deviceId 与登录上报不一致（`harmony-main` vs `${brand}-${model}`）且路径 404；`LoginPage.ets:79-84` 用 `local-随机串` 伪造推送 token 上报污染注册表。
6. 硬编码色值绕过令牌体系：ConnectionPage、ChatPage、DashboardPage、AgentListPage、SessionListPage、SettingPage、KnowledgePage（品牌渐变重复 8 处）、GraphPreviewPage、安卓 PairingScreen。
7. `Logger.ets:37` 默认 DEBUG 全量输出（release 未设级别）；`ConfigManager.ets:32` 30s 与 `HttpAdapter.ets:58` 15s 超时双口径。
8. 死码：`libs/protocol/PairingProtocol.ets:58-68` `parsePairingPayload` 零调用（实际用 PairingPayload.parse）；`libs/adapters/StorageAdapter.ets`(249 行) 零生产引用。
9. `AndroidManifest.xml:16` `usesCleartextTraffic="true"` 全局放行明文——建议 networkSecurityConfig 按域放行。
10. 版本基线：安卓 versionCode=1/0.1.0 vs 鸿蒙 versionCode=2/1.0.0 无对齐；`Mobile/signing/INFO.md` 仍写建议包名 `com.neurova.app`（实际 `top.neurova.mobile`）。
11. 零散：`Index.ets:40` `applyServerProfile` 未 await；`ShellPage.ets:20` 死导入；`NotificationsStore.ets:41` 对象展开与 ArkTS 自我约定冲突（待复核）；`AgentsApi.ets:62` `group_id` 语义错位充当 `createdAt`。

### 3.9 测试 / 脚本 / CI（8 条）

1. 孤儿测试 `tests/unit/core/test_define_action.py`：指向不存在的 `neurova.core.define_action`/`neurova.actions`（全量 743 行 import 扫描中唯一孤儿）；已整文件模块级 skip（:19-23）挂在 `docs/test-debt-skip-list.md`——不炸收集，属在案挂起债（复核注：skip 文案里的路径已陈旧，实际登记在 `docs/11-legacy/test-debt-skip-list.md:43`）。
2. 复核更正：`tests/cognitive_body_store.py` **并非零引用**——7 个认知域测试 import 其 `bodyManager`/`cognitiveEngine` 作共享 fixture（如 `tests/unit/test_cognitive_storage_flush_m11.py:15`），不可按死码清理；根目录另有 Windows 设备名残留文件 `nul`（已被忽略，卫生项）。
3. 旧布局测试顶层目录实存 22 个（复核更正原"约 13"），其中 10 个与 `tests/unit/` 子目录重名（admin/api/auth/cognitive_layers/collaboration/context/core/knowledge/llm/neurflow）；重名文件 14 组（纯用例重名 11 组，test_storage.py×4 等），靠 `--import-mode=importlib` 规避冲突（pyproject.toml:114-116 自认）——按 §2 归属纪律逐步收敛。
4. 根 `package.json` 两个死 npm script：`cost:analyze`/`cost:rollup` 指向不存在的 `scripts/cost_analyzer.py`/`cost_rollup.py`（CI 未引用，仅死入口）。
5. `.gitignore` 与跟踪状态不一致三目录：`/helm/`、`/examples/`、`/embedding/` 在忽略清单却各有跟踪文件——**目录内新增文件会被 git add 静默排除**（历史吞测试文件事故的同款土壤），改精确产物忽略。
6. Node 版本口径不一：`.github/workflows/cost-guards.yml:19,57` 用 node 18，全仓其余（ci.yml、.cnb.yml、compose）为 node 22。
7. 18 个"仅文档/自检引用"脚本（复核更正原"13"：scripts/diagnostics/ 12 个＋knowledge_* 5 个＋reorg_docs.py；diagnostics 目录现有 23 个脚本）——收纳型工具，知情项。
8. `neurova/memory/scripts/save_vue_frontend_memories.py:52` 演示敏感信息内嵌记忆种子文本（内网 IP＋弱口令字样随包分发）——改环境注入或删除（该子包已被 ci_static_gate 刻意排除，无执行风险）。

---

## 4. 移动端 ↔ 后端契约比对（重点交付物）

后端挂载规则：`/api + 表前缀 + 路由`（`endpoints/__init__.py:358`）；鸿蒙 baseUrl=`{host}/api/v1`。27 项核对：

| # | 后端实际 | 移动端调用 | 结果 |
|---|---|---|---|
| 1 | `GET /api/v1/rules` 裸数组 | CapabilityApi 读 `res.data` | TypeError 恒失败（P1-28） |
| 2 | rules 单条 CRUD 裸对象 | `unwrapOne` | 成功也抛错（P1-28） |
| 3 | `GET /scheduler/tasks` 裸数组 | RuntimeApi 读 `res.data` | 恒空/抛错（P1-28） |
| 4 | `GET /sleep/{id}/status` 裸对象 | `unwrapOne` | 恒抛错（P1-28） |
| 5 | `GET /trace`、`/trace/{id}` 裸数组/对象 | RuntimeApi | 恒失败（P1-28） |
| 6 | `GET /firewall/rules` 裸数组 | RuntimeApi | 恒失败（P1-28） |
| 7 | `GET /files` 裸数组 | CapabilityApi/MonitorApi | 恒空（P1-29） |
| 8 | `GET /channel-configs` 裸数组 | AgentChannelsApi/ChannelIntegrationApi | 恒空（P1-29） |
| 9 | channel-configs 写操作裸结果对象 | 读 `res.data.success` | 恒 false（P1-29） |
| 10 | `GET /sync/sessions` 裸 `{total,sessions}` | SessionSyncApi | 恒空（P1-29） |
| 11 | neuron 实挂 `/api/neuron`（无 /v1） | MonitorApi 调 `/api/v1/neuron/*` | 404（P1-30） |
| 12 | `GET /tasks/boards` 等裸数组 | CollaborationApi | 恒空/404（P1-29） |
| 13 | `GET /settings` 返回 `{settings:Dict}` | SettingsApi 期望数组 | 永远回退默认（P1-31） |
| 14 | `GET/PUT /settings/{key}` 存在 | SettingsApi 双 /v1 | 404（P1-30） |
| 15 | 后端无 /settings/reset、/health/metrics、/health/services/* | SettingsApi/HealthApi | 404（P1-30） |
| 16 | `DELETE /mobile/push/push-tokens/{id}` | PushApi 多写 /v1 | 404（P1-30） |
| 17 | `POST /console/chat/sessions/{id}/pin` 需 `{pinned}` | SessionsApi 发 `{}` | 422（P1-32） |
| 18 | WS 心跳须 JSON `{"type":"ping"}` | 安卓发裸文本且 10s 必 close | **P0-2** |
| 19-27 | governance/home/providers/models/enhanced-users/generation/metacognition/agents+auth+pairing/console+WS 握手 | AdminApi/HomeApi/ProvidersApi/AigcApi/CognitionApi/AuthApi/MobilePairingApi/SessionsApi | **通过**（边界归一正确） |

## 5. 前端 API 契约比对结论

从 `ENDPOINT_MODULES` 注册表＋全部 `@router` 装饰器重建后端全量路由（1146 条装饰器 → 930 个归一化路径），与 NeurUI 全量 237 个 API 调用点做 method+path 精确比对：**232 个精确匹配，0 个真实错位**（上轮 5 条不匹配已全部修复）。剩余 5 条"未匹配"经核查均为提取器误报（模板字符串拼接）。〔复核抽验 6 个调用点（monitor/ontology/budgets/enhanced-users/tool-layers 跨 5 模块）全部精确匹配。〕

## 6. 上轮（2026-11-12）50 条复核结果

**总结论：51 条已修复（含按拍板退役），3 条部分修复，0 条仍存在，0 条无法确认。** 修复集中在 11-12 审计落盘后的一批收口提交（`6a52019df`、`5102ce68d`、`446bad3fa`、`f4803ce5c`、`7cf27c206`、`77213fdc5`、`309b47ea1`、`e400761bd`、`38323330c`、`38b80b366`、`a8c163b53` 等，提交说明多带"审计 Pxx 收口"字样）。〔复核抽验 15 项全部与代码现状相符，提交号/行号/残留数量均对得上。〕

| 编号 | 标题（缩写） | 现状 | 关键证据 |
|---|---|---|---|
| P0-1 | enhanced_users 假内存存储 | 已修复 | enhanced_users_api.py:68-72 走真账本，`_users_store` 仅存于历史注释 |
| P0-2 | active/enabled 字段错位 | 已修复 | UserUpdate.active；前端三处均 active |
| P1-1 | budget/cost_rollup 零鉴权 | 已修复 | 路由级 get_current_user＋写面 require_admin |
| P1-2 | 连接池满池持锁等待 | 已修复 | connection_pool.py:156-196 等待移锁外＋借出前 SELECT 1 |
| P1-3 | mergeDuplicateRecords 零调用 | 已修复 | ekb:217-218 挂 _migrate_schema 尾 |
| P1-4 | 记忆 importance/tags 丢弃 | 已修复 | 请求模型/透传 ×100/读侧输出三段齐 |
| P1-5 | systemPrompt/maxTokens 收集即丢 | 已修复 | 后端消费（agent.py:198-208,524-529,652-655）；systemPrompt 输入框按拍板删除 |
| P1-5b | 性格/宪法死表单 | 已修复 | 前端提交+回填；后端模型收字段 |
| P1-6 | group_id 回显断链 | 已修复 | types/store/page 三层补齐 |
| P1-7 | 告警确认 PUT→405 | 已修复 | monitor.ts 改 POST |
| P1-8 | 本体命名空间 404 | 已修复 | ontology.ts:91 补 /ontology 段 |
| P1-9 | protected_tests 索引↔分片差 7 条 | 已修复 | comm 双向差集空；NPC 归档分支已删 |
| P1-10 | 三层隔离恒 default | 已修复 | 渠道绑定→检索透传→ContextVar 注入→存储读侧过滤四点闭环 |
| P1-10b | /import-url 堵事件循环 | 已修复 | knowledge_ingestion.py:255-270 to_thread |
| P1-11 | AgentBuilder 死码 | 已修复（退役） | builder.py 已删 |
| P1-12 | GateCatalog 零接线 | 已修复（退役） | gate_catalog.py 已删 |
| P1-13 | 元技能七模块死码 | 已修复（退役） | 七文件全删零引用 |
| P1-14 | InfrastructureManager 假在役 | 已修复（退役） | infrastructure.py 已删 |
| P1-15 | llm_router 只同步 admin 表 | 已修复 | sync/select 带 scope，agent_core 传属主 scope |
| P2-1 | context 预览/压缩假面 | 已修复 | context.py:499-560 真实现 |
| P2-2 | /performance 恒零 | 已修复 | runtime.py:131-177 真计数器采样 |
| P2-3 | 验证码落日志＋谎报 | 已修复 | 桌面形态诚实化（a2b3c9c10）；服务端形态敞口转为本轮 P1-6 |
| P2-4 | files 删除吞异常 | 已修复 | 先 unlink 后删记录，失败如实报错 |
| P2-5 | triggers 删除吞异常 | 已修复 | 先 unregister 后删存储 |
| P2-6 | /tools/execute 无属主校验 | 已修复 | 路由级鉴权＋_executeOwnershipGate |
| P2-7 | enhanced-users 分页不认 | 已修复 | page/page_size/search 生效 |
| P2-8 | budget /alerts 恒空 | **部分修复** | 后端已实装（budget_api.py:199-215）；前端零消费——缺读取腿 |
| P2-9 | merge 漏保留行 | 已修复 | candidates=[kept]+others |
| P2-10 | 证据落账共享 try | 已修复 | tool_executor.py:1613-1615 拆分 |
| P2-11 | 反思门外壳 | 已修复 | post_chat_pipeline.py:3505-3517 外壳摘除 |
| P2-12 | 元认知游标越事件 | 已修复 | self_model.py:227-244 分页取尽 |
| P2-13 | 反思游标随机排序 | 已修复 | ledger.py 全部 ORDER BY created_at,rowid |
| P2-14 | execute_skill_isolated | **部分修复** | 子进程装配已修（create_default_skills）；生产仍零调用＋静默降级残留 |
| P2-15 | MemorySkill 恒空 stub | 已修复 | 接注入的 memory_manager |
| P2-16 | CrystallizedManager 零消费 | 已修复 | 新增只读诊断端点（admin 门） |
| P2-17 | ekb_revalidation 零引用 | 已修复（退役） | 模块已删 |
| P2-18 | model_route_config/config_console | 已修复（退役） | 两文件已删 |
| P2-19 | SmartModelSelector | 已修复（退役） | model_selector.py 已删（残留 2 处陈旧注释） |
| P2-20 | EKB 迁移未注册 | 已修复 | register_migration(domain=experience_records) |
| P2-21 | 五处 DCL 用 Lock | 已修复 | 五处均 RLock（7df0c7670）；本轮新发现另有约 30 处同型（core-P2-2） |
| P2-22 | _current_user_id 死读层 | 已修复（形态调整） | 改显式身份位＋契约测试钉住；失实注释订正 |
| P2-23 | injector 兜底不登记 | 已修复 | injector.py:753-759 同走登记＋守卫测试 |
| P2-24 | attachUserOutcome strip 不对称 | 已修复 | 匹配绑原始串同口径 |
| P2-25 | avg_proficiency None 折叠 0 | 已修复 | null 渲染"未测量" |
| P2-26 | searchSimilar 类型撒谎 | 已修复 | 类型/limit 映射修正 |
| P2-27 | 死页面×3 | 已修复（退役） | 三文件已删 |
| P2-28 | StarBackground 死组件 | 已修复（退役） | 组件已删 |
| P2-29 | notifications 双轨 | 已修复 | 页面改走 store |
| P2-30 | getAgentConfig/clearEventsLost | 已修复 | 两 action 已删；横幅 store 管理 |
| P2-31 | 硬编码色值 200+ | **部分修复** | 已落两批令牌（ModelPage 57→49）；仍 73 个 .vue 文件命中，棘轮受控 |
| P2-32 | 空操作监听 | 已修复 | onEpisodeTitleChange 防抖落库；空监听已删 |
| P2-33 | 页面裸写 URL | 已修复 | monitor.ts/console.ts 封装建立 |
| P2-34 | home.ts 幽灵字段 | 已修复 | 键已删 |
| P2-35 | .bak 残留 | 已修复 | 全仓零 .bak（复核注：磁盘 data/ 运行时目录有 2 个被 gitignore 的会话备份 .bak，非源码残留） |

## 7. 检查通过的高风险点（汇总）

- **命令执行面**：/shell、/debug/command admin 门＋白名单＋数组执行；沙箱 AppContainer/SAFER 完整且 `enforced()` 诚实自报；workflow/scripted AST 白名单＋独立子进程＋副作用走父侧治理。
- **文件上传**：流式落盘＋大小上限＋扩展名黑名单＋路径白名单＋越根二次校验＋属主 404 同构（S-15 完整）。
- **MCP**：stdio 仅 admin、出网 URL 全过 `assert_public_url`、执行面属主门 fail-closed、DCR/OAuth 面完整。
- **SSRF**：web_reach 每跳复核、知识导入先验后抓、plugin_sources 四件套——未发现可达内网探测路径（webhooks 例外见 P1-5）。
- **移动端安全**：凭证不进 URL（Authorization 头优先）、安卓凭证分仓加密、WS 4001 续签决策与后端咬合、无 token/secret 落日志、配对载荷单源解析。
- **SQL/注入**：全库未发现字符串拼接用户输入进 SQL；DB 均参数化；知识连接器标识符白名单＋只读硬闸。
- **身份单通道（§6-163）**：全仓仅一条装 user_id 的 ContextVar；会话可见性单点 resolveSessionOwner。
- **前端**：7 处 v-html 全部经 DOMPurify 白名单净化；401 单飞刷新＋重放一次；SSE/WS 自愈设计完整；stores 无越权直改、无死 action；死组件 0。
- **吞异常面**：全库裸 `except:` 0 处（复核 grep 证实，仅命中 2 处文档字符串）；`except: pass` 个位数且均有注释交代；绝大多数 broad except 转结构化结果或 warning。
- **CI/部署**：门禁脚本引用链全存在（2 处 Windows 手动路径例外）；helm appVersion==代码版本；端口/密钥面一致；requirements 与重依赖抽样 14/14 命中；scripts 82/82 ast 通过、无硬编码密钥。
- **可选依赖**：后端全量惰性 import＋诚实降级，无顶层裸 import 重型依赖。
- **尺寸棘轮**：agent_core.py 2046 行 < 基线；新发现 12 个 >1500 行文件建议纳入棘轮管理（见 §8）。

## 8. 遗留债统计

- **TODO/FIXME**：后端 api 域 9 处（在案未实现 3：chat.py:894 附件、logs.py:64、session_sync.py:248）；skills/collaboration 5 处（neurflow 四 stub＋computer_manager）；models/cost_budget 4 处；其余域合计 <10。前端与鸿蒙主源码 0 处（鸿蒙死页面内约 40 处随死码处置）。
- **死码存量**：约 1.6 万行（复核修订后）——core ≈3,100、agent ≈1,375、llm ≈300、security ≈1,770、channels/websocket 548、EnhancedUserModel 533、鸿蒙 15 页面 ≈8,100、StorageAdapter 249、Android Contracts 重复模型、NeurUI health store/MCP 块/webhook 抽屉等。原 core 3,845 计入了 ConfigManager/LogManager（实为 core/config.py、core/logger.py 活码）、原 agent 2,345 计入 3 个活码（initialization_manager/preset_templates/subagent），均已剔除。
- **超大文件（>1500 行，建议纳入尺寸棘轮）**：tool_executor.py 8210、memory_layer/manager.py 5407、context/orchestrator.py 4012、post_chat_pipeline.py 3895、agent/chat_pipeline.py 3507、browser_manager.py 3034、console.py 2604、knowledge/repository.py 2570、knowledge_facts.py 2478、builtin.py(neurflow) 2712、commerce_nodes.py 2505、session_manager.py 2334、provider_manager.py 2238、skill_service.py 2133、cli.py 2085、knowledge_ontology.py 2099、neurova_recall.py 2049、agent_core.py 2046（已有棘轮）。〔复核 wc -l 逐文件精确命中。〕
- **锁形态**：threading.Lock 192 处 vs RLock 295 处（复核精确命中）；约 30 处单例 DCL 规格偏离（core-P2-2）。
- **测试债**：旧布局目录 22 个（10 个与 unit 重名）、重名 14 组、孤儿 1（已 skip）、tests 根零引用 0（cognitive_body_store 经复核为活 fixture）。
- **仓库卫生**：双份模型二进制（工作树两份跟踪＋src-tauri 一份打包副本）、gitignore 三目录、node 版本、死 npm script×2、CI 失效引用×2。

## 9. 未提交改动专审（工作树 2 文件）

1. `Mobile/harmony/.../adapters/WebSocketAdapter.ets`（+3）：`on('error')` 新增 `JSON.stringify(value)` 日志。风险：循环引用对象会抛 TypeError 且回调体内无 try/catch，可能吞掉后续 `ws:error` 分发；建议安全序列化（取 code/message 逐字段）或降 debug 级。可合入，建议先修。
2. `Mobile/harmony/.../api/modules/AgentsApi.ets`（+4/-3，复核更正：原记 +7/-3 系两文件合计口径）：`toAgent` 对 `group_id/description` 判空兜底（后端实测返 null）——正确修复，无新增风险。遗留：`:62` `group_id` 语义错位充当 `createdAt` 未解决（移动-P2-11）。

## 10. 方法说明、误报修正与待复核项

- **方法**：只读静态审计（逐文件 Read＋全量机械 grep/comm/ast 扫描），不做动态利用测试。P0/P1 由主审逐条复验（13/13 坐实）；P2 抽验。上轮 50 条复核全部重新取证，未照抄旧结论。
- **误报修正**：前端 API 比对中 5 条提取器"未匹配"经人工核验均为模板字符串误报，后端路由真实存在；`embedding/` 与 `models/embedding/` 的 du 读数（184M/274M）含文件系统块开销，实际二进制字节以 agent 实测 wc -c 为准（约 480MB/两份）。
- **待复核项**（证据不足以下结论，未计入发现）：ArkTS 对对象展开/计算键字面量的编译器放行度；`enhanced_memory_search` 之外个别"裸形状"判断基于模块自述＋后端 return 抽验；鸿蒙 87 个 ohosTest 未逐字精读（已核对与被测对象一一对应）；skill_pool 共享资产属主语义待产品裁定。
- **边界**：P1-14 隔离修复效果、P1-16/17 阻塞的实际时长未做活体压测，判定依据是完整代码链路与同仓已修范本；静态审计不能替代教义第 4 条的 live-verify。

---

## 11. 独立复核记录与勘误（2026-11-16 第二轮）

**方法**：10 个只读核查组按域全量复核（后端 API、core/渠道、仓库/前端、移动/CI、P2 四片、上轮复核抽验、统计与工作树），P0 两条由主审外独立逐行复验；全程只读取证，未运行测试、未改动代码。

**总判定**：147 条中 **137 条属实、9 条部分属实（核心问题仍在，细节已就地修订）、1 条含不实子项**。§0.2 文件计数（5227＝py 4230/ts 522/ets 248/vue 169/kt 58）、§8 大文件行数（9/9 精确）与锁计数（Lock 192/RLock 295）、§7 裸 except 0 处与 helm 版本对齐、§6 上轮 50 条抽验 15/15、§5 契约抽验 6/6——全部与仓库实况吻合。

**勘误清单**（均已回写正文）：

| 条目 | 原表述 | 修订后 |
|---|---|---|
| P1-11 | 死码簇含 settings_manager.py＋ConfigManager＋LogManager，约 3,845 行 | ConfigManager/LogManager 实为 core/config.py、core/logger.py **活码**，剔除；8 个死码模块约 3,100 行 |
| P1-12 | 死码簇含 initialization_manager/preset_templates/subagent，约 2,345 行 | 三者均为**活码**（agent_core init_all／agent/templates→collaboration_template→/teams/orchestrate／spawn_subagent→tool_executor），剔除，**不得退役**；余下 matrix/、capability_discovery、legacy_stream_reader、MessageQueue/MessageSerializer 约 1,375 行 |
| P1-21 | "LFS 从未真正接管" | git 历史为 LFS 指针（大文件同 OID、.git/lfs 去重 277M），工作树二进制是 LFS checkout 正常形态；问题实质＝双份跟踪副本＋src-tauri 第三份未跟踪 274M 副本 |
| P1-23 | HealthPage 总体状态恒 degraded | 实为 axios 拦截器解包后 `checks=[]` → `[].every()` 恒真 → **恒 'healthy' 假绿**（掩盖故障，更危险） |
| P1-29 | MonitorApi notifications 在静默空清单 | notifications 后端实返回 {code,data} 信封，剔除；其余 7 处命中点成立 |
| P1-35 | CollaborationApi 九法恒 throw | 实为十五法；三模块合计 33 个方法 |
| 3.6-16 | console.log 残留 17 处 | 实测约 8 处存活（ModelPage 6 等），部分系审计后已清理 |
| 3.9-2 | cognitive_body_store.py 全仓零引用 | **不实**：7 个认知域测试 import 作共享 fixture，不可清理；nul 残留属实 |
| 3.9-3 | 旧布局目录约 13、重名约 19 组 | 实测 22 个目录（10 个与 unit 重名）、重名 14 组（纯用例 11 组） |
| 3.9-7 | 仅文档引用脚本 13 个 | 实测 18 个（diagnostics 12＋knowledge_* 5＋reorg_docs） |
| §9 | AgentsApi.ets +7/-3 | 单文件 +4/-3（+7 为两文件合计） |
| P1-9/§3.1-12/§3.2-8 等行号 | 个别行号/目录漂移 | 已按实测修订（chat.py 501 实在 :874；auth str(e) 实为 7 处；retriever_adapters 实在 agent/ 下） |

**复核新增命中点**（教义第 5 条，修复时同批扫平）：

1. `/benchmark/compare`（benchmark.py:255-256）与 P1-8 同款 `sum(None)` TypeError，且 `avg_latency_ms` 键值 None 同炸。
2. console.py 除点名 2 处外，另有约 8 处无属主门 `get_agent_instance`（chat/review:1292、auto-title:1726、回合操作 :1912/:2013/:2046/:2079、feedback :2257/:2272）；文件内已有 `_check_session_ownership` 可复用。
3. 越权链放大：`/agent/{id}/switch` 改**进程级全局默认 agent**，console WS 腿吃的正是这份默认——任意用户可先把默认切到他人私有 agent，再让所有 WS 用户对话（P1-2×P1-1 组合，量级上调）。
4. plugin.py `uninstall`(:368)、`disable`(:419) 同为仅登录门；远程安装实际被 501 拦死，"远程源人工确认"属前瞻项。
5. auth.py 500 detail 带 `str(e)` 实为 7 处（原列 6 处，漏 :676）。
6. neurflow SSE `/executions/{id}/events`（neurflow_api.py:601-626）属主判断对匿名用户短路放行——匿名可订阅他人执行事件流。
7. `from tests.ast_scan import parseSource` 在 scripts/ 下另有 6 处（ci_static_gate、generate_api_inventory、ci/architecture_check、ci/cognitive_component_table、ci/context_deadline_ledger、ci/tool_loop_deadline_ledger）——P1-19 收口时一并裁定。
8. triage fail-open 不止异常分支：`no_history` 分支（triage.py:154-161）与 `'true' in content.lower()[:50]` 判定（:171-172）同根因，修 P1-10 时一并收口。
9. 移动端信封契约无单一事实源：后端裸数组/裸对象、`{code,data}` 信封、`{success,...}` 裸 dict 三种形状并存，移动端 23 个 API 模块统一按 `{code,data}` 解包——修 P1-28/29 须全量盘点，不许两边各改一半。
10. status_* 假颜色 token 还被 5 个 ohosTest 断言——修 token 时测试同批改，并在 StyleManager 增补三个真 token 单源。
11. 绕过 db_migration 自建表合计 6 个域（pending_memories＋channel_user_bindings/outbound_failures/ingress_bypass/approval_requests/evolution_jobs），应一批全部登记注册表。
12. xiaoyi 渠道事故根因之一是 ChannelConfig 双定义；全仓 10 处适配器手写 `get_channel_config`，收口时按教义第 7 条一并裁决。

---

*审计执行：10 个并行只读域审计＋主审复验汇总；2026-11-16 第二轮独立复核完成，勘误与新增命中点已就地回写（见 §11）。本报告为只读产物，未改动任何代码；修复执行前请按 §0.4 拍板项逐条决策。*
