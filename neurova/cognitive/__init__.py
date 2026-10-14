"""
Cognitive Module - 认知模块

本包只剩 ADR-0001 的重导出点：`Memory` 从记忆层真源取回，供历史 import 路径继续可用
（钉住它的是 tests/unit/cognitive_layers/memory_layer/test_memory_dataclass_unification.py）。

此前的「认知编排器」orchestrator.py 已退役。它对外自称三件事——代理注册表、
任务流水线、任务三态落盘——但 orchestrate() 给流水线里每一步直接写 "completed"，
从不派发任何 handler，也没有 handler 可派发；注册进去的 agent 记录无人读取。
这三格在服务请求的那条路上都有在位实现：
- 团队 Agent 注册表：collaboration/neurflow/agent_manager.py（含 capabilities 字段）
- 任务流水线：collaboration/neurflow/execution_engine.py 的 _execute_node，真 await
  注册表解析出的节点执行器，解析不到即失败而非假成功
- 执行态落盘：collaboration/neurflow/storage.py 的 save_execution / get_execution
判据：tests/unit/cognitive/test_taskPipelineSingleSourceIsLive.py（活路面 + 退役面 + 反向断言）。

永久失去：注意力记录与本模块自带记忆的 JSON 落盘——两者全仓零消费者，
记忆的唯一真源是 cognitive_layers/memory_layer/。
"""



from neurova.cognitive_layers.memory_layer.models import Memory

# `Memory` 是本包唯一对外供给的名字，取法是属性形（`import neurova.cognitive as cog; cog.Memory`，
# 见 tests/unit/cognitive_layers/memory_layer/test_memory_dataclass_unification.py:58-65）——
# 按 `from … import …` 一种形状去数消费者会把它读成零消费者（§6-212 实测的第三种偏法）。
__all__ = ["Memory"]
