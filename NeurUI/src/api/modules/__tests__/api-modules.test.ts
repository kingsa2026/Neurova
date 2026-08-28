import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the api module before importing anything that depends on it
vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    post: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    put: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    delete: vi.fn().mockResolvedValue({ code: 0, data: {} }),
  },
}))

import api from '@/api'
import * as runtime from '@/api/modules/runtime'
import * as image from '@/api/modules/image'
import * as builder from '@/api/modules/builder'
import * as modelAdapter from '@/api/modules/model-adapter'
import * as contextApi from '@/api/modules/context'
import * as contextPool from '@/api/modules/context-pool'
import * as agentEnhancement from '@/api/modules/agent-enhancement'
import * as agentCommunication from '@/api/modules/agent-communication'
import * as neurflow from '@/api/modules/neurflow'
import * as mobile from '@/api/modules/mobile'
import * as negativeScreen from '@/api/modules/negative-screen'
import * as logsApi from '@/api/modules/logs-api'
import * as synonyms from '@/api/modules/synonyms'
import * as groups from '@/api/modules/groups'
import * as teams from '@/api/modules/teams'
import * as projects from '@/api/modules/projects'
import * as providers from '@/api/modules/providers'
import * as models from '@/api/modules/models'

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)
const mockPut = vi.mocked(api.put)
const mockDelete = vi.mocked(api.delete)

beforeEach(() => {
  vi.clearAllMocks()
})

// ===========================================================================
// runtime.ts
// ===========================================================================
describe('runtime API', () => {
  it('getRuntimeStatus calls GET /runtime/status', async () => {
    await runtime.getRuntimeStatus()
    expect(mockGet).toHaveBeenCalledWith('/runtime/status')
  })

  it('getResourceUsage calls GET /runtime/resources', async () => {
    await runtime.getResourceUsage()
    expect(mockGet).toHaveBeenCalledWith('/runtime/resources')
  })

  it('getPerformanceMetrics calls GET /runtime/performance', async () => {
    await runtime.getPerformanceMetrics()
    expect(mockGet).toHaveBeenCalledWith('/runtime/performance')
  })

  it('triggerGC calls POST /runtime/gc', async () => {
    await runtime.triggerGC()
    expect(mockPost).toHaveBeenCalledWith('/runtime/gc')
  })
})

// ===========================================================================
// image.ts
// ===========================================================================
describe('image API', () => {
  it('getTemplates calls GET /image/templates', async () => {
    await image.getTemplates()
    expect(mockGet).toHaveBeenCalledWith('/image/templates')
  })

  it('getTemplate calls GET /image/templates/{name}', async () => {
    await image.getTemplate('ubuntu-base')
    expect(mockGet).toHaveBeenCalledWith('/image/templates/ubuntu-base')
  })

  it('buildImage calls POST /image/build', async () => {
    await image.buildImage({ template_name: 'ubuntu-base', tag: 'latest' })
    expect(mockPost).toHaveBeenCalledWith('/image/build', {
      template_name: 'ubuntu-base',
      tag: 'latest',
    })
  })

  it('getBuilds calls GET /image/builds with params', async () => {
    await image.getBuilds({ status: 'success', limit: 10 })
    expect(mockGet).toHaveBeenCalledWith('/image/builds', { params: { status: 'success', limit: 10 } })
  })

  it('getBuild calls GET /image/builds/{buildId}', async () => {
    await image.getBuild('build-123')
    expect(mockGet).toHaveBeenCalledWith('/image/builds/build-123')
  })
})

// ===========================================================================
// builder.ts
// ===========================================================================
describe('builder API', () => {
  it('getTemplates calls GET /builder/templates', async () => {
    await builder.getTemplates()
    expect(mockGet).toHaveBeenCalledWith('/builder/templates')
  })

  it('getTemplate calls GET /builder/templates/{id}', async () => {
    await builder.getTemplate('coder')
    expect(mockGet).toHaveBeenCalledWith('/builder/templates/coder')
  })

  it('validateConfig calls POST /builder/validate', async () => {
    await builder.validateConfig({ name: 'test', system_prompt: 'hello' })
    expect(mockPost).toHaveBeenCalledWith('/builder/validate', {
      name: 'test',
      system_prompt: 'hello',
    })
  })

  it('buildAgent calls POST /builder/build', async () => {
    await builder.buildAgent({ name: 'my-agent', template_id: 'assistant' })
    expect(mockPost).toHaveBeenCalledWith('/builder/build', {
      name: 'my-agent',
      template_id: 'assistant',
    })
  })

  it('getBuiltAgents calls GET /builder/agents', async () => {
    await builder.getBuiltAgents()
    expect(mockGet).toHaveBeenCalledWith('/builder/agents')
  })
})

