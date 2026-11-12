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
