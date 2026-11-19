# ACP 编码代理团队接入设计方案

> 状态：**备稿待拍板**（2026-11-19）。目标：把外部专业编码代理（Claude Code、Codex、OpenCode、Gemini CLI、Qoder、CodeBuddy 等）经 Agent Client Protocol（ACP，Zed/JetBrains 主导的编辑器—智能体互操作协议）编入本仓 swarm/team 协作，补齐协作团队的「编码执行域」。**Trae 经用户裁定暂不接入（2026-11-19）**，其能力核实结论留档 §4.10 备查。
>
> 事实基础：本文档中协议与生态结论来自 2026-11-19 当日对 agentclientprotocol.com、官方 registry 与各工具官方文档的实时查证；仓内挂点来自对 `neurova/` 与 `NeurUI/src/` 的逐文件核实（行号以当日工作区为准）。

---

## 0. 结论摘要

1. **方向成立**：本仓成员模型是「名册 `user_id` → 进程内 Agent 实例 → `_run_member` 里一句 `agent.chat()`」。接入外部编码代理的最小切口，是让 `SwarmManager._resolve_agent` 对带外部执行体标记的名册成员返回一个 **chat 兼容适配器**；事件回灌、审批、台账、轨迹、数据围栏、进度流经现有 spawn 主链路自动生效，**不建第二套编排管线**（修复教义第 6 条）。
2. **生态现实**：ACP v1 稳定（传输仅 stdio），v2 草案中；官方 registry 已收录 46 个 agent。目标工具中，**OpenCode / Gemini CLI / Qoder / CodeBuddy 原生支持 ACP**，**Claude Code / Codex 经官方组织适配器接入**，**ZCode 无 ACP 支持（2026-11-19 四处核实：registry / llms.txt / CLI 文档 / CLI 源码目录均无）但 headless CLI 成熟（`--prompt` + `--output-format stream-json` NDJSON 事件流 + `--resume` 续跑）→ 插件形态首批落地对象**。**Trae 经用户裁定暂不接入（2026-11-19）**——其 ACP 能力（`traecli acp serve`，未进 registry，仅 TRAE 企业旗舰版可用）已核实并留档 §4.10，后续需要时可随时启用。
3. **角色模型**：Neurova 扮演 **ACP Client**（编排方/授权方），外部编码代理扮演 **ACP Agent**（被驱动的子进程/远端进程）。这与 Zed/JetBrains 把 ACP agent 接给「单个用户在编辑器里用」不同——本仓把它们编入**受治理的多代理团队**（任务书、验收门、审批链、房间协作、全量台账），是 ACP 生态尚无的编排层玩法。
4. **撞名澄清（必读）**：仓内已有 `neurova/agent/protocols/acp_runtime.py` + `team.py AgentTeam` + `acp_api.py`，那是**进程内 AgentMessage 消息总线**（自研 Agent Communication Protocol），与 Zed 的 Agent Client Protocol **同名不同物**，且该路线绕过 Swarm 治理/台账/验收——**不作为本方案主路径**。新模块命名经用户拍板（2026-11-19）：**统一以 `neuacp` 为准**，落 `neurova/agent/neuacp/`，类名以 `Neuacp` 前缀（`NeuacpMemberAdapter` 等），与仓内 `acp_runtime` 总线划清界限。

---

## 1. 背景与目标

### 1.1 背景与动机

- 本仓 swarm 成员是通用对话/工具代理，编码执行能力（大范围读写代码、跑构建与测试、多轮修复）弱于专业编码代理。
- ACP 已成为编码代理接入编辑器/IDE 的事实标准（Zed、JetBrains 原生支持，VS Code 经扩展、Emacs/neovim 经社区客户端），主流编码代理或原生支持或提供官方适配器。
- 把专业编码代理编入本仓团队，可组合出「本仓代理负责规划/记忆/治理 + 外部编码代理负责代码执行」的协作形态，直接增强 `spawn_subagent / dispatch_team` 的工程交付能力。

### 1.2 目标

- 外部编码代理可作为**团队名册成员**被 `dispatch_team` / `spawn_subagent` 派活，走统一任务书（TaskUnit）→ 执行 → 流式回报 → 结果候选 → 验收门/评审 → 合入 → 台账收行的全链路。
- 外部代理的工具/命令执行请求经 **ACP `session/request_permission`** 映射到本仓审批链（L0/L1/L2 + 房间审批卡），fail-closed。
- 提供本地（stdio 子进程）与远程（现阶段 SSH 隧道跑 stdio）两种接入形态。
- 前端完成团队名册、外部成员配置、进度面板、审批卡的适配（复用既有组件与事件通道为主）。

### 1.3 非目标（红线）

- **不建第二套编排/验收/存储体系**：外部成员必须走 `SwarmManager.spawn` 单管道；仓内 `acp_runtime/AgentTeam` 进程内总线不承载外部代理。
- **不做 ACP v2 适配**：v2 仍是草案（官方明示"will change"），锁 v1 稳定面；v2 定稿后另批。
- **不自制伪 ACP 硬接**：ZCode 无 ACP，走 §4.10 插件形态（已核实可接，插件首批落地对象）；Trae 走其官方 ACP（`traecli acp serve`）；均以工具实际能力为准，不臆造协议。
- **不默认开放**：新增能力以环境开关灰度（默认关），对齐 `NEUROVA_SWARM_ACCEPTANCE` 惯例。

---

## 2. 生态与协议事实（2026-11-19 查证）

### 2.1 ACP 协议

