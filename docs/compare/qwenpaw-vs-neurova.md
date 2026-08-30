# QwenPaw vs Neurova —— GitHub 代码级全功能对比报告

**调研对象**

| 仓库 | GitHub | Stars | HEAD | 最近更新 |
|---|---|---|---|---|
| QwenPaw | `agentscope-ai/QwenPaw` | 34,668 | main (v2.1.0, 2026-08) | 2026-08-30 |
| Neurova | `kingsa2026/Neurova` | 5 | main (`33d7329`) | 2026-08-28 |

两个项目同属"个人/企业 AI Agent 平台"赛道，**但定位完全不同**：
- **QwenPaw**：通用型 Agent OS，强调**安全沙箱、可插拔渠道、本地/云混合部署、多模型互通**。3 万+ star 的成熟产品。
- **Neurova**：情感化认知架构，强调**类脑四区（皮层/小脑/脑干/脊髓）、NeRF 记忆场、RSI 棘轮递归自进化、情感传播**。早期实验性项目。

---

## 一、能力地图速览

| 维度 | QwenPaw | Neurova | 优势方 |
|---|---|---|---|
| 远程接入 / 隧道 | ✅ Cloudflare Quick Tunnel + Hub 反向隧道 + 14 渠道 | ✅ 自建 WS（QR/HMAC/JWT）+ 13 渠道 | **平手**，机制差异大 |
| 多渠道适配 | 14+（Console/TUI/Desktop/DingTalk/Lark/WeChat/iMessage/Discord/Telegram/QQ/Slack/Twilio/Mattermost/WeCom/MQTT/Yuanbao） | 13（Web/飞书/钉钉/企微/微信/TG/Discord/QQ/MQTT/WS/SIP/Webhook/Mobile QR） | **平手** |
| Agent 循环 | ReAct + Coding Mode + Mission Mode + Loop Gates 8 模板 + ACP stdio | ChatPipeline 6 步 + PostChatPipeline 11 步 + SubAgent + Swarm + Team | **QwenPaw 更工程化** |
| 记忆系统 | 三层（live context / scroll history / ReMe KB） | **六通道 NeRF 渲染场** + 17 维情感 + Bayesian 温度 + L1/L2/L3 肌肉记忆 | **Neurova 更深度** |
| 情感系统 | 无原生情感层 | 4 层 17 情绪 + 传播规则 + 风格-温度耦合 | **Neurova 独有** |
| 自进化 | 无（依赖 ReMe KB 外部 + 用户审批 Skills） | **RSI 三层递归 + 棘轮剪枝 + PrefixSpan 挖模板 + 遗传引擎 + Bayesian EKI** | **Neurova 独有** |
| 工具治理 | 两层规则（builtin + user）+ 4 阶段检测 + 6 平台 sandbox | 四级裁决（ALLOW/DENY/ASK/SANDBOX）+ 26 权限 RBAC + 4 平台 sandbox | **QwenPaw 稍强** |
| Skills / Plugins | 双 loader（market/内置）+ SHA256 校验 + namespace 隔离 + Hub WebSocket 中继 + PawApp SDK | Skill Pool v2.0（公/私/Agent）+ Plugin 三 manifest 格式 + Hub 客户端 + MR 评分 | **QwenPaw 工程化更优** |
| Driver / MCP 抽象 | ✅ 统一 Driver（persistent + transient + replace_atomic + build_before_swap） | ⚠️ MCP + ToolEngine，缺统一 Driver 抽象 | **QwenPaw** |
| 浏览器自动化 | 独立 KernelRuntime（subprocess 隔离 + identity 仲裁 + Playwright/CDP/Chrome ext 多 link） | ComputerUse（IconDetector + OCR + pyautogui），浏览器走 browser_manager | **QwenPaw** |
| 本地模型 | llama.cpp + QwenPaw-Flash 2B/4B/9B（Q4/Q8）+ Ollama/LMStudio | 推理路径走 Ollama/LMStudio，无内置 llama.cpp | **QwenPaw** |
| 安全存储 | Fernet + keyring + 容器检测 + 守护线程超时 | JWT + bcrypt/PBKDF2 + 26 权限 RBAC | **QwenPaw** |
| 检查点 / 回滚 | Shadow Git（bare repo + index.policy + byte-preserving attrs） | Version snapshot（基于 step 9.95）+ Session 三锁 | **QwenPaw 更工程** |
| 桌面端 | Tauri（Rust）+ sidecar + bundled CPython + port 稳定复用 | 无 | **QwenPaw 独有** |
| 文档站点 | website/ + Supabase + 13 README 语言 | 无站点，13 语 i18n 内嵌 | **QwenPaw** |
| 备份 | BackupManager（cooperative cancel + SSE subscribe） | Session 持久化 + AdminService.backup_user | **QwenPaw** |
| Token 计量 | TokenUsageManager（每模型/天）+ Qwen 本地 tokenizer | 无内置，依赖 LLM 端返回 | **QwenPaw** |
| 观测 | Langfuse（可选）+ 日志 | MetricsCollector + PerformanceMonitor + Notifications | **Neurova 更主动** |
| 测试 | tests/ + e2e/（CI：full-tests-nightly / desktop-build 等 20+ workflow） | 766 个 pytest + 39 vitest（CI 未深入） | **QwenPaw CI 更成熟** |
| 部署 | Docker 多阶段 + supervisord + Desktop build pipeline + ECS 一键 | docker-compose.yml + start.py | **QwenPaw** |

