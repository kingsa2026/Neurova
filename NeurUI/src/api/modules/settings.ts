import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface GeneralSettings {
  app_name: string
  language: string
}

export interface LLMSettings {
  default_provider: string
  default_model: string
  temperature: number
  max_tokens: number
}

export interface SecuritySettings {
  jwt_secret: string
  jwt_expiry_hours: number
  min_password_length: number
  require_special: boolean
}

export interface StorageSettings {
  media_path: string
  max_upload_mb: number
  cache_ttl_minutes: number
}

export interface AdvancedSettings {
  debug_mode: boolean
  log_level: string
  telemetry: boolean
}

export interface AppSettings {
  general: GeneralSettings
  llm: LLMSettings
  security: SecuritySettings
  storage: StorageSettings
  advanced: AdvancedSettings
  providers?: string[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/settings'

/** Get all application settings. */
export function getSettings() {
  return api.get<ApiResponse<AppSettings>>(BASE)
}

/** Update a settings section. */
export function updateSettings(section: string, data: Record<string, unknown>) {
  return api.put<ApiResponse<null>>(BASE, { section, data })
}

/** Clear application cache. */
export function clearCache() {
  return api.post<ApiResponse<null>>(`${BASE}/clear-cache`)
}
