<template>
  <section class="nr-mpp" data-testid="mobile-pairing-panel">
    <div class="nr-mpp-head">
      <div>
        <h3 class="nr-mpp-title">{{ t('channel.mobile') }}</h3>
        <p class="nr-mpp-desc">{{ t('channel.mobilePairingDesc') }}</p>
      </div>
      <GlassButton size="sm" variant="primary" data-testid="pairing-generate"
        :disabled="generating || blockedByChannel" @click="generate">
        {{ generating ? t('channel.pairingGenerating') : t('channel.pairingGenerate') }}
      </GlassButton>
    </div>

    <!-- 通道状态条：这条链今天缺的不是"能不能扫"，而是**连不连得上**。
         服务端在无固定 IP 的机器上时，二维码里的地址必须是手机够得着的那一条；
         够不着却仍显示"等待扫码"，就是把故障渲染成进行中（AGENTS §2）。 -->
    <div class="nr-mpp-channel" data-testid="tunnel-badge">
      <a-tag :color="channelColor" data-testid="tunnel-state">{{ channelText }}</a-tag>
      <span v-if="tunnel?.route_id" class="nr-mpp-route">{{ tunnel.route_id }}</span>
      <span v-if="tunnel?.last_rtt_ms != null" class="nr-mpp-rtt">{{ tunnel.last_rtt_ms }} ms</span>
    </div>
    <p v-if="tunnelErrorText" class="nr-mpp-error" data-testid="tunnel-error">{{ tunnelErrorText }}</p>
    <p v-if="blockedByChannel" class="nr-mpp-blocked" data-testid="pairing-blocked">
      {{ t('channel.pairingBlockedByChannel', { state: channelText }) }}
    </p>
    <!-- 终态提示位：码收摊之后屏上不能什么都不留。`revoked`（有人解除了设备）与
         `expired`（码放久了）处置不同，合并成一句就是把两种事说成一件事（§2.5）。 -->
    <p v-if="terminalNotice" class="nr-mpp-terminal" data-testid="pairing-terminal">
      {{ terminalNotice }}
    </p>

    <!-- 权限态与空态不合并（与渠道身份面板同纪律）：401/403 要说"无权/未登录"，
         不能退化成"还没有设备"——后者把登录问题伪装成空数据。 -->
    <p v-if="errorText" class="nr-mpp-error" data-testid="pairing-error">{{ errorText }}</p>

    <div v-if="pairing && !blockedByChannel" class="nr-mpp-active" data-testid="pairing-active">
      <div class="nr-mpp-qr">
        <!-- 图不是 `<img :src="qr_code_url">`：那一口带登录门，而资源标签发不出
             Authorization 头。取图走带凭证的 blob（`mobile.ts::getPairingQrcodeBlob`），
             自建的 object URL 由本面板持有并在换码/卸载时释放。 -->
        <img v-if="qrUrl" :src="qrUrl" :alt="t('channel.scanQR')" data-testid="pairing-qr" />
        <p class="nr-mpp-scan">{{ t('channel.scanQR') }}</p>
        <!-- 载荷文本可直接粘贴，给"屏幕没法对着屏幕"的远程协助场景；
             它同样是凭据，所以随图一起收摊。 -->
        <GlassButton v-if="pairing.ref" size="sm" variant="ghost" data-testid="pairing-copy-ref"
          @click="copyRef">
          {{ t('channel.pairingCopyRef') }}
        </GlassButton>
      </div>
      <div class="nr-mpp-meta">
        <p class="nr-mpp-code" data-testid="pairing-code">{{ pairing.code }}</p>
        <p class="nr-mpp-hint">{{ t('channel.pairingShortCodeHint') }}</p>
        <p class="nr-mpp-expires">{{ t('channel.pairingExpiresIn', { seconds: pairing.expires_in }) }}</p>
        <a-tag :color="statusColor" data-testid="pairing-status">{{ statusText }}</a-tag>
        <!-- 已扫未确认是**另一格**：没有它，手机那侧已经扫完而屏上还写着"等待扫码" -->
        <GlassButton v-if="cancellable" size="sm" variant="ghost" data-testid="pairing-cancel"
          :disabled="cancelling" @click="cancel">
          {{ t('channel.pairingCancel') }}
        </GlassButton>
      </div>
    </div>
    <p v-else-if="!errorText && !blockedByChannel" class="nr-mpp-idle" data-testid="pairing-idle">
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
          <!-- 连接方式与在线态是两件事：隧道断了在线态会自己变，连接方式不会 -->
          <span class="nr-mpp-via" data-testid="pairing-device-via">
            {{ d.state === 'online' && tunnel?.state === 'via_relay'
              ? t('channel.pairingViaRelay') : t('channel.pairingViaDirect') }}
          </span>
          <span class="nr-mpp-last" data-testid="pairing-device-last">{{ lastActiveText(d) }}</span>
          <!-- 30 天无活动只是提示，不是告警色：系统不代属主删设备（设计方案 §4.9 已裁） -->
          <span v-if="d.dormant" class="nr-mpp-dormant" data-testid="pairing-device-dormant">
            {{ t('channel.pairingDormantNotice') }}
          </span>
          <GlassButton size="sm" variant="danger" :data-testid="'pairing-revoke-' + d.pairing_id"
            @click="unpair(d)">
            {{ t('channel.pairingRevoke') }}
          </GlassButton>
        </li>
      </ul>
    </div>

    <!-- 已登记风险如实呈现，不藏：中继终结 TLS ⇒ 它看得见经手的明文（设计方案 §4.5） -->
    <p class="nr-mpp-risk" data-testid="pairing-relay-risk">{{ t('channel.pairingRelayRisk') }}</p>
  </section>