- 治理：Zed Industries 创建，现由独立组织 `agentclientprotocol/agent-client-protocol` 托管（Apache-2.0）；双 Lead Maintainer（Zed + JetBrains）。
- 版本：**v1 稳定**（"The current stable ACP protocol version is 1"）；**v2 处于 Draft**（2026-07-20 公告，内容仍会变）。
- 传输：**v1 仅定义 stdio**——客户端把 agent 作为子进程拉起，双方交换换行分隔的 JSON-RPC 2.0 消息。远程传输（Streamable HTTP + WebSocket）为 Active RFD，未定稿；官方对远程 agent 的表述是 "work in progress"。**现阶段远程的务实做法 = SSH 隧道跑 stdio**。
- 交互模型（v1）：`initialize`（版本/能力协商）→ `authenticate`（可选）→ `session/new` / `session/load` → `session/prompt` → agent 以 `session/update` 通知流式推送（消息块/工具调用/计划/模式变更）→ `session/prompt` 返回 stop reason；`session/cancel` 中断。
- 权限：agent 经客户端方法 **`session/request_permission`** 请求用户批准工具调用；工具调用以 `session/update` 流式上报（pending → in_progress → completed/failed）。
- 官方 registry：`https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json`，每 agent 一个目录 + `agent.json`（含启动命令、包名、版本），curated 清单。

### 2.2 七家目标工具支持矩阵

| 工具 | ACP 支持形态 | 接入方式（registry/官方文档口径） | 阶段 |
|------|--------------|----------------------------------|------|
| Gemini CLI | **原生**（首个参考实现） | `gemini --acp`，stdio JSON-RPC | P0 |
| OpenCode | **原生** | `opencode acp` 子命令，stdio ACP v1 | P0 |
| Claude Code | **官方组织适配器** | npm `@agentclientprotocol/claude-agent-acp`（基于 Claude Agent SDK，内置 Claude CLI） | P1 |
| Codex | **官方组织适配器** | npm `@agentclientprotocol/codex-acp`（内部翻译 Codex App Server 协议） | P1 |
| Qoder | **原生** | `qoder --acp`（官方文档 "Qoder CLI implements this protocol standard"） | P2 |
| CodeBuddy | **原生** | npm `@tencent-ai/codebuddy-code`，启动参数 `--acp`（registry 官方条目，Tencent Cloud） | P2 |
| ZCode | **无 ACP 支持**（2026-11-19 四处核实） | ACP registry / 官方 llms.txt / CLI 文档（quickstart、cli-reference）/ CLI 源码目录均无 ACP；但 **headless CLI 可插接**：`zcode --prompt <任务> --cwd <目录> --output-format stream-json --no-color`（NDJSON 事件流，`type:"result"` 终行，`--resume` 续跑），详见 §4.10 专项 | P2（**插件形态首批**） |
| Trae | **ACP 支持（官方文档核实，未进 registry）** | `docs.trae.cn/cli_agent-client-protocol`：`traecli acp serve`（亦 `traecli --acp`）以 subprocess+stdio 供 ACP 客户端拉起（Zed 为官方集成示例）；`--permission-mode <default\|auto\|bypass_permissions>`；**硬门槛：仅 TRAE 企业版旗舰版可用，须 PAT 登录**；headless 降级通道 `traecli exec --json`（JSONL 事件流，schema 无公开文档须实测），详见 §4.10 专项 | **暂不接入**（2026-11-19 裁定，结论留档） |

> 备注：registry 另收录 Cursor、GitHub Copilot（public preview）、Cline、Goose、Kimi CLI、Qwen Code 等 51 个 agent，可作为后续扩编池。ZCode 虽不在 ACP registry，但其 headless CLI 已核实可插接（见上表与 §4.10 专项）；Trae 支持 ACP 但未进 registry、有企业旗舰版门槛，**经裁定暂不接入**（结论留档 §4.10）。

---

## 3. 总体架构

### 3.1 角色与数据流

```
用户 / 主 Agent
   │  spawn_subagent / dispatch_team（既有工具，neurova/builtin_tools.py:1243/:1296）
   ▼
SwarmManager.spawn（neurova/agent/swarm.py:552）── 治理三明治/数据围栏/台账开行（不变）
   ▼
_resolveTeamMember → 名册成员带 executor 标记
   ▼
_resolve_agent 切口（swarm.py:1931）：executor.kind ∈ {acp, plugin}
   → 返回 NeuacpMemberAdapter（chat 兼容鸭子面），不再取进程内 Agent
   ▼
_run_member（swarm.py:2178）→ adapter.chat(task_text, stream=True,
   session_id=member_session_id, metadata={"event_emitter": ...})
   ▼
NeuacpMemberAdapter（新，neurova/agent/neuacp/）
   ├─ NeuacpStdioExecutor：JSON-RPC 2.0 over stdio（ACP v1）
   │    initialize → session/new → session/prompt（任务书文本）
   │    ← session/update（流式块/工具调用）→ emitter("content"/"reasoning")
   │    ← session/request_permission → requestRunApproval（审批链）
   ├─ NeuacpPluginExecutor：行协议文本插件（ZCode，已核实可接）
   ▼
session/prompt 返回 → 适配器返回 {"text": ...} → _extract_text
   ▼
_submitResultCandidate → runAcceptanceLoop → runReviewLoop → 合入（不变）
   ▼
closeSubagentRun + subagent_completed 广播（不变）
```

前端消费面（`SubAgentPanel.vue` / `useSubAgentWindows.ts` / 房间审批卡）对事件形状**零改动或微改**（§5）。

### 3.2 模块结构（新增）

```
neurova/agent/neuacp/     # 模块名经用户拍板（2026-11-19）：统一以 neuacp 为准
├── __init__.py
├── executor.py          # NeuacpExecutor 协议 + 会话生命周期管理
├── acp_client.py        # NeuacpClient：ACP v1 JSON-RPC over stdio 客户端（帧层复用 runner_bridge 骨架）
├── acp_executor.py      # NeuacpStdioExecutor：session/prompt/update/permission 映射
├── acp_member.py        # NeuacpMemberAdapter：swarm 成员鸭子面（chat/config.name/llm_client）
├── plugin_executor.py   # NeuacpPluginExecutor：通用 CLI 行协议插件（P2，ZCode）
├── catalog.py           # NeuacpCatalog：工具目录（内置七家预设 + 官方 registry 拉取缓存 + 本地命令探测）
└── process_pool.py      # NeuacpProcessPool：外部代理进程池（按 tool+command+cwd 复用进程；session 每 run 一个）
tests/unit/agent/neuacp/   # 单元测试（假 ACP agent 用测试内 stdio 子进程）
```

