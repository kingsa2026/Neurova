import asyncio
from neurova.cognitive_layers.memory_layer.dependency_graph import (
    DependencyGraph, EntityNode, DependencyEdge, DependencyType,
)

print('=== Testing NEURON Components ===')

# 1. Test DependencyGraph
print('\n1. Testing DependencyGraph...')
graph = DependencyGraph()
graph.add_entity(EntityNode(id='server', name='服务器', entity_type='object'))
graph.add_entity(EntityNode(id='database', name='数据库', entity_type='object'))
graph.add_entity(EntityNode(id='api', name='API', entity_type='object'))
graph.add_dependency(DependencyEdge(
    id='server_db', source_id='server', target_id='database',
    dep_type=DependencyType.PREREQUISITE,
))
graph.add_dependency(DependencyEdge(
    id='server_api', source_id='server', target_id='api',
    dep_type=DependencyType.CAUSAL,
))
print(f'  Entities: {len(graph.entities)}')
print(f'  Edges: {len(graph.edges)}')
downstream = graph.get_downstream('server')
print(f'  Downstream(server): {downstream}')

# 2. Test CascadeEngine
print('\n2. Testing CascadeEngine...')
from neurova.cognitive_layers.memory_layer.cascade_engine import CascadeEngine
engine = CascadeEngine(graph)
result = engine.forward_cascade('server')
print(f'  Forward cascade: {result.total_affected} entities affected')
print(f'  Confidence: {result.confidence:.2f}')

# 3. Test AbsenceReasoner
print('\n3. Testing AbsenceReasoner...')
from neurova.cognitive_layers.memory_layer.absence_reasoner import AbsenceReasoner
reasoner = AbsenceReasoner(graph)
absence = reasoner.detect_absence(
    expected_entity='nonexistent',
    expected_relation=DependencyType.CAUSAL,
    context_entities=['server', 'database'],
)
print(f'  Is absent: {absence.is_absent}')
print(f'  Entity exists: {absence.entity_exists}')
print(f'  Explanation: {absence.explanation}')

# 4. Test MOEDependencyExtractor
print('\n4. Testing MOEDependencyExtractor...')
from neurova.cognitive_layers.memory_layer.moe_dependency_extractor import MOEDependencyExtractor
extractor = MOEDependencyExtractor()

async def test_extract():
    deps = await extractor.extract_from_memory(
        memory_id='test_001',
        content='部署服务器需要先安装数据库，然后配置API接口',
    )
    return deps

deps = asyncio.run(test_extract())
print(f'  Dependencies extracted: {len(deps)}')
for dep in deps:
    print(f'    - {dep.source_entity["name"]} -> {dep.target_entity["name"]} ({dep.dep_type.value})')

print('\n=== All Tests Passed! ===')
