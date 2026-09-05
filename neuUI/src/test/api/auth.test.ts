import { describe, it, expect, beforeEach, vi } from 'vitest'
import { authAPI } from '@/api/auth'

// Mock request module
vi.mock('@/api', () => ({
  request: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn()
  }
}))

describe('Auth API 模块测试', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('login()', () => {
    it('应该正确调用登录API', async () => {
      const mockResponse = {
        code: 0,
        data: {
          token: 'mock-jwt-token',
          user: {
            id: '1',
            username: 'testuser',
            email: 'test@example.com'
          }
        }
      }

      const { request } = await import('@/api')
      ;(request.post as any).mockResolvedValue(mockResponse)

      const result = await authAPI.login({
        username: 'testuser',
        password: 'password123'
      })

      expect(request.post).toHaveBeenCalledWith('/auth/login', {
        username: 'testuser',
        password: 'password123'
      })
      expect(result).toEqual(mockResponse.data)
    })

    it('应该处理登录失败', async () => {
      const { request } = await import('@/api')
      ;(request.post as any).mockResolvedValue({
        code: 401,
        message: '用户名或密码错误'
      })

      await expect(authAPI.login({
        username: 'wronguser',
        password: 'wrongpass'
      })).rejects.toBeDefined()
    })
  })

  describe('register()', () => {
    it('应该正确调用注册API', async () => {
      const mockResponse = {
        code: 0,
        message: '注册成功'
      }

      const { request } = await import('@/api')
      ;(request.post as any).mockResolvedValue(mockResponse)

      const result = await authAPI.register({
        username: 'newuser',
        email: 'new@example.com',
        password: 'password123',
        confirmPassword: 'password123'
      })

      expect(request.post).toHaveBeenCalledWith('/auth/register', {
        username: 'newuser',
        email: 'new@example.com',
        password: 'password123',
        confirmPassword: 'password123'
      })
      expect(result).toEqual(mockResponse)
    })
  })

  describe('getCurrentUser()', () => {
    it('应该正确获取当前用户信息', async () => {
      const mockUser = {
        id: '1',
        username: 'testuser',
        email: 'test@example.com',
        role: 'user'
      }

      const { request } = await import('@/api')
      ;(request.get as any).mockResolvedValue({
        code: 0,
        data: mockUser
      })

      const result = await authAPI.getCurrentUser()

      expect(request.get).toHaveBeenCalledWith('/auth/me')
      expect(result).toEqual(mockUser)
    })
  })

  describe('changePassword()', () => {
    it('应该正确调用修改密码API', async () => {
      const mockResponse = {
        code: 0,
        message: '密码修改成功'
      }

      const { request } = await import('@/api')
      ;(request.post as any).mockResolvedValue(mockResponse)

      const result = await authAPI.changePassword({
        old_password: 'oldpass123',
        new_password: 'newpass123'
      })

      expect(request.post).toHaveBeenCalledWith('/auth/change-password', {
        old_password: 'oldpass123',
        new_password: 'newpass123'
      })
      expect(result).toEqual(mockResponse)
    })
  })
})
