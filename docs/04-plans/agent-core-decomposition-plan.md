# agent_core.py 上帝对象拆分方案（行为不变的分阶段重构）

> **立项日期**：2026-09-16
> **依据**：全库实测审计（AST 方法行数统计 + 属性访问面扫描 + patch 目标扫描 + 测试基线实跑）
> **约束**：每阶段行为零变化——公开属性名、方法签名、返回类型、异常语义、patch 目标全部保持
>
> **执行状态**：Phase 0 已完成（2026-09-16）；Phase 1 已完成（2026-09-17，与原方案有重大偏差，见 Phase 1 节）
> ——棘轮与契约守卫已入库并常驻 CI
> （`test_agent_core_size_ratchet.py` 17 用例已列入 `scripts/ci/protected_tests.txt`；
> `test_agent_public_contract.py` 30 用例因需真实构造 Agent，待 CI 瘦依赖环境验证后再入列）。

---

## 1. 实测现状

### 1.1 文件结构（2182 行）

| 区块 | 行范围 | 行数 | 职责 |
|------|--------|------|------|
| `debug_log` | 103–119 | 17 | 调试日志 |
| `AgentLLMClient` | 120–206 | 87 | LLM 客户端包装（测试 patch 目标） |
| `AgentConfig` | 207–371 | 165 | 配置 dataclass |
| `_NullSystem` + `wire_memory_guards` | 372–450 | 79 | 空系统占位 + 记忆守卫装配 |
| `SubSystemContainer` | 451–1036 | **586** | 初始化逻辑，已按 12 域分组（上轮成果） |
| `Agent` | 1037–2182 | **1145** | 上帝对象（本次拆分对象） |

### 1.2 Agent 类体量

- **56 个方法**（含 property getter/setter 对），方法体合计 **1041 行**
- 方法体 Top 10：

| 方法 | 行数 | 归属域 |
|------|------|--------|
| `process_multimodal` | 140 | 多模态入口 |
| `_init_cognitive_graph` | 92 | 记忆/认知装配 |
| `_on_skill_post_execute` | 87 | 技能 |
| `chat` | 63 | 对话主链 |
| `_init_memory_modules` | 62 | 记忆/认知装配 |
| `init_router` | 61 | 路由 |
| `_record_tool_failure_lesson` | 53 | 工具失败闭环 |
| `chat_stream` | 42 | 对话主链 |
| `process_message` | 38 | 对话主链 |
| `rebuild_loop` | 27 | 模型/循环切换 |

### 1.3 耦合面（决定策略的关键数据）

| 事实 | 实测值 | 对方案的含义 |
|------|--------|--------------|
| 外部 `self.agent.xxx` 访问 | 19 处 | 显式访问少，说明多数通过 `agent_ref` 间接访问 |
| 多形态 agent 属性访问 | ~350 处 | 属性契约是**事实接口**，不可搬离 Agent 实例 |
| 外部直接读**私有字段** | `_skill_registry` 60、`_tool_messages_list` 37、`_collect_tool_messages` 24、`_current_user_input` 13、`_builtin_tools` 9、`_turn_count` 8… | **字段必须留在 Agent 实例上**，或为私有名加转发（不划算） |
| 外部直接**写**私有字段 | `_turn_count`、`_tool_messages_list`、`_current_reasoning`、`_current_user_input`、`_last_tool_used`（tests 多处） | 状态对象抽取必须先迁移这些写点 |
| Agent 类内 `super()` 调用 | **0 处** | mixin 切分无 MRO super 链风险 ✓ |
| 测试 patch 目标 | `neurova.agent_core.AgentLLMClient`、`Agent._load_identity`、`Agent._init_memory_modules`、`neurova.agent_core.get_session_manager` | 类仍在 agent_core 且方法在 MRO 上则 patch 继续有效 |
| 测试安全网 | 93 个测试文件引用 agent_core；`tests/unit/agent/` **1032 passed / 11 skipped** | 基线健康，可作每阶段验收闸 |

### 1.4 核心问题：尺寸反弹

