# Neurova 升级实施步骤（P0 + P1）

> 依据：[Neurova_升级计划_QwenPaw代码级评测_2026-08-30.md](../Neurova_升级计划_QwenPaw代码级评测_2026-08-30.md)（评测证据与 M1-M12 缺口清单在该文档）
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

### P0-2 治理穿透修复 ☐

**问题**：M3 `call_tool`（`mcp_client.py:314`）无防火墙而 router 优先走它（`tool_router.py:530-535`）；M4 `_governance_precheck`（`tool_executor.py:745-755`）只认 command/code/file_path/path 四键名；治理缺失 fail-open（`:739-740`）。

| 步骤 | 内容 |
|---|---|
| 红测 | `tests/unit/security/test_governance_mcp.py`：① MCP 工具参数键名 `exec`（非四键名）仍被治理评估；② 治理模块故障时 MCP 来源工具返回 deny（fail-closed）；③ ToolRouter 走 call_tool 路径防火墙被调用（mock 断言）；④ 内置白名单工具治理故障仍放行（不误杀） |
| 实现 | ① `mcp_client.call_tool` 入口加 `_check_firewall`（execute_tool 保留，二者不重复调用——firewall 加已检标志或只在 call_tool 检查、execute_tool 委托 call_tool）；② `tool_executor._governance_precheck` 增加全参数模式：MCP 来源工具把全部 string 参数值拼接交 `governance.evaluate(command=...)`，并在 `security/governance.py` 增加 `evaluate_tool_call(tool_name, params, scan_all=True)` 入口；③ fail-open 改分级 fail-closed：来源为 MCP/未知 → deny+audit，内置白名单 → 放行 |
| 验证 | 红测文件 + `pytest tests/unit/test_audit_regressions.py tests/unit/tools/ -q` 无回归 |
| 回滚 | revert；governance.evaluate 签名向后兼容（新增可选参数） |

### P0-3 MCP 用户隔离 ☐

**问题**：`get_mcp_client(user_id)`（`mcp_client.py:471-476`）单例只记首个 user_id，跨用户共享会话与防火墙身份。

| 步骤 | 内容 |
|---|---|
| 红测 | ① A 建连后 B 调用，`_check_firewall` 收到 B；② `get_mcp_client()` 无参仍返回 default（bootstrap/测试兼容）；③ 不同 user 的 client 不共享 `_servers` |
| 实现 | 单例 → `Dict[user_id, MCPToolClient]` client 池 + RLock；`mcp_bootstrap.py` 显式 user_id="system"；chat 请求链路传当前用户：`api/deps.py` 当前用户 → tool_router 执行上下文 → `_execute_mcp` 取请求级 user_id 建/取 client。注意 tool_router 是长生命周期对象，user_id 必须按请求传参而非构造时固化 |
| 验证 | 红测 + 双账号手工：A 配置的 server B 不可见（或按产品语义共享但防火墙身份正确——实施时与现有 shared_config 语义对齐） |
| 回滚 | revert（client 池对外接口不变） |

### P0-4 配置收敛 + 掩码 ☐

| 步骤 | 内容 |
|---|---|
| 红测 | ① shared_config 端点 POST 非法配置（未知键/缺 transport 输入）→ 400；② 读接口 headers 中 `Authorization`/`*token*`/`*secret*` 打码（现状只掩 env，`shared_config.py:33-40`）；③ `transport=streamable_http` 归一化为 http 被接受 |
| 实现 | ① `mcp_config.py` `_VALID_TRANSPORTS` 加 `streamable_http` 别名→归一化 `http`（M12）；② `shared_config.py` POST/PUT 前置 `validate_mcp_server_config`；③ 掩码函数抽公共 `_mask_secrets(mapping)` 覆盖 env+headers；④ 两套 CRUD 统一为 SharedConfigManager 薄壳（内存 dict 分叉删除） |
| 验证 | 红测 + 前端 `NeurUI/src/api/modules/` 相关类型对照（MCPServerInfo 形状不变） |
| 回滚 | revert；归一化仅放宽不收紧，无兼容风险 |

### P0-5 死路与键名 bug ☐

