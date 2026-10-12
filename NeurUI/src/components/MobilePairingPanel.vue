<template>
  <section class="nr-mpp" data-testid="mobile-pairing-panel">
    <div class="nr-mpp-head">
      <div>
        <h3 class="nr-mpp-title">{{ t('channel.mobile') }}</h3>
        <p class="nr-mpp-desc">{{ t('channel.mobilePairingDesc') }}</p>
      </div>
      <GlassButton size="sm" variant="primary" data-testid="pairing-generate"
        :disabled="generating" @click="generate">
        {{ generating ? t('channel.pairingGenerating') : t('channel.pairingGenerate') }}
      </GlassButton>
    </div>

    <!-- 权限态与空态不合并（与渠道身份面板同纪律）：401/403 要说"无权/未登录"，
         不能退化成"还没有设备"——后者把登录问题伪装成空数据。 -->
    <p v-if="errorText" class="nr-mpp-error" data-testid="pairing-error">{{ errorText }}</p>

    <div v-if="pairing" class="nr-mpp-active" data-testid="pairing-active">
      <div class="nr-mpp-qr">
        <!-- 图不是 `<img :src="qr_code_url">`：那一口带登录门，而资源标签发不出
             Authorization 头。取图走带凭证的 blob（`mobile.ts::getPairingQrcodeBlob`），
             自建的 object URL 由本面板持有并在换码/卸载时释放。 -->
        <img v-if="qrUrl" :src="qrUrl" :alt="t('channel.scanQR')" data-testid="pairing-qr" />
        <p class="nr-mpp-scan">{{ t('channel.scanQR') }}</p>
      </div>
      <div class="nr-mpp-meta">
        <p class="nr-mpp-code" data-testid="pairing-code">{{ pairing.code }}</p>
        <p class="nr-mpp-expires">{{ t('channel.pairingExpiresIn', { seconds: pairing.expires_in }) }}</p>
        <a-tag :color="statusColor" data-testid="pairing-status">{{ statusText }}</a-tag>
      </div>
    </div>
    <p v-else-if="!errorText" class="nr-mpp-idle" data-testid="pairing-idle">
      {{ t('channel.pairingIdle') }}
    </p>

    <div class="nr-mpp-devices" data-testid="pairing-devices">
      <p class="nr-mpp-sub">{{ t('channel.pairingDevicesTitle') }}</p>
      <div v-if="!devices.length && !errorText" class="nr-mpp-empty" data-testid="pairing-devices-empty">
        {{ t('channel.pairingDevicesEmpty') }}
      </div>
      <ul v-else class="nr-mpp-list">
        <li v-for="d in devices" :key="d.pairing_id" class="nr-mpp-item" data-testid="pairing-device">
          <span class="nr-mpp-name">{{ d.device_name }}</span>
          <a-tag :color="d.is_online ? 'green' : 'default'" data-testid="pairing-device-state">
            {{ d.is_online ? t('channel.pairingOnline') : t('channel.pairingOffline') }}
          </a-tag>
          <GlassButton size="sm" variant="danger" :data-testid="'pairing-revoke-' + d.pairing_id"
            @click="unpair(d)">
            {{ t('channel.pairingRevoke') }}
          </GlassButton>
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup lang="ts">
/**
 * 移动端配对面板（工单 2026-10-13 批 29，用户裁定「建配对面板」）。
 *
 * 这条链的后端在 §6-154／§6-161／§6-172 三批里逐一修通（调用形状、请求级属主、
 * 凭据不出本机、真二维码、回连地址可达、读口上登录门），**但一直没有任何用户可达入口**：
 * 配对码只能在服务器上凭空存在 300 秒，没人能把它交给手机。这一块补的就是那一步。
 *
 * 面板只做三件事：发码 → 等手机扫 → 列出/解绑已配设备。刻意**不**在这里挑选
 * "这台设备算哪个账号"——归属只从登录态出（后端 `Depends(_get_current_user_id)`），
 * 与渠道身份面板同一口径：能点面板的人不该同时能决定归属。
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import GlassButton from '@/components/GlassButton.vue'
import {
  generatePairing, getPairedDevices, getPairingQrcodeBlob, getPairingStatus, revokePairing,
  type PairedDevice, type PairingCode, type PairingStatus,
} from '@/api/modules/mobile'

const { t } = useI18n()

/** 轮询间隔：配对码本身 300 秒过期，2 秒已经够"扫完立刻有反馈"，不必更快。 */
const POLL_MS = 2000

const generating = ref(false)
const pairing = ref<PairingCode | null>(null)
const status = ref<PairingStatus | null>(null)
const devices = ref<PairedDevice[]>([])
const errorText = ref('')
const qrUrl = ref('')

let ownedUrl = ''
let timer: ReturnType<typeof setInterval> | null = null

const statusText = computed(() => {
  const s = status.value?.status ?? 'pending'
  if (s === 'confirmed') return t('channel.pairingStatusConfirmed')
  if (s === 'expired' || s === 'revoked') return t('channel.pairingStatusExpired')
  return t('channel.pairingStatusPending')
})
const statusColor = computed(() => (status.value?.status === 'confirmed' ? 'green' : 'default'))