// ===========================================================================
// model-adapter.ts
// ===========================================================================
describe('model-adapter API', () => {
  it('getAdapters calls GET /model-adapter', async () => {
    await modelAdapter.getAdapters()
    expect(mockGet).toHaveBeenCalledWith('/model-adapter')
  })

  it('getAdapter calls GET /model-adapter/{id}', async () => {
    await modelAdapter.getAdapter('openai')
    expect(mockGet).toHaveBeenCalledWith('/model-adapter/openai')
  })

  it('matchModel calls POST /model-adapter/match', async () => {
    await modelAdapter.matchModel('gpt-4o')
    expect(mockPost).toHaveBeenCalledWith('/model-adapter/match', { model: 'gpt-4o' })
  })
})

// ===========================================================================
// context.ts
// ===========================================================================
describe('context API', () => {
  it('buildContext calls POST /context/build', async () => {
    await contextApi.buildContext({ user_input: 'hello', agent_id: 'default' })
    expect(mockPost).toHaveBeenCalledWith('/context/build', {
      user_input: 'hello',
      agent_id: 'default',
    })
  })

  it('buildContextV2 calls POST /context/build/v2', async () => {
    await contextApi.buildContextV2({ user_input: 'test' })
    expect(mockPost).toHaveBeenCalledWith('/context/build/v2', { user_input: 'test' })
  })

  it('getContextStats calls GET /context/stats', async () => {
    await contextApi.getContextStats()
    expect(mockGet).toHaveBeenCalledWith('/context/stats')
  })

  it('getContextPreview calls GET /context/{id}/preview', async () => {
    await contextApi.getContextPreview('ctx-123')
    expect(mockGet).toHaveBeenCalledWith('/context/ctx-123/preview')
  })

  it('compressContext calls POST /context/{id}/compress with query params', async () => {
    await contextApi.compressContext('ctx-123', 8000)
    expect(mockPost).toHaveBeenCalledWith('/context/ctx-123/compress', null, { params: { target_tokens: 8000 } })
  })

  it('injectReflection calls GET /context/inject/reflection', async () => {
    await contextApi.injectReflection('agent1', 5)
    expect(mockGet).toHaveBeenCalledWith('/context/inject/reflection', {
      params: { agent_id: 'agent1', limit: 5 },
    })
  })

  it('injectMemories calls GET /context/inject/memories', async () => {
    await contextApi.injectMemories('agent1', 'query', 20)
    expect(mockGet).toHaveBeenCalledWith('/context/inject/memories', {
      params: { agent_id: 'agent1', query: 'query', limit: 20 },
    })
  })

  it('injectHotMemories calls GET /context/inject/hot', async () => {
    await contextApi.injectHotMemories('agent1', 10)
    expect(mockGet).toHaveBeenCalledWith('/context/inject/hot', {
      params: { agent_id: 'agent1', limit: 10 },
    })
  })

  it('getTokenBudget calls GET /context/token-budget', async () => {
    await contextApi.getTokenBudget('agent1')
    expect(mockGet).toHaveBeenCalledWith('/context/token-budget', {
      params: { agent_id: 'agent1' },
    })
  })

  it('setTokenBudget calls PUT /context/token-budget', async () => {
    await contextApi.setTokenBudget('agent1', 32000)
    expect(mockPut).toHaveBeenCalledWith('/context/token-budget', null, {
      params: { agent_id: 'agent1', max_tokens: 32000 },
    })
  })
})

