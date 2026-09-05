/**
 * 存储工具函数
 * 统一封装 localStorage 和 sessionStorage 操作
 */

/**
 * 安全地获取 localStorage 项
 * @param key - 键名
 * @param defaultValue - 默认值
 * @returns 存储的值或默认值
 */
export function getLocalStorage<T>(key: string, defaultValue: T | null = null): T | null {
  try {
    const item = localStorage.getItem(key)
    if (item === null) return defaultValue
    return JSON.parse(item) as T
  } catch (error) {
    console.error(`Error reading localStorage key "${key}":`, error)
    return defaultValue
  }
}

/**
 * 安全地设置 localStorage 项
 * @param key - 键名
 * @param value - 值
 */
export function setLocalStorage<T>(key: string, value: T): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch (error) {
    console.error(`Error setting localStorage key "${key}":`, error)
  }
}

/**
 * 安全地移除 localStorage 项
 * @param key - 键名
 */
export function removeLocalStorage(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch (error) {
    console.error(`Error removing localStorage key "${key}":`, error)
  }
}

/**
 * 清空 localStorage
 */
export function clearLocalStorage(): void {
  try {
    localStorage.clear()
  } catch (error) {
    console.error('Error clearing localStorage:', error)
  }
}

/**
 * 安全地获取 sessionStorage 项
 * @param key - 键名
 * @param defaultValue - 默认值
 * @returns 存储的值或默认值
 */
export function getSessionStorage<T>(key: string, defaultValue: T | null = null): T | null {
  try {
    const item = sessionStorage.getItem(key)
    if (item === null) return defaultValue
    return JSON.parse(item) as T
  } catch (error) {
    console.error(`Error reading sessionStorage key "${key}":`, error)
    return defaultValue
  }
}

/**
 * 安全地设置 sessionStorage 项
 * @param key - 键名
 * @param value - 值
 */
export function setSessionStorage<T>(key: string, value: T): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value))
  } catch (error) {
    console.error(`Error setting sessionStorage key "${key}":`, error)
  }
}

/**
 * 安全地移除 sessionStorage 项
 * @param key - 键名
 */
export function removeSessionStorage(key: string): void {
  try {
    sessionStorage.removeItem(key)
  } catch (error) {
    console.error(`Error removing sessionStorage key "${key}":`, error)
  }
}

/**
 * 清空 sessionStorage
 */
export function clearSessionStorage(): void {
  try {
    sessionStorage.clear()
  } catch (error) {
    console.error('Error clearing sessionStorage:', error)
  }
}
