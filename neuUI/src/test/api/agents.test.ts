import { describe, it, expect, beforeEach, vi } from 'vitest'
import { agentAPI } from '@/api/modules/agents'

// Mock request module
vi.mock('@/api', () => ({
  request: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn()
  }
}))

describe('Agent API 模块测试', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('list()', () => {
    it('应该正确获取Agent列表', async () => {
      const mockAgents = [
        { id: '1', name: 'Agent 1', status: 'active' },
        { id: '2', name: 'Agent 2', status: 'inactive' }
      ]

      const { request } = await import('@/api')
      ;(request.get as any).mockResolvedValue({
        code: 0,
        data: { agents: mockAgents }
      })

      const result = await agentAPI.list()

      expect(request.get).toHaveBeenCalledWith('/agents')
      expect(result).toEqual(mockAgents)
    })
  })

  describe('get()', () => {
    it('应该正确获取单个Agent详情', async () => {
      const mockAgent = {
        id: '1',
        name: 'Test Agent',
        description: 'A test agent',
        status: 'active'
      }

      const { request } = await import('@/api')
      ;(request.get as any).mockResolvedValue({
        code: 0,
        data: mockAgent
      })

      const result = await agentAPI.get('1')

      expect(request.get).toHaveBeenCalledWith('/agents/1')
      expect(result).toEqual(mockAgent)
    })
  })

  describe('create()', () => {
    it('应该正确创建新Agent', async () => {
      const newAgent = {
        name: 'New Agent',
        description: 'Description',
        model: 'gpt-4'
      }

      const mockResponse = {
        id: '3',
        ...newAgent,
        status: 'active'
      }

      const { request } = await import('@/api')
      ;(request.post as any).mockResolvedValue({
        code: 0,
        data: mockResponse
      })

      const result = await agentAPI.create(newAgent)

      expect(request.post).toHaveBeenCalledWith('/agents', newAgent)
      expect(result).toEqual(mockResponse)
    })
  })

  describe('delete()', () => {
    it('应该正确删除Agent', async () => {
      const mockResponse = {
        code: 0,
        message: 'Agent deleted successfully'
      }

      const { request } = await import('@/api')
      ;(request.delete as any).mockResolvedValue(mockResponse)

      await agentAPI.delete('1')

      expect(request.delete).toHaveBeenCalledWith('/agents/1')
    })
  })

  describe('getStats()', () => {
    it('应该正确获取Agent统计信息', async () => {
      const mockStats = {
        totalConversations: 100,
        totalMessages: 5000,
        avgResponseTime: 1.5,
        successRate: 0.95
      }

      const { request } = await import('@/api')
      ;(request.get as any).mockResolvedValue({
        code: 0,
        data: mockStats
      })

      const result = await agentAPI.getStats('1')

      expect(request.get).toHaveBeenCalledWith('/agents/1/stats')
      expect(result).toEqual(mockStats)
    })
  })
})