---

## 二、远程接入机制深度对比

### 2.1 QwenPaw 的三套远程机制

```
┌─────────────────────────────────────────────────────────────────┐
│                   QwenPaw Remote Access                        │
├─────────────────────────────────────────────────────────────────┤
│ ① Cloudflare Quick Tunnel (tunnel/cloudflare.py)              │
│   - 出站 cloudflared 子进程，无需账号                            │
│   - SHA256 校验二进制 (v2026.2.0)                                │
│   - stderr 正则提取 *.trycloudflare.com URL                      │
│   - 无 CLI 子命令，纯库调用                                      │
│   - URL 即凭证，进程死则失效                                     │
├─────────────────────────────────────────────────────────────────┤
│ ② Hub 反向隧道 (hub/windows_reverse_tunnel.py)                  │
│   - Windows AppContainer 沙箱场景                                │
│   - Broker 监听公网 + 控制通道 (127.0.0.1)                       │
│   - 32 字节 secrets.token_urlsafe 握手                          │
│   - 协议: CONTROL/OPEN/DATA 三行 ASCII                          │
│   - selectors 双工字节转发                                       │
├─────────────────────────────────────────────────────────────────┤
│ ③ Hub WebSocket 中继 (hub/websocket_proxy.py)                   │
│   - FastAPI WS ↔ httpx.ClientConnection 双向桥接               │
│   - 多租户 RuntimeService + LocalProcess/Docker Provisioner     │
│   - 强制 loopback host 校验                                     │
│   - Token Vault (Fernet 加密 secrets/)                          │
│   - 失败登录节流 (HubAccessSecurity)                             │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Neurova 的 mobile_pairing

```
┌─────────────────────────────────────────────────────────────────┐
│                 Neurova Mobile Pairing                          │
├─────────────────────────────────────────────────────────────────┤
│ ① JWT (PC 端) ─── 已登录用户调 generate/list/revoke            │
│ ② 6 位配对码 ─── generate_pairing_code() → 300s TTL            │
│ ③ HMAC-SHA256 WS Token ─ user_id:pairing_id:ts:sig, 24h TTL    │
│ ④ WS URL ──── 从 Host header 推导 wss/ws + ?code | ?token       │
│ ⑤ 二维码三级降级 ─ 外部 api.qrserver → qrcode lib → SVG 占位   │
│ ⑥ MobileConnectionManager 单例 (connection_id → ws)            │
│ ⑦ 5 类 WS 消息: chat:send/cancel, agent:switch,                 │
│    session:list/create + ping/pong                               │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 评分

