<template>
  <div class="sandbox-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.sandbox') }}</h2>
      <GlassButton variant="primary" size="sm" :loading="starting" @click="startSandbox">{{ t('common.create') }}</GlassButton>
    </div>

    <!-- Active sandboxes -->
    <a-spin :spinning="loading">
      <div class="sandbox-grid">
        <GlassCard v-for="sb in sandboxes" :key="sb.id" variant="default">
          <template #header>
            <div class="sb-header">
              <span class="sb-name">{{ sb.name || sb.id }}</span>
              <a-tag :color="sb.status === 'running' ? 'green' : sb.status === 'paused' ? 'orange' : 'default'">
                {{ sb.status }}
              </a-tag>
            </div>
          </template>
          <div class="sb-body">
            <p class="sb-meta">Created: {{ formatTime(sb.created_at) }}</p>
            <p class="sb-meta">Steps: {{ sb.steps_count ?? 0 }}</p>
            <p v-if="sb.image" class="sb-meta">Image: {{ sb.image }}</p>
          </div>
          <template #footer>
            <div class="sb-actions">
              <GlassButton variant="ghost" size="sm" @click="selectSandbox(sb)">{{ t('common.open') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" @click="commitSandbox(sb.id)">Commit</GlassButton>
              <GlassButton variant="danger" size="sm" @click="destroySandbox(sb.id)">Destroy</GlassButton>
            </div>
          </template>
        </GlassCard>
      </div>
      <a-empty v-if="!sandboxes.length && !loading" :description="t('common.noData')" />
    </a-spin>

    <!-- Execute step section -->
    <GlassCard v-if="selectedSandbox" title="Execute Step" style="margin-top: 20px">
      <div class="exec-form">
        <a-textarea v-model:value="stepCommand" :rows="4" placeholder="Enter command or code to execute..." />
        <div class="exec-actions">
          <a-select v-model:value="stepLanguage" style="width: 120px">
            <a-select-option value="python">Python</a-select-option>
            <a-select-option value="shell">Shell</a-select-option>
            <a-select-option value="javascript">JavaScript</a-select-option>
          </a-select>
          <GlassButton variant="primary" size="sm" :loading="executing" @click="executeStep">{{ t('tool.execute') }}</GlassButton>
        </div>
      </div>
      <div v-if="execOutput" class="exec-output">
        <h4>Output</h4>
        <pre>{{ execOutput }}</pre>
      </div>
    </GlassCard>

    <!-- Start sandbox modal -->
    <a-modal v-model:open="showStart" title="Start Sandbox" @ok="confirmStart" :confirm-loading="starting">
      <a-form layout="vertical" :model="newSandbox">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="newSandbox.name" />
        </a-form-item>
        <a-form-item label="Image">
          <a-input v-model:value="newSandbox.image" placeholder="python:3.11-slim" />
        </a-form-item>
        <a-form-item label="Timeout (seconds)">
          <a-input-number v-model:value="newSandbox.timeout" :min="60" :max="3600" style="width: 100%" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message, Modal } from 'ant-design-vue'

const { t } = useI18n()

const loading = ref(false)
const starting = ref(false)
const executing = ref(false)
const sandboxes = ref<any[]>([])
const selectedSandbox = ref<any>(null)
const showStart = ref(false)
const stepCommand = ref('')
const stepLanguage = ref('python')
const execOutput = ref('')

const newSandbox = ref({ name: '', image: 'python:3.11-slim', timeout: 300 })

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const fetchSandboxes = async () => {
  loading.value = true
  try {
    const res: any = await request.get('/sandbox')
    sandboxes.value = res?.data ?? res ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const startSandbox = () => {
  newSandbox.value = { name: '', image: 'python:3.11-slim', timeout: 300 }
  showStart.value = true
}

const confirmStart = async () => {
  starting.value = true
  try {
    await request.post('/sandbox/start', newSandbox.value)
    message.success(t('common.success'))
    showStart.value = false
    await fetchSandboxes()
  } catch {
    message.error(t('common.error'))
  } finally {
    starting.value = false
  }
}

const selectSandbox = async (sb: any) => {
  selectedSandbox.value = sb
  execOutput.value = ''
  try {
    const res: any = await request.get(`/sandbox/${sb.id}`)
    selectedSandbox.value = res?.data ?? res ?? sb
  } catch {
    // keep existing data
  }
}

const executeStep = async () => {
  if (!selectedSandbox.value || !stepCommand.value) return
  executing.value = true
  try {
    const res: any = await request.post(`/sandbox/${selectedSandbox.value.id}/execute`, {
      command: stepCommand.value,
      language: stepLanguage.value,
    })
    const data = res?.data ?? res ?? {}
    execOutput.value = data.output ?? data.result ?? JSON.stringify(data, null, 2)
  } catch (e: any) {
    execOutput.value = e.message || t('common.error')
  } finally {
    executing.value = false
  }
}

const commitSandbox = async (id: string) => {
  try {
    await request.post(`/sandbox/${id}/commit`)
    message.success(t('common.success'))
    await fetchSandboxes()
  } catch {
    message.error(t('common.error'))
  }
}

const destroySandbox = (id: string) => {
  Modal.confirm({
    title: t('common.confirm'),
    content: t('agent.deleteConfirm'),
    onOk: async () => {
      try {
        await request.delete(`/sandbox/${id}`)
        message.success(t('common.success'))
        if (selectedSandbox.value?.id === id) selectedSandbox.value = null
        await fetchSandboxes()
      } catch {
        message.error(t('common.error'))
      }
    },
  })
}

onMounted(fetchSandboxes)
</script>

<style scoped>
.sandbox-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.sandbox-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.sb-header { display: flex; justify-content: space-between; align-items: center; }
.sb-name { font-weight: 600; color: var(--nr-text-primary); }
.sb-body { display: flex; flex-direction: column; gap: 4px; }
.sb-meta { font-size: 12px; color: var(--nr-text-tertiary); font-family: var(--nr-font-mono); }
.sb-actions { display: flex; gap: 6px; }
.exec-form { display: flex; flex-direction: column; gap: 12px; }
.exec-actions { display: flex; gap: 8px; align-items: center; }
.exec-output { margin-top: 16px; }
.exec-output h4 { color: var(--nr-text-primary); font-size: 14px; margin-bottom: 8px; }
.exec-output pre { background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px; font-size: 12px; color: var(--nr-text-secondary); font-family: var(--nr-font-mono); max-height: 300px; overflow: auto; white-space: pre-wrap; margin: 0; }
</style>