// ===========================================================================
// context-pool.ts
// ===========================================================================
describe('context-pool API', () => {
  it('getPoolSettings calls GET /context-pool/pool-settings', async () => {
    await contextPool.getPoolSettings()
    expect(mockGet).toHaveBeenCalledWith('/context-pool/pool-settings')
  })

  it('updatePoolSettings calls PUT /context-pool/pool-settings', async () => {
    await contextPool.updatePoolSettings({ max_size: 200 })
    expect(mockPut).toHaveBeenCalledWith('/context-pool/pool-settings', { max_size: 200 })
  })

  it('getModelTokenBudget calls GET with model name in path', async () => {
    await contextPool.getModelTokenBudget('gpt-4o')
    expect(mockGet).toHaveBeenCalledWith('/context-pool/pool-settings/token-budget/gpt-4o')
  })

  it('testBudgetCalculation calls POST /context-pool/pool-settings/test-budget', async () => {
    await contextPool.testBudgetCalculation({ model_name: 'gpt-4o' })
    expect(mockPost).toHaveBeenCalledWith('/context-pool/pool-settings/test-budget', {
      model_name: 'gpt-4o',
    })
  })
})

// ===========================================================================
// agent-enhancement.ts
// ===========================================================================
describe('agent-enhancement API', () => {
  it('getAgentStatus calls GET /agent-enhancement/{id}/status', async () => {
    await agentEnhancement.getAgentStatus('agent1')
    expect(mockGet).toHaveBeenCalledWith('/agent-enhancement/agent1/status')
  })

  it('getAgentCapabilities calls GET /agent-enhancement/{id}/capabilities', async () => {
    await agentEnhancement.getAgentCapabilities('agent1')
    expect(mockGet).toHaveBeenCalledWith('/agent-enhancement/agent1/capabilities')
  })

  it('getAgentHealth calls GET /agent-enhancement/{id}/health', async () => {
    await agentEnhancement.getAgentHealth('agent1')
    expect(mockGet).toHaveBeenCalledWith('/agent-enhancement/agent1/health')
  })

  it('restartAgent calls POST /agent-enhancement/{id}/restart', async () => {
    await agentEnhancement.restartAgent('agent1')
    expect(mockPost).toHaveBeenCalledWith('/agent-enhancement/agent1/restart')
  })
})

// ===========================================================================
// agent-communication.ts
// ===========================================================================
describe('agent-communication API', () => {
  it('generateAPIKey calls POST /agent-communication/api-keys', async () => {
    await agentCommunication.generateAPIKey({ name: 'test-key', agent_id: 'agent1' })
    expect(mockPost).toHaveBeenCalledWith('/agent-communication/api-keys', {
      name: 'test-key',
      agent_id: 'agent1',
    })
  })

  it('getAPIKeys calls GET /agent-communication/api-keys', async () => {
    await agentCommunication.getAPIKeys()
    expect(mockGet).toHaveBeenCalledWith('/agent-communication/api-keys')
  })

  it('updateAPIKey calls PUT /agent-communication/api-keys/{id}', async () => {
    await agentCommunication.updateAPIKey('key1', { name: 'renamed' })
    expect(mockPut).toHaveBeenCalledWith('/agent-communication/api-keys/key1', { name: 'renamed' })
  })

  it('revokeAPIKey calls POST /agent-communication/api-keys/{id}/revoke', async () => {
    await agentCommunication.revokeAPIKey('key1')
    expect(mockPost).toHaveBeenCalledWith('/agent-communication/api-keys/key1/revoke')
  })

  it('deleteAPIKey calls DELETE /agent-communication/api-keys/{id}', async () => {
    await agentCommunication.deleteAPIKey('key1')
    expect(mockDelete).toHaveBeenCalledWith('/agent-communication/api-keys/key1')
  })

  it('handshake calls POST /agent-communication/handshake', async () => {
    await agentCommunication.handshake({ agent_id: 'ext1', agent_name: 'External' })
    expect(mockPost).toHaveBeenCalledWith('/agent-communication/handshake', {
      agent_id: 'ext1',
      agent_name: 'External',
    })
  })

  it('sendMessage calls POST /agent-communication/messages/send', async () => {
    await agentCommunication.sendMessage({
      target_agent_id: 'ext1',
      content: { text: 'hello' },
    })
    expect(mockPost).toHaveBeenCalledWith('/agent-communication/messages/send', {
      target_agent_id: 'ext1',
      content: { text: 'hello' },
    })
  })

  it('getMessages calls GET /agent-communication/messages with params', async () => {
    await agentCommunication.getMessages({ agent_id: 'ext1', limit: 20 })
    expect(mockGet).toHaveBeenCalledWith('/agent-communication/messages', {
      params: { agent_id: 'ext1', limit: 20 },
    })
  })

  it('getExternalAgents calls GET /agent-communication/external-agents', async () => {
    await agentCommunication.getExternalAgents()
    expect(mockGet).toHaveBeenCalledWith('/agent-communication/external-agents')
  })

  it('registerExternalAgent calls POST /agent-communication/external-agents', async () => {
    await agentCommunication.registerExternalAgent({
      agent_id: 'ext2',
      agent_name: 'Agent2',
    })
    expect(mockPost).toHaveBeenCalledWith('/agent-communication/external-agents', {
      agent_id: 'ext2',
      agent_name: 'Agent2',
    })
  })

  it('getExternalAgentStatus calls GET /agent-communication/external-agents/{id}/status', async () => {
    await agentCommunication.getExternalAgentStatus('ext1')
    expect(mockGet).toHaveBeenCalledWith('/agent-communication/external-agents/ext1/status')
  })

  it('getRoutingStats calls GET /agent-communication/routing/stats', async () => {
    await agentCommunication.getRoutingStats()
    expect(mockGet).toHaveBeenCalledWith('/agent-communication/routing/stats')
  })
})

