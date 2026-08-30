import { ref, computed } from 'vue'
import { getFeedbackStats, type FeedbackStats, type FeedbackRecentItem } from '@/api/modules/console'

/**
 * useFeedbackStats — 反馈质量闭环的仪表盘数据源。
 *
 * 拉取 GET /console/chat/feedback/stats 聚合，并派生满意度（like 占比）。
 * 失败时保持零状态（仪表盘不因该卡片崩溃），error 仅暴露给调用方。
 */

export interface FeedbackSummary {
  like: number
  dislike: number
  totalFeedback: number
  /** 满意度 = like / total（百分比整数）；无反馈时为 null */
  satisfactionRate: number | null
  hasFeedback: boolean
  recent: FeedbackRecentItem[]
}

/** 从后端聚合派生展示摘要（纯函数，便于单测）。 */
export function deriveFeedbackSummary(data: Pick<FeedbackStats, 'like' | 'dislike' | 'total_feedback' | 'recent'>): FeedbackSummary {
  const total = data.total_feedback ?? 0
  return {
    like: data.like ?? 0,
    dislike: data.dislike ?? 0,
    totalFeedback: total,
    satisfactionRate: total > 0 ? Math.round(((data.like ?? 0) / total) * 100) : null,
    hasFeedback: total > 0,
    recent: data.recent ?? [],
  }
}

export function useFeedbackStats() {
  const summary = ref<FeedbackSummary>({
    like: 0,
    dislike: 0,
    totalFeedback: 0,
    satisfactionRate: null,
    hasFeedback: false,
    recent: [],
  })
  const loading = ref(false)
  const error = ref<Error | null>(null)

  /**
   * 拉取反馈统计。agentId 缺省 = 全部 agent（仪表盘全局视角）。
   * limit=200 覆盖更多会话；后端 SessionRepository 已按 user_id 过滤。
   */
  async function refresh(agentId?: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const res: any = await getFeedbackStats({ agent_id: agentId, limit: 200 })
      const data = res?.data ?? res
      if (data) {
        summary.value = deriveFeedbackSummary(data)
      }
    } catch (err) {
      error.value = err instanceof Error ? err : new Error(String(err))
    } finally {
      loading.value = false
    }
  }

  const satisfactionText = computed(() =>
    summary.value.satisfactionRate === null ? '--' : `${summary.value.satisfactionRate}%`,
  )

  return { summary, loading, error, satisfactionText, refresh }
}
