<template>
  <div class="collab-page">
    <div class="page-header">
      <h2>{{ t('collab.title') }}</h2>
      <GlassButton variant="primary" size="sm" @click="showInitiate = true">{{ t('collab.initiate') }}</GlassButton>
    </div>

    <!-- Stats -->
    <div class="stats-row">
      <GlassCard v-for="s in stats" :key="s.label" :title="s.label" variant="subtle" padding="14px 18px">
        <span class="stat-value">{{ s.value }}</span>
      </GlassCard>
    </div>

    <!-- Quick start -->
    <GlassPanel variant="subtle" padding="20px 24px">
      <h3 class="section-title">{{ t('dashboard.quickActions') }}</h3>
      <div class="quick-actions">
        <GlassButton variant="secondary" size="sm" @click="$router.push('/collaboration/templates')">{{ t('collab.templates') }}</GlassButton>
        <GlassButton variant="secondary" size="sm" @click="$router.push('/collaboration/history')">{{ t('collab.history') }}</GlassButton>
        <GlassButton variant="secondary" size="sm" @click="$router.push('/collaboration/projects')">{{ t('collab.projects') }}</GlassButton>
        <GlassButton variant="secondary" size="sm" @click="$router.push('/collaboration/teams')">{{ t('collab.teams') }}</GlassButton>
        <GlassButton variant="secondary" size="sm" @click="$router.push('/collaboration/tasks')">{{ t('collab.tasks') }}</GlassButton>
      </div>
    </GlassPanel>

    <!-- Active sessions -->
    <GlassPanel variant="default" padding="20px 24px">
      <h3 class="section-title">{{ t('common.active') }} {{ t('collab.title') }}</h3>
      <a-spin :spinning="loading">
        <a-empty v-if="!loading && sessions.length === 0" :description="t('common.noData')" />
        <a-table
          v-else
          :columns="columns"
          :data-source="sessions"
          :pagination="{ pageSize: 10 }"
          size="small"
          row-key="id"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <a-badge :status="record.status === 'active' ? 'processing' : record.status === 'completed' ? 'success' : 'default'" :text="record.status" />
            </template>
            <template v-if="column.key === 'actions'">
              <GlassButton variant="ghost" size="sm" @click="handleViewSession(record)">{{ t('common.open') }}</GlassButton>
            </template>
          </template>
        </a-table>
      </a-spin>
    </GlassPanel>

    <!-- Session detail modal -->
    <a-modal v-model:open="showDetail" :title="selectedSession?.name" :footer="null">
      <div v-if="selectedSession" class="session-detail">
        <p><strong>{{ t('common.description') }}:</strong> {{ selectedSession.description }}</p>
        <p><strong>{{ t('common.status') }}:</strong> {{ selectedSession.status }}</p>
        <p><strong>{{ t('collab.members') }}:</strong> {{ selectedSession.participants?.join(', ') }}</p>
        <p><strong>{{ t('common.createdAt') }}:</strong> {{ selectedSession.createdAt }}</p>
      </div>
    </a-modal>

    <!-- Initiate collaboration drawer -->
    <a-drawer v-model:open="showInitiate" :title="t('collab.initiate')" placement="right" width="520" :body-style="{ padding: '20px 24px' }">
      <a-steps :current="initStep" size="small" style="margin-bottom: 24px">
        <a-step :title="t('collab.templates')" />
        <a-step :title="t('collab.members')" />
        <a-step :title="t('agent.config')" />
        <a-step :title="t('common.confirm')" />
      </a-steps>

      <!-- Step 1: Select template -->
      <div v-if="initStep === 0">
        <a-spin :spinning="loadingTemplates">
          <a-empty v-if="!loadingTemplates && templates.length === 0" :description="t('common.noData')" />
          <div v-else class="tpl-list">
            <div
              v-for="tpl in templates"
              :key="tpl.id"
              class="tpl-option"
              :class="{ selected: initForm.templateId === tpl.id }"
              @click="initForm.templateId = tpl.id"
            >
              <strong>{{ tpl.name }}</strong>
              <span class="tpl-desc">{{ tpl.description }}</span>
              <a-tag color="blue">{{ tpl.type }}</a-tag>
            </div>
          </div>
        </a-spin>
      </div>

      <!-- Step 2: Configure participants -->
      <div v-if="initStep === 1">
        <a-form layout="vertical">
          <a-form-item :label="t('collab.members')">
            <a-select v-model:value="initForm.participants" mode="tags" :placeholder="t('collab.members')" style="width: 100%" />
          </a-form-item>
        </a-form>
      </div>

      <!-- Step 3: Parameters -->
      <div v-if="initStep === 2">
        <a-form layout="vertical">
          <a-form-item :label="t('common.name')">
            <a-input v-model:value="initForm.name" :placeholder="t('common.name')" />
          </a-form-item>
          <a-form-item :label="t('common.description')">
            <a-input v-model:value="initForm.description" type="textarea" :rows="3" :placeholder="t('common.description')" />
          </a-form-item>
        </a-form>
      </div>

      <!-- Step 4: Review -->
      <div v-if="initStep === 3">
        <p><strong>{{ t('common.name') }}:</strong> {{ initForm.name }}</p>
        <p><strong>{{ t('common.description') }}:</strong> {{ initForm.description }}</p>
        <p><strong>{{ t('collab.templates') }}:</strong> {{ selectedTemplateName }}</p>
        <p><strong>{{ t('collab.members') }}:</strong> {{ initForm.participants.join(', ') }}</p>
      </div>

      <template #footer>
        <div style="display: flex; gap: 8px; justify-content: flex-end">
          <GlassButton v-if="initStep > 0" variant="secondary" size="sm" @click="initStep--">{{ t('common.prev') }}</GlassButton>
          <GlassButton v-if="initStep < 3" variant="primary" size="sm" @click="initStep++">{{ t('common.next') }}</GlassButton>
          <GlassButton v-if="initStep === 3" variant="primary" size="sm" :loading="starting" @click="handleStart">{{ t('common.submit') }}</GlassButton>
        </div>
      </template>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()

