import axios from 'axios'
import type { LoginRequest, RegisterRequest, AuthResponse, ApiResponse } from '@/types/auth'
 
const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'
 
const apiClient = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})
 
apiClient.interceptors.request.use((config) => {
  // 登录和注册请求不添加 token
  const url = config.url || ''
  if (url.includes('/auth/login') || url.includes('/auth/register')) {
    console.log('[authAPI] 跳过 token（登录/注册请求）:', url)
    return config
  }
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
    console.log('[authAPI] 添加 token:', { url, hasToken: true })
  } else {
    console.log('[authAPI] 无 token:', { url })
  }
  return config
})
 
apiClient.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(error)
)
 
export interface SendCodeRequest {
  email: string
  purpose: 'register' | 'forgot_password' | 'change_email'
  invite_code?: string
}
 
export interface VerifyCodeRequest {
  email: string
  code: string
  purpose: 'register' | 'forgot_password'
}
 
export interface ChangePasswordRequest {
  old_password: string
  new_password: string
}
 
export interface ResetPasswordRequest {
  email: string
  code: string
  new_password: string
}
 
export interface DeactivateAccountRequest {
  password: string
  reason?: string
}
 
export interface AccountStatus {
  username: string
  email?: string
  status: string
  email_verified: boolean
  created_at: string
  activated_at?: string
}
 
export interface RefreshResponse {
  access_token: string
  refresh_token?: string
  expires_in: number
  token_type: string
}
 
export interface TokenRefreshRequest {
  refresh_token: string
}
 
export const authAPI = {
  login: (data: LoginRequest): Promise<ApiResponse<AuthResponse>> => 
    apiClient.post('/auth/login', data),
 
  register: (data: RegisterRequest): Promise<ApiResponse<AuthResponse>> => 
    apiClient.post('/auth/register', data),
 
  logout: (): Promise<ApiResponse<null>> => 
    apiClient.post('/auth/logout'),
 
  getCurrentUser: (): Promise<ApiResponse<AuthResponse['user']>> => 
    apiClient.get('/auth/me'),
 
  refresh: (data: TokenRefreshRequest): Promise<ApiResponse<RefreshResponse>> => 
    apiClient.post('/auth/refresh', data),
 
  sendRegisterCode: (data: SendCodeRequest): Promise<ApiResponse<{email: string, expires_in: number}>> => 
    apiClient.post('/auth/register/send-code', data),
 
  verifyRegisterCode: (data: VerifyCodeRequest): Promise<ApiResponse<{verified: boolean}>> => 
    apiClient.post('/auth/register/verify-code', data),
 
  forgotPassword: (email: string): Promise<ApiResponse<{email: string}>> => 
    apiClient.post('/auth/forgot-password', { email }),
 
  resetPassword: (data: ResetPasswordRequest): Promise<ApiResponse<{email: string}>> => 
    apiClient.post('/auth/reset-password', data),
 
  changePassword: (data: ChangePasswordRequest): Promise<ApiResponse<{username: string}>> => 
    apiClient.post('/auth/change-password', data),
 
  getAccountStatus: (): Promise<ApiResponse<AccountStatus>> => 
    apiClient.get('/auth/account/status'),
 
  deactivateAccount: (data: DeactivateAccountRequest): Promise<ApiResponse<{username: string, deactivated: boolean}>> => 
    apiClient.post('/auth/account/deactivate', data),
}
 
export default authAPI
 