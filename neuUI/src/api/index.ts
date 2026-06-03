import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import type { ApiResponse, AuthResponse } from '@/types/auth'
import type { DownloadProgressEvent } from '@/types/api'
import { limitInputLength } from '@/utils/security'
 
// 统一的存储键名
const TOKEN_KEY = 'token'
const REFRESH_TOKEN_KEY = 'refresh_token'
const USER_KEY = 'user'
 
// 生产环境使用完整 URL（绕过 vite 代理），开发环境使用相对路径
// Vite 代理 /api/* -> http://localhost:9527/* (自动去掉 /api 前缀)
// 后端路由前缀是 /v1，所以完整路径是 /api/v1/*
const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'
 
// 创建 axios 实例
const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE,
  timeout: 300000,
  headers: {
    'Content-Type': 'application/json'
  }
})
 
// 安全存储工具
function secureGet(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
 
function secureRemove(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    // ignore
  }
}
 
// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    const token = secureGet(TOKEN_KEY)
    if (token) {
      config.headers.set('Authorization', `Bearer ${token}`)
    }
    // 安全检查：防止过大的请求数据
    if (config.data && typeof config.data === 'string') {
      config.data = limitInputLength(config.data, 1000000) // 1MB 限制
    }
    console.log('[API Request]', config.method?.toUpperCase(), (config.baseURL || '') + (config.url || ''), { 
      hasToken: !!token,
      url: config.url
    })
    return config
  },
  (error) => Promise.reject(error)
)
 
// 响应拦截器 — 401 自动清 token 并跳转登录
apiClient.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    if (error.response?.status === 401) {
      secureRemove(TOKEN_KEY)
      secureRemove(REFRESH_TOKEN_KEY)
      secureRemove(USER_KEY)
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)
 
// 通用请求方法
export const request = {
  get: <T = unknown>(url: string, config?: AxiosRequestConfig): Promise<ApiResponse<T>> => {
    return apiClient.get(url, config)
  },
  post: <T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<ApiResponse<T>> => {
    return apiClient.post(url, data, config)
  },
  put: <T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<ApiResponse<T>> => {
    return apiClient.put(url, data, config)
  },
  delete: <T = unknown>(url: string, config?: AxiosRequestConfig): Promise<ApiResponse<T>> => {
    return apiClient.delete(url, config)
  },
  upload: <T = unknown>(url: string, formData: FormData, onProgress?: (percent: number) => void): Promise<ApiResponse<T>> => {
    return apiClient.post(url, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      },
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total)
          onProgress(percent)
        }
      }
    })
  }
}
 
export default apiClient
 