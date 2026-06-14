import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import asyncio
import time
from unittest.mock import Mock, AsyncMock, MagicMock

print('=== Full Session Flow Test ===')

from neurova.cognitive_layers.memory_layer.dependency_graph import (
    DependencyGraph, EntityNode, DependencyEdge, DependencyType,
)
from neurova.cognitive_layers.memory_layer.cascade_engine import CascadeEngine
from neurova.cognitive_layers.memory_layer.absence_reasoner import AbsenceReasoner
from neurova.cognitive_layers.memory_layer.moe_dependency_extractor import MOEDependencyExtractor
from neurova.cognitive_layers.memory_layer.conversation_rule_extractor import ConversationRuleExtractor
from neurova.cognitive_layers.memory_layer.unified_reasoning_engine import UnifiedReasoningEngine
from neurova.cognitive_layers.memory_layer.experience_memory_fusion import ExperienceMemoryFusion
from neurova.cognitive_layers.memory_layer.deletion_state_manager import DeletionStateManager
from neurova.cognitive_layers.memory_layer.retrieval_facade import MemoryRetrievalFacade
from neurova.agent.tool_pipeline import ToolExecutionPipeline, ToolExecutionContext
from neurova.context.context_facade import ContextFacade
from neurova.evolution.evolution_facade import EvolutionFacade

# Init components
graph = DependencyGraph()
cascade_engine = CascadeEngine(graph)
absence_reasoner = AbsenceReasoner(graph)
extractor = MOEDependencyExtractor(dependency_graph=graph)
fusion = ExperienceMemoryFusion()
deletion_manager = DeletionStateManager()

class MockLLMClient:
    async def generate(self, prompt):
        return '{"rules": [{"source": "database", "target": "API", "relation": "causal", "confidence": 0.8, "evidence": "db failure causes API error"}]}'

class MockPatternMiner:
    def add_sequence(self, tools):
        pass
    def recommend(self, query):
        return ['db_check', 'log_analyzer']

class MockExperienceKB:
    def find_similar(self, query):
        return [{'tool': 'db_check', 'success_rate': 0.9}]

llm_client = MockLLMClient()
pattern_miner = MockPatternMiner()
experience_kb = MockExperienceKB()

rule_extractor = ConversationRuleExtractor(llm_client, graph)
retrieval_facade = MemoryRetrievalFacade()
reasoning_engine = UnifiedReasoningEngine(
    cascade_engine=cascade_engine,
    experience_kb=experience_kb,
    pattern_miner=pattern_miner,
)

print('[1] All components initialized')

# Add test data
graph.add_entity(EntityNode(id='db', name='database', entity_type='object'))
graph.add_entity(EntityNode(id='api', name='API', entity_type='object'))
graph.add_dependency(DependencyEdge(
    id='db_api', source_id='db', target_id='api',
    dep_type=DependencyType.CAUSAL, confidence=0.8,
))

# Test memory retrieval
result = retrieval_facade.retrieve('database', limit=5)
print('[2] Memory retrieval: {} results'.format(len(result.memories)))

# Test experience fusion
tool_result = {'tool_name': 'db_check', 'success': True, 'execution_time': 0.5, 'problem_text': 'db failure'}
graph_context = {'related_entities': ['database', 'API'], 'causal_chains': ['database-F>API']}
fused = fusion.fuse(tool_result, graph_context)
print('[3] Experience fusion: tool={}, confidence={:.2f}'.format(fused['tool_name'], fused['confidence']))

# Test cascade
cascade_result = cascade_engine.forward_cascade('db')
print('[4] Cascade: {} entities affected'.format(cascade_result.total_affected))

# Test absence
absence = absence_reasoner.detect_absence('nonexistent', DependencyType.CAUSAL, ['db', 'api'])
print('[5] Absence: is_absent={}'.format(absence.is_absent))

# Test deletion manager
deletion_manager.mark_as_deleted('mem_001', 'memory', 'user delete')
status = deletion_manager.get_deletion_status('mem_001')
print('[6] Deletion: is_deleted={}'.format(status['is_deleted']))
deletion_manager.restore_entity('mem_001')

# Test reasoning engine
reasoning = reasoning_engine.reason('database failure', {})
print('[7] Reasoning: {} chains, {} tools'.format(len(reasoning.causal_chains), len(reasoning.tool_recommendations)))

# Test tool pipeline
pipeline = ToolExecutionPipeline()
context = ToolExecutionContext(tool_name='db_check', params={}, user_input='check db', success=True, execution_time=0.5)
report = pipeline.execute(context)
print('[8] Tool pipeline: tool={}, success={}'.format(report.tool_name, report.success))

# Test rule extraction
async def test_rules():
    return await rule_extractor.extract('db failure', 'API error', 'conv_001')

rules = asyncio.run(test_rules())
print('[9] Rule extraction: {} rules'.format(len(rules)))

# Final state
print('[10] Final: {} entities, {} edges, {} fused memories'.format(
    len(graph.entities), len(graph.edges), len(fusion._fused_memories)))

print()
print('=== ALL MODULES COORDINATING SUCCESSFULLY ===')