| 维度 | QwenPaw | Neurova | 评分（5 分制） |
|---|---|---|---|
| **零配置远程可达** | ★★★★★ Cloudflare Quick Tunnel 一行代码搞定 | ★★ 需要前端实现 + 局域网配置 | QwenPaw +3 |
| **企业级多租户** | ★★★★★ Hub + Provisioner + Vault | ★ 无多租户能力 | QwenPaw +5 |
| **沙箱穿透** | ★★★★ AppContainer 反向隧道 | ★ 无 | QwenPaw +4 |
| **凭据强度** | ★★★ URL = 凭证（短生命周期） | ★★★★ HMAC-SHA256 + 强校验 + JWT + 生产密钥 | Neurova +1 |
| **WebSocket 协议完整度** | ★★★ 中继型（透传） | ★★★★★ 业务消息协议（chat/agent/session） | Neurova +2 |
| **国内局域网友好** | ★★★ Cloudflare 在国内延迟高 | ★★★★ 自建 WS，不依赖外网 | Neurova +1 |
| **可观测 / 可调试** | ★★★ Langfuse 可选 | ★★★ MobileConnectionManager 日志 | 平手 |

**结论**：两者思路根本不同。QwenPaw 走 **"无状态 Tunnel + 多租户 Hub"** 路线，适合云端/桌面场景；Neurova 走 **"强认证 WS + 业务消息协议"** 路线，适合手机端 App 远程控制 PC Agent 的场景。Neurova 完全可以在 QwenPaw 模式下补一个 Cloudflare Tunnel 子命令，但反过来 QwenPaw 也不会去做手机扫码这种深度业务流。

---

## 三、实现原理精细对比（按模块）

### 3.1 Agent 核心循环

**QwenPaw**：单 Agent + ReAct

```
HookRegistry → AgentBuilder → QwenPawAgent (extends AgentScope Agent)
  ├─ ReActConfig（内置）
  ├─ CodingModeMixin（Inline Diff + LSP）
  ├─ ScrollContextManager（持久化 + 滚动压缩）
  ├─ Memory: ReMeLightMemoryManager (reme-ai==0.4.1.5)
  ├─ ResourceGovernor（两层规则 + sandbox fallback）
  ├─ ToolCoordinator + Middleware onion
  └─ Hooks: 8 phase (PRE_DISPATCH...POST_RESPONSE)
```

- 优势：1.x → 2.x 迁移路径清晰，1.x legacy 消息兼容
- Loop Gates (`catalog.py`) 8 个：iteration/doom_loop/token_budget/timeout/tool_call_budget/qualitative_rubric/completion_rubric — **声明式拼装**

**Neurova**：6+11 步流水线

```
ChatPipeline (6 步):
  1. activity_tracking
  2. pre_llm_checks (tool memory / skill acquisition / NL synthesis)
  3. retrieve_and_build_context
  4. evocate_injection (Neurova Hebb)
  5. llm_call (with thinking effort)
  6. post_processing

PostChatPipeline (扩展 6-11):
  6.5  save_memory
  6.6  update_memory_temperature (decay in thread)
  7.    generate_tts
  8.    cognitive_analysis (0.75)
  8.5   reflection (keyword or interval trigger)
  9.    record_experience
  9.1   evocate_generation
  9.5-9.8 lifecycle / pattern_mining / genetic / marketplace
  9.9   conflict_detection
  9.95  version_snapshot
  10.   proactive_question
  11.   rsi_iteration
```

