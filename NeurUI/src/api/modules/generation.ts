import api from '@/api'
import type { ApiResponse } from '@/types/response'
import { request } from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TextGenerationPayload {
  prompt: string
  model?: string
  temperature?: number
  max_tokens?: number
  system_prompt?: string
  agent_id?: string
}

export interface TextGenerationResult {
  id: string
  text: string
  model: string
  tokens_used: number
  duration_ms: number
}

export interface ImageGenerationPayload {
  prompt: string
  style?: string
  width?: number
  height?: number
  model?: string
  negative_prompt?: string
}

export interface AudioGenerationPayload {
  text: string
  voice?: string
  speed?: number
  model?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/generation'

/** Generate text using an LLM. */
export function generateText(data: TextGenerationPayload) {
  return api.post<ApiResponse<TextGenerationResult>>(`${BASE}/text`, data)
}

/** Generate an image. Returns binary image data. */
export function generateImage(data: ImageGenerationPayload) {
  return api.post<ApiResponse<{ url: string; base64?: string }>>(`${BASE}/image`, data)
}

/** Generate audio (TTS). Returns binary WAV data. */
export function generateAudio(data: AudioGenerationPayload) {
  return request.post(`${BASE}/audio`, data, { responseType: 'blob' }) as unknown as Promise<Blob>
}

/** Get available generation models. */
export function getGenerationModels() {
  return api.get<ApiResponse<{ text: string[]; image: string[]; audio: string[] }>>(`${BASE}/models`)
}
