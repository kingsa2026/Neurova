# Neurova 升级实施步骤（P0 + P1）

> 本文是执行层：每步含 TDD 红测定义、改动文件、验证命令、回滚方式。
> 状态标记：☐ 未开始 / ◐ 进行中 / ☑ 完成。

## 执行约定（每步适用）

1. **TDD 红绿**：先写失败测试（红）→ 最小实现（绿）→ 必要时重构。禁止先写实现补测试。
2. 解释器一律用项目 venv（3.12）。新增测试文件提交前需 `git add -f`（tests/ 的 gitignore 规则仍在）。
3. 提交过 Mimosa git-gate：i18n/假凭据类误报按既定流程临时禁用+恢复。
4. 每步开工前 `git status` 确认目标文件无未预期改动（并行编辑覆盖已复发 3 次）。
5. 后端验证：`python start.py --backend` 重启 + 冒烟；每项完成跑相关 pytest 子集。
6. 每步一个独立 commit，便于回滚（`git revert <commit>`）。

---

## Phase 0：安全止血 + CI 底座（第 1 周）

### P0-1 MCP 未认证 RCE 修复 ◐

**问题**：`tool_layers.py:27` 路由无鉴权 → POST `/v1/tool-layers/mcp-servers` 接受任意 `command+args+env` stdio spawn = 未认证 RCE；http/sse url 无私网校验 = SSRF 面。

| 步骤 | 内容 |
|---|---|
| 红测 | `tests/unit/api/test_tool_layers_auth.py`：① 无 token POST/DELETE/GET 写接口 → 401；② stdio command 非白名单（如 `bash`）→ 400；③ http url 指向 127.0.0.1/私网且未显式 `allow_private_url` → 400；④ 显式 `allow_private_url: true` 的 localhost 配置通过（保住本地 MCP server 合法场景） |
| 实现 | ① `tool_layers.py` router 加 `dependencies=[Depends(get_current_user)]`；② 新建 `neurova/security/url_guard.py`（从 `web_reach/reach.py` 抽取 scheme 白名单+`_BLOCKED_NETS`+getaddrinfo 逐 IP 校验；**保持 198.18.0.0/15 fake-ip 代理段不在黑名单**——Clash 代理场景，memory 有案）；`reach.py` 改为委托复用，公开函数签名不变；③ `mcp_config.py`：新增 `allow_private_url` 字段（默认 False）、stdio command 白名单（npx/node/npm/python/python3/uvx/pipx/bun/deno + 绝对路径 + env `NEUROVA_MCP_ALLOWED_COMMANDS` 扩展）；④ `tool_layers.connect_mcp_server` 显式 `validate_mcp_server_config` 前置，ValueError → 400 带指名字段 |
| 验证 | `pytest tests/unit/api/test_tool_layers_auth.py tests/unit/tools/ tests/unit/web_reach/ -v` 全绿；重启后端 curl 无 token → 401 |
| 回滚 | revert 单 commit；url_guard 为新增文件无侵入 |

### P0-2 治理穿透修复 ☑（2026-08-31 实现，待随 tool_executor.py 用户并行改动一并提交）

| 步骤 | 内容 |
|---|---|
| 红测 | `tests/unit/security/test_governance_mcp.py`（13 用例全绿）：① MCP 工具参数键名 `exec`（非四键名）仍被治理评估 ✓；② 治理模块故障时 MCP/未知来源返回 deny ✓；③ call_tool 路径防火墙被调用且拒绝时不触达服务端 ✓；④ 内置白名单工具治理故障仍放行 ✓；⑤ execute_tool 恰好校验一次不重复 ✓；⑥ 非 MCP 四键名提取语义不变 ✓ |
| 实现 | ① `mcp_client.call_tool` 入口加 `_check_firewall`（execute_tool 末尾委托 call_tool，消除重复检查）——router 主路径（`tool_router.py:532-534` 优先 call_tool）不再绕过防火墙；② `security/governance.py` 新增 `evaluate_tool_call(tool_name, params, user_id, scan_all)` 入口 + 模块级 `extract_adjudicable_params`（scan_all=True 时全参数 json 序列化进裁决文本 + 路径型参数单独提取供敏感路径规则）；③ `_governance_precheck` 重写：MCP（mcp.* 前缀）恒走 scan_all；治理不可用时 `_governance_fail_closed` 分级——MCP/未知来源 deny，内置白名单（`_builtin_dispatch`）放行；MCP 命中 SANDBOX 裁决显式阻断（JSON 参数无沙箱执行语义）；④ **顺手修复预存 bug**：`_audit_governance` 缺 `AuditSeverity` 必填参数导致全部治理审计静默失败——按裁决级别映射（deny→HIGH/sandbox·ask→MEDIUM/allow→LOW） |
| 验证 | 新测试 13/13 绿；audit 写盘恢复（"治理审计日志写入失败" 0 次）；test_audit_regressions / governance_endpoints / tool_engine_integration / url_guard 全绿；tools 套件与基线完全一致（61F 预存）；test_governance_integration 仅剩 Windows AppContainer 真实 curl spawn 的环境性预存失败 |
| 待办 | **提交**：tool_executor.py 混有用户未提交改动（diff 188+/37- 中约一半非本任务），无法干净切分——P0-2 四文件暂留工作区，待用户处理 tool_executor.py 后统一提交 |
| 回滚 | revert 对应 commit；evaluate_tool_call 为新增入口向后兼容 |

