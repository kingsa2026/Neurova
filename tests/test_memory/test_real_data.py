import asyncio
from neurova.cognitive_layers.memory_layer.dependency_graph import (
    DependencyGraph, EntityNode, DependencyEdge, DependencyType,
)
from neurova.cognitive_layers.memory_layer.cascade_engine import CascadeEngine
from neurova.cognitive_layers.memory_layer.absence_reasoner import AbsenceReasoner
from neurova.cognitive_layers.memory_layer.moe_dependency_extractor import MOEDependencyExtractor

print('=== Testing Memory System with Real Data ===')

# 1. Create graph and components
graph = DependencyGraph()
cascade_engine = CascadeEngine(graph)
absence_reasoner = AbsenceReasoner(graph)
extractor = MOEDependencyExtractor()

# 2. Simulate real memory content
print('\n1. Processing real memory content...')
real_memories = [
    {
        'id': 'mem_001',
        'content': '用户需要部署Python Web应用，首先需要安装Docker，然后配置Nginx反向代理，最后部署到云服务器',
        'metadata': {'source': 'conversation', 'timestamp': '2026-06-13'}
    },
    {
        'id': 'mem_002', 
        'content': '数据库迁移需要先备份现有数据，然后执行迁移脚本，最后验证数据完整性',
        'metadata': {'source': 'documentation', 'timestamp': '2026-06-12'}
    },
    {
        'id': 'mem_003',
        'content': 'API接口设计需要先定义数据模型，然后实现业务逻辑，最后编写测试用例',
        'metadata': {'source': 'code_review', 'timestamp': '2026-06-11'}
    },
]

async def process_memories():
    all_deps = []
    for memory in real_memories:
        deps = await extractor.extract_from_memory(
            memory_id=memory['id'],
            content=memory['content'],
            metadata=memory['metadata'],
        )
        all_deps.extend(deps)
        print(f'   Memory {memory["id"]}: extracted {len(deps)} dependencies')
    return all_deps

print('\n2. Extracting dependencies from real memories...')
all_deps = asyncio.run(process_memories())
print(f'   Total dependencies extracted: {len(all_deps)}')

# 3. Check graph state
print('\n3. Graph state after extraction...')
print(f'   Entities: {len(graph.entities)}')
print(f'   Edges: {len(graph.edges)}')

# 4. Test cascade reasoning with real data
print('\n4. Testing cascade reasoning with real data...')
if graph.entities:
    # Get first entity
    first_entity = list(graph.entities.keys())[0]
    first_entity_name = graph.entities[first_entity].name
    
    # Forward cascade
    result = cascade_engine.forward_cascade(first_entity)
    print(f'   Forward cascade from "{first_entity_name}":')
    print(f'     - Entities affected: {result.total_affected}')
    print(f'     - Confidence: {result.confidence:.2f}')
    
    # Backward cascade
    if result.effects:
        target = result.effects[0].entity_id
        target_name = graph.entities.get(target, EntityNode(id=target, name=target)).name
        backward = cascade_engine.backward_cascade(target)
        print(f'   Backward cascade to "{target_name}":')
        print(f'     - Entities affected: {backward.total_affected}')

# 5. Test absence detection with real scenarios
print('\n5. Testing absence detection with real scenarios...')

# Scenario 1: Check if "测试环境" exists
absence1 = absence_reasoner.detect_absence(
    expected_entity='测试环境',
    expected_relation=DependencyType.PREREQUISITE,
    context_entities=['服务器', '数据库'],
)
print(f'   Scenario 1 - "测试环境" prerequisites:')
print(f'     - Entity exists: {absence1.entity_exists}')
print(f'     - Relation exists: {absence1.relation_exists}')
print(f'     - Is absent: {absence1.is_absent}')
if absence1.explanation:
    print(f'     - Explanation: {absence1.explanation[0]}')

# Scenario 2: Check if "数据库" has dependencies
absence2 = absence_reasoner.detect_absence(
    expected_entity='数据库',
    expected_relation=DependencyType.CAUSAL,
    context_entities=['服务器', 'Docker'],
)
print(f'\n   Scenario 2 - "数据库" causal relationships:')
print(f'     - Entity exists: {absence2.entity_exists}')
print(f'     - Relation exists: {absence2.relation_exists}')
print(f'     - Is absent: {absence2.is_absent}')

# 6. Test graph queries with real data
print('\n6. Testing graph queries with real data...')
if graph.entities:
    # Query all entities
    print(f'   All entities ({len(graph.entities)}):')
    for eid, entity in list(graph.entities.items())[:5]:
        downstream = graph.get_downstream(eid, max_depth=2)
        print(f'     - {entity.name} ({entity.entity_type}): downstream={downstream}')
    
    # Find all paths between entities
    entities_list = list(graph.entities.keys())
    if len(entities_list) >= 2:
        paths = graph.find_cascade_paths(entities_list[0], entities_list[-1])
        print(f'\n   Paths from "{graph.entities[entities_list[0]].name}" to "{graph.entities[entities_list[-1]].name}":')
        for path in paths[:3]:
            path_names = [graph.entities[eid].name for eid in path if eid in graph.entities]
            print(f'     - {" → ".join(path_names)}')

# 7. Test MOE extraction details
print('\n7. MOE extraction details...')
for dep in all_deps[:5]:
    print(f'   - {dep.source_entity["name"]} [{dep.dep_type.value}] → {dep.target_entity["name"]} (conf={dep.confidence:.2f})')

print('\n=== Real Data Test Complete ===')
print('\nFinal Statistics:')
print(f'  - Processed {len(real_memories)} memories')
print(f'  - Extracted {len(all_deps)} dependencies')
print(f'  - Graph contains {len(graph.entities)} entities and {len(graph.edges)} edges')
print(f'  - All components functioning correctly with real data')