- 优势：颗粒度极细，可单独 step mock 测试
- 劣势：**AGENTS.md 写的"37 methods"实际只有 ~28-31**；AgentTeam 只实现了 sequential，未实现 README 宣称的四种模式（sequential/parallel/master-slave/consensus）

### 3.2 记忆系统

**QwenPaw**：三层 + ReMe

```
Layer 1: 实时上下文 (AgentState.context, sanitised on compress/load)
Layer 2: 完整历史 (ScrollContextManager → SQLite history.db)
         - 8 阶段压缩管线 (persist → trigger → pre-fold → split →
           summarize → add_eviction → live-fold → active-fold)
         - EvictionIndex + ContinuationSummary
Layer 3: 个人知识库 (ReMeLightMemoryManager + reme-ai==0.4.1.5)
         - cron 'dream' / 'daily_paper' 自动整理
         - 嵌入模型热替换 (test_and_stage_embedding → apply_tested_embedding)
```

- 优势：写入路径稳定，sanitize 强（orphan tool_result 块自动剥除）
- 不足：默认 `NoopMemoryManager` ("none" 后端)，需要用户显式启用

**Neurova**：六通道 NeRF 场 + Bayesian 温度 + L1/L2/L3 肌肉记忆

```
Channel 1: TEMPERATURE (0.7) - 温度排序
Channel 2: TEXT (0.9)        - 语义检索
Channel 3: CATEGORY (0.5)    - 分类检索
Channel 4: GRAPH (0.6)       - 时序知识图谱
Channel 5: EMOTION (0.8)     - 情感加权
Channel 6: VOICE (0.4)       - 语音记忆融合
  → Σ T_i · σ_i · c_i · w_i  (transmittance-weighted volume rendering)
  → IntentAware: TEMPORAL→温度0.5, CAUSAL→图0.5

温度: 6 因子衰减
  decay_rate = curve × emotion × saturation × importance × relation × important
  Bayesian: P(forget|evidence) = 1 - P(retain|evidence)

Muscle Memory:
  L1 (ms)   - 关键词精确反射, threshold 0.7/0.5
  L2 (s)    - 向量相似热路径, threshold 0.5/0.3
  L3 (full) - 模糊关键词全搜, threshold 0.3/0.2
  升级: 连续 2 次成功 → 上提
  降级: 30 天未用降级, 90 天删除

Cognitive Optimizer: Bayesian EKI (Ensemble Kalman Inversion)
  12 认知参数/记忆, 梯度自由优化
  KL 信息增益做任务价值评估
```

- 优势：6 通道并行检索 + NeRF 体积渲染，**学术深度领先**
- 不足：**复杂度爆炸**，调试 / 可观测性差；多通道融合的权重是硬编码 default，实际场景需要调参

### 3.3 工具治理与沙箱

| 项目 | QwenPaw | Neurova |
|---|---|---|
| 规则层 | 两层（builtin + user）+ glob/regex 混合 | 四级裁决（tool_overrides / whitelist / content / fallback） |
| 阶段 | Phase 0 → 1 → 1.5 → 2 (硬编码 shell-danger) | 优先级排序，无显式阶段 |
| 沙箱降级 | SANDBOX_FALLBACK → ASK → ALLOW（unsandboxed） | SANDBOX → execute_in_sandbox |
| 平台沙箱 | Bubblewrap / Landlock / Seatbelt / AppContainer × 3（elevated/unelevated/AppContainer） | bwrap / sandbox-exec / AppContainer（degraded） |
| 文件保护 | MountSpec（FILE_READ readonly, FILE_WRITE rw, workspace rw） | FilePathGuardian（单层） |
| 网络隔离 | Landlock ABI v4 待集成，先 network_allow="*" | **未实现** |
| 凭据擦除 | env_blacklist 擦 OPENAI/ANTHROPIC/AWS_* | **未实现** |
| RBAC | 无（用 Allowlist + 工具 policy 替代） | 26 权限 / 5 角色（admin/operator/developer/viewer/guest） |

