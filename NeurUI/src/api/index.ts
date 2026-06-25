import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { secureStorage } from '@/utils/security'
import bus from '@/bus'
import logger from '@/utils/logger'
import config from '@/config'

const TOKEN_KEY = 'auth_token'

/**
 * Generate a UUID v4 string for request tracing (X-Request-ID).
 * Uses crypto.randomUUID when available, otherwise falls back to a
 * manual implementation based on crypto.getRandomValues.
 */
function generateRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // Fallback UUID v4
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  bytes[6] = (bytes[6] & 0x0f) | 0x40 // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80 // variant 10
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

/**
 * Create the shared axios instance.
 */
export const request: AxiosInstance = axios.create({
  baseURL: config.apiBaseUrl,
  timeout: config.apiTimeout,
  headers: {
    'Content-Type': 'application/json',
  },
})

/**
 * Request interceptor:
 * - Attach Bearer token to every request
 * - Generate and attach X-Request-ID for distributed tracing
 * - Log outgoing requests with their request ID
 */
request.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // Attach auth token
    const token = secureStorage.get(TOKEN_KEY)
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }

    // Generate unique request ID for tracing through the middleware stack
    const requestId = generateRequestId()
    if (config.headers) {
      config.headers['X-Request-ID'] = requestId
    }

    // Stash the request ID on the config so the response interceptor can read it
    (config as any).__requestId = requestId

    const method = (config.method || 'GET').toUpperCase()
    const url = config.baseURL
      ? `${config.baseURL}${config.url || ''}`
      : config.url || ''
    logger.info(`[API] -> ${method} ${url}  [${requestId}]`)

    return config
  },
  (error) => Promise.reject(error),
)

/**
 * Response interceptor:
 * - Log responses with their request ID
 * - Handle 401 by clearing auth state and redirecting
 * - Handle 429 (rate limiting) with a user-visible warning
 */
request.interceptors.response.use(
  (response: AxiosResponse) => {
    const requestId = (response.config as any).__requestId || 'unknown'
    const method = (response.config.method || 'GET').toUpperCase()
    const url = response.config.url || ''
    logger.info(`[API] <- ${method} ${url}  ${response.status}  [${requestId}]`)
    return response.data
  },
  (error) => {
    const requestId = (error.config as any)?.__requestId || 'unknown'
    const status = error.response?.status

    if (status === 401) {
      secureStorage.remove(TOKEN_KEY)
      secureStorage.remove('user')
      // Redirect to login if not already there
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
      // Don't treat expired/missing token as a real error — it's expected on page load
      logger.warn(`[API] 401 Auth required [${requestId}] → redirecting to login`)
    } else if (status === 429) {
      const retryAfter = error.response?.headers?.['retry-after']
      const msg = retryAfter
        ? `Rate limit exceeded. Retry after ${retryAfter}s.`
        : 'Rate limit exceeded. Please slow down.'
      logger.warn(`[API] 429 Rate Limited [${requestId}]: ${msg}`)
      // 通过统一事件总线通知（替代 window.dispatchEvent）
      bus.emit('api:rate-limited', { requestId, retryAfter, message: msg })
    }

    // Only log non-auth errors (auth errors are handled above)
    if (status !== 401) {
      logger.error(`[API] !! ${error.config?.method?.toUpperCase()} ${error.config?.url}  ${status || 'network'}  [${requestId}]`)
    }
    return Promise.reject(error)
  },
)

/**
 * Convenience methods with generic typing.
 */
export const api = {
  get<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return request.get(url, config) as unknown as Promise<T>
  },

  post<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return request.post(url, data, config) as unknown as Promise<T>
  },

  put<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return request.put(url, data, config) as unknown as Promise<T>
  },

  delete<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return request.delete(url, config) as unknown as Promise<T>
  },

  /**
   * Upload a file using multipart/form-data.
   */
  upload<T = unknown>(url: string, file: File, fieldName = 'file', extraData?: Record<string, unknown>): Promise<T> {
    const formData = new FormData()
    formData.append(fieldName, file)
    if (extraData) {
      Object.entries(extraData).forEach(([key, value]) => {
        formData.append(key, typeof value === 'string' ? value : JSON.stringify(value))
      })
    }
    return request.post(url, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }) as unknown as Promise<T>
  },
}

export { generateRequestId }
export default api
