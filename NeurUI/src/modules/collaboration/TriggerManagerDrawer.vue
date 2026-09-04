<script setup lang="ts">
/**
 * TriggerManagerDrawer.vue — 工作流触发器管理（P1 前端集成）
 *
 * 列出/创建/删除/手动触发触发器（webhook/cron/manual）。
 * webhook 创建后的明文 secret 仅展示一次（复制提示）。
 */
import { ref, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import {
  listWorkflowTriggers,
  createWorkflowTrigger,
  deleteWorkflowTrigger,
  fireWorkflowTrigger,
  listFailedDeliveries,
  retryDelivery,
  retryDueDeliveries,
  type WorkflowTriggerSummary,
} from '@/api/modules/collaboration'

const props = defineProps<{
  open: boolean
  workflowId: string | null
}>()

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
}>()

const { t } = useI18n()

const triggers = ref<WorkflowTriggerSummary[]>([])
const loading = ref(false)
const busy = ref<string | null>(null)

// ── P2 失败投递重试 ──
interface FailedDelivery {
  id: number
  trigger_id: string
  status_code: number
  attempt: number
  created_at: number
}
const failedDeliveries = ref<FailedDelivery[]>([])
const retrying = ref<number | null>(null)
const bulkRetrying = ref(false)

async function reloadFailed() {
  try {
    const res = await listFailedDeliveries(50)
    const data = (res?.data ?? res) as unknown as { items?: FailedDelivery[] }
    failedDeliveries.value = data?.items ?? []
  } catch {
    failedDeliveries.value = []
  }
}

async function handleRetry(id: number) {
  retrying.value = id
  try {
    await retryDelivery(id)
    message.success(t('trigger.retrySuccess'))
    await reloadFailed()
  } catch {
    /* 拦截器已提示 */
  } finally {
    retrying.value = null
  }
}

async function handleRetryDue() {
  bulkRetrying.value = true
  try {
    const res = await retryDueDeliveries()
    const data = (res?.data ?? res) as { count?: number }
    message.success(t('trigger.retryDueDone', { n: data?.count ?? 0 }))
    await reloadFailed()
  } catch {
    /* 拦截器已提示 */
  } finally {
    bulkRetrying.value = false
  }
}

// ── 新建表单 ──
const creating = ref(false)
const newType = ref<'webhook' | 'cron'>('webhook')
const newCron = ref('0 9 * * 1-5')
const newRateLimit = ref<number | null>(null)
const submitLoading = ref(false)
/** 一次性 secret 展示（创建 webhook 后） */
const oneTimeSecret = ref<string | null>(null)

async function reload() {
  if (!props.workflowId) return
  loading.value = true
  try {
    const res = await listWorkflowTriggers(props.workflowId)
    triggers.value = (res?.data ?? res) as unknown as WorkflowTriggerSummary[]
  } catch {
    triggers.value = []
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.open, props.workflowId] as const,
  async ([open, wfId]) => {
    if (open && wfId) {
      await reload()
      await reloadFailed()
    }
  },
  { immediate: true },
)

const canSubmit = computed(
  () => !!props.workflowId && (newType.value === 'webhook' || !!newCron.value.trim()),
)

async function handleCreate() {
  if (!props.workflowId || submitLoading.value) return
  submitLoading.value = true
  oneTimeSecret.value = null
  try {
    const payload: { type: string; config?: Record<string, unknown>; rate_limit_per_minute?: number } = { type: newType.value }
    if (newType.value === 'cron') payload.config = { cron: newCron.value.trim() }
    if (newRateLimit.value) payload.rate_limit_per_minute = newRateLimit.value
    const res = await createWorkflowTrigger(props.workflowId, payload)
    const data = (res?.data ?? res) as { trigger: WorkflowTriggerSummary; secret?: string }
    if (data?.secret) oneTimeSecret.value = data.secret
    message.success(t('trigger.created'))
    await reload()
  } catch {
    /* 拦截器已提示 */
  } finally {
    submitLoading.value = false
  }
}

async function handleDelete(id: string) {
  busy.value = id
  try {
    await deleteWorkflowTrigger(id)
    await reload()
  } finally {
    busy.value = null
  }
}

async function handleFire(id: string) {
  busy.value = `${id}:fire`
  try {
    await fireWorkflowTrigger(id)
    message.success(t('trigger.fired'))
  } finally {
    busy.value = null
  }
}

function typeLabel(type: string): string {
  const map: Record<string, string> = {
    webhook: 'typeWebhook',
    cron: 'typeCron',
    manual: 'typeManual',
    plugin: 'typePlugin',
  }
  return t(`trigger.${map[type] ?? 'typeManual'}`)
}
</script>

