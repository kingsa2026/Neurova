<script setup lang="ts">
/**
 * PairingView - 移动端配对入口（安卓端 M2）
 *
 * 桌面端"复制配对链接"场景：把 neurova://pair?ref=… 粘贴进来（相机扫码批后续接入）。
 * 流程（设计方案 §3.4）：ref → resolve 换回连地址 → confirm 拿一次性票据 + 长期设备身份。
 * 注意：ref 与生成它的桌面属同一台服务器——请先切到对应服务器档案再粘贴。
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { usePairingStore } from '@/stores/pairing'
import { useServersStore } from '@/stores/servers'
import { resolvePairing, confirmPairingByRef } from '@/api/pairing'

const router = useRouter()
const pairing = usePairingStore()
const servers = useServersStore()

const raw = ref('')
const errorMsg = ref('')
const status = ref<'idle' | 'resolving' | 'confirming' | 'success'>('idle')

async function submit() {
  errorMsg.value = ''
  const input = raw.value.trim()
  const refMatch = input.match(/ref=([A-Za-z0-9]{22})/)
  if (!refMatch) {
    errorMsg.value = '未识别到有效的 22 位配对引用（ref）'
    return
  }
  status.value = 'resolving'
  try {
    const resolved = await resolvePairing(refMatch[1])
    status.value = 'confirming'
    const confirmed = await confirmPairingByRef(refMatch[1], 'Android-Device')
    await pairing.applyConfirmed(resolved, confirmed)
    status.value = 'success'
    router.replace('/profile')
  } catch (e) {
    status.value = 'idle'
    const resp = (e as { response?: { status?: number; data?: { detail?: string } } }).response
    const code = resp?.status
    if (code === 404) errorMsg.value = '配对引用无效或已过期'
    else if (code === 410) errorMsg.value = '配对引用已过期'
    else if (code === 429) errorMsg.value = '尝试过于频繁，请稍后再试'
    else errorMsg.value = resp?.data?.detail || (e as Error).message || '配对失败'
  }
}
</script>

<template>
  <div>
    <h2 class="page-title">配对（绑定本设备）</h2>
    <p class="muted">
      在桌面端「配对」面板生成二维码并复制配对链接，把其中的
      <code>neurova://pair?ref=…</code> 粘贴到下面。当前服务器：{{ servers.active.name }}。
    </p>
    <div class="card">
      <label class="field-label">配对链接 / ref</label>
      <textarea v-model="raw" rows="3" placeholder="neurova://pair?ref=…" />
      <p v-if="errorMsg" class="error-text">{{ errorMsg }}</p>
      <button class="btn-primary" :disabled="status === 'resolving' || status === 'confirming'" @click="submit">
        {{ status === 'resolving' ? '换取连接地址中…' : status === 'confirming' ? '确认配对中…' : '确认配对' }}
      </button>
      <p v-if="pairing.paired" class="muted tip">本设备已配对（{{ pairing.pairingId }}）。</p>
    </div>
  </div>
</template>

<style scoped>
.page-title { font-size: 18px; margin: 4px 0 10px; }
.tip { margin-top: 10px; }
</style>