// ===========================================================================
// neurflow.ts
// ===========================================================================
describe('neurflow API', () => {
  it('getWorkflows calls GET /neurflow/workflows', async () => {
    await neurflow.getWorkflows({ category: 'ai', limit: 10 })
    expect(mockGet).toHaveBeenCalledWith('/neurflow/workflows', {
      params: { category: 'ai', limit: 10 },
    })
  })

  it('createWorkflow calls POST /neurflow/workflows', async () => {
    await neurflow.createWorkflow({ name: 'Test Flow' })
    expect(mockPost).toHaveBeenCalledWith('/neurflow/workflows', { name: 'Test Flow' })
  })

  it('getWorkflow calls GET /neurflow/workflows/{id}', async () => {
    await neurflow.getWorkflow('wf-123')
    expect(mockGet).toHaveBeenCalledWith('/neurflow/workflows/wf-123')
  })

  it('updateWorkflow calls PUT /neurflow/workflows/{id}', async () => {
    await neurflow.updateWorkflow('wf-123', { name: 'Updated' })
    expect(mockPut).toHaveBeenCalledWith('/neurflow/workflows/wf-123', { name: 'Updated' })
  })

  it('deleteWorkflow calls DELETE /neurflow/workflows/{id}', async () => {
    await neurflow.deleteWorkflow('wf-123')
    expect(mockDelete).toHaveBeenCalledWith('/neurflow/workflows/wf-123')
  })

  it('validateWorkflow calls POST /neurflow/workflows/{id}/validate', async () => {
    await neurflow.validateWorkflow('wf-123')
    expect(mockPost).toHaveBeenCalledWith('/neurflow/workflows/wf-123/validate')
  })

  it('executeWorkflow calls POST /neurflow/workflows/{id}/execute', async () => {
    await neurflow.executeWorkflow('wf-123', { input: 'test' }, { agent_id: 'a1' })
    expect(mockPost).toHaveBeenCalledWith('/neurflow/workflows/wf-123/execute', {
      inputs: { input: 'test' },
      agent_id: 'a1',
    })
  })

  it('getExecutions calls GET /neurflow/executions', async () => {
    await neurflow.getExecutions({ workflow_id: 'wf-123' })
    expect(mockGet).toHaveBeenCalledWith('/neurflow/executions', {
      params: { workflow_id: 'wf-123' },
    })
  })

  it('getExecution calls GET /neurflow/executions/{id}', async () => {
    await neurflow.getExecution('exec-1')
    expect(mockGet).toHaveBeenCalledWith('/neurflow/executions/exec-1')
  })

  it('cancelExecution calls POST /neurflow/executions/{id}/cancel', async () => {
    await neurflow.cancelExecution('exec-1')
    expect(mockPost).toHaveBeenCalledWith('/neurflow/executions/exec-1/cancel')
  })

  it('resumeExecution calls POST /neurflow/executions/{id}/resume', async () => {
    await neurflow.resumeExecution('exec-1')
    expect(mockPost).toHaveBeenCalledWith('/neurflow/executions/exec-1/resume')
  })

  it('getNodes calls GET /neurflow/nodes', async () => {
    await neurflow.getNodes({ category: 'tool' })
    expect(mockGet).toHaveBeenCalledWith('/neurflow/nodes', { params: { category: 'tool' } })
  })

  it('searchNodes calls GET /neurflow/nodes/search/{query}', async () => {
    await neurflow.searchNodes('memory')
    expect(mockGet).toHaveBeenCalledWith('/neurflow/nodes/search/memory')
  })

  it('syncNodes calls POST /neurflow/nodes/sync', async () => {
    await neurflow.syncNodes()
    expect(mockPost).toHaveBeenCalledWith('/neurflow/nodes/sync')
  })

  it('getNodeStats calls GET /neurflow/nodes/stats', async () => {
    await neurflow.getNodeStats()
    expect(mockGet).toHaveBeenCalledWith('/neurflow/nodes/stats')
  })

  it('getTemplates calls GET /neurflow/templates', async () => {
    await neurflow.getTemplates({ category: 'ai' })
    expect(mockGet).toHaveBeenCalledWith('/neurflow/templates', { params: { category: 'ai' } })
  })

  it('getNeurflowStats calls GET /neurflow/stats', async () => {
    await neurflow.getNeurflowStats()
    expect(mockGet).toHaveBeenCalledWith('/neurflow/stats')
  })

  it('duplicateWorkflow calls POST /neurflow/workflows/{id}/duplicate', async () => {
    await neurflow.duplicateWorkflow('wf-123')
    expect(mockPost).toHaveBeenCalledWith('/neurflow/workflows/wf-123/duplicate')
  })

  it('publishWorkflow calls POST /neurflow/workflows/{id}/publish', async () => {
    await neurflow.publishWorkflow('wf-123')
    expect(mockPost).toHaveBeenCalledWith('/neurflow/workflows/wf-123/publish')
  })
})

