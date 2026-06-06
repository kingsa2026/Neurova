/**
 * Audio API Module
 * 音频处理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface AudioFile {
  id: string
  filename: string
  duration: number
  format: string
  sample_rate: number
  channels: number
  url: string
  created_at: number
}

export interface TranscriptionResult {
  id: string
  audio_id: string
  text: string
  language: string
  confidence: number
  segments: Array<{ start: number; end: number; text: string }>
  created_at: number
}

export interface TranscribeRequest {
  audio_id: string
  language?: string
  model?: string
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取音频文件列表
 * @param params 查询参数
 * @returns 音频文件列表
 */
export async function getAudioFiles(params?: {
  format?: string
  limit?: number
  offset?: number
}): Promise<AudioFile[]> {
  return request({ url: `/api/v1/audio`, method: 'get', params })
}

/**
 * 获取音频文件详情
 * @param audioId 音频ID
 * @returns 音频详情
 */
export async function getAudioFile(audioId: string): Promise<AudioFile> {
  return request({ url: `/api/v1/audio/${audioId}`, method: 'get' })
}

/**
 * 上传音频文件
 * @param formData 表单数据
 * @returns 上传的音频
 */
export async function uploadAudio(formData: FormData): Promise<AudioFile> {
  return request({ url: `/api/v1/audio/upload`, method: 'post', data: formData })
}

/**
 * 删除音频文件
 * @param audioId 音频ID
 * @returns 删除结果
 */
export async function deleteAudio(audioId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/audio/${audioId}`, method: 'delete' })
}

/**
 * 转录音频
 * @param data 转录请求
 * @returns 转录结果
 */
export async function transcribeAudio(data: TranscribeRequest): Promise<TranscriptionResult> {
  return request({ url: `/api/v1/audio/transcribe`, method: 'post', data })
}

/**
 * 获取转录历史
 * @param audioId 音频ID
 * @returns 转录结果
 */
export async function getTranscription(audioId: string): Promise<TranscriptionResult | null> {
  return request({ url: `/api/v1/audio/${audioId}/transcription`, method: 'get' })
}

/**
 * 获取音频统计
 * @returns 统计数据
 */
export async function getAudioStats(): Promise<ApiResponse<{
  total_files: number
  total_duration: number
  by_format: Record<string, number>
}>> {
  return request({ url: `/api/v1/audio/stats`, method: 'get' })
}

/**
 * 获取支持的转录语言
 * @returns 语言列表
 */
export async function getSupportedTranscriptionLanguages(): Promise<string[]> {
  return request({ url: `/api/v1/audio/languages`, method: 'get' })
}

/**
 * 下载音频文件
 * @param audioId 音频ID
 * @returns 下载URL
 */
export async function getAudioDownloadUrl(audioId: string): Promise<ApiResponse<{ url: string }>> {
  return request({ url: `/api/v1/audio/${audioId}/download`, method: 'get' })
}