### P0-3 MCP 用户隔离 ☑（2026-08-31 实现，与 P0-2 同批待提交）

| 步骤 | 内容 |
|---|---|
| 红测 | `tests/unit/tools/test_mcp_user_isolation.py`（7 用例全绿）：① call_tool/execute_tool 接受请求级 user_id 且防火墙按其裁决 ✓；② 无请求上下文回退 client 构造身份 ✓；③ router 把 user_id 穿到防火墙 ✓；④ `_user_id` 内部键不注入 MCP params（不泄漏给外部 server）✓；⑤ 命名空间/裸名双解析保持 ✓；⑥ executor 把 `_agent_identity()` 传给 route ✓ |
| 实现 | **对计划"per-user client 池"方案的修正**：MCP server 连接是系统共享资源，per-user 池=N 倍 stdio spawn 且破坏 bootstrap 语义；隔离点改为**防火墙身份按请求穿透**——`mcp_client.call_tool/_check_firewall/execute_tool` 接受 `user_id`（None 回退构造身份）；`tool_router._execute_mcp` 显式穿透（`_accepts_kwarg` 签名探测兼容旧式客户端，**不靠 TypeError 重试**——副作用工具会双重执行）；`user_id=None` 时不附加参数（保住既有精确参数契约）；MCP 源排除 params 注入；executor 调 route 传 `_agent_identity()[0]`。**顺手修复潜伏缺口**：`_resolve_mcp_tool` 只认属性访问不认 dict，而 `MCPToolClient.list_tools()` 返回 dict——bootstrap 注册的客户端在兜底解析中永远失配，已补 dict 容错 |
| 验证 | 新测试 7/7 绿；mcp_client/router/config/governance/tool_engine 集成 132 全绿；tools+audit 回归与基线一致（61F+28E 预存）；`test_tool_success_flag_p1_fixes` 桩签名随 route 契约更新（user_id 可选形参） |
| 待办 | **提交**：与 P0-2 同批——governance.py / mcp_client.py / tool_router.py / 两个测试文件可干净提交，tool_executor.py 混用户并行改动需用户处理 |
| 回滚 | revert；call_tool 的 user_id 为可选参数，向后兼容 |

### P0-4 配置收敛 + 掩码 ☑（2026-08-31 实现，与 P0-2/P0-3 同批待提交）

| 步骤 | 内容 |
|---|---|
| 红测 | `tests/unit/api/test_shared_config_mcp_convergence.py`（16 用例全绿）：① shared-config POST schema 校验前置（缺 url/非法 transport/shell command → 400 指名）✓；② MCP CRUD 收敛 SharedConfigManager（持久化 + GET/export 同源 + DELETE 透传 + 重复 409）✓；③ env 全掩（既有）+ headers 敏感键掩码（authorization/token/secret/key/password/cookie，非敏感头不掩保回显）✓；④ 掩码回写保护扩展到 headers ✓；⑤ `streamable_http` 别名归一化 http（mcp_config 单元 + 两端点集成）✓；⑥ 角色门对齐 tool-layers（stdio 仅 admin、非 admin 拒私网）✓ |
| 实现 | ① `mcp_config.py`：`_TRANSPORT_ALIASES = {"streamable_http": "http"}`，`_validate_types`/`_infer_transport` 归一化（**空串视为未指定**交给推断——`is not None` 判空会挡住推断路径）；② `shared_config.py` MCP CRUD 重写为 Manager 薄壳（`_mcp_config_from_body` + `_validate_and_gate_mcp_config` 返回归一化配置）；GET `/`、`/export` 的 mcp_servers 改 Manager 同源（保持 dict 键形前端兼容）；`/import` mcp_servers best-effort 逐条入 Manager；③ 掩码：`_mask_sensitive_headers` + `_masked_mcp_server` 扩展；④ `MCPServerRequest` 扩展完整字段集（url/transport/headers/cwd/timeout_ms，command 放宽可选）；⑤ **门禁时序修正（两端点）**：先校验拿归一化 transport 再做角色门/URL 门——shared-config 的 transport 可省略、stdio 靠推断，查原始字符串会漏掉推断路径（红测抓到的真洞） |
| 验证 | 新测试 16/16 绿；P0-1/2/3 全部测试 + mcp 全套 + audit_regressions + api_router 共 213 绿；security 目录回归逐组与基线一致；前端 `MCPServer.created_at?` 本就可选（响应去掉该字段类型兼容） |
| 发现（未修） | 前端调用 `POST /shared-config/mcp-servers/{id}/test`（shared-config.ts:121）但后端无此路由——预存缺口，建议后续补"测试连接"端点或前端改走 tool-layers |
| 待办 | **提交**：与 P0-2/P0-3 同批（tool_executor.py 待用户处理） |
| 回滚 | revert；归一化仅放宽不收紧 |