命名纪律：模块/类 PascalCase、函数 camelCase；包名/前缀统一 `neuacp`，**不复用** `acp_runtime`（已被仓内进程内总线占用）。

---

## 4. 后端设计

### 4.1 团队名册成员模型扩展

`neurova/api/endpoints/teams_api.py` 的 `members_detail` 单条结构（现：`user_id/name/role/prompt/joined_at`，add_members :288-297）增加可选 `executor` 字段（JSON 落盘 `_STORE_FILE`，向后兼容——无 `executor` 即内置成员，行为零漂移）。**执行体适配器落 `neurova/agent/neuacp/`（命名经用户拍板）**：

```json
{
  "user_id": "acp-opencode-1",
  "name": "OpenCode 编码代理",
  "role": "coder",
  "prompt": "负责前端组件实现，输出补丁与测试",
  "joined_at": 1731993600.0,
  "executor": {
    "kind": "acp",
    "tool": "opencode",
    "transport": "stdio",
    "command": ["opencode", "acp"],
    "cwd": "E:/workspace/demo",
    "env_keys": ["OPENCODE_API_KEY"],
    "permission_mode": "chain",
    "remote": null
  }
}
```

字段语义：

- `kind`：`acp` | `plugin`（插件形态，§4.10）。
- `tool`：目录标识（§4.9 catalog），用于默认命令与能力声明。
- `transport`：`stdio`（本地子进程）| `ssh`（远程：SSH 隧道跑 stdio）。
- `command`：完整启动命令（argv）。catalog 提供默认值，允许覆盖。
- `cwd`：外部代理工作目录（编码任务的目标仓库根）。**必须显式声明**，禁止默认落到本仓安装目录。
- `env_keys`：需要注入子进程的凭据**键名**清单；键值不经名册落盘，运行时从本仓凭据面（keyring/环境）按 `agent_id` 作用域取（对齐 QwenPaw 批 B5「凭据后缀+展开」先例）。
- `permission_mode`：`chain`（映射审批链，默认）| `auto`（仅 L0，且须 admin 建成员时显式勾选）。
- `remote`：`transport=ssh` 时的 `{host, port, user, key_ref}`；`key_ref` 指向凭据面，不落明文。

请求模型扩展：`MemberBatchAdd`（teams_api.py:78）增加 `executor: Optional[NeuacpExecutorSpec]`；**添加外部成员限 admin 角色**（外部成员涉及本机进程拉起与凭据注入，按核心原则第 9 条须显式受控；内置成员维持现状）。新增 `DELETE /{team_id}/members/{member_id}`（现名册无移除入口，前端亦无）。

### 4.2 `_resolve_agent` 切口（唯一主链路改动点）

`neurova/agent/swarm.py:1931 _resolve_agent` 前置一步：按 `run.team_id` 查名册，若命中成员带 `executor` 标记，则返回 `NeuacpMemberAdapter` 实例而非进程内 Agent。适配器鸭子面（与 `_run_member`/验收/评审的既有约定严格对齐，见核实报告）：

1. `async chat(user_input, *, stream=True, session_id, metadata)` → 返回 `str | {"text": str}`：
   - 必须消费 `metadata["event_emitter"]`，以 `emitter("content", chunk)`（可选 `emitter("reasoning", chunk)`）同步回调产出块——流式事件、卡死看门狗（`swarm.py:2011 _stallWatchdog` 读 `run.last_progress_at`）、失败交接缓冲（`contentBuffer`）都依赖它；
   - 整轮须在 budget（`run.runtime_budget_sec` 或 `NEUROVA_SWARM_SUBAGENT_BUDGET_SEC`）内返回，超时由 `asyncio.wait_for` 判 failed；
   - 失败要么抛异常、要么返回 `"[LLM Error] ..."` 前缀文本（`swarm.py:2314` 按失败处理）；
   - 不支持 temperature/max_tokens 等生成参数（签名约束，swarm.py:2256-2259）。
2. `.config.name` → 事件/台账/审批卡的 `agent_name`（swarm.py:758/:791）。
3. `.llm_client.chat(messages) -> 带 .content（建议带 .model）`：验收门/评审的受限判定通道（`callSubSessionChannel`，sub_session.py:25-41）。外部成员默认**不提供**（验收/评审诚实降级 skipped，不阻断）；如需提供，由适配器以目录内声明的「判定用小模型」实现。
4. `current_session_id` 语义 = `run.member_session_id`（递归 spawn 治理阀门依赖，swarm.py:2260-2265）。
5. 审批面：适配器内部直接调 `requestRunApproval(run, action, reason, level, context)`（approval_chain.py:267），run 对象字段已齐备。

**不改**：`spawn`、`_run_member`、`_broadcast`、事件账本、轨迹、围栏、验收/评审/合入、`closeSubagentRun`。

### 4.3 ACP stdio 客户端（neuacp/acp_client.py，`NeuacpClient`）

帧层/进程层复用 `neurova/channels/runner_bridge.py` 骨架，帧内协议换成 ACP v1：

- 进程拉起：`subprocess.Popen(command, stdin/stdout/stderr=PIPE, env=白名单环境, cwd=executor.cwd)`。环境白名单照抄 `_RUNNER_ENV_BASE_KEYS` 思路（runner_bridge.py:44-48）——代理变量天然被排除（规避 httpx/子进程代理坑），再叠加 `executor.env_keys` 的注入值与 `PYTHONIOENCODING=utf-8`（Windows 编码坑，见 `neurova/core/text_encoding.py` 注释）。
- 帧：**换行分隔 JSON-RPC 2.0**（ACP v1 stdio 规约），UTF-8，读侧 `errors="replace"` 容错；单帧上限对齐 1MB（runner_protocol.py:20-22 同量级）。
- 握手：`initialize`（protocolVersion="1"，clientCapabilities）→ 校验响应版本；不兼容即 terminate **fail-closed**（对齐 RunnerHost.start 的审计纪律）。
- 会话：每次 spawn 开新 ACP session（`session/new`，cwd 与任务上下文经 `session/new` 参数传入）；run 结束 `session/cancel`（对齐 `cancel_subagent`）并归还进程到池。
- 监督：崩溃回调 → 有限重启（对齐 `ChannelProcessSupervisor`，max_restarts=3）；stderr 泵落轨迹。
- 超时：prompt 级超时 = run budget；单请求级超时（initialize 等）30s（对齐 RunnerHost.sendRequest 默认）。

