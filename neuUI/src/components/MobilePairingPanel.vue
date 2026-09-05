<template>
  <div >
    <div >
      <MobileOutlined style="font-size:20px;color:#10b981" />
      <span >移动设备配对</span>
      <a-button type="primary" size="small" @click="handleGenerate" :loading="generating">
        <QrcodeOutlined /> 生成配对码
      </a-button>
    </div>
 
    <!-- 二维码 + 配对码展示 -->
    <div v-if="pairingSession" >
      <div >
        <img
          v-if="qrImageUrl"
          :src="qrImageUrl"
          alt="配对二维码"
        />
        <div v-else >
          <QrcodeOutlined style="font-size:64px;color:rgba(255,255,255,0.2)" />
        </div>
      </div>
      <div >
        <div >
          <span >配对码</span>
          <span >{{ pairingSession.code }}</span>
        </div>
        <div >
          <a-tag :color="statusColor">{{ statusText }}</a-tag>
          <span  v-if="countdown > 0">{{ countdown }}s</span>
        </div>
        <p >请在手机 App 中扫描二维码或输入配对码完成配对</p>
      </div>
    </div>
 
    <!-- 已配对设备列表 -->
    <div v-if="pairedDevices.length" >
      <h4>已配对设备</h4>
      <div v-for="device in pairedDevices" :key="device.pairing_id" >
        <div >
          <MobileOutlined />
        </div>
        <div >
          <span >{{ device.device_info?.device_name || '未知设备' }}</span>
          <span >{{ device.device_info?.os || '' }}</span>
        </div>
        <div >
          <a-tag size="small">{{ device.agent_id }}</a-tag>
        </div>
        <a-button size="small" danger @click="handleRevoke(device.pairing_id)">
          <DeleteOutlined />
        </a-button>
      </div>
    </div>
    <div v-else-if="!pairingSession" >
      <MobileOutlined style="font-size:32px;color:rgba(255,255,255,0.15)" />
      <p>暂无已配对设备</p>
    </div>
  </div>
</template>
 
<script setup lang="ts">
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
 
const props = defineProps<{ agentId: string }>()
 
const generating = ref(false)
const pairingSession = ref<GeneratePairingResponse | null>(null)
const pairedDevices = ref<PairedDevice[]>([])
const countdown = ref(0)
 
let pollTimer: ReturnType<typeof setInterval> | null = null
let countdownTimer: ReturnType<typeof setInterval> | null = null
 
const qrImageUrl = computed(() => {
  if (!pairingSession.value) return ''
  return mobilePairingAPI.getQRCodeImage(pairingSession.value.code)
})
 
const statusColor = computed(() => {
  if (!pairingSession.value) return 'default'
  const s = pairingSession.value.status
  if (s === 'pending') return 'processing'
  if (s === 'confirmed') return 'success'
  if (s === 'expired') return 'error'
  return 'default'
})
 
const statusText = computed(() => {
  if (!pairingSession.value) return ''
  const s = pairingSession.value.status
  if (s === 'pending') return '等待扫码'
  if (s === 'confirmed') return '已配对'
  if (s === 'expired') return '已过期'
  return s
})
 
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
 
function startPolling() {
  stopPolling()
  if (!pairingSession.value) return
  pollTimer = setInterval(async () => {
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
 
function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}
 
function startCountdown() {
  stopCountdown()
  if (!pairingSession.value) return
  const expiresAt = pairingSession.value.expires_at
  countdownTimer = setInterval(() => {
    const remaining = Math.max(0, Math.floor(expiresAt - Date.now() / 1000))
    countdown.value = remaining
    if (remaining <= 0) {
      stopCountdown()
      if (pairingSession.value) {
        pairingSession.value.status = 'expired'
      }
    }
  }, 1000)
}
 
function stopCountdown() {
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }
}
 
async function loadDevices() {
  try {
    const res = await mobilePairingAPI.listDevices()
    pairedDevices.value = res.data as unknown as PairedDevice[]
  } catch {
    // 静默失败
  }
}
 
async function handleRevoke(pairingId: string) {
  try {
    await mobilePairingAPI.revoke(pairingId)
    message.success('已解除配对')
    loadDevices()
  } catch (err: unknown) {
    message.error('解除配对失败: ' + (err instanceof Error ? err.message : String(err)))
  }
}
 
// 初始化加载
loadDevices()
 
onUnmounted(() => {
  stopPolling()
  stopCountdown()
})
</script>
 
<style scoped>
.mobile-pairing {
  padding: 16px;
}
 
.pairing-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}
 
.pairing-title {
  flex: 1;
  font-size: 14px;
  font-weight: 500;
}
 
.pairing-qr-section {
  display: flex;
  gap: 20px;
  padding: 16px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  margin-bottom: 16px;
}
 
.qr-container {
  flex-shrink: 0;
}
 
.qr-image {
  width: 160px;
  height: 160px;
  border-radius: 8px;
  border: 2px solid rgba(255, 255, 255, 0.1);
}
 
.qr-placeholder {
  width: 160px;
  height: 160px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
}
 
.pairing-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
 
.pairing-code {
  display: flex;
  align-items: center;
  gap: 8px;
}
 
.code-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.45);
}
 
.code-value {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 4px;
  font-family: monospace;
  color: #10b981;
}
 
.pairing-status {
  display: flex;
  align-items: center;
  gap: 8px;
}
 
.countdown {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.45);
}
 
.pairing-hint {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.35);
  margin-top: auto;
}
 
.paired-devices h4 {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.55);
  margin-bottom: 8px;
}
 
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
 
.device-icon {
  font-size: 18px;
  color: #10b981;
}
 
.device-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
}
 
.device-name {
  font-size: 13px;
  font-weight: 500;
}
 
.device-os {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.35);
}
 
.no-devices {
  text-align: center;
  padding: 24px;
  color: rgba(255, 255, 255, 0.3);
}
 
.no-devices p {
  margin-top: 8px;
  font-size: 13px;
}
</style>
 