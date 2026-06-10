<template>
  <div class="computer-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('computer.title') }}</h2>
      <GlassButton variant="primary" size="sm" :loading="screenshotLoading" @click="takeScreenshot">{{ t('computer.screenshot') }}</GlassButton>
    </div>

    <div class="two-col">
      <!-- Screenshot viewer -->
      <GlassCard :title="t('computer.screenshot')">
        <div class="screenshot-area">
          <img v-if="screenshotUrl" :src="screenshotUrl" alt="Screenshot" class="screenshot-img" @click="onScreenshotClick" />
          <div v-else class="screenshot-placeholder">
            <span>{{ t('computer.screenshot') }}</span>
          </div>
        </div>
        <template v-if="clickCoords" #footer>
          <span class="coords-text">Click: ({{ clickCoords.x }}, {{ clickCoords.y }})</span>
        </template>
      </GlassCard>

      <!-- Action buttons and controls -->
      <div class="controls-col">
        <!-- Basic actions -->
        <GlassCard :title="t('common.actions')">
          <div class="action-grid">
            <div class="action-row">
              <span class="action-label">{{ t('computer.click') }} (x, y)</span>
              <a-input-number v-model:value="clickX" :min="0" size="small" style="width: 80px" />
              <a-input-number v-model:value="clickY" :min="0" size="small" style="width: 80px" />
              <GlassButton variant="secondary" size="sm" @click="doClick">{{ t('computer.click') }}</GlassButton>
            </div>
            <div class="action-row">
              <span class="action-label">{{ t('computer.type') }}</span>
              <a-input v-model:value="typeText" size="small" style="flex: 1" />
              <GlassButton variant="secondary" size="sm" @click="doType">{{ t('computer.type') }}</GlassButton>
            </div>
            <div class="action-row">
              <span class="action-label">{{ t('computer.scroll') }}</span>
              <a-select v-model:value="scrollDir" size="small" style="width: 100px">
                <a-select-option value="up">{{ t('computer.up') }}</a-select-option>
                <a-select-option value="down">{{ t('computer.down') }}</a-select-option>
                <a-select-option value="left">{{ t('computer.left') }}</a-select-option>
                <a-select-option value="right">{{ t('computer.right') }}</a-select-option>
              </a-select>
              <a-input-number v-model:value="scrollAmount" :min="1" :max="10" size="small" style="width: 60px" />
              <GlassButton variant="secondary" size="sm" @click="doScroll">{{ t('computer.scroll') }}</GlassButton>
            </div>
          </div>
        </GlassCard>

        <!-- Browser controls -->
        <GlassCard :title="t('computer.browser')" style="margin-top: 16px">
          <div class="action-grid">
            <div class="action-row">
              <a-input v-model:value="browserUrl" placeholder="https://..." size="small" style="flex: 1" />
              <GlassButton variant="secondary" size="sm" @click="browserNavigate">{{ t('computer.navigate') }}</GlassButton>
            </div>
            <div class="action-grid-row">
              <GlassButton variant="ghost" size="sm" @click="browserScreenshot">{{ t('computer.screenshot') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" @click="browserClick">{{ t('computer.click') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" @click="browserType">{{ t('computer.type') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" @click="browserExtract">{{ t('computer.extract') }}</GlassButton>
            </div>
            <div class="action-grid-row">
              <GlassButton variant="ghost" size="sm" @click="smartClick">{{ t('computer.smartClick') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" @click="visualParse">{{ t('computer.visualParse') }}</GlassButton>
            </div>
          </div>
        </GlassCard>

        <!-- Shell command -->
        <GlassCard :title="t('computer.shell')" style="margin-top: 16px">
          <div class="shell-input">
            <a-input v-model:value="shellCommand" :placeholder="t('computer.shell')" @press-enter="executeShell">
              <template #prefix><span class="shell-prompt">$</span></template>
            </a-input>
            <GlassButton variant="primary" size="sm" :loading="shellLoading" @click="executeShell">{{ t('computer.run') }}</GlassButton>
          </div>
          <div v-if="shellOutput" class="shell-output">
            <pre>{{ shellOutput }}</pre>
          </div>
        </GlassCard>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()
const route = useRoute()
const agentId = route.params.agentId as string

const screenshotLoading = ref(false)
const shellLoading = ref(false)
const screenshotUrl = ref('')
const clickCoords = ref<{ x: number; y: number } | null>(null)
const clickX = ref(0)
const clickY = ref(0)
const typeText = ref('')
const scrollDir = ref('down')
const scrollAmount = ref(3)
const browserUrl = ref('')
const shellCommand = ref('')
const shellOutput = ref('')

const takeScreenshot = async () => {
  screenshotLoading.value = true
  try {
    const res: any = await request.post('/computer/screenshot', { agent_id: agentId })
    const data = res?.data ?? res ?? {}
    screenshotUrl.value = data.url || data.image || (data.base64 ? `data:image/png;base64,${data.base64}` : '')
  } catch {
    message.error(t('common.error'))
  } finally {
    screenshotLoading.value = false
  }
}

const onScreenshotClick = (e: MouseEvent) => {
  const img = e.target as HTMLImageElement
  const rect = img.getBoundingClientRect()
  const scaleX = img.naturalWidth / rect.width
  const scaleY = img.naturalHeight / rect.height
  clickX.value = Math.round((e.clientX - rect.left) * scaleX)
  clickY.value = Math.round((e.clientY - rect.top) * scaleY)
  clickCoords.value = { x: clickX.value, y: clickY.value }
}

const doClick = async () => {
  try {
    await request.post('/computer/click', { agent_id: agentId, x: clickX.value, y: clickY.value })
    message.success(t('common.success'))
    await takeScreenshot()
  } catch { message.error(t('common.error')) }
}

const doType = async () => {
  if (!typeText.value) return
  try {
    await request.post('/computer/type', { agent_id: agentId, text: typeText.value })
    message.success(t('common.success'))
    typeText.value = ''
  } catch { message.error(t('common.error')) }
}

const doScroll = async () => {
  try {
    await request.post('/computer/scroll', { agent_id: agentId, direction: scrollDir.value, amount: scrollAmount.value })
    message.success(t('common.success'))
    await takeScreenshot()
  } catch { message.error(t('common.error')) }
}

const browserNavigate = async () => {
  if (!browserUrl.value) return
  try {
    await request.post('/computer/browser/navigate', { agent_id: agentId, url: browserUrl.value })
    message.success(t('common.success'))
    await takeScreenshot()
  } catch { message.error(t('common.error')) }
}

const browserScreenshot = async () => { await takeScreenshot() }

const browserClick = async () => { await doClick() }

const browserType = async () => { await doType() }

const browserExtract = async () => {
  try {
    const res: any = await request.post('/computer/browser/extract', { agent_id: agentId })
    message.info(JSON.stringify(res?.data ?? res))
  } catch { message.error(t('common.error')) }
}

const smartClick = async () => {
  try {
    await request.post('/computer/smart-click', { agent_id: agentId, x: clickX.value, y: clickY.value })
    message.success(t('common.success'))
    await takeScreenshot()
  } catch { message.error(t('common.error')) }
}

const visualParse = async () => {
  try {
    const res: any = await request.post('/computer/visual-parse', { agent_id: agentId })
    message.info(JSON.stringify(res?.data ?? res))
  } catch { message.error(t('common.error')) }
}

const executeShell = async () => {
  if (!shellCommand.value) return
  shellLoading.value = true
  try {
    const res: any = await request.post('/computer/shell', { agent_id: agentId, command: shellCommand.value })
    const data = res?.data ?? res ?? {}
    shellOutput.value = data.output ?? data.result ?? JSON.stringify(data, null, 2)
    shellCommand.value = ''
  } catch (e: any) {
    shellOutput.value = e.message || t('common.error')
  } finally {
    shellLoading.value = false
  }
}

onMounted(takeScreenshot)
</script>

<style scoped>
.computer-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }
.controls-col { display: flex; flex-direction: column; }
.screenshot-area { min-height: 300px; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,0.2); border-radius: 8px; overflow: hidden; cursor: crosshair; }
.screenshot-img { max-width: 100%; max-height: 500px; object-fit: contain; }
.screenshot-placeholder { color: var(--nr-text-muted); font-size: 14px; }
.coords-text { font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-tertiary); }
.action-grid { display: flex; flex-direction: column; gap: 10px; }
.action-row { display: flex; align-items: center; gap: 8px; }
.action-grid-row { display: flex; gap: 6px; flex-wrap: wrap; }
.action-label { font-size: 12px; color: var(--nr-text-secondary); width: 80px; flex-shrink: 0; }
.shell-input { display: flex; gap: 8px; }
.shell-prompt { font-family: var(--nr-font-mono); color: var(--nr-primary-light, #6366f1); }
.shell-output { margin-top: 12px; background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px; max-height: 200px; overflow: auto; }
.shell-output pre { margin: 0; font-size: 12px; color: var(--nr-text-secondary); font-family: var(--nr-font-mono); white-space: pre-wrap; }
</style>