### 4.4 NeuacpStdioExecutor：事件与权限映射（neuacp/acp_executor.py）

| ACP 侧 | 本仓侧 |
|--------|--------|
| `session/update`（message chunk） | `emitter("content", text)` / reasoning 块 → `emitter("reasoning", text)` |
| `session/update`（tool_call pending/in_progress/completed/failed） | 镜像进 member span 轨迹（`TrajectoryRecorder.record_event`，trace_recorder.py:267）+ H-4 事件账本（`_logRunEvent`，swarm.py:1126）；**不经过**本仓 ToolExecutor（外部代理工具面自带，白名单语义见 §6.3） |
| `session/update`（plan/mode） | `emitter("reasoning", "[plan] ...")` 摘要呈现（不新造事件类型） |
| `session/request_permission` | `requestRunApproval(run, action=f"acp:{tool}:{kind}", reason=..., level=按动作分级, context=参数摘要)`；denied → 回复拒绝并继续会话；pending → 等待（审批超时语义沿用 `NEUROVA_SWARM_APPROVAL_WAIT_S`） |
| `session/prompt` 返回 stop reason | `end_of_turn`/`cancelled`/错误 → 适配器返回文本或抛错 |
| `session/cancel` | 对接 `cancel_subagent` 工具 → `SwarmManager.cancelRun` 链 |
| 连接断开/进程崩溃 | 适配器抛异常 → run failed（cause=`external_agent_crash`），台账诚实收行 |

权限分级建议（`classifyActionLevel` 已有危险命令升档，approval_chain.py:77-92）：文件读/搜索类 → L0；文件写/编辑 → L1；命令执行/网络/删除 → L1（危险命令正则命中升 L1/L2）；用户在 `permission_mode=auto` 且非危险时 L0 放行。**默认全部走 chain**。

### 4.5 进程池与生命周期（process_pool.py）

- 键：`(tool, tuple(command), cwd, transport, remote)`；池内进程承载多个 ACP session，空闲超时（默认 10 分钟）回收。
- 上限：全局并发外部进程数（默认 4，`NEUROVA_EXTERNAL_AGENTS_MAX_PROCS`），超限排队，防资源失控。
- 崩溃的进程踢出池；重启由下次 spawn 惰性完成。

### 4.6 台账 / 围栏 / 审计（自动生效点 + 需补点）

- **自动生效**（走 spawn 主链路即可）：`openSubagentRun/closeSubagentRun`（agent_run_ledger.py:359/:401，含 subagent_id/parent_session_id/trace_id/project_id/team_id 列）、H-4 事件账本、member span 轨迹、`buildDataFence` 数据围栏扫描（context_firewall.py:105，spawn 时扫任务文本与不可信载荷）。
- **需补点**：
  1. run 台账 `model` 列写 `external:{tool}`（区别于内部模型名），成本记账对外部代理**不按 token 计**（用量在外部体系），标注 `cost_source=external`；
  2. `SubAgentRun.subagent_type` 建议值 `external_coder`（前端徽标通用渲染已支持任意非 general 值，SubAgentPanel.vue:167-178）；
  3. 审计日志补一条「外部成员接入/移除」事件（security/audit_logger.py，admin 操作留痕）。

### 4.7 管理面 API（新增端点，挂 `/api/v1/external-agents`，admin 门）

- `GET /api/v1/external-agents/catalog`：目录 = 内置七家预设（含默认 command、是否需 npm、支持 transport）∪ 官方 registry 拉取缓存（TTL 24h，拉取失败降级内置清单）∪ 本地命令探测（shutil.which 标注「本机可用」）。
- `POST /api/v1/external-agents/test`：对给定 executor 配置做一次握手级连通测试（initialize 往返），返回能力/版本/错误——供前端「测试连接」按钮。
- `GET /api/v1/external-agents/status`：进程池状态（存活进程、活跃 session、近端崩溃计数）。
- 鉴权：`requireAdmin`（对齐 webhook 管理面教训——外部执行面必须有属主/角色门）。

### 4.8 远程形态（transport=ssh）

- 现阶段：本机经 SSH 在远端主机拉起同一 ACP 进程，stdio 经 SSH 隧道（`ssh -o BatchMode=yes host -- <command>`），复用配对档三的 SSH 凭据代管理经验（`key_ref` 指向凭据面）。
- ACP 远程 Streamable HTTP RFD 定稿后，再增 `transport=http` 实现（接口已由 `NeuacpExecutor` 协议预留），**不在本期实现**。

### 4.9 工具目录（catalog.py）

内置预设（默认 command 为官方口径，允许名册覆盖）：

```
gemini-cli : ["gemini", "--acp"]                 # 原生
opencode   : ["opencode", "acp"]                 # 原生
claude-code: ["npx", "@agentclientprotocol/claude-agent-acp"]   # 适配器，需 Node
codex      : ["npx", "@agentclientprotocol/codex-acp"]          # 适配器，需 Node
qoder      : ["qoder", "--acp"]                 # 原生
codebuddy  : ["npx", "@tencent-ai/codebuddy-code", "--acp"]    # 原生（npm 包启动参数 --acp）
trae       : 暂不接入（2026-11-19 裁定；ACP 能力已核实留档——["traecli","acp","serve"]，仅 TRAE 企业旗舰版+PAT，不进 catalog 生效预设）
```

registry 拉取仅作**扩编发现**（新工具浮现时提示可加），不作为运行时事实源——运行时以名册 `executor.command` 为准（单一事实源：目录给默认值，名册给生效值）。

### 4.10 插件形态（plugin_executor.py，ZCode）；附 Trae ACP 核实留档

