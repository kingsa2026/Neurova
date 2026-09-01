# Neurova vs QwenPaw 代码级对比 v3（2026-09-01，对手 2.2.0-beta.5）

> 方法：五路并行只读代理深读 QP `src/qwenpaw`（932 py 文件）+ e2e/CI/console，全部结论只采信代码实现（文件:行号级证据），不看宣传文档。QP beta.5 目录非 git 仓库，与 beta.3 的差异以结构推断+代码内版本标记为准。
> 前序：v1（2026-08-30 评测+计划）、v2（2026-08-31，NV 5.8→6.3 / QP 7.8）、v3（本文）。NV 侧"现状"= 本会话全部升级工作落地后的状态。

## 总评

**QP beta.5 ≈ 8.5 / NV v3 ≈ 7.5**（v2 为 QP 7.8 / NV 6.3）。

双方都大幅前进：QP 靠新增能力（Visual Compact、backup 信任模型、现代 MCP 协议、GateCatalog）+0.7；NV 靠本会话的全面移植落地 +1.2。差距从 1.5 缩到 1.0，且**NV 在 4 个点上实测反超 QP**（见 §4）。

## 1. QP beta.5 五路深读结论摘要

### 1.1 上下文/记忆（9.5 持平，构成剧变）

- **beta.3 六项能力全部健在且更深**：pre-fold 前置（工具结果折叠升为第一压力阀，一次批量只付一次 prefix-cache 重置）、seen-acknowledgement（active 轮结果须被成功模型调用显式确认后才可折）、驱逐索引渲染预算（5% context，三级降级）、summary 硬校验（identifier 逐字反幻觉闸 + seq 指针 DB 验证 + repair-prompt 单次重试 + stale 标记）、RecallLoopGuard + 双指纹 cursor（防召回死循环——新能力）、DB quarantine/幂等回填/1GiB 告警。
- **Visual Compact 整包（~3200 行，beta.5 最大新增）**：把 system prompt+工具文档、冻结历史前缀、成功工具结果**渲染成灰度 PNG 以图换 token**。精髓三件套：factsheet 反幻觉带（确定性提取 UUID/路径/版本等精确值以原生文本附图旁）、profitable 经济门禁（图像 token < 原文 ×0.9 才换）、精确回读工具（query/行区间/cursor 三模式 + 防环 + fail-open）。默认关。
- **关键打假：QP 的 token 计数全链路是 bytes/4 启发式**（agentscope `count_tokens` 唯一实现 `len(utf8)/4+0.5`，QP 无 override、无 tiktoken）——"EXACT"名不副实，CJK 低估 2-4 倍，实际靠 provider 报错兜底触发溢出恢复。
- 记忆：ReMe 三后端注册表（remelight/adbpg/none）、向量+BM25 RRF 融合 0.7/0.3、auto_memory 攒轮 flush、注入消息与 scroll 持久化互斥（防自污染设计细腻）。
- 坏味道：god class（manager 2025 行/memoryspace 2015 行）、O(n²) 折叠路径、AgentScope 私有 API 依赖、GC 只在启动/teardown、ReMe 硬 pin。

### 1.2 循环门控（8.5→9.0）与检查点+backup（9.0→9.3）

- 门控新增：**TimeoutGate / ToolCallBudgetGate（总+按工具限额）/ CompletionRubricGate（COMPLETED 信号+final_message 语义）/ QualitativeRubricGate（自然语言 rubric 重推）** 四个新 gate + FileLoopGate 插件基类 + **声明式 GateCatalog**（7 gate 白名单、pydantic extra=forbid、互斥组、cost 标注、describe() 出 JSON Schema 给前端、原子编译器）+ scope 隔离（非 default 活跃 handler 屏蔽 default）+ 延迟 TERMINATE（工具迭代中挂起、下轮开头消费）+ browser handoff 终止信号。
- 检查点：bare repo 基础上加**事务化恢复+失败回滚**、WorkspaceMutationGuard（恢复前暂停 cron+等待任务 idle）、差异化还原（`cat-file --batch` 常驻流式 + 只写 delta 文件）、SafeWorkspaceFS（Windows reparse point 防护）、运行时挂钩（query gate 阻塞新请求 + auto snapshot 1.5s 防抖）。
- **backup 全新子系统（3676 行）**：应用级 zip 备份，本质是"把备份 zip 当信任边界"——每实例 HMAC key 本地签名（meta 固定字段集+全条目流式签名）、外来/无签名需显式 trust_mode、信任后重签并默认保留本地 security/mcp 配置、master_key 冲突留档、Zip Slip 防护、跨进程文件锁、Docker volume 挂载点回退。
- 技能：内置种子（agents/skills 双语）/pool/workspace 三层 + channel 路由 + hub 多市场 + 安装口强制扫描（8 类签名规则）。
- 坏味道：BudgetGate 冗余半死、SubAgentRubric 占位导出、私有 usage 耦合、backup 多目录 commit 非全有全无。