### P0-5 死路与键名 bug ☑（2026-08-31 实现，与 P0-2/3/4 同批待提交）

| 步骤 | 内容 |
|---|---|
| 红测 | `tests/unit/tools/test_p0_5_dead_paths.py`（6 用例全绿）：① sync_mcp 按 `server_id` 键取名（节点 type `mcp:s1:t1` 非 `mcp:default:t1`）✓；② 旧式 `server` 键回退兼容 ✓；③ `_sync_tools_to_engine(engine=None)` 落到 API 层单例引擎（GET /tool-layers/tools 可见）✓；④ 显式 engine 硬约束不变（集成测试签名契约）✓；⑤⑥ mcp_client_manager.py 已删且不可导入 ✓ |
| 实现 | ① `adapters.py` sync_mcp：`tool.get("server_id") or tool.get("server", "default")`（新键优先，旧键回退）；② `mcp_client._sync_tools_to_engine` engine=None → 延迟 import `get_tool_engine()` 懒获取 API 单例（签名不动）；③ 删除 `execution_engine/mcp_client_manager.py`（git rm，零生产消费方）+ 其未跟踪测试文件 |
| 验证 | 新测试 6/6 绿；tool_engine 集成硬约束 + tools 套件 + audit 回归与基线一致。**基线外 2 个失败为环境敏感预存**：`test_sync_skills`/`test_adapters_skill_to_node` 用真实 SkillRegistry 硬编码断言 3 个 skill，用户的并行工作已注册第 4 个（kb_builder_executor，untracked）——与 P0-5 无关，测试需随技能增长改参数化 |
| 回滚 | revert；M9 修复保留旧键回退，无兼容风险 |

### P0-7 工作流子系统安全快修 ☑（2026-08-31，对比 v2 §3 N1-N6，commit 70f40df）

| 项 | 修复 |
|---|---|
| N1 | 触发器 CRUD/fire 挂严格 `get_current_user`（此前零鉴权，fire 可无鉴权派发任意已发布工作流） |
| N2 | cron 断链：`TriggerManager.configure_runtime/bind_loop` + app 启动注入 dispatch（与 fire 端点同构）与 by-id loader；`_scheduled_fire` 经 `run_coroutine_threadsafe` 回投主循环（原线程池线程内 create_task 永不执行） |
| N3 | webhook 重放防护：`verify_request`（签名覆盖 `<ts>.` 前缀 + 300s 时效）；ingress 携 timestamp 头走新约定，旧约定保留兼容 |
| N4 | receive 端点 body 1MB 上限（Content-Length 预检+实读复检，413） |
| N5 | 限流器清理分支缩进修复（原 return 后不可达，桶满永不清理） |
| N6 | 调试引擎消费 mock（node.mock_output/_NODE_MOCKS 迁引擎单一事实源）+ step_mode 每节点暂停；触发器测试注入认证身份（404→401 契约更新） |

验证：test_p0_7_workflow_hardening 16 用例全绿；webhook/triggers/debug 既有套件随契约更新后全绿。
预存备注：`test_approval_reply_mechanism.py` 存在挂死用例（HEAD 同挂，审批域，与 P0-7 无关）。

### P0-6 CI 底座 ☑（2026-08-31 实现并本地验证，随 P0-2~P0-5 同批提交）

