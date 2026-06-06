/**
 * Computer API Module
 * 计算机视觉/操作 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface Screenshot {
  id: string
  image_url: string
  timestamp: number
  resolution: { width: number; height: number }
}

export interface UIElement {
  type: string
  text: string
  bbox: number[]
  confidence: number
  attributes: Record<string, any>
}

export interface ClickRequest {
  x: number
  y: number
  button?: 'left' | 'right' | 'middle'
}

export interface TypeRequest {
  text: string
  delay?: number
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取屏幕截图
 * @returns 截图信息
 */
export async function takeScreenshot(): Promise<Screenshot> {
  return request({ url: `/api/v1/computer/screenshot`, method: 'get' })
}

/**
 * 获取 UI 元素
 * @returns UI 元素列表
 */
export async function getUIElements(): Promise<UIElement[]> {
  return request({ url: `/api/v1/computer/elements`, method: 'get' })
}

/**
 * 点击操作
 * @param data 点击参数
 * @returns 操作结果
 */
export async function clickElement(data: ClickRequest): Promise<ApiResponse<{ success: boolean }>> {
  return request({ url: `/api/v1/computer/click`, method: 'post', data })
}

/**
 * 输入文本
 * @param data 输入参数
 * @returns 操作结果
 */
export async function typeText(data: TypeRequest): Promise<ApiResponse<{ success: boolean }>> {
  return request({ url: `/api/v1/computer/type`, method: 'post', data })
}

/**
 * 按键操作
 * @param key 按键名称
 * @returns 操作结果
 */
export async function pressKey(key: string): Promise<ApiResponse<{ success: boolean }>> {
  return request({ url: `/api/v1/computer/key`, method: 'post', params: { key } })
}

/**
 * 滚动操作
 * @param direction 滚动方向
 * @param amount 滚动量
 * @returns 操作结果
 */
export async function scroll(direction: 'up' | 'down', amount: number = 3): Promise<ApiResponse<{ success: boolean }>> {
  return request({ url: `/api/v1/computer/scroll`, method: 'post', params: { direction, amount } })
}

/**
 * 移动鼠标
 * @param x X坐标
 * @param y Y坐标
 * @returns 操作结果
 */
export async function moveMouse(x: number, y: number): Promise<ApiResponse<{ success: boolean }>> {
  return request({ url: `/api/v1/computer/mouse`, method: 'post', params: { x, y } })
}

/**
 * 获取屏幕尺寸
 * @returns 屏幕尺寸
 */
export async function getScreenSize(): Promise<ApiResponse<{ width: number; height: number }>> {
  return request({ url: `/api/v1/computer/screen-size`, method: 'get' })
}

/**
 * 获取计算机状态
 * @returns 计算机状态
 */
export async function getComputerStatus(): Promise<ApiResponse<{
  os: string
  hostname: string
  resolution: { width: number; height: number }
  mouse_position: { x: number; y: number }
}>> {
  return request({ url: `/api/v1/computer/status`, method: 'get' })
}