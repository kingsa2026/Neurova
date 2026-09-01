import { ref } from 'vue'
import { getHomeData, getHomeTrends } from '@/api/modules/home'
import { getTokenUsage, getSystemInfo } from '@/api/modules/stats'
import { getMemoryStats } from '@/api/modules/memory'
import { getKnowledgeNodes } from '@/api/modules/knowledge'
import { getHealthReport } from '@/api/modules/health'
import { getSchedulerStatus } from '@/api/modules/scheduler'
import type { TokenUsageByModel } from '@/api/modules/stats'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DashboardStatCard {
  key: 'agents' | 'conversations' | 'tokens' | 'calls' | 'memories' | 'knowledge'
  value: number
  /** 末天 vs 前段均值百分比 delta；无历史时为 undefined（不渲染徽章） */
  trend?: number
  /** 7 天序列；为空时不渲染 sparkline */
  spark?: number[]
}

export interface TrendSuite {
  labels: string[]
  agent: number[]
  conversation: number[]
  message: number[]
}

export interface DashboardHealth {
  overall: string | null
  checks: Array<{ name: string; status: string }>
  system: { cpu: number | null; memory: number | null; disk: number | null } | null
}

export interface DashboardScheduler {
  running: boolean | null
  total_tasks: number | null
  active_tasks: number | null
}

// ---------------------------------------------------------------------------
// 纯函数（独立可测）
// ---------------------------------------------------------------------------

/**
 * 计算序列末天相比之前均值的变化百分比（四舍五入）。
 * 序列不足 2 点或基线均值为 0 时返回 undefined（无对比基线，不渲染徽章）。
 */
export function computeDelta(data?: number[]): number | undefined {
  if (!data || data.length < 2) return undefined
  const prev = data.slice(0, -1)
  const prevMean = prev.reduce((sum, v) => sum + v, 0) / prev.length
  if (prevMean <= 0) return undefined
  const last = data[data.length - 1]
  return Math.round(((last - prevMean) / prevMean) * 100)
}

/** 兼容信封 {code,data} 与裸对象的部分解包（与页面既有 raw?.data ?? raw 一致）。 */
export function unwrapPayload<T>(raw: unknown): T | null {
  if (raw && typeof raw === 'object') {
    const r = raw as { data?: unknown }
    return (r.data ?? raw) as T
  }
  return null
}

function buildCards(input: {
  agents: number
  conversations: number
  tokens: number
  calls: number
  memories: number
  knowledge: number
  agentSeries: number[]
  convSeries: number[]
}): DashboardStatCard[] {
  return [
    { key: 'agents', value: input.agents, trend: computeDelta(input.agentSeries), spark: input.agentSeries.length ? input.agentSeries : undefined },
    { key: 'conversations', value: input.conversations, trend: computeDelta(input.convSeries), spark: input.convSeries.length ? input.convSeries : undefined },
    { key: 'tokens', value: input.tokens },
    { key: 'calls', value: input.calls },
    { key: 'memories', value: input.memories },
    { key: 'knowledge', value: input.knowledge },
  ]
}

// ---------------------------------------------------------------------------
// Composable
// ---------------------------------------------------------------------------