`NeuacpExecutor` 协议统一两种形态：

```
class NeuacpExecutor(Protocol):
    async def start(self, ctx: SessionContext) -> None: ...      # 握手/建会话
    async def prompt(self, task_text: str, emitter, on_permission) -> NeuacpExecResult: ...
    async def cancel(self) -> None: ...
    async def close(self) -> None: ...
```

`NeuacpPluginExecutor` 约定（对 ACP 不可用但有 headless CLI 的工具）：spawn CLI 子进程，stdin 写任务文本，stdout 按行读 JSON 事件（`{"type":"chunk"|"tool"|"permission"|"done"|"error", ...}`），语义与 ACP 映射表（§4.4）一致。插件形态现有一个已核实落地对象（ZCode，见下）；Trae 的 ACP/CLI 核实结论见文末留档（已裁定暂不接入）。

**ZCode 专项（插件形态首个落地对象，2026-11-19 官方文档与源码核实）**：

- 驱动方式：`zcode --prompt <任务文本> --cwd <executor.cwd> --output-format stream-json --no-color --mode yolo --disallowed-tools "AskUserQuestion,EnterPlanMode,ExitPlanMode"`；stdout 逐行解析 NDJSON 事件，`type:"result"` 为正常终行；stderr 为诊断流，落 span 轨迹。退出码：成功 0、参数/运行错误 1、信号取消保留原始 signal；**权限拒绝不一定体现在退出码**（可能作为工具错误交回模型继续），验收须「事件流 + 文件产物」双核验，不裸信退出码。
- 续跑：`--resume <sessionId>`（须保持同一隔离数据目录）对接本仓 run 续跑/验收不达标回炉语义。
- 隔离红线（必须，因 headless `-p` 缺省即 `yolo` 权限档——非只读、非沙箱，且运行中无审批客户端，`ask` 类工具直接失败）：独立工作目录 + 每成员独立 `ZCODE_DATA_BASE_DIR` 数据根 + 环境变量白名单（复用 §4.3 机制）+ `--disallowed-tools` 收权；交互授权型 MCP 服务视为不批处理就绪，禁入。
- 局限（诚实登记）：单向管道（prompt→事件流→result），**无运行中双向控制通道**——无法像 ACP 那样中途审批/改参。故 ZCode 成员若 `permission_mode=chain`，审批发生在**派活前**（任务书级审批），运行中不再逐工具打扰；其高风险性由隔离红线 + 产物核验 + 事后审计兜底。
- 无官方 agent SDK / HTTP API：`@zcode/rpc`、app-server 为内部 IPC（无对外契约文档）；docs.z.ai 的 SDK 是 GLM 模型 API，与驱动 ZCode agent 无关，勿混淆。若未来 ACP registry 收录 ZCode 或官方发布 agent SDK，再升级接入形态（届时以本次核实的五处无证据点为基线复验）。

**Trae 专项（2026-11-19 官方文档核实：ACP 可用，企业版门槛）**——**已裁定暂不接入（2026-11-19），本节结论留档备查**：

- **主通道 = ACP**：`traecli acp serve`（等价 `traecli --acp`）以 subprocess+stdio 供本仓 ACP 客户端拉起，直接复用 §4.3/§4.4 的 `NeuacpClient`/`NeuacpStdioExecutor` 链路，**无需单独适配器**；权限经 `--permission-mode <default|auto|bypass_permissions>` 传入，本仓默认 `default`（`session/request_permission` 照映射审批链）。
- **降级通道 = headless exec**：`traecli exec --json --sandbox workspace-write --ask-for-approval never -C <executor.cwd> "<任务>"`，stdout 收 JSONL 事件流、`-o` 落最终结果、`--output-schema` 约束结构化产出、`resume/fork` 续会话。**JSONL 事件 schema 与退出码均无公开文档**——接入前必须实测采样真实事件流，适配层对未知字段容错，不臆造字段。
- **门槛与红线**：① TRAE CLI 2.0 / ACP **仅企业版旗舰版套餐可用**，且须 `TRAECLI_PERSONAL_ACCESS_TOKEN` + `traecli login --with-trae-pat` 登录（PAT 走凭据面按 `env_keys` 注入，不落名册）；② `-y/--yolo` 会同时跳过审批并**关闭沙箱**（文档自警仅限外部隔离环境）——本仓默认禁用，沙箱由 `-s/--sandbox workspace-write` 档位承担；③ headless 下审批必须显式落旗标（`-a never` + 沙箱档位），否则卡在人工审批；④ 未信任目录会**静默禁用**项目级配置/Hooks——`cwd` 须先过目录信任流程；⑤ 企业 OpenAPI 仅覆盖成员/用量/审计管理面，无任务驱动接口，不可作为接入面；⑥ `TRAECLI_HOST`/代理变量按 §4.3 白名单治理。

### 4.11 配置开关

| 环境变量 | 默认 | 语义 |
|----------|------|------|
| `NEUROVA_EXTERNAL_AGENTS_ENABLED` | `off` | 总开关；off 时名册含 executor 成员照常显示但 spawn 时拒绝并诚实报错 |
| `NEUROVA_EXTERNAL_AGENTS_MAX_PROCS` | `4` | 全局外部进程上限 |
| `NEUROVA_EXTERNAL_AGENTS_REGISTRY_TTL_S` | `86400` | registry 缓存 TTL |
| `NEUROVA_EXTERNAL_AGENTS_IDLE_S` | `600` | 进程池空闲回收 |

命名与读取惯例对齐 `NEUROVA_SWARM_ACCEPTANCE`（env 显式值最优先，默认保持现行为）。

---

## 5. 前端 UI 适配设计（NeurUI）

原则：**复用既有组件与事件通道为主，新增面集中在「配置外部成员」与「目录/状态呈现」**。

### 5.1 团队页名册增强（TeamPage.vue）

现状：成员是纯字符串数组（`Team.members?: string[]`，teams.ts L7-16），添加成员弹窗仅 members 多选 + systemPrompt；无角色列、无移除入口。

改动：

