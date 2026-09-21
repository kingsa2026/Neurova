# ADR 0017: 技能注册表的键值域统一（name 与身份域归一为一次查找）

- **Status**: Accepted
- **Date**: 2026-09-20
- **Decision Maker**: RSI 进化闭环修复批次 · 工单 014

## Context

ADR 0011 判定了**实现**只有一个（`neurova/skill_system.py` 的 SkillRegistry，类 A），
但它没管**键值域**：注册表以什么字符串建键、调用方以什么字符串取键，是另一层契约。

探索发现（逐行核实，行号为修复前）：

- 建键单点：`skill_system.py:505` `self._skills[skill.name] = skill` —— 键域 = **name**
- 身份解析：`skills/skill_contract.py:88-92` 次序 **skill_id → id → name → fallback**，
  且 `canonicalize_skill_identity` 永不覆写既有 `skill_id`（`:108`）
- 注册边界写入的恰是 `skill_id`：`skill_system.py:504`、`_carry_manifest_identity :580-585`
- 进化侧 8 个取键点传的都是身份解析的结果：`agent_core.py:1370`、
  `skill_experience.py:195/280/358`、`skill_improver.py:523/664`、
  `post_chat_pipeline.py:2513`、`collaborate/workflow/scheduler.py:396`

`id != name` 时（技能台账与工具清单本就允许两名）两个域不是同一个串，实测
`register_skill(id='skill_ab12…', name='read_write_skill_…')` 之后
`get_skill(identity)` 返回 **None** ⇒ 上述 8 处取键全灭：改进提案永不落到技能本体、
经验重建静默跳过、启停对按 id 寻址的调用方恒 False、执行链判"不存在"。
全部失败都发生在 `except` 之后或返回 False 的路径上，**没有任何报错**。

## Decision

**键值域归一发生在注册表内部的一次查找上，不发生在任何一个调用方。**

1. `SkillRegistry` 增设身份索引 `_identity_index: Dict[str, Skill]`（`skill_system.py:487`），
   登记 `canonicalize_skill_identity()` 的返回值，与主字典指向**同一个对象**。
   建键单点（`register`）同时写两处（`:521-524`）——canonicalize 已经算出最终身份，
   直接用它登记，不做二次解析。
2. 唯一定位口 `_lookup(key)`（`:608-617`）：主字典 → 身份索引。
   `get_skill` / `has_skill` / `set_skill_enabled` / `execute_skill` / `unregister` / `clear`
   六个动作全部改走它，`unregister` 按对象身份同时摘两侧（摘一侧会留幽灵技能）。
3. `get_skill` 补进 `SkillRegistryProtocol`（`:449`）：协议此前只声明
   `skills` 只读视图，没有"定位单个技能"这一口，于是调用方字典直取
   `skills.get(name)` —— 那是绕过归一的第二套键域。`tool_executor.py:931` 与
   `agent/chat_pipeline.py:873` 两处按此迁回，并由
   `tests/unit/skills/test_skill_identity_key_domain.py::test_no_direct_dictionary_lookup_outside_the_registry`
   以 AST 锁住（新增绕过点即红）。
4. 迭代面（`.skills.items()`：LLM 工具清单、语义检索候选）保持 name 键域不变 ——
   那是**执行与展示域**，模型看到的工具名必须是 name。

### 不采纳的替代方案

- **让 name 成为唯一身份**（取消 skill_id 索引）：被否。台账侧身份就是 `skill_id`，
  且 ADR 0011 之前定下的 `canonicalize_skill_identity` 明确"已有身份永不覆写"
  ——工具名与账本 id 可以合法不同，覆写会撕裂改进/经验/回滚的谱系。
- **把主字典键改成身份域**（工单 014 阶段三原案）：被否。`skills` 视图的键就是喂给
  LLM 的工具名，翻转主键要么改名（模型侧工具面漂移、历史会话里的调用名失效），
  要么在视图 property 里再反查一次 name（把归一成本摊给每个消费者）。
  身份索引 + 单点 `_lookup` 用一份冗余指针换到同样的"两键同对象"不变量。
- **每个调用方各自 `resolve_skill_identity()` 后再取**：被否。那是第 9 处、第 10 处
  口径，两处迟早漂移（本批次一路在拆的就是这种"多处各写一遍"）。

### 迁移期契约

扩展（双登记）→ 迁移（调用方逐个改走 `_lookup`）→ 收缩（字典直取由 AST 锁清零）。
全程保持绿；每批迁移点的验收是"在 `id != name` 用例下返回 True / 非 None"。

## Consequences

- **正向**：8 个身份取键点 + 执行入口一次性转绿，改进/经验/启停/执行四种动作
  作用在同一个对象上；键域差异被封在注册表内部，调用方无需知道有两个域。
- **负向**：一次登记写两份索引、`_identity_index` 与 `_skills` 必须同生同灭
  （由 `register`/`unregister`/`clear` 三点保证，用例覆盖）。name 冲突时主字典后写覆盖，
  身份索引仍指向最后登记对象，与既有 `_skills` 语义一致（未新增冲突面）。
- **验证**：`tests/unit/skills/test_skill_identity_key_domain.py`（8 例，先红后绿）+
  `tests/unit/skills/test_improvement_persistence.py`（反掩盖：删掉假注册表 `_FakeRegistry`，
  改用真实 `SkillRegistry` 且 `id != name`；改后有 2 例转红，证其此前靠假注册表洗绿，已修到绿）。
- **未验证**：注册表在真机多 agent 会话下的身份索引命中率（无观测面，见工单 012 收口后的
  `get_status()`）；本 ADR 的判据全部来自单元与静态锁。

## References

- 实现：`neurova/skill_system.py`（`_identity_index` / `_lookup` / `SkillRegistryProtocol`）、
  `neurova/tool_executor.py`、`neurova/agent/chat_pipeline.py`
- 相关 ADR：[0011 统一 SkillRegistry](./0011-unify-skill-registry.md)（本单补它未管的键值域）、
  [0016 RSI 参数事实源](./0016-rsi-parameter-source-of-truth.md)
- 工单：`docs/specs/2026-09-19-rsi-closed-loop/tickets/014-身份键统一扩展收缩.md`
