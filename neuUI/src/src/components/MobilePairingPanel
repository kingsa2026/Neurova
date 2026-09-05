&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;MobileOutlined style="font-size:20px;color:#10b981" /&gt;
      &lt;span &gt;移动设备配对&lt;/span&gt;
      &lt;a-button type="primary" size="small" @click="handleGenerate" :loading="generating"&gt;
        &lt;QrcodeOutlined /&gt; 生成配对码
      &lt;/a-button&gt;
    &lt;/div&gt;
&nbsp;
    &lt;!-- 二维码 + 配对码展示 --&gt;
    &lt;div v-if="pairingSession" &gt;
      &lt;div &gt;
        &lt;img
          v-if="qrImageUrl"
          :src="qrImageUrl"
          alt="配对二维码"
        /&gt;
        &lt;div v-else &gt;
          &lt;QrcodeOutlined style="font-size:64px;color:rgba(255,255,255,0.2)" /&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;div &gt;
          &lt;span &gt;配对码&lt;/span&gt;
          &lt;span &gt;{{ pairingSession.code }}&lt;/span&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;a-tag :color="statusColor"&gt;{{ statusText }}&lt;/a-tag&gt;
          &lt;span  v-if="countdown &gt; 0"&gt;{{ countdown }}s&lt;/span&gt;
        &lt;/div&gt;
        &lt;p &gt;请在手机 App 中扫描二维码或输入配对码完成配对&lt;/p&gt;
      &lt;/div&gt;
    &lt;/div&gt;
&nbsp;
    &lt;!-- 已配对设备列表 --&gt;
    &lt;div v-if="pairedDevices.length" &gt;
      &lt;h4&gt;已配对设备&lt;/h4&gt;
      &lt;div v-for="device in pairedDevices" :key="device.pairing_id" &gt;
        &lt;div &gt;
          &lt;MobileOutlined /&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;span &gt;{{ device.device_info?.device_name || '未知设备' }}&lt;/span&gt;
          &lt;span &gt;{{ device.device_info?.os || '' }}&lt;/span&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;a-tag size="small"&gt;{{ device.agent_id }}&lt;/a-tag&gt;
        &lt;/div&gt;
        &lt;a-button size="small" danger @click="handleRevoke(device.pairing_id)"&gt;
          &lt;DeleteOutlined /&gt;
        &lt;/a-button&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;div v-else-if="!pairingSession" &gt;
      &lt;MobileOutlined style="font-size:32px;color:rgba(255,255,255,0.15)" /&gt;
      &lt;p&gt;暂无已配对设备&lt;/p&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&nbsp;
