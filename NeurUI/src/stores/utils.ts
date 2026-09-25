/**
 * Store Utilities - Helper functions for Pinia stores
 * 
 * Provides common utilities for error handling, logging, and data transformation
 */

import { logger } from '@/utils/logger'

/**
 * Handle store errors consistently
 * @param err - The error that occurred
 * @param context - Context string for logging
 * @param options - Configuration options
 * @returns Error message string
 */
export function handleStoreError(
  err: unknown,
  context: string,
  options: { rethrow?: boolean; silent?: boolean; defaultValue?: unknown } = {}
): string {
  const { rethrow = false, silent = false, defaultValue } = options
  
  const errorMessage = err instanceof Error ? err.message : String(err)
  
  if (!silent) {
    logger.error(`[Store Error] ${context}:`, errorMessage)
  }
  
  if (rethrow) {
    throw err
  }
  
  return errorMessage
}

/**
 * Log store operations with context
 * @param context - Operation context
 * @param message - Log message
 * @param data - Optional data to log
 */
export function logStoreOperation(
  context: string,
  message: string,
  data?: unknown
): void {
  logger.debug(`[Store ${context}] ${message}`, data ? { data } : {})
}

/**
 * Map API response to domain model
 * @param raw - Raw API response
 * @param mapper - Function to map raw data to domain model
 * @returns Mapped domain object
 */
export function mapApiResponse<T>(
  raw: Record<string, any>,
  mapper: (raw: Record<string, any>) => T
): T {
  return mapper(raw)
}

/**
 * Transform snake_case to camelCase
 * @param obj - Object with snake_case keys
 * @returns Object with camelCase keys
 */
export function snakeToCamel(obj: Record<string, any>): Record<string, any> {
  const result: Record<string, any> = {}
  
  for (const [key, value] of Object.entries(obj)) {
    const camelKey = key.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase())
    result[camelKey] = typeof value === 'object' && value !== null && !Array.isArray(value)
      ? snakeToCamel(value)
      : Array.isArray(value)
        ? value.map(item => typeof item === 'object' && item !== null && !Array.isArray(item) ? snakeToCamel(item) : item)
        : value
  }
  
  return result
}

/**
 * Transform camelCase to snake_case
 * @param obj - Object with camelCase keys
 * @returns Object with snake_case keys
 */
export function camelToSnake(obj: Record<string, any>): Record<string, any> {
  const result: Record<string, any> = {}
  
  for (const [key, value] of Object.entries(obj)) {
    const snakeKey = key.replace(/[A-Z]/g, m => `_${m.toLowerCase()}`)
    result[snakeKey] = typeof value === 'object' && value !== null && !Array.isArray(value)
      ? camelToSnake(value)
      : Array.isArray(value)
        ? value.map(item => typeof item === 'object' && item !== null && !Array.isArray(item) ? camelToSnake(item) : item)
        : value
  }
  
  return result
}

/**
 * Safe property access with default value
 * @param obj - Object to access
 * @param path - Property path (e.g., 'config.temperature')
 * @param defaultValue - Default value if property not found
 * @returns Property value or default
 */
export function safeGet<T>(obj: Record<string, any>, path: string, defaultValue: T): T {
  const keys = path.split('.')
  let current: any = obj
  
  for (const key of keys) {
    if (current === undefined || current === null) {
      return defaultValue
    }
    current = current[key]
  }
  
  return current !== undefined && current !== null ? current : defaultValue
}

/**
 * Merge objects deeply
 * @param target - Target object
 * @param sources - Source objects to merge
 * @returns Merged object
 */
export function deepMerge(target: any, ...sources: any[]): any {
  const result = { ...target }
  
  for (const source of sources) {
    for (const key in source) {
      if (source.hasOwnProperty(key)) {
        const sourceValue = source[key]
        const targetValue = result[key]
        
        if (
          sourceValue !== undefined &&
          typeof sourceValue === 'object' &&
          sourceValue !== null &&
          !Array.isArray(sourceValue) &&
          typeof targetValue === 'object' &&
          targetValue !== null &&
          !Array.isArray(targetValue)
        ) {
          result[key] = deepMerge(targetValue, sourceValue)
        } else {
          result[key] = sourceValue ?? targetValue
        }
      }
    }
  }
  
  return result
}

/**
 * Debounce function calls
 * @param fn - Function to debounce
 * @param delay - Delay in milliseconds
 * @returns Debounced function
 */
export function debounce<T extends (...args: any[]) => any>(
  fn: T,
  delay: number
): (...args: Parameters<T>) => void {
  let timeoutId: NodeJS.Timeout | null = null
  
  return (...args: Parameters<T>) => {
    if (timeoutId) {
      clearTimeout(timeoutId)
    }
    
    timeoutId = setTimeout(() => {
      fn(...args)
      timeoutId = null
    }, delay)
  }
}

/**
 * Throttle function calls
 * @param fn - Function to throttle
 * @param limit - Time limit in milliseconds
 * @returns Throttled function
 */
export function throttle<T extends (...args: any[]) => any>(
  fn: T,
  limit: number
): (...args: Parameters<T>) => void {
  let lastCall = 0
  let timeoutId: NodeJS.Timeout | null = null
  
  return (...args: Parameters<T>) => {
    const now = Date.now()
    const remaining = limit - (now - lastCall)
    
    if (remaining <= 0) {
      if (timeoutId) {
        clearTimeout(timeoutId)
        timeoutId = null
      }
      
      fn(...args)
      lastCall = now
    } else if (!timeoutId) {
      timeoutId = setTimeout(() => {
        fn(...args)
        lastCall = Date.now()
        timeoutId = null
      }, remaining)
    }
  }
}
