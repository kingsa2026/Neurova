# SkillGLoW 与 Neurova 技能沉淀机制对比(2026-10-07)

> **性质声明**:本文属 INDEX.md §2.4「竞品/外部对标」——**研究参考,仅作背景,不可作为本仓设计的事实源或对齐依据**(AGENTS.md 协作红线)。文中"借鉴点"若落地,一律按本仓修复教义独立立项(先红后绿),本文不构成对齐承诺。
>
> **对比对象**:Yan, Zhang, Du, Zhou,《SkillGLoW: Procedural-Family Skill Consolidation for Self-Improving Agents on Long-Horizon Task Streams》,arXiv:2609.02217 v1(2026-09-02)。
> **方法**:论文方法细节取自 arXiv HTML 全文(v1);Neurova 侧为工作树实测(2026-10-07),证据一律 `文件:行号`。
> **阅读对象**:技能域(skill_consolidator / skill_lifecycle / creation_governance / skill_experience)维护者。

---

## 0. 结论摘要

- SkillGLoW 的核心洞察打在 Neurova 技能域一个真实空白上:Neurova 有"同族**识别与收编**"(`skill_consolidator` 按工具序列聚簇、umbrella 吸收其余归档),没有"**去实例化泛化**"——合并只选质量最高的既有成员,不生成更通用的正文,被吸收技能的经验账本不迁移(umbrella 冷启动重新学习)。
- 其 commit gate(V ≥ max(现役库, 无技能基线) − ε)与 Neurova 的 gain 门/噪声地板/回滚体系**同构**,属互相印证;真正可搬的是三件:吸收时账本迁移与教训回流、整合计划的召回预检、去实例化压缩纪律。
- **治理决策(2026-10-07,用户指令)**:整合审批引入**全自动 commit gate 替代人工审批**——确定性多检 fail-closed(任一检不过仍留人工),治理开关 `consolidation_auto_commit_enabled` 默认开,审计与回滚路径齐全。此为对"改行为默认待审"哲学的一次**显式规则修订**(无例外条款:以改规则为准),修订理由:整合动作 = 归档可逆 + 预检确定性 + 全程留痕,风险量级低于新技能生成(后者维持评审闸不变)。

## 1. 论文一页纸

**问题**:技能库组织两难——全局单文档在异构任务流上塌缩成泛泛纪律;per-task 池膨胀且条目绑死实例。缺失的复用单元 = 一族相关任务共享的解题过程。

**方法**:
1. **局部技能**:从任务自身执行反馈(相邻轨迹差 Δτ + 验证分)提炼 ≤80 词技能卡,提取提示强制去实例化("不得含任务特定文件路径/测试常数/验证器输出"),不直接入库;
2. **族聚类**:五视图编码(签名×2/指令/轨迹/全文,权重 0.30/0.20/0.20/0.20/0.10)+ 九份层次聚类共识 + Kneedle 自动定 K + LLM 成对判"同一可复用过程";**每轮从当前证据全量重推**,坏分组不向前携带;
3. **压缩成先验**:一族任务技能蒸馏为一个去实例化先验,只保留**适用条件 + 核心过程 + 常见失败模式**(实测例:989 词带记忆化表的局部技能 → 440 词四步,表被剥除);
4. **测试期再生**:全局先验常驻 + 语义 top-1 召回族先验(阈值 0.45,低于即 fail-closed),实例细节**用的时候现场再生**,不存储;
5. **commit gate**:先验价值 V 只用先验测(局部技能不参与,信用可归因),提交判据 `V ≥ max(V⋆, V_ns) − ε`,ε=0.02 按实测噪声 s.d. 2.71pp 校准;拒绝即回滚,锚定前一轮最优。

**成绩**:四基准三模型 12 组连续运行全部正增益(冻结先验 +17.2 hard / 带再生 +18.0);库紧凑 3.6×;零样本迁移 73.9→83.9%;gate 使终轮库分 +14.7 vs 无条件准入 +9.6。**自认失败模式**:8 任务大族"修好一个弄坏另一个,零净收益"——族质量是概率性的;压缩可能"放宽规则或丢约束"(故有 gate)。

## 2. Neurova 侧对位部件(实测)

