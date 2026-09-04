<template>
  <a-modal
    v-model:open="visible"
    :title="t('modelDownload.title')"
    :footer="null"
    :width="520"
    :mask-closable="false"
  >
    <p class="hint">{{ t('modelDownload.hint') }}</p>

    <div v-for="item in pending" :key="item.model" class="model-row">
      <div class="model-info">
        <div class="name">{{ item.description }}</div>
        <div class="meta">{{ item.model }} · {{ item.size_hint }}</div>
      </div>

      <!-- 未选择：源选择按钮组 -->
      <div v-if="stateOf(item.model)?.status !== 'done'" class="actions">
        <a-radio-group
          v-if="!started[item.model]"
          v-model:value="sourceChoice[item.model]"
          size="small"
        >
          <a-radio value="auto">{{ t('modelDownload.sourceAuto') }}</a-radio>
          <a-radio value="always_modelscope">{{ t('modelDownload.sourceCN') }}</a-radio>
          <a-radio value="always_huggingface">{{ t('modelDownload.sourceIntl') }}</a-radio>
        </a-radio-group>

        <a-progress
          v-if="stateOf(item.model)?.status === 'downloading' || stateOf(item.model)?.status === 'done'"
          :percent="Math.round(stateOf(item.model)?.percentage ?? 0)"
          :status="stateOf(item.model)?.status === 'done' ? 'success' : 'active'"
          size="small"
        />
        <div v-if="stateOf(item.model)?.status === 'failed'" class="err">
          {{ stateOf(item.model)?.error }}
        </div>

        <div class="btns">
          <a-button
            v-if="!started[item.model]"
            type="primary"
            size="small"
            @click="start(item)"
          >{{ t('modelDownload.download') }}</a-button>
          <a-button
            v-if="stateOf(item.model)?.status === 'failed'"
            size="small"
            @click="start(item)"
          >{{ t('modelDownload.retry') }}</a-button>
          <a-button
            v-if="!started[item.model]"
            size="small"
            @click="skip(item)"
          >{{ t('modelDownload.skip') }}</a-button>
        </div>
      </div>
      <a-tag v-else color="success">{{ t('modelDownload.done') }}</a-tag>
    </div>

    <div class="foot">
      <a-button size="small" type="link" @click="visible = false">{{ t('modelDownload.later') }}</a-button>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import {
  listPendingDownloads,
  setDownloadSource,
  triggerDownload,
  getDownloadProgress,
  type DownloadChoice,
  type PendingDownloadItem,
  type DownloadState,
} from '@/api/modules/models'

const { t } = useI18n()
const visible = ref(false)
const pending = ref<PendingDownloadItem[]>([])
const states = ref<DownloadState[]>([])
const started = reactive<Record<string, boolean>>({})
const sourceChoice = reactive<Record<string, DownloadChoice>>({})

const stateOf = computed(() => {
  const map = new Map(states.value.map((s) => [s.model, s]))
  return (model: string) => map.get(model)
})

let pollTimer: number | null = null

async function open() {
  try {
    const items = await listPendingDownloads()
    pending.value = (items as PendingDownloadItem[]).filter((i) => !i.available)
    if (!pending.value.length) return
    for (const i of pending.value) {
      sourceChoice[i.model] = i.choice === 'skip' ? 'auto' : i.choice
    }
    visible.value = true
    startPolling()
  } catch {
    /* 静默：提示框是尽力而为的增强，失败不打扰用户 */
  }
}

function startPolling() {
  if (pollTimer !== null) return
  pollTimer = window.setInterval(async () => {
    if (!visible.value) return stopPolling()
    try {
      states.value = await getDownloadProgress()
    } catch {
      /* 轮询失败静默 */
    }
  }, 1000)
}

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function start(item: PendingDownloadItem) {
  started[item.model] = true
  try {
    const choice = sourceChoice[item.model] || 'auto'
    // 先持久化选择（下次不再问），再触发下载
    await setDownloadSource({ model: item.model, choice })
    await triggerDownload({ model: item.model })
    states.value = await getDownloadProgress()
  } catch (e: unknown) {
    started[item.model] = false
    message.error(t('modelDownload.triggerFailed'))
  }
}

async function skip(item: PendingDownloadItem) {
  started[item.model] = true
  try {
    await setDownloadSource({ model: item.model, choice: 'skip' })
    message.info(t('modelDownload.skippedHint'))
  } catch {
    /* 静默 */
  }
}

watch(visible, (v) => {
  if (!v) stopPolling()
})

defineExpose({ open })
</script>

<style scoped>
.hint { color: var(--nr-text-secondary, #888); margin-bottom: 16px; }
.model-row {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 10px 0; border-bottom: 1px solid rgba(128,128,128,.15);
}
.model-row:last-of-type { border-bottom: none; }
.model-info { flex: 1; min-width: 0; }
.model-info .name { font-weight: 600; }
.model-info .meta { font-size: 12px; color: var(--nr-text-secondary, #999); margin-top: 2px; }
.actions { width: 260px; }
.btns { margin-top: 8px; display: flex; gap: 8px; }
.err { color: #e05555; font-size: 12px; margin-top: 4px; word-break: break-all; }
.foot { text-align: right; margin-top: 8px; }
</style>
