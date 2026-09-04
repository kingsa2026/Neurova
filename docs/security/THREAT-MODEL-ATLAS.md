# Neurova 威胁模型（MITRE ATLAS 式，2026-09-04）

> OpenClaw 对比 #17 落地。参照 `openclaw/docs/security/THREAT-MODEL-ATLAS.md` 的结构：
> 威胁编号（T-XXX）+ 信任边界图 + 攻击链示例 + 现有控制映射 + 残余风险。
> 范围：Neurova 后端（FastAPI/SQLite）+ NeurUI 前端 + 桌面壳 + 14 渠道适配器 + MCP 层。
> 方法论：ATLAS 是针对 AI 系统的敌对威胁分类法；本文不做形式化验证（TLA+ 参考 OpenClaw，
> 收益/成本比暂不成立），以"攻击者视角走查 + 现有控制对照"为准。

---

## 0. 系统边界与信任假设

### 0.1 信任边界图

```
┌─────────────────────────────────────────────────────────────────────┐
│ 不可信区                                                            │
│   用户浏览器/桌面壳 ⇄ JWT ┐                                          │
│   14 渠道入站(webhook/长连接) ┤                                      │
│   MCP servers(远程协议/子进程) │                                     │
│   技能市场源(阿里/讯飞/GitHub) │                                     │
│   外部网页内容(web_fetch/browser_read/agent-reach) ┘                │
├──────────────── 边界 B1：API 鉴权面 ─────────────────────────────────┤
│ 半可信区：FastAPI 端点层（get_current_user / require_admin）         │
├──────────────── 边界 B2：身份→数据面 ────────────────────────────────┤
│ 半可信区：业务模块（三层隔离 ctx：agent_id × neuser_id × user_id）   │
├──────────────── 边界 B3：执行面（模型→工具） ─────────────────────────┤
│ 受控区：ToolExecutor（治理四级裁决 allow/deny/ask/sandbox）          │
│         技能声明式权限（P0-4 fail-closed）                           │
├──────────────── 边界 B4：持久化面 ───────────────────────────────────┤
│ 可信区：SQLite（RLock）/ agent_workspaces / data/                    │
└─────────────────────────────────────────────────────────────────────┘
```

### 0.2 信任假设

1. JWT 签发/校验可信；登录态不可伪造（B1）。
2. 同一服务器上的操作系统账户不可信程度低于服务进程（本地单机部署模型）。
3. LLM 输出**完全不可信**——它可能被提示注入操纵（跨 B3 的核心假设）。
4. 外部网页/技能包/MCP server 返回的内容**完全不可信**。
5. 多用户共享实例时，用户之间互不信任（区别于 OpenClaw 的 trusted-operator 单用户边界）。

---

## 1. 威胁条目

> 严重度：C(ritical)/H(igh)/M(edium)/L(ow)。状态：✅有控制 ⚠️部分 🚫无控制（登记）。

### 边界 B1 — API 鉴权面

| ID | 威胁 | 严重度 | 状态 | 控制/缺口 |
|----|------|--------|------|-----------|
| T-101 | 未鉴权端点被匿名调用（RCE/数据外读） | H | ⚠️ | 全站 `get_current_user` 为主；历史上有 tool_layers API 无鉴权（M1-M12 已修）；**残余**：逐端点审计未成文，`delete_agent` 无鉴权依赖已登记 |
| T-102 | 越权访问他人 agent/知识库（IDOR） | H | ✅ | 三层隔离 ctx 注入 + `owner_user_id` 属主契约（agent 导出包 T-112 同面）+ MoE SQL 三层 WHERE 强制 |
| T-103 | 弱口令/默认管理员凭据 | M | ✅ | 注册即管理员 + setup-status 向导；忘记密码双条件（admin 账号+魔密）+15min5次限流 |
| T-104 | JWT 泄露长期有效 | M | 🚫 | 无撤销/轮换机制（登记待办） |

### 边界 B2 — 身份→数据面（多租户隔离）

