/**
 * Generic API response envelope from the backend.
 * Most endpoints return `{ code: 0, message: "ok", data: ... }`.
 */
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
}

/**
 * Paginated list response (page/size pattern).
 */
export interface PaginatedData<T> {
  items: T[]
  total: number
  page: number
  size: number
  pages?: number
}

/**
 * Paginated list response (limit/offset pattern).
 */
export interface LimitOffsetData<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

/**
 * Pagination query params (limit/offset) — 与后端分页契约同源
 * （如 notifications/scheduler 均为 `limit: Query(20)` + `offset: Query(0)`）。
 * P1-13（审计 2026-11-14）：旧定义 {page,size} 是后端不认的参数，翻页被
 * FastAPI 静默忽略成恒第一页；后端只认 page/size 的模块（plugins/experience）
 * 在各自 module 内做 limit/offset → page/size 换算，调用方统一说 limit/offset。
 */
export interface PageParams {
  limit?: number
  offset?: number
}

/**
 * Pagination query params (limit/offset).
 */
export interface LimitOffsetParams {
  limit?: number
  offset?: number
}

/**
 * Generic key-value record used in many endpoints.
 */
export type Metadata = Record<string, unknown>