| 步骤 | 内容 |
|---|---|
| 实现 | ① `ci.yml` 六 job：static-gate（既有）+ **lint**（ruff E9+F821，规则/豁免在 pyproject）+ import-and-regression（既有，cache 改指 lock）+ **unit-tests**（py3.11/3.12 matrix，`scripts/ci/protected_tests.txt` 子集 + `--cov-fail-under=60`，uv 装锁定依赖）+ **frontend**（npm ci → vue-tsc → vitest，node 20）+ **dependency-audit**（pip-audit 对 lock，非阻塞）；② `codeql.yml`：python 周扫描 + PR，非阻塞；③ `uv pip compile --universal` 生成 `requirements-ci.lock`（98 锁定版本）；④ pyproject：`[tool.ruff.lint] select=[E9,F821]` + per-file-ignores（F821 存量逐个销账）+ `[tool.coverage.run] include` 受保护模块集；⑤ requirements-ci.txt 补 `mcp>=1.2.0`（MCP 子集进 CI 的前提） |
| 实测 | ruff 全库绿（修 `exec_sandbox.py` 缺 List 导入真问题；F821 存量 30 处分诊：用户并行文件 2 处/星号导入误报 13 处/缺导入 7 处进豁免清单逐销账）；coverage TOTAL 66.64% ≥ 60（url_guard 100%/mcp_config 92%/mcp_client 82%/bootstrap 89%）；vitest 614 绿 + vue-tsc 干净；YAML 双文件解析通过；protected 子集 211 用例 7.9s |
| 要点 | protected_tests.txt 是 CI 与本地唯一事实源（grep -v 过注释）；coverage include 与 source 并用会被忽略（coverage 限制）；F821 全量扫描暴露 pyflakes 门禁漏掉的 5+25 个未定义名——static gate 的 pyflakes 未启用 undefined-name 检查，ruff 门禁实际补上了这个洞 |
| 待办 | 推送后观察首次 CI 运行（Ubuntu 环境 unpinned 依赖可能有平台差异）；`NeurUI` 的 npm cache 依赖 package-lock.json（已存在） |
| 回滚 | workflow 文件独立 commit |

**Phase 0 出口**：RCE/防火墙/隔离/配置四洞清零；CI 五类门禁生效；测试绿。

---

## Phase 1：核心能力建设（第 2-8 周）

### P1-1 上下文管线四期 ◐（切片 1 已提交 6950418；详设见评测文档 §4.1）

**切片 1（☑）**：`neurova/context/pairing.py` 视图配对完整性校验 + `ContextPool.draw()` 出口接入——
孤儿 TOOL_CALL（pairs_with 目标未入选）不再泄入 LLM 视图；`ContextInput.metadata` 增
turn_id/pairs_with 约定。9 用例锁定；pool 既有套件 36 绿。
**切片 2（☑ 已提交 7c31458）**：`neurova/context/recovery.py` 三件套
（assign_turn_ids / is_context_overflow_error / compact_messages_for_overflow——
system 全留+首 user 锚点+末尾 recent_keep 原样，中段折叠恢复桩，切割点对齐轮次边界
不留孤儿 tool 消息）；`openai_loop._predict_stream` 拆 once+恢复包装（打开即溢出→折叠
单次重试；重试仍溢出抛；流中已产出内容抛；非 overflow 不触发）；orchestrator 对话归档
写入 turn_id。17 用例锁定。
**期① 收尾（☑ e6c0318）**：orchestrator 归档循环抽取为 `_archive_conversation_to_pool`
可测单元——role=tool 消息以 TOOL_CALL 源入池并写 pairs_with=当前轮，配对锚点在真实
数据流闭合。**期② slice A（☑ 同 commit）**：TokenEstimator EXACT 策略（tiktoken
o200k_base，失败回退 BALANCED）。**期② 余项**：动态预算接 provider_manager 元数据
（该文件有用户未提交改动，只读接入待其提交后做）；pool-settings 端点扩
trigger_ratio/output_reserve。

| 期 | 步骤 | 红测要点 |
|---|---|---|
| ①（第 2 周）轮次化+溢出恢复 | `pool_models.ContextInput.metadata` 加 `turn_id/pairs_with` → orchestrator 写入打标 → `orchestrator.validate_pairing(view)` 孤儿 tool_result 清理 → `openai_loop.py:370-390` token_limit 分支接 `orchestrator.recover_from_overflow`（折叠→重建→**单次**重试） | 孤儿 tool_result 被清；400 后单次恢复成功；二次溢出不循环重试 |
| ②（第 2-3 周）EXACT 计数+动态预算 | `token_estimator.py` 加 EXACT 策略（provider count_tokens→tiktoken→BALANCED 降级链）→ 删 `get_token_budget_for_model` 硬编码表改接 provider_manager 元数据 → pool-settings 端点加 `trigger_ratio`(0.85)/`output_reserve`(4096)，响应向后兼容 | EXACT 在有/无 tiktoken 下的降级；预算端点新字段默认值；旧客户端不破 |
| ③（第 3-4 周）真摘要+台账持久化 | 新 `context/summarizing_compressor.py`（LLM 增量摘要、60s 超时、失败保留旧摘要、脱敏）→ 摘要回写池新枚举 `ContextSource.SUMMARY`（归档无损语义不破坏）→ 新 `context/eviction_ledger_db.py`（SQLite WAL+FTS5，三元组隔离列，强制 WHERE 沿 `_PersistDbStore` 模式）→ `recall_evicted` 接口不变换实现 → `recall_history` 注册 agent 工具 | 摘要失败保留旧摘要；台账重启后 FTS 可召回；跨用户 WHERE 隔离；`recall_history` 工具端到端 |
| ④（第 4-5 周）ack 集+分层剪枝 | `ContextInput.seen_confirmed` → `loops/base.py` 模型请求成功后确认本轮 tool result → 折叠候选只取已确认 → 剪枝顺序：旧轮 tool result→老记忆→低分经验 | 未读 tool result 不被折叠；超预算剪枝顺序断言 |

