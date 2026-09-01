import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HomeStats {
  agent_count: number
  conversation_count: number
  token_consumption: number
  llm_call_count: number
}

export interface HomeTrends {
  agent_trend: number
  conversation_trend: number
  token_trend: number
  plugin_trend: number
}

export interface HomeActivity {
  icon: string
  text: string
  color: string
  created_at: string
}

export interface HomeData {
  stats: HomeStats
  trends: HomeTrends
  recent_activities: HomeActivity[]
}

export interface TrendDataPoint {
  date: string
  value: number
}

export interface TrendSeries {
  data: number[]
  labels: string[]
}

export interface HomeTrendResponse {
  agent_trend: TrendSeries
  conversation_trend: TrendSeries
  message_trend: TrendSeries
  token_trend: TrendSeries
  llm_trend: TrendSeries
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/home'

/** Fetch dashboard home data (stats, trends, recent activities). */
export function getHomeData() {
  return api.get<ApiResponse<HomeData>>(`${BASE}/data`)
}

/** Fetch trend data for sparklines and charts. */
export function getHomeTrends(days?: number) {
  return api.get<ApiResponse<HomeTrendResponse>>(`${BASE}/trends`, { params: days ? { days } : undefined })
}
