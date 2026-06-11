<template>
  <div class="project-page">
    <div class="page-header">
      <h2>{{ t('collab.projects') }}</h2>
      <GlassButton variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
    </div>

    <!-- Stats -->
    <div class="stats-row">
      <GlassCard v-for="s in stats" :key="s.label" :title="s.label" variant="subtle" padding="14px 18px">
        <span class="stat-value">{{ s.value }}</span>
      </GlassCard>
    </div>

    <!-- Project grid -->
    <a-spin :spinning="loading">
      <a-empty v-if="!loading && projects.length === 0" :description="t('common.noData')" />
      <div v-else class="project-grid">
        <GlassCard
          v-for="proj in projects"
          :key="proj.id"
          :title="proj.name"
          :subtitle="proj.description"
          variant="default"
          padding="18px 22px"
        >
          <div class="proj-meta">
            <a-tag :color="proj.status === 'active' ? 'green' : proj.status === 'archived' ? 'default' : 'blue'">{{ proj.status }}</a-tag>
            <span class="meta-text">{{ t('collab.members') }}: {{ proj.memberCount ?? 0 }}</span>
            <span class="meta-text">{{ t('dashboard.systemStatus') }}: {{ proj.progress ?? 0 }}%</span>
          </div>
          <div class="proj-progress">
            <div class="progress-bar" :style="{ width: (proj.progress ?? 0) + '%' }" />
          </div>
          <div class="proj-actions">
            <GlassButton variant="ghost" size="sm" @click="handleViewDetail(proj)">{{ t('common.open') }}</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="openEdit(proj)">{{ t('common.edit') }}</GlassButton>
            <a-popconfirm :title="t('common.confirm') + '?'" @confirm="handleDelete(proj.id)">
              <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
            </a-popconfirm>
          </div>
        </GlassCard>
      </div>
    </a-spin>

    <!-- Detail modal -->
    <a-modal v-model:open="showDetail" :title="detailProject?.name" :footer="null" width="600px">
      <div v-if="detailProject" class="detail-body">
        <p>{{ detailProject.description }}</p>
        <div class="detail-stats">
          <span>{{ t('common.status') }}: <a-tag>{{ detailProject.status }}</a-tag></span>
          <span>{{ t('collab.members') }}: {{ detailProject.memberCount ?? 0 }}</span>
          <span>{{ t('dashboard.systemStatus') }}: {{ detailProject.progress ?? 0 }}%</span>
        </div>
        <h4>{{ t('dashboard.recentActivity') }}</h4>
        <a-timeline>
          <a-timeline-item v-for="(act, i) in detailProject.activities ?? []" :key="i">{{ act }}</a-timeline-item>
        </a-timeline>
      </div>
    </a-modal>

    <!-- Create/Edit modal -->
    <a-modal v-model:open="showModal" :title="editingId ? t('common.edit') : t('common.create')" @ok="handleSave" :confirm-loading="saving">
      <a-form layout="vertical">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="form.name" :placeholder="t('common.name')" />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-input v-model:value="form.description" type="textarea" :rows="3" :placeholder="t('common.description')" />
        </a-form-item>
        <a-form-item :label="t('common.status')">
          <a-select v-model:value="form.status">
            <a-select-option value="active">{{ t('common.active') }}</a-select-option>
            <a-select-option value="paused">{{ t('collab.paused') }}</a-select-option>
            <a-select-option value="archived">{{ t('collab.archived') }}</a-select-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()

interface Project {
  id: string
  name: string
  description: string
  status: string
  memberCount?: number
  progress?: number
  activities?: string[]
}

const projects = ref<Project[]>([])
const loading = ref(false)
const showModal = ref(false)
const showDetail = ref(false)
const saving = ref(false)
const editingId = ref<string | null>(null)
const detailProject = ref<Project | null>(null)

const form = reactive({ name: '', description: '', status: 'active' })

const stats = computed(() => [
  { label: t('common.total'), value: projects.value.length },
  { label: t('common.active'), value: projects.value.filter((p) => p.status === 'active').length },
  { label: t('common.archived'), value: projects.value.filter((p) => p.status === 'archived').length },
])

function resetForm() {
  form.name = ''
  form.description = ''
  form.status = 'active'
  editingId.value = null
}

function openCreate() { resetForm(); showModal.value = true }
function openEdit(p: Project) {
  editingId.value = p.id
  form.name = p.name
  form.description = p.description
  form.status = p.status
  showModal.value = true
}

async function fetchProjects() {
  loading.value = true
  try {
    const res = await request.get('/projects') as unknown as Project[]
    projects.value = res ?? []
  } catch { projects.value = [] } finally { loading.value = false }
}

async function handleSave() {
  if (!form.name) return
  saving.value = true
  try {
    if (editingId.value) {
      await request.put(`/projects/${editingId.value}`, { ...form })
    } else {
      await request.post('/projects', { ...form })
    }
    showModal.value = false
    resetForm()
    await fetchProjects()
  } catch { /* handled */ } finally { saving.value = false }
}

async function handleDelete(id: string) {
  try {
    await request.delete(`/projects/${id}`)
    await fetchProjects()
  } catch { /* handled */ }
}

function handleViewDetail(p: Project) {
  detailProject.value = p
  showDetail.value = true
}

onMounted(fetchProjects)
</script>

<style scoped>
.project-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.stat-value { font-family: var(--nr-font-display); font-size: 24px; font-weight: 700; color: var(--nr-text-primary); }
.project-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.proj-meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.meta-text { font-size: 12px; color: var(--nr-text-tertiary); }
.proj-progress { height: 4px; background: rgba(255,255,255,0.06); border-radius: 2px; margin-bottom: 12px; overflow: hidden; }
.proj-progress .progress-bar { height: 100%; background: linear-gradient(90deg, #6366f1, #a78bfa); border-radius: 2px; transition: width 0.4s; }
.proj-actions { display: flex; gap: 6px; }
.detail-body { display: flex; flex-direction: column; gap: 14px; }
.detail-body p { color: var(--nr-text-secondary); font-size: 14px; margin: 0; }
.detail-body h4 { color: var(--nr-text-primary); margin: 0; }
.detail-stats { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; font-size: 13px; color: var(--nr-text-secondary); }
</style>