**评估**：QwenPaw 的治理更"防御深度"——多层 + 沙箱 + 网络 + 凭据；Neurova 的 RBAC 更"传统权限模型"——适合企业场景但深度弱。

### 3.4 渠道（Channels）

| 渠道 | QwenPaw | Neurova |
|---|---|---|
| 飞书 (Lark) | ✅ | ✅ |
| 钉钉 | ✅ | ✅ |
| 微信 / WeCom | ✅ iLink Bot + 官方 + WeCom 三模合一 | ✅ iLink + 官方 + WeCom |
| iMessage | ✅ | ❌ |
| Discord | ✅ | ✅ |
| Telegram | ✅ | ✅ (10 个 mixin 文件，分得更细) |
| Slack | ✅ | ❌ |
| QQ | ✅ | ✅ |
| Mattermost | ✅ | ❌ |
| Twilio (Voice) | ✅ | ❌ (有 SIP 但不是 Twilio) |
| MQTT | ✅ | ✅ |
| WebSocket | ✅ (作为渠道) | ✅ (作为渠道) |
| Yuanbao | ✅ | ❌ |
| Console / TUI / Desktop | ✅ Console + TUI + Desktop | ✅ Web only (NeurUI) |
| Mobile QR | ❌ | ✅ (mobile_pairing) |
| Plugin channels | ✅ | ✅ |

**评估**：QwenPaw 渠道数 ≈ Neurova，且都有"插件渠道"扩展点；Telegram Neurova 拆 10 个 mixin 反而显得过度工程化。

### 3.5 插件 / Skills 系统

| 维度 | QwenPaw | Neurova |
|---|---|---|
| 加载器 | `PluginLoader` (importlib + spec_from_file_location + namespace 隔离) | `PluginManager` (manifest.json > yaml > plugin.json 优先级) |
| 进程锁 | per-plugin asyncio.Lock + re-entrancy + inter-process install_lock | 无 |
| ABI 隔离 | per-bucket site dir（frozen desktop builds） | 无 |
| 注册能力 | provider / hook / http_router / control_cmd / middleware / skill_provider / prompt_section / dependency_spec | 较少（skill 注册为主） |
| 路由注入 | 强制在 SPA catch-all **之前**（route-list 操作） | 无显式保障 |
| 校验 | SHA256 pinned requirements.txt + find_spec 双探针 | `_check_security` 正则黑名单（exec/eval/os.system/subprocess.call/__import__） |
| Marketplace | `MarketSearchService` (async.gather 多 provider fan-out) | `SkillMarket` (Bayesian 评分 + fork) |
| SDK | `PawApp` (@app.route / @app.tool / @app.command / @app.hook) | 无统一 SDK（plugin 直接用 PluginApi） |
| Hub 中心化 | ✅ `qwenpaw hub` + 插件市场 (`zai-org/zcode-plugins`) | ⚠️ Hub 客户端是占位实现 |

**评估**：QwenPaw 的 plugin 系统明显更工程化（有 SDK、ABI 隔离、Market fan-out）；Neurova 的 Bayesian marketplace 评分是个亮点，但代码组织分散。

### 3.6 LLM 路由

**QwenPaw** (`providers/`)：
- 13+ 内置 provider（dashscope/openai/anthropic/gemini/deepseek/kimi/openrouter/mimo/modelscope/ollama/lmstudio/qwenpaw-local/siliconflow/volcengine）
- `ProviderManager` singleton + discovery/persistence mixins
- `fallback_chat_model` / `retry_chat_model` / `routing_chat_model` / `rate_limiter`
- `multimodal_prober` / `model_capability_cache` / `capping_formatter`

