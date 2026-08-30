<script setup lang="ts">
/**
 * WorkflowVersionsDrawer.vue — 工作流版本历史与回滚（P2-4.4 前端）
 *
 * 列出 workflow_versions（倒序），一键回滚（confirm 后调 API）。
 * 回滚成功后 emit refreshed 让父组件重载画布。
 */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  listWorkflowVersions,
  rollbackWorkflowVersion,
} from '@/api/modules/collaboration'

const props = defineProps<{
  open: boolean
  workflowId: string | null
}>()

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'refreshed'): void
}>()

const { t } = useI18n()

interface VersionItem {
  version: number
  snapshot_json: string
  commit_msg: string
  created_at: number
}

const versions = ref<VersionItem[]>([])
const loading = ref(false)
const rollingBack = ref<number | null>(null)

watch(
  () => [props.open, props.workflowId] as const,
  async ([open, wfId]) => {
    if (!open || !wfId) return
    loading.value = true
    versions.value = []
    try {
      const res = await listWorkflowVersions(wfId)
      versions.value = (res?.data ?? res) as unknown as VersionItem[]
    } catch {
      versions.value = []
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

async function handleRollback(version: number) {
  if (!props.workflowId || rollingBack.value !== null) return
  rollingBack.value = version
  try {
    await rollbackWorkflowVersion(props.workflowId, version)
    emit('refreshed')
  } catch {
    /* 错误由全局拦截器提示 */
  } finally {
    rollingBack.value = null
  }
}

function formatTime(ts: number): string {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString()
}
</script>

<template>
  <a-drawer
    :open="open"
    :title="t('workflowVersion.drawerTitle')"
    :width="480"
    @close="emit('update:open', false)"
  >
    <a-spin :spinning="loading">
      <div v-if="versions.length === 0" class="ver-empty">
        {{ t('workflowVersion.empty') }}
      </div>
      <div v-else class="ver-list">
        <div v-for="v in versions" :key="v.version" class="ver-row" data-testid="version-row">
          <div class="ver-main">
            <span class="ver-badge">v{{ v.version }}</span>
            <span class="ver-time">{{ formatTime(v.created_at) }}</span>
            <span class="ver-msg">{{ v.commit_msg }}</span>
          </div>
          <a-popconfirm
            :title="t('workflowVersion.rollbackConfirm', { version: v.version })"
            @confirm="handleRollback(v.version)"
          >
            <a-button size="small" :loading="rollingBack === v.version">
              {{ t('workflowVersion.rollback') }}
            </a-button>
          </a-popconfirm>
        </div>
      </div>
    </a-spin>
  </a-drawer>
</template>

<style scoped>
.ver-empty {
  color: var(--nr-text-tertiary, #6b7280);
  font-size: 13px;
  padding: 24px 0;
  text-align: center;
}
.ver-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ver-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border: 1px solid var(--nr-border, #e5e7eb);
  border-radius: 6px;
}
.ver-main {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.ver-badge {
  font-family: monospace;
  background: var(--nr-bg-muted, #f3f4f6);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.ver-time {
  font-size: 12px;
  color: var(--nr-text-tertiary, #6b7280);
}
.ver-msg {
  font-size: 12px;
  color: var(--nr-text-secondary, #4b5563);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>