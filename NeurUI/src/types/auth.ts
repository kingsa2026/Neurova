export interface User {
  id: string
  username: string
  email: string
  role: 'admin' | 'user' | 'viewer'
  status: 'active' | 'inactive' | 'banned'
  /** 用户组功能模块白名单（后端 /auth/me 返回；空数组/缺省 = 不限制） */
  allowed_modules?: string[]
  avatar?: string
  createdAt?: string
}

export interface LoginForm {
  username: string
  password: string
  remember?: boolean
}

export interface RegisterForm {
  username: string
  email?: string
  password: string
  confirmPassword: string
  code?: string
}

export interface AuthTokens {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}
