<template>
  <div class="nr-qr-block" data-testid="qrcode-auth-block">
    <div class="nr-qr-label">{{ label }}</div>
    <GlassButton class="nr-qr-btn" variant="primary" size="sm" :loading="loading" data-testid="qrcode-fetch-btn" @click="fetchQrcode">
      {{ loading ? t('channel.qrcodeFetching') : buttonText }}
    </GlassButton>
    <div v-if="qrcodeImg" class="nr-qr-img-wrap" data-testid="qrcode-img-wrap">
      <img :src="`data:image/png;base64,${qrcodeImg}`" :alt="label" data-testid="qrcode-img" />
      <p class="nr-qr-hint">{{ hintText }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 渠道扫码授权块（对齐 QwenPaw QrcodeAuthBlock.tsx，2026-09-13 移植）。
 *
 * 嵌入配置弹窗：点按钮 → 后端真实平台协议生成二维码 → 轮询 → confirmed/success
 * 时 emit credentials，由页面回填表单。任意 QRCODE_AUTH_HANDLERS 渠道通用。
 */
import { useI18n } from 'vue-i18n'
import GlassButton from '@/components/GlassButton.vue'
import { useChannelQrcode } from '@/composables/useChannelQrcode'

const props = defineProps<{
  /** 后端 handler 键（feishu/dingtalk/qq/wecom/wechat） */
  channel: string
  label: string
  buttonText: string
  hintText: string
  successStatus?: string
  successCredentialKey: string
  pollInterval?: number
  pollTimeout?: number
  maxPollCount?: number
  params?: Record<string, string>
}>()

const emit = defineEmits<{
  (e: 'success', credentials: Record<string, string>): void
  (e: 'error', type: 'fetch' | 'expired' | 'fail'): void
}>()

const { t } = useI18n()

const { qrcodeImg, loading, fetchQrcode } = useChannelQrcode({
  channel: props.channel,
  successStatus: props.successStatus || 'success',
  successCredentialKey: props.successCredentialKey,
  pollInterval: props.pollInterval,
  pollTimeout: props.pollTimeout,
  maxPollCount: props.maxPollCount,
  params: props.params,
  onSuccess: (credentials) => emit('success', credentials),
  onError: (type) => emit('error', type),
})
</script>

<style scoped>
.nr-qr-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  margin-bottom: 12px;
  border: 1px dashed rgba(255, 255, 255, 0.12);
  border-radius: 10px;
}

.nr-qr-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-text-primary);
}

.nr-qr-btn {
  width: 100%;
  justify-content: center;
}

.nr-qr-img-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.nr-qr-img-wrap img {
  width: 200px;
  height: 200px;
  border-radius: 10px;
  background: #fff;
  object-fit: contain;
}

.nr-qr-hint {
  margin: 0;
  font-size: 12px;
  color: var(--nr-text-secondary);
  text-align: center;
}
</style>
