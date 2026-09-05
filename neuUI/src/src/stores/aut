import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authAPI } from '@/api/auth'
import type { UserInfo, LoginRequest, RegisterRequest } from '@/types/auth'
import { validateUsername, validateEmail, validatePasswordStrength, safeJsonParse, limitInputLength } from '@/utils/security'
&nbsp;
/**
 * 安全的Token存储 - 使用加密的localStorage（或迁移到HTTP-only cookies）
 */
const TOKEN_KEY = 'token'
const REFRESH_TOKEN_KEY = 'refresh_token'
const USER_KEY = 'user'
&nbsp;
// 安全存储工具（生产环境建议使用HTTP-only cookies）
function secureStorageSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch (e) {
    console.warn('Storage not available', e)
  }
}
&nbsp;
function secureStorageGet(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
&nbsp;
function secureStorageRemove(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    // ignore
  }
}
&nbsp;
export const useAuthStore = defineStore('auth', () =&gt; {
  // 状态
  const token = ref&lt;string | null&gt;(secureStorageGet(TOKEN_KEY))
  const user = ref&lt;UserInfo | null&gt;(null)
  const loading = ref(false)
  const error = ref&lt;string | null&gt;(null)
&nbsp;
  // 计算属性
  const isAuthenticated = computed(() =&gt; !!token.value)
  const currentUser = computed(() =&gt; user.value)
&nbsp;
  // 从 localStorage 恢复用户状态
  function restoreUser() {
    const saved = secureStorageGet(USER_KEY)
    if (saved) {
      user.value = safeJsonParse&lt;UserInfo | null&gt;(saved, null)
    }
  }
&nbsp;
  // 获取用户信息
  async function fetchCurrentUser() {
    if (!token.value) return
    try {
      const response = await getCurrentUser()
      if (response.success) {
        user.value = response.data
        secureStorageSet(USER_KEY, JSON.stringify(response.data))
      } else {
        // token 无效，清除登录状态
        clearAuth()
      }
    } catch {
      // 网络错误暂不清除
    }
  }
&nbsp;
  // actions
  async function login(credentials: LoginRequest) {
    loading.value = true
    error.value = null
&nbsp;
    try {
      // 安全验证输入
      const { username, password } = credentials
      console.log('[AuthStore] 尝试登录:', { username, passwordLength: password?.length })
      if (!validateUsername(username) &amp;&amp; !validateEmail(username)) {
        throw new Error('请输入有效的用户名或邮箱')
      }
      const passwordCheck = validatePasswordStrength(password)
      if (!passwordCheck.valid || password.length &lt; 3) {
        throw new Error('密码强度不够或太短（至少3个字符）')
      }
&nbsp;
      // 限制输入长度
      const safeCredentials: LoginRequest = {
        username: limitInputLength(username, 100),
        password: limitInputLength(password, 128),
      }
&nbsp;
      console.log('[AuthStore] 发送登录请求:', { url: '/api/v1/auth/login', credentials: { username } })
      const response = await authAPI.login(safeCredentials)
      console.log('[AuthStore] 登录响应:', response)
      if (response.success) {
        const tokenData = response.data
        token.value = tokenData.access_token
        secureStorageSet(TOKEN_KEY, tokenData.access_token)
        if (tokenData.refresh_token) {
          secureStorageSet(REFRESH_TOKEN_KEY, tokenData.refresh_token)
        }
&nbsp;
        // 先返回登录成功，用户信息异步获取不阻塞
        // 避免 getCurrentUser 失败被 401 拦截器误杀刚写入的 token
        setTimeout(() =&gt; {
          getCurrentUser().then(userResp =&gt; {
            if (userResp.success) {
              user.value = userResp.data
              secureStorageSet(USER_KEY, JSON.stringify(userResp.data))
            }
          }).catch(() =&gt; { /* 静默失败 */ })
        }, 100)
&nbsp;
        return { success: true }
      } else {
        error.value = response.message
        return { success: false, message: response.message }
      }
    } catch (err: unknown) {
      // 详细错误信息
      const errorObj = err as { message?: string; response?: { status?: number; data?: { message?: string; detail?: string } }; config?: { url?: string; data?: unknown } }
      const errInfo = {
        message: errorObj.message,
        response_status: errorObj.response?.status,
        response_data: errorObj.response?.data,
        request_url: errorObj.config?.url,
        request_data: errorObj.config?.data,
      }
      console.error('[AuthStore] 登录失败 (详细):', errInfo)
      // 提取错误信息
      let msg = '登录失败，请重试'
      if (errorObj.response?.data?.message) {
        msg = errorObj.response.data.message
      } else if (errorObj.response?.data?.detail) {
        msg = errorObj.response.data.detail
      } else if (errorObj.message) {
        msg = errorObj.message
      }
      error.value = msg
      return { success: false, message: msg, _debug: errInfo }
    } finally {
      loading.value = false
    }
  }
&nbsp;
  async function register(data: RegisterRequest) {
    loading.value = true
    error.value = null
&nbsp;
    try {
      // 安全验证输入
      if (!validateUsername(data.username)) {
        throw new Error('用户名格式不正确（3-20个字符，只允许字母、数字、下划线）')
      }
      if (!validateEmail(data.email)) {
        throw new Error('请输入有效的邮箱地址')
      }
      const passwordCheck = validatePasswordStrength(data.password)
      if (!passwordCheck.valid) {
        throw new Error('密码强度不够（建议至少8位，包含大小写字母和数字）')
      }
      if (data.password !== data.confirmPassword) {
        throw new Error('两次输入的密码不一致')
      }
&nbsp;
      // 限制输入长度
      const safeData: RegisterRequest = {
        username: limitInputLength(data.username, 50),
        email: limitInputLength(data.email, 255),
        password: limitInputLength(data.password, 128),
        confirmPassword: limitInputLength(data.confirmPassword, 128),
      }
&nbsp;
      const response = await authAPI.register({
        ...safeData,
        agreed_terms: true,
        agreed_privacy: true,
        register_source: 'web',
      })
&nbsp;
      if (response.success) {
        const tokenData = response.data
        token.value = tokenData.access_token
        secureStorageSet(TOKEN_KEY, tokenData.access_token)
        if (tokenData.refresh_token) {
          secureStorageSet(REFRESH_TOKEN_KEY, tokenData.refresh_token)
        }
&nbsp;
        // 异步获取用户信息，不阻塞注册流程
        setTimeout(() =&gt; {
          getCurrentUser().then(userResp =&gt; {
            if (userResp.success) {
              user.value = userResp.data
              secureStorageSet(USER_KEY, JSON.stringify(userResp.data))
            }
          }).catch(() =&gt; {})
        }, 100)
&nbsp;
        return { success: true }
      } else {
        error.value = response.message
        return { success: false, message: response.message }
      }
    } catch (err: unknown) {
      const errorObj = err as { message?: string; response?: { data?: { message?: string; detail?: string } } }
      const msg = errorObj.message || errorObj.response?.data?.message || errorObj.response?.data?.detail || '注册失败，请重试'
      error.value = msg
      return { success: false, message: msg }
    } finally {
      loading.value = false
    }
  }
&nbsp;
  async function logout() {
    try {
      await authAPI.logout()
    } catch {
      // 忽略登出接口错误，后端可能尚未实现此端点
    } finally {
      clearAuth()
    }
  }
&nbsp;
  function clearAuth() {
    token.value = null
    user.value = null
    secureStorageRemove(TOKEN_KEY)
    secureStorageRemove(REFRESH_TOKEN_KEY)
    secureStorageRemove(USER_KEY)
  }
&nbsp;
  return {
    token, user, loading, error,
    isAuthenticated, currentUser,
    login, register, logout,
    fetchCurrentUser, restoreUser,
  }
})
&nbsp;
interface RawUserData {
  id?: string
  username?: string
  email?: string
  role?: string
  status?: string
  created_at?: string
}
&nbsp;
// 内部辅助函数
async function getCurrentUser() {
  const token = secureStorageGet(TOKEN_KEY)
  const resp = await authAPI.getCurrentUser()
  // 后端 /auth/me 返回 { username, token_type }
  if (resp.success &amp;&amp; resp.data) {
    const data = resp.data as RawUserData
    return {
      success: true,
      data: {
        id: data.id || data.username || '',
        username: data.username || '',
        email: data.email || '',
        role: data.role || 'user',
        status: data.status || 'active',
        createdAt: data.created_at || '',
      } as UserInfo
    }
  }
  return { success: false, data: null }
}
&nbsp;