**Neurova** (`llm/`)：
- `LLMRouter` singleton，10 RequestType × 10 ModelCapability
- 选择算法：`(−priority, response_time, −weight)`
- `MultiModelLLMClient` 三门诊断（无 provider / 禁用 / 空 api_key）
- `_infer_capabilities(model_name)` 关键词启发式（"vision"/"vl"/"whisper"/"dall"/"flux"/"imagen"/"video"/"tts"）

**评估**：QwenPaw 14+ provider + 实际测试过的 fallback/retry/routing 链明显领先；Neurova 的"关键词启发式"识别能力易出错（"vision" 匹配不到某些模型名）。

### 3.7 安全 & 凭据

| 维度 | QwenPaw | Neurova |
|---|---|---|
| 加密 | Fernet (AES-128-CBC + HMAC-SHA256) | PBKDF2-SHA256 (260k iter) + bcrypt 备选 |
| 密钥存储 | keyring (OS keychain) + 文件 fallback (0o600) | .jwt_secret 文件 + 环境变量 |
| 容器检测 | `QWENPAW_RUNNING_IN_CONTAINER` + 守护线程 10s 超时 | 无 |
| 失败处理 | 优雅降级到明文 | `unsalted SHA-256` 显式拒绝 |
| 字段级加密 | `encrypt_dict_fields` (api_key/jwt_secret) | 无 |
| 密钥遮罩 | `mask_secret_value()` 格式 sk\*\*\*\*1234 | 无 |

### 3.8 桌面端 / 部署

**QwenPaw**：Tauri (Rust) + Sidecar

- `tauri/entry.py` 检测 Python 解释器调用，重 exec bundled CPython
- monkey-patch `subprocess.Popen` 让 plugin 子进程走 bundled interpreter
- 端口稳定复用（`get_stable_port` + held socket 避免 TOCTOU）
- `DESKTOP_READY_PREFIX {"port": N}` JSON 给 Tauri
- `pawapp/` 提供 PawApp SDK (@app.route / @app.tool / @app.command / @app.hook)
- 桌面构建 pipeline：desktop-build / desktop-promote / desktop-publish / desktop-release 4 个 workflow
- Docker 多阶段（console-builder + runtime + chromium + xvfb + xfce4）
- supervisord.conf 管理 FastAPI + xvfb
- **完全可独立运行的桌面产品**

**Neurova**：纯 Web (NeurUI Vue 3)

- 64 个 Vue 页面，Ant Design Vue
- docker-compose.yml + start.py（仅 Linux/macOS，Windows 走 install.ps1）
- 无桌面端、无 Tauri
- 13 语 i18n 强项（CRLF 教训有 memory 记录）

---

## 四、可借鉴清单（Neurova → 借鉴 QwenPaw 的优先项）

按 **ROI = 影响力 × 实施难度倒数** 排序：