</template>

<script setup lang="ts">
/**
 * 移动端配对面板（工单 2026-10-13 批 29 建面板；2026-10-24 S0.5 批接通道状态）。
 *
 * 这条链的后端在 §6-154／§6-161／§6-172 三批里逐一修通（调用形状、请求级属主、
 * 凭据不出本机、真二维码、回连地址可达、读口上登录门），面板补的是"用户可达入口"。
 * S0.5 再补一格：面板原先**无从知道**服务端在不在这台手机够得着的地址上——
 * 无固定 IP 场景里那是常态，而它表现成的仍是"等待扫码"。
 *
 * 面板只做四件事：问通道 → 能发码才发码 → 等手机扫 → 列出/解绑在册设备。
 * 刻意**不**在这里挑"这台设备算哪个账号"：归属只从登录态出（后端 `Depends(_get_current_user_id)`），
 * 与渠道身份面板同一口径——能点面板的人不该同时能决定归属。
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { identityFailureOf } from '@/utils/authIdentity'
import GlassButton from '@/components/GlassButton.vue'
import {
  cancelPairing, generatePairing, getPairedDevices, getPairingQrcodeBlob, getPairingStatus,
  getTunnelStatus, revokePairing,
  type PairedDevice, type PairingCode, type PairingStatus, type TunnelStatus,
} from '@/api/modules/mobile'

const { t } = useI18n()

/** 轮询间隔：配对码本身 300 秒过期，2 秒已经够"扫完立刻有反馈"，不必更快。 */
const POLL_MS = 2000
/** 没有进行中的码时，设备列表/通道降频到 10 秒（在线态要会动，但不必秒级打后端）。 */
const IDLE_POLL_MS = 10000
const DAY_MS = 86400000

const generating = ref(false)
const cancelling = ref(false)
const pairing = ref<PairingCode | null>(null)
const status = ref<PairingStatus | null>(null)
const devices = ref<PairedDevice[]>([])
const tunnel = ref<TunnelStatus | null>(null)
const errorText = ref('')
// 通道读数与设备列表是**两个独立的读者**，不能共写一个 errorText：
// 实测形态是 `loadTunnel` 先失败写下原因，紧跟的 `loadDevices` 成功又把那句抹成空——
// 通道坏了却一行错误都看不到，比不报还难查（本卷形态 402 同族）。
const tunnelErrorText = ref('')
const qrUrl = ref('')
const terminalNotice = ref('')

let ownedUrl = ''
let timer: ReturnType<typeof setInterval> | null = null

const statusText = computed(() => {
  const s = status.value?.status ?? 'pending'
  if (s === 'scanned') return t('channel.pairingStatusScanned')
  if (s === 'confirmed') return t('channel.pairingStatusConfirmed')
  if (s === 'expired') return t('channel.pairingStatusExpired')
  // `revoked` 与 `expired` 分开：今天合并成一句"已过期"，把"有人解除了设备"
  // 说成了"码放久了"——两形的处置动作不同（一个要查是谁，一个什么都不用做）
  if (s === 'revoked') return t('channel.pairingStatusRevoked')
  if (s === 'aborted') return t('channel.pairingStatusAborted')
  return t('channel.pairingStatusPending')
})
const statusColor = computed(() => {
  const s = status.value?.status
  if (s === 'confirmed') return 'green'
  if (s === 'expired' || s === 'revoked' || s === 'aborted') return 'red'
  return 'default'
})