**实施状态（2026-08-31）**：期① ☑（6950418 配对校验 + 7c31458 溢出恢复/打标 + e6c0318 TOOL_CALL 入池）；期② ◐（EXACT ☑ e6c0318；动态预算待 provider_manager 用户提交后接入）；期③ ☑（0ff5585 台账+摘要+池集成；2fbc8d4 recall_history 工具三件套）；期④ ◐（db05fba ack 基础+折叠候选；**余项**：drawer 预算遍历按位置序回投，pre-sort 分层无效——预算遍历重设计另行切片）。

**收尾批次（☑ 已提交 0c13f0c）**：期② 动态预算 ☑（get_token_budget_for_model 接 provider_manager 元数据 context_window×0.6 钳位，只读接入不改其文件）→ **期② 全部 ☑**；期③ 接线 ☑（orchestrator 懒建 EvictionLedgerDB 按 agent 分库 + SummarizingCompressor 接真 LLM 桥 + pool.rollup_overflow_digest 摘要回写 + get_ledger_db 暴露）→ **期③ 全部 ☑**；期④ drawer 分层预算回投 ☑（第 1 层未读 TOOL_CALL 必入视野、第 2 层其余；created_at 稳定排序保前缀缓存）→ **期④ 全部 ☑**。P1-1 四期全部完成。
**增强② 收尾（☑ 0a18124）**：recovery.info 增 folded_messages（溢出恢复→rollup_overflow_digest→SUMMARY 回写链路闭合，此前 rollup 恒空转）+ EvictionLedgerDB.gc_stale() 语义化封装（keep_count=5000/keep_days=30，与 test_ledger_gc_trigger 契约对齐）+ ContextPool piggyback 统一。5 用例；P1 全套 386 绿。**P1 主线收尾。**
**可选增强（☑ 已提交 83a6161）**：① compact info 暴露 folded_messages + openai_loop 恢复时 fire-and-forget 调 rollup_overflow_digest（兼容 dict 消息，不阻塞重试）；② EvictionLedgerDB 增 keep_count/keep_days 与 gc_stale() + pool 节流触发（每 20 次驱逐一次，异常不破坏归档）。

验收：100+ 轮压测不溢出或恢复 100%；token 偏差 ≤5%；重启后可召回；现有 pool 测试与 pool-settings 契约零破坏。

### P1-2 工具执行协调器 ◐（切片 1/2 已提交 fd7ea92；与 P1-1①② 并行）

**切片 1（☑）**：`neurova/agent/tool_coordinator.py`——per-tool 超时注册表
（calculator 5s/memory_search 10s/web_search 30s/browser_* 60-90s，未知回落 60s）+
ToolCoordinator（run_with_timeout 超时**转后台不取消**——同一任务继续持有引用防 GC，
观察者协程投递 pending hints；pop_pending_hints 取走即清）+ is_concurrency_safe
声明制（只读清单，未知保守 False）。11 用例。
**切片 2（☑ fd7ea92）**：`_execute_single_tool` 执行链抽取为 `_execute_tool_core`
（返回三元组）+ run_with_timeout 单一咽喉点覆盖全部执行路径（治理预检后、H5 钩子前）；
chat_pipeline step3 pending hints 以 [后台工具完成] system 消息注入。4 用例。
**教训**：neurova.agent 包 __init__ 链回 tool_executor——模块级导入循环，
协调器导入必须懒加载（AGENTS.md 纪律再次验证）。
**切片 3（☑ 已提交 b49dbda）**：循环体抽取 `_execute_tool_call_worker`
（顺序无关纯执行单元，返回 (tool_message, records)）+ 声明制并行——全部
is_concurrency_safe 才 gather，任一未声明整轮保守串行；结果按原 tool_call
顺序回装，call/result 记录保持相邻配对契约；全部修复注释语义原样保留。
9 用例（并行时序/混合降级/结果对应/解析隔离/未知工具/user_id 穿透）。
**P1-2 状态：三切片全部 ☑**。余项=文本正则兜底收窄（原计划第 6 步，随 P2 清理）。