// ===========================================================================
// mobile.ts
// ===========================================================================
describe('mobile API', () => {
  it('generatePairing calls POST /mobile/pairing/generate', async () => {
    await mobile.generatePairing({ device_name: 'iPhone', device_type: 'ios' })
    expect(mockPost).toHaveBeenCalledWith('/mobile/pairing/generate', {
      device_name: 'iPhone',
      device_type: 'ios',
    })
  })

  it('getPairingStatus calls GET /mobile/pairing/status/{code}', async () => {
    await mobile.getPairingStatus('123456')
    expect(mockGet).toHaveBeenCalledWith('/mobile/pairing/status/123456')
  })

  it('getPairedDevices calls GET /mobile/pairing/list', async () => {
    await mobile.getPairedDevices()
    expect(mockGet).toHaveBeenCalledWith('/mobile/pairing/list')
  })

  it('revokePairing calls DELETE /mobile/pairing/{id}', async () => {
    await mobile.revokePairing('pair-123')
    expect(mockDelete).toHaveBeenCalledWith('/mobile/pairing/pair-123')
  })
})

// ===========================================================================
// negative-screen.ts
// ===========================================================================
describe('negative-screen API', () => {
  it('getNegativeScreenConfig calls GET /negative-screen', async () => {
    await negativeScreen.getNegativeScreenConfig()
    expect(mockGet).toHaveBeenCalledWith('/negative-screen')
  })

  it('updateNegativeScreenConfig calls PUT /negative-screen', async () => {
    await negativeScreen.updateNegativeScreenConfig({ enabled: true })
    expect(mockPut).toHaveBeenCalledWith('/negative-screen', { enabled: true })
  })

  it('testNegativeScreenPush calls POST /negative-screen/test', async () => {
    await negativeScreen.testNegativeScreenPush({ task_name: 'Test' })
    expect(mockPost).toHaveBeenCalledWith('/negative-screen/test', { task_name: 'Test' })
  })

  it('deleteNegativeScreenConfig calls DELETE /negative-screen', async () => {
    await negativeScreen.deleteNegativeScreenConfig()
    expect(mockDelete).toHaveBeenCalledWith('/negative-screen')
  })
})

