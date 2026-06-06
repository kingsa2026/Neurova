/**
 * Media API Module
 * 媒体处理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface MediaFile {
  id: string
  filename: string
  type: 'image' | 'audio' | 'video' | 'document'
  mime_type: string
  size: number
  url: string
  created_at: number
  metadata?: Record<string, any>
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取媒体文件列表
 * @param params 查询参数
 * @returns 媒体文件列表
 */
export async function getMediaFiles(params?: {
  type?: string
  limit?: number
  offset?: number
}): Promise<MediaFile[]> {
  return request({ url: `/api/v1/media`, method: 'get', params })
}

/**
 * 获取媒体文件详情
 * @param mediaId 媒体ID
 * @returns 媒体详情
 */
export async function getMediaFile(mediaId: string): Promise<MediaFile> {
  return request({ url: `/api/v1/media/${mediaId}`, method: 'get' })
}

/**
 * 上传媒体文件
 * @param formData 表单数据
 * @returns 上传的媒体
 */
export async function uploadMedia(formData: FormData): Promise<MediaFile> {
  return request({ url: `/api/v1/media/upload`, method: 'post', data: formData })
}

/**
 * 删除媒体文件
 * @param mediaId 媒体ID
 * @returns 删除结果
 */
export async function deleteMedia(mediaId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/media/${mediaId}`, method: 'delete' })
}

/**
 * 获取媒体统计
 * @returns 统计数据
 */
export async function getMediaStats(): Promise<ApiResponse<{
  total_files: number
  total_size: number
  by_type: Record<string, number>
}>> {
  return request({ url: `/api/v1/media/stats`, method: 'get' })
}

/**
 * 下载媒体文件
 * @param mediaId 媒体ID
 * @returns 下载URL
 */
export async function getMediaDownloadUrl(mediaId: string): Promise<ApiResponse<{ url: string }>> {
  return request({ url: `/api/v1/media/${mediaId}/download`, method: 'get' })
}