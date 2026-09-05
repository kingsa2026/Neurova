import { request } from '@/api'

export type MarketItemType = 'agent' | 'skill' | 'workflow' | 'model' | 'template' | 'theme'

export type MarketItemStatus = 'draft' | 'published' | 'archived' | 'suspended'

export interface MarketItem {
  id: string
  type: MarketItemType
  name: string
  description: string
  long_description?: string
  author_id: string
  author_name: string
  author_avatar?: string
  version: string
  tags: string[]
  categories: string[]
  icon_url?: string
  screenshot_urls?: string[]
  featured: boolean
  verified: boolean
  status: MarketItemStatus
  price: number
  currency: string
  is_free: boolean
  rating: number
  rating_count: number
  download_count: number
  view_count: number
  like_count: number
  compatibility: {
    min_version: string
    max_version?: string
  }
  dependencies?: Record<string, string>
  metadata?: Record<string, unknown>
  created_at: string
  updated_at: string
  published_at?: string
}

export interface MarketItemListResponse {
  items: MarketItem[]
  total: number
  page: number
  page_size: number
}

export interface MarketItemDetail extends MarketItem {
  readme?: string
  changelog?: string
  installation_guide?: string
  release_notes?: string
}

export interface MarketItemReview {
  id: string
  item_id: string
  user_id: string
  user_name: string
  user_avatar?: string
  rating: number
  title?: string
  content?: string
  helpful_count: number
  created_at: string
  updated_at?: string
}

export interface ReviewListResponse {
  items: MarketItemReview[]
  total: number
  page: number
  page_size: number
}

export interface PurchaseRecord {
  id: string
  item_id: string
  user_id: string
  item_name: string
  item_type: MarketItemType
  price: number
  currency: string
  payment_method?: string
  transaction_id?: string
  status: 'pending' | 'completed' | 'refunded'
  purchased_at: string
  expires_at?: string
}

export interface PurchaseListResponse {
  items: PurchaseRecord[]
  total: number
  page: number
  page_size: number
}

export interface InstalledItem {
  id: string
  item_id: string
  user_id: string
  item_type: MarketItemType
  name: string
  version: string
  installed_at: string
  last_updated?: string
  is_enabled: boolean
  config?: Record<string, unknown>
}

export interface InstalledListResponse {
  items: InstalledItem[]
  total: number
  page: number
  page_size: number
}

export interface SearchParams {
  page?: number
  page_size?: number
  type?: MarketItemType
  category?: string
  tag?: string
  keyword?: string
  author_id?: string
  featured?: boolean
  verified?: boolean
  free_only?: boolean
  min_rating?: number
  sort_by?: 'newest' | 'popular' | 'rating' | 'downloads' | 'price_low' | 'price_high'
}

export const marketplaceAPI = {
  getMarketItems: (params?: SearchParams) =>
    request.get<MarketItemListResponse>('/api/v1/marketplace/items', { params }),

  getMarketItem: (itemId: string) =>
    request.get<MarketItemDetail>(`/api/v1/marketplace/items/${itemId}`),

  getMarketItemReviews: (itemId: string, params?: { page?: number; page_size?: number }) =>
    request.get<ReviewListResponse>(`/api/v1/marketplace/items/${itemId}/reviews`, { params }),

  createReview: (itemId: string, data: { rating: number; title?: string; content?: string }) =>
    request.post<MarketItemReview>(`/api/v1/marketplace/items/${itemId}/reviews`, data),

  updateReview: (itemId: string, reviewId: string, data: { rating?: number; title?: string; content?: string }) =>
    request.put<MarketItemReview>(`/api/v1/marketplace/items/${itemId}/reviews/${reviewId}`, data),

  deleteReview: (itemId: string, reviewId: string) =>
    request.delete(`/api/v1/marketplace/items/${itemId}/reviews/${reviewId}`),

  likeItem: (itemId: string) =>
    request.post<{ success: boolean; liked: boolean }>(`/api/v1/marketplace/items/${itemId}/like`),

  unlikeItem: (itemId: string) =>
    request.post<{ success: boolean; liked: boolean }>(`/api/v1/marketplace/items/${itemId}/unlike`),

  purchaseItem: (itemId: string) =>
    request.post<PurchaseRecord>(`/api/v1/marketplace/items/${itemId}/purchase`),

  getPurchaseHistory: (params?: { page?: number; page_size?: number }) =>
    request.get<PurchaseListResponse>('/api/v1/marketplace/purchases', { params }),

  getPurchase: (purchaseId: string) =>
    request.get<PurchaseRecord>(`/api/v1/marketplace/purchases/${purchaseId}`),

  installItem: (itemId: string) =>
    request.post<InstalledItem>(`/api/v1/marketplace/items/${itemId}/install`),

  uninstallItem: (itemId: string) =>
    request.delete(`/api/v1/marketplace/items/${itemId}/uninstall`),

  getInstalledItems: (params?: { page?: number; page_size?: number; type?: MarketItemType }) =>
    request.get<InstalledListResponse>('/api/v1/marketplace/installed', { params }),

  updateInstalledItem: (itemId: string, data: { is_enabled?: boolean; config?: Record<string, unknown> }) =>
    request.put<InstalledItem>(`/api/v1/marketplace/installed/${itemId}`, data),

  checkForUpdates: () =>
    request.get<{ updates_available: boolean; items: Array<{ id: string; name: string; current_version: string; latest_version: string }> }>('/api/v1/marketplace/check-updates'),

  updateItem: (itemId: string) =>
    request.post<InstalledItem>(`/api/v1/marketplace/installed/${itemId}/update`),

  getFeaturedItems: () =>
    request.get<MarketItemListResponse>('/api/v1/marketplace/featured'),

  getTrendingItems: (params?: { type?: MarketItemType; limit?: number }) =>
    request.get<MarketItemListResponse>('/api/v1/marketplace/trending', { params }),

  getCategories: () =>
    request.get<{ categories: string[] }>('/api/v1/marketplace/categories'),

  getTags: () =>
    request.get<{ tags: string[] }>('/api/v1/marketplace/tags'),
}
