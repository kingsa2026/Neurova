// 认证相关类型定义

export interface LoginRequest {
  username: string
  password: string
  remember?: boolean
}

export interface RegisterRequest {
  username: string
  email: string
  password: string
  confirmPassword: string
  agreed_terms?: boolean
  agreed_privacy?: boolean
  register_source?: string
}

export interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface UserInfo {
  id: string
  username: string
  email?: string
  avatar?: string
  role?: string
  status?: string
  createdAt?: string
  created_at?: string
}

// 后端统一响应格式
export interface ApiResponse<T> {
  success: boolean
  code: number
  message: string
  data: T
}