// ── Initiate drawer state ──
const showInitiate = ref(false)
const initStep = ref(0)
const starting = ref(false)
const loadingTemplates = ref(false)
const templates = ref<{ id: string; name: string; description: string; type: string }[]>([])
const initForm = reactive({ templateId: '', participants: [] as string[], name: '', description: '' })
const selectedTemplateName = computed(() => templates.value.find((t) => t.id === initForm.templateId)?.name ?? '-')

async function fetchTemplates() {
  loadingTemplates.value = true
  try {
    const res: any = await request.get('/collaboration/templates')
    const raw = res?.data ?? res ?? []
    templates.value = Array.isArray(raw) ? raw : (raw?.data ?? [])
  } catch { templates.value = [] }
  finally { loadingTemplates.value = false }
}

async function handleStart() {
  starting.value = true
  try {
    await request.post('/collaboration/start', { templateId: initForm.templateId, participants: initForm.participants, name: initForm.name, description: initForm.description })
    message.success(t('common.success'))
    showInitiate.value = false
    initStep.value = 0
    initForm.templateId = ''
    initForm.participants = []
    initForm.name = ''
    initForm.description = ''
    fetchSessions()
  } catch { message.error(t('common.error')) }
  finally { starting.value = false }
}

interface Session {
  id: string
  name: string
  description: string
  status: string
  participants?: string[]
  createdAt: string
}

const sessions = ref<Session[]>([])
const loading = ref(false)
const showDetail = ref(false)
const selectedSession = ref<Session | null>(null)

const columns = [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('common.status'), dataIndex: 'status', key: 'status' },
  { title: t('common.createdAt'), dataIndex: 'createdAt', key: 'createdAt' },
  { title: t('common.actions'), key: 'actions', width: 120 },
]

const stats = computed(() => [
  { label: t('common.total'), value: sessions.value.length },
  { label: t('common.active'), value: sessions.value.filter((s) => s.status === 'active').length },
  { label: t('collab.history'), value: sessions.value.filter((s) => s.status === 'completed').length },
])

async function fetchSessions() {
  loading.value = true
  try {
    const res = await request.get('/collaboration/templates') as unknown as Session[]
    sessions.value = res ?? []
  } catch {
    sessions.value = []
  } finally {
    loading.value = false
  }
}

function handleViewSession(record: Session) {
  selectedSession.value = record
  showDetail.value = true
}

onMounted(() => { fetchSessions(); fetchTemplates() })
</script>

<style scoped>
.collab-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.stat-value { font-family: var(--nr-font-display); font-size: 24px; font-weight: 700; color: var(--nr-text-primary); }
.section-title { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 600; margin: 0 0 16px; font-size: 16px; }
.quick-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.session-detail { display: flex; flex-direction: column; gap: 10px; }
.session-detail p { color: var(--nr-text-secondary); font-size: 14px; margin: 0; }
.tpl-list { display: flex; flex-direction: column; gap: 8px; }
.tpl-option { padding: 12px 16px; border: 1px solid var(--nr-glass-border); border-radius: 10px; cursor: pointer; transition: all 0.2s; display: flex; flex-direction: column; gap: 4px; }
.tpl-option:hover { border-color: var(--nr-primary-light); background: rgba(99,102,241,0.05); }
.tpl-option.selected { border-color: var(--nr-primary); background: rgba(99,102,241,0.1); }
.tpl-desc { font-size: 13px; color: var(--nr-text-tertiary); }
</style>