1. 名册列表改为读 `members_detail`（后端已返回），每行呈现：名称、角色、**执行体徽标**（内置 / `ACP·OpenCode` / `插件·ZCode`；外部成员用主色描边徽标，颜色走 `var(--nr-primary-light)` 等令牌，禁硬编码色值）。
2. 新增「移除成员」按钮 → `DELETE /teams/{id}/members/{member_id}`（后端 §4.1 同步新增）。
3. 「添加成员」弹窗拆两档：**内置成员**（现状交互不变）与**外部编码代理**（新增表单，见 5.2）。

### 5.2 外部成员配置表单（新组件 `TeamNeuacpMemberForm.vue`）

字段（与 §4.1 契约一一对应）：

- 工具类型：下拉（catalog 接口返回；每项含原生/适配器标注、本机可用探测结果、需 Node 提示）；
- 成员名称 / 团队角色（coder/reviewer/...，沿角色语义）；
- 职责 prompt（进任务书拼装）；
- 工作目录 `cwd`（必填，路径选择/输入）；
- 启动命令（预填 catalog 默认，可改）；
- 传输方式：本地 stdio / SSH（SSH 展开 host/port/user/key_ref 选择）；
- 凭据键名 `env_keys`（标签输入；**只录键名不录值**，值走凭据面）；
- 权限模式：审批链（默认）/ 自动放行 L0（admin 可见，选中需二次确认）；
- 「测试连接」按钮 → `POST /external-agents/test`，展示握手结果（版本/能力/错误原文）。

提交 → `POST /teams/{id}/members`（body 扩 `executor` 字段）。表单校验：`cwd` 必填、`command` 非空、`permission_mode=auto` 需 admin。

### 5.3 进度与状态（基本零改动）

- `useSubAgentWindows.ts` / `SubAgentPanel.vue`：外部成员复用 `subagent_started/chunk/stalled/completed` 同形事件（后端经既有 `event_emitter` 通道发出），**零改动**；`subagent_type="external_coder"` 徽标由既有通用渲染直接显示。仅当引入新状态词值才需扩 `LEDGER_TO_WINDOW_STATUS`（本方案不引入新状态值，复用 running/completed/failed）。
- 可选增强（P1）：SubAgentPanel 徽标旁显示外部工具名（从 run 载荷 `agent_name`/`subagent_type` 推导），不加新事件。

### 5.4 审批 UI（零改动 / 微改）

- L1/L2 房间审批卡：`CollaborationRoomPage.vue` L62-93 既有 `swarm_approval` 卡与 `decideRoomApproval` 通道直接复用——外部代理的 `session/request_permission` 经 `requestRunApproval` 落同一审批单体系，卡片自动上墙。action 文本带 `acp:opencode:write_file` 字样即可区分来源，无需新卡片类型。
- `auto` 模式提示：外部成员行内标注「自动放行（仅低危）」。

### 5.5 管理入口与路由

- 团队页内完成外部成员配置（不新开顶级页面），符合「团队管理不加新工具面防膨胀」的 S13 口径。
- 目录/连通性调试入口：团队页「外部代理」次级 Tab 或设置页一个只读状态卡（进程池/近端崩溃），调用 `GET /external-agents/status`。
- 权限：外部成员的添加/移除/测试连接按钮 `v-if` admin（`authStore.user.role==='admin'`，permissions.ts 判定惯例）。

### 5.6 i18n 与主题

- 新增键预估 25-35 个（nav 0-1、团队名册 8-12、外部成员表单 10-14、状态/审批标注 3-5、测试连接 2-3），**×11 locale 全量同步**（zh-CN 基准 + en-US/ru-RU/ja-JP/fr-FR/ar-SA/ko-KR/es-ES/de-DE/hi-IN/it-IT），守卫 `locale-consistency.test.ts` 强制键集一致、两层 camelCase、禁空值。
- 样式只用 `--nr-*` 令牌（variables.css），双皮肤×双明暗自适配；JS 侧取 `styles/tokens.ts` 镜像。

---

## 6. 安全与治理

### 6.1 威胁面与对策

| 威胁 | 对策 |
|------|------|
| 外部代理任意执行命令/写文件 | permission 请求全量映射审批链（fail-closed）；危险命令正则升档；`permission_mode=auto` 仅 L0 且 admin 显式开启 |
| 凭据泄漏 | 名册只存键名不存值；子进程环境白名单 + 按需注入；日志/轨迹/审批卡对 env 值与命令参数做 redact（对齐入模前脱敏闸经验） |
| 供应链（npx 拉包） | catalog 标注适配器包名与版本；测试连接时记录实际版本；后续可加包完整性校验（P2 增强） |
| 数据外发 | 外部代理把代码/上下文发给其模型服务商属**用户自主选择**；spawn 时数据围栏照扫并告警标记（run.data_fence），团队页展示「该成员会把工作目录内容送至外部模型」提示 |
| 失控进程 | 进程池上限 + 空闲回收 + 有限重启 + run budget 超时 + `session/cancel` 对接 cancelRun |
| 越权管理 | catalog/test/status 端点 admin 门；名册外部成员增删 admin 门；审计日志留痕 |

### 6.2 审批链映射（复用不新建）

`requestRunApproval(run, action, reason, level, context)` → L0 自动放行 / L1 投父邮箱（interactive）或 auto_approve / L2 强制人工 + 房间审批卡；裁决单源 `decideSwarmApproval`（父裁/房裁同源，decidedByChannel 标记通道）。外部代理不新增审批形态，只新增 action 命名空间 `acp:{tool}:{kind}`。

### 6.3 工具面白名单语义

外部代理**自带工具**（其 CLI 内置 bash/edit 等），不经过本仓 `computeSubagentToolAllowlist`（swarm.py:711）。约定：外部成员不参与本仓工具白名单借用（`mcpBorrowedToolNames` 对其无效）；其工具调用以 ACP update 事件**镜像进轨迹与账本**，实现「不纳管执行、但全量可见」——这是与内置成员在治理上的关键差异，须在团队页成员详情中明示。