// ===========================================================================
// logs-api.ts
// ===========================================================================
describe('logs-api API', () => {
  it('createWorkLog calls POST /logs-api', async () => {
    await logsApi.createWorkLog({ title: 'Daily work', category: 'dev' })
    expect(mockPost).toHaveBeenCalledWith('/logs-api', {
      title: 'Daily work',
      category: 'dev',
    })
  })

  it('getWorkLogs calls GET /logs-api with params', async () => {
    await logsApi.getWorkLogs({ category: 'dev', limit: 20 })
    expect(mockGet).toHaveBeenCalledWith('/logs-api', {
      params: { category: 'dev', limit: 20 },
    })
  })

  it('getDailySummary calls GET /logs-api/daily-summary', async () => {
    await logsApi.getDailySummary('2026-06-15')
    expect(mockGet).toHaveBeenCalledWith('/logs-api/daily-summary', {
      params: { date: '2026-06-15' },
    })
  })

  it('getDailySummary without date omits params', async () => {
    await logsApi.getDailySummary()
    expect(mockGet).toHaveBeenCalledWith('/logs-api/daily-summary', { params: undefined })
  })

  it('getWeeklyReport calls GET /logs-api/weekly-report', async () => {
    await logsApi.getWeeklyReport(1)
    expect(mockGet).toHaveBeenCalledWith('/logs-api/weekly-report', {
      params: { week_offset: 1 },
    })
  })

  it('getWorkLogStats calls GET /logs-api/stats', async () => {
    await logsApi.getWorkLogStats()
    expect(mockGet).toHaveBeenCalledWith('/logs-api/stats')
  })

  it('exportWorkLogs calls GET /logs-api/export', async () => {
    await logsApi.exportWorkLogs({ format: 'csv' })
    expect(mockGet).toHaveBeenCalledWith('/logs-api/export', {
      params: { format: 'csv' },
    })
  })
})

// ===========================================================================
// synonyms.ts
// ===========================================================================
describe('synonyms API', () => {
  it('getSynonymStats calls GET /synonyms/stats', async () => {
    await synonyms.getSynonymStats()
    expect(mockGet).toHaveBeenCalledWith('/synonyms/stats')
  })

  it('getAllSynonyms calls GET /synonyms', async () => {
    await synonyms.getAllSynonyms({ category: 'tech', limit: 50 })
    expect(mockGet).toHaveBeenCalledWith('/synonyms', {
      params: { category: 'tech', limit: 50 },
    })
  })

  it('getSynonyms calls GET /synonyms/{word}', async () => {
    await synonyms.getSynonyms('happy')
    expect(mockGet).toHaveBeenCalledWith('/synonyms/happy')
  })

  it('addSynonyms calls POST /synonyms', async () => {
    await synonyms.addSynonyms({ word: 'happy', synonyms: ['joyful', 'glad'] })
    expect(mockPost).toHaveBeenCalledWith('/synonyms', {
      word: 'happy',
      synonyms: ['joyful', 'glad'],
    })
  })

  it('setSynonyms calls PUT /synonyms', async () => {
    await synonyms.setSynonyms({ word: 'happy', synonyms: ['content'] })
    expect(mockPut).toHaveBeenCalledWith('/synonyms', {
      word: 'happy',
      synonyms: ['content'],
    })
  })

  it('removeSynonym calls DELETE /synonyms/{word}/synonyms/{synonym}', async () => {
    await synonyms.removeSynonym('happy', 'glad')
    expect(mockDelete).toHaveBeenCalledWith('/synonyms/happy/synonyms/glad')
  })

  it('deleteWord calls DELETE /synonyms/{word}', async () => {
    await synonyms.deleteWord('happy')
    expect(mockDelete).toHaveBeenCalledWith('/synonyms/happy')
  })

  it('getLLMConfig calls GET /synonyms/config/llm', async () => {
    await synonyms.getLLMConfig()
    expect(mockGet).toHaveBeenCalledWith('/synonyms/config/llm')
  })

  it('setLLMConfig calls PUT /synonyms/config/llm', async () => {
    await synonyms.setLLMConfig({ enabled: false, max_expansions: 3 })
    expect(mockPut).toHaveBeenCalledWith('/synonyms/config/llm', {
      enabled: false,
      max_expansions: 3,
    })
  })

  it('testSemanticSearch calls POST /synonyms/test-search', async () => {
    await synonyms.testSemanticSearch({ query: 'happy day', use_synonyms: true })
    expect(mockPost).toHaveBeenCalledWith('/synonyms/test-search', {
      query: 'happy day',
      use_synonyms: true,
    })
  })
})