`docs/CONTEXT.md` 记录上轮重构成果 **2180 → 1621 行**；**当前实测 2182 行**——已回涨 +561 行，超过拆分前体量。

> 根因：拆分是单向动作，没有棘轮守卫。新功能持续落回 Agent 类，历史成果被逐步吃掉。
> **结论：本方案的 Phase 0 必须先建尺寸棘轮，否则任何拆分成果都只是暂时性的。**

---

## 2. 目标与非目标

**目标**
1. `agent_core.py` ≤ 900 行；`Agent` 类 ≤ 400 行（含 docstring）
2. 每阶段行为零变化，且**独立可 revert**
3. 尺寸棘轮常驻：拆分成果不可被后续功能回填

**非目标**
- 不修 bug、不改行为、不顺手优化、不调格式
- 不重构已完成的 `SubSystemContainer` 分组（仅接收 Phase 4 迁入的记忆装配残部）
- 不引入新依赖、不改公开 API 签名

---

## 3. 策略选型

两个候选，按域分别选用：

### 策略 A：Mixin 切分（**主选**，覆盖大多数域）

```
class Agent(ChatRuntimeMixin, TurnStateMixin, ModelSwitchMixin,
            SkillFacadeMixin, MemoryWiringMixin, LoopGuardMixin):
    """剩：门面 + 生命周期 + 属性转发"""
```

- **优点**：字段天然留在 `self` 上（`_skill_registry` 60 处直接访问全部不受影响）；`patch('neurova.agent_core.Agent.xxx')` 走 MRO 继续命中；无 `super()` 链风险（实测 0 处）；机械式切分，行为等价性最容易论证
- **缺点**：仍是同一个类，`self.xxx` 隐式耦合未真正解除（文件变小、耦合变浅，但没消除）
- **适用**：技能、模型切换、装配、对话入口、循环检测等**行为型**域

### 策略 B：组合委托（**辅选**，仅状态型域）

抽出独立状态对象（如 `TurnState`），Agent 保留 property 转发。

- **优点**：真正解耦、可单测、可复用
- **缺点**：私有字段直接读写点必须先迁移（`_tool_messages_list` 37 处读 + tests 多处写）；转发垫片是净新增 LOC
- **适用**：轮次/请求状态（Phase 1）——内聚度最高、收益最大
- **前置**：Phase 1 前先完成 1.3 表中的私有写点迁移（tests 同步更新，属"允许的测试改动"）

> 决策规则：**能在不触碰字段访问点的前提下搬走的 → A；内聚强且值得为此迁移访问点的 → B。**

---

## 4. 行为不变的硬约束

1. **签名冻结**：搬迁方法不得改参数名/默认值/返回类型/异常类型。`inspect.signature` 快照守卫。
2. **命名空间 re-export**：搬走的模块级符号（`AgentLLMClient`、`wire_memory_guards`、`get_session_manager` 等）必须在 `agent_core.py` 保留 import，否则 patch 目标失效 → 测试红。
3. **字段归属不变**：Agent 实例属性集合不变（`__dict__` 键集快照）。
4. **无反向导入**：`agent/*` 新模块**不得** import `agent_core`；需要 Agent 时走 `agent_ref` 注入（沿用既有模式，必要时延迟导入）。
5. **锁所有权**：`asyncio.Lock`（`_model_switch_lock`）由 Agent 创建持有，逻辑可外迁、锁不随外迁（跨事件循环语义）。

---

## 5. 分阶段计划

### Phase 0 — 安全网与棘轮（**必做前置**，0.5 天）✅ 已完成

