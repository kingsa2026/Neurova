# P1-10 三层隔离复核（2026-11-12，随断点审计修复批）

审计 P1-10 断言"聊天主链 L2/L3 恒 default、跨人串忆"。逐点复核结论：**主链身份绑定与写路径盖章已在位（票 B 语义已由并发批实现），剩余待证面收窄到两路检索引擎的 SQL 级过滤实证**。引用的票据文档 `docs/05-reports/三层隔离执行面审计_2026-09-24.md` 在仓内缺失，票 A 的验收判据（R1/R2/R3）无从对照——先登记复核证据，实施前需补票据或按本复核继续。

## 已证在位（票 B 语义）

1. **渠道路由每回合注入真发送者作用域**：`channels/channel_router.py:290-292` 在 `set_request_user_id(turnIdentity["user_id"])`（§6-163 唯一身份通道）之后，同回合 `memoryManager.set_request_scope(neuser_id=turnIdentity["neuser_id"], user_id=turnIdentity["user_id"])`——渠道 sender→neuser 绑定即此；未绑定降级语义由 turnIdentity 的解析侧承担。
2. **API 面同一机制**：`api/deps.py:124-125`（get_memory_manager 按请求身份注入）、`api/endpoints/memory/base.py:274-277`（记忆端点同型）。
3. **作用域机制本体**：`manager.py:88-100` 请求级 ContextVar（`_scope_var`）＋ `(agent_id, neuser_id, user_id, db_path)` 作用域注册表（2026-09-02 根因修复）；`set_request_scope/clear_request_scope/request_scope` 三件套（:1302-1321）；`_eff_neuser_id/_eff_user_id`（:1323-1330）生效读数；`memoryScope()`（:643-649）自述"作用域口径只在这里"。
4. **写路径盖章单源**：`cognitive_storage_engine.py:389-395` flush 时 `neuserId, userId = self._memory.memoryScope()` 给每条正文行盖章（注释明言"读侧按生效三元组过滤——写进去就再也读不回来"）。
5. agent_core `_init_memory_modules` 的 `"default"` 形参只是**实例缺省**（agent 级第 1 层），请求级作用域每回合覆盖它——审计把初始化缺省误读成了运行时恒 default。

## 待证面（票 A 残留）

- `agent/retriever_adapters.py` 与 `unified_retriever.py` 确实不出现 neuser 字样（审计此条属实），但适配器→引擎→manager.memoryScope() 是**间接**生效链，静态 grep 零命中不等于不过滤；
- **MoE 路由（moe_router.py）与 recall_flat（neurova_recall.py:869）两路无 neuser/scope 字样**——其取数若不经 manager 作用域过滤即存在跨人召回面，需逐引擎做到 SQL 级核验（缺票据判据）；
- `storage.py:378/395` share_group_ids 只写不读（共享组可见性未实现）属实，属票 A 的共享组半张。

## 处置建议

补建（或从 git 历史找回）三层隔离执行面审计文档，按上面已证/待证清单继续票 A：先做 MoE 与 recall_flat 两路的 SQL 级核验（有过滤即闭票，无过滤则把 `manager.memoryScope()` 透传进两路取数），共享组可见性另票。

## 票 A 实施结果（2026-11-12 续，用户拍板"现在开工"后）

- **黑盒验收红**：`tests/unit/memory/test_recall_scope_isolation.py` 实测泄漏读路=['recall_flat']——用户 B 作用域经 recall_flat 召回用户 A 私有记忆；manager.recall / storage_engine.retrieve / unified_retriever.retrieve 三路实测不漏。
- **修复一（`fix(memory)` 召回面）**：`get_all_memories` 增 scoped 形参（True=请求面按生效 (neuser,user) 过滤；False=系统面全量，睡眠整合/关机持久化等缺省不变）；六个内建召回通道与 neurova_recall 两处召回取数切 scoped=True。通道单测 Mock 签名对齐。
- **修复二（`fix(memory)` MoE 支路）**：mem_core 的 MoE 索引 SELECT 补 neuser_id/user_id 身份列；MoEMemoryRouter 增 scope_resolver（装配接 memory_manager.memoryScope 单源），retrieve 在专家下钻后与向量兜底后各过一道 _scopeFilter，无身份标记的结果按拒绝处理（fail-closed）。
- **验收**：隔离五格全过（B 不漏 A／本人不丢／缺省桶两用户行均不可见）；memory 全族 1212 passed（2 失败=crystallization_llm_gate 在册预存红）。
- **share_group_ids（storage.py:378/395 只写不读）处置**：全仓无任何生产代码向 IsolationContext 填 share_group_ids（仅 isolation.py 自身 docstring 示例）——休眠特性，无数据带非空共享组，读侧忽略**当前无实际影响**。接线（共享组可见性）属新功能工程（需组员关系源＋可见性规则），按"待拍板"登记，不在本批盲做。
- **票据文档缺失**：`docs/05-reports/三层隔离执行面审计_2026-09-24.md` 仓内与 git 全历史均不存在——本复核的黑盒验收即替代判据；后续如需 R1/R2/R3 原文，需从会话存档或原作者处找回。

