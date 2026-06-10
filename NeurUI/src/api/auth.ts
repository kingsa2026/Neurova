import { api } from './index'
import type { LoginForm, RegisterForm, AuthTokens } from '@/types/auth'
import type { User } from '@/types/auth'

interface ApiResponse<T = unknown> {
  code: number
  success: boolean
  message: string
  data: T
}

export const authAPI = {
  /**
   * Authenticate with username/email and password.
   */
  login: (data: LoginForm) => api.post<ApiResponse<AuthTokens>>('/auth/login', data),

  /**
   * Register a new user account.
   */
  register: (
    data: RegisterForm & {
      agreed_terms: boolean
      agreed_privacy: boolean
      register_source: string
    },
  ) => api.post<ApiResponse<{ user: User; tokens: AuthTokens }>>('/auth/register', data),

  /**
   * Log out the current user (server-side token invalidation).
   */
  logout: () => api.post<ApiResponse<null>>('/auth/logout'),

  /**
   * Refresh an expired access token using a refresh token.
   */
  refreshToken: (refreshToken: string) =>
    api.post<ApiResponse<AuthTokens>>('/auth/refresh', { refresh_token: refreshToken }),

  /**
   * Fetch the currently authenticated user's profile.
   */
  getCurrentUser: () => api.get<ApiResponse<User>>('/auth/me'),

  /**
   * Send a verification code to the given email (for registration).
   */
  sendCode: (email: string) => api.post<ApiResponse<null>>('/auth/register/send-code', { email }),

  /**
   * Verify an email code during registration.
   */
  verifyCode: (email: string, code: string) =>
    api.post<ApiResponse<{ verified: boolean }>>('/auth/register/verify-code', { email, code }),
}

export default authAPI
