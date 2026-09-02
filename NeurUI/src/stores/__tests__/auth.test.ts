import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'

vi.mock('@/api/auth', () => ({
  authAPI: {
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    getCurrentUser: vi.fn(),
    setupStatus: vi.fn(),
    setupRegister: vi.fn(),
  },
}))

import { authAPI } from '@/api/auth'

describe('useAuthStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('starts unauthenticated', () => {
    const store = useAuthStore()
    expect(store.isAuthenticated).toBe(false)
    expect(store.token).toBe(null)
    expect(store.user).toBe(null)
  })

  it('login validates empty username', async () => {
    const store = useAuthStore()
    const result = await store.login({ username: '', password: 'pass' })
    expect(result).toBe(false)
    expect(store.error).toContain('required')
  })

  it('login validates empty password', async () => {
    const store = useAuthStore()
    const result = await store.login({ username: 'user', password: '' })
    expect(result).toBe(false)
    expect(store.error).toContain('required')
  })

  it('login succeeds with valid credentials', async () => {
    vi.mocked(authAPI.login).mockResolvedValue({
      access_token: 'test-token',
      refresh_token: 'test-refresh',
    } as any)
    vi.mocked(authAPI.getCurrentUser).mockResolvedValue({
      user_id: '1',
      username: 'testuser',
      email: 'test@example.com',
      role: 'user',
    } as any)

    const store = useAuthStore()
    const result = await store.login({ username: 'testuser', password: 'password123' })

    expect(result).toBe(true)
    expect(store.isAuthenticated).toBe(true)
    expect(store.token).toBe('test-token')
  })

  it('login handles API errors', async () => {
    vi.mocked(authAPI.login).mockRejectedValue(new Error('Invalid credentials'))

    const store = useAuthStore()
    const result = await store.login({ username: 'user', password: 'wrong' })

    expect(result).toBe(false)
    expect(store.error).toBe('Invalid credentials')
  })

  it('register validates username', async () => {
    const store = useAuthStore()
    const result = await store.register({
      username: 'ab',
      email: 'test@example.com',
      password: 'Str0ng!Pass',
      confirmPassword: 'Str0ng!Pass',
    })
    expect(result).toBe(false)
    expect(store.error).toContain('Username')
  })

  it('register validates email', async () => {
    const store = useAuthStore()
    const result = await store.register({
      username: 'validuser',
      email: 'notanemail',
      password: 'Str0ng!Pass',
      confirmPassword: 'Str0ng!Pass',
    })
    expect(result).toBe(false)
    expect(store.error).toContain('email')
  })

  it('register validates password match', async () => {
    const store = useAuthStore()
    const result = await store.register({
      username: 'validuser',
      email: 'test@example.com',
      password: 'Str0ng!Pass',
      confirmPassword: 'Different!Pass1',
    })
    expect(result).toBe(false)
    expect(store.error).toContain('match')
  })

  it('register succeeds with valid form', async () => {
    vi.mocked(authAPI.register).mockResolvedValue({
      tokens: { access_token: 'token', refresh_token: 'refresh' },
      user: { id: '1', username: 'newuser', email: 'new@example.com' },
    } as any)

    const store = useAuthStore()
    const result = await store.register({
      username: 'newuser',
      email: 'new@example.com',
      password: 'Str0ng!Pass',
      confirmPassword: 'Str0ng!Pass',
    })

    expect(result).toBe(true)
    expect(store.isAuthenticated).toBe(true)
  })

  it('register without email succeeds (email optional)', async () => {
    vi.mocked(authAPI.register).mockResolvedValue({
      tokens: { access_token: 'token', refresh_token: 'refresh' },
      user: { id: '1', username: 'noemail' },
    } as any)

    const store = useAuthStore()
    const result = await store.register({
      username: 'noemail',
      password: 'Str0ng!Pass',
      confirmPassword: 'Str0ng!Pass',
    })

    expect(result).toBe(true)
    expect(store.isAuthenticated).toBe(true)
  })

  it('register accepts flat backend contract (access_token at data top level)', async () => {
    // 后端 POST /auth/register 实际返回 {code,message,data:{user_id,username,access_token,refresh_token}}
    vi.mocked(authAPI.register).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        user_id: '1',
        username: 'flatuser',
        access_token: 'flat-token',
        refresh_token: 'flat-refresh',
      },
    } as any)
    vi.mocked(authAPI.getCurrentUser).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { user_id: '1', username: 'flatuser', role: 'admin' },
    } as any)

    const store = useAuthStore()
    const result = await store.register({
      username: 'flatuser',
      password: 'Str0ng!Pass',
      confirmPassword: 'Str0ng!Pass',
    })

    expect(result).toBe(true)
    expect(store.token).toBe('flat-token')
    expect(store.isAuthenticated).toBe(true)
  })

  it('logout clears state', async () => {
    vi.mocked(authAPI.logout).mockResolvedValue({ code: 0, message: 'ok', data: null })

    const store = useAuthStore()
    await store.logout()

    expect(store.isAuthenticated).toBe(false)
    expect(store.token).toBe(null)
    expect(store.user).toBe(null)
  })

  it('logout clears state even on API error', async () => {
    vi.mocked(authAPI.logout).mockRejectedValue(new Error('network'))

    const store = useAuthStore()
    await store.logout()

    expect(store.isAuthenticated).toBe(false)
  })

  it('fetchCurrentUser returns null when not authenticated', async () => {
    const store = useAuthStore()
    const result = await store.fetchCurrentUser()
    expect(result).toBe(null)
  })
})
