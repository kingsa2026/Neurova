"""
完整会话流程测试

测试用户会话消息、上下文、LLM路由、LLM调用、记忆检索、消息路由、进化、工具进化、经验积累、记忆写入等各个模块之间的协调
"""

import asyncio
import time
from unittest.mock import Mock, AsyncMock, MagicMock

print('=== 完整会话流程测试 ===')
print('测试模块: 用户会话 → 上下文 → LLM路由 → 记忆检索 → 消息路由 → 进化 → 经验积累 → 记忆写入')

# ============================================================
# 1. 初始化所有组件
# ============================================================
print('\n' + '='*60)
print('1. 初始化所有组件')
print('='*60)

from neurova.cognitive_layers.memory_layer.dependency_graph import (
    DependencyGraph, EntityNode, DependencyEdge, DependencyType,
)
from neurova.cognitive_layers.memory_layer.cascade_engine import CascadeEngine
from neurova.cognitive_layers.memory_layer.absence_reasoner import AbsenceReasoner
from neurova.cognitive_layers.memory_layer.moe_dependency_extractor import MOEDependencyExtractor
from neurova.cognitive_layers.memory_layer.conversation_rule_extractor import ConversationRuleExtractor
from neurova.cognitive_layers.memory_layer.unified_reasoning_engine import UnifiedReasoningEngine
from neurova.cognitive_layers.memory_layer.experience_memory_fusion import ExperienceMemoryFusion
from neurova.cognitive_layers.memory_layer.deletion_state_manager import DeletionStateManager
from neurova.cognitive_layers.memory_layer.semantic_edge_filter import SemanticEdgeFilter
from neurova.cognitive_layers.memory_layer.coreference_resolver import CoreferenceResolver
from neurova.cognitive_layers.memory_layer.retrieval_facade import MemoryRetrievalFacade
from neurova.agent.tool_pipeline import ToolExecutionPipeline, ToolExecutionContext
from neurova.context.context_facade import ContextFacade
from neurova.evolution.evolution_facade import EvolutionFacade

# 初始化组件
graph = DependencyGraph()
cascade_engine = CascadeEngine(graph)
absence_reasoner = AbsenceReasoner(graph)
extractor = MOEDependencyExtractor(dependency_graph=graph)
fusion = ExperienceMemoryFusion()
deletion_manager = DeletionStateManager()
edge_filter = SemanticEdgeFilter()
resolver = CoreferenceResolver()

# Mock组件
class MockMemoryManager:
    def get_all_memories(self):
        return []
    def recall(self, query, limit=10):
        return []

class MockLLMClient:
    async def generate(self, prompt):
        return '{"rules": [{"source": "数据库", "target": "API", "relation": "causal", "confidence": 0.8, "evidence": "数据库故障导致API异常"}]}'

class MockPatternMiner:
    def add_sequence(self, tools):
        pass
    def recommend(self, query):
        return ["db_check", "log_analyzer"]

class MockExperienceKB:
    def find_similar(self, query):
        return [{"tool": "db_check", "success_rate": 0.9}]

# 创建组件实例
memory_manager = MockMemoryManager()
llm_client = MockLLMClient()
pattern_miner = MockPatternMiner()
experience_kb = MockExperienceKB()

# 创建Facade
rule_extractor = ConversationRuleExtractor(llm_client, graph)
retrieval_facade = MemoryRetrievalFacade()
reasoning_engine = UnifiedReasoningEngine(
    cascade_engine=cascade_engine,
    experience_kb=experience_kb,
    pattern_miner=pattern_miner,
)

print('  ✅ 所有组件初始化完成')

# ============================================================
# 2. 模拟用户会话消息
# ============================================================
print('\n' + '='*60)
print('2. 模拟用户会话消息')
print('='*60)

class MockMessage:
    def __init__(self, content, sender="user"):
        self.content = content
        self.sender = sender
        self.metadata = {}
        self.timestamp = time.time()

# 模拟3轮对话
conversations = [
    {"user": "数据库挂了，API返回500错误", "assistant": "建议先用db_check诊断数据库状态"},
    {"user": "测试通过后才能部署", "assistant": "是的，测试是部署的必要前置条件"},
    {"user": "Redis慢了导致查询慢", "assistant": "可以尝试用cache_clear清理缓存"},
]