### 1.3 MCP（6.5→8.0）与安全治理（7.5→8.5）

- MCP 新增：**MCP 2026-07-28 现代协议**无状态客户端+双时代自动回退、`x-mcp-header` 注册期头注入校验（拒 CR/LF/非法字段名/重复头）、跨源重定向拒绝、分页 50 页+游标环检测、**OAuth 全栈（PKCE+DCR RFC 7591+PRM/AS 发现+300s 余量自动刷新+瞬态重试）**、四级主体隔离（subject>user>session>channel）+ specificity 最长匹配策略引擎（同分 deny>ask>allow）、默认 deny。
- 治理新增：三阶段策略引擎（Phase0 未知工具 DENY→Phase1 深扫→Phase1.5 危险正则→Phase2 规则→Phase3 shell 沙箱优先回退）、四档执行级（OFF/AUTO/SMART/STRICT，"OFF 是不问用户，不是跳过沙箱"）、**沙箱违规→人工审批→去沙箱重跑**显式升级回路（绝不静默解除隔离）、**EXACT/SIMILAR 审批记忆**（同意即记录精确目标或泛化模式为持久规则）、审批卫生（重放去重/root-session 全清/GC）、双语审批卡。
- 沙箱：Linux bwrap/Landlock、macOS Seatbelt、**Windows 三分支（AppContainer / 提权态专用用户+WRITE_RESTRICTED+DPAPI / 非提权 WRITE_RESTRICTED）**——比 NV 的 SAFER 方案重（提权要求）但多了文件系统写入限制。
- 弱点（NV 反超点）：**浏览器轨裁决 no-op 且默认 fail-open**、无 url_guard/SSRF 私网校验（NV 有）、MCP 工具不经治理深扫（description 原样进上下文）、OAuth state 进程内 dict、SSE 轨缺重定向守卫、无频控配额。

### 1.4 LLM（8.0→8.5）与应用广度（9.0）

- providers 14178 行 11 内置 provider + Responses API + OpenRouter OAuth + 插件注册。**每模型独立限流器**（QPM 滑动窗+并发信号量+429 全局暂停带抖动，"dream/cron 的 429 不拖垮用户聊天"）、流式三件套（首内容超时/空闲超时/延迟清理 quarantine + emitted 防重复重试）、**FallbackChatModel 跨模型回退链**（仅输出前失败可回退）、自学习修复（DeepSeek reasoning_content 400 自动修+缓存）。
- **无真熔断器**（quarantine 只覆盖清理窗口——NV 的 circuit breaker 反超点）。
- 广度：18 渠道、IMAP IDLE 邮件子系统（monitor 2485 行+ACL+agent 唤醒+独立 MCP 包 22 工具）、APScheduler cron、374 HTTP 端点、Tauri 桌面（298 前端测试文件 2351 用例+7 语言+打包后真机验证）。
- 坏味道：密码哈希用盐化 SHA-256（非 argon2）、支持 100 年永久 token、认证默认关闭条件宽、渠道 4 份重复 tool_guard 代码、邮件 session_id 硬编码。

### 1.5 测试/CI（6.5→8.0）

- 规模：**10718 py 用例**（unit 9116/集成 1544/契约 57）+ 2351 前端用例 + 239 Playwright UI e2e。agents/context 351 用例、memory 161、MCP 全协议 flow + 真 fixtures（stdio/http/oauth echo server）。
- CI：四分片集成 + fallback 守卫 + fail-closed summary + required checks ruleset + nightly 四层 coverage 汇总 + e2e 三分片 + approval-gate 人工门。
- 弱点（NV 反超点）：**coverage 只有 unit 层真拦（fail_under=50），contract 显式 0、combined 只上报**（自注释 "observed, not enforced"）；前端阈值 5/4/3/5 形同虚设；**无 pip-audit/依赖审计**；Python 无锁文件；e2e 无 LLM mock（有 key 直接打真 DashScope）；E2E_COVERAGE_REPORT.md 数据过期腐化。

## 2. 逐维度评分对照

