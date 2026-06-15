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
            <p class="sb-meta">{{ t('sandbox.created') }}{{ formatTime(sb.created_at) }}</p>
            <p class="sb-meta">{{ t('sandbox.steps') }}{{ sb.steps_count ?? 0 }}</p>
            <p v-if="sb.image" class="sb-meta">{{ t('sandbox.image') }}{{ sb.image }}</p>
          </div>
          <template #footer>
            <div class="sb-actions">
              <GlassButton variant="ghost" size="sm" @click="selectSandbox(sb)">{{ t('common.open') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" @click="doCommitSandbox(sb.id)">{{ t('sandbox.commit') }}</GlassButton>
              <GlassButton variant="danger" size="sm" @click="destroySandbox(sb.id)">{{ t('sandbox.destroy') }}</GlassButton>
            </div>
          </template>
        </GlassCard>
      </div>
      <a-empty v-if="!sandboxes.length && !loading" :description="t('common.noData')" />
    </a-spin>

    <!-- Execute step section -->
    <GlassCard v-if="selectedSandbox" :title="t('sandbox.executeStep')" style="margin-top: 20px">
      <div class="exec-form">
        <a-textarea v-model:value="stepCommand" :rows="4" :placeholder="t('sandbox.commandPlaceholder')" />
        <div class="exec-actions">
          <a-select v-model:value="stepLanguage" style="width: 120px">
            <a-select-option value="python">{{ t('sandbox.python') }}</a-select-option>
            <a-select-option value="shell">{{ t('sandbox.shell') }}</a-select-option>
            <a-select-option value="javascript">{{ t('sandbox.javascript') }}</a-select-option>
          </a-select>
          <GlassButton variant="primary" size="sm" :loading="executing" @click="executeStep">{{ t('tool.execute') }}</GlassButton>
        </div>
      </div>
      <div v-if="execOutput" class="exec-output">
        <h4>{{ t('sandbox.output') }}</h4>
        <pre>{{ execOutput }}</pre>
      </div>
    </GlassCard>

    <!-- Start sandbox modal -->
    <a-modal v-model:open="showStart" :title="t('sandbox.startSandbox')" @ok="confirmStart" :confirm-loading="starting">
      <a-form layout="vertical" :model="newSandbox">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="newSandbox.name" />
        </a-form-item>
        <a-form-item :label="t('sandbox.imageLabel')">
          <a-input v-model:value="newSandbox.image" placeholder="python:3.11-slim" />
        </a-form-item>
        <a-form-item :label="t('sandbox.timeout')">
          <a-input-number v-model:value="newSandbox.timeout" :min="60" :max="3600" style="width: 100%" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { sandboxApi } from '@/api/modules'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message, Modal } from 'ant-design-vue'

const { t } = useI18n()

const loading = ref(false)
const starting = ref(false)
const executing = ref(false)
const sandboxes = ref<sandboxApi.Sandbox[]>([])
const selectedSandbox = ref<sandboxApi.Sandbox | null>(null)
const showStart = ref(false)
const stepCommand = ref('')
const stepLanguage = ref('python')
const execOutput = ref('')

const newSandbox = ref<sandboxApi.CreateSandboxPayload>({ name: '', image: 'python:3.11-slim', timeout: 300 })

const formatTime = (ts?: string) => ts ? new Date(ts).toLocaleString() : ''

const fetchSandboxes = async () => {
  loading.value = true
  try {
    const res = await sandboxApi.listSandboxes()
    sandboxes.value = res ?? []
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
    await sandboxApi.createSandbox(newSandbox.value)
    message.success(t('common.success'))
    showStart.value = false
    await fetchSandboxes()
  } catch {
    message.error(t('common.error'))
  } finally {
    starting.value = false
  }
}

const selectSandbox = async (sb: sandboxApi.Sandbox) => {
  selectedSandbox.value = sb
  execOutput.value = ''
  try {
    const res = await sandboxApi.getSandbox(sb.id)
    selectedSandbox.value = res ?? sb
  } catch {
    // keep existing data
  }
}

const executeStep = async () => {
  if (!selectedSandbox.value || !stepCommand.value) return
  executing.value = true
  try {
    const res = await sandboxApi.executeInSandbox(selectedSandbox.value.id, {
      command: stepCommand.value,
      language: stepLanguage.value,
    })
    execOutput.value = res.output ?? res.result ?? JSON.stringify(res, null, 2)
  } catch (e: any) {
    execOutput.value = e.message || t('common.error')
  } finally {
    executing.value = false
  }
}

const doCommitSandbox = async (id: string) => {
  try {
    await sandboxApi.commitSandbox(id)
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
        await sandboxApi.deleteSandbox(id)
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