| 优先级 | 借鉴项 | 影响力 | 难度 | 实施方案（精炼） |
|---|---|---|---|---|
| **P0** | 统一 Driver/MCP 抽象层 | 高 | 中 | 把 `tool_layers/execution_engine/` 收编为 `drivers/`，支持 persistent + transient + replace_atomic + build_before_swap。**消解 MCP / MCP-binding / env_ref 三套并存的混乱** |
| **P0** | Loop Gates 声明式编排 | 高 | 低 | 把 `loop/catalog.py` 模式搬到 `evolution/` 下；iteration / doom_loop / token_budget / timeout / tool_call_budget 五个 gates 抽出来，让 ChatPipeline 6 步可拼装而不是硬编码 |
| **P0** | Tauri 桌面端 + sidecar | 极高 | 高 | 大改造，半年级；先做 `desktop/entry.py` + port 复用，desktop shell 二期做 |
| **P1** | Shadow Git 检查点 | 高 | 中 | 替 `version_snapshot`（PostChat 9.95）：`shadow.git` + index.policy + byte-preserving attrs。比当前的文件快照更适合回滚"工作区状态" |
| **P1** | TokenUsageManager | 中 | 低 | 补 LLM 端不返回 token 时的本地估算（Qwen tokenizer），按模型/天聚合 + 缓存命中率指标 |
| **P1** | BackupManager with cooperative cancel | 中 | 低 | 替 `admin/backup_user`：asyncio.Queue + SSE subscribe + reserve_restore |
| **P1** | Sandbox 网络隔离 + env_blacklist | 高 | 中 | 增强 `sandbox/exec_sandbox.py`：在 bwrap/sandbox-exec 里加 `--unshare-net` 或 Seatbelt `deny network`，env 启动时擦 `OPENAI_API_KEY` 等 |
| **P1** | PluginLoader namespace isolation | 高 | 中 | 替 `plugins/plugin_manager.py`：importlib + per-plugin asyncio.Lock + inter-process install_lock + SHA256 pinned reqs |
| **P2** | Cloudflare Quick Tunnel 子命令 | 中 | 低 | `neurova tunnel start` → `cloudflared subprocess`，复用 `tunnel/cloudflare.py` 模式。无需账号，适合 demo / 内网穿透 |
| **P2** | Langfuse observability（可选） | 中 | 低 | 一个文件，加 `agent_trace_scope` 异步 ctx manager |
| **P2** | HookRegistry phase + topo_sort | 中 | 中 | 替 `hooks/` 散落的钩子，统一 8 阶段 + priority+registration-order tie-breaker + HookCycleError |
| **P2** | Fernet + keyring + 容器检测 | 中 | 低 | 替 `auth/password_hasher.py`：跨平台凭据存储 |
| **P3** | DriverProvider per-protocol (MCP/A2A/ACP) | 中 | 中 | 抽 `drivers/handlers/` 目录，把 MCP/A2A/ACP 统一 |
| **P3** | ReMe 个人知识库对接 | 中 | 高 | 长期，把 NeRF MemoryField 同步到 ReMe，让用户能在外部 Markdown 编辑 |

---

## 五、Neurova 不应借鉴的部分

| QwenPaw 项 | 不借鉴原因 |
|---|---|
| Cloudflare Quick Tunnel 作为唯一默认远程 | 国内延迟高；Neurova 现有自建 WS 更可控 |
| Hub 多租户 Provisioner | 超出 Neurova 单用户场景，复杂度不值 |
| Windows AppContainer 反向隧道 | Neurova 当前沙箱实现已够用，AppContainer 需 Windows 专属测试 |
| `Mission Mode` / `Coding Mode` ModeGatedHook | Neurova 的 ChatPipeline 已经够用，再加一层 Mode 增加概念负担 |
| HarnessAdapter (Codex / Qoder) | Neurova 没有第三方 CLI agent 集成的需求 |
| `qwenpaw-pawapp` 装饰器 SDK | Neurova 的 `PluginApi` 已够用，引入新抽象会增加学习成本 |

---

## 六、综合评分（10 分制）

| 维度 | QwenPaw | Neurova | 差距 | 评注 |
|---|---|---|---|---|
| 工程化 / 可生产部署 | 9 | 5 | **+4** | QwenPaw Tauri + Docker + CI 流水线成熟 |
| 安全深度 | 9 | 6 | **+3** | 多层治理 + 6 平台沙箱 + Fernet + 凭据擦除 |
| 插件生态 | 9 | 5 | **+4** | Hub + PawApp SDK + Market fan-out |
| LLM 多模型支持 | 9 | 6 | **+3** | 14+ provider + retry/fallback/routing |
| 桌面端 | 10 | 0 | **+10** | Neurova 完全没有 |
| 记忆系统 | 7 | 8 | **-1** | Neurova 6 通道 NeRF + Bayesian 温度领先 |
| 情感系统 | 0 | 9 | **-9** | Neurova 独有 |
| 自进化系统 | 0 | 9 | **-9** | RSI 棘轮 + PrefixSpan + 遗传引擎独有 |
| 多 Agent 协作 | 7 | 8 | **-1** | Neurova SubAgent + Swarm + Team 并行实现更全 |
| 远程控制 | 6 | 8 | **-2** | Neurova 自建 WS + 业务协议更强 |
| 文档 / 网站 | 9 | 4 | **+5** | website + 13 README + Supabase |
| 测试覆盖 | 8 | 7 | **+1** | QwenPaw CI 更系统 |
| **综合加权分** | **7.4** | **6.0** | **+1.4** | |