function releaseQr() {
  if (ownedUrl) URL.revokeObjectURL(ownedUrl)
  ownedUrl = ''
  qrUrl.value = ''
}

function stopPairingPolling() {
  if (timer) clearInterval(timer)
  timer = null
}

function pairingErrorText(e: any): string {
  const code = e?.response?.status
  if (code === 401 || code === 403) return t('channel.pairingDenied')
  return t('channel.pairingFailed', {
    reason: String(e?.response?.data?.detail || e?.message || ''),
  })
}

async function loadDevices() {
  try {
    const res: any = await getPairedDevices()
    const body = res?.data ?? res
    devices.value = Array.isArray(body?.devices) ? body.devices : []
    errorText.value = ''
  } catch (e: any) {
    errorText.value = pairingErrorText(e)
  }
}

async function showQr(code: string) {
  releaseQr()
  const blob = await getPairingQrcodeBlob(code)
  ownedUrl = URL.createObjectURL(blob)
  qrUrl.value = ownedUrl
}

async function tick() {
  if (!pairing.value) return
  try {
    const res: any = await getPairingStatus(pairing.value.code)
    status.value = (res?.data ?? res) as PairingStatus
    if (status.value?.status === 'confirmed') {
      // 扫完就该收摊：那张图的内容是一个凭据，留着等于在屏幕上挂一把过期的钥匙
      stopPairingPolling()
      releaseQr()
      pairing.value = null
      await loadDevices()
    } else if (status.value?.status === 'expired' || status.value?.status === 'revoked') {
      stopPairingPolling()
      releaseQr()
    }
  } catch (e: any) {
    // 读不到状态就是**不知道**：继续挂着二维码与"等待扫码"，等于把权限/网络问题
    // 扮成进行中（与渠道身份面板"403 不许伪装成空态"同一条纪律）。整块撤下。
    stopPairingPolling()
    releaseQr()
    pairing.value = null
    status.value = null
    errorText.value = pairingErrorText(e)
  }
}

async function generate() {
  if (generating.value) return
  generating.value = true
  errorText.value = ''
  stopPairingPolling()
  releaseQr()
  try {
    const res: any = await generatePairing({ device_name: 'web', device_type: 'mobile' })
    const body = (res?.code ? res : res?.data) as PairingCode
    pairing.value = body
    status.value = { code: body.code, status: 'pending' }
    await showQr(body.code)
    timer = setInterval(tick, POLL_MS)
  } catch (e: any) {
    errorText.value = pairingErrorText(e)
  } finally {
    generating.value = false
  }
}

async function unpair(device: PairedDevice) {
  errorText.value = ''
  try {
    await revokePairing(device.pairing_id)
    await loadDevices()
  } catch (e: any) {
    errorText.value = pairingErrorText(e)
  }
}

loadDevices()

onBeforeUnmount(() => {
  stopPairingPolling()
  releaseQr()
})
</script>

<style scoped>
.nr-mpp { margin-top: 24px; padding: 16px 18px; border: 1px solid var(--nr-border-subtle, rgba(255, 255, 255, 0.1)); border-radius: 14px; }
.nr-mpp-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.nr-mpp-title { margin: 0; font-size: 15px; font-weight: 600; color: var(--nr-text-primary); }
.nr-mpp-desc { margin: 4px 0 0; font-size: 12px; color: var(--nr-text-tertiary); max-width: 60ch; }
.nr-mpp-error { margin: 12px 0 0; font-size: 12px; color: var(--nr-color-danger, #e11d48); }
.nr-mpp-idle { margin: 12px 0 0; font-size: 12px; color: var(--nr-text-tertiary); }
.nr-mpp-active { display: flex; gap: 18px; align-items: center; margin-top: 14px; }
.nr-mpp-qr { display: flex; flex-direction: column; align-items: center; gap: 6px; }
.nr-mpp-qr img { width: 200px; height: 200px; border-radius: 10px; background: var(--nr-surface-raised, rgba(255, 255, 255, 0.04)); }
.nr-mpp-scan { margin: 0; font-size: 12px; color: var(--nr-text-secondary); }
.nr-mpp-meta { display: flex; flex-direction: column; gap: 6px; }
.nr-mpp-code { margin: 0; font-size: 22px; letter-spacing: 4px; font-weight: 700; color: var(--nr-text-primary); }
.nr-mpp-expires { margin: 0; font-size: 12px; color: var(--nr-text-tertiary); }
.nr-mpp-sub { margin: 16px 0 6px; font-size: 12px; color: var(--nr-text-secondary); }
.nr-mpp-empty { margin-top: 8px; font-size: 12px; color: var(--nr-text-tertiary); }
.nr-mpp-list { margin: 0; padding: 0; list-style: none; }
.nr-mpp-item { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-top: 1px solid var(--nr-border-subtle, rgba(255, 255, 255, 0.06)); font-size: 12px; }
.nr-mpp-name { color: var(--nr-text-primary); font-weight: 600; }
</style>
