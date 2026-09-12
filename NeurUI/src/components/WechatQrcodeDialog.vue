<template>
  <div v-if="visible" class="nr-wechat-qr-backdrop" data-testid="qr-backdrop" @click.self="handleClose">
    <div class="nr-wechat-qr-dialog" role="dialog" :aria-label="t('channel.qrTitle')">
      <div class="nr-wechat-qr-header">
        <h3>{{ t('channel.qrTitle') }}</h3>
        <button class="nr-wechat-qr-close" data-testid="qr-close" @click="handleClose">&times;</button>
      </div>
      <div class="nr-wechat-qr-body">
        <div class="nr-wechat-qr-img" data-testid="qr-image-wrap">
          <img v-if="qrUrl" :src="qrUrl" :alt="t('channel.qrTitle')" data-testid="qr-image" />
          <a-spin v-else size="large" />
        </div>
        <p class="nr-wechat-qr-hint">{{ t('channel.qrHint') }}</p>
        <p class="nr-wechat-qr-status" :data-state="status" data-testid="qr-status">
          {{ statusText }}
        </p>
        <a-button
          v-if="status === 'expired' || status === 'error'"
          type="primary"
          block
          data-testid="qr-regenerate"
          @click="emit('regenerate')"
        >
          {{ t('channel.qrRegenerate') }}
        </a-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// F-3（2026-09-12）：iLink 微信渠道首次接入扫码闭环。
// 职责：展示二维码 + 3s 轮询 status 端点 + 状态机（pending/scanned/confirmed/expired/error）。
// 资源纪律：confirmed/expired/error/关闭/卸载任一终态都必须 clearInterval。
import { ref, computed, watch, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getWechatIlinkQrcodeStatus } from '@/api/modules/channel-configs'

const props = defineProps<{
  visible: boolean
  qrUrl: string
  qrId: string
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'confirmed'): void
  (e: 'regenerate'): void
}>()

const { t } = useI18n()

type QrStatus = 'pending' | 'scanned' | 'confirmed' | 'expired' | 'error'

const status = ref<QrStatus>('pending')
const POLL_INTERVAL_MS = 3000
const MAX_CONSECUTIVE_ERRORS = 3

let timer: ReturnType<typeof setInterval> | null = null
let consecutiveErrors = 0

const statusText = computed(() => {
  const map: Record<QrStatus, string> = {
    pending: t('channel.qrWaiting'),
    scanned: t('channel.qrScanned'),
    confirmed: t('channel.qrConfirmed'),
    expired: t('channel.qrExpired'),
    error: t('channel.qrError'),
  }
  return map[status.value]
})

function stopPolling() {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

async function poll() {
  if (!props.qrId) return
  try {
    const data = (await getWechatIlinkQrcodeStatus(props.qrId)) as { status?: string }
    consecutiveErrors = 0
    const s = data?.status
    if (s === 'confirmed') {
      status.value = 'confirmed'
      stopPolling()
      emit('confirmed')
    } else if (s === 'expired') {
      status.value = 'expired'
      stopPolling()
    } else if (s === 'scanned') {
      status.value = 'scanned'
    } else {
      status.value = 'pending'
    }
  } catch {
    consecutiveErrors += 1
    if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
      status.value = 'error'
      stopPolling()
    }
  }
}

function startPolling() {
  stopPolling()
  status.value = 'pending'
  consecutiveErrors = 0
  if (!props.qrId) return
  void poll()
  timer = setInterval(() => {
    void poll()
  }, POLL_INTERVAL_MS)
}

watch(
  () => [props.visible, props.qrId] as const,
  ([visible, qrId]) => {
    if (visible && qrId) startPolling()
    else stopPolling()
  },
  { immediate: true },
)

function handleClose() {
  emit('update:visible', false)
}

onUnmounted(stopPolling)
</script>

<style scoped>
.nr-wechat-qr-backdrop {
  position: fixed;
  inset: 0;
  z-index: 10010; /* 高于配置弹窗（9999），支持在保存流程之上叠加 */
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: nrWechatQrFadeIn 0.2s ease;
}

@keyframes nrWechatQrFadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.nr-wechat-qr-dialog {
  width: 340px;
  max-width: 92vw;
  border-radius: 16px;
  background: rgba(22, 22, 30, 0.96);
  backdrop-filter: blur(24px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.5);
}

.nr-wechat-qr-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.nr-wechat-qr-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--nr-text-primary);
}

.nr-wechat-qr-close {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--nr-text-secondary);
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.nr-wechat-qr-close:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--nr-text-primary);
}

.nr-wechat-qr-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 20px 24px 24px;
}

.nr-wechat-qr-img {
  width: 200px;
  height: 200px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.nr-wechat-qr-img img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.nr-wechat-qr-hint {
  margin: 0;
  font-size: 13px;
  color: var(--nr-text-secondary);
  text-align: center;
}

.nr-wechat-qr-status {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-text-primary);
}

.nr-wechat-qr-status[data-state='scanned'] {
  color: var(--nr-warning, #faad14);
}

.nr-wechat-qr-status[data-state='confirmed'] {
  color: var(--nr-success, #22c55e);
}

.nr-wechat-qr-status[data-state='expired'],
.nr-wechat-qr-status[data-state='error'] {
  color: var(--nr-error, #ef4444);
}
</style>
