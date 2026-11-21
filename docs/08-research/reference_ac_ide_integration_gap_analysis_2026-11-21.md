# 参照系 ac（T3 Code）IDE 接入支持范围专项对照——与本仓差距及补齐方案

> 2026-11-21 专项研究。基线：T3 克隆 `C:\Users\xccoo\.zcode\tmp\t3code-src` @ `6f94a063`
> （本轮勘察实测；`80871270` 仅版本探测去重，能力面无漂移）。本报告只追加事实与方案，
> 不改既有评测结论；第三方名仅作研究背景。配套：`reference_ac_vs_neurova_coding_agent_control_plane_evaluation_2026-11-21.md`。

## 1. T3 Code 的 IDE 接入支持范围（勘察结论，证据为 T3 克隆内 file:line）

### 1.1 定位：控制面，不是编辑器插件

T3 自我定位 "The open-source control plane for coding agents"（README.md:9）。全仓**无任何
VS Code/JetBrains 扩展产物**；形态是「环境服务器 + 桌面/Web/手机三端控制面」：编码 agent
以子进程跑在用户本机（或远程环境机），T3 负责编排、呈现与多端同显。桌面为 Electron 44
（apps/desktop/package.json）且把服务器作为子进程内嵌（DesktopBackendPool.ts:23,90）；
服务器可独立为 `t3` CLI（Node SEA，bin.ts:11），支持装成后台服务。

### 1.2 支持的 agent 全名单 × 接入机制（11 内置 driver，builtInDrivers.ts:33-45）

| Agent | 机制 | 证据 | 备注 |
|---|---|---|---|
| Codex | 私有 JSON-RPC（`codex app-server`，stdio） | codexLaunchArgs.ts:17；CodexAdapterV2.ts:88-90 | 能力最全：fork 子代理线程/会话内切模型与权限/turn 级 diff/线程快照 |
| Claude Code | 官方 SDK `query()` 进程内 | ClaudeProvider.ts:37；ClaudeAdapterV2.ts:52 | fork/rollback/steering/排队消息；权限原生执行 |
| Cursor | 官方 `@cursor/sdk` 于独立 worker 进程 | CursorAgentSdk.ts:1-31 | 用量限额按 SDK 错误码识别 |
| Grok / fx / Kiro / Antigravity | ACP flavor（共享 ACP adapter + 小特例包） | provider-grok/acpSupport.ts:23-40 等 | 特例仅做注入/配置差异 |
| OpenCode | HTTP/SSE（`opencode serve`） | providers.md:14-30 | 1.x/2.x 服务拓扑不同；"always" 授权用 once 防扩大 |
| Pi | 私有 RPC（`pi --mode rpc`，LF-JSON） | provider-pi/mcpInjection.ts:249-293 | 原生 resume/rollback/fork 靠会话文件 |
| Muse Code | 官方 `@muse-code/sdk`（MSP 协议） | provider-muse/sdk.ts:6-10 | 仅两档权限 |
| 任意 ACP agent | **通用 ACP registry driver**：从官方注册表 CDN 发现并安装（npx/uvx/压缩包，SHA-256 校验），或本地命令；ACP v2 优先兼容 v1 | AcpRegistrySupport.ts:53；providers-acp.md | 已知特例 7 个小 flavor（claude/copilot/droid/kimi/omp/opencode/devin） |

### 1.3 统一抽象与新增成本

- 统一接口 = `ProviderDriver`（driver.ts:117）+ `ProviderAdapterV2`（ProviderAdapter.ts:838-859，
  约 25 个方法：ensureThread/resumeThread/startTurn/steerTurn/interruptTurn/respondToRuntimeRequest/
  readThreadSnapshot/rollbackThread/forkThread…）+ 12 组布尔能力 schema（contracts/orchestrationV2.ts:405-420）。
  编排层与客户端**只读能力、绝不按 driver 名分支**；能力虚报视为 bug。
- 新增成本三档：ACP 规范内 agent=**零代码**（注册表条目）；特例=微型 flavor 包（grok/fx/kiro 合计约 7.4k 行）；
  原生协议=完整 adapter（pi/cursor/opencode/muse 四包约 39.7k 行；Claude 单文件 15.1k 行）。
- **回放式测试契约**：每家用真实进程录制 transcript fixture，经真实 orchestrator+adapter+投影回放断言；
  共享场景集（握手/多轮/排队/中断/steering/续跑/工具调用）+ 每家特有 fixture；文档明文列出多个
  provider 都踩过的协议陷阱清单（adding-a-provider.md:70-102）。

### 1.4 IDE 场景的权限/安全

四档权限模式（Supervised/Auto-accept edits/Auto/Full access），核心纪律=**只暴露 agent 原生支持的
模式，不代答审批模仿缺失模式**，缺失降级 Supervised；管理员托管策略可设模式天花板（重启恢复超天花板
即拒）；ACP 路径校验做符号链接感知的逐级 realpath、出错 fail-closed；Codex 每回合下发 sandboxPolicy；
附件存工作区外、经认领使用（"prompt 里出现路径≠授予访问"）。

### 1.5 多端协同

单写者服务器 + Effect RPC 订阅（按需发送，"看一个线程不付全部线程的账"）；事件日志约 1 天供断线
重放、更早走快照；web/桌面/手机共用 `client-runtime`（重连/探活策略单源）；四种路由（LAN/Tailscale/
SSH 隧道/云中继）按序试连；手机离线推送（完成/失败/待审批）；跨环境 peer-link 带 `T3-Mode-Limit`
只收窄不放大。终端面：PTY 服务器独占，渲染行为抽象为 libghostty-vt 单一 C ABI（web=WASM/原生=napi）。

## 2. 本仓（Neurova）现状对照