| 项 | 落地结果 |
|----|------|
| 棘轮 | `tests/unit/agent/test_agent_core_size_ratchet.py`（17 用例）：七项指标只降不升 + history 单调防篡改 + 方法数豁免登记 + goal 不高于实测。基线 `agent_core_size_baseline.json`。**已入 protected_tests.txt 常驻 CI**（AST-only，不影响覆盖率门禁） |
| 契约 | `tests/unit/agent/test_agent_public_contract.py`（30 用例）：模块消费者面（显式清单，含 re-export 的 `get_session_manager`——`vars()` 探测会漏它）、类体成员名单+种类、签名逐字比对、实例字段集（含显式迁出登记表）、快照完整性**双向断言**、patch 目标可解析性 |
| 手法 | 快照由一次性生成器产出（已删）；实例字段以 `Agent(workspace_path=tmp, enable_memory=False)` 真实构造采集（套件既有轻量路径，2.3s） |
| 红灯验证 | ① 污染 agent_core +1 行 → 棘轮 2 红 ✓；② 真实代码改 `workspace_path` 属性名 → 契约 3 红 ✓；③ **删快照条目模拟"吞 diff"→ 初版守卫仍绿（单向盲区，实录）→ 补 TestSnapshotIntegrity 双向断言后 1 红 ✓** |
| 验收 | `tests/unit/agent/` **1079 passed / 11 skipped** 全绿；受保护子集 228 passed + 覆盖率 62.19%；全库收集 0 errors |
| LOC | +2 测试文件 + 2 快照 JSON（防回归用例，不计净 LOC）；生产代码零改动 |

### Phase 1 — 轮次/请求状态 → `neurova/agent/turn_state.py`（策略 B，~110 行迁出）✅ 已完成（2026-09-17）

> **执行偏差说明（如实记录）**：实施侦察发现方案写立时基于的旧事实已漂移——
> 轮次级状态的**存储**早已在审计 P0-B1 迁入 `neurova/core/turn_context.py`（ContextVar），
> Agent 的 17 个轮次 API（P3-c）已变成单行转发；方案中“tests 直写私有字段的 5 处”
> 也已大部分被历次修复收编（现仅 conftest MagicMock 与 pipeline 测试的自造 fake 对象）。
> 故本阶段实际执行的是：**实现归位（TurnState 门面对象）+ 两处 P0-B1 遗留分叉根治**。
>
> **根治的分叉（原方案未发现的真实缺陷）**：
> 1. `Agent._collect_tool_messages()` 读死实例属性 `_tool_messages_list`（ContextVar
>    迁移后恒空）→ post_chat_pipeline 3 处消费点恒拿 []，工具消息永不落盘；
>    已改为转发 TurnState（读同一 ContextVar）。
> 2. `Agent._set_reasoning()` 写死实例属性 `_current_reasoning` →
>    channels/post_chat 经 `getattr(agent, "current_reasoning")` 恒拿 None；
>    已改为 `set_current_reasoning()`（写同一 ContextVar）。
>
> **落地物**：`neurova/agent/turn_state.py`（162 行门面，无反向依赖）；
> Agent 保留全部同名转发 + 新增 `turn_state` property（懒建，兼容 `__new__` 直构）；
> `_current_user_input` property getter/setter 原样保留（getattr 契约 + A-04 契约）。
> **守卫**：`test_turn_state_facade.py` 15 用例（门面语义/转发契约/分叉防回归/无反向依赖 AST 断言）。
> **验证**：a04+state_api+turn_session 套件 38 绿；`tests/unit/agent/` 1094 passed；
> 静态门禁全过；收集数 16495 无异常。棘轮：2182→2159（类 1146→1122；方法 +1 为 turn_state
> property 转发面，带 waiver）。净 LOC：生产 +186/−27（含两处分叉修复与注释）。
> **残留登记**：`_tool_messages_list`/`_current_reasoning`/`_turn_count` 旧实例属性在
> ~30 个测试文件里仍是 MagicMock/fake 的属性名（不影响真 Agent 行为），收编属后续阶段。