<template>
  <a-drawer
    :open="open"
    :title="t('trigger.drawerTitle')"
    :width="560"
    @close="emit('update:open', false)"
  >
    <a-spin :spinning="loading">
      <!-- 一次性 secret 提示 -->
      <a-alert
        v-if="oneTimeSecret"
        type="warning"
        show-icon
        class="trig-secret-alert"
        :message="t('trigger.secretOnceTitle')"
        :description="oneTimeSecret"
      />

      <!-- 触发器列表 -->
      <div v-if="triggers.length === 0" class="trig-empty">
        {{ t('trigger.empty') }}
      </div>
      <div v-else class="trig-list">
        <div v-for="tr in triggers" :key="tr.id" class="trig-row" data-testid="trigger-row">
          <div class="trig-main">
            <div class="trig-title">
              <span class="trig-badge" :class="`badge-${tr.type}`">{{ typeLabel(tr.type) }}</span>
              <span class="trig-id">{{ tr.id.slice(0, 14) }}</span>
              <a-tag v-if="!tr.enabled" color="red">{{ t('trigger.disabled') }}</a-tag>
            </div>
            <div class="trig-meta">
              <span v-if="tr.type === 'cron'">cron: {{ tr.config?.cron || '-' }}</span>
              <span v-else-if="tr.rate_limit_per_minute">
                {{ t('trigger.rateLimit', { n: tr.rate_limit_per_minute }) }}
              </span>
              <span v-else>{{ t('trigger.webhookHint') }}</span>
            </div>
          </div>
          <div class="trig-actions">
            <a-button size="small" :loading="busy === `${tr.id}:fire`" @click="handleFire(tr.id)">
              {{ t('trigger.fire') }}
            </a-button>
            <a-popconfirm :title="t('trigger.deleteConfirm')" @confirm="handleDelete(tr.id)">
              <a-button size="small" danger :loading="busy === tr.id">
                {{ t('common.delete') }}
              </a-button>
            </a-popconfirm>
          </div>
        </div>
      </div>

      <!-- P2 失败投递重试 -->
      <template v-if="failedDeliveries.length > 0">
        <a-divider>
          <span>{{ t('trigger.failedDeliveries') }}（{{ failedDeliveries.length }}）</span>
        </a-divider>
        <div class="trig-list">
          <div v-for="d in failedDeliveries" :key="d.id" class="trig-row" data-testid="delivery-row">
            <div class="trig-main">
              <div class="trig-title">
                <a-tag color="red">HTTP {{ d.status_code }}</a-tag>
                <span class="trig-id">#{{ d.id }} · {{ d.trigger_id.slice(0, 12) }}</span>
                <a-tag v-if="d.attempt > 0" color="orange">×{{ d.attempt }}</a-tag>
              </div>
            </div>
            <div class="trig-actions">
              <a-button size="small" :loading="retrying === d.id" @click="handleRetry(d.id)">
                {{ t('trigger.retry') }}
              </a-button>
            </div>
          </div>
        </div>
        <a-button size="small" block style="margin-top: 8px" :loading="bulkRetrying" @click="handleRetryDue">
          {{ t('trigger.retryDueAll') }}
        </a-button>
      </template>

      <a-divider>{{ t('trigger.createDivider') }}</a-divider>

      <!-- 新建表单 -->
      <div class="trig-form">
        <div class="form-row">
          <label>{{ t('trigger.typeLabel') }}</label>
          <a-select v-model:value="newType" style="flex: 1">
            <a-select-option value="webhook">{{ t('trigger.typeWebhook') }}</a-select-option>
            <a-select-option value="cron">{{ t('trigger.typeCron') }}</a-select-option>
          </a-select>
        </div>
        <div v-if="newType === 'cron'" class="form-row">
          <label>cron</label>
          <a-input v-model:value="newCron" placeholder="0 9 * * 1-5" style="flex: 1" />
        </div>
        <div class="form-row">
          <label>{{ t('trigger.rateLimitLabel') }}</label>
          <a-input-number
            v-model:value="newRateLimit"
            :min="1"
            :placeholder="t('trigger.rateLimitPh')"
            style="flex: 1"
          />
        </div>
        <a-button
          type="primary"
          block
          :loading="submitLoading"
          :disabled="!canSubmit"
          data-testid="trigger-create"
          @click="handleCreate"
        >
          {{ t('trigger.create') }}
        </a-button>
      </div>
    </a-spin>
  </a-drawer>
</template>

<style scoped>
.trig-secret-alert {
  margin-bottom: 12px;
  word-break: break-all;
}
.trig-empty {
  color: var(--nr-text-tertiary, #6b7280);
  font-size: 13px;
  padding: 16px 0;
  text-align: center;
}
.trig-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.trig-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--nr-border, #e5e7eb);
  border-radius: 6px;
}
.trig-main {
  min-width: 0;
}
.trig-title {
  display: flex;
  align-items: center;
  gap: 6px;
}
.trig-badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--nr-bg-muted, #f3f4f6);
}
.trig-badge.cron {
  background: var(--nr-primary-bg, #e6f4ff);
}
.trig-id {
  font-family: monospace;
  font-size: 12px;
}
.trig-meta {
  font-size: 12px;
  color: var(--nr-text-tertiary, #6b7280);
  margin-top: 2px;
}
.trig-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.trig-form .form-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.trig-form label {
  width: 90px;
  font-size: 13px;
  flex-shrink: 0;
}
</style>