### 6.4 可借鉴机制台账（源自 ZCode 官方文档 2026-11-19 核实；登记备查，不属本期接入范围，另批评估）

1. **AIMD 共享并发治理**：按 provider key 的自适应限流（降 ×0.75 / 连胜 +1）+ run 级上限取小 + 超限子代理 parking 保位 + 「工具执行不占票据」——可用于 swarm 多成员的模型配额公平调度。
2. **工作流 journal/resume/supersede**：run 全量 journal、恢复即重放（"Resume is crash recovery, not re-verification"）、修订版取代在跑 run 并记录 supersededBy。
3. **hooks 工作区信任 digest**：PreToolUse 同步阻断（退出码 2）+ 信任与 hook 声明内容绑定 digest、声明变更即失效、存储损坏 fail-closed。
4. **类型化 hole + escalate**：工作流留类型化空缺由主模型运行中填充；子代理被阻塞时显式 escalate 上报主会话而非自由发挥。
5. **权限五档语义**（plan/build/edit/yolo/guarded）与**子智能体定义文件**（`agents/<name>.md` frontmatter：tools/maxTurns/mcpServers/injectAgentsMd）。

---

## 7. 实施计划（任务卡制，先红后绿）

> 每卡交付定义：红灯测试先行（断言缺失行为且实证红）→ 最小实现转绿 → A/B 自证零新增失败 → live-verify 证据 → `git commit --only -- <paths>` 单任务单提交。

### P0 最小闭环（OpenCode / Gemini CLI 原生接入）

| 卡 | 内容 | 主要落点 | 红灯测试点 | live-verify 判据 |
|----|------|----------|------------|------------------|
| A1 | `NeuacpExecutor` 协议 + `NeuacpClient` 帧层（JSON-RPC over stdio、initialize 握手、版本协商 fail-closed、崩溃回调、UTF-8/编码纪律） | `neurova/agent/neuacp/acp_client.py` | 假 ACP agent（测试内子进程）握手成功/版本不兼容拒绝/EOF 崩溃上报 | — |
| A2 | `NeuacpStdioExecutor`：session/new→prompt→update 流→文本返回；content/reasoning → emitter | `neuacp/acp_executor.py` | 假 agent 回放 update 流，断言 emitter 收到等价块序列、返回文本正确 | — |
| A3 | `NeuacpMemberAdapter` 鸭子面（chat/config.name/超时/错误文本约定） | `neuacp/acp_member.py` | 适配器对 `_run_member` 调用形态的契约测试（stream=True、metadata.event_emitter、budget 内返回） | — |
| A4 | `_resolve_agent` 切口：名册 executor 成员返回适配器；`NEUROVA_EXTERNAL_AGENTS_ENABLED` off 时拒绝并诚实报错 | `swarm.py:1931` 前置分支 | 开关 off→spawn 拒绝；on→解析出适配器；内置成员路径零变化（A/B） | — |
| A5 | 名册 executor 字段 + admin 门 + 移除成员端点 | `teams_api.py` | executor 字段落盘回读；非 admin 加外部成员 403；移除成员后名册更新 | — |
| A6 | 端到端：建队→加 opencode 外部成员→spawn 派小任务→流式→候选→台账 completed | 全链 | 集成测试（真 opencode 子进程，标记 e2e） | 真后端 9527（.venv、清代理变量）+ 真 `opencode acp`：subagent_chunk 上屏、台账 completed、无 [ERROR] |

### P1 治理完备 + Claude Code / Codex

| 卡 | 内容 | 主要落点 | 红灯测试点 |
|----|------|----------|------------|
| B1 | permission 映射：`session/request_permission` → `requestRunApproval`；denied 回注会话；L 分级 | `acp_executor.py` | 假 agent 发 permission 请求→断言审批单创建、denied 后 agent 收到拒绝、L2 上房间卡 |
| B2 | 工具调用事件镜像进 span 轨迹 + H-4 账本 | `acp_executor.py` + `swarm.py _logRunEvent` | update(tool_call) 后账本/轨迹出现对应事件行 |
| B3 | `session/cancel` 对接 cancelRun；进程池上限/空闲回收/崩溃重启 | `process_pool.py` | 取消后 agent 进程 session 终止；超限排队；崩溃后有限重启计数 |
| B4 | catalog + test + status 三个 admin 端点（内置预设 + registry 缓存 + which 探测） | `neuacp/catalog.py` + `api/endpoints/neuacp_admin_api.py` | registry 失联降级内置清单；test 端点对假命令返回握手错误原文 |
| B5 | Claude Code / Codex 接入（npx 适配器；catalog 预设 + 文档 + 测试连接实测） | `catalog.py` | 各自真适配器握手测试（标记 e2e，本机无 Node 时 skip 并如实标注） |
| B6 | 前端：TeamPage 名册增强 + TeamNeuacpMemberForm + neuacp API 模块 + admin 门 | `TeamPage.vue`、`TeamNeuacpMemberForm.vue`、`api/modules/neuacp.ts`、`types/agent.ts` | vitest：表单校验/提交 payload/徽标渲染；vue-tsc 0 错 |
| B7 | i18n 25-35 键 ×11 locale | `src/i18n/locales/*.ts` | locale-consistency 全绿 |

### P2 扩编与远程

| 卡 | 内容 | 前置 |
|----|------|------|
| C1 | Qoder / CodeBuddy 接入（原生 `--acp`，catalog 预设 + 实测） | 本机安装对应 CLI |
| C2 | SSH 远程 transport（隧道跑 stdio；key_ref 凭据面接线；remote 字段） | 凭据面按 agent_id 作用域取 SSH key |
| C3 | **ZCode 插件接入**（`NeuacpPluginExecutor` 首个实现：stream-json NDJSON 解析/`type:"result"` 终行/`--resume` 续跑/隔离红线四件套） | ZCode 协议已核实（§4.10 专项）；Trae 已裁定暂不接入（2026-11-19），如未来启用走 `traecli acp serve` 复用 `NeuacpStdioExecutor` 链路（留档 §4.10） |
| C4 | 反向 MCP：本仓工具面经自建 MCP server 暴露给外部编码代理（复用 `mcp_ontology_server.py` 双鉴权先例） | 另批细化 |
| C5 | ACP 远程 HTTP transport（RFD 定稿后） | 上游 v1 纳入远程传输 |

