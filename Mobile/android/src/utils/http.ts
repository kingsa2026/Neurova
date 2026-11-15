/**
 * axios 实例：动态服务器档案 base + Bearer + X-Request-ID + 401 单飞刷新。
 * 对齐 NeurUI/src/api/index.ts 的刷新语义（设计方案 §5.1），但依赖更轻。
 */
import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { useServersStore } from '@/stores/servers'
import { STORAGE_KEYS, storageGet, storageGetJson, storageRemove, storageSet } from '@/utils/session'

declare module 'axios' {
  export interface AxiosRequestConfig {
    /** 调用方可声明"预期失败状态码"，拦截器降级为 debug 不刷 error */
    __expectedStatus?: number | number[]
  }
}

let refreshInFlight: Promise<string> | null = null
let authFailureHandler: (() => void) | null = null

/** 登录失效时的回调（由 auth store 注册，避免循环依赖） */
export function onAuthFailure(handler: () => void) {
  authFailureHandler = handler
}

async function getAccessToken(): Promise<string> {
  return (await storageGet(STORAGE_KEYS.accessToken)) ?? ''
}

async function refreshAccessToken(): Promise<string> {
  refreshInFlight ??= (async () => {
    const servers = useServersStore()
    const refreshToken = (await storageGet(STORAGE_KEYS.refreshToken)) ?? ''
    if (!refreshToken) throw new Error('no refresh token')
    const r = await fetch(`${servers.apiBase}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!r.ok) throw new Error(`refresh failed: ${r.status}`)
    const data = (await r.json()) as { access_token?: string; refresh_token?: string }
    if (!data.access_token) throw new Error('refresh response missing access_token')
    await storageSet(STORAGE_KEYS.accessToken, data.access_token)
    if (data.refresh_token) await storageSet(STORAGE_KEYS.refreshToken, data.refresh_token)
    return data.access_token
  })().finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}

export const http: AxiosInstance = axios.create({ timeout: 30000 })

http.interceptors.request.use(async (cfg: InternalAxiosRequestConfig) => {
  const servers = useServersStore()
  cfg.baseURL = servers.apiBase
  const token = await getAccessToken()
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  cfg.headers['X-Request-ID'] = crypto.randomUUID()
  return cfg
})

http.interceptors.response.use(
  (resp) => resp,
  async (error) => {
    const cfg = error?.config as InternalAxiosRequestConfig & { __retried?: boolean }
    const status = error?.response?.status
    const url = String(cfg?.url ?? '')
    const isAuthEndpoint = ['/auth/login', '/auth/refresh', '/auth/register'].some((p) => url.includes(p))
    if (status === 401 && cfg && !cfg.__retried && !isAuthEndpoint) {
      cfg.__retried = true
      try {
        await refreshAccessToken()
        return http.request(cfg)
      } catch {
        await storageRemove(STORAGE_KEYS.accessToken)
        await storageRemove(STORAGE_KEYS.refreshToken)
        authFailureHandler?.()
      }
    }
    if (status && cfg?.__expectedStatus) {
      const expected = Array.isArray(cfg.__expectedStatus) ? cfg.__expectedStatus : [cfg.__expectedStatus]
      if (expected.includes(status)) return Promise.resolve(error.response)
    }
    return Promise.reject(error)
  },
)

/** 通用 JSON GET/POST 便捷封装（返回后端 data 字段） */
export async function apiGet<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const r = await http.get(url, { params })
  return (r?.data?.data ?? r?.data) as T
}

export async function apiPost<T>(url: string, body?: unknown): Promise<T> {
  const r = await http.post(url, body ?? {})
  return (r?.data?.data ?? r?.data) as T
}

export { storageGet, storageGetJson }