- **迁出**：`set_request_identity`、`_current_user_input`(prop+setter)、`current_user_input`、`current_session_id`、`current_user_id`、`current_reasoning`、`set_current_reasoning`、`_set_reasoning`、`increment_turn_count`、`turn_count`、`session_id`、`reset_tool_messages`、`append_tool_messages`、`get_tool_messages_snapshot`、`_collect_tool_messages`、`append_tool_event`、`tool_events`
- **理由**：单一内聚状态（"本轮"上下文），跨模块访问最频繁；抽成对象后可独立单测
- **手法**：`TurnState` 持有字段；Agent 保留同名 property + 方法转发；tests 直接写 `_turn_count` 等私有字段的 5 处一并迁到公开 API（属允许的测试改动）
- **风险**：低（无异步、无 IO；property setter 语义需逐一比对）
- **验收**：`tests/unit/agent/`、`tests/unit/core/test_agent_*.py`、`tests/unit/api/test_memory_request_scope.py`（依赖 `set_request_scope` 链）

### Phase 2 — 模型/循环切换 → `neurova/agent/model_switch.py`（策略 A，~55 行）

- **迁出**：`rebuild_loop`、`_get_model_switch_lock`、`_rebuild_loop_locked`（锁创建留 Agent）
- **风险**：中（asyncio.Lock 所有权 + 事件循环亲和）
- **验收**：`pytest -k "rebuild_loop or model_switch"` + `tests/unit/agent/`

### Phase 3 — 技能门面 → `neurova/agent/skill_facade.py`（策略 A，~150 行）

- **迁出**：`skill_registry`(prop+setter)、`skill_manifest_provider`(prop+setter)、`get_skill_manifest`、`load_skill`、`_on_skill_post_execute`、`_loaded_skills`
- **理由**：单块最大（150 行）、内聚清晰；`_skill_registry` 60 处直接访问由 mixin 天然兼容
- **风险**：中（`AgentSkillManager` / `SkillRegistry` 事件注册握手；`_on_skill_post_execute` 被外部直接调用 8 处）
- **验收**：`tests/unit/agent/test_agent_core_skill_imports.py`、`test_agent_skill_packer_init.py`、`-k skill`

### Phase 4 — 记忆/认知装配残部 → `SubSystemContainer.init_memory`（策略 A，~173 行）

- **迁出**：`_init_memory_modules`(62)、`_init_cognitive_graph`(92)、`_update_memory_temperature`(19)
- **注意**：这三个方法**已被 `SubSystemContainer` 调用**（agent_core 576/584 行）；且 `_init_memory_modules` **被多个测试 patch**（`test_agent_chat_tracer_bullet.py`、`test_agent_neuHebb_integration.py`、`test_agent_minimal.py`、`test_data_flow_closed_loop.py`）
- **手法**：逻辑移入 container 的 `init_memory` 域；Agent 上**保留同名转发方法**（patch 靠 `patch.object(Agent, ...)` 与 `patch('neurova.agent_core.Agent._init_memory_modules')`，MRO 命中即可）
- **风险**：中高（装配顺序敏感 + patch 面广）→ 建议拆分后立刻跑 `tests/integration/test_agent_minimal.py`
- **验收**：`tests/unit/agent/`、`tests/integration/test_agent_minimal.py`、`test_data_flow_closed_loop.py`

### Phase 5 — 循环检测包装层（策略 A，~12 行）

- **迁出/删除**：`_detect_content_loop`、`_calculate_similarity`、`_has_repeated_patterns`、`detect_content_loop`——四者均为 3 行包装，底层已有独立模块 `neurova/agent_loop_detection.py`
- **手法**：Agent 保留转发（对外签名不变），实现直接委托模块函数
- **风险**：低
- **验收**：`-k "detect_content_loop or repeated_patterns or similarity"`

### Phase 6 — 对话入口收敛 → `neurova/agent/chat_runtime.py`（策略 A，~300 行，**最高风险**）

- **迁出**：`process_message`、`chat`、`chat_stream`、`process_multimodal`、`_build_tools_for_llm`、`_execute_text_tool_calls`、`_save_to_session`、`clear_history`、`_record_tool_failure_lesson`、`record_tool_failure_lesson`、`get_llm_stats`、`get_integration_info`
- **顺序**：先 `process_multimodal`(140) 独立成 multimodal 模块 → 再 chat 三件套（前置阶段已把状态外移，此阶段 Agent 只剩编排）
- **风险**：高（主链路；ChatPipeline/PostChatPipeline 边界重划需谨慎，只搬不改）
- **验收**：`tests/unit/agent/` 全量 + `tests/unit/core/test_agent_chat_stream.py` + `tests/integration/test_agent_loop.py`