| ID | 威胁 | 严重度 | 状态 | 控制/缺口 |
|----|------|--------|------|-----------|
| T-201 | 跨用户读取记忆/知识库（检索层穿透） | H | ✅ | ContextVar 作用域唯一注入入口 + MoE `_PersistDbStore.execute` 正则强制注入三层 WHERE + 分片索引（public/user:uid/shared） |
| T-202 | 角色降级（admin 请求被当普通用户） | M | ✅ | role 透传链 chat.py→pipeline→adapter（隔离审计修复） |
| T-203 | agent 间记忆串台（每 agent 独立库被绕过） | H | ✅ | scope 注册表 + per-agent UnifiedVectorStore 实例索引；MemoryPage agent 全量快照隔离 |
| T-204 | 共享知识库投毒（shared 可见性滥用） | M | ⚠️ | 可见性模型 public/private/shared_with+审批；**残余**：写入内容无来源信任分级（P1 #9 origin 列登记待办） |

### 边界 B3 — 执行面（模型→工具，ATLAS 核心面）

| ID | 威胁 | 严重度 | 状态 | 控制/缺口 |
|----|------|--------|------|-----------|
| T-301 | 提示注入→任意命令执行（LLM 幻觉/被注入后调 computer_shell） | H | ✅ | 治理四级裁决（CRITICAL→DENY，HIGH→SANDBOX/DENY 诚实化）+ 命令白名单 + 声明位 `sandbox_required`（P2-15，`NEUROVA_TOOL_SANDBOX_ENFORCE=1` 强制路由） |
| T-302 | 技能供应链：市场技能含恶意代码 | C | ✅ | 安装门 skill_install_gate（DENY 策略扫描 fail-closed）+ 声明式权限四强制面 + hub 安装链 gate_check_and_rollback |
| T-303 | 技能声明绕过（manifest 声明与实际行为不符） | H | ⚠️ | 运行时按声明 fail-closed 裁决工具调用；**残余**：声明是"承诺"而非能力证明，未做行为级校验（动态分析登记待办） |
| T-304 | MCP server 恶意/被劫持 | H | ⚠️ | MCP 配置校验（未知键拒绝+stdio shell 拒绝）+ mcp.* 全参数扫描 + 治理故障 fail-closed；**残余**：MCP 工具命中沙箱策略直接 DENY（无进程级沙箱） |
| T-305 | SSRF（web_fetch/browser_read 打内网） | H | ✅ | url_guard/check_outbound_url + fake-ip 代理段排除（agent-reach）；**残余**：无 DNS pinning（rebinding 缓解不完整，登记待办） |
| T-306 | 外部内容注入→二次提示注入（结果直入上下文） | H | ⚠️ | browser_read 文本上限 60k + SSE SHA-256 去重；**残余**：无结果侧包裹脱敏（对标 OpenClaw external-content.ts，登记待办） |
| T-307 | 工具参数注入（换键名绕过守卫） | M | ✅ | scan_all 全参数序列化扫描（MCP 面）+ 参数守卫 schema 感知档 |
| T-308 | 子代理滥用（spawn 无限递归/资源耗尽） | M | ✅ | spawn 三明治（MAX_ACTIVE_CHILDREN=5/结构化拒绝）+ 快照冻结（身份层 LRU） |
| T-309 | 审批流社会工程（模型诱导用户批准恶意操作） | M | ⚠️ | 审批 metadata 存完整调用供批准后重放 + is_policy_denial 单源口径；**残余**：审批卡无渠道镜像路由，拒绝文案未按 OpenClaw 规范约束（P1 #11 登记） |

### 边界 B4 — 持久化面与可用性

| ID | 威胁 | 严重度 | 状态 | 控制/缺口 |
|----|------|--------|------|-----------|
| T-401 | SQLite 并发损坏（跨进程/线程写） | M | ✅ | threading.RLock 咽喉 + tmp+os.replace 原子写（session JSON）+ .corrupt-*.bak 隔离 |
| T-402 | 渠道入站消息重启丢失（可用性） | M | 🚫 | 入站内存态（OpenClaw 对比 P0 #5：channel_ingress_events 表登记待办） |
| T-403 | 备份/恢复引入恶意产物 | M | ✅ | BackupOrchestrator Ed25519 签名 + trust.py 校验 |
| T-404 | agent 应用包导入携带恶意载荷 | H | ✅ | 本日落地（P2-16）：manifest 结构 fail-closed 校验（kind/版本/agent 面缺一即 422）；MCP 只出引用面（id/name/transport），env/headers/command/args/url 凭据与宿主拓扑**永不离开宿主**；技能只登记清单不执行代码体；agent_id 白名单正则 + 冲突 409 + 失败全量回滚 |
| T-405 | 桌面版安装包供应链（NSIS 2GB/解压损坏类） | M | ✅ | 打包暂存排除 __pycache__（pyc 225MB 红线案）+ 签名入 tauri.conf |

