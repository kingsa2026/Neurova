# QwenPaw 借鉴点适配落地方案（2026-11-18）

> 来源：[十维中立框架对照评测](../08-research/reference_d_vs_neurova_standard_harness_framework_evaluation_2026-11-18.md)（QwenPaw 81.5 vs Neurova 80.5）与 [形态标尺版](../08-research/reference_d_vs_neurova_personal_assistant_harness_evaluation_2026-11-17.md) 的六路代码分析。
> 原则：**只吸收机制形制，不搬运实现与措辞**；每条先对照本仓现状（已逐文件核实），标明落点与验收判据；一律走先红后绿 + live-verify。
> 状态：待拍板。P0=建议下一批优先，P1=高价值中成本，P2=按需/产品化。

## 0. 已对齐、不再立项（防止重复建设）

以下能力经核实本仓已有对等实现，**不要**再按 QwenPaw 清单重复立项：

- 工具超时三处置（BACKGROUND/ABORT/KILL + 诚实收尸）：`agent/tool_coordinator.py:190-339` ≈ QwenPaw offload/kill 双截止。
- per-model 限流隔离（QPM 滑窗 + 并发信号量 + 429 全局暂停带抖动 + 快速失败）：`llm/model_rate_limiter.py` ≈ QwenPaw `providers/rate_limiter.py`。
- 模型错误分类单源 + 跨模型回退资格（仅 rate_limited/transient/model_not_found 可切）：`llm/model_error_policy.py` + `multi_model_client.py:825-827,1504` ≈ QwenPaw `model_error_policy.py`/`FallbackChatModel`。
- 技能安装期扫描硬拒闸：`skills/skill_install_gate.py` + `security/skill_scanner.py`（940 行，规则族分类）≈ QwenPaw `scan_skill_dir_or_raise`。
- MCP 熔断（连续失败→OPEN→半开→stale 降级）：`tool_layers/mcp_resilience.py:48-160`。
- 记忆写入准入（敏感拦截 + 该记/不记/绝不记清单单点包层）：`memory_admission.py`。
- 审计日志及清理：`security/audit_logger.py`（cleanup :712）。
- 会话检查点（git 裸仓库 + 事务回滚）：`checkpoints/service.py:181-223`。
- 多源技能市场（阿里云 + 讯飞，ClawHub 兼容协议）：`skills/market_sources.py`。
- 元技能（NL 合成工具 + AutoSkillBuilder + 评审闸）：`evolution/nl_synthesizer.py`、`skills/skill_encapsulation.py`。

---

## P0（建议下一批优先：高风险面 + 低成本高收益）

### A1. 渠道子进程隔离 + 握手期依赖审计

