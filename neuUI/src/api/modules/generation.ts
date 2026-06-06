import { request } from '@/api'

// 文本生成请求
export interface TextGenerationRequest {
  prompt: string
  model?: string
  max_tokens?: number
  temperature?: number
  stream?: boolean
}

// 图像生成请求
export interface ImageGenerationRequest {
  prompt: string
  model?: string
  width?: number
  height?: number
  num_images?: number
}

// 音频生成请求
export interface AudioGenerationRequest {
  text: string
  model?: string
  voice?: string
  speed?: number
}

// 视频生成请求
export interface VideoGenerationRequest {
  prompt: string
  model?: string
  duration?: number
  resolution?: string
}

// 生成响应
export interface GenerationResponse {
  code: number
  data: {
    text?: string
    image_url?: string
    audio_url?: string
    video_url?: string
    model: string
    request_id: string
  }
  message?: string
}

/**
 * 文本生成
 * @param data 文本生成请求
 * @returns 生成结果
 */
export async function generateText(data: TextGenerationRequest): Promise<GenerationResponse> {
  return request({
    url: '/api/v1/generation/text',
    method: 'post',
    data,
  })
}

/**
 * 图像生成
 * @param data 图像生成请求
 * @returns 生成结果
 */
export async function generateImage(data: ImageGenerationRequest): Promise<GenerationResponse> {
  return request({
    url: '/api/v1/generation/image',
    method: 'post',
    data,
  })
}

/**
 * 音频生成
 * @param data 音频生成请求
 * @returns 生成结果
 */
export async function generateAudio(data: AudioGenerationRequest): Promise<GenerationResponse> {
  return request({
    url: '/api/v1/generation/audio',
    method: 'post',
    data,
  })
}

/**
 * 视频生成
 * @param data 视频生成请求
 * @returns 生成结果
 */
export async function generateVideo(data: VideoGenerationRequest): Promise<GenerationResponse> {
  return request({
    url: '/api/v1/generation/video',
    method: 'post',
    data,
  })
}

/**
 * 流式文本生成
 * @param data 文本生成请求
 * @returns 流式响应
 */
export async function generateTextStream(data: TextGenerationRequest) {
  return request({
    url: '/api/v1/generation/text',
    method: 'post',
    data: { ...data, stream: true },
    responseType: 'stream',
  })
}

export default {
  generateText,
  generateImage,
  generateAudio,
  generateVideo,
  generateTextStream,
}