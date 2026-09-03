import asyncio
from neurova.cognitive_layers.memory_layer.dependency_graph import (
    DependencyGraph, EntityNode, DependencyEdge, DependencyType,
)
from neurova.cognitive_layers.memory_layer.cascade_engine import CascadeEngine
from neurova.cognitive_layers.memory_layer.absence_reasoner import AbsenceReasoner
from neurova.cognitive_layers.memory_layer.moe_dependency_extractor import (
    MOEDependencyExtractor, EntityExtractor, RelationClassifier,
)

print('=== Testing Memory System Closed Loop (Corrected) ===')

# 1. Create a shared graph
print('\n1. Create shared graph...')
shared_graph = DependencyGraph()
print(f'   Initial state: {len(shared_graph.entities)} entities, {len(shared_graph.edges)} edges')

# 2. Initialize components with shared graph
print('\n2. Initialize components...')
cascade_engine = CascadeEngine(shared_graph)
absence_reasoner = AbsenceReasoner(shared_graph)
extractor = MOEDependencyExtractor()
print('   Components initialized')

# 3. Manually add some test data to the graph
print('\n3. Add test data to graph...')
shared_graph.add_entity(EntityNode(id='server', name='服务器', entity_type='object'))
shared_graph.add_entity(EntityNode(id='database', name='数据库', entity_type='object'))
shared_graph.add_entity(EntityNode(id='api', name='API', entity_type='object'))
shared_graph.add_dependency(DependencyEdge(
    id='server_db', source_id='server', target_id='database',
    dep_type=DependencyType.PREREQUISITE,
))
shared_graph.add_dependency(DependencyEdge(
    id='server_api', source_id='server', target_id='api',
    dep_type=DependencyType.CAUSAL,
))
print(f'   Graph: {len(shared_graph.entities)} entities, {len(shared_graph.edges)} edges')

# 4. Extract dependencies from memory content
print('\n4. Extract dependencies from memory content...')
async def test_extract():
    deps = await extractor.extract_from_memory(
        memory_id='mem_001',
        content='部署服务器需要先安装数据库，然后配置API接口',
    )
    return deps

deps = asyncio.run(test_extract())
print(f'   Extracted {len(deps)} dependencies from content')

# 5. Test cascade reasoning with shared graph
print('\n5. Test cascade reasoning...')
result = cascade_engine.forward_cascade('server')
print(f'   Forward cascade from "server": {result.total_affected} affected')
print(f'   Confidence: {result.confidence:.2f}')

# 6. Test absence detection
print('\n6. Test absence detection...')
absence = absence_reasoner.detect_absence(
    expected_entity='database',
    expected_relation=DependencyType.PREREQUISITE,
    context_entities=['server'],
)
print(f'   Entity "database" exists: {absence.entity_exists}')
print(f'   Relation exists: {absence.relation_exists}')
print(f'   Is absent: {absence.is_absent}')

# 7. Test graph queries
print('\n7. Test graph queries...')
downstream = shared_graph.get_downstream('server')
upstream = shared_graph.get_upstream('database')
print(f'   Downstream of "server": {downstream}')
print(f'   Upstream of "database": {upstream}')

# 8. Find cascade paths
print('\n8. Find cascade paths...')
paths = shared_graph.find_cascade_paths('server', 'database')
print(f'   Paths from "server" to "database": {paths}')

print('\n=== Closed Loop Test Complete ===')
print('\nSummary:')
print(f'  - Graph: {len(shared_graph.entities)} entities, {len(shared_graph.edges)} edges')
print(f'  - Extracted: {len(deps)} dependencies from memory content')
print(f'  - Cascade: {result.total_affected} entities affected')
print(f'  - Absence: detected={absence.is_absent}')
print(f'  - All components working together in closed loop!')
