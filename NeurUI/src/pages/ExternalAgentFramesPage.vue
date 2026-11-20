<template>
  <div class="frames-page">
    <h2 class="frames-title">{{ t('neuacp.framesTitle') }}</h2>

    <div v-if="!isAdmin" class="frames-notice">{{ t('neuacp.framesNotAdmin') }}</div>

    <template v-else>
      <div class="frames-controls">
        <a-input
          v-model:value="subagentId"
          class="frames-id-input"
          :placeholder="t('neuacp.framesIdPlaceholder')"
          @keyup.enter="loadFrames(true)"
        />
        <GlassButton variant="primary" size="sm" :loading="loading" @click="loadFrames(true)">
          {{ t('neuacp.framesLoad') }}
        </GlassButton>
      </div>

      <div v-if="errorMsg" class="frames-notice is-error">{{ t('neuacp.framesLoadFailed') }}: {{ errorMsg }}</div>

      <div v-if="frames.length" class="frames-list">
        <div v-for="f in frames" :key="f.seq" class="frame-row">
          <span class="frame-seq" :title="t('neuacp.framesDirection')">#{{ f.seq }}</span>
          <span class="frame-dir" :class="`dir-${f.direction}`">{{ f.direction }}</span>
          <span class="frame-type">{{ frameType(f) }}</span>
          <span class="frame-time">{{ frameTime(f.occurred_at) }}</span>
          <span class="frame-payload" :title="frameText(f)">{{ frameText(f) }}</span>
        </div>
        <div class="frames-more">
          <GlassButton
            v-if="hasMore"
            variant="secondary"
            size="sm"
            :loading="loading"
            @click="loadFrames(false)"
          >
            {{ t('neuacp.framesLoadMore') }}
          </GlassButton>
        </div>
      </div>
      <div v-else-if="loaded && !loading" class="frames-notice">{{ t('neuacp.framesEmpty') }}</div>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * 外部代理帧回放（F2 帧账本读面的 admin 调试视图）。
 *
 * 数据源：GET /v1/external-agents/runs/{id}/frames（admin 门+同租户由后端承担，
 * 非 admin 在本页先行拦截给出诚实提示）。after_seq 游标翻页：首页从 0 起，
 * 续页取已加载末条 seq；limit 固定 200（服务端夹取 [1,1000]）。
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { fetchNeuacpRunFrames } from '@/api/modules/neuacp'
import { useAuthStore } from '@/stores/auth'
import GlassButton from '@/components/GlassButton.vue'
import type { NeuacpFrameRecord } from '@/types/agent'

const { t } = useI18n()
const authStore = useAuthStore()
const isAdmin = ref(authStore.user?.role === 'admin')

const subagentId = ref('')
const frames = ref<NeuacpFrameRecord[]>([])
const loading = ref(false)
const errorMsg = ref('')
const loaded = ref(false)
/** 已加载末条 seq（游标）；首页从 0 起 */
const cursor = ref(0)
/** 服务端按 limit 满页返回时可能还有下一页 */
const hasMore = ref(false)

const PAGE_LIMIT = 200

function frameType(f: NeuacpFrameRecord): string {
  return String((f.frame || {}).type ?? '—')
}

function frameText(f: NeuacpFrameRecord): string {
  try {
    const text = JSON.stringify(f.frame)
    return text.length > 160 ? `${text.slice(0, 160)}…` : text
  } catch {
    return String(f.frame)
  }
}

/** 帧时间展示（局部格式化；命名避开 SubAgentPanel.shortTime 的跨文件同名组） */
function frameTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString()
}

async function loadFrames(reset: boolean) {
  const sid = subagentId.value.trim()
  if (!sid) {
    message.warning(t('neuacp.framesIdRequired'))
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const start = reset ? 0 : cursor.value
    const res = await fetchNeuacpRunFrames(sid, start, PAGE_LIMIT)
    const batch = Array.isArray(res?.frames) ? res.frames : []
    frames.value = reset ? batch : frames.value.concat(batch)
    const last = frames.value[frames.value.length - 1]
    cursor.value = last ? Number(last.seq) : start
    hasMore.value = batch.length >= PAGE_LIMIT
    loaded.value = true
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : String(err)
    message.error(t('neuacp.framesLoadFailed'))
  } finally {
    loading.value = false
  }
}

defineExpose({
  subagentId,
  frames,
  cursor,
  hasMore,
  loadFrames,
})
</script>

<style scoped>
.frames-page { display: flex; flex-direction: column; gap: 14px; padding: 4px 2px; }
.frames-title { margin: 0; font-size: 18px; font-weight: 700; color: var(--nr-text-primary, #e2e8f0); }
.frames-controls { display: flex; gap: 10px; align-items: center; }
.frames-id-input { max-width: 420px; }
.frames-notice {
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--nr-border, rgba(99, 102, 241, 0.25));
  color: var(--nr-text-secondary, #cbd5e1);
  font-size: 13px;
}
.frames-notice.is-error { color: var(--nr-error, #f87171); border-color: var(--nr-error-soft-border, rgba(248, 113, 113, 0.35)); }
.frames-list {
  border: 1px solid var(--nr-border, rgba(99, 102, 241, 0.25));
  border-radius: 10px;
  overflow: hidden;
}
.frame-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  font-size: 12px;
  border-bottom: 1px dashed var(--nr-border, rgba(99, 102, 241, 0.15));
}
.frame-row:last-child { border-bottom: none; }
.frame-seq { flex-shrink: 0; font-weight: 700; color: var(--nr-text-tertiary, #94a3b8); min-width: 44px; }
.frame-dir {
  flex-shrink: 0;
  padding: 1px 8px;
  border-radius: 8px;
  font-weight: 600;
  text-transform: uppercase;
  font-size: 10px;
  border: 1px solid var(--nr-border, rgba(99, 102, 241, 0.35));
  color: var(--nr-text-secondary, #cbd5e1);
}
.frame-dir.dir-in { color: var(--nr-primary-light, #818cf8); }
.frame-dir.dir-out { color: var(--nr-warning, #facc15); }
.frame-dir.dir-observed { color: var(--nr-success, #4ade80); }
.frame-type { flex-shrink: 0; font-weight: 600; color: var(--nr-text-primary, #e2e8f0); min-width: 90px; }
.frame-time { flex-shrink: 0; color: var(--nr-text-tertiary, #94a3b8); }
.frame-payload {
  flex: 1;
  color: var(--nr-text-secondary, #cbd5e1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.frames-more { display: flex; justify-content: center; padding: 8px; }
</style>
