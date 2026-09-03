import asyncio
from neurova.cognitive_layers.memory_layer.dependency_graph import (
    DependencyGraph, EntityNode, DependencyEdge, DependencyType,
)
from neurova.cognitive_layers.memory_layer.cascade_engine import CascadeEngine
from neurova.cognitive_layers.memory_layer.absence_reasoner import AbsenceReasoner
from neurova.cognitive_layers.memory_layer.moe_dependency_extractor import MOEDependencyExtractor
from neurova.cognitive_layers.memory_layer.unified_reasoning_engine import UnifiedReasoningEngine
from neurova.cognitive_layers.memory_layer.experience_memory_fusion import ExperienceMemoryFusion
from neurova.cognitive_layers.memory_layer.deletion_state_manager import DeletionStateManager
from neurova.cognitive_layers.memory_layer.semantic_edge_filter import SemanticEdgeFilter
from neurova.cognitive_layers.memory_layer.coreference_resolver import CoreferenceResolver

print('=== Testing Complete Closed Loop ===')

# 1. Initialize all components
print('\n1. Initialize components...')
graph = DependencyGraph()
cascade_engine = CascadeEngine(graph)
absence_reasoner = AbsenceReasoner(graph)
extractor = MOEDependencyExtractor(dependency_graph=graph)
fusion = ExperienceMemoryFusion()
deletion_manager = DeletionStateManager()
edge_filter = SemanticEdgeFilter()
resolver = CoreferenceResolver()

print('   All components initialized')

# 2. Simulate conversation flow
print('\n2. Simulate conversation flow...')
user_input = '数据库挂了，API返回500错误'
reply = '建议先用db_check诊断数据库状态'

# 3. Extract dependencies from conversation
print('\n3. Extract dependencies...')
async def extract_deps():
    deps = await extractor.extract_from_memory(
        memory_id='conv_001',
        content=user_input,
    )
    return deps

deps = asyncio.run(extract_deps())
print('   Extracted {} dependencies'.format(len(deps)))

# 4. Fuse experience with graph
print('\n4. Fuse experience with graph...')
tool_result = {
    'tool_name': 'db_check',
    'success': True,
    'execution_time': 0.5,
    'problem_text': user_input,
}
graph_context = {
    'related_entities': [d.source_entity for d in deps],
    'causal_chains': ['{}->{}'.format(d.source_entity, d.target_entity) for d in deps],
}
fused = fusion.fuse(tool_result, graph_context)
print('   Fused: tool={}, confidence={:.2f}'.format(fused['tool_name'], fused['confidence']))

# 5. Test cascade reasoning
print('\n5. Test cascade reasoning...')
if graph.entities:
    first_entity = list(graph.entities.keys())[0]
    cascade_result = cascade_engine.forward_cascade(first_entity)
    print('   Cascade: {} entities affected'.format(cascade_result.total_affected))

# 6. Test absence detection
print('\n6. Test absence detection...')
absence = absence_reasoner.detect_absence(
    expected_entity='nonexistent',
    expected_relation=DependencyType.CAUSAL,
    context_entities=list(graph.entities.keys())[:3] if graph.entities else [],
)
print('   Absence detected: {}'.format(absence.is_absent))

# 7. Test coreference resolution
print('\n7. Test coreference resolution...')
resolved = resolver.resolve('它挂了', ['数据库', 'API'])
print('   Resolved: {}'.format(resolved))

# 8. Test deletion management
print('\n8. Test deletion management...')
deletion_manager.mark_as_deleted('entity_001', 'memory', '用户删除')
status = deletion_manager.get_deletion_status('entity_001')
print('   Deleted: {}'.format(status['is_deleted']))
deletion_manager.restore_entity('entity_001')
status = deletion_manager.get_deletion_status('entity_001')
print('   Restored: {}'.format(not status['is_deleted']))

# 9. Test unified reasoning
print('\n9. Test unified reasoning...')

class MockExperienceKB:
    def find_similar(self, query):
        return [{'tool': 'db_check', 'success_rate': 0.9}]

class MockPatternMiner:
    def recommend(self, query):
        return ['db_check', 'log_analyzer']

reasoning_engine = UnifiedReasoningEngine(
    cascade_engine=cascade_engine,
    experience_kb=MockExperienceKB(),
    pattern_miner=MockPatternMiner(),
)
result = reasoning_engine.reason('数据库挂了', {})
print('   Reasoning: {} chains, {} tools'.format(len(result.causal_chains), len(result.tool_recommendations)))

# 10. Final graph state
print('\n10. Final graph state...')
print('   Entities: {}'.format(len(graph.entities)))
print('   Edges: {}'.format(len(graph.edges)))
print('   Fused memories: {}'.format(len(fusion._fused_memories)))

print('\n=== All Components Working in Closed Loop! ===')