// ===========================================================================
// groups.ts
// ===========================================================================
describe('groups API', () => {
  it('listGroups calls GET /groups', async () => {
    await groups.listGroups()
    expect(mockGet).toHaveBeenCalledWith('/groups')
  })

  it('getGroup calls GET /groups/{id}', async () => {
    await groups.getGroup('g1')
    expect(mockGet).toHaveBeenCalledWith('/groups/g1')
  })

  it('createGroup calls POST /groups', async () => {
    await groups.createGroup({ name: 'Admins' })
    expect(mockPost).toHaveBeenCalledWith('/groups', { name: 'Admins' })
  })

  it('updateGroup calls PUT /groups/{id}', async () => {
    await groups.updateGroup('g1', { name: 'Renamed' })
    expect(mockPut).toHaveBeenCalledWith('/groups/g1', { name: 'Renamed' })
  })

  it('deleteGroup calls DELETE /groups/{id}', async () => {
    await groups.deleteGroup('g1')
    expect(mockDelete).toHaveBeenCalledWith('/groups/g1')
  })

  it('listGroupMembers calls GET /groups/{id}/members', async () => {
    await groups.listGroupMembers('g1')
    expect(mockGet).toHaveBeenCalledWith('/groups/g1/members')
  })

  it('addGroupMember calls POST /groups/{id}/members', async () => {
    await groups.addGroupMember('g1', { username: 'alice' })
    expect(mockPost).toHaveBeenCalledWith('/groups/g1/members', { username: 'alice' })
  })

  it('removeGroupMember calls DELETE /groups/{id}/members/{memberId}', async () => {
    await groups.removeGroupMember('g1', 'm1')
    expect(mockDelete).toHaveBeenCalledWith('/groups/g1/members/m1')
  })
})

// ===========================================================================
// teams.ts
// ===========================================================================
describe('teams API', () => {
  it('listTeams calls GET /teams', async () => {
    await teams.listTeams()
    expect(mockGet).toHaveBeenCalledWith('/teams')
  })

  it('getTeam calls GET /teams/{id}', async () => {
    await teams.getTeam('t1')
    expect(mockGet).toHaveBeenCalledWith('/teams/t1')
  })

  it('createTeam calls POST /teams', async () => {
    await teams.createTeam({ name: 'Alpha' })
    expect(mockPost).toHaveBeenCalledWith('/teams', { name: 'Alpha' })
  })

  it('updateTeam calls PUT /teams/{id}', async () => {
    await teams.updateTeam('t1', { description: 'Updated' })
    expect(mockPut).toHaveBeenCalledWith('/teams/t1', { description: 'Updated' })
  })

  it('deleteTeam calls DELETE /teams/{id}', async () => {
    await teams.deleteTeam('t1')
    expect(mockDelete).toHaveBeenCalledWith('/teams/t1')
  })

  it('addTeamMembers calls POST /teams/{id}/members', async () => {
    await teams.addTeamMembers('t1', { members: ['alice', 'bob'] })
    expect(mockPost).toHaveBeenCalledWith('/teams/t1/members', { members: ['alice', 'bob'] })
  })
})

