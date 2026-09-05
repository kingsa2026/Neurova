import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import type { ApiResponse, AuthResponse } from '@/types/auth'
import type { DownloadProgressEvent } from '@/types/api'
import { limitInputLength } from '@/utils/security'
&nbsp;
// 统一的存储键名
const TOKEN_KEY = 'token'
const REFRESH_TOKEN_KEY = 'refresh_token'
const USER_KEY = 'user'
&nbsp;
// 生产环境使用完整 URL（绕过 vite 代理），开发环境使用相对路径
// Vite 代理 /api/* -&gt; http://localhost:9527/* (自动去掉 /api 前缀)
// 后端路由前缀是 /v1，所以完整路径是 /api/v1/*
const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'
&nbsp;
// 创建 axios 实例
const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE,
  timeout: 300000,
  headers: {
    'Content-Type': 'application/json'
  }
})
&nbsp;
// 安全存储工具
function secureGet(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
&nbsp;
function secureRemove(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    // ignore
  }
}
&nbsp;
// 请求拦截器
apiClient.interceptors.request.use(
  (config) =&gt; {
    const token = secureGet(TOKEN_KEY)
    if (token) {
      config.headers.set('Authorization', `Bearer ${token}`)
    }
    // 安全检查：防止过大的请求数据
    if (config.data &amp;&amp; typeof config.data === 'string') {
      config.data = limitInputLength(config.data, 1000000) // 1MB 限制
    }
    console.log('[API Request]', config.method?.toUpperCase(), (config.baseURL || '') + (config.url || ''), { 
      hasToken: !!token,
      url: config.url
    })
    return config
  },
  (error) =&gt; Promise.reject(error)
)
&nbsp;
// 响应拦截器 — 401 自动清 token 并跳转登录
apiClient.interceptors.response.use(
  (response) =&gt; {
    return response.data
  },
  (error) =&gt; {
    if (error.response?.status === 401) {
      secureRemove(TOKEN_KEY)
      secureRemove(REFRESH_TOKEN_KEY)
      secureRemove(USER_KEY)
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)
&nbsp;
// 通用请求方法
export const request = {
  get: &lt;T = unknown&gt;(url: string, config?: AxiosRequestConfig): Promise&lt;ApiResponse&lt;T&gt;&gt; =&gt; {
    return apiClient.get(url, config)
  },
  post: &lt;T = unknown&gt;(url: string, data?: unknown, config?: AxiosRequestConfig): Promise&lt;ApiResponse&lt;T&gt;&gt; =&gt; {
    return apiClient.post(url, data, config)
  },
  put: &lt;T = unknown&gt;(url: string, data?: unknown, config?: AxiosRequestConfig): Promise&lt;ApiResponse&lt;T&gt;&gt; =&gt; {
    return apiClient.put(url, data, config)
  },
  delete: &lt;T = unknown&gt;(url: string, config?: AxiosRequestConfig): Promise&lt;ApiResponse&lt;T&gt;&gt; =&gt; {
    return apiClient.delete(url, config)
  },
  upload: &lt;T = unknown&gt;(url: string, formData: FormData, onProgress?: (percent: number) =&gt; void): Promise&lt;ApiResponse&lt;T&gt;&gt; =&gt; {
    return apiClient.post(url, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      },
      onUploadProgress: (progressEvent) =&gt; {
        if (onProgress &amp;&amp; progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total)
          onProgress(percent)
        }
      }
    })
  }
}
&nbsp;
export default apiClient
&nbsp;