/** 通道态 → 文案。字面量单源在 `contracts/pairingStates.ts`，这里只取词不再造词。 */
const channelText = computed(() => {
  const state = tunnel.value?.state ?? 'disabled'
  if (state === 'via_relay') return t('channel.tunnelViaRelay')
  if (state === 'probing') return t('channel.tunnelProbing')
  if (state === 'relay_down') return t('channel.tunnelRelayDown')
  if (state === 'evicted') return t('channel.tunnelEvicted')
  return t('channel.tunnelDirect')
})
const channelColor = computed(() => {
  const state = tunnel.value?.state ?? 'disabled'
  if (state === 'via_relay') return 'green'
  if (state === 'relay_down' || state === 'evicted') return 'red'
  if (state === 'probing') return 'orange'
  return 'default'
})

/**
 * 「配了中继又没注册上」才阻断发码——把"没配中继"也拦掉会打死已上线的
 * 局域网/自建反代配对。规则与行为不符时以改规则为准（设计方案 §5.2 已回写），
 * 后端那侧的拒绝才是判据，这里 disable 只是不让人白点一次。
 */
const blockedByChannel = computed(() => {
  const current = tunnel.value
  if (!current) return false
  return current.configured && current.state !== 'via_relay'
})

const cancellable = computed(() => {
  const s = status.value?.status
  return !!pairing.value && (s === 'pending' || s === 'scanned')
})

function releaseQr() {
  if (ownedUrl) URL.revokeObjectURL(ownedUrl)
  ownedUrl = ''
  qrUrl.value = ''
}

function stopPairingPolling() {
  if (timer) clearInterval(timer)
  timer = null
}

function startPanelPolling(ms: number) {
  stopPairingPolling()
  timer = setInterval(tick, ms)
}

function pairingErrorText(e: any): string {
  const code = e?.response?.status
  // 身份失败（没登录 / 登了但不够格）由单源判一次，本面板只决定说哪句人话
  if (identityFailureOf(code)) return t('channel.pairingDenied')
  if (code === 503 && e?.response?.data?.detail?.code === 'tunnel_not_ready') {
    // 后端拒了并点名原因——照它说，不要改写成"操作失败"那种模糊话
    return t('channel.pairingBlockedByServer', {
      reason: String(e?.response?.data?.detail?.message || ''),
    })
  }
  return t('channel.pairingFailed', {
    reason: String(e?.response?.data?.detail || e?.message || ''),
  })
}

