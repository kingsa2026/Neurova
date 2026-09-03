import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import asyncio
from neurova.cognitive_layers.memory_layer.conversation_rule_extractor import ConversationRuleExtractor
from neurova.cognitive_layers.memory_layer.dependency_graph import DependencyGraph

print('=== PostChatPipeline Integration Test ===')

# Test ConversationRuleExtractor
class MockLLMClient:
    async def generate(self, prompt):
        return '{"rules": [{"source": "database", "target": "API", "relation": "causal", "confidence": 0.8, "evidence": "db failure causes API error"}]}'

graph = DependencyGraph()
llm_client = MockLLMClient()
extractor = ConversationRuleExtractor(llm_client, graph)

# Test rule extraction
async def test_extraction():
    rules = await extractor.extract('数据库挂了', 'API返回500错误', 'conv_001')
    return rules

rules = asyncio.run(test_extraction())
print('[1] Rule extraction: {} rules'.format(len(rules)))
for rule in rules:
    print('  - {} -> {} ({}, conf={:.2f})'.format(
        rule.source_entity, rule.target_entity, rule.relation_type, rule.confidence))

# Test ExperienceMemoryFusion
from neurova.cognitive_layers.memory_layer.experience_memory_fusion import ExperienceMemoryFusion

fusion = ExperienceMemoryFusion()
tool_result = {'tool_name': 'db_check', 'success': True, 'execution_time': 0.5, 'problem_text': 'db failure'}
graph_context = {'related_entities': ['database', 'API'], 'causal_chains': ['database-F>API']}
fused = fusion.fuse(tool_result, graph_context)
print('[2] Experience fusion: tool={}, confidence={:.2f}'.format(fused['tool_name'], fused['confidence']))

# Test DeletionStateManager
from neurova.cognitive_layers.memory_layer.deletion_state_manager import DeletionStateManager

deletion_manager = DeletionStateManager()
deletion_manager.mark_as_deleted('mem_001', 'memory', 'user delete')
status = deletion_manager.get_deletion_status('mem_001')
print('[3] Deletion: is_deleted={}'.format(status['is_deleted']))

print()
print('=== PostChatPipeline Integration Complete ===')
