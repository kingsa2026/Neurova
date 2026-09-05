import axios from 'axios'
import type { LoginRequest, RegisterRequest, AuthResponse, ApiResponse } from '@/types/auth'
&nbsp;
const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'
&nbsp;
const apiClient = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})
&nbsp;
apiClient.interceptors.request.use((config) =&gt; {
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
&nbsp;
apiClient.interceptors.response.use(
  (response) =&gt; response.data,
  (error) =&gt; Promise.reject(error)
)
&nbsp;
export interface SendCodeRequest {
  email: string
  purpose: 'register' | 'forgot_password' | 'change_email'
  invite_code?: string
}
&nbsp;
export interface VerifyCodeRequest {
  email: string
  code: string
  purpose: 'register' | 'forgot_password'
}
&nbsp;
export interface ChangePasswordRequest {
  old_password: string
  new_password: string
}
&nbsp;
export interface ResetPasswordRequest {
  email: string
  code: string
  new_password: string
}
&nbsp;
export interface DeactivateAccountRequest {
  password: string
  reason?: string
}
&nbsp;
export interface AccountStatus {
  username: string
  email?: string
  status: string
  email_verified: boolean
  created_at: string
  activated_at?: string
}
&nbsp;
export interface RefreshResponse {
  access_token: string
  refresh_token?: string
  expires_in: number
  token_type: string
}
&nbsp;
export interface TokenRefreshRequest {
  refresh_token: string
}
&nbsp;
export const authAPI = {
  login: (data: LoginRequest): Promise&lt;ApiResponse&lt;AuthResponse&gt;&gt; =&gt; 
    apiClient.post('/auth/login', data),
&nbsp;
  register: (data: RegisterRequest): Promise&lt;ApiResponse&lt;AuthResponse&gt;&gt; =&gt; 
    apiClient.post('/auth/register', data),
&nbsp;
  logout: (): Promise&lt;ApiResponse&lt;null&gt;&gt; =&gt; 
    apiClient.post('/auth/logout'),
&nbsp;
  getCurrentUser: (): Promise&lt;ApiResponse&lt;AuthResponse['user']&gt;&gt; =&gt; 
    apiClient.get('/auth/me'),
&nbsp;
  refresh: (data: TokenRefreshRequest): Promise&lt;ApiResponse&lt;RefreshResponse&gt;&gt; =&gt; 
    apiClient.post('/auth/refresh', data),
&nbsp;
  sendRegisterCode: (data: SendCodeRequest): Promise&lt;ApiResponse&lt;{email: string, expires_in: number}&gt;&gt; =&gt; 
    apiClient.post('/auth/register/send-code', data),
&nbsp;
  verifyRegisterCode: (data: VerifyCodeRequest): Promise&lt;ApiResponse&lt;{verified: boolean}&gt;&gt; =&gt; 
    apiClient.post('/auth/register/verify-code', data),
&nbsp;
  forgotPassword: (email: string): Promise&lt;ApiResponse&lt;{email: string}&gt;&gt; =&gt; 
    apiClient.post('/auth/forgot-password', { email }),
&nbsp;
  resetPassword: (data: ResetPasswordRequest): Promise&lt;ApiResponse&lt;{email: string}&gt;&gt; =&gt; 
    apiClient.post('/auth/reset-password', data),
&nbsp;
  changePassword: (data: ChangePasswordRequest): Promise&lt;ApiResponse&lt;{username: string}&gt;&gt; =&gt; 
    apiClient.post('/auth/change-password', data),
&nbsp;
  getAccountStatus: (): Promise&lt;ApiResponse&lt;AccountStatus&gt;&gt; =&gt; 
    apiClient.get('/auth/account/status'),
&nbsp;
  deactivateAccount: (data: DeactivateAccountRequest): Promise&lt;ApiResponse&lt;{username: string, deactivated: boolean}&gt;&gt; =&gt; 
    apiClient.post('/auth/account/deactivate', data),
}
&nbsp;
export default authAPI
&nbsp;