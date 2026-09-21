# 工具↔经验↔再调用三环路修复 · 规格说明书

- 日期：2026-09-21
- 来源：Issue #80（用户派发 11 张工单：001–011）
- 范围：`neurova/agent/`、`neurova/tool_executor.py`、`neurova/skills/`、
  `neurova/evolution/`、`neurova/cognitive_layers/memory_layer/`
- 票集与依赖：[`docs/specs/2026-09-21-tool-experience-loop/tickets/`](./2026-09-21-tool-experience-loop/tickets/000-索引.md)

---

## 1. 问题陈述

「工具调用 → 经验记忆 → 再次调用」这条环路在**三处同时断开**，且断裂点互相咬合：

1. **不产票**：写票口唯一在 `tool_executor.py` 的 finally，原生 function-calling 链
   （`agent/loops/base.py` 的两条出口）不经它 ⇒ 原生链执行的工具在服务端证据账本上
   查无票据，`resolve_ticket_evidence` 恒 `absent`。
2. **形状分叉**：`chat_pipeline._call_loop_stream` 把 `{type, data}` 包装事件与原生的
   扁平记录写进**同一个**取证列表 ⇒ `turn_state.resolve_tool_outcome` 读不到 `success`
   （成功轮被判 False）、`post_chat_pipeline` 读出 `unknown` 工具名（真实库已有
   `skill_name='unknown,weather'` 的行）。
3. **三态折叠**：`success` 由不同位置的 `bool()` / truthiness 各自折叠 ⇒「未测量」显示成
   「失败」、「被策略拦截」计成「工具故障」，且拦截会永久粘在结构身份上。
4. **再调用不可用**：肌肉记忆的中文指纹用 `\w\s` + `split()`，中文整句成**一个** token，
   「指纹相等」≈「整串相等」，近似问法恒不命中；且写侧存的是降级后的 `{"_raw": …}`，
   命中后必然被参数校验拒 ⇒ 每次自动执行都往证据库续一张永久失败票。

## 2. 方案概述

按票据依赖顺序分两批落地，**先立可测量的探针，再改生产代码**：

- **第一批（探针与形状）** 001 三链路探针基座 → 002 工具记录形状单源；
- **第二批（收编与三态）** 003 原生链收编进执行咽喉 → 004 成败三态收口；
- **并行支线** 005 其余入口迁移 / 006 视图键域收口 / 007 肌肉记忆止血 /
  009 经验度量落库 / 010 采集可观测；
- **终态** 008 肌肉记忆指纹与参数复用（解 007 的临时收紧）。

三条贯穿原则：
1. **成败判据单源**：`tool_executor._result_is_success` 是唯一内容判据；
2. **形状单源**：取证源只有扁平记录一种形状，传输壳（SSE/蜂群流）不进取证源；
3. **三态不许折叠**：`True` / `False` / `None`（未测量）各归各位，落库 `NULL`。

## 3. 已定决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | 原生链执行一律经 `ToolExecutor` 咽喉 | 同一次执行一次收齐票据 / `on_tool_executed` / 治理 / hooks / 超时 |
| D2 | 取证源只收扁平记录 | 包装事件是传输壳，语义与扁平记录重复且缺关键字段 |
| D3 | `success` 列放开为可空 | 「没测到」与「失败」在检索降权、指标、展示三面必须分得开 |
| D4 | 肌肉记忆**彻底修**（不砍臂） | 先止血（007）再换指纹与写侧参数（008） |

## 4. 测试决策

- 探针必须经**生产构造点**驱动（真 `Agent` / 真 `ToolExecutor` / 真 `ChatPipeline`），
  替身只放在模型边界（`ScriptedModel` 只实现 `chat_stream` / `chat`）；
- 反向锁各一条：证明拦阻者确实是根因，不是探针写错；
- 写验证一律落 `tmp` 库（`NEUROVA_EKB_DB` + `SkillService` 目录隔离），
  **严禁**对 `data/` 生产库写验证。

## 5. 明确不做（登记）

- **D5 失败粘性解冻**（绑工具契约版本）：依赖本批落地后才有新数据校准，另批；
- `injector.py` 的 `context`/`content` 键错位：只在非池路径可达，本批不定级；
- `estimate_confidence` 序列分虚高、`voice_memory_bridge` 硬编码 success、
  `neurflow/builtin.py` 吃模型自报：前两批已登记项，本批不重复计入。

## 6. 执行结果（逐票）

见各票「执行结果」节与 PR 描述。关键读数：

- 001 探针三条：改前全红（形状 2 条违规 / 票据 `absent` / EKB `unknown,get_datetime`），
  003 后全绿；
- 003 起原生链执行产票：`lookup == "evidenced"`；
- 006 停用生效判据改为「发给 LLM 的工具清单少一项」；
- 008 换实体近似句 confidence 由 0.400 升到 0.85（门槛 0.8 可达）。

## 7. 第二轮补做（006 / 005 残留 + 011）

前一轮只完成主干，三条收口各有未尽的断点，第二轮逐条补齐（明细见
[`000-索引.md`](./2026-09-21-tool-experience-loop/tickets/000-索引.md)）：

- **006**：`VisibleSkill.enabled` 的三条判停落点此前只有 manifest `enabled` 一条真生效；
  补 registry 运行时 `status` 与生命周期 `usage.state=archived`，三闸同读一份 entry。
  同名冲突计数改为可重跑（`scripts/diagnostics/skill_name_collisions.py`）。
- **005**：`neurflow` 两处 `get_tool_engine` 是**不存在的导入**（静默零同步）；
  `/tool-layers/tools/execute` 把 `ToolEngine` 当入口用（绕过咽喉）。两处各自改道 + 守卫。
- **011**：整票交付——回滚判据单源（`should_rollback`）、留痕落 `revisions`、
  治理面端点（未装配 503 / 空归档 409）、`AgentSkillPage.vue` 归档与回滚入口、
  11 份 locale。

live-verify（真 Agent + 真 ToolExecutor + 真 SkillService）：端点经咽喉执行产票、
停用/归档后工具面各少一项、重建→归档→回滚留痕带操作者、`improvements` 键未复活、
空归档回滚返回 False。