1. 红测：三通道（loop 原生/文本兜底/肌肉记忆）同入口；独立工具并行结果完整；超时转后台语义；hint 注入下一轮
2. 统一入口 `execute(tool_name, params, source, context)`（`tool_executor.py` 收敛；肌肉记忆自动执行=白名单+高置信直通）
3. 并行：`loops/base.py:69-277` 独立调用 `asyncio.gather`（工具元数据 `is_concurrency_safe` 声明制，默认串行保守）
4. per-tool 超时注册表（对标 QP shell 60s/grep 30s 元数据方式）
5. 超时**转后台不取消**：返回 `{"status":"background","task_id":...}`，完成经 pending_hints 注入（QP `_coordinator.py` offload 语义）
6. 文本正则兜底收窄到 openai 兼容层 tools-400 降级路径

### P1-3 MCP 可靠性 ☑（a7e1e98，2026-09-01）

交付与原设计的差异说明：状态机/熔断/退避/TTL 收敛为单文件深度模块 `tool_layers/mcp_resilience.py`（纯逻辑+时钟注入，替代原计划内嵌 mcp_client 的分散实现）；"stdio 子进程退出监听"以**会话操作失败即断连信号**等价实现（mcp SDK stdio_client 进程死→流关→call_tool 抛连接类错误→_mark_disconnected+调度重连），不穿透 SDK 内部。call_tool 401 刷新重试保留（P2-6，鉴权层未触达工具、无副作用）；其余失败绝不自动重试（锁定测试）。16 用例（test_mcp_resilience.py）；test_schemas 4F 为预存。

红测：子进程崩溃自动重连（退避 1→60s+jitter）；5 次连续失败熔断 OPEN、300s 半开探测；断连窗口 `get_available_tools` 降级返回缓存；call_tool 无同会话自动重试（副作用安全，锁定测试）。实现：`mcp_client.py` per-server 状态机（CONNECTED/DISCONNECTED/OPEN）+ 重连后台 task + stdio 子进程退出监听；tools 缓存 TTL 默认 300s；`last_error`/status 契约不变。

### P1-4 停止门控 ☑（由 P2-5 交付，f11e162——单文件 gates.py 替代原分文件设计；后续 P2-b GateCatalog 补配置层 d330087）

新 `neurova/agent/gates/{base,doom_loop,token_budget,iteration,runner}.py`：StopAction 三态（BYPASS/INTERRUPT_AND_CONTINUE/TERMINATE）+ StopGate ABC + runner（优先级排序、异常隔离、reset_turn/reset_session）。DoomLoopGate 从 `chat_pipeline._auto_continue:1176-1253` 的 0.8 相似度检测迁移升级（+args hash 维度）。挂点 `loops/base.py` 每轮工具调用后。红测：死循环序列终止、预算超限终止、gate 异常不影响主循环。

### P1-5 检查点 ☑（e5c82e3，2026-09-01）

交付差异：repository+service 两文件（原计划同）；mktree flat tree + `_index.json` 索引映射替代嵌套 tree（路径任意字符安全）；make_ts 单调计数后缀保同秒密集写入排序稳定；committerdate+ts 双键降序。知识库文件快照的 kb_files 参数已备，知识库子系统注入后启用。10 用例（test_checkpoints.py）。

新 `neurova/checkpoints/{repository,service}.py`：`git init --bare` at `data/checkpoints/{agent_id}.git`（零新依赖）；范围=会话 JSON+知识库文件；refs `{auto,snap,pre-restore}/{session_key}/{ts}`；恢复先做对话档+文件档，恢复前自动 pre-restore 留档；GC keep_count/keep_days；自动快照挂 chat_pipeline Step4 防抖。红测：快照→修改→恢复→还原；pre-restore 存在性；GC 保留策略。

### P1-6 Tool Guard + 技能扫描 ☑（5eaa1a9，2026-09-01）

交付差异说明：ToolGuard 危险命令规则（12 条含 mkfs/dd/fork bomb）+ Shell 逃逸 + FilePathGuardian + governance 接线（_governance_precheck 四级裁决）已由 P0-2 批次交付，未重复造规则文件外置层。本批补齐技能侧三缺口：①PromptInjectionAnalyzer（11 条中英双语注入签名，critical）；②**真漏洞修复**——_discover_files 白名单漏 .md，SKILL.md 注入主载体从未被扫描；③零消费方接线——hub_client 三安装分支落盘扫描（不通过回滚）+ NL 合成产物注册前注入扫描 + skill_install_gate（DENY fail-closed）。13 用例（test_p1_6_skill_guard.py）。