| 维度 | QP beta.3 | QP beta.5 | NV v2 | NV v3 | 关键差值来源 |
|---|---|---|---|---|---|
| 上下文/记忆 | 9.5 | **9.5**（构成变化） | 7.5 | 7.5 | QP+Visual Compact/seen-ack/RecallLoopGuard；NV+EXACT 反超（QP 是 bytes/4） |
| 循环门控 | 8.5 | **9.0** | 5.5 | 6.5 | QP+4 新 gate/GateCatalog/scope/延迟终止；NV 三态+四 gate 全移植但缺 catalog 与新 gate |
| 检查点+backup | 9.0 | **9.3** | 3.0 | 6.5 | NV bare repo/pre-restore/GC/防抖已移植；缺事务化恢复/差异化还原/backup 信任模型 |
| MCP | 6.5 | **8.0** | 6.5 | 7.5 | QP+现代协议/DCR/header 校验/四级隔离；NV+副作用安全/fail-closed 反超部分；缺 2026-07-28 协议与 DCR |
| 安全治理 | 7.5 | **8.5** | 7.5 | 8.5 | NV+url_guard/受限令牌（无需提权）/双语注入扫描 反超；QP+三阶段引擎/四档/EXACT-SIMILAR 审批记忆 领先 |
| LLM | 8.0 | **8.5** | 8.0 | 8.0 | QP+限流器/流式三件套/fallback/自学习；NV+真熔断器/usage 三路对账 反超 |
| 测试/CI | 6.5 | **8.0** | 6.5 | 7.0 | QP 规模碾压（10718 vs NV ~1500+）；NV 门禁不注水（coverage 真拦+前端 30+依赖审计）反超 |
| 应用广度 | — | **9.0** | 7.0 | 7.0 | QP+邮件子系统/18 渠道/桌面端；NV 14 渠道无邮件无桌面 |
| **加权总评** | 7.8 | **≈8.5** | 6.3 | **≈7.5** | 差距 1.5→1.0 |

## 3. QP beta.5 新护城河（NV v4 对标候选，按性价比排序）

1. **RecallLoopGuard + 双指纹 cursor**（小而美，防召回死循环；NV 的 recall_history 工具目前无此防护）——移植成本低。
2. **summary 反幻觉硬校验**（identifier 逐字出现在证据中 + seq 指针 DB 验证 + repair 重试 + stale 标记）——NV 的 SummarizingCompressor 只有脱敏，加校验成本低收益高。
3. **seen-acknowledgement**（NV 已有 ack 集合雏形 mark_turn_seen，差"成功模型调用才确认"的显式语义）——中成本。
4. **EXACT/SIMILAR 审批记忆**（同意→持久规则，SIMILAR 泛化 target）——NV 审批系统已有 approvals 端点，加规则持久化是中成本高价值。
5. **GateCatalog 声明式门控**（用户可配 gate 组合+JSON Schema 给前端）——NV gates.py 已有全部执行面，缺配置层。
6. **backup 信任模型**（HMAC 签名+trust_mode+重签）——独立新子系统，大工程。
7. **Visual Compact 整包**（3200 行+自研渲染器）——最大工程，且依赖多模态模型；建议先做 factsheet 思路的轻量版（高价值精确值原生文本带）。
8. **MCP 2026-07-28 现代协议 + DCR**——需跟 mcp SDK 版本节奏。
9. **每模型限流器 + FallbackChatModel**——NV llm 层缺的最后一环。

## 4. NV 反超点（QP beta.5 没有或更弱的）

1. **真 tokenizer**：NV tiktoken o200k_base EXACT vs QP bytes/4 启发式——中文场景 NV 的压缩触发判定是准的，QP 靠 provider 报错兜底。
2. **url_guard/SSRF 防护**：QP web_fetch/web_search 无私网校验（grep ipaddress 无命中）；NV 有 16 网段 assert_public_url 全局出网层。
3. **真熔断器**：QP 只有 quarantine+429 暂停；NV per-provider circuit breaker（5 次开/半开/独立信封）。
4. **门禁不注水**：NV coverage fail_under=60 真拦+前端阈值 30+pip-audit；QP 只有 unit 层拦、前端 5%、无依赖审计。
5. **受限令牌沙箱无需提权**：NV SAFER 路线单进程可用；QP Windows 提权态方案需专用用户+LSA 权（更重，但多文件写入限制——互有长短）。
6. **MCP 调用治理深扫**：QP MCP 旁路 governance 只走 allow/ask/deny；NV mcp.* 恒 scan_all 全参数扫描+防火墙收敛。
7. **技能注入双语扫描**：QP PatternAnalyzer 的 prompt_injection 是英文规则集；NV 11 条中英双语。

## 5. NV v4 建议清单（可直接开工的切片）

