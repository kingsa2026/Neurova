<template>
  <div class="pool-page">
    <!-- Header -->
    <GlassPanel class="pool-header">
      <div class="header-row">
        <h2 class="page-title">{{ t('skillPool.title') }}</h2>
        <GlassButton variant="primary" size="sm" @click="openCreateModal">
          {{ t('skillPool.createSkill') }}
        </GlassButton>
      </div>
    </GlassPanel>

    <!-- Tabs -->
    <a-tabs v-model:activeKey="activeTab" class="pool-tabs">
      <!-- Public Skills Tab -->
      <a-tab-pane key="public" :tab="t('skillPool.publicSkills')">
        <div class="tab-toolbar">
          <a-input-search
            v-model:value="publicSearch"
            :placeholder="t('skillPool.searchPublic')"
            allow-clear
            style="max-width: 300px"
          />
        </div>
        <a-spin :spinning="publicLoading">
          <div v-if="filteredPublic.length" class="skills-grid">
            <GlassCard
              v-for="skill in filteredPublic"
              :key="skill.id"
              :title="skill.name"
              :subtitle="skill.description"
            >
              <div class="skill-body">
                <div class="skill-meta">
                  <a-tag color="blue">{{ skill.category ?? t('skillPool.general') }}</a-tag>
                  <span class="meta-text">📥 {{ skill.install_count ?? 0 }}</span>
                  <span class="meta-text">👤 {{ skill.author ?? '—' }}</span>
                </div>
                <GlassButton
                  variant="primary"
                  size="sm"
                  :loading="skill._installing"
                  @click="installPublic(skill)"
                >
                  {{ t('skillPool.install') }}
                </GlassButton>
              </div>
            </GlassCard>
          </div>
          <a-empty v-else :description="t('skillPool.noPublic')" />
        </a-spin>
      </a-tab-pane>

      <!-- Private Skills Tab -->
      <a-tab-pane key="private" :tab="t('skillPool.privateSkills')">
        <div class="tab-toolbar">
          <a-input-search
            v-model:value="privateSearch"
            :placeholder="t('skillPool.searchPrivate')"
            allow-clear
            style="max-width: 300px"
          />
        </div>
        <a-spin :spinning="privateLoading">
          <div v-if="filteredPrivate.length" class="skills-grid">
            <GlassCard
              v-for="skill in filteredPrivate"
              :key="skill.id"
              :title="skill.name"
              :subtitle="skill.description"
            >
              <div class="skill-body">
                <div class="skill-meta">
                  <a-tag :color="skill.shared ? 'green' : 'default'">
                    {{ skill.shared ? t('skillPool.shared') : t('skillPool.private') }}
                  </a-tag>
                  <span class="meta-text">v{{ skill.version ?? '1.0' }}</span>
                </div>
                <div class="skill-actions">
                  <GlassButton variant="ghost" size="sm" @click="editSkill(skill)">
                    {{ t('common.edit') }}
                  </GlassButton>
                  <GlassButton variant="secondary" size="sm" @click="toggleShare(skill)">
                    {{ skill.shared ? t('skillPool.unshare') : t('skillPool.share') }}
                  </GlassButton>
                  <GlassButton variant="secondary" size="sm" @click="pushToPool(skill)">
                    {{ t('skillPool.pushToPool') }}
                  </GlassButton>
                  <GlassButton variant="danger" size="sm" @click="deleteSkill(skill)">
                    {{ t('common.delete') }}
                  </GlassButton>
                </div>
              </div>
            </GlassCard>
          </div>
          <a-empty v-else :description="t('skillPool.noPrivate')" />
        </a-spin>
      </a-tab-pane>
    </a-tabs>

    <!-- Create / Edit Modal -->
    <a-modal
      v-model:open="modalVisible"
      :title="editingSkill ? t('skillPool.editSkill') : t('skillPool.createSkill')"
      :confirm-loading="saving"
      @ok="saveSkill"
      @cancel="modalVisible = false"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('skillPool.skillName')">
          <a-input v-model:value="form.name" :placeholder="t('skillPool.namePlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('skillPool.skillDesc')">
          <a-textarea v-model:value="form.description" :rows="3" :placeholder="t('skillPool.descPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('skillPool.skillCategory')">
          <a-input v-model:value="form.category" :placeholder="t('skillPool.categoryPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('skillPool.skillCode')">
          <a-textarea v-model:value="form.code" :rows="8" placeholder="def run(args): ..." />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message, Modal } from 'ant-design-vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import * as skillPoolApi from '@/api/modules/skill-pool'

interface PoolSkill {
  id: string
  name: string
  description: string
  category?: string
  author?: string
  install_count?: number
  shared?: boolean
  version?: string
  code?: string
  _installing?: boolean
}

const { t } = useI18n()

