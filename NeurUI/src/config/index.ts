/**
 * 统一前端配置库 - 集中管理应用级配置
 *
 * 所有 UI 配置必须通过此库读取，禁止散落的 import.meta.env 调用。
 *
 * 特性：
 * - 集中读取 Vite 环境变量与默认值
 * - getConfig() 返回配置副本，避免外部篡改内部状态
 * - updateConfig() 支持运行时局部更新
 *
 * 用法：
 *   import config, { getConfig, updateConfig } from '@/config'
 *   console.log(config.apiBaseUrl)
 *   updateConfig({ apiTimeout: 5000 })
 */
export interface AppConfig {
  /** API 基础地址 */
  apiBaseUrl: string
  /** API 超时时间（毫秒） */
  apiTimeout: number
  /** 应用名称 */
  appName: string
  /** 应用版本号 */
  appVersion: string
  /** 是否开发环境 */
  isDev: boolean
  /** 是否生产环境 */
  isProd: boolean
}

const config: AppConfig = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  apiTimeout: 300000,
  appName: import.meta.env.VITE_APP_NAME || 'Neurova',
  appVersion: import.meta.env.VITE_APP_VERSION || '1.0.0',
  isDev: import.meta.env.DEV,
  isProd: import.meta.env.PROD,
}

/**
 * 返回当前配置的浅拷贝副本
 */
export function getConfig(): AppConfig {
  return { ...config }
}

/**
 * 局部更新配置（合并写入）
 * @param patch 待合并的字段
 */
export function updateConfig(patch: Partial<AppConfig>): void {
  Object.assign(config, patch)
}

export default config