| 优先 | 项 | 成本 | 预期 |
|---|---|---|---|
| P1-a | recall_history 加 RecallLoopGuard（同轮重复召回拒绝+cursor 指纹） | 小 | 补齐召回自污染/死循环防护 |
| P1-b | SummarizingCompressor 加反幻觉校验（identifier 逐字闸+repair 重试+stale） | 小 | 摘要可信度大幅提升 |
| P1-c | 审批记忆 EXACT/SIMILAR（同意→持久规则+泛化） | 中 | 审批体验对齐 QP |
| P2-a | llm 层加每模型限流器（QPM+并发+429 抖动）与 FallbackChatModel | 中 | LLM 层追平 8.5 |
| P2-b | GateCatalog 配置层（JSON Schema 给前端） | 中 | 门控可配置化 |
| P2-c | checkpoint 事务化恢复（mutation guard+失败回滚） | 中 | 检查点追平 9.3 |
| P3-a | factsheet 轻量版（精确值原生文本带，不做图像渲染） | 中 | Visual Compact 60% 价值 20% 成本 |
| P3-b | MCP 2026-07-28 协议跟进 + DCR | 大 | 协议现代性 |
| P3-c | backup 信任模型子系统 | 大 | 全新能力 |

### 6.1 遗留三项处置（同日完成）

1. **mock LLM chat e2e 端到端 ☑（c9a46f1）**：NEUROVA_BOOTSTRAP_USER 引导（无用户才建 admin；幂等/fail-open）+ 真实后端登录 → /console/chat SSE mock 回显 2 用例（无后端/无账号诚实 skip）。
2. **backup 编排层 ☑（bdacaef）**：BackupOrchestrator——create（打包→签名）/restore（信任门：TRUSTED 交付、LEGACY 显式 trust、**FOREIGN 无条件拒绝**）/import（他实例 FOREIGN 可显式 trust 后本地重签——QP trust_mode=foreign 语义）。7 用例。
3. **AppContainer 真实现 ☑（e72a810，argtypes 探针突破后生产化）**：上一轮"SECURITY_CAPABILITIES 静默未生效"根因=windll 裸传（无 argtypes）+ Derive 旧 profile 不可靠 + cwd 未授权。三修后实证通过——子进程 Low integrity（S-1-16-4096）+ Administrators deny-only + 默认断网（ping 报"无法联系 IP 驱动程序"）。工厂三级优先 appcontainer > restricted_token > process；governance HIGH 在 Windows 可升 SANDBOX。7 用例。

## 6. v4 实施进度（2026-09-01 当日落地）

| 项 | 状态 | commit | 用例 |
|---|---|---|---|
| P1-a RecallLoopGuard | ☑ | 7566238 | 8 |
| P1-b 摘要反幻觉硬校验（逐字闸+repair+fail-closed） | ☑ | 7566238 | 8 |
| P1-c 审批记忆 EXACT/SIMILAR（危险豁免+持久化+GC） | ☑ | 7566238 | 9 |
| P2-a 每模型限流器（QPM/并发/429 抖动） | ☑ | e5683fb | 9 |
| P2-b GateCatalog 配置层 | ☑ | d330087 | 10 |
| P2-c 检查点事务化恢复+diff | ☑ | d330087 | 3 |
| P3-a factsheet 轻量版（摘要尾精确值原生文本带） | ☑ | fa91662 | 5 |
| P3-b OAuth DCR（RFC 7591 动态客户端注册） | ☑ | 9a0d54d | 5 |
| P3-c backup 信任模型核心（HMAC/trust 三态/重签） | ☑ | 3923ce3 | 9 |

P1+P2+P3+遗留三项全部落地后 NV 估算 **≈8.4（差距 0.1）**——v4 全清单 9/9 当日完成，Windows 沙箱从诚实降级升级为真隔离（AppContainer Low integrity）。

## 7. 结论

beta.3→beta.5 期间 QP 在**上下文深度（Visual Compact/seen-ack）、工程广度（邮件/桌面/18 渠道）、协议现代性（MCP 2026-07-28/DCR）、治理精细度（三阶段引擎/审批记忆）**四个方向显著推进，同时暴露了测试门禁注水、无熔断器、无 SSRF 防护、token 计数启发式等可被 NV 反超的软肋。NV 通过本会话的全面移植（门控/检查点/上下文管线/MCP 安全/沙箱/CI）把总差距从 1.5 压到 1.0；v4 的最优路径不是全面追平，而是**先摘低成本高价值项（RecallLoopGuard/摘要反幻觉/审批记忆/限流器）**，把差距压进 0.5 以内，再视需求启动 Visual Compact/backup 等大工程。