function lastActiveText(d: PairedDevice): string {
  const at = d.last_active
  if (!at) return t('channel.pairingNeverConnected')
  const days = Math.floor((Date.now() - at * 1000) / DAY_MS)
  if (days <= 0) return t('channel.pairingLastActiveToday')
  return t('channel.pairingLastActiveDays', { days })
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

async function loadTunnel() {
  try {
    const res: any = await getTunnelStatus()
    tunnel.value = (res?.data ?? res) as TunnelStatus
    tunnelErrorText.value = ''
  } catch (e: any) {
    // 通道读不到就是**不知道**：不许把徽标渲染成"直连"让人以为一切正常
    tunnel.value = null
    tunnelErrorText.value = pairingErrorText(e)
  }
}

async function showQr(code: string) {
  releaseQr()
  const blob = await getPairingQrcodeBlob(code)
  ownedUrl = URL.createObjectURL(blob)
  qrUrl.value = ownedUrl
}

async function copyRef() {
  if (!pairing.value) return
  try {
    await navigator.clipboard.writeText(`neurova://pair?ref=${pairing.value.ref}`)
  } catch {
    // 剪贴板被浏览器拒绝不该打断配对：码就在屏幕上，图也还在
  }
}

async function tick() {
  if (!pairing.value) {
    // 没有进行中的码时这一拍只干一件事：让在册设备的在线态/最近连接时间会动
    await loadDevices()
    return
  }
  try {
    const res: any = await getPairingStatus(pairing.value.code)
    status.value = (res?.data ?? res) as PairingStatus
    if (status.value?.status === 'confirmed') {
      // 扫完就该收摊：那张图的内容是一个凭据，留着等于在屏幕上挂一把过期的钥匙
      stopPairingPolling()
      releaseQr()
      pairing.value = null
      await loadDevices()
      startPanelPolling(IDLE_POLL_MS)
    } else if (['expired', 'revoked', 'aborted'].includes(status.value?.status ?? '')) {
      stopPairingPolling()
      releaseQr()
      terminalNotice.value = statusText.value
      pairing.value = null
      startPanelPolling(IDLE_POLL_MS)
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
  if (generating.value || blockedByChannel.value) return
  generating.value = true
  errorText.value = ''
  terminalNotice.value = ''
  stopPairingPolling()
  releaseQr()
  try {
    const res: any = await generatePairing({ device_name: 'web', device_type: 'mobile' })
    const body = (res?.code ? res : res?.data) as PairingCode
    pairing.value = body
    status.value = { code: body.code, status: 'pending' }
    await showQr(body.code)
    startPanelPolling(POLL_MS)
  } catch (e: any) {
    errorText.value = pairingErrorText(e)
  } finally {
    generating.value = false
  }
}

async function cancel() {
  if (!pairing.value || cancelling.value) return
  cancelling.value = true
  try {
    await cancelPairing(pairing.value.code)
    stopPairingPolling()
    releaseQr()
    terminalNotice.value = t('channel.pairingStatusAborted')
    pairing.value = null
    status.value = null
    startPanelPolling(IDLE_POLL_MS)
  } catch (e: any) {
    errorText.value = pairingErrorText(e)
  } finally {
    cancelling.value = false
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

// 先问通道再列设备：面板打开的第一拍就得知道"现在能不能发码"
loadTunnel()
loadDevices()
startPanelPolling(IDLE_POLL_MS)

onBeforeUnmount(() => {
  stopPairingPolling()
  releaseQr()
})
</script>

<style scoped>
.nr-mpp { margin-top: 24px; padding: 16px 18px; border: 1px solid var(--nr-border-subtle, rgba(255, 255, 255, 0.1)); border-radius: var(--nr-radius-lg); }
.nr-mpp-head { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--nr-space-md); }
.nr-mpp-title { margin: 0; font-size: 15px; font-weight: 600; color: var(--nr-text-primary); }
.nr-mpp-desc { margin: 4px 0 0; font-size: 12px; color: var(--nr-text-tertiary); max-width: 60ch; }
.nr-mpp-channel { display: flex; align-items: center; gap: var(--nr-space-sm); margin-top: var(--nr-space-md); }
.nr-mpp-route, .nr-mpp-rtt { font-size: 11px; color: var(--nr-text-muted); font-family: var(--nr-font-mono); }
.nr-mpp-terminal { margin: var(--nr-space-xs) 0 0; font-size: 12px; color: var(--nr-text-secondary); }
.nr-mpp-blocked { margin: var(--nr-space-xs) 0 0; font-size: 12px; color: var(--nr-text-secondary); }
.nr-mpp-error { margin: 12px 0 0; font-size: 12px; color: var(--nr-color-danger, #e11d48); }
.nr-mpp-idle { margin: 12px 0 0; font-size: 12px; color: var(--nr-text-tertiary); }
.nr-mpp-active { display: flex; gap: 18px; align-items: center; margin-top: var(--nr-space-md); }
.nr-mpp-qr { display: flex; flex-direction: column; align-items: center; gap: 6px; }
/* 二维码图本体是**内容**不是 UI 色：黑模块白底不随皮肤变（改了扫不出来）。
   这条在 themes.test.ts 里显式豁免，不靠兜底掩盖。 */
.nr-mpp-qr img { width: 200px; height: 200px; border-radius: var(--nr-radius-md); background: var(--nr-surface-raised, rgba(255, 255, 255, 0.04)); }
.nr-mpp-scan { margin: 0; font-size: 12px; color: var(--nr-text-secondary); }
.nr-mpp-meta { display: flex; flex-direction: column; gap: var(--nr-space-xs); }
.nr-mpp-code { margin: 0; font-size: 22px; letter-spacing: 4px; font-weight: 700; color: var(--nr-text-primary); }
.nr-mpp-hint { margin: 0; font-size: 11px; color: var(--nr-text-tertiary); }
.nr-mpp-expires { margin: 0; font-size: 12px; color: var(--nr-text-tertiary); }
.nr-mpp-sub { margin: 16px 0 6px; font-size: 12px; color: var(--nr-text-secondary); }
.nr-mpp-empty { margin-top: var(--nr-space-xs); font-size: 12px; color: var(--nr-text-tertiary); }
.nr-mpp-list { margin: 0; padding: 0; list-style: none; }
.nr-mpp-item { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-top: 1px solid var(--nr-border-subtle, rgba(255, 255, 255, 0.06)); font-size: 12px; }
.nr-mpp-name { color: var(--nr-text-primary); font-weight: 600; }
.nr-mpp-via, .nr-mpp-last { color: var(--nr-text-tertiary); }
.nr-mpp-dormant { color: var(--nr-text-tertiary); font-style: italic; }
.nr-mpp-risk { margin: var(--nr-space-md) 0 0; font-size: 11px; color: var(--nr-text-muted); }
</style>