// ===========================================================================
// projects.ts
// ===========================================================================
describe('projects API', () => {
  it('listProjects calls GET /projects', async () => {
    await projects.listProjects()
    expect(mockGet).toHaveBeenCalledWith('/projects')
  })

  it('getProjectInfo calls GET /projects/{id}', async () => {
    await projects.getProjectInfo('p1')
    expect(mockGet).toHaveBeenCalledWith('/projects/p1')
  })

  it('listProjectTeams calls GET /projects/{id}/teams', async () => {
    await projects.listProjectTeams('p1')
    expect(mockGet).toHaveBeenCalledWith('/projects/p1/teams')
  })

  it('createProjectTeam calls POST /projects/{id}/teams', async () => {
    await projects.createProjectTeam('p1', { name: 'T' })
    expect(mockPost).toHaveBeenCalledWith('/projects/p1/teams', { name: 'T' })
  })

  it('addTeamMember calls POST /projects/{id}/teams/{tid}/members', async () => {
    await projects.addTeamMember('p1', 't1', { agent_id: 'a1' })
    expect(mockPost).toHaveBeenCalledWith('/projects/p1/teams/t1/members', { agent_id: 'a1' })
  })

  it('listProjectTasks calls GET /projects/{id}/tasks', async () => {
    await projects.listProjectTasks('p1')
    expect(mockGet).toHaveBeenCalledWith('/projects/p1/tasks')
  })

  it('createProjectTask calls POST /projects/{id}/tasks', async () => {
    await projects.createProjectTask('p1', {
      name: 'K',
      workflow_id: 'wf1',
      schedule_config: { type: 'cron', cron: '0 9 * * *' },
    })
    expect(mockPost).toHaveBeenCalledWith('/projects/p1/tasks', {
      name: 'K',
      workflow_id: 'wf1',
      schedule_config: { type: 'cron', cron: '0 9 * * *' },
    })
  })

  it('pause/resumeProjectTask call POST pause|resume', async () => {
    await projects.pauseProjectTask('p1', 't1')
    expect(mockPost).toHaveBeenCalledWith('/projects/p1/tasks/t1/pause')
    await projects.resumeProjectTask('p1', 't1')
    expect(mockPost).toHaveBeenCalledWith('/projects/p1/tasks/t1/resume')
  })

  it('createProject calls POST /projects', async () => {
    await projects.createProject({ name: 'New Project' })
    expect(mockPost).toHaveBeenCalledWith('/projects', { name: 'New Project' })
  })

  it('updateProject calls PUT /projects/{id}', async () => {
    await projects.updateProject('p1', { status: 'active' })
    expect(mockPut).toHaveBeenCalledWith('/projects/p1', { status: 'active' })
  })

  it('deleteProject calls DELETE /projects/{id}', async () => {
    await projects.deleteProject('p1')
    expect(mockDelete).toHaveBeenCalledWith('/projects/p1')
  })
})

// ===========================================================================
// providers.ts
// ===========================================================================
describe('providers API', () => {
  it('listProviders calls GET /providers', async () => {
    await providers.listProviders()
    expect(mockGet).toHaveBeenCalledWith('/providers')
  })

  it('getProvider calls GET /providers/{id}', async () => {
    await providers.getProvider('openai')
    expect(mockGet).toHaveBeenCalledWith('/providers/openai')
  })

  it('createProvider calls POST /providers', async () => {
    await providers.createProvider({ name: 'My Provider', provider_type: 'openai' })
    expect(mockPost).toHaveBeenCalledWith('/providers', { name: 'My Provider', provider_type: 'openai' })
  })

  it('updateProvider calls PUT /providers/{id}', async () => {
    await providers.updateProvider('openai', { api_key: 'sk-123' })
    expect(mockPut).toHaveBeenCalledWith('/providers/openai', { api_key: 'sk-123' })
  })

  it('deleteProvider calls DELETE /providers/{id}', async () => {
    await providers.deleteProvider('openai')
    expect(mockDelete).toHaveBeenCalledWith('/providers/openai')
  })

  it('getActiveModel calls GET /providers/active-model', async () => {
    await providers.getActiveModel()
    expect(mockGet).toHaveBeenCalledWith('/providers/active-model')
  })

  it('activateModel calls POST /providers/activate-model', async () => {
    await providers.activateModel({ provider_id: 'openai', model_id: 'gpt-4o' })
    expect(mockPost).toHaveBeenCalledWith('/providers/activate-model', { provider_id: 'openai', model_id: 'gpt-4o' })
  })

  it('testConnection calls POST /providers/{id}/check-connection', async () => {
    await providers.testConnection('openai')
    expect(mockPost).toHaveBeenCalledWith('/providers/openai/check-connection')
  })

  it('discoverModels calls GET /providers/{id}/models/discover', async () => {
    await providers.discoverModels('openai')
    expect(mockGet).toHaveBeenCalledWith('/providers/openai/models/discover')
  })
})

// ===========================================================================
// models.ts
// ===========================================================================
describe('models API', () => {
  it('listModels calls GET /models', async () => {
    await models.listModels()
    expect(mockGet).toHaveBeenCalledWith('/models')
  })

  it('getModel calls GET /models/{id}', async () => {
    await models.getModel('gpt-4o')
    expect(mockGet).toHaveBeenCalledWith('/models/gpt-4o')
  })

  it('deleteModel calls DELETE /models/{id}', async () => {
    await models.deleteModel('gpt-4o')
    expect(mockDelete).toHaveBeenCalledWith('/models/gpt-4o')
  })
})