&lt;script setup lang="ts"&gt;
import { ref, computed, onUnmounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  MobileOutlined,
  QrcodeOutlined,
  DeleteOutlined,
} from '@ant-design/icons-vue'
import {
  mobilePairingAPI,
  type GeneratePairingResponse,
  type PairedDevice,
} from '@/api/modules/mobile-pairing'
&nbsp;
const props = defineProps&lt;{ agentId: string }&gt;()
&nbsp;
const generating = ref(false)
const pairingSession = ref&lt;GeneratePairingResponse | null&gt;(null)
const pairedDevices = ref&lt;PairedDevice[]&gt;([])
const countdown = ref(0)
&nbsp;
let pollTimer: ReturnType&lt;typeof setInterval&gt; | null = null
let countdownTimer: ReturnType&lt;typeof setInterval&gt; | null = null
&nbsp;
const qrImageUrl = computed(() =&gt; {
  if (!pairingSession.value) return ''
  return mobilePairingAPI.getQRCodeImage(pairingSession.value.code)
})
&nbsp;
const statusColor = computed(() =&gt; {
  if (!pairingSession.value) return 'default'
  const s = pairingSession.value.status
  if (s === 'pending') return 'processing'
  if (s === 'confirmed') return 'success'
  if (s === 'expired') return 'error'
  return 'default'
})
&nbsp;
const statusText = computed(() =&gt; {
  if (!pairingSession.value) return ''
  const s = pairingSession.value.status
  if (s === 'pending') return '等待扫码'
  if (s === 'confirmed') return '已配对'
  if (s === 'expired') return '已过期'
  return s
})
&nbsp;
async function handleGenerate() {
  generating.value = true
  try {
    const res = await mobilePairingAPI.generate(props.agentId)
    pairingSession.value = res.data as unknown as GeneratePairingResponse
    startPolling()
    startCountdown()
  } catch (err: unknown) {
    message.error('生成配对码失败: ' + (err instanceof Error ? err.message : String(err)))
  } finally {
    generating.value = false
  }
}
&nbsp;
function startPolling() {
  stopPolling()
  if (!pairingSession.value) return
  pollTimer = setInterval(async () =&gt; {
    if (!pairingSession.value) return
    try {
      const res = await mobilePairingAPI.getStatus(pairingSession.value.code)
      const data = res.data as unknown as { status: string }
      if (pairingSession.value) {
        pairingSession.value.status = data.status
      }
      if (data.status === 'confirmed' || data.status === 'expired' || data.status === 'revoked') {
        stopPolling()
        if (data.status === 'confirmed') {
          message.success('设备配对成功！')
          loadDevices()
        }
      }
    } catch {
      stopPolling()
    }
  }, 2000)
}
&nbsp;
function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}
&nbsp;
function startCountdown() {
  stopCountdown()
  if (!pairingSession.value) return
  const expiresAt = pairingSession.value.expires_at
  countdownTimer = setInterval(() =&gt; {
    const remaining = Math.max(0, Math.floor(expiresAt - Date.now() / 1000))
    countdown.value = remaining
    if (remaining &lt;= 0) {
      stopCountdown()
      if (pairingSession.value) {
        pairingSession.value.status = 'expired'
      }
    }
  }, 1000)
}
&nbsp;
function stopCountdown() {
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }
}
&nbsp;
async function loadDevices() {
  try {
    const res = await mobilePairingAPI.listDevices()
    pairedDevices.value = res.data as unknown as PairedDevice[]
  } catch {
    // 静默失败
  }
}
&nbsp;
async function handleRevoke(pairingId: string) {
  try {
    await mobilePairingAPI.revoke(pairingId)
    message.success('已解除配对')
    loadDevices()
  } catch (err: unknown) {
    message.error('解除配对失败: ' + (err instanceof Error ? err.message : String(err)))
  }
}
&nbsp;
// 初始化加载
loadDevices()
&nbsp;
onUnmounted(() =&gt; {
  stopPolling()
  stopCountdown()
})
&lt;/script&gt;
&nbsp;
&lt;style scoped&gt;
.mobile-pairing {
  padding: 16px;
}
&nbsp;
.pairing-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}
&nbsp;
.pairing-title {
  flex: 1;
  font-size: 14px;
  font-weight: 500;
}
&nbsp;
.pairing-qr-section {
  display: flex;
  gap: 20px;
  padding: 16px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  margin-bottom: 16px;
}
&nbsp;
.qr-container {
  flex-shrink: 0;
}
&nbsp;
.qr-image {
  width: 160px;
  height: 160px;
  border-radius: 8px;
  border: 2px solid rgba(255, 255, 255, 0.1);
}
&nbsp;
.qr-placeholder {
  width: 160px;
  height: 160px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
}
&nbsp;
.pairing-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
&nbsp;
.pairing-code {
  display: flex;
  align-items: center;
  gap: 8px;
}
&nbsp;
.code-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.45);
}
&nbsp;
.code-value {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 4px;
  font-family: monospace;
  color: #10b981;
}
&nbsp;
.pairing-status {
  display: flex;
  align-items: center;
  gap: 8px;
}
&nbsp;
.countdown {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.45);
}
&nbsp;
.pairing-hint {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.35);
  margin-top: auto;
}
&nbsp;
.paired-devices h4 {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.55);
  margin-bottom: 8px;
}
&nbsp;
.device-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  margin-bottom: 6px;
}
&nbsp;
.device-icon {
  font-size: 18px;
  color: #10b981;
}
&nbsp;
.device-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
}
&nbsp;
.device-name {
  font-size: 13px;
  font-weight: 500;
}
&nbsp;
.device-os {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.35);
}
&nbsp;
.no-devices {
  text-align: center;
  padding: 24px;
  color: rgba(255, 255, 255, 0.3);
}
&nbsp;
.no-devices p {
  margin-top: 8px;
  font-size: 13px;
}
&lt;/style&gt;
&nbsp;