const activeTab = ref<'public' | 'private'>('public')
const publicSkills = ref<PoolSkill[]>([])
const privateSkills = ref<PoolSkill[]>([])
const publicLoading = ref(false)
const privateLoading = ref(false)
const publicSearch = ref('')
const privateSearch = ref('')

// Modal state
const modalVisible = ref(false)
const saving = ref(false)
const editingSkill = ref<PoolSkill | null>(null)
const form = ref({ name: '', description: '', category: '', code: '' })

const filteredPublic = computed(() => {
  const q = publicSearch.value.toLowerCase()
  if (!q) return publicSkills.value
  return publicSkills.value.filter(
    (s) => s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q),
  )
})

const filteredPrivate = computed(() => {
  const q = privateSearch.value.toLowerCase()
  if (!q) return privateSkills.value
  return privateSkills.value.filter(
    (s) => s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q),
  )
})

function openCreateModal() {
  editingSkill.value = null
  form.value = { name: '', description: '', category: '', code: '' }
  modalVisible.value = true
}

function editSkill(skill: PoolSkill) {
  editingSkill.value = skill
  form.value = {
    name: skill.name,
    description: skill.description,
    category: skill.category ?? '',
    code: skill.code ?? '',
  }
  modalVisible.value = true
}

async function fetchPublic() {
  publicLoading.value = true
  try {
    const res = await skillPoolApi.getPublicSkills({ search: publicSearch.value || undefined })
    const data = res?.data
    publicSkills.value = (Array.isArray(data) ? data : data?.items ?? []).map((s: any) => ({ ...s, _installing: false }))
  } catch {
    message.error(t('skillPool.loadError'))
  } finally {
    publicLoading.value = false
  }
}

async function fetchPrivate() {
  privateLoading.value = true
  try {
    const res = await skillPoolApi.getPrivateSkills('_all')
    const data = res?.data
    privateSkills.value = (Array.isArray(data) ? data : data?.items ?? []).map((s: any) => ({ ...s, _installing: false }))
  } catch {
    message.error(t('skillPool.loadError'))
  } finally {
    privateLoading.value = false
  }
}

async function saveSkill() {
  if (!form.value.name.trim()) {
    message.warning(t('skillPool.nameRequired'))
    return
  }
  saving.value = true
  try {
    if (editingSkill.value) {
      await skillPoolApi.updateSkill(editingSkill.value.id, { name: form.value.name, description: form.value.description, category: form.value.category })
      message.success(t('skillPool.updateSuccess'))
    } else {
      await skillPoolApi.createSkill({ name: form.value.name, description: form.value.description, category: form.value.category })
      message.success(t('skillPool.createSuccess'))
    }
    modalVisible.value = false
    fetchPrivate()
  } catch {
    message.error(t('skillPool.saveError'))
  } finally {
    saving.value = false
  }
}

async function installPublic(skill: PoolSkill) {
  skill._installing = true
  try {
    await skillPoolApi.installSkill(skill.id, '_current')
    skill.install_count = (skill.install_count ?? 0) + 1
    message.success(t('skillPool.installSuccess'))
  } catch {
    message.error(t('skillPool.installError'))
  } finally {
    skill._installing = false
  }
}

async function toggleShare(skill: PoolSkill) {
  try {
    if (skill.shared) {
      // Unshare not directly supported by API, use update
      await skillPoolApi.updateSkill(skill.id, { config: { shared: false } })
    } else {
      await skillPoolApi.shareSkill(skill.id)
    }
    skill.shared = !skill.shared
    message.success(skill.shared ? t('skillPool.shareSuccess') : t('skillPool.unshareSuccess'))
  } catch {
    message.error(t('skillPool.shareError'))
  }
}

async function pushToPool(skill: PoolSkill) {
  try {
    await skillPoolApi.pushSkill(skill.id)
    message.success(t('skillPool.pushSuccess'))
  } catch {
    message.error(t('skillPool.pushError'))
  }
}

function deleteSkill(skill: PoolSkill) {
  Modal.confirm({
    title: t('skillPool.confirmDelete'),
    content: skill.name,
    okText: t('common.confirm'),
    cancelText: t('common.cancel'),
    onOk: async () => {
      try {
        await skillPoolApi.deleteSkill(skill.id)
        privateSkills.value = privateSkills.value.filter((s) => s.id !== skill.id)
        message.success(t('skillPool.deleteSuccess'))
      } catch {
        message.error(t('skillPool.deleteError'))
      }
    },
  })
}

onMounted(() => {
  fetchPublic()
  fetchPrivate()
})
</script>

<style scoped>
.pool-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.pool-header .header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.page-title {
  font-family: var(--nr-font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--nr-text-primary);
  margin: 0;
}

.tab-toolbar {
  margin-bottom: 16px;
}

.skills-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.skill-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skill-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.meta-text {
  font-size: 12px;
  color: var(--nr-text-tertiary);
}

.skill-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid var(--nr-glass-border);
}
</style>
