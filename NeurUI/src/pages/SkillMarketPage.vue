<template>
  <div class="market-page">
    <!-- Header -->
    <GlassPanel class="market-header">
      <div class="header-row">
        <div class="header-left">
          <h2 class="page-title">{{ t('market.title') }}</h2>
          <a-input-search
            v-model:value="searchQuery"
            :placeholder="t('market.searchPlaceholder')"
            allow-clear
            style="width: 280px"
            @search="fetchSkills"
          />
        </div>
        <div class="header-actions">
          <GlassButton variant="secondary" size="sm" @click="fetchSkills">
            {{ t('common.refresh') }}
          </GlassButton>
          <GlassButton variant="primary" size="sm" @click="showUrlModal = true">
            {{ t('market.installFromUrl') }}
          </GlassButton>
          <GlassButton variant="secondary" size="sm" @click="triggerZipUpload">
            {{ t('market.importZip') }}
          </GlassButton>
        </div>
      </div>
    </GlassPanel>

    <div class="market-body">
      <!-- Category Sidebar -->
      <GlassPanel class="category-panel" variant="subtle">
        <div class="category-list">
          <div
            v-for="cat in categories"
            :key="cat.id"
            class="category-item"
            :class="{ active: activeCategory === cat.id }"
            @click="selectCategory(cat.id)"
          >
            <span class="cat-icon">{{ cat.icon ?? '📁' }}</span>
            <span class="cat-name">{{ cat.name }}</span>
            <a-badge :count="cat.count ?? 0" :number-style="{ backgroundColor: 'rgba(99,102,241,0.3)', color: 'var(--nr-text-secondary)', fontSize: '10px' }" />
          </div>
        </div>
      </GlassPanel>

      <!-- Skills Content -->
      <div class="skills-content">
        <!-- Featured Section -->
        <template v-if="!activeCategory && !searchQuery">
          <h3 class="section-title">{{ t('market.featured') }}</h3>
          <div v-if="featuredSkills.length" class="featured-grid">
            <GlassCard
              v-for="skill in featuredSkills"
              :key="skill.id"
              :title="skill.name"
              :subtitle="skill.description"
              variant="elevated"
              glow
            >
              <div class="skill-card-body">
                <div class="skill-stats-row">
                  <span class="rating">⭐ {{ skill.rating?.toFixed(1) ?? '—' }}</span>
                  <span class="installs">📥 {{ skill.install_count ?? 0 }}</span>
                </div>
                <GlassButton
                  :variant="skill.installed ? 'danger' : 'primary'"
                  size="sm"
                  :loading="skill._installing"
                  @click="toggleInstall(skill)"
                >
                  {{ skill.installed ? t('market.uninstall') : t('market.install') }}
                </GlassButton>
              </div>
            </GlassCard>
          </div>
        </template>

        <!-- All / Filtered Skills -->
        <h3 class="section-title">{{ sectionTitle }}</h3>
        <a-spin :spinning="loading">
          <div v-if="displaySkills.length" class="skills-grid">
            <GlassCard
              v-for="skill in displaySkills"
              :key="skill.id"
              :title="skill.name"
              :subtitle="skill.description"
            >
              <div class="skill-card-body">
                <div class="skill-stats-row">
                  <span class="rating">⭐ {{ skill.rating?.toFixed(1) ?? '—' }}</span>
                  <span class="installs">📥 {{ skill.install_count ?? 0 }}</span>
                  <a-tag v-if="skill.category" color="blue">{{ skill.category }}</a-tag>
                </div>
                <GlassButton
                  :variant="skill.installed ? 'danger' : 'primary'"
                  size="sm"
                  :loading="skill._installing"
                  @click="toggleInstall(skill)"
                >
                  {{ skill.installed ? t('market.uninstall') : t('market.install') }}
                </GlassButton>
              </div>
            </GlassCard>
          </div>
          <a-empty v-else :description="t('market.noSkills')" />
        </a-spin>
      </div>
    </div>

    <!-- URL Install Modal -->
    <a-modal
      v-model:open="showUrlModal"
      :title="t('market.urlInputTitle')"
      :ok-text="t('market.install')"
      :confirm-loading="urlInstalling"
      @ok="handleUrlInstall"
    >
      <div style="margin-bottom: 8px; color: var(--nr-text-secondary); font-size: 13px;">
        {{ t('market.urlInputDesc') }}
      </div>
      <a-input
        v-model:value="installUrl"
        :placeholder="t('market.urlInputPlaceholder')"
        allow-clear
        @press-enter="handleUrlInstall"
      />
    </a-modal>

    <!-- Hidden ZIP file input -->
    <input
      ref="zipFileInput"
      type="file"
      accept=".zip"
      style="display: none"
      @change="handleZipFileChange"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { request } from '@/api'