- **QwenPaw**：每渠道实例一个子进程（`app/channels/process_supervisor.py:77`），LaunchSpec 声明可信根（python_executable/code_root/descriptor_path/source_revision）+ 白名单 private_env；LSP Content-Length 帧 + JSON-RPC；握手携带协议版本/源码摘要/Python ABI/**依赖审计结果并 `audit.require_satisfied()` 强制通过**（`runner_host.py:44-83`）。
- **本仓现状**：渠道为主进程内 asyncio 适配器（`channels/base.py` ChannelAdapter + `channels/manager.py` 1,102 行 + `channel_router.py`），渠道异常会波及宿主；无进程隔离与供应链审计。
- **落地方案**：新增 `channels/runner/`（ChannelProcess 子进程壳 + JSON-RPC 帧编解码 + 握手协议）；`ChannelManager` 增加 launch/supervise 生命周期；先接 1 个渠道（建议 telegram，N2 已有 webhook 基础）验证双形态并行；依赖审计用 `pip-audit` 结果随握手上报，不通过即拒绝拉起。
- **验收**：子渠道进程被 kill 后宿主与其它渠道消息通路不受影响（真后端 live-verify）；握手缺依赖审计结果时渠道拒绝启动（红灯用例）。
- **风险**：进程间消息序列化需覆盖媒体/语音等大 payload——沿用"子进程只做平台 I/O，队列/策略/Agent 执行留主进程"的 QwenPaw 边界。

### A2. 技能扫描签名库对齐（双语 + 八类覆盖）

- **QwenPaw**：8 个 YAML 签名库共 42 条规则，八类齐全（prompt_injection 5 / command_injection 12 / data_exfiltration 7 / hardcoded_secrets 8 / obfuscation 4 / social_engineering 2 / supply_chain 1 / unauthorized_tool_use 3），**中英双语模式**（如同时匹配 "ignore previous instructions" 与"忽略以上指令"），CRITICAL/HIGH 安装期硬拒。
- **本仓现状**：`security/skill_scanner.py`（940 行）已有规则族框架（ScanRule.category、文档类降级为报告项、名称级规则族）+ install_gate 硬拒闸；规则条数与双语覆盖未达 42 条粒度。
- **落地方案**：不动扫描器引擎，只扩充规则资产（本仓规则即代码常量，可保持或改 YAML 资产——按教义第 6 条选一处单源）；按八类补齐，重点补 obfuscation / social_engineering / supply_chain / unauthorized_tool_use 四类与中文变体。
- **验收**：八类各至少 1 条规则的命中/放行双向用例；中英文变体各命中 1 例；既有误报样本（正常技能文档）不回归。

### A3. DoomLoop 相似度滑窗 + 两阶段升级

- **QwenPaw**：`gates/doom_loop.py:37` 滑窗记录 tool_name+args_hash，相似度超阈后按 stages 升级：先 `modify_prompt`（注入警告续跑）再 `stop`。
- **本仓现状**：`agent/gates.py:198-266` DoomLoopGate 默认逐字相等（阈值 1.0），同义换参空转抓不到；无"先警告后终止"梯度。
- **落地方案**：在 DoomLoopGate 内加参数相似度（归一化后序列相似度或 token 集合 Jaccard，阈值可配 `NEUROVA_DOOM_SIM_THRESHOLD`）；命中先注入警告续跑一次（复用 continuation 注入通道），二次命中才 TERMINATE。
- **验收**：同义换参循环用例（红灯：现网逐字相等判据抓不到）→ 升级后先警告后终止；正常重试（参数在变化）不误杀。

### A4. 审批泛化安全校验（审批成果复用）

- **QwenPaw**：审批通过后由 LLM 生成保守 glob 泛化规则实现免重复审批，但**危险命令拒绝泛化只记精确匹配**，全部过 `_is_safe_generalization`（`governance/generalize.py:1-17`）。
- **本仓现状**：审批链 L0/L1/L2（`agent/approval_chain.py`、`security/approval_manager.py`）逐次审批，无成果复用；重复同类操作反复打扰用户。
- **落地方案**：`security/` 新增审批泛化器：审批通过后生成保守模式（同工具+同参数形状），危险命令族（rm/sudo/删库/外发）只记精确匹配；泛化规则进 AccessPolicy user_rules 层并留审计。
- **验收**：同类安全操作第二次免审批；危险命令永不泛化（红灯用例）；泛化规则可查询可撤销。

---

## P1（高价值、中成本）

### B1. 声明式停止门编译

- **QwenPaw**：`loop/catalog.py:155` 7 种 gate 白名单（iteration/doom_loop/token_budget/timeout/tool_call_budget/qualitative_rubric/completion_rubric，后两者互斥）+ pydantic 严格参数模型（extra="forbid"）+ `loop/compiler.py:11` 把用户可编辑 JSON 编译成按 order 排序的 gate 链。
- **本仓现状**：四门硬编码于 `agent/gates.py`，GateRunner 按固定优先级跑（:394-423）；无用户级声明入口。
- **落地方案**：为既有四门加参数模型与 catalog 注册表（不新增 gate 种类，先把已有四门参数化）；`agent` 配置增加 `loopGates` JSON 声明，经编译器校验（互斥/必填/上限）后生成 GateRunner 装配；默认声明=现行为（零行为变化）。
- **验收**：默认配置下 A/B 零新增失败；非法声明（未知 gate/缺参数/互斥同配）编译期拒绝用例。

### B2. 人机共编记忆入口 + 定期蒸馏

- **QwenPaw**：vault 内 `MEMORY.md` 用户可直接编辑；`auto_memory` 每 N 轮 LLM 归纳入当日笔记，`auto_dream` cron（scan→integrate→finish）蒸馏为 digest 节点。
- **本仓现状**：自演化走认知层/结晶经验（用户不可见）；S16 记忆重纪律（候选转正/世代失效/人工审阅，默认 off）已落地治理骨架。
- **落地方案**：在 S16 之上叠加：agent workspace 增加 `MEMORY.md`（用户可编辑，启动时并入记忆上下文装配）；蒸馏任务接 `app` 层 cron（本仓已有任务调度面），产物走 S16 候选通道人工审阅后转正——不绕开准入。
- **验收**：用户编辑 MEMORY.md 后下一轮对话可召回；蒸馏产物未经审阅不生效（fail-closed 用例）。

### B3. 沙箱 Python recall（历史库只读查询）

- **QwenPaw**：模型可在沙箱 REPL 用 Python 查询只读 ATTACH 的历史 SQLite（`memoryspace.py:3-10`）——图灵完备的确定性回溯。
- **本仓现状**：`fold_index.py` 提供 covers/档号确定性寻址，但取回仍走固定工具；无模型自主查询面。
- **落地方案**：`sandbox/`（已有 appcontainer/exec_sandbox 基础）增加受控 Python 执行入口，仅暴露只读会话历史库连接（SQLite ATTACH readonly）+ 白名单模块；工具名沿用 recall 语义新增 `recall_query`（SQL 只读）。
- **验收**：模型可查回被折叠原文（端到端用例）；尝试写库/读其它库被拒（红灯）。

### B4. token 保证金（拒收自适应抬高估算）

- **QwenPaw**：provider 溢出拒收后永久抬高该模型 token 估算基线（`scroll/manager.py:390-463`），防止反复撞溢出。
- **本仓现状**：`context/token_estimator.py` 估算静态；溢出兜底重试一次（S6）但不记忆教训。
- **落地方案**：token_estimator 增加按模型的保守系数表（持久化到模型能力缓存 `llm/model_capability_cache.py`），溢出一次系数 ×1.25（封顶 2.0），成功若干次后缓慢回落。
- **验收**：模拟 provider 溢出拒收后，下次构建上下文预算变小；连续成功后系数回落。

### B5. File Guard（路径级防护）

- **QwenPaw**：敏感文件黑名单（config + `.qwenpaw.secret` 目录）+ Windows 大小写/UNC/环境变量规范化后匹配 + **解析 shell 重定向目标**（`file_guardian.py:76-127`）。
- **本仓现状**：`security/sensitive_info.py` 做内容级识别脱敏（唯一实装）；无路径级文件防护闸。
- **落地方案**：`security/` 新增 file_guard：敏感路径规则表（复用 sensitive_info 的规则表形态）+ 路径规范化（大小写/UNC/`~` 展开）+ 工具参数与 shell 重定向目标（`>`/`>>`/`tee`）双向检查，接入 tool_executor 治理预检四级裁决。
- **验收**：向敏感路径写入/重定向被拦（含 `> $ENV` 变量展开与 UNC 大小写绕过用例）；正常项目文件不受影响。

### B6. 工具执行级别五档

- **QwenPaw**：STRICT（全审批）/ SMART（按风险）/ JEV（决策模型）/ AUTO（白名单）/ OFF（`execution_level.py:14-46`），默认 AUTO。
- **本仓现状**：治理预检四级裁决 allow/deny/ask/sandbox（`tool_executor.py:2022-2100`），无全局档位。
- **落地方案**：在治理预检外加执行级别开关（per-agent 或全局配置），映射到既有四级裁决的行为组合；不新增裁决种类。
- **验收**：STRICT 下白名单工具也走审批；AUTO 下行为与现状一致（A/B 零新增）。

### B7. 工具完成缓存与事后查询面

- **QwenPaw**：完成 entry 进 60s/50 条缓存，`GET /output` 可事后取（`_coordinator.py:36-38`）。
- **本仓现状**：工具结果直接回填上下文，无事后独立查询面。
- **落地方案**：`agent/tool_coordinator.py` 增加完成缓存（条数/时长上限同 QwenPaw 量级即可）+ console 只读端点（按 run_id/tool_call_id 查），fail-closed 归属校验复用台账。
- **验收**：执行完成后 60s 内可查；越权查他人 run 被 4xx。

### B8. Shell 逃逸对抗规则补齐

- **QwenPaw**：POSIX 行续接归一化防 token 拆分绕过（`engine.py:237-247`）、引号感知的混淆/注释失配、heredoc 逃逸检测（`shell_evasion_guardian.py`）。
- **本仓现状**：`security/shell_normalization.py` + `command_syntax.py` + `command_segments.py` 已有归一化与分段基础。
- **落地方案**：在既有归一化后补三类检测：续接符拼接还原、引号内外差异比对、heredoc 体提取匹配；命中走 tool_guard 现有裁决。
- **验收**：三类绕过样本（续接拆分危险命令、引号夹带、heredoc 夹带）被拦；正常脚本不误伤。

### B9. 渠道入站优先级与群聊拆批

- **QwenPaw**：统一队列以 `(channel_id, session_id, priority_level)` 为 key 的每会话优先级队列；群聊共享会话按 ACL identity 拆批（`unified_queue_manager.py:14,516`）。
- **本仓现状**：`channels/channel_ingress_queue.py` 为 SQLite 租约队列（enqueue/lease/max_attempts），无优先级字段、无拆批。
- **落地方案**：入站队列表加 priority 列（approval/人工消息高优先），出队排序消费；群聊按 sender identity 拆批防串扰。
- **验收**：高优先消息插队消费用例；同群多发送者不互相阻塞。

### B10. 市场源扩展与 priority 可插拔

- **QwenPaw**：默认 clawhub.ai + 7 源 URL 导入 + provider priority（`hub.py:2185`），hub 插件可注册新 provider。
- **本仓现状**：`skills/market_sources.py` 已接阿里云 + 讯飞两源（命名空间前缀防碰撞、同步白名单），注册机制在 `market_registry.py`。
- **落地方案**：补 GitHub / lobehub / skills.sh 等源适配（复用既有 catalog entry 映射形制）；源配置加 priority 字段决定搜索排序与默认源。
- **验收**：新增源可浏览/安装/联邦注册；priority 影响搜索排序用例。

### B11. 技能 manifest 渠道过滤 + 环境依赖 + 渐进披露

- **QwenPaw**：`resolve_effective_skills`（`registry.py:1268`）按 manifest 的 enabled、**channel 过滤、require_envs 依赖检查**解析生效技能；`select_preload_skills`（:1328）仅装载 preload 技能，其余按需斜杠命令取用。
- **本仓现状**：`skills/manifest_entry.py`（纯数据条目）+ `skill_injection.py` 注入；无渠道过滤与环境依赖门槛，披露粒度待查。
- **落地方案**：manifest entry 增加可选 `channels` / `requireEnvs` / `preload` 字段（缺省=现行为）；`agent_skill_manager` 解析时过滤；缺失 env 的技能注入时降级为"存在但不可用"诚实提示。
- **验收**：带渠道限定的技能在其它渠道不注入；缺 env 技能给出诚实不可用提示而非静默缺失。

---

## P2（按需 / 产品化 / 跨平台时再做)

- **C1. macOS Seatbelt / Linux Landlock+Bubblewrap 沙箱 + 内核状态自证**（`runtime_boundary.py:22-79`：uid_map 单映射、CapEff=0、mountinfo 根指向）——本仓仅 Windows AppContainer（`sandbox/appcontainer.py`）。跨平台发行前落地；**不学**其"沙箱默认关"。
- **C2. Fallback 细节**：输出可见前完成切换 + 请求结束强制复位防 fallback 泄漏进压缩与能力学习（`fallback_chat_model.py:174-186`）——本仓 `multi_model_client` 已有回退链，切换时序细节对齐。
- **C3. 溢出恢复"不重放有效输出"**：已有有效输出则不重放（`overflow_recovery.py:27-71`）——本仓 S6 溢出兜底重试可对齐。
- **C4. recall 防自污染细节**：recall 工具自身轮次排除出检索索引（`history.py:60-67`）——本仓 recall_loop_guard 之上补该条。
- **C5. secret_store 增强**：OS keychain 优先 + `ENC:` 前缀灰度迁移 + 按安装路径哈希派生 account（`secret_store.py:48-90`）——本仓 `security/secret_store.py`/`local_key_protection.py` 已有基础。
- **C6. 覆盖率棘轮语义**（fail_under 只升不降，演进史进注释）+ **前端 bundle 体积预算门**——本仓 CI 覆盖率门禁 60% 已高于对方 50%，补"只升不降"与 bundle 预算。
- **C7. Docker 构建期依赖门禁**：Node 版本不符即 fail、关键依赖钉扎（`deploy/Dockerfile:31-40`）——本仓根目录 Dockerfile/docker-compose.yml 可加。
- **C8. 附件防护**：附件白名单根 + 拒绝 symlink 逃逸（QwenPaw iMessage 渠道）——本仓 `channels/mediaIngress.py` 落点。
- **C9. 本地模型运行时 + Tauri 桌面 + PyInstaller 打包**——产品化形态，视发行计划。
- **C10. JEV 决策模型预执行风险评估**（impact 四选一 + destructive/secret_exposure/privilege_change 结构化判定）——**必须本地模型实现**，QwenPaw 云端外发完整脚本是反模式，不照搬。
- **C11. 记忆图谱 3D 可视化**（QwenPaw `MemoryGraphView.tsx` 1,389 行）——前端可选。
- **C12. e2e page object 分级 + mock/真后端双档**——本仓 e2e 已有 boot 冒烟与真后端 live-verify，按需扩展。

---

## 不学清单（QwenPaw 的反模式）

1. **guardian fail-open**（守卫异常仅 warning 照常执行，`engine.py:271-278`）——违反本仓"禁表面抹除"教义。
2. **决策模型把完整工具脚本发云端模型**（`decision_model.py:4-6`）——数据外发通道；要学就本地化（C10）。
3. **技能 = Markdown + 模型念 CLI 命令、无类型化 schema 兜底**——本仓类型化工具面更稳。
4. **-en/-zh 全量双份技能目录**（连脚本都复制）——漂移风险；本仓 i18n 走 locale 对齐守卫。
5. **沙箱默认关闭（`config.py:3244`）+ Docker 以 root 运行 + 认证默认关仅打印警告**——安全能力必须默认开。
6. **约 50 处 except-pass 静默降级**——与教义第 2 条冲突。
7. **巨型文件**（model_factory.py 2,797 行等）——本仓尺寸棘轮纪律继续执行。

---

## 建议执行批次

| 批次 | 条目 | 理由 |
|---|---|---|
| 第一批（P0） | A1、A2、A3、A4 | 渠道隔离是架构性欠账；扫描规则/AI 审批泛化/DoomLoop 升级成本低收益高 |
| 第二批（P1 上） | B3、B4、B8、B7 | 全在上下文/工具执行咽喉，改动面集中 |
| 第三批（P1 下） | B1、B2、B5、B6、B9、B10、B11 | 涉及配置面与渠道/技能治理，依赖第一批经验 |
| 按需 | P2 全部 | 触发条件：跨平台发行（C1）、本地模型产品化（C9/C10）等 |

> 每条执行时仍须：先红后绿（红灯用例先证明现状缺口）→ 最小实现 → live-verify 真链路 → A/B 零新增失败；涉及渠道/安全的条目加守卫测试防回归。

---

## 执行记录（2026-11-18，严格按教义逐条推进）

### P0（4 条）

| 条目 | 结果 | 提交 |
|---|---|---|
| A1 渠道子进程隔离+握手期依赖审计 | ✅ 落地：`channels/runner_spec.py`（LaunchSpec 可信根）+`runner_protocol.py`（帧协议+依赖审计 fail-closed）+`runner_main.py`（子进程入口）+`runner_bridge.py`（RunnerHost/RunnerChannelAdapter/Supervisor 有限重启）；红（移文件收集错）→绿 7 用例，channels 834 零回归，live-verify 真子进程隔离/崩溃重启全过 | 5e57bde99 |
| A2 技能扫描签名库 | ✅ 落地：三分析器（密钥内容/社会工程/越权工具）+四规则；红 13→绿，security 1191 零回归，live-verify 恶意包 DENY/正常包 PASS | 68cb667f7 |
| A3 DoomLoop 升级 | ⚠️ **读码改判：已对齐**——`gates.py:157` 相似度判定与两阶段升级早已实装；默认阈值 1.0 系 2026-10-16 拍板（翻页误杀代价），收紧走 `doom_loop_similarity_threshold` 配置，不擅改 | — |
| A4 审批泛化 | ⚠️ **读码改判：已对齐**——`approval_manager.py` P1-c 已落结构泛化+危险命令豁免 SIMILAR，写读双侧接线 | — |

### P1（11 条）

| 条目 | 结果 | 提交 |
|---|---|---|
| B1 声明式停止门编译 | ✅ 落地：`agent/loop_gates_compiler.py`（门目录单源+参数白名单+fail-closed 校验）+`_buildGateRunner` 接线（声明即全按声明、未声明零变化）；7 用例+门控回归 58 绿，live-verify 编译门行为实测 | — |
| B2 人机共编 MEMORY.md | ✅ 落地（蒸馏回写另批）：`memory/memory_md.py` 存取+console GET/PUT（requireAgentOwner 门）+build_context 注入；8 用例绿，memory/context 2344 零回归（2 个 storage 失败 A/B 定责为预存）。**2026-11-18 退役**（用户拍板：宪法/人格/memories 温度生命周期已覆盖其价值，且无 UI/无蒸馏/无写入口成潜伏件；蒸馏回写改立独立方案进温度体系） | c132f7d64 |
| B3 沙箱 Python recall | ✅ 落地（收敛为受限表达式引擎）：`tools/recall_expression.py`（白名单 AST+只读 items 注入+截断）+`recall_query` 工具（schema/dispatch/handler，与 recall_history 同取数源）；12 用例+tools 不变量 90 绿，live-verify 逃逸拦截实测 | — |
| B4 token 保证金 | ✅ 落地：`token_estimator.py` 保证金三函数（×1.25 步进封顶 ×2.0，存模型能力缓存）+estimate_tokens 可选 model_id+multi_model_client context_overflow 接线；930 回归绿，live-verify 真溢出分类链实测 | — |
| B5 File Guard | ✅ 落地：凭据后缀族对齐（.pem/.key/.ppk/.p12/.pfx/.kdbx/.git-credentials/.htpasswd）+%VAR%/$VAR 展开判定；5 用例+guard 回归 89 绿，live-verify 六形态实测 | — |
| B6 五档执行级别 | ⚠️ **改判：不立项**——本仓已有 permission_mode 六模式（plan/build/edit/yolo/guarded/auto）+approval_level+治理四裁决，再引 QwenPaw 五档即平行体系（教义第 6 条） | — |
| B7 完成缓存查询面 | ✅ 落地：`ToolCoordinator.getCompletedEntry`（归属 fail-closed 只读投影）+console `GET /chat/tools/{task_id}/result`；7 用例绿，api 3231 零新增失败（18 个失败 A/B 定责全为预存） | — |
| B8 Shell 逃逸补齐 | ✅ 落地：heredoc 签名（行续接归一化已接线，本条补 `sh <<EOF` 形态）；4 用例+guard 回归 69 绿，live-verify 引擎真流程实测 | — |
| B9 渠道优先级队列 | ✅ 落地：ingress v2 迁移加 priority 列+claim 按 priority DESC/id ASC+metadata.priority 默认来源；4 用例绿，channels 837 零回归，live-verify 顺序实测。群聊拆批不另建（resolve_session_scope_id 已裁决） | — |
| B10 市场多源 priority | ⚠️ **改判：基本对齐，不立项**——market_adapters 已有六源适配器（skills.sh/clawhub/skillsmp/lobehub/aliyun/xfyun ≈ QwenPaw 7 源），聚合已按相关性排序 | — |
| B11 manifest 渠道过滤/env/preload | ✅ 落地：manifest 三字段+turn_context 渠道盖章（chat_pipeline execute）+select_skills_for_turn 过滤（渠道未盖章=零行为变化，env 缺失点名出局）；patch 法红 2→绿 6，注入回归 20 绿，live-verify 双渠道实测 | — |

**执行期坑（后续批次避让）**：
1. `writeFrame` 与 `_FrameWriter.write` 鸭子类型互递归（bytes 进 json.dumps）——帧出口方法名勿与协议函数撞；
2. `defaultSourceRevision` 引用旧函数名被裸 except 吞成 unknown——裸 except 连 NameError 都吞；
3. **并行会话清掉未跟踪新文件**（runner 四文件+测试整体消失）——按上下文重建后立即提交；未跟踪产物要尽早 `--only` 提交缩短暴露窗口；
4. console 路由实际前缀是 `/api/v1/console`（注册表声明 `/v1/console` 外还有全局 /api 前缀），新端点测试以真 app 探针定前缀；
5. `get_session_repository().get_session()` 返回 SessionRecord 对象（非 dict）——归属读取要兼容两种形态。

### P2（6 条，2026-11-18）

| 条目 | 结果 | 提交 |
|---|---|---|
| C2 Fallback 切换时序+强制复位 | ⚠️ **读码改判：结构性已对齐**——本仓 failover 状态是**请求级局部变量**（`multi_model_client.py:769` failover_excluded 在函数内），无 QwenPaw 式实例级 fallback 态可泄漏；流式路径失败即诚实终止（无重复输出风险），「首字前切换」为可用性增强、不立项 | — |
| C3 溢出不重放有效输出 | ⚠️ **读码改判：已对齐**——`openai_loop.py:754` `if gotContent or not isOverflow(error): return None`（已有有效输出不重放，注释明说"已产出的正文事件不重复 yield"） | — |
| C4 recall 防自污染 | ✅ 落地：归档写侧从 assistant.tool_calls 反查落 `tool_name`（orchestrator）+ 读侧 `recall_evicted` 双源排除 recall 族条目（context_pool `_RECALL_FAMILY_TOOLS`）；patch 法红→绿 5 用例，context 全目录 1154 零回归，live-verify 真池过滤实测 | 98ab3816a |
| C5 secret_store 增强 | ⚠️ **读码改判：基本已对齐**——`enc:v1:` 前缀灰度迁移（存量明文透传、保存自动迁移）与 keyring 链（env→keyring→文件）均已实装；「按安装路径哈希派生 account」不立项（本仓单实例部署形态无多安装互覆盖面，动密钥链兼容面不值） | — |
| C6 覆盖率棘轮+bundle 预算 | ✅ 落地：`scripts/ci/coverage_ratchet.py`+`neurova/ci/ci_ratchet_core.py`（实际<记录值即红、超越上调写回 `coverage_ratchet.json`，绝对下限 60 独立生效）+ `scripts/ci/bundle_budget.py`+`neurova/ci/bundle_budget_core.py`（JS/CSS gzip 合计 vs `NeurUI/bundle-budget.json`，首跑标定写回实测 4372.4KB 后只降不升）+ ci.yml 两处接线；12 用例绿，live-verify 真文件往返/真 dist 标定实测 | afe723b08 |
| C12 e2e 双档+page object | ✅ 落地：conftest 注册 `e2e_mock`/`e2e_real` 双档 marker（真后端档 NEUROVA_E2E_REAL=1 才跑，否则诚实跳过）+ `tests/e2e/pages/`（BasePage/BootPage）+ 三测试打标 + `_e2e.py` 临时脚本退役；harness 7 用例绿，e2e 默认档 mock 5 passed/real 诚实 skip，NEUROVA_E2E_REAL=1 真后端档 5 passed | 39cbfad3b |

### P2 二轮严格化（2026-11-18，复核指令后按教义第 5 条全命中点扫荡，推翻两条初判并落地）

首轮对 C2/C3/C5 的「已对齐」判读经二轮深查发现**三处真实缺口**（初判只看了
主链路，未扫全消费方/全兜底层），全部先红后绿补齐：

| 条目 | 二轮发现 | 修复 | 提交 |
|---|---|---|---|
| C2 Fallback 切换时序 | 初判只验了 multi_model_client 请求级状态与 OpenAI 环；扫荡全部 `chat_stream` 消费方后发现 **Anthropic 环不认 retry_status/reset**——模型 A 的半截正文与模型 B 的续写拼成缝合回复，typed 事件不出、前端无倒计时 | `anthropic_loop._predict_stream` dict 分支补 retry_status 处理：reset 时清空 reply_parts/reasoningGuard/pending_tool_calls 并让出 typed 事件，与 OpenAI 环同契约 | 1cf51a6c8 |
| C3 溢出不重放 | 初判只看了 loop 层 gotContent 门（`openai_loop.py:754`）；**管线层兜底会 Undo 该纪律**——`_callAgentLoopWithOverflowGuard` 压缩重试时，流式已让出的半截正文（ctx.partial_reply）会与新回复拼接/重复 | 守卫重试前判 partial_reply 非空则先发 `("retry", {reset: true})` 事件（消费方按既有协议清空半截）再压缩重试；非流式产出未出管线，保持静默恢复 | 25707f5b8 |
| C5 secret_store | 初判 declined「account 派生」（单实例无互覆盖面）；按指令补齐——固定条目名下同机多部署确实互覆盖密钥且无迁移路径 | `_keyringEntry()` = `config-secret-key-<sha256(数据根)[:12]>` + 旧条目灰度迁移（旧条目命中回填派生条目，双读期不弃钥）；链序 env 最优先不变；keyring 仍为可选依赖 fail-soft | 52e3a10d0 |

**二轮验证**：新测试 9 用例红 6→绿 9；agent/llm/security 三域 A/B（patch 法）
失败集合逐行比对**零新增**（预存 9 失败两轮一致，均为 tkg_retriever/
failureLanding/goal_gate 等无关项）；live-verify = 9681 真后端 boot
（/health 200、Registered router: /v1/providers 在册、改动模块随真实装配
链加载无异常）+ 真实 Fernet seal/unseal 回环与迁移语义实测（临时数据根，
真实密钥状态零波及）。

**执行期坑（新增）**：`.gitignore` 的 `tests/**/*_secret*` 反泄密规则会误杀
含 `_secret` 子串的正当测试文件名（`test_secret_store_*` 被 git add 拒收）——
测试文件命名避开该子串（改名 `test_keyring_account_derivation.py`），
不得用 `git add -f` 兜底（AGENTS.md §4）。

**前端适配面结论（2026-11-18 排查）**：本批改动几乎全在后端/测试/CI；
唯一必要适配 = C3 新 retry 相位 `overflow_retry` 的前端文案（缺失时落
「重试耗尽」兜底文案造成误标）——已补 `retryNoticeText` 分支 +
`retryNotice.phase` 联合 + 11 locale 文案 + 契约测试
（ChatPage.overflowRetry.test.ts，红 13→绿，全量 vitest 2679 绿 +
vue-tsc 0 错，17d49137f）。reset 清空语义前端本就支持（case 'retry'
既有分支），C2 流内切换（phase=switched）走既有文案，均零改动。
可选增强（端点就绪、暂无 UI 消费方，待拍板另批）：B7 工具完成缓存查询
（GET /chat/tools/{task_id}/result）可做结果查看面板。（B2 MEMORY.md 已于
2026-11-18 退役（c132f7d64），蒸馏回写另立
`2026-11-18-memory-distillation-plan.md` 进记忆温度体系。）
