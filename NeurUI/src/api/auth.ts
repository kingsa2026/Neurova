import { api } from './index'
import type { LoginForm, RegisterForm, AuthTokens } from '@/types/auth'
import type { User } from '@/types/auth'
import type { ApiResponse } from '@/types/response'

export const authAPI = {
  /**
   * Check first-install setup status (public): whether no user exists yet.
   * Desktop shell first-launch wizard shows the admin-creation form when true.
   */
  setupStatus: () => api.get<ApiResponse<{ needs_setup: boolean }>>('/auth/setup-status'),

  /**
   * First-install admin registration (no email, no verification code).
   * Backend assigns admin role when no user exists yet.
   */
  setupRegister: (data: { username: string; password: string }) =>
    api.post<
      ApiResponse<{ user_id: string; username: string; access_token: string; refresh_token: string }>
    >('/auth/register', data),

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
