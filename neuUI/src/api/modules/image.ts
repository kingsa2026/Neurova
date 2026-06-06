/**
 * Image API Module
 * 图像处理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface ImageResult {
  id: string
  url: string
  width: number
  height: number
  format: string
  size: number
  created_at: number
}

export interface GenerateImageRequest {
  prompt: string
  negative_prompt?: string
  width?: number
  height?: number
  num_images?: number
  model?: string
  style?: string
}

export interface ImageAnalysisRequest {
  image_url: string
  analysis_type: 'description' | 'objects' | 'faces' | 'ocr' | 'all'
}

export interface ImageAnalysisResult {
  description: string
  objects: Array<{ name: string; confidence: number; bbox: number[] }>
  faces: number
  text: string
  tags: string[]
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 生成图像
 * @param data 生成参数
 * @returns 生成的图像
 */
export async function generateImage(data: GenerateImageRequest): Promise<ImageResult> {
  return request({
    url: `/api/v1/image/generate`,
    method: 'post',
    data
  })
}

/**
 * 分析图像
 * @param data 分析参数
 * @returns 分析结果
 */
export async function analyzeImage(data: ImageAnalysisRequest): Promise<ImageAnalysisResult> {
  return request({
    url: `/api/v1/image/analyze`,
    method: 'post',
    data
  })
}

/**
 * 获取图像历史
 * @param limit 数量限制
 * @param offset 偏移量
 * @returns 图像列表
 */
export async function getImageHistory(limit: number = 20, offset: number = 0): Promise<ImageResult[]> {
  return request({
    url: `/api/v1/image/history`,
    method: 'get',
    params: { limit, offset }
  })
}

/**
 * 删除图像
 * @param imageId 图像ID
 * @returns 删除结果
 */
export async function deleteImage(imageId: string): Promise<ApiResponse<{ id: string }>> {
  return request({
    url: `/api/v1/image/${imageId}`,
    method: 'delete'
  })
}

/**
 * 获取图像统计
 * @returns 统计数据
 */
export async function getImageStats(): Promise<ApiResponse<{
  total_images: number
  total_size: number
  by_format: Record<string, number>
  avg_generation_time: number
}>> {
  return request({
    url: `/api/v1/image/stats`,
    method: 'get'
  })
}

/**
 * 获取可用模型
 * @returns 模型列表
 */
export async function getAvailableImageModels(): Promise<string[]> {
  return request({
    url: `/api/v1/image/models`,
    method: 'get'
  })
}

/**
 * 获取可用风格
 * @returns 风格列表
 */
export async function getAvailableImageStyles(): Promise<string[]> {
  return request({
    url: `/api/v1/image/styles`,
    method: 'get'
  })
}