import { installSkillFromUrl, installSkillFromZip } from '@/api/modules/skill-pool'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

interface MarketSkill {
  id: string
  name: string
  description: string
  rating?: number
  install_count?: number
  category?: string
  icon?: string
  featured?: boolean
  installed?: boolean
  _installing?: boolean
}

interface Category {
  id: string
  name: string
  icon?: string
  count?: number
}

const { t } = useI18n()

const skills = ref<MarketSkill[]>([])
const categories = ref<Category[]>([])
const loading = ref(false)
const searchQuery = ref('')
const activeCategory = ref<string>('')

const featuredSkills = computed(() => skills.value.filter((s) => s.featured))
const displaySkills = computed(() => {
  let list = skills.value
  if (activeCategory.value) {
    list = list.filter((s) => s.category === activeCategory.value)
  }
  const q = searchQuery.value.toLowerCase()
  if (q) {
    list = list.filter(
      (s) => s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q),
    )
  }
  return list
})

const sectionTitle = computed(() => {
  if (searchQuery.value) return t('market.searchResults')
  if (activeCategory.value) {
    const cat = categories.value.find((c) => c.id === activeCategory.value)
    return cat?.name ?? t('market.allSkills')
  }
  return t('market.allSkills')
})

function selectCategory(id: string) {
  activeCategory.value = activeCategory.value === id ? '' : id
}

// --- ZIP import ---
const zipFileInput = ref<HTMLInputElement | null>(null)

function triggerZipUpload() {
  zipFileInput.value?.click()
}

async function handleZipFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  input.value = '' // reset so same file can be re-selected

  if (!file.name.endsWith('.zip')) {
    message.error('Please select a .zip file')
    return
  }

  message.loading({ content: t('market.uploading'), key: 'zip-upload', duration: 0 })
  try {
    await installSkillFromZip(file)
    message.success({ content: t('market.installSuccess'), key: 'zip-upload' })
    fetchSkills()
  } catch {
    message.error({ content: t('market.installFailed'), key: 'zip-upload' })
  }
}

// --- Remote URL install ---
const showUrlModal = ref(false)
const installUrl = ref('')
const urlInstalling = ref(false)

async function handleUrlInstall() {
  const url = installUrl.value.trim()
  if (!url) return

  urlInstalling.value = true
  try {
    await installSkillFromUrl(url)
    message.success(t('market.installSuccess'))
    showUrlModal.value = false
    installUrl.value = ''
    fetchSkills()
  } catch {
    message.error(t('market.installFailed'))
  } finally {
    urlInstalling.value = false
  }
}

async function fetchCategories() {
  try {
    const res: any = await request.get('/skills-market/categories')
    const data = res?.data ?? res
    categories.value = Array.isArray(data) ? data : data?.items ?? []
  } catch {
    // Categories optional
  }
}

async function fetchSkills() {
  loading.value = true
  try {
    const res: any = await request.get('/skills-market/skills')
    const data = res?.data ?? res
    skills.value = (Array.isArray(data) ? data : data?.items ?? []).map((s: any) => ({
      ...s,
      _installing: false,
    }))
  } catch {
    message.error(t('market.loadError'))
  } finally {
    loading.value = false
  }
}

async function toggleInstall(skill: MarketSkill) {
  skill._installing = true
  try {
    if (skill.installed) {
      await request.delete(`/marketplace/skills/${skill.id}/install`)
      skill.installed = false
      skill.install_count = Math.max(0, (skill.install_count ?? 1) - 1)
      message.success(t('market.uninstallSuccess'))
    } else {
      await request.post('/skills-market/install', { skill_id: skill.id })
      skill.installed = true
      skill.install_count = (skill.install_count ?? 0) + 1
      message.success(t('market.installSuccess'))
    }
  } catch {
    message.error(t('market.actionError'))
  } finally {
    skill._installing = false
  }
}

onMounted(() => {
  fetchCategories()
  fetchSkills()
})
</script>

<style scoped>
.market-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.market-header .header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-title {
  font-family: var(--nr-font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--nr-text-primary);
  margin: 0;
  white-space: nowrap;
}

.market-body {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 20px;
  align-items: start;
}

.category-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.category-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 13px;
  color: var(--nr-text-secondary);
}

.category-item:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--nr-text-primary);
}

.category-item.active {
  background: rgba(99, 102, 241, 0.12);
  color: var(--nr-primary-light);
}

.cat-icon {
  font-size: 16px;
}

.cat-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.section-title {
  font-family: var(--nr-font-display);
  font-size: 16px;
  font-weight: 600;
  color: var(--nr-text-primary);
  margin: 0 0 12px;
}

.skills-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.featured-grid,
.skills-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.skill-card-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skill-stats-row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}

.rating,
.installs {
  color: var(--nr-text-secondary);
}
</style>
