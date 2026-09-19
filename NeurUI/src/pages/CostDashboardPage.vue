<template>
  <div class="cost-page">
    <div class="page-header">
      <h2 class="page-title">LLM 成本看板</h2>
      <div class="header-actions">
        <a-tag v-if="status && !status.store_ready" color="orange">成本账本未装配</a-tag>
        <a-tag v-else-if="status" :color="status.running ? 'green' : 'default'">
          聚合{{ status.running ? '运行中' : '未运行' }}
        </a-tag>
        <a-button size="small" :loading="rolling" @click="onRollupNow">立即聚合</a-button>
        <a-button size="small" @click="fetchAll">刷新</a-button>
      </div>
    </div>

    <a-alert
      v-if="storeUnavailable"
      type="warning"
      show-icon
      message="成本账本尚未装配或暂无数据"
      description="推送对话产生 LLM 调用后，成本会自动落盘；也可在部署中确认 NEUROVA_COST_TRACKING 未被关闭。"
    />

    <a-spin :spinning="loading">
      <!-- 实时指标 -->
      <div class="stats-grid">
        <GlassStatCard label="当前小时成本" :value="formatUsd(metrics.current_hour?.cost ?? 0)" emoji="💰" />
        <GlassStatCard label="输入 Tokens" :value="formatInt(metrics.current_hour?.input_tokens ?? 0)" emoji="📥" />
        <GlassStatCard label="输出 Tokens" :value="formatInt(metrics.current_hour?.output_tokens ?? 0)" emoji="📤" />
        <GlassStatCard label="活跃 Agent" :value="metrics.current_hour?.active_agents ?? 0" emoji="🤖" />
      </div>

      <a-tabs v-model:activeKey="activeTab" style="margin-top: 8px">
        <!-- 趋势 -->
        <a-tab-pane key="trend" tab="成本趋势">
          <GlassCard title="近 24 小时成本">
            <div class="chart-placeholder">
              <div v-for="(p, i) in hourlyBars" :key="i" class="chart-bar-wrapper">
                <div class="chart-bar" :style="{ height: `${p.heightPct}%` }" :title="p.cost" />
                <span class="chart-label">{{ p.label }}</span>
              </div>
              <a-empty v-if="!hourlyBars.length" :description="t('common.noData')" />
            </div>
          </GlassCard>

          <GlassCard title="近 7 天每日成本" style="margin-top: 20px">
            <div class="chart-placeholder">
              <div v-for="(p, i) in dailyBars" :key="i" class="chart-bar-wrapper">
                <div class="chart-bar" :style="{ height: `${p.heightPct}%` }" :title="p.cost" />
                <span class="chart-label">{{ p.label }}</span>
              </div>
              <a-empty v-if="!dailyBars.length" :description="t('common.noData')" />
            </div>
          </GlassCard>
        </a-tab-pane>

        <!-- 预算 -->
        <a-tab-pane key="budget" tab="预算">
          <GlassCard title="预算使用情况">
            <a-table
              :columns="budgetColumns"
              :data-source="budgets"
              :row-key="(r: BudgetStatus) => `${r.scope}:${r.identifier}`"
              :pagination="false"
              size="small"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'usage'">{{ formatUsd(record.usage) }} / {{ formatUsd(record.amount) }}</template>
                <template v-else-if="column.key === 'percentage'">
                  <a-progress
                    :percent="Math.min(100, Math.round(record.percentage))"
                    :status="record.is_over_budget ? 'exception' : record.percentage >= 75 ? 'active' : 'normal'"
                    size="small"
                  />
                </template>
                <template v-else-if="column.key === 'state'">
                  <a-tag :color="record.is_over_budget ? 'red' : record.percentage >= 75 ? 'orange' : 'green'">
                    {{ record.is_over_budget ? '超支' : record.percentage >= 75 ? '接近上限' : '正常' }}
                  </a-tag>
                </template>
              </template>
              <template #emptyText><a-empty :description="t('common.noData')" /></template>
            </a-table>
          </GlassCard>
        </a-tab-pane>

        <!-- 历史明细 -->
        <a-tab-pane key="history" tab="每日明细">
          <GlassCard title="每日成本明细">
            <a-table
              :columns="dailyColumns"
              :data-source="metrics.last_7_days ?? []"
              row-key="date"
              :pagination="false"
              size="small"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'total_cost'">{{ formatUsd(record.total_cost) }}</template>
                <template v-else-if="column.key === 'total_input'">{{ formatInt(record.total_input) }}</template>
                <template v-else-if="column.key === 'total_output'">{{ formatInt(record.total_output) }}</template>
              </template>
              <template #emptyText><a-empty :description="t('common.noData')" /></template>
            </a-table>
          </GlassCard>
        </a-tab-pane>
      </a-tabs>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import * as costApi from '@/api/modules/cost'
