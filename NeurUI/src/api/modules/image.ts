import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ImageTemplate {
  name: string
  description: string
  base_image: string
  dockerfile_content: string
  build_args: { name: string; default?: string }[]
  tags: string[]
  created_at: number
  updated_at: number
}

export interface BuildRecord {
  build_id: string
  template_name: string
  tag: string
  status: 'pending' | 'building' | 'success' | 'failed'
  started_at: number
  finished_at?: number
  duration?: number
  error_message?: string
  image_id?: string
  build_args: Record<string, string>
}

export interface BuildRequest {
  template_name: string
  tag: string
  build_args?: Record<string, string>
  no_cache?: boolean
  platform?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/image'

/** List available image templates. */
export function getTemplates() {
  return api.get<ApiResponse<{ templates: ImageTemplate[]; total: number }>>(`${BASE}/templates`)
}

/** Get template details. */
export function getTemplate(name: string) {
  return api.get<ApiResponse<ImageTemplate>>(`${BASE}/templates/${name}`)
}

/** Build an image from a template. */
export function buildImage(data: BuildRequest) {
  return api.post<ApiResponse<{ build_id: string; status: string; image_tag?: string; image_id?: string; duration_seconds?: number }>>(`${BASE}/build`, data)
}

/** List build history. */
export function getBuilds(params?: { template_name?: string; status?: string; limit?: number }) {
  return api.get<ApiResponse<{ builds: BuildRecord[]; total: number }>>(`${BASE}/builds`, { params })
}

/** Get build details. */
export function getBuild(buildId: string) {
  return api.get<ApiResponse<BuildRecord>>(`${BASE}/builds/${buildId}`)
}