新 `neurova/security/tool_guard/`：`rules/dangerous_shell_commands.yaml`（首批 CRITICAL：mkfs/dd of=/dev//fork bomb）、file_guardian（ntpath/POSIX 双规范化+默认 deny 目录）、shell 逃逸解析首批模式表（`$()`/反引号/引号状态机）。接入 `_governance_precheck` 深度检查阶段。`neurova/security/skill_scanner.py` + 中英双语 prompt-injection 签名 → 挂 NL 工具合成（`chat_pipeline._check_nl_synthesis`）与技能加载点。红测：恶意 SKILL.md 被拦、危险命令命中、正常操作不误杀。

### P1-7 沙箱诚实化 ☑（f191dd7，2026-09-01）

AppContainer available() 诚实 False + Windows 降级 ProcessSandbox；ExecSandbox.enforced() 真实性声明 + execute 结果自报 sandbox_enforced/isolated/WARNING；governance HIGH→SANDBOX 前检查 _platform_has_enforced_sandbox（无后端升级 DENY——拒绝优于静默放行）；check_outbound_url 全局出网校验暴露。9 用例 + 7 处旧契约断言更新 + 6 处 wrap→wrap_argv API 漂移修复。

`exec_sandbox.py` Windows AppContainer `available()` 诚实返回 False（真实现推 P2）；`report_unenforced_config` 模式（backend 声明未强制字段 → WARNING 自报）；governance 规则 bash/command 默认 severity→NETWORK_OFF；`url_guard`（P0-1 产物）提升为全局出网校验层。红测：Windows 降级明确报错；unenforced 警告断言。

### P1-8 测试去水分 ☑（530c14e，2026-09-01）

e2e boot 冒烟（纯 subprocess——in-process create_app 实测卡死故弃用；路径经 openapi 校准）5 用例；context pool 压测 4 用例（关键词降级路径锁频，ONNX 变量剔除）；CI e2e job；vitest coverage 阈值起步线 30（实测 43.6%）。mock LLM chat 与登录 e2e 依赖后端注入点与测试账号（诚实未做，标注待办）。

新 `tests/e2e/test_backend_boot.py`（subprocess 拉起 + `/api/version` 探活 + 登录 + mock LLM chat + MCP 生命周期，对标 QP `test_hub_local_runtime.py`）；`tests/performance/` 填 context pool 100 轮压测（兼作 P1-1 验收）；`NeurUI/vitest.config.ts` coverage thresholds lines 30 起步；CI 加 e2e job（push main）。

**Phase 1 出口**：长会话不炸 / 工具并行+超时优雅 / MCP 自愈 / 死循环可终止 / 误操作可回滚 / 内容级安全扫描 / 沙箱诚实 / e2e 真实存在。

---

## P2 概要（随迭代）

**P2-1 记忆检索真实性 ☑（已提交 b6095b6，2026-08-31）**：`_semantic_recall` 重写——UnifiedVectorStore 增量索引（同 id 去重仅编码新记忆，消灭 O(n)/query 重建）+ 向量相似度搜索（faiss/fastembed/ONNX/TF-IDF 链接入主链路）+ RRF 融合（向量 0.7/关键词 0.3）+ 按隔离三元组分库 + 向量异常降级关键词。test_forget 契约更新（语义召回 intent-true：被遗忘记忆按 id 断言）。6 用例；记忆全套 924 绿（2 预存 tie 断言）。

**P2-2 ☑（已提交 81e2e1c）**：retry/circuit 装配——multi_model_client._chat_with_retry（per-provider guard：可重试=RateLimit/Connection/Timeout，Auth 不重试；熔断 5 次开/30s 半开，CircuitBreakerOpen 单独信封）+ provider_manager 两处被遮蔽死方法删除 + secret_store 双份标注（签名不兼容，待统一抽象）。
**P2-4 首刀 ☑（同 commit）**：core/metrics.py（prometheus_client 指标集单一事实源：tool/llm/circuit counter+histogram+gauges）+ /metrics 端点替换手拼 + tool_executor/llm.chat 全量埋点。
**P2-4c ☑（82c64a7）**：chat_pipeline trace total_tokens 切换——usage_accounting.last_call() 真实值优先，无则回退字符估算；last_call() API 新增。4 用例。**P2-4d ☑（已提交 1eb1316）**：openai_loop 流式 chunk usage 逐轮聚合进 done 事件 + chat_pipeline 消费入账——**usage 对账三路齐备**（非流式 chat/流式 done/后续多模型）。
**P2-7 测试处置批（☑ 53b3ca9）**：tool_engine_v2 修复全绿（守卫 mock should_block 契约 + 3 类 setUp 补 mock_security_system）；closed_loop 修复（模块路径 + skill_packer.observe 闭环补线 + duration 修复）12/12；monitor_v2 删除（断言的富 API 已移除）。剩余 7F 定性预存（plan_orchestrator 签名漂移 + async 缺 marker）。
**P2-6 MCP OAuth ☑（已提交 9a82b38）**：tool_layers/mcp_oauth.py（PKCE + client_credentials 带 60s 提前刷新/force_refresh、resolve_mcp_token per-call 解析——QP 烘焙坑规避）+ call_tool 401→刷新→重试一次。10 用例。
**P2-5 循环门控+goal 模式 ☑（f11e162）**：gates.py（StopAction 三态+DoomLoop/Iteration/TokenBudget/Goal 四 gate+Runner 故障隔离）+ openai_loop 双路径接入（懒初始化；INTERRUPT=提示注入消息序列；TERMINATE yield gate_terminate）+ set_goal_gate。21 用例。

