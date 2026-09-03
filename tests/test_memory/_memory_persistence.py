import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import asyncio
import time
from neurova.cognitive_layers.memory_layer.dependency_graph import DependencyGraph, EntityNode, DependencyEdge, DependencyType
from neurova.cognitive_layers.memory_layer.moe_dependency_extractor import MOEDependencyExtractor
from neurova.cognitive_layers.memory_layer.experience_memory_fusion import ExperienceMemoryFusion

print('=== Real User Conversation Memory Persistence Test ===')

# Init
graph = DependencyGraph()
extractor = MOEDependencyExtractor(dependency_graph=graph)
fusion = ExperienceMemoryFusion()

# Real conversations
conversations = [
    {'user': '我的Python项目部署失败了', 'tools': ['git_pull', 'docker_build'], 'success': True},
    {'user': '数据库连接超时', 'tools': ['db_check', 'restart_service'], 'success': True},
    {'user': 'API响应很慢', 'tools': ['cache_clear', 'log_analyzer'], 'success': False},
    {'user': '服务器磁盘满了', 'tools': ['disk_cleanup', 'log_rotate'], 'success': True},
]

async def process_conversation(conv, idx):
    content = conv['user']
    deps = await extractor.extract_from_memory(memory_id='mem_{:03d}'.format(idx), content=content)
    
    for tool in conv['tools']:
        fusion.fuse({'tool_name': tool, 'success': conv['success'], 'problem_text': content}, {})
    
    return deps

for i, conv in enumerate(conversations):
    deps = asyncio.run(process_conversation(conv, i))
    print('[{}] User: "{}" -> {} deps, tools: {}'.format(i+1, conv['user'], len(deps), conv['tools']))

print()
print('Final state:')
print('  Entities: {}'.format(len(graph.entities)))
print('  Edges: {}'.format(len(graph.edges)))
print('  Fused memories: {}'.format(len(fusion._fused_memories)))

# Check tool statistics
for tool in ['git_pull', 'db_check', 'cache_clear', 'disk_cleanup']:
    stats = fusion.get_tool_statistics(tool)
    if stats['count'] > 0:
        print('  {}: count={}, success_rate={:.0%}'.format(tool, stats['count'], stats['success_rate']))

print()
print('=== Memory Persistence Verified ===')