| 步骤 | 内容 |
|---|---|
| 红测 | ① M9 回归：`list_tools()` 返回 `server_id` → neurflow node server 名正确（`adapters.py` `tool.get("server")` 键名错）；② M8：API `GET /tool-layers/tools` 能列出已连 MCP 工具（engine=None 懒获取真实单例）；③ 删除 `execution_engine/mcp_client_manager.py` 后全量导入巡检通过 |
| 实现 | ① 键名改 `server_id`；② `mcp_client.py:437-438` engine=None → 延迟 import `get_tool_engine()` 懒获取（签名不动，test_tool_engine_integration.py 硬约束）；③ 删死文件（先 grep 确认零消费方+测试引用） |
| 验证 | `pytest tests/unit/tools tests/integration/test_tool_engine_integration.py tests/unit/neurflow -q` |
| 回滚 | revert |

### P0-6 CI 底座 ☐

| 步骤 | 内容 |
|---|---|
| 变更 | ① `ci.yml` 加 lint（ruff E9/F 宽松起步）、unit-tests（py3.11/3.12 matrix，跑健康子集：tools/api/memory/security + MCP 全量；预存失败模块不进 CI）、frontend（npm ci && vue-tsc && vitest run && eslint）；② `uv pip compile` 生成 `requirements.lock`，CI 用 lock；pip-audit job（allow-list 已知项）；③ 新 `codeql.yml`（python，非阻塞）；④ pytest-cov 对 tool_layers/context/security `fail_under=30` |
| 验证 | 推分支 CI 全绿；本地先跑 `ruff check` + 子集 pytest 预演 |
| 回滚 | workflow 文件独立 commit，revert 即可 |

**Phase 0 出口**：RCE/防火墙/隔离/配置四洞清零；CI 五类门禁生效；测试绿。

---

## Phase 1：核心能力建设（第 2-8 周）

### P1-1 上下文管线四期 ☐（详设见评测文档 §4.1）

| 期 | 步骤 | 红测要点 |
|---|---|---|
| ①（第 2 周）轮次化+溢出恢复 | `pool_models.ContextInput.metadata` 加 `turn_id/pairs_with` → orchestrator 写入打标 → `orchestrator.validate_pairing(view)` 孤儿 tool_result 清理 → `openai_loop.py:370-390` token_limit 分支接 `orchestrator.recover_from_overflow`（折叠→重建→**单次**重试） | 孤儿 tool_result 被清；400 后单次恢复成功；二次溢出不循环重试 |
| ②（第 2-3 周）EXACT 计数+动态预算 | `token_estimator.py` 加 EXACT 策略（provider count_tokens→tiktoken→BALANCED 降级链）→ 删 `get_token_budget_for_model` 硬编码表改接 provider_manager 元数据 → pool-settings 端点加 `trigger_ratio`(0.85)/`output_reserve`(4096)，响应向后兼容 | EXACT 在有/无 tiktoken 下的降级；预算端点新字段默认值；旧客户端不破 |
| ③（第 3-4 周）真摘要+台账持久化 | 新 `context/summarizing_compressor.py`（LLM 增量摘要、60s 超时、失败保留旧摘要、脱敏）→ 摘要回写池新枚举 `ContextSource.SUMMARY`（归档无损语义不破坏）→ 新 `context/eviction_ledger_db.py`（SQLite WAL+FTS5，三元组隔离列，强制 WHERE 沿 `_PersistDbStore` 模式）→ `recall_evicted` 接口不变换实现 → `recall_history` 注册 agent 工具 | 摘要失败保留旧摘要；台账重启后 FTS 可召回；跨用户 WHERE 隔离；`recall_history` 工具端到端 |
| ④（第 4-5 周）ack 集+分层剪枝 | `ContextInput.seen_confirmed` → `loops/base.py` 模型请求成功后确认本轮 tool result → 折叠候选只取已确认 → 剪枝顺序：旧轮 tool result→老记忆→低分经验 | 未读 tool result 不被折叠；超预算剪枝顺序断言 |

验收：100+ 轮压测不溢出或恢复 100%；token 偏差 ≤5%；重启后可召回；现有 pool 测试与 pool-settings 契约零破坏。

### P1-2 工具执行协调器 ☐（第 2-3 周，与 P1-1①② 并行）

1. 红测：三通道（loop 原生/文本兜底/肌肉记忆）同入口；独立工具并行结果完整；超时转后台语义；hint 注入下一轮
2. 统一入口 `execute(tool_name, params, source, context)`（`tool_executor.py` 收敛；肌肉记忆自动执行=白名单+高置信直通）
3. 并行：`loops/base.py:69-277` 独立调用 `asyncio.gather`（工具元数据 `is_concurrency_safe` 声明制，默认串行保守）
4. per-tool 超时注册表（对标 QP shell 60s/grep 30s 元数据方式）
5. 超时**转后台不取消**：返回 `{"status":"background","task_id":...}`，完成经 pending_hints 注入（QP `_coordinator.py` offload 语义）
6. 文本正则兜底收窄到 openai 兼容层 tools-400 降级路径