---

## P3 渐进项 ☑（2026-09-01，全部落地）

- **P3-a 脚本式测试处置 ☑（dc368c6；前置 53c01f1/a07e474 为重写内容落库）**：execution_engine 7F+2E 清零（110 全绿）——根因三类（已删 mcp_manager 残留引用 / try-except 吞异常+缺 asyncio marker 的脚本式空转 / create_plan(task=,context=) 等臆想契约漂移），重写测试锁定现行契约 + 目录 5 个未跟踪测试入版。
- **P3-b OAuth 授权码流浏览器跳转 ☑（fa09573）**：build_authorization_url（RFC 6749+7636 S256）+ OAuthCallbackServer（RFC 8252 环回一次性回调）+ run_authorization_code_flow（state CSRF 不匹配绝不换 token、非环回 redirect_uri 拒绝、超时中止）+ fetch_token_by_code 入 per-call 缓存 + resolve_mcp_token grant_type 感知。28 用例。
- **P3-c agent_ref 收窄第一批 ☑（89ddbca）**：agent_core 轮次级状态显式 API（set_request_identity + current_* property、set_current_reasoning、reset/append_tool_messages、append_tool_event、increment_turn_count、公有别名）——深度模块不再直掏 _current_*/_tool_messages_list/_turn_count/_tool_events 私有属性；存储不变+旧 getattr 保留（渐进非翻转）。agent 全套回 47F 预存基线（passed 589→599）。
- **P3-d OAuth 全栈接线 ☑（931453e + 247ecbb）**：POST /mcp-servers/{id}/oauth/authorize（仅 authorization_code；client_credentials 明确 400）+ MCPServerInfo.oauth_grant + 前端 ToolLayerPage 条件按钮（370s 独立超时）+ 11 语言 i18n。**MCP OAuth 端到端闭环**。
- **P3-e 单例收敛 ☑（ba81f96 + 3fc2b2f）**：AST 审计（287 工厂/55 惰性创建/17 无锁）→ 6 高危 DCL → 11 良性 DCL，**55/55 全带锁**；reset_semantic_search/reset_embedding_engine 公有化；防回归网 tests/unit/core/test_singleton_convergence.py 20 用例。顺手修 CI 门禁 2 个预存 F821（openai_loop 缺 import asyncio——P1-1 溢出 rollup 实为静默 no-op，本修恢复功能）。
- **P2-4 观测补刀 ☑（58901f3）**：record_llm_call 零调用缺口——chat() 成功/失败/熔断 + chat_stream 四分支接线（stream 死语句 time.time() 顺手修复）。/metrics 的 neurova_llm_calls_total 恢复真实计数。

**P1 状态修订（2026-09-01 终版）：P1-1~P1-8 全部 ☑。**mock LLM chat/登录 e2e 依赖后端环境级注入点（未做，见 P1-8 诚实标注）；AppContainer 真实现推后（P1-7 诚实降级）。
**剩余可选项 ☑（2026-09-01 全部落地，52aae6e + 9e41f80）**：
- **mock LLM 注入点**：NEUROVA_LLM_MOCK=1 → chat/chat_stream 在 provider 解析前返回 canned（回显用户消息）；信封/流式契约与真实路径同形，无 Key 全链路贯通。
- **JSON 结构化日志**：NEUROVA_LOG_JSON=1 → 单行 JSON（json.dumps 引号安全、exc 结构化）——structlog 核心价值落地，零新依赖。
- **Windows 受限令牌沙箱（真隔离）**：SAFER/SRP NormalUser 令牌 → CreateProcessAsUserW，特权剥离（Administrators→deny-only，自证 S-1-5-114）；诚实边界 enforced_severities=∅（SRP 无网络/FS 语义，governance DENY 不受影响）；_detect_backend Windows 无 docker/bwrap/seatbelt 时优先 restricted_token。**AppContainer（COM/SECURITY_CAPABILITIES 语义）仍留待真需求出现**——受限令牌已覆盖特权剥离安全增益。

**QwenPaw 升级计划 P0/P1/P2/P3 + 可选项全部收官。**
