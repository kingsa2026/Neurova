<template>
  <div class="project-list-page">
    <div class="page-header">
      <h2>{{ t('project.title') }}</h2>
      <GlassButton variant="primary" size="sm" @click="showCreate = true">{{ t('project.create') }}</GlassButton>
    </div>

    <a-spin :spinning="loading">
      <div v-if="!loading && projects.length === 0" class="empty-state">
        <a-empty :description="t('common.noData')" />
      </div>
      <div v-else class="project-grid">
        <GlassCard
          v-for="p in projects"
          :key="p.project_id"
          :title="p.name"
          :subtitle="p.description"
          variant="default"
          padding="18px 22px"
          class="project-card"
          @click="router.push(`/projects/${p.project_id}`)"
        >
          <div class="proj-meta">
            <a-tag :color="p.status === 'active' ? 'green' : 'default'">{{ p.status || 'active' }}</a-tag>
            <span class="meta-text">{{ t('project.teams') }}: {{ p.teams_count ?? 0 }}</span>
            <span class="meta-text">{{ t('project.tasks') }}: {{ p.tasks_count ?? 0 }}</span>
            <span v-if="p.updated_at" class="meta-text">{{ formatTime(p.updated_at) }}</span>
          </div>
        </GlassCard>
      </div>
    </a-spin>

    <!-- 新建项目 -->
    <a-modal v-model:open="showCreate" :title="t('project.create')" :confirm-loading="creating" @ok="handleCreate">
      <a-form layout="vertical">
        <a-form-item :label="t('common.name')" required>
          <a-input v-model:value="createForm.name" :placeholder="t('common.name')" @pressEnter="handleCreate" />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-textarea v-model:value="createForm.description" :rows="3" :placeholder="t('common.description')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { listProjects, createProject, type ProjectInfo } from '@/api/modules/projects'

const { t } = useI18n()
const router = useRouter()

const projects = ref<ProjectInfo[]>([])
const loading = ref(false)
const creating = ref(false)
const showCreate = ref(false)
const createForm = reactive({ name: '', description: '' })

function unwrap<T>(res: unknown): T | null {
  const r = res as { data?: T } | null
  return (r?.data ?? (res as T)) as T | null
}

async function fetchProjects() {
  loading.value = true
  try {
    const data = unwrap<ProjectInfo[]>(await listProjects())
    projects.value = Array.isArray(data) ? data : []
  } catch {
    projects.value = []
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!createForm.name.trim()) return
  creating.value = true
  try {
    const created = unwrap<ProjectInfo>(
      await createProject({ name: createForm.name.trim(), description: createForm.description }),
    )
    showCreate.value = false
    createForm.name = ''
    createForm.description = ''
    if (created?.project_id) {
      router.push(`/projects/${created.project_id}`)
    } else {
      await fetchProjects()
    }
  } catch { /* handled by interceptor */ } finally {
    creating.value = false
  }
}

function formatTime(ts?: number): string {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleString()
}

onMounted(fetchProjects)
</script>

<style scoped>
.project-list-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.project-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.project-card { cursor: pointer; }
.proj-meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.meta-text { font-size: 12px; color: var(--nr-text-tertiary); }
.empty-state { padding: 48px 0; }
</style>
