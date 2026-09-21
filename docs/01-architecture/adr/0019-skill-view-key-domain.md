# ADR 0019: 技能视图键域收口（查询键 = name，记账键 = identity）

- **Status**: Accepted
- **Date**: 2026-09-21
- **Decision Maker**: 工具↔经验↔再调用三环路修复批（工单 006）

## Context

`skills/skill_visibility.py` 的 `build_turn_view` 建了**两类**条目，且两类用不同键：

- ① registry 运行时技能：按 registry 键（= `skill.name`）建，条目里**硬编码 `enabled: True`**；
- ② 三库 manifest 条目：按 `skill_service.iter_skills()` 的键（= `skill_id`）建，并按其 `enabled` 过滤。

而 schema 装配（`context/orchestrator.py`）拿的是 **name** 去问视图（`_view.invocable(n)`）。

自动技能的 `name ≠ skill_id`（`evolution/skill_encapsulation.py` 明写"名字不是身份"），
于是永远命中①条目，三件事同时恒开绿灯：

1. `quality_for(name)` 读①⇒无 `usage`⇒返回 `None`⇒质量熔断 `quality_blocked(None)` 放行；
2. manifest 的 `enabled=False` 只挡②，挡不到①；
3. `SkillRegistry.set_skill_enabled` 只改 `skill.status`，而 schema 段没有 `status` 判据
   （runtime `Skill` 也无 `enabled` 属性，`getattr(s, "enabled", True)` 恒取默认值）。

表现：在管理面停用一条自动技能，**LLM 的工具面一个都不少**；质量熔断对自动技能咬不动。

## Decision

**键域收口为"一次反查"：查询键是 `name`，但 `name` 必须能取到 identity 那份 entry。**

- `build_turn_view` 对每个 manifest 条目：取其 `name` 作为**视图键**，把 manifest 的
  `enabled` / `usage` / `trust` / `status` 与 registry 底座的展示字段**合并进同一份 entry**；
  停用的名字连同 registry 底座条目一并从视图摘除（否则①那条硬编码 True 会把停用"救回来"）。
- `SkillView.invocable` / `quality_for` / `trust_for` 三个取数口统一读这一份 entry，
  **不再各自查一遍**。
- 可调性判据 = `enabled` 且 `status` 不属停用态。`enabled` 是运营面/评审闸的落点，
  `status` 是 registry 运行时状态机，任一判停即不可调。

不新建第三份 name↔identity 映射（工单 015 教训：映射必须单源）。

## 同名覆盖：出声不硬拒

`SkillRegistry.register` 按 `skill.name` 建键，`name ≠ skill_id` 的自动技能会**静默**顶掉
先到的同名条目（现网 `data/agents/default/skills/manifest.json` 有 8 条不同 `synth_*`
共用 name=`general_tool`）。本单只加**告警 + 计数**（`_name_collision_count`），
**不硬拒**：当场硬拒会让存量库装配失败，迁移方案另单。

## 不采纳的替代方案

- **视图按 `skill_id` 索引**：schema 装配、执行门、目录渲染三处调用方全都拿 name 查询，
  改索引等于同时改三处查询面并引入一次全局改名；ADR 0017 的"键域统一"方向没错，
  只是没覆盖视图域——补的是这一域的反查，不是把查询键换掉。
- **给 runtime `Skill` 加 `enabled` 属性并让它读 manifest**：runtime 对象是注册表的内存态，
  让它反查磁盘 manifest 会把 IO 拖进执行热路径，且"停用"是运营面语义、不该由执行体承载。

## Consequences

- 停用/熔断的生效判据变成"**发给 LLM 的工具清单真的少了那一项**"（断言 `tools_for_llm`），
  不再以"manifest 字段变了"充数。
- 视图条目多带一份 `status`/`usage` 快照，装配成本可忽略（内存态合并）。
- 同名冲突在存量库上可复算（计数），迁移待另单。

## References

- 守卫：`tests/unit/skills/test_skill_view_key_domain.py`、`tests/unit/skills/test_visibility_wave_h2.py`
- 相关：ADR 0017（技能注册表键值域统一）、ADR 0011（SkillRegistry 单一实现）