import type { BudgetStatus, DashboardMetrics, RollupStatus } from '@/api/modules/cost'

const { t } = useI18n()

const loading = ref(false)
const rolling = ref(false)
const storeUnavailable = ref(false)
const activeTab = ref('trend')

const metrics = ref<Partial<DashboardMetrics>>({})
const status = ref<RollupStatus | null>(null)
const budgets = ref<BudgetStatus[]>([])

function formatUsd(v: number): string {
  return `$${(Number(v) || 0).toFixed(4)}`
}
function formatInt(v: number): string {
  return (Number(v) || 0).toLocaleString()
}

// 柱状图数据（时间升序展示）
const hourlyBars = computed(() => toBars(metrics.value.hourly_trend ?? [], 'hour'))
const dailyBars = computed(() => toBars(metrics.value.last_7_days ?? [], 'date'))

function toBars(rows: any[], timeKey: string) {
  const asc = [...rows].reverse()
  const max = Math.max(...asc.map((r) => Number(r.total_cost) || 0), 0.000001)
  return asc.map((r) => ({
    label: String(r[timeKey] ?? '').slice(5, 13),
    cost: formatUsd(r.total_cost),
    heightPct: Math.max(4, Math.round((Number(r.total_cost) || 0) / max * 100)),
  }))
}

const budgetColumns = computed(() => [
  { title: '范围', dataIndex: 'scope', key: 'scope' },
  { title: '标识', dataIndex: 'identifier', key: 'identifier' },
  { title: '用量 / 预算', key: 'usage' },
  { title: '使用率', key: 'percentage', width: 180 },
  { title: '状态', key: 'state', width: 100 },
])

const dailyColumns = computed(() => [
  { title: '日期', dataIndex: 'date', key: 'date' },
  { title: '成本', key: 'total_cost', dataIndex: 'total_cost' },
  { title: '输入 Tokens', key: 'total_input', dataIndex: 'total_input' },
  { title: '输出 Tokens', key: 'total_output', dataIndex: 'total_output' },
  { title: '调用次数', dataIndex: 'call_count', key: 'call_count' },
])

async function fetchAll() {
  loading.value = true
  try {
    const [m, s, b] = await Promise.all([
      costApi.getDashboardMetrics().catch(() => null),
      costApi.getRollupStatus().catch(() => null),
      costApi.getAllBudgetStatuses().catch(() => null),
    ])
    storeUnavailable.value = m === null
    metrics.value = m ?? {}
    status.value = s
    budgets.value = b?.budgets ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

async function onRollupNow() {
  rolling.value = true
  try {
    const res = await costApi.forceRollupNow()
    message.success(`聚合完成，影响 ${res?.affected_rows ?? 0} 行`)
    await fetchAll()
  } catch {
    message.error('聚合失败')
  } finally {
    rolling.value = false
  }
}

onMounted(fetchAll)
</script>

<style scoped>
.cost-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
.chart-placeholder { display: flex; align-items: flex-end; gap: 6px; min-height: 180px; padding: 12px 0; }
.chart-bar-wrapper { display: flex; flex-direction: column; align-items: center; gap: 4px; flex: 1; height: 160px; justify-content: flex-end; }
.chart-bar { width: 100%; max-width: 40px; background: linear-gradient(180deg, #6366f1, #8b5cf6); border-radius: 4px 4px 0 0; min-height: 4px; transition: height 0.3s; }
.chart-label { font-size: 10px; color: var(--nr-text-muted); }
</style>