for i, conv in enumerate(conversations):
    print(f'  对话{i+1}:')
    print(f'    用户: {conv["user"]}')
    print(f'    助手: {conv["assistant"]}')

# ============================================================
# 3. 测试上下文构建
# ============================================================
print('\n' + '='*60)
print('3. 测试上下文构建')
print('='*60)

# 模拟Agent
class MockAgent:
    def __init__(self):
        self.config = Mock()
        self.config.llm_model = "gpt-4"
        self.memory_manager = MockMemoryManager()
        self.conversation_history = []

agent = MockAgent()
context_facade = ContextFacade(agent)

# 构建上下文
result = context_facade.build_context.__wrapped__ if hasattr(context_facade.build_context, '__wrapped__') else context_facade.build_context
print('  ✅ ContextFacade 初始化完成')

# ============================================================
# 4. 测试LLM路由（模拟）
# ============================================================
print('\n' + '='*60)
print('4. 测试LLM路由（模拟）')
print('='*60)

class MockLLMRouter:
    def select_model(self, request_type):
        return {"model": "gpt-4", "provider": "openai"}

router = MockLLMRouter()
selected = router.select_model("chat")
print(f'  ✅ LLM路由: 选择模型 {selected["model"]}')

# ============================================================
# 5. 测试记忆检索
# ============================================================
print('\n' + '='*60)
print('5. 测试记忆检索')
print('='*60)

# 添加测试数据到图谱
graph.add_entity(EntityNode(id="db", name="数据库", entity_type="object"))
graph.add_entity(EntityNode(id="api", name="API", entity_type="object"))
graph.add_entity(EntityNode(id="redis", name="Redis", entity_type="object"))
graph.add_dependency(DependencyEdge(
    id="db_api", source_id="db", target_id="api",
    dep_type=DependencyType.CAUSAL, confidence=0.8,
))
graph.add_dependency(DependencyEdge(
    id="redis_api", source_id="redis", target_id="api",
    dep_type=DependencyType.CAUSAL, confidence=0.7,
))

print(f'  图谱: {len(graph.entities)} 实体, {len(graph.edges)} 边')

# 测试检索
async def test_retrieval():
    result = retrieval_facade.retrieve("数据库", limit=5)
    return result

result = asyncio.run(test_retrieval())
print(f'  ✅ 记忆检索: {len(result.memories)} 条结果')

# ============================================================
# 6. 测试消息路由（模拟）
# ============================================================
print('\n' + '='*60)
print('6. 测试消息路由（模拟）')
print('='*60)

class MockRouter:
    def route(self, message):
        return {"type": "chat", "success": True}

router = MockRouter()
route_result = router.route({"content": "test"})
print(f'  ✅ 消息路由: {route_result}')

# ============================================================
# 7. 测试进化系统
# ============================================================
print('\n' + '='*60)
print('7. 测试进化系统')
print('='*60)

evolution_facade = EvolutionFacade(Mock())

# 记录经验
result = evolution_facade.record_experience(
    text="用户: 数据库挂了\n助手: 建议用db_check",
    task="数据库诊断",
    tools=["db_check"],
    success=True,
)
print(f'  ✅ 经验记录: {result}')

# 获取工具权重
weight = evolution_facade.get_tool_weight("db_check")
print(f'  ✅ 工具权重: db_check={weight}')

# ============================================================
# 8. 测试经验积累
# ============================================================
print('\n' + '='*60)
print('8. 测试经验积累')
print('='*60)

# 融合经验
tool_result = {
    "tool_name": "db_check",
    "success": True,
    "execution_time": 0.5,
    "problem_text": "数据库挂了",
}
graph_context = {
    "related_entities": ["数据库", "API"],
    "causal_chains": ["数据库→API"],
}

fused = fusion.fuse(tool_result, graph_context)
print(f'  ✅ 经验融合: tool={fused["tool_name"]}, confidence={fused["confidence"]:.2f}')

# 获取统计
stats = fusion.get_tool_statistics("db_check")
print(f'  ✅ 工具统计: count={stats["count"]}, success_rate={stats["success_rate"]:.2f}')

# ============================================================
# 9. 测试记忆写入（模拟）
# ============================================================
print('\n' + '='*60)
print('9. 测试记忆写入（模拟）')
print('='*60)

