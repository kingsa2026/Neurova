import sys
sys.path.insert(0, '.')

from neurova.api.endpoints.neuron import (
    list_entities, create_entity, get_entity_dependencies,
    cascade_reasoning, detect_absence, get_neuron_stats, neuron_health
)

import asyncio

print('=== Testing NEURON API Endpoints (Direct) ===')

# Test 1: Health check
print('\n1. Testing neuron_health...')
result = asyncio.run(neuron_health())
print(f'   Success: {result.get("success")}')
print(f'   Status: {result.get("status")}')

# Test 2: Stats
print('\n2. Testing get_neuron_stats...')
result = asyncio.run(get_neuron_stats())
print(f'   Success: {result.get("success")}')
print(f'   Data: {result.get("data")}')

# Test 3: List entities
print('\n3. Testing list_entities...')
result = asyncio.run(list_entities())
print(f'   Success: {result.get("success")}')
print(f'   Total: {result.get("total", 0)}')

# Test 4: Create entity
print('\n4. Testing create_entity...')
from neurova.api.endpoints.neuron import EntityCreate
result = asyncio.run(create_entity(EntityCreate(
    name='Test Server',
    entity_type='object',
    metadata={'test': True}
)))
print(f'   Success: {result.get("success")}')
print(f'   Message: {result.get("message")}')

# Test 5: Cascade reasoning
print('\n5. Testing cascade_reasoning...')
from neurova.api.endpoints.neuron import CascadeRequest
result = asyncio.run(cascade_reasoning(CascadeRequest(
    entity_id='server',
    direction='forward',
    max_depth=3
)))
print(f'   Success: {result.get("success")}')
if result.get('data'):
    print(f'   Total affected: {result["data"].get("total_affected", 0)}')

# Test 6: Absence detection
print('\n6. Testing detect_absence...')
from neurova.api.endpoints.neuron import AbsenceCheckRequest
result = asyncio.run(detect_absence(AbsenceCheckRequest(
    expected_entity='database',
    expected_relation='prerequisite',
    context_entities=['server']
)))
print(f'   Success: {result.get("success")}')
if result.get('data'):
    print(f'   Is absent: {result["data"].get("is_absent")}')

print('\n=== All API Tests Completed ===')