---

## 8. 测试与验收

- **单元**（tests/unit/agent/neuacp/）：帧编解码、握手协商、update 流映射、permission 映射、适配器鸭子面契约、名册 executor 解析、开关行为、进程池上限/回收。假 ACP agent = 测试内可执行脚本子进程（真 stdio，非 mock 对象冒充——遵守教义第 3 条禁例）。
- **集成**：名册→spawn→适配器→假 agent→候选→台账全链；审批请求→审批单→裁决回注。
- **A/B 纪律**：共享文件（swarm.py/teams_api.py）改动前后全量比对失败集合（patch 法，不用 stash），预存失败不算回归、新增失败才算。
- **live-verify**：真后端（`.venv\Scripts\python.exe`、`create_app --factory`、清代理变量、[ERROR]=0、`/v1/providers` 注册行在）+ 真 OpenCode/Gemini CLI 跑通「建队→外部成员→派活→流式上屏→验收→台账 completed」；审批链验一个 L1 请求的人工批准回注。
- **前端门**：`npm run test`（vitest）与 `npx vue-tsc --noEmit` 全绿。

---

## 9. 风险与缓解

1. **各工具 ACP 实现质量参差**（字段取舍/权限粒度不一）：适配器对可选字段宽容、对必要字段严格；以官方 registry `agent.json` 的启动参数为准，不猜命令行。
2. **v2 协议漂移**：锁 v1；`initialize` 版本协商 fail-closed；v2 定稿后另批升级卡（C5 同批评估）。
3. **Windows 子进程环境坑**：编码（PYTHONIOENCODING 双头钉）、代理变量（白名单排除）、路径（ASCII cwd 优先，含中文路径走 utf-8 纪律）——均有仓内先例可抄。
4. **外部代理行为不可完全预测**（长任务、超预算、输出超长）：run budget 硬超时 + chunk 截断投影 + `contentBuffer` 失败交接既有机制兜底。
5. **npm 适配器可用性**（国内网络拉包慢/失败）：catalog 预设备注镜像/离线安装方式；测试连接如实报错。

---

## 10. 待拍板项

| # | 问题 | 选项与影响面 | 建议 |
|---|------|--------------|------|
| D1 | 首批接入顺序 | 甲：P0=OpenCode+Gemini CLI（零适配器、最快闭环）；乙：P0 直接上 Claude Code（生态最常用，但引入 npm 适配器 + Node 运行时依赖） | **甲**。影响面：P0 交付时间、Node 是否进部署依赖 |
| D2 | 外部成员判定模型（验收/评审通道） | 甲：不提供 llm_client，验收/评审 skipped（诚实降级，交付物无第二道机审）；乙：适配器提供判定小模型通道（多一层质量闸，增加成本与复杂度） | **甲先行**，乙挂 P2 按需。影响面：验收门有效性 vs 成本 |
| D3 | 外部成员可否入「固定团队」被主代理自主 dispatch | 甲：可以（名册即团队，统一待遇）；乙：仅限用户显式派活（主代理不能自发把任务交给外部代理） | **甲**（名册/审批/围栏已兜住）。影响面：spawn_subagent/dispatch_team 工具描述与治理面 |
| D4 | `permission_mode=auto` 是否开放 | 甲：开放（admin 专属，仅 L0）；乙：首版只留 `chain`（全部过审批链，打扰多但零风险） | **乙**首版，甲视使用反馈再放。影响面：表单字段、审批打扰频率 |
| D5 | 特殊工具接入口径（ZCode 无 ACP / Trae 企业版门槛） | **已裁定（2026-11-19）：Trae 暂不接入**——其 ACP 能力已核实并留档 §4.10，后续需要时随时启用；ZCode 走插件形态（已核实可接，§4.10 专项） | 影响：`NeuacpPluginExecutor` 首版随 ZCode 真落地；P2 不含 Trae |
| D6 | 外部代理用量/成本呈现 | 甲：台账标 `cost_source=external`、不计费不展示 token；乙：接各工具本地会话日志估算 token（各格式不一，成本高） | **甲**。影响面：成本台账口径 |

---

## 11. 与既有设施的单一事实源关系（防重复建设对照）

| 能力 | 复用 | 不新建 |
|------|------|--------|
| 成员执行入口 | `SwarmManager.spawn → _run_member` | 不建第二编排引擎（仓内 `AgentTeam/acp_runtime` 不承载外部代理） |
| 审批 | `requestRunApproval / decideSwarmApproval / 房间审批卡` | 不建外部代理专用审批表 |
| 台账/轨迹/围栏 | `agent_run_ledger / swarm_event_log / trace_recorder / context_firewall` | 不建外部代理独立账本 |
| 子进程治理 | `runner_bridge` 骨架（白名单环境/握手审计/有限重启） | 不复制第二套进程监督 |
| 注册/鉴权 | 复用 JWT/APIKey 体系；管理面走 admin 门 | 不引入新鉴权通道 |
| 前端进度/审批 | `SubAgentPanel / useSubAgentWindows / CollaborationRoomPage 审批卡` | 不加新事件类型、不加新状态值 |

---

## 12. 执行记录

- 2026-11-19：方案备稿入库（05196e759）；模块命名拍板为 neuacp（4e009aad9）；ZCode 专项核实回填（66c83f280）；Trae 专项核实回填（09ec9b239）。
- 2026-11-19：**用户裁定 D5——Trae 暂不接入**（本 commit）：目标清单收敛为 Claude Code、Codex、OpenCode、Gemini CLI、Qoder、CodeBuddy（ACP）+ ZCode（插件）；Trae 核实结论留档 §4.10，后续需要时随时启用。
- （实施时逐卡继续回填：commit 号、红→绿实测输出摘要、A/B 失败集合比对、live-verify 证据、偏离说明。）