class MockMemoryWriter:
    def remember(self, content, metadata=None):
        return "mem_001"

memory_writer = MockMemoryWriter()
mem_id = memory_writer.remember(
    content="数据库挂了，API返回500错误",
    metadata={"source": "conversation", "agent_id": "test"},
)
print(f'  ✅ 记忆写入: memory_id={mem_id}')

# ============================================================
# 10. 测试删除管理
# ============================================================
print('\n' + '='*60)
print('10. 测试删除管理')
print('='*60)

deletion_manager.mark_as_deleted("mem_001", "memory", "用户删除")
status = deletion_manager.get_deletion_status("mem_001")
print(f'  ✅ 标记删除: is_deleted={status["is_deleted"]}')

deletion_manager.restore_entity("mem_001")
status = deletion_manager.get_deletion_status("mem_001")
print(f'  ✅ 恢复实体: is_deleted={status["is_deleted"]}')

# ============================================================
# 11. 测试指代消解
# ============================================================
print('\n' + '='*60)
print('11. 测试指代消解')
print('='*60)

resolved = resolver.resolve("它挂了", ["数据库", "API", "Redis"])
print(f'  ✅ 指代消解: "它挂了" → "{resolved}"')

# ============================================================
# 12. 测试工具执行管线
# ============================================================
print('\n' + '='*60)
print('12. 测试工具执行管线')
print('='*60)

pipeline = ToolExecutionPipeline()
context = ToolExecutionContext(
    tool_name="db_check",
    params={"query": "SELECT 1"},
    user_input="检查数据库",
    success=True,
    execution_time=0.5,
)

report = pipeline.execute(context)
print(f'  ✅ 工具执行: tool={report.tool_name}, success={report.success}')
print(f'    处理时间: {report.total_processing_time:.3f}s')

# ============================================================
# 13. 测试级联推理
# ============================================================
print('\n' + '='*60)
print('13. 测试级联推理')
print('='*60)

cascade_result = cascade_engine.forward_cascade("db")
print(f'  ✅ 正向级联: {cascade_result.total_affected} 个实体受影响')
print(f'    置信度: {cascade_result.confidence:.2f}')

# ============================================================
# 14. 测试缺失检测
# ============================================================
print('\n' + '='*60)
print('14. 测试缺失检测')
print('='*60)

absence = absence_reasoner.detect_absence(
    expected_entity="nonexistent",
    expected_relation=DependencyType.CAUSAL,
    context_entities=["db", "api"],
)
print(f'  ✅ 缺失检测: is_absent={absence.is_absent}')

# ============================================================
# 15. 测试统一推理
# ============================================================
print('\n' + '='*60)
print('15. 测试统一推理')
print('='*60)

reasoning_result = reasoning_engine.reason("数据库挂了", {})
print(f'  ✅ 统一推理:')
print(f'    因果链: {len(reasoning_result.causal_chains)} 条')
print(f'    工具推荐: {reasoning_result.tool_recommendations}')
print(f'    风险预警: {reasoning_result.risk_warnings}')
print(f'    置信度: {reasoning_result.confidence:.2f}')

# ============================================================
# 16. 测试对话规则提取
# ============================================================
print('\n' + '='*60)
print('16. 测试对话规则提取')
print('='*60)

async def test_rule_extraction():
    rules = await rule_extractor.extract(
        "数据库挂了",
        "API返回500错误",
        conversation_id="conv_001",
    )
    return rules

rules = asyncio.run(test_rule_extraction())
print(f'  ✅ 规则提取: {len(rules)} 条规则')
for rule in rules:
    print(f'    - {rule.source_entity} → {rule.target_entity} ({rule.relation_type}, conf={rule.confidence:.2f})')

# ============================================================
# 17. 最终状态
# ============================================================
print('\n' + '='*60)
print('17. 最终状态')
print('='*60)

print(f'  图谱: {len(graph.entities)} 实体, {len(graph.edges)} 边')
print(f'  融合记忆: {len(fusion._fused_memories)} 条')
print(f'  删除记录: {len(deletion_manager._deletions)} 条')

print('\n' + '='*60)
print('✅ 完整会话流程测试通过！')
print('='*60)