## 台账正文补登（simplification-audit-2026-10-05.md §6-612 摘要）

612. **P1-10 三层隔离·票 A 召回面/MoE 支路作用域隔离闭合** ✅🟢 —— 修复详见本目录 `simplification-audit-2026-11-12-复核.md` 的"票 A 实施结果"。要点：`get_all_memories(scoped=)` 请求面/系统面分流；六召回通道＋recall 两处取数切 scoped；MoE 索引带身份列＋scope_resolver（memoryScope 单源）＋retrieve 双道过滤（无身份 fail-closed）。黑盒验收：B 作用域召回 A 私有记忆（红）→ 四读路全不漏（绿）；memory 全族 1212 passed。**另票登记**：share_group_ids 共享组可见性（休眠特性，无生产写入方，接线需组员关系源）；semantic_search_api 两处全量取数属 X-Service-Token 另一面（auth.py docstring 在案）。**下一枚空号现查：本格取 612，后继从 613 起。**

## 续批核验结果（2026-11-13，拍板"两项全做/本批核验"后）

### §6-501 裁定② 存量迁移归属——核验结论：文件级迁移在位，行级时间轴归属未实施（维持待核）

- **文件级布局迁移在位**：`core/agent_layout_migration.py`（旧 agent 扁平落点 →
  `data/<agent_id>/` 统一布局，含 `_merge_move`/冲突登记/孤儿防护）——**整库文件**
  搬迁有实装；
- **行级"按时间轴切行归属"未实施**：context_ledger.db 里归属 `default` 的存量行
  按时间轴切归真实 agent 的行级迁移，全仓无实现标记（grep 时间轴/切行/归属零命中）；
- **判据原文**：裁定②的三段走（先只搬不删 → 校验行数一致 → 再决定删）与不可逆点
  （"删老文件"单独点单）见台账 §6-501 原文——行级实施需按该三段设计票另批。

### T-02/T-03 抽查——受阻：双通路审计文档不可定位

`docs/05-reports/` 无双通路审计文档（ls 实证），T-02/T-03 的抽查判据原文无从
对照——与 R1/R2/R3 同因（票据文档缺失）。建议与三层隔离票据一并找回。

### storage.py 共享组读侧——复核推翻审计断言：读侧早已在位

审计 P1-10 称"storage.py:378/395 share_group_ids 只写不读"——**复核不成立**：
- `_passesIsolation`（storage.py:448-468）已实现共享组放行分支（`rec.shared`
  与 `_in_same_share_group` 组交集）；
- `_in_same_share_group`（:672-694）经 `share_group.get_share_group_manager()
  .are_agents_shared(请求者 agent, 记录 agent)` 裁决（组员关系源＝共享组管理器的
  agent 索引）；
- 管理面已挂载：`memory_share_groups.py`（ENDPOINT_MODULES :321，GET/POST/PUT/
  DELETE 组与组员，get_current_user 门）。
审计该断言系误读。真正缺的是主 memories 表路径（本批迁移 v6＋仲裁器＋FTS 已补）。

### 检索链身份形参透传——实装（拍板：两项全做）

四路透传落地：RetrievalContext 增 neuser_id → chat_pipeline 主路构造点从
ctx.metadata.memory_scope 播种 → UnifiedRetrieverAdapter/MoERetrieverAdapter
透传 → UnifiedRetriever/engine.retrieve/searchMemoriesFulltext 增
scope_override 覆盖位（**显式形参是覆盖位，ContextVar 仍是唯一缺省通道**
——不造第二身份通道）；MoEMemoryRouter.retrieve 同型（explicit 优先于
resolver）。验收：隔离族 9 passed。