### P1-3 MCP 可靠性 ☐（第 4 周，依赖 P0-1/P0-3）

红测：子进程崩溃自动重连（退避 1→60s+jitter）；5 次连续失败熔断 OPEN、300s 半开探测；断连窗口 `get_available_tools` 降级返回缓存；call_tool 无同会话自动重试（副作用安全，锁定测试）。实现：`mcp_client.py` per-server 状态机（CONNECTED/DISCONNECTED/OPEN）+ 重连后台 task + stdio 子进程退出监听；tools 缓存 TTL 默认 300s；`last_error`/status 契约不变。

### P1-4 停止门控 ☐（第 4-5 周，依赖 P1-2 挂点）

新 `neurova/agent/gates/{base,doom_loop,token_budget,iteration,runner}.py`：StopAction 三态（BYPASS/INTERRUPT_AND_CONTINUE/TERMINATE）+ StopGate ABC + runner（优先级排序、异常隔离、reset_turn/reset_session）。DoomLoopGate 从 `chat_pipeline._auto_continue:1176-1253` 的 0.8 相似度检测迁移升级（+args hash 维度）。挂点 `loops/base.py` 每轮工具调用后。红测：死循环序列终止、预算超限终止、gate 异常不影响主循环。

### P1-5 检查点 ☐（第 6 周）

新 `neurova/checkpoints/{repository,service}.py`：`git init --bare` at `data/checkpoints/{agent_id}.git`（零新依赖）；范围=会话 JSON+知识库文件；refs `{auto,snap,pre-restore}/{session_key}/{ts}`；恢复先做对话档+文件档，恢复前自动 pre-restore 留档；GC keep_count/keep_days；自动快照挂 chat_pipeline Step4 防抖。红测：快照→修改→恢复→还原；pre-restore 存在性；GC 保留策略。

### P1-6 Tool Guard + 技能扫描 ☐（第 6-7 周）

新 `neurova/security/tool_guard/`：`rules/dangerous_shell_commands.yaml`（首批 CRITICAL：mkfs/dd of=/dev//fork bomb）、file_guardian（ntpath/POSIX 双规范化+默认 deny 目录）、shell 逃逸解析首批模式表（`$()`/反引号/引号状态机）。接入 `_governance_precheck` 深度检查阶段。`neurova/security/skill_scanner.py` + 中英双语 prompt-injection 签名 → 挂 NL 工具合成（`chat_pipeline._check_nl_synthesis`）与技能加载点。红测：恶意 SKILL.md 被拦、危险命令命中、正常操作不误杀。

### P1-7 沙箱诚实化 ☐（第 7 周）

`exec_sandbox.py` Windows AppContainer `available()` 诚实返回 False（真实现推 P2）；`report_unenforced_config` 模式（backend 声明未强制字段 → WARNING 自报）；governance 规则 bash/command 默认 severity→NETWORK_OFF；`url_guard`（P0-1 产物）提升为全局出网校验层。红测：Windows 降级明确报错；unenforced 警告断言。

### P1-8 测试去水分 ☐（第 7-8 周收尾）

新 `tests/e2e/test_backend_boot.py`（subprocess 拉起 + `/api/version` 探活 + 登录 + mock LLM chat + MCP 生命周期，对标 QP `test_hub_local_runtime.py`）；`tests/performance/` 填 context pool 100 轮压测（兼作 P1-1 验收）；`NeurUI/vitest.config.ts` coverage thresholds lines 30 起步；CI 加 e2e job（push main）。

**Phase 1 出口**：长会话不炸 / 工具并行+超时优雅 / MCP 自愈 / 死循环可终止 / 误操作可回滚 / 内容级安全扫描 / 沙箱诚实 / e2e 真实存在。

---

## P2 概要（随迭代，不在本批）

记忆检索接真向量（UnifiedVectorStore 已在，消灭假向量）；LLM 双抽象合一 + Retry-Fallback-RateLimit 三层；agent_ref 代理收窄 + 275 单例收敛（渐进）；structlog + prometheus_client + per-turn token 对账 + 成本核算；goal/mission 循环模式；MCP OAuth（凭据**每次调用时解析**，避开 QP 烘焙坑）。
