# 参照系 O（botiverse/oar，Open Agent Runtime）与本仓 neuacp 接入方式对比

> 调研日期：2026-11-20。对象：github.com/botiverse/oar @ main（1,219 commits / 663 stars / Apache-2.0，TypeScript pnpm monorepo，ESM-only、Node 24+）。
> 对照面：本仓刚落地的 ACP 外部编码代理接入（`neurova/agent/neuacp/`，P0+P1+P2，见
> `docs/04-plans/2026-11-19-acp-coding-agent-team-integration-plan.md`）。
> 定位说明：OAR 是**面向工作台开发者的接入层库**（provider-independent programming
> interface for coding-agent runtimes）；本仓 neuacp 是**平台运行时内的治理型接入模块**。
> 两者同题（多编码 agent 统一接入）异构（库 vs 服务端治理），对比按此口径校准。

---

## 1. OAR 机制画像

### 1.1 接入方式：自研 record-stream，不用 ACP

- README 未提及 ACP，不声称兼容。其 `docs/prior-arts/feature-comparison.md` 调研了
  Paseo/Lody/Synara/One Works/Orca/Herdr/Multica 七个宿主项目——**ACP 在这些项目里
  只是"共享协议层"**（Paseo "direct SDK/app-server 与共享 ACP"、Lody "Launch → 共享
  ACP Client"、Multica "ACP 默认选择允许选项"），未被当作独立对照行，Zed 全文未提及。
- 核心规范 `docs/spec/record-stream.md`：**单一全序记录流**，三种记录
  `frame`（runtime 原话，append-only，"oar never synthesizes a frame"）/ `request`
  （动作）/ `response`（仅观测 runtime 自己不会说出的结果，如进程退出码；
  "Backfilling a guessed response is forbidden"）。每条记录带
  `seq`（"total order per stream"）与 `agentPath`（子代理谱系，`[]`=root）。
- 归一分两层：`records()` 保留原始记录（`body.native` 保存 wire 原文，凭据
  `[redacted]`）；`events()` 是纯投影（`text_delta`/`tool_call_started`/`turn_ended`/
  `usage` 等），"Lossy by design, never lossy in the stream"。
- 控制与事实**同流**："Control never prunes facts"——abort/steer/withdraw 与
  tool_result 在同一 seq 空间，先后可判定；关联靠显式 id（`responseTo`），
  "Correlation never comes from timing or order"。

### 1.2 能力声明：不支持即提前拒绝

"What differs by runtime is declared on the Runtime, not guessed"（runtime-matrix）；
"An option a runtime cannot honor is refused before anything opens, never silently
dropped."

### 1.3 覆盖面与会话外 API

- 14 个 runtime：Antigravity、Claude Code、CodeBuddy、Codex、Cursor、DeepSeek
  Harness、Devin、Factory Droid、Grok Build、Kimi Code、OpenCode、Pi、Qoder、Qwen Code
  （"One API drives every runtime"）。
- 会话内：事件流、prompt/steer/queue/withdraw/abort（均返回 accepted/rejected 与
  类型化错误码）、`serveMcpTools`（宿主工具以 MCP 挂给 runtime）、子 agent 调度、
  `observe`（UI 折叠视图）、`testing`（无二进制测试运行时）。
- 会话外：安装检测/安装/更新、登录与账号状态、用量与配额、可用模型、skills/
  commands/MCP 清单、可渲染设置表单、一次性 Orientation。
- 部署：本地为主；跨进程恢复（`resume: session.id`，"even from another process"）；
  浏览器形态（Pi Durable）；生态 Raft 提供托管算力。安全边界："OAR never handles
  the tokens"。

## 2. 与本仓 neuacp 逐维对比