### Phase 7 — 收尾（策略 A，~110 行）

- **迁出**：`_load_identity`(25)、`init_router`(61)、`spawn_subagent`、`router`(prop)、`shutdown`、`workspace_path`、`__repr__`
- **风险**：中（`init_router` 61 行含路由装配；`_load_identity` 被 patch 2 处）
- **验收**：`tests/unit/agent/test_agent_config.py`、`test_agent_integration.py` + 全套

---

## 6. 每阶段 DoD（缺一不可）

1. `pytest tests/unit/agent/ -q` 全绿（基线 1032 passed）
2. 目标测试套件绿（见各阶段验收）
3. 尺寸棘轮绿（行数已下调到本阶段实际值）
4. 公开契约快照绿（无成员丢失 / 无签名变更）
5. 导入冒烟：`python -c "from neurova.agent_core import Agent, AgentConfig, AgentLLMClient"`
6. patch 目标清单逐项验证（4 项）
7. `docs/CONTEXT.md` 重构状态同步 + 净 LOC 记账（迁出行数 vs 转发垫片成本）

---

## 7. 风险登记表

| 风险 | 影响 | 缓解 |
|------|------|------|
| patch 目标失效 | 多个测试红 | 符号在 `agent_core` re-export；Phase 0 守卫锁定 patch 目标存在性 |
| 私有字段访问断裂 | ~200 处调用点失效 | 策略 A 保字段在 `self`；Phase 1 走 B 时先迁移访问点 |
| 尺寸反弹（已发生一次） | 拆分成果被吃掉 | Phase 0 棘轮，只降不升 |
| 循环导入 | 启动即失败 | 新模块禁止 import `agent_core`；沿用 `agent_ref` + 延迟导入 |
| asyncio.Lock 跨事件循环 | 死锁 | 锁所有权留 Agent（约束 5） |
| property 同名遮蔽 | 静默行为变化 | 每个 property 归属唯一 mixin；Phase 0 快照含 property 定义列表 |
| 装配顺序敏感（Phase 4） | 记忆/认知初始化异常 | 逻辑搬移不改顺序；迁后立即跑集成冒烟 |
| 主链回归（Phase 6） | 对话不可用 | 放最后；前置阶段已降压；只搬不改 |

---

## 8. 排期与依赖

```
Phase 0（棘轮+契约，必做）
   └─ Phase 1（TurnState，B）─┬─ Phase 2（模型切换）
                              ├─ Phase 3（技能门面）
                              ├─ Phase 4（记忆装配）
                              ├─ Phase 5（循环检测）
                              └─ Phase 6（对话入口）── Phase 7（收尾）
```

- Phase 1–5 可并行（不同 mixin/对象，文件不重叠）；Phase 6 依赖 1–4 完成（状态与技能已外移，主链才只剩编排）
- 每阶段独立 commit，提交信息含"净 LOC 去向"（转发垫片行数）

## 9. 完成判据

- `agent_core.py` ≤ 900 行、`Agent` 类 ≤ 400 行
- 公开契约零丢失（快照 + patch 清单全绿）
- 行为零变化：`tests/unit/agent/` + 相关 integration 全绿
- 尺寸棘轮常驻 CI，后续新功能无法回填

---

## 附：本方案与历史拆分的关系

| 历史成果（CONTEXT.md） | 本方案 |
|------------------------|--------|
| MemCore / ContextOrchestrator / ToolExecutor / PostChatPipeline / ChatPipeline 提取 | 保持不动（Phase 6 只重划边界，不改其内部） |
| `Agent.__init__` → `SubSystemContainer`（427→14 行） | Phase 4 把记忆装配残部并入该 container，不推翻其分组 |
| "2180→1621 行"（已回涨到 2182） | Phase 0 棘轮解决回涨 |
