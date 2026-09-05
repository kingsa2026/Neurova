/**
 * 请求工具函数
 * 基于 axios 封装，统一处理请求和响应
 */
import axios, { type AxiosRequestConfig, type AxiosResponse } from 'axios'
import type { ApiResponse } from '@/types/auth'
import type { DownloadProgressEvent } from '@/types/api'
import { limitInputLength } from '@/utils/security'

// 安全的存储键名
const TOKEN_KEY = 'auth_token'

// 创建 axios 实例
const request = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 安全存储工具
function secureGetToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

function secureRemoveItem(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    // ignore
  }
}

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    // 从 localStorage 获取 token
    const token = secureGetToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    // 安全检查：防止过大的请求数据
    if (config.data && typeof config.data === 'string') {
      config.data = limitInputLength(config.data, 1000000) // 1MB 限制
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
request.interceptors.response.use(
  (response: AxiosResponse<ApiResponse<unknown>>) => {
    // 直接返回 data
    return response.data as ApiResponse<unknown>
  },
  (error) => {
    // 统一错误处理 - 安全模式，不暴露敏感信息
    if (error.response) {
      const { status, data } = error.response
      
      if (status === 401) {
        // Token 过期或无效
        secureRemoveItem(TOKEN_KEY)
        secureRemoveItem('auth_user')
        secureRemoveItem('auth_refresh')
        window.location.href = '/login'
      } else if (status === 403) {
        console.error('权限不足')
      } else if (status === 500) {
        console.error('服务器错误')
      }
      
      return Promise.reject(data || error)
    }
    
    return Promise.reject(error)
  }
)

// 封装常用请求方法
export const http = {
  get: <T = unknown>(url: string, config?: AxiosRequestConfig): Promise<ApiResponse<T>> => {
    return request.get(url, config)
  },
  
  post: <T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<ApiResponse<T>> => {
    return request.post(url, data, config)
  },
  
  put: <T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<ApiResponse<T>> => {
    return request.put(url, data, config)
  },
  
  delete: <T = unknown>(url: string, config?: AxiosRequestConfig): Promise<ApiResponse<T>> => {
    return request.delete(url, config)
  },
  
  upload: <T = unknown>(url: string, formData: FormData, onProgress?: (percent: number) => void): Promise<ApiResponse<T>> => {
    return request.post(url, formData, {
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

export default request
