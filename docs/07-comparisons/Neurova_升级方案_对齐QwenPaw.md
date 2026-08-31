# Neurova 优化升级方案（对齐 QwenPaw 短板 + 放大自身优势）

> 目标：在不破坏 Neurova「认知深度 + 多模态」差异化优势的前提下，补齐与 QwenPaw 的工程级差距。
> 定位：本地优先、隐私友好、认知智能优先的「个人 AI 认知体」。

---

## 0. 差距复盘（来自对比报告）

| 维度 | Neurova 现状 | 与 QwenPaw 差距 | 升级优先级 |
|------|------------|----------------|-----------|
| 安全与治理 | `security/`（认证/审计/RBAC）+ 记忆加密 | 无内核沙箱、无工具护栏、无文件护栏、无 Skill 注入扫描 | **P0（最高）** |
| 多智能体 | `agent_matrix`/`collaboration` 弱 | 无标准通信协议、无运行时子代理 | P1 |
| 工程化/CI | ~419 测试、linter | 无 CodeQL、无 e2e、无 release-duty | P2 |
| 分发/部署 | Docker + `start.py` | 依赖复杂、前端需手动构建 | P2 |
| 记忆可解释 | 17 维稀疏/向量存储 | 不可读、不可编辑、不易 debug | P1（差异化补足） |
| 生态/社区 | 本地项目 | 无插件市场、无多语言文档 | P3 |

---

## 1. P0 — 安全与治理内核（最关键，对标 QwenPaw 四层安全）

QwenPaw 的安全是「能不能放心让 Agent 跑本地命令」的分水岭。Neurova 已有 `neurova/sandbox/`（仅占位），应落地为真实基座。

### 1.1 内核级 Sandbox（`neurova/sandbox/` 落地）
- **Linux**：基于 `bubblewrap`(bwrap) 或 `Landlock` 系统调用封装进程级文件系统/网络隔离。
- **macOS**：`Seatbelt`(sandbox-exec) 配置文件生成 + 执行。
- **Windows**：`AppContainer` 容器化执行。
- 统一抽象 `SandboxBackend` 基类，按 OS 自动选择后端；配置 `severity: none/network-off/read-only/full`。
- 集成点：`tool_executor.py` 执行 shell/代码前自动套用 Sandbox（仅当 governance 策略为 `sandbox`）。

### 1.2 Tool Guard（命令护栏，`neurova/security/tool_guard.py` 新建）
- 复用现有 `security/` 体系，新增 YAML 规则引擎 `ShellEvasionGuardian`：
  - 检测命令注入（`;`、`&&`、`|`、`$()`、反引号）、路径穿越（`../`、绝对敏感路径）、反弹 shell、危险命令（`rm -rf /`、`curl|sh`、`chmod 777`）。
  - 输出 `Allowed / Denied / Ask` 三级裁决，交 governance 统一处理。
- 单测：复用 `tests/unit/` 结构，覆盖 20+ 注入样例。

### 1.3 File Guard（文件护栏）
- 默认保护列表：`~/.ssh`、`~/.aws`、`~/.gnupg`、系统目录、env 文件。
- 在读/写文件工具（`file_read`/`file_write`）前做路径白名单/黑名单校验。

### 1.4 Skill Scanner（提示注入扫描）
- 对从外部加载的 Skill 文本、MCP 描述、网页抓取内容做注入特征扫描（指令劫持、`ignore previous`、角色越权）。
- 集成到 `skill_system`/`tool_layers` 加载入口。

### 1.5 Governance 策略中心（`neurova/security/governance.py` 新建）
- 策略：`allow` / `deny` / `ask` / `sandbox` 四级，按工具/渠道/用户维度配置。
- 复用已有 `rbac.py`、`audit_logger.py`，新增策略评估器。

**成功标准**：`tests/security/` 全绿；后端能拒绝一个构造的反弹 shell 命令；沙箱能隔离一次越权文件访问。

---

## 2. P1 — 多智能体协议 + 记忆可解释性

### 2.1 ACP 式通信协议（`neurova/ ȧgent/protocols/` 扩展）
- 已有 `agent/protocols/` 目录，落地轻量 **ACP（Agent Communication Protocol）**：
  - 消息信封：`{sender, receiver, type, payload, trace_id}`。
  - 运行时子代理派生：`Agent.spawn_subagent(role, task)` → 独立上下文、可并发。
  - Agent Team：`AgentTeam.orchestrate([...])` 编排多角色协作。
- 复用 `agent_matrix.py` 的角色定义，把「同一实例多角色」升级为「跨进程/跨 agent 标准协议」。