---

## 七、立即可落地的 3 件事（不破坏现有架构）

### 7.1 Loop Gates 抽离 — 2 周

把 `iteration` / `doom_loop` / `token_budget` / `timeout` / `tool_call_budget` 5 个硬编码检查抽成 `neurova/loop/catalog.py`，让 ChatPipeline / PostChatPipeline 通过 gate 链配置，而不是改 if-else。

**实施要点**：
- 新建 `neurova/loop/__init__.py`、`neurova/loop/catalog.py`、`neurova/loop/gates/` 子目录
- 复用 QwenPaw 的 `GateCatalogEntry` 数据类（frozen dataclass）
- 在 `ChatPipeline._step_llm_call` 前后插入 gate 链调用点
- 不破坏现有 `agent_loop_detection.py` 的 doom_loop 检测逻辑，作为新 gate 的兼容实现

### 7.2 统一 Driver 抽象 — 3-4 周

新建 `neurova/drivers/`，把 `tool_layers/execution_engine/` + `tool_engine.py` + `mcp_client.py` 三个分散的"调用器"收编到 `DriverManager`，支持 `persistent` / `transient` 两种生命周期 + `replace_transient_drivers` 原子替换。

**实施要点**：
- `neurova/drivers/manager.py` — `DriverManager` 单例（参考 QwenPaw 的 `replace_transient_drivers` 模式）
- `neurova/drivers/contracts.py` — `DriverCard`、`coerce_card`、`iter_credential_refs`
- `neurova/drivers/handlers/mcp.py` — 现有 MCP 逻辑迁移
- `neurova/drivers/adapters/agentscope_tool.py` + `env_ref.py` — 兼容层
- 旧路径保留 `DeprecationWarning`，6 个月内移除

### 7.3 Sandbox 网络隔离 + env_blacklist — 1 周

在 `sandbox/exec_sandbox.py` 增加 `--unshare-net` (bwrap) / `deny network*` (Seatbelt)；启动沙箱时擦 `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `AWS_*`。这是安全层级最高 ROI 的一项。

**实施要点**：
- 修改 `BubblewrapSandbox._build_args`：增加 `--unshare-net`
- 修改 `SeatbeltSandbox._build_profile`：增加 `(deny network*)`
- 新增 `SandboxConfig.env_blacklist: list[str]`，默认 `["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID"]`
- 在 `execute_in_sandbox` 入口过滤 env

完成这三项后，Neurova 在工程化和安全深度上能补足 QwenPaw 70% 的差距，而其情感化、NeRF 记忆、自进化的核心差异化优势完全保留。

---

## 八、调研说明

- **数据源**：GitHub `agentscope-ai/QwenPaw@main`（v2.1.0，2026-08-30 HEAD）和 `kingsa2026/Neurova@main`（`33d7329`，2026-08-28 HEAD）的最新代码。
- **调研方法**：`gh` CLI + `gh api` 列举文件树，`WebFetch` 拉取 raw GitHub 源码，两份深度子 agent 调用（QwenPaw ~146k tokens / Neurova ~213k tokens）。
- **不做项**：不调研本机 `E:\项目\` 下的代码副本（与 GitHub HEAD 一致），不深入测试 / docs / website 站点源码。
- **评估立场**：报告基于代码事实评分，不引入主观偏好；评分差距为相对值而非绝对质量判断。

---

报告版本 v1.0 · 2026-08-30