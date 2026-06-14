import requests
import json
import time

base_url = 'http://localhost:9527/api/neuron'

print('=== Testing NEURON API Endpoints ===')

# Wait for server to be ready
time.sleep(2)

# Test 1: Health check
print('\n1. Testing /neuron/health...')
try:
    resp = requests.get(f'{base_url}/health', timeout=5)
    print(f'   Status: {resp.status_code}')
    data = resp.json()
    print(f'   Success: {data.get("success")}')
    print(f'   Status: {data.get("status")}')
except Exception as e:
    print(f'   Error: {e}')

# Test 2: Stats
print('\n2. Testing /neuron/stats...')
try:
    resp = requests.get(f'{base_url}/stats', timeout=5)
    print(f'   Status: {resp.status_code}')
    data = resp.json()
    print(f'   Entities: {data.get("data", {}).get("total_entities", 0)}')
    print(f'   Edges: {data.get("data", {}).get("total_edges", 0)}')
except Exception as e:
    print(f'   Error: {e}')

# Test 3: List entities
print('\n3. Testing /neuron/entities...')
try:
    resp = requests.get(f'{base_url}/entities', timeout=5)
    print(f'   Status: {resp.status_code}')
    data = resp.json()
    print(f'   Total: {data.get("total", 0)}')
except Exception as e:
    print(f'   Error: {e}')

# Test 4: Create entity
print('\n4. Testing POST /neuron/entities...')
try:
    resp = requests.post(f'{base_url}/entities', json={
        'name': 'Test Server',
        'entity_type': 'object',
        'metadata': {'test': True}
    }, timeout=5)
    print(f'   Status: {resp.status_code}')
    data = resp.json()
    print(f'   Success: {data.get("success")}')
    print(f'   Message: {data.get("message")}')
except Exception as e:
    print(f'   Error: {e}')

# Test 5: Cascade reasoning
print('\n5. Testing POST /neuron/cascade...')
try:
    resp = requests.post(f'{base_url}/cascade', json={
        'entity_id': 'server',
        'direction': 'forward',
        'max_depth': 3
    }, timeout=5)
    print(f'   Status: {resp.status_code}')
    data = resp.json()
    print(f'   Success: {data.get("success")}')
    if data.get('data'):
        print(f'   Total affected: {data["data"].get("total_affected", 0)}')
except Exception as e:
    print(f'   Error: {e}')

# Test 6: Absence detection
print('\n6. Testing POST /neuron/absence/detect...')
try:
    resp = requests.post(f'{base_url}/absence/detect', json={
        'expected_entity': 'database',
        'expected_relation': 'prerequisite',
        'context_entities': ['server']
    }, timeout=5)
    print(f'   Status: {resp.status_code}')
    data = resp.json()
    print(f'   Success: {data.get("success")}')
    if data.get('data'):
        print(f'   Is absent: {data["data"].get("is_absent")}')
except Exception as e:
    print(f'   Error: {e}')

print('\n=== All API Tests Completed ===')