- **同族识别**:`sequence_family`(族键=工具名序列,`skill_consolidator.py:112-126`)+ `find_structural_clusters`(`:129-186`,basis=identity/structure/name_prefix 三级)+ `cross_intent` 标注(`:59-61`)——"同一过程族的不同业务变体"在 basis="structure" 的簇里已可观测;
- **合并执行**:`ConsolidationApproval.approve`(`:452-479`)= 逐个 `archive_skill`(归档可逆、永不删除),umbrella 保留;**绝不生成新正文**(`:456-458`);
- **审批面**:计划由 post-chat 每轮产出 upsert(`post_chat_pipeline.py:2874-2888`),人工经 `/consolidation/{umbrella}/approve|reject`(`skill_pool_api.py:712-789`)决策;
- **生命周期**:active→stale(14d)→archived(30d) 确定性扫描(`skill_lifecycle.py:32-38`);淘汰双门槛(`skill_experience.py:44-45`);增益剪枝三证合取(`evolution_yield_prune.py:28-83`);
- **检索/冷却**:关键词+语义 floor 选入(`skill_injection.py:246-304`)、质量熔断(`:237-243`)、EKB 采纳调权(`experience_knowledge_base.py:772-806`)、结晶温度冷档(`pattern_crystallizer.py:372-378, 550-575`)。

## 3. 逐维判定

| 维度 | SkillGLoW | Neurova | 判定 |
|---|---|---|---|
| 复用单元 | 每过程族一个去实例化先验;实例细节按需再生 | 每技能一条目;consolidator 只识别+收编,不泛化 | 对方有,我方无 |
| 族形成 | 五视图嵌入+共识聚类+LLM 成对判,每轮重推 | 确定性零 LLM 工具序列族;语义不参与聚簇 | 各有理:对方抓语义同族,我方零误杀;"不同序列同目的"的语义同义重复我方无判据 |
| 入库门 | 自动 ε-gate(V ≥ max(现役, 无技能)−ε),拒绝即回滚 | holdout+噪声地板+bench 门+泄漏门+人工主 gate+部署阶段门 | 互相印证;我方多层更严,缺"无技能锚/历史最优锚" |
| 信用归因 | V 只用先验测 | 漏斗账"兜底完成不计功"、success 三态 | 我方已有,同构 |
| 库规模 | 保持性从整合中涌现,\|G\| 随过程数 | 生命周期+淘汰+增益剪枝;`.archive/` 无界;计划仓溢出静默截断 | 我方机制更全但有账目瑕疵 |
| 退役知识 | 实例细节不存储,无需回收 | 被吸收技能的经验/usage/trust 不迁移,umbrella 冷启动 | 对方思路揭示我方断点 |

## 4. 落地项(2026-10-07 实施)

| # | 项 | 落点 | 状态 |
|---|---|---|---|
| P1-1 | 吸收时账本迁移:被吸收技能的 applied 经验重键到 umbrella;吸收来源审计注记 | `skill_consolidator.ConsolidationApproval` + `skill_experience` | 本轮 |
| P1-2 | 整合计划召回预检 + **全自动 commit gate**(治理开关默认开,fail-closed 多检) | `skill_consolidator` + `skill_injection.routing_sanity_check` + `governance_settings` | 本轮 |
| P1-3 | 去实例化压缩纪律:结晶 LLM 裁决与经验重建提示词增加"适用条件+核心过程+失败模式,剥除任务特定常数"判据 | `pattern_crystallizer.review_pending_with_llm` + `skill_experience` 组合路径 | 本轮 |
| P2-5 | `ConsolidationPlanStore` 溢出留痕计数(对齐工单 016 口径) | 同文件 | 本轮 |
| P2-4 | 文本进化接受阈值加无技能锚/历史最优锚(A = max(V⋆, V_ns) − ε) | `eval/runner` accept_threshold 组装处 | 登记 |
| P3 | 语义族第二计划源(嵌入多视图+LLM 成对判,只产计划进审批) | consolidator 第二来源 | 登记 |
| — | 规则修订登记 | 本文 §0 + `skill_consolidator` 模块文档 + `skill_review_gate` 覆盖清单注记 | 本轮 |

**明确不引入**:每轮全量重推库(基准循环专属,生产常驻不可负担且毁审计链);全自动 gate 推广到新技能生成(评审闸维持);fail-closed 检索替代"零命中回退全量"(两域各自适配)。

## 附录 A. 证据索引

- 论文:arXiv:2609.02217v1(abs + HTML 全文,2026-10-07 抓取);
- Neurova:上表落点文件实测行号见正文各节(实施后以各提交 diff 为准);
- 实施提交:见仓库 log(2026-10-07,feat(evolution) 系列)。
