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
 * Pagination query params (page/size).
 */
export interface PageParams {
  page?: number
  size?: number
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
