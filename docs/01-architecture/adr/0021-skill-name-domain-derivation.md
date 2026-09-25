# ADR 0021: 技能名字域迁移（同 name 不同身份 ⇒ 名字携带身份）

- **Status**: Accepted
- **Date**: 2026-09-25
- **Decision Maker**: Issue #189 残留收口 · ADR 0019「同名覆盖：出声不硬拒」留的口

## Context

ADR 0017 定了注册表的键域：**主字典按 `skill.name` 建键**（name 是执行与展示域，
模型看到的工具名就是它），身份域是 `skill_id`，两键经 `_lookup` 归一到同一个对象。
ADR 0019 又把这层纪律钉进视图域，并写明同名覆盖「**出声不硬拒**」——因为
**存量库**里已经有撞名条目：历史生成器遗留的 `ai_tool` / `general_tool` 被多条
不同身份的自动技能（`synth_*`）共用。当场硬拒会让存量装配直接失败，故迁移留给另单。

随之而来的实况（Issue #189 启动实测累计 10 次告警）：

- 注册表只留得住**先到者**，同一 name 下其余条目在工具面上**静默消失**——
  "少了几条"在读数上不可见，工具面与技能库对不上；
- 这些条目在库里都还在（`iter_skills()` 数得出来），所以"少了"只体现在 LLM 的工具清单上；
- 上一批只修了**产生侧**（新合成名携带身份），存量库不动。

## Decision

**名字域 = 身份的函数**：同一份技能库里，同 name 不同身份的额外条目必须拿到一个
**携带身份**的派生名；唯一占用的名字**原样保留**（对无关条目零 churn，也不改字形）。

判据只写一份：`neurova/skills/skill_name_domain.py`。它提供的三件事：

- `claimUniqueName(base, identity, taken)`：空闲即原名，被占即派生（派生名恒满足
  工具名契约 `^[a-zA-Z0-9_-]{1,64}$`；身份缺席时**不伪造**身份，原样返回由调用方出声）；
- `migrateManifestNames(payload)`：就地收敛一份 manifest（幂等、不丢条目、不动血缘，
  别名表与 `identity`/`version_history` 一概不碰）；
- `recountManifestCollisions(payload)`：复算读数（口径与 `SkillRegistry._warn_on_name_collision`
  一致 = 同 name 下身份不同的额外条目数），迁移前后可对照。

三种消费共用同一份判据：

1. **存量库迁移**：`SkillService.__init__` 打开库的那一刻就地收敛并落盘。理由：
   "名字域唯一"是**库自身的不变量**，不是某个装配点的责任——放在库的生命周期起点，
   冷启动、提案回灌、API 直读全部自然覆盖；落盘失败回读磁盘并出声（`persisted=False`），
   不把"没写成功"读成"迁移完成"。
2. **新写入取名**：`SkillService` 的两个写入口（`_register_metadata`、`install_skill` 的
   新增分支）按同一判据取名——**按构造成立**，而不是等下一次装配事后补救。
   同名**覆盖式重装**（同一 `skill_id`）是升级语义，保留原名。
3. **运维复算/迁移**：`scripts/diagnostics/skill_name_collisions.py`（加 `--apply` 就地迁移），
   脚本内不含第二份口径。

**不翻转主键**（不采纳"注册表主字典改成 identity 建键"）：ADR 0017 已否过同一方案
——那会让模型侧工具面漂移、历史会话里的调用名失效，或在视图 property 里再反查一次
name（把归一成本摊给每个消费者）。本 ADR 补的是"键域的取值"这一层：让按 name 建键
不再意味着丢条目。

## 不采纳的替代方案

- **注册表改成"同名条目共存"**（主字典值变列表）：会同时改 8 处按 `.skills.items()`
  迭代的消费面（工具清单渲染、语义检索、目录渲染、MCP 面……），且"同名两个工具"
  对模型是无意义输入——同一份清单里出现两条同名 function，派发歧义无解。
- **当场硬拒存量库**（ADR 0019 明确排除）：存量装配失败，用户看到的是起不来，
  而病灶是历史数据形状。
- **装配点各自迁移**：迁移点会长出第二处、第三处口径（冷启动一处、提案回灌一处、
  API 一处），正是本批一路在拆的"多处各写一遍"。
- **顺手把 `本地版` / `Web Search` 这类非 ASCII 名字改成 ASCII**：超出"键域唯一"的
  范围（改的是字形，不是键域），且会打断既有引用。字符集约束只作用在派生名上——
  派生名要进工具清单，必须合法。

## Consequences

- **正向**：存量库装配后工具面条目数 = 库内条目数（实测 10/10，身份域全部可取），
  注册表同名覆盖计数 0；迁移幂等，重跑零副作用；新写入按构造成立，名字域不再退化。
- **负向**：存量条目的名字会变（`general_tool` → `general_tool_synth_0001` 一类），
  历史会话/文档里引用旧名字的地方需按身份（`skill_id`）重新取；这是"名字不是身份"
  的代价，且本来就应该按身份引用。迁移只改名字，`id`/血缘/账本不动，故回滚点清晰。
- **未验证**：真实生产库上的迁移读数（本检出环境没有 `data/agents/*/skills/manifest.json`），
  需在有生产库的机器上跑 `python scripts/diagnostics/skill_name_collisions.py --apply` 复核。

## References

- 实现：`neurova/skills/skill_name_domain.py`、`neurova/skills/skill_service.py`
  （`migrateNameDomain` / `_claimNameForNewEntry`）、`scripts/diagnostics/skill_name_collisions.py`
- 守卫：`tests/unit/skills/test_skill_name_domain_migration.py`
- 相关 ADR：[0017 技能注册表键值域统一](./0017-skill-registry-key-domain.md)、
  [0019 技能视图键域收口](./0019-skill-view-key-domain.md)
