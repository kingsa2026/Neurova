import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authAPI } from '@/api/auth'
import { secureStorage, validateUsername, validateEmail, validatePasswordStrength } from '@/utils/security'
import type { User, LoginForm, RegisterForm, AuthTokens } from '@/types/auth'

const TOKEN_KEY = 'auth_token'
const REFRESH_TOKEN_KEY = 'refresh_token'
const USER_KEY = 'user'

export const useAuthStore = defineStore('auth', () => {
  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  const token = ref<string | null>(secureStorage.get(TOKEN_KEY))
  const refreshToken = ref<string | null>(secureStorage.get(REFRESH_TOKEN_KEY))
  const user = ref<User | null>(secureStorage.getObject<User | null>(USER_KEY, null))
  const loading = ref<boolean>(false)
  const error = ref<string | null>(null)

  // ---------------------------------------------------------------------------
  // Computed
  // ---------------------------------------------------------------------------
  const isAuthenticated = computed(() => !!token.value)
  const currentUser = computed(() => user.value)

  // ---------------------------------------------------------------------------
  // Internal helpers
  // ---------------------------------------------------------------------------

  function persistTokens(tokens: AuthTokens): void {
    token.value = tokens.access_token
    refreshToken.value = tokens.refresh_token
    secureStorage.set(TOKEN_KEY, tokens.access_token)
    secureStorage.set(REFRESH_TOKEN_KEY, tokens.refresh_token)
  }

  function clearAuth(): void {
    token.value = null
    refreshToken.value = null
    user.value = null
    error.value = null
    secureStorage.remove(TOKEN_KEY)
    secureStorage.remove(REFRESH_TOKEN_KEY)
    secureStorage.remove(USER_KEY)
  }

  function persistUser(u: User): void {
    user.value = u
    secureStorage.setObject(USER_KEY, u)
  }

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  /**
   * Log in with username/email and password.
   */
  async function login(form: LoginForm): Promise<boolean> {
    error.value = null

    // Basic client-side validation
    const identifier = form.username.trim()
    if (!identifier) {
      error.value = 'Username or email is required.'
      return false
    }
    if (!form.password) {
      error.value = 'Password is required.'
      return false
    }

    loading.value = true
    try {
      const res = await authAPI.login({ ...form, username: identifier })
      const data = (res as any)?.data ?? res
      if (data?.access_token) {
        persistTokens(data as AuthTokens)
        await fetchCurrentUser()
        return true
      }
      error.value = (res as any)?.message || 'Login failed.'
      return false
    } catch (err: any) {
      error.value = err?.response?.data?.message || err?.message || 'Login failed. Please try again.'
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * Register a new user account.
   */
  async function register(
    form: RegisterForm & {
      agreed_terms?: boolean
      agreed_privacy?: boolean
      register_source?: string
    },
  ): Promise<boolean> {
    error.value = null

    // Client-side validation
    if (!validateUsername(form.username)) {
      error.value = 'Username must be 3-20 characters (letters, numbers, underscores).'
      return false
    }
    if (!validateEmail(form.email)) {
      error.value = 'Please enter a valid email address.'
      return false
    }
    const pwCheck = validatePasswordStrength(form.password)
    if (!pwCheck.valid) {
      error.value = pwCheck.feedback
      return false
    }
    if (form.password !== form.confirmPassword) {
      error.value = 'Passwords do not match.'
      return false
    }

    loading.value = true
    try {
      const res = await authAPI.register({
        ...form,
        agreed_terms: form.agreed_terms ?? true,
        agreed_privacy: form.agreed_privacy ?? true,
        register_source: form.register_source ?? 'web',
      })
      const data = (res as any)?.data ?? res
      if (data?.tokens) {
        persistTokens(data.tokens)
        if (data.user) persistUser(data.user)
        return true
      }
      error.value = (res as any)?.message || 'Registration failed.'
      return false
    } catch (err: any) {
      error.value = err?.response?.data?.message || err?.message || 'Registration failed. Please try again.'
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * Persist tokens obtained directly from a registration response
   * (first-install wizard: register returns tokens, skipping a second login call).
   */
  function setTokensFromRegistration(tokens: Pick<AuthTokens, 'access_token' | 'refresh_token'>): void {
    persistTokens(tokens as AuthTokens)
  }

  /**
   * Log out: invalidate server token and clear local state.
   */
  async function logout(): Promise<void> {
    try {
      await authAPI.logout()
    } catch {
      // Ignore errors during logout - clear local state regardless
    } finally {
      clearAuth()
    }
  }

  /**
   * Fetch the currently authenticated user's profile from the server.
   */
  async function fetchCurrentUser(): Promise<User | null> {
    if (!token.value) return null

    loading.value = true
    try {
      const res = await authAPI.getCurrentUser()
      const data = (res as any)?.data ?? res
      // Backend returns { user_id, username, role, ... } — check for user_id or username
      if (data && typeof data === 'object' && ('user_id' in data || 'username' in data)) {
        const user: User = {
          id: String(data.user_id || data.id || ''),
          username: data.username || '',
          email: data.email || '',
          role: data.role || 'user',
          status: data.status || 'active',
          createdAt: data.created_at,
        }
        persistUser(user)
        return user
      }
      return null
    } catch {
      // If fetching user fails, do not clear auth - the token might still be valid
      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * Restore user from persisted storage (called on app init).
   */
  function restoreUser(): void {
    const savedToken = secureStorage.get(TOKEN_KEY)
    const savedRefresh = secureStorage.get(REFRESH_TOKEN_KEY)
    const savedUser = secureStorage.getObject<User | null>(USER_KEY, null)

    if (savedToken) {
      token.value = savedToken
      refreshToken.value = savedRefresh
      user.value = savedUser
    }
  }

  return {
    // state
    token,
    refreshToken,
    user,
    loading,
    error,
    // computed
    isAuthenticated,
    currentUser,
    // actions
    login,
    register,
    setTokensFromRegistration,
    logout,
    fetchCurrentUser,
    restoreUser,
    clearAuth,
  }
})