### 2.2 记忆可解释性（借鉴 ReMe，放大 Neurova 认知优势）
- 在 `cognitive_layers/memory_layer/` 新增 **Markdown 导出/导入**：
  - `MemoryExporter.export_markdown()` 把 17 维记忆转成可读 Markdown（含时间戳、置信度、关联）。
  - 支持用户在 Web 端直接编辑后写回（对应 QwenPaw ReMe 的「可读可编辑」）。
- **Scroll Context 式上下文管理**：对话轮次持久化 + 被驱逐轮次索引、按需召回（复用 `context_pool.py` 的 Compressor，新增 eviction index）。

**成功标准**：用户可在前端查看/编辑一条记忆；多子代理示例能并行完成「检索+生成」两段任务。

---

## 3. P2 — 工程化与交付

### 3.1 CI/CD 对齐
- 新增 `.github/workflows/`：`tests.yml`（pytest 全量）、`codeql.yml`（语义安全扫描）、`e2e.yml`（启动后端+前端冒烟）、`release.yml`（自动打 tag + 构建镜像）。
- 引入 `pre-commit`（black/isort/ruff）与覆盖率门禁（已有 `--cov`，设阈值 ≥75% 再放行）。
- 在 `neurova/api/app.py` 等关键入口加 smoke 测试进 e2e。

### 3.2 一键部署与分发
- `install.py`/`start.py` 已存在，扩展为：自动检测并构建前端（`NeuUI` 一键 `npm install && build`），生成单一 `docker-compose` 启动后端+前端。
- 提供 `pip install` 友好的打包（当前已是 Python 包结构），补充 `pyproject.toml` 元数据。
- 可选：Tauri/Rust 桌面壳（长期，对标 QwenPaw 桌面端），短期先做好 Web+PWA。

**成功标准**：`docker-compose up` 一条命令跑通前后端；CI 全绿且覆盖率达标。

---

## 4. P3 — 生态与文档

- **Plugin Market / Skill 市场**：在 `neurova/plugins/` 基础上，新增市场索引 + 签名校验（复用 `plugin_manifest.py` 语义化版本）。
- **多语言文档**：当前 `docs/` 已有 311 文件但偏中文，补充英文 README 与架构图（已有 CONTEXT.md、各类 md）。
- **社区钩子**：引入 `CONTRIBUTING.md`、Issue 模板、`good-first-issue` 标签；与 AgentScope 社区做差异化定位（强调本地隐私 + 认知深度）。

---

## 5. 必须保留 / 放大的优势（不要为对齐而削掉）

| 优势 | 现状 | 升级中不破坏，反而增强 |
|------|------|----------------------|
| 17 维记忆 + 睡眠整合 + 贝叶斯遗忘 | `memory_layer/` | 与「记忆可解释」结合，做成可视化时间线 |
| 情感闭环 + 元认知 | `emotion_context_layer/` | 保持，作为「人格一致性」卖点 |
| 多模态语音（6 TTS + ASR + voice_pipeline） | `tts/ asr/ voice_*` | QwenPaw 缺此项，做成核心差异化 |
| 14 渠道适配 | `channels/` | 保留并补 QwenPaw 已有的微信/iMessage/QQ |
| 富前端 82 页 | `NeuUI/` | 新增「记忆可视化」「安全策略」页面 |

---

## 6. 分阶段路线图与工作量

| 阶段 | 内容 | 预计 | 验收 |
|------|------|------|------|
| **P0** | 沙箱 + 工具护栏 + 文件护栏 + Skill 扫描 + 治理中心 | 2~3 周 | 安全测试全绿，能拦截真实注入 |
| **P1** | ACP 协议 + 子代理 + 记忆 Markdown 可解释 + Scroll Context | 2 周 | 多子代理 demo + 记忆可编辑 |
| **P2** | CI(CodeQL/e2e/release) + 一键部署 | 1~2 周 | compose 一键起；CI 全绿 |
| **P3** | 插件市场 + 英文文档 + 社区 | 持续 | 市场可装一个第三方 Skill |

**总评**：补齐 P0/P1 后，Neurova 可从「7.4」提升到「8.5+」，并在「本地安全 + 认知深度 + 多模态」三角形成 QwenPaw 不具备的独特定位。

---

## 7. 风险与对策
- **沙箱依赖系统工具**（bwrap/Seatbelt 可能缺失）→ 提供 `none` 模式降级，CI 中非 Linux 平台跳过真实沙箱测试。
- **记忆可解释写回一致性** → 导出/导入走版本化 diff，避免破坏内部向量索引（保留原始 embedding，仅编辑文本层）。
- **避免 God Object 复膨胀** → 所有新增模块遵循已有「深度模块 + agent_ref 注入」规范（`agent_core.py` 只做委托）。

> 建议：先落地 P0（安全），因为它既是最大短板，也是「本地执行代码」能否上线的前提；其余按路线图渐进推进，每阶段用 `pytest tests/` 回归验证。
