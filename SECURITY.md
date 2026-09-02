# 安全策略（SECURITY）

## 支持版本

| 版本 | 状态 |
|---|---|
| 1.0.0-beta1（main） | ✅ 接收安全报告 |
| < 1.0.0 | ❌ 不再接收 |

## 报告漏洞

**请勿公开 issue 披露安全漏洞。**

1. 优先使用 GitHub 私有 Security Advisory（仓库页 → Security → Report a vulnerability）。
2. 备选：仓库维护者私信（含复现步骤、影响面、PoC）。
3. 承诺：72 小时内确认收悉，修复前不公开细节，修复后在 CHANGELOG 致谢（可要求匿名）。

## 安全架构要点（供评估影响面参考）

- **治理三阶段引擎**：未知工具默认 DENY → 深扫 → 危险正则 → 规则裁决（`neurova/security/`）。
- **沙箱**：Windows 三级（AppContainer Low integrity > 受限令牌 > 进程级，`neurova/sandbox/`）；Linux bwrap/Landlock；macOS Seatbelt。HIGH 严重度在无真隔离后端时升级为 DENY——拒绝优于静默放行。
- **出网防护**：`neurova/security/url_guard.py` 16 网段 SSRF 封禁（IPv4+IPv6 全谱）+ 逐 DNS 解析 IP 校验；豁免段（Clash fake-ip 198.18.0.0/15）写在文件头注释，换环境须复核。
- **审批记忆**：`approve(remember=exact/similar)` 持久化审批规则，危险命令豁免 SIMILAR 泛化（`neurova/security/approval_manager.py`）。
- **MCP**：调用恒走治理深扫+防火墙收敛；熔断（5 次开/300s 半开）+ OAuth PKCE/DCR（`neurova/tool_layers/`）。
- **技能注入扫描**：`neurova/security/skill_scanner.py` PromptInjectionAnalyzer（中英双语 11 签名）；技能安装 fail-closed；agent 运行时 create_skill 同闸（`tool_executor.py`）。
- **隔离**：三层 SQL WHERE 强制注入（`_PersistDbStore.execute`）+ ContextVar 作用域为唯一身份注入入口；JWT 含 neuser_id。
- **备份信任模型**：`neurova/backup/trust.py` Ed25519（HMAC-sha256-v1 scheme）签名 zip，FOREIGN/LEGACY/TRUSTED 三态；restore 对 FOREIGN 无条件拒绝。

## 已知接受的风险（诚实边界）

- Docker 容器内 Chromium `--no-sandbox`（`deploy/Dockerfile`）——宿主隔离依赖容器边界。
- Windows 本地 Whisper 模型下载走管理员 opt-in 同意门（`b9901b9`）。
- 依赖审计 pip-audit 为**非阻塞**门禁（CI `dependency-audit` job，allow-list 演进中）。
- SQLite 在线热备未实现：`BackupOrchestrator` 不打包 `data/` 运行态库（在线文件打包不一致）——冷备请先停服。

## 密钥管理

- API Key 走 `.env`（`.env.example` 有字段说明），**永不入库**；Mimosa git-gate 会拦假凭据形态的提交。
- 官网开放平台 Token 统一 `nvk_` 前缀（旧双段格式兼容）。
- 备份签名 key 落 `data/backup_signing.key`（0600，O_EXCL，拒 symlink）——请纳入宿主级备份策略。
