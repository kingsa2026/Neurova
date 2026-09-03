from neurova.api.endpoints.neuron import get_shared_graph, create_entity, list_entities, extract_dependencies, reset_shared_graph
from neurova.api.endpoints.neuron import EntityCreate, DependencyExtractRequest
import asyncio

# Reset the shared graph
reset_shared_graph()

# Create entities
print('Creating entities...')
for name in ['服务器', '数据库', 'API']:
    result = asyncio.run(create_entity(EntityCreate(name=name, entity_type='object')))
    print(f'  Created: {name}')

# Check entities
result = asyncio.run(list_entities())
print(f'After creation: {result.get("total", 0)} entities')

# Extract dependencies
result = asyncio.run(extract_dependencies(DependencyExtractRequest(
    memory_id='mem_001',
    content='部署服务器需要先安装数据库，然后配置API接口',
)))
print(f'After extraction: extracted {result.get("total", 0)} dependencies')

# Check final state
graph = get_shared_graph()
print(f'Final state: {len(graph.entities)} entities, {len(graph.edges)} edges')