| 维度 | T3 Code | 本仓现状 | 差距判定 |
|---|---|---|---|
| 接入形态 | 控制面（无编辑器插件） | 同为控制面（服务端+NeurUI Web+鸿蒙/安卓移动端），无编辑器插件 | **同构**，无差距 |
| agent 广度 | 11 内置 driver + registry 零代码接入 + 7 特例 flavor | catalog 8 家族（opencode/qoder/codebuddy/zcode/gemini-cli/claude-code/codex/trae），全部需预设/代码注册 | **落后**：缺"注册表零代码接入"档 |
| 接入协议 | 每家原生协议 adapter + ACP 通用通道（v2 优先兼容 v1） | 自研 ACP v1 客户端（stdio+ssh 双栈）+ plugin 执行体（headless CLI） | **落后**：ACP 仅 v1；无 v2/registry |
| 统一抽象 | ProviderAdapterV2 约 25 方法 + 12 组能力 schema，编排层零 driver 分支 | 能力布尔维度 9 个 + 五结果切换决策 + chat 兼容适配器；方法级抽象较窄 | **落后**：适配器方法面窄（fork/rollback/快照读取等未成方法契约） |
| 接入测试 | 真实进程录制 transcript → 真编排器回放；共享场景集+协议陷阱清单 | 真握手 live-verify（三家已 PASS）+ 假 agent 桩 + 严格类型守卫；无录制回放契约 | **落后**：缺"真实 transcript 回放"这层回归网 |
| 权限模型 | 四档；只暴露原生模式、缺失降级；托管策略天花板；symlink 感知 fail-closed；sandbox 每回合下发 | L0/L1/L2 审批链+记忆式批准+组织天花板（只收紧不放宽）+租户隔离红线+数据围栏 | **互有胜负**：本仓多租户/审批链更强；T3 的"只暴露原生模式"与 symlink 感知路径校验可借鉴 |
| 多端协同 | 单写者+按需订阅+共享连接运行时+四路由+离线推送 | WS+SSE；移动 WS 账本 cursor 续传（新）；退避单源（新）；自托管 relay（配对场景） | **部分落后**：缺共享连接运行时单源与"按需订阅"语义；无云中继（自托管路线为既定决策） |
| 工作区/检查点 | 每线程 git worktree + 隐藏 ref 检查点 + turn 级 diff | scope 化隐藏 ref 检查点（批二）+依赖门/评审门；无每线程 worktree、无 SCM 托管集成 | **部分落后**：worktree 隔离与 turn 级 diff 呈现未做（是否做取决于产品形态） |
| 终端面 | 服务器独占 PTY + libghostty-vt | 无 PTY 终端面（产品形态为对话/编排，非终端 UI） | 不适用（形态差异，非缺陷） |

## 3. 差距清单（按补齐优先级）

- **G1 接入成本档缺失（最大差距）**：T3 新增一个规范内 ACP agent 零代码；本仓每家都要写预设与
  注册代码，且 ACP 仅 v1。
- **G2 无录制回放测试契约**：本仓有真握手 live-verify 与假 agent 桩，但缺"真实 transcript 经真编排器
  回放"的回归网——协议细节回归（分帧/事件序/权限请求形状）目前靠活体抽查。
- **G3 适配器方法面窄**：fork/rollback/线程快照/steering 等在 T3 是方法级契约+能力声明；本仓部分
  能力散在决策函数与工具面，未收敛成统一 adapter 接口。
- **G4 多端连接运行时**：三端重连/探活策略刚有退避单源，但订阅按需、共享连接运行时、离线推送
  仍未成体系。
- **G5 权限两小项**：路径校验的 symlink 感知 fail-closed、"只暴露原生支持模式"的成文纪律。

## 4. 补齐方案（P0/P1/P2 + 不做清单）

- **P0-1 ACP registry 零代码接入**：仿 registry 驱动思路建"目录条目即接入"通道——从 ACP 官方
  registry 拉取条目（含 SHA-256 校验的安装/缓存），catalog 预设降级为"种子数据"；本地命令直配
  保留。验收：新增一个规范内 ACP agent 不改 Python 代码即可入册并被派活。
- **P0-2 真实 transcript 回放契约**：为已 live 的三家（opencode/claude-code 适配器/codex 适配器）
  各录一份真实握手+会话 fixture，经真 neuacp 管线回放断言；沉淀共享场景集（握手/权限请求/取消/
  续跑）与"协议陷阱清单"进 adding-a-provider 同位文档。
- **P1-1 适配器方法面收敛**：把 fork/rollback/快照读取/steering 映射为本仓既有机制（候选制/检查点/
  事件账本/steer 队列）上的方法级契约，能力声明驱动可用性（不引入 Effect 栈）。
- **P1-2 多端连接运行时**：把重连/探活/订阅语义收敛为三端共享的单源契约（已有退避单源，续做
  订阅按需与探活），移动端离线提醒走既有自托管 relay。
- **P2 权限两小项**：外部成员路径校验加 symlink 感知逐级规约；"只暴露原生支持模式"写入外部
  成员能力声明纪律。
- **不做**：编辑器插件（T3 亦无）；云中继（自托管 relay 为既定路线）；PTY 终端面（产品形态不符）；
  为对齐而重写编排栈。

## 5. 一句话结论

T3 的 IDE 接入是"控制面 + 11 driver + registry 零代码接入"，与本仓同构但接入成本档更低、测试契约
更深。本仓补齐顺序：先做 **registry 零代码接入**与**真实 transcript 回放契约**（P0，直接消除最大
差距并补上回归网），再做适配器方法面收敛与多端连接运行时（P1），权限两小项 P2；编辑器插件、
云中继、PTY 终端面明确不做。
