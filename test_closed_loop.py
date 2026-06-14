import asyncio
from neurova.cognitive_layers.memory_layer.dependency_graph import (
    DependencyGraph, EntityNode, DependencyEdge, DependencyType,
)
from neurova.cognitive_layers.memory_layer.cascade_engine import CascadeEngine
from neurova.cognitive_layers.memory_layer.absence_reasoner import AbsenceReasoner
from neurova.cognitive_layers.memory_layer.moe_dependency_extractor import MOEDependencyExtractor

print('=== Testing Memory System Closed Loop ===')

# 1. Initialize components
print('\n1. Initialize components...')
graph = DependencyGraph()
cascade_engine = CascadeEngine(graph)
absence_reasoner = AbsenceReasoner(graph)
extractor = MOEDependencyExtractor()
print('   All components initialized')

# 2. Test: Extract dependencies from memory content
print('\n2. Extract dependencies from memory content...')
async def test_extract():
    deps = await extractor.extract_from_memory(
        memory_id='mem_001',
        content='部署服务器需要先安装数据库，然后配置API接口',
    )
    return deps

deps = asyncio.run(test_extract())
print(f'   Extracted {len(deps)} dependencies')

# 3. Check if dependencies are in graph
print('\n3. Check if dependencies are in graph...')
print(f'   Entities in graph: {len(graph.entities)}')
print(f'   Edges in graph: {len(graph.edges)}')

# 4. Test cascade reasoning with extracted data
print('\n4. Test cascade reasoning with extracted data...')
if graph.entities:
    first_entity = list(graph.entities.keys())[0]
    result = cascade_engine.forward_cascade(first_entity)
    print(f'   Forward cascade from "{first_entity}": {result.total_affected} affected')

# 5. Test absence detection
print('\n5. Test absence detection...')
absence = absence_reasoner.detect_absence(
    expected_entity='nonexistent_entity',
    expected_relation=DependencyType.CAUSAL,
    context_entities=list(graph.entities.keys())[:3],
)
print(f'   Absence detected: {absence.is_absent}')
print(f'   Explanation: {absence.explanation}')

# 6. Test: Query graph for related memories
print('\n6. Test graph queries...')
if graph.entities:
    entity_id = list(graph.entities.keys())[0]
    downstream = graph.get_downstream(entity_id)
    upstream = graph.get_upstream(entity_id)
    print(f'   Entity "{entity_id}" downstream: {downstream}')
    print(f'   Entity "{entity_id}" upstream: {upstream}')

print('\n=== Closed Loop Test Complete ===')