export function useDashboardStats(options?: { agentId?: string | (() => string) }) {
  const loading = ref(false)
  const error = ref<string | null>(null)
  const cards = ref<DashboardStatCard[]>([])
  const trends = ref<TrendSuite>({ labels: [], agent: [], conversation: [], message: [] })
  const tokenByModel = ref<TokenUsageByModel[]>([])
  const health = ref<DashboardHealth>({ overall: null, checks: [], system: null })
  const scheduler = ref<DashboardScheduler>({ running: null, total_tasks: null, active_tasks: null })

  function cardByKey(key: DashboardStatCard['key']) {
    return cards.value.find((c) => c.key === key)
  }

  async function refresh() {
    loading.value = true
    error.value = null
    const provider = options?.agentId
    const agentId = typeof provider === 'function' ? provider() : (provider ?? '')

    const [homeRes, trendRes, tokenRes, memRes, knRes, sysRes, healthRes, schedRes] =
      await Promise.allSettled([
        getHomeData(),
        getHomeTrends(7),
        getTokenUsage(),
        getMemoryStats(agentId),
        getKnowledgeNodes({ page: 1, size: 1 }),
        getSystemInfo(),
        getHealthReport(),
        getSchedulerStatus(),
      ])

    if (homeRes.status === 'rejected') {
      // 核心统计失败才视为错误（通知/健康等可选源失败不干扰页面）
      error.value = String(homeRes.reason)
    }

    // --- 7 天趋势序列 ---
    let agentSeries: number[] = []
    let convSeries: number[] = []
    let msgSeries: number[] = []
    let labels: string[] = []
    if (trendRes.status === 'fulfilled') {
      const d = unwrapPayload<{
        agent_trend?: { labels?: string[]; data?: number[] }
        conversation_trend?: { labels?: string[]; data?: number[] }
        message_trend?: { labels?: string[]; data?: number[] }
      }>(trendRes.value)
      agentSeries = d?.agent_trend?.data ?? []
      convSeries = d?.conversation_trend?.data ?? []
      msgSeries = d?.message_trend?.data ?? []
      labels = d?.agent_trend?.labels?.length ? d.agent_trend.labels : ((d?.conversation_trend?.labels ?? []) as string[])
      trends.value = { labels, agent: agentSeries, conversation: convSeries, message: msgSeries }
    } else {
      trends.value = { labels: [], agent: [], conversation: [], message: [] }
    }

    // --- 主统计 ---
    let homeStats: { agent_count?: number; conversation_count?: number; token_consumption?: number; llm_call_count?: number; memory_count?: number } = {}
    if (homeRes.status === 'fulfilled') {
      const d = unwrapPayload<{ stats?: typeof homeStats }>(homeRes.value)
      homeStats = d?.stats ?? {}
    }

    // --- token 用量（主源 /stats/token-usage，回退 home） ---
    let tokTotal: { calls?: number; total_tokens?: number } = {}
    if (tokenRes.status === 'fulfilled') {
      const d = unwrapPayload<{ total?: typeof tokTotal; by_model?: TokenUsageByModel[] }>(tokenRes.value)
      tokTotal = d?.total ?? {}
      tokenByModel.value = d?.by_model ?? []
    } else {
      tokenByModel.value = []
    }

    // --- 记忆 / 知识 ---
    // 记忆总数主源 = home/data.stats.memory_count（真实记忆表，经 MemoryManager 统计）；
    // /memory/stats 是三层隔离语义（登录用户只见本人作用域记忆，admin 对存量
    // default 作用域记忆不可见——隔离审计设计），仅作回退。
    let memories = 0
    if (homeStats.memory_count != null) {
      memories = homeStats.memory_count
    } else if (memRes.status === 'fulfilled') {
      memories = unwrapPayload<{ total_memories?: number }>(memRes.value)?.total_memories ?? 0
    }
    let knowledge = 0
    if (knRes.status === 'fulfilled') {
      const d = unwrapPayload<{ total?: number }>(knRes.value)
      // 后端契约：GET /knowledge 返回 List[KnowledgeItem]（数组），无分页 total
      if (Array.isArray(d)) knowledge = d.length
      else knowledge = d?.total ?? 0
    }

    cards.value = buildCards({
      agents: homeStats.agent_count ?? 0,
      conversations: homeStats.conversation_count ?? 0,
      tokens: tokTotal.total_tokens ?? homeStats.token_consumption ?? 0,
      calls: tokTotal.calls ?? homeStats.llm_call_count ?? 0,
      memories,
      knowledge,
      agentSeries,
      convSeries,
    })

    // --- 健康状态（真健康报告 + 系统资源） ---
    let sys: { cpu?: { percent?: number }; memory?: { percent?: number }; disk?: { percent?: number } } | null = null
    let report: { overall?: string; checks?: Array<{ name: string; status: string }> } | null = null
    if (sysRes.status === 'fulfilled') {
      sys = unwrapPayload(sysRes.value)
    }
    if (healthRes.status === 'fulfilled') {
      report = unwrapPayload(healthRes.value)
    }
    health.value = {
      overall: report?.overall ?? null,
      checks: report?.checks ?? [],
      system: sys
        ? {
            cpu: sys.cpu?.percent ?? null,
            memory: sys.memory?.percent ?? null,
            disk: sys.disk?.percent ?? null,
          }
        : null,
    }

    // --- 调度器 ---
    if (schedRes.status === 'fulfilled') {
      const d = unwrapPayload<DashboardScheduler>(schedRes.value)
      scheduler.value = {
        running: d?.running ?? null,
        total_tasks: d?.total_tasks ?? null,
        active_tasks: d?.active_tasks ?? null,
      }
    }

    loading.value = false
  }

  return { loading, error, cards, trends, tokenByModel, health, scheduler, refresh, cardByKey }
}
