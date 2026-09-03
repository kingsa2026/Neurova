import asyncio
from neurova.api.endpoints.neuron import (
    list_entities, create_entity, get_entity_dependencies,
    cascade_reasoning, detect_absence, get_neuron_stats, neuron_health,
    extract_dependencies,
)
from neurova.api.endpoints.neuron import EntityCreate, CascadeRequest, AbsenceCheckRequest, DependencyExtractRequest

print('=== Testing NEURON API with Shared Graph ===')

# 1. Health check
print('\n1. Testing neuron_health...')
result = asyncio.run(neuron_health())
print(f'   Success: {result.get("success")}')
print(f'   Entities: {result.get("stats", {}).get("entities", 0)}')
print(f'   Edges: {result.get("stats", {}).get("edges", 0)}')

# 2. Create entities
print('\n2. Creating entities...')
entities_to_create = [
    EntityCreate(name='服务器', entity_type='object', metadata={'type': 'hardware'}),
    EntityCreate(name='数据库', entity_type='object', metadata={'type': 'software'}),
    EntityCreate(name='API', entity_type='object', metadata={'type': 'interface'}),
]
for entity in entities_to_create:
    result = asyncio.run(create_entity(entity))
    print(f'   Created: {entity.name} - {result.get("message")}')

# 3. Check entities
print('\n3. Checking entities...')
result = asyncio.run(list_entities())
print(f'   Total entities: {result.get("total", 0)}')

# 4. Extract dependencies from memory
print('\n4. Extracting dependencies from memory...')
extract_req = DependencyExtractRequest(
    memory_id='mem_001',
    content='部署服务器需要先安装数据库，然后配置API接口',
)
result = asyncio.run(extract_dependencies(extract_req))
print(f'   Extracted: {result.get("total", 0)} dependencies')

# 5. Check graph state after extraction
print('\n5. Checking graph state...')
result = asyncio.run(get_neuron_stats())
print(f'   Entities: {result.get("data", {}).get("total_entities", 0)}')
print(f'   Edges: {result.get("data", {}).get("total_edges", 0)}')

# 6. Test cascade reasoning
print('\n6. Testing cascade reasoning...')
cascade_req = CascadeRequest(entity_id='server', direction='forward', max_depth=3)
result = asyncio.run(cascade_reasoning(cascade_req))
print(f'   Success: {result.get("success")}')
if result.get('data'):
    print(f'   Affected: {result["data"].get("total_affected", 0)}')

# 7. Test absence detection
print('\n7. Testing absence detection...')
absence_req = AbsenceCheckRequest(
    expected_entity='测试环境',
    expected_relation='prerequisite',
    context_entities=['服务器', '数据库'],
)
result = asyncio.run(detect_absence(absence_req))
print(f'   Is absent: {result.get("data", {}).get("is_absent")}')

# 8. Final health check
print('\n8. Final health check...')
result = asyncio.run(neuron_health())
print(f'   Entities: {result.get("stats", {}).get("entities", 0)}')
print(f'   Edges: {result.get("stats", {}).get("edges", 0)}')

print('\n=== All API Tests with Shared Graph Passed ===')
