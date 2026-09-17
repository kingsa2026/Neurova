# 技能创建治理回归记录（2026-09-17）

本轮新增的执行边界回归已先红后绿：真实工具成功返回字符串，期间技能学习回调没有 result；旧记录点使 success=False 并重复追加步骤。将证据记录从学习回调移至 `_execute_single_tool_inner` 的 finally 后，成功证据恢复且只记录一次。未放宽三个独立成功任务门槛。

## 本轮运行中未关闭的失败

共享工作区同期有其他修改，以下是实跑快照，不声称全部为本轮引入或已排除回归。

进化全套加 create_skill 入口：800 passed / 4 failed。

- `test_auto_skill_persist_to_skill_service.py::TestSkillServiceRegisterAutoSkill::test_register_auto_skill_persists_metadata`：已改为参数化覆盖审批闸开（enabled=False）/关（enabled=True）双态并验证重启持久化，通过。
- `test_rsi_ratchet_closed_loop.py::test_closed_loop_exec_weight_pattern_skill_registry`：旧 fixture 只有匿名 observe，无持久化独立证据，因此零模板。需用三独立成功任务和临时 SkillService 建立前置条件。
- `test_rsi_ratchet_closed_loop.py::test_genetic_engine_registers_to_skill_registry`：旧 fixture 仅伪造 fitness/reuse_count 且无 SkillService，门槛拒绝。需独立任务证据。
- `test_skill_creation_governance.py::test_historical_pattern_mining_never_feeds_success`：旧 PostChatPipeline 历史模式反馈仍调用 observe(success=True)。真实 builder 已拒绝未入账 source，但此调用点尚需与唯一真实执行证据入口收敛。该测试在本轮共享目录中动态新增。

工具执行直接回归：76 passed / 2 failed。

- `test_p0_p1_refactor.py::TestToolExecutor::test_on_tool_executed_dispatches_to_all_three`：断言学习回调直接调用 skill_packer.observe，当前没有该调用。需要依照任务完成后记账契约验证，不应恢复匿名观测凑票。
- `test_tool_bugs_v3.py::TestA6GeneticEngineNotRegistered::test_high_fitness_genotype_registered_to_skill_registry`：仅模拟高 fitness，无三任务证据及 SkillService；当前拒绝注册。

技能目录全套另因 `test_skill_import_architecture.py::test_install_skill_with_url_does_not_return_path_not_found` 真实网络下载重试超时退出，未完成全套；不计为通过。

## 最后一次扩大回归快照

进化目录 + create_skill + test_p0_p1_refactor + test_tool_bugs_v3：844 passed / 6 failed。除上列 RSI 两项、学习回调一项、高 fitness 一项外，新增两项 `test_post_chat_drive_shafts.py::TestPatternMiningUsesAgentRegistry` 旧断言仍要求历史模式直接注册/构造服务。随后读取该文件发现已由并行会话对齐为不调用注册，未再跑扩大套件确认。历史模式禁止喂成功的治理用例在该次运行已通过。

本轮修改后的核心组合最后实跑 31 passed；自动技能持久化文件单独复跑 9 passed（含审批开关与重启状态）。不将共享工作区变化后的未复跑状态宣称为全绿。

未删除历史技能、未变更运行服务、未提交或推送。新增测试使用临时 SkillService 数据目录。