| 维度 | OAR | 本仓 neuacp | 优方 |
|------|-----|-------------|------|
| 接入协议 | 自研 record-stream（归一层） | ACP v1 标准（JSON-RPC over stdio）+ 插件行协议 | **本仓**（标准生态互认：Zed/JetBrains/VS Code 同协议；"被编辑器当 agent"唯一路） |
| runtime 覆盖 | 14 家全经归一层，换 runtime 不改代码 | P0 落 4 家（OpenCode/Qoder/CodeBuddy 原生 + ZCode 插件），Gemini/Claude/Codex 预设钉死待启用 | **OAR**（覆盖广；归一层薄是覆盖广的原因） |
| 事件保真/审计 | 单流全序 seq；frame 原文永久留痕；绝不合成、绝不推断结果；控制与事实同流 | 多通道：emitter→WS、H-4 事件账本（JSONL）、span 轨迹、SQLite 台账；chunk 不落账本 | **OAR**（审计/回放/测试可判定"abort 是否先于 tool_result"这类时序问题） |
| 能力声明 | runtime-matrix 显式声明；不支持选项打开前拒绝 | catalog 只有 installed/origin/requires_node 探测 | **OAR** |
| 会话外管理面 | 安装/登录/用量/模型/skills/MCP 清单/设置表单/Orientation | catalog/test/status 三端点 | **OAR** |
| 多 agent 编排 | child 会话记录与归因（session_linked/agentPath）；"任务分配、mailbox、worktree 归宿主；可观察 child ≠ 拥有控制权" | TaskUnit 任务书、验收门、评审相位、审批链 L0/L1/L2、房间人在环、依赖门控、结果候选 CAS 合入 | **本仓**（OAR 是记录/归因层，无验收/治理） |
| 治理与多租户 | 无（开发库；"OAR never handles the tokens"） | JWT 租户（部门根）全链隔离、审批链、数据围栏、台账 owner 栅栏、admin 管理面 | **本仓**（OAR 无此维度） |
| 恢复/续跑 | 跨进程 resume 同一会话 | `--resume` 透传 + member 会话落盘 | **OAR**（跨进程语义更完整） |
| 测试证据 | testing 包（replay/live 分层、无二进制）；对自身覆盖被 prior-arts 自我设限 | 假 CLI 桩（真 stdio 子进程）+ live-verify 真后端 | 平手（各有侧重） |
| 生态位/形态 | npm 库 + CLI + 浏览器 observe + Raft 托管；嵌入宿主应用 | 平台服务端内嵌模块 + HTTP 管理面 | 各自贴合自身场景（不计分） |

**评分卡（接入层专项十分制）**：OAR 74 / 本仓 neuacp 73。
OAR 强在接入层本职（覆盖 10、事件保真 10、能力声明 9、会话外面 9、恢复 8）；
本仓强在治理与编排（多 agent 9、租户治理 9、协议标准化 9），弱在事件保真（7）、
能力声明（5）、覆盖面（7）。

## 3. 优劣结论

1. **同题异构**：OAR 用"自研归一层 + 事件流契约"把 14 个 runtime 压成一套可编程
   接口，卖点是一次接入全覆盖与审计级事件保真；本仓 neuacp 用"ACP 标准协议 +
   平台治理"把外部代理编入受治理的 swarm 团队，卖点是标准生态互认与全链治理。
2. **纯接入层维度 OAR 更优**（覆盖、保真、能力声明、会话外面）；**平台维度本仓
   更优**（治理、多租户、多 agent 编排、验收）。总分接近（74 vs 73），差异主要
   来自定位：库 vs 平台模块。
3. **对 OAR 的定位警示同样适用于本仓**：其 prior-arts 自我设限"provider 数量与
   统一方法名本身不足以证明增量价值"——覆盖广必须伴随可复现的跨 runtime 行为
   证据，这正是本仓 A6/A7 用真/桩 CLI 做 live-verify 的意义。

## 4. 可借鉴清单（建议 P1 级，待拍板）

1. **能力显式声明 + 打开前拒绝**：catalog 增 per-runtime capability 声明（支持
   的 transport、是否流式、权限交互形态），派活前校验，不支持的组合在 spawn 前
   结构化拒绝——对齐"refused before anything opens"。
2. **控制与事实同流全序**：外部成员的 abort/steer 与 chunk/tool 事件进同一
   全序账本（H-4 已有 seq 雏形），使"取消是否先于某 tool_result"可判定。
3. **事件保真纪律**：tool 结果只在 runtime 明确报告时落账，不从退出码/输出
   推断补造（对齐 "never infers it from output, exit codes, or timing"）；
   native 原文留痕（凭据脱敏）供审计回放。

## 5. 不照搬清单

1. **SDK 库形态**：OAR 是给工作台开发者嵌入的 npm 库；本仓是服务平台，接入层
   内嵌于后端并有治理面——形态由场景决定，不迁移。
2. **自研协议替代 ACP**：OAR 弃 ACP 自研有其库生态理由；本仓已押 ACP 标准
   （互操作 + 潜在"被编辑器当 agent"的反向接入），不改道。
3. **ESM-only / Node 24+ 的运行时要求**：与本仓 Python 服务端无关。
4. **登录令牌经手面**：OAR "never handles the tokens" 的边界与本仓凭据面
   （env_keys 只录键名、值走凭据面）同向，已对齐，无需再学。