---

## 2. 攻击链示例（走查验证）

### 链 A：市场技能→持久化 RCE（对应 T-302/303）

```
攻击者提交技能(marketplace submit) → 审批人误批 → 用户安装
  → [控制] 安装门 DENY 策略扫描：critical 特征→拒绝（fail-closed）
  → [控制] manifest.permissions 声明校验：未知能力键→拒绝
  → 运行时技能调工具 → [控制] check_tool_permission 无声明→拒绝（fail-closed）
残余：若技能代码本身有 scan 未覆盖的逃逸（如运行期动态 import），
行为级校验缺失（T-303 ⚠️）——缓解：安装是显式用户动作 + 审批留痕。
```

### 链 B：提示注入→沙箱逃逸失败（对应 T-301/306）

```
用户让 agent 读网页 → 网页含注入指令"执行 rm -rf"
  → LLM 生成 computer_shell 调用
  → [控制] 治理预检：CRITICAL 发现→DENY（连沙箱都不进）
  → HIGH 发现→SANDBOX；无真隔离后端→升级 DENY（P1-7 诚实化，拒绝优于裸跑）
  → [控制] 声明位 enforce 开启时：computer_shell/run_code 无条件走沙箱/DENY
残余：Docker 后端不可用的 Windows 主机上，执行面依赖 DENY 精度（规则漏报=放行）。
```

### 链 C：跨用户记忆渗透（对应 T-201/202）

```
用户 A 在 chat 端点注入伪造 role=admin 的 metadata
  → [控制] role 由 JWT 服务端解析，metadata 角色字段被忽略
  → 检索请求进入 MoE 索引
  → [控制] _PersistDbStore.execute 正则强制注入
    agent_id/neuser_id/user_id 三层 WHERE（用户 SQL 无法剥离）
  → 分片索引按 (agent, user) 键隔离，无跨片泄漏
```

### 链 D：恶意 agent 包导入（对应 T-404，本日新增面）

```
攻击者分发伪造 agent-package.json
  → 用户在 AgentListPage 导入
  → [控制] kind/manifest_version 校验：非 neurova.agent-package v1 → 422
  → [控制] agent_id 白名单正则（路径片段攻击 → 422）；已存在 → 409（不覆盖）
  → manifest.mcp 若含 env/headers/凭据 → 服务端只拷贝白名单引用键，
    凭据永不进入配置（导出侧已剥离，导入侧只登记引用）
  → 技能面只登记清单（不安装代码体，代码体须另行走市场安装门）
  → cron 导入只在调度器注册（action 白名单动作），失败全量回滚三清
残余：cron 的 parameters.message 内容进入聊天上下文（提示注入面同 T-306）。
```

---

## 3. 残余风险台账（按优先级）

| 优先级 | 项 | 来源对比 | 状态 |
|--------|----|----------|------|
| P0 | 渠道入站持久化队列（T-402） | OpenClaw #5 | 登记待办 |
| P1 | 记忆写入 origin 信任分级（T-204/毒化面） | OpenClaw #9 | 登记待办（并行会话已见 test_memory_origin_trust.py） |
| P1 | 审批持久化状态机+渠道镜像路由（T-309） | OpenClaw #11 | 登记待办 |
| P1 | DNS pinning 防 rebinding（T-305） | OpenClaw 网络三道闸 | 登记待办 |
| P2 | 外部内容包裹脱敏（T-306） | OpenClaw external-content | 登记待办 |
| P2 | JWT 撤销/轮换（T-104） | 通用 | 登记待办 |
| P2 | 技能行为级动态校验（T-303） | 本分析 | 登记待办 |

## 4. 维护约定

- 每次新增**执行面/入站面**（新工具类型、新渠道、新包格式）必须走查本文并补条目；
- 修复教义（AGENTS.md Repair Doctrine）的"放大视角"条款同样适用于威胁处置：
  同一根因的攻击面在所有命中点闭环，不允许只堵报告的那一条链；
- 状态列变更须同步残余风险台账，禁止"修了但台账还挂着"或反向漂移。
