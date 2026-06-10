<template>
  <div class="collab-tpl-page">
    <div class="page-header">
      <h2>{{ t('collab.templates') }}</h2>
      <GlassButton variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
    </div>

    <a-spin :spinning="loading">
      <a-empty v-if="!loading && templates.length === 0" :description="t('common.noData')" />
      <div v-else class="tpl-grid">
        <GlassCard
          v-for="tpl in templates"
          :key="tpl.id"
          :title="tpl.name"
          :subtitle="tpl.description"
          variant="default"
          padding="18px 22px"
        >
          <div class="tpl-meta">
            <a-tag color="blue">{{ tpl.type }}</a-tag>
            <span class="meta-text">{{ t('collab.members') }}: {{ tpl.participants?.length ?? 0 }}</span>
          </div>
          <div class="tpl-actions">
            <GlassButton variant="ghost" size="sm" @click="openEdit(tpl)">{{ t('common.edit') }}</GlassButton>
            <a-popconfirm :title="t('common.confirm') + '?'" @confirm="handleDelete(tpl.id)">
              <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
            </a-popconfirm>
          </div>
        </GlassCard>
      </div>
    </a-spin>

    <!-- Create/Edit modal -->
    <a-modal v-model:open="showModal" :title="editingId ? t('common.edit') : t('common.create')" @ok="handleSave" :confirm-loading="saving">
      <a-form layout="vertical">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="form.name" :placeholder="t('common.name')" />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-input v-model:value="form.description" type="textarea" :rows="3" :placeholder="t('common.description')" />
        </a-form-item>
        <a-form-item :label="t('common.type')">
          <a-select v-model:value="form.type" :placeholder="t('common.type')">
            <a-select-option value="multi-agent">{{ t('collab.title') }}</a-select-option>
            <a-select-option value="pipeline">Pipeline</a-select-option>
            <a-select-option value="debate">Debate</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('collab.members')">
          <a-select v-model:value="form.participants" mode="tags" :placeholder="t('collab.members')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()

interface Template {
  id: string
  name: string
  description: string
  type: string
  participants?: string[]
}

const templates = ref<Template[]>([])
const loading = ref(false)
const showModal = ref(false)
const saving = ref(false)
const editingId = ref<string | null>(null)

const form = reactive({ name: '', description: '', type: '', participants: [] as string[] })

function resetForm() {
  form.name = ''
  form.description = ''
  form.type = ''
  form.participants = []
  editingId.value = null
}

function openCreate() {
  resetForm()
  showModal.value = true
}

function openEdit(tpl: Template) {
  editingId.value = tpl.id
  form.name = tpl.name
  form.description = tpl.description
  form.type = tpl.type
  form.participants = tpl.participants ? [...tpl.participants] : []
  showModal.value = true
}

async function fetchTemplates() {
  loading.value = true
  try {
    const res = await request.get('/collaboration/templates') as unknown as Template[]
    templates.value = res ?? []
  } catch {
    templates.value = []
  } finally {
    loading.value = false
  }
}

async function handleSave() {
  if (!form.name) return
  saving.value = true
  try {
    if (editingId.value) {
      await request.put(`/collaboration/templates/${editingId.value}`, { ...form })
    } else {
      await request.post('/collaboration/templates', { ...form })
    }
    showModal.value = false
    resetForm()
    await fetchTemplates()
  } catch { /* handled */ } finally {
    saving.value = false
  }
}

async function handleDelete(id: string) {
  try {
    await request.delete(`/collaboration/templates/${id}`)
    await fetchTemplates()
  } catch { /* handled */ }
}

onMounted(fetchTemplates)
</script>

<style scoped>
.collab-tpl-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.tpl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.tpl-meta { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.meta-text { font-size: 12px; color: var(--nr-text-tertiary); }
.tpl-actions { display: flex; gap: 6px; }
</style>
