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
          <GlassButton variant="secondary" size="sm" @click="openSubmitModal">
            {{ t('market.submitSkill') }}
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
                  <a-tag v-if="hasPermissionDeclaration(skill)" color="purple">
                    {{ t('market.permissionDeclared') }}
                  </a-tag>
                  <a-tag v-if="sandboxDeclared(skill)" color="orange">
                    {{ t('market.sandboxRequired') }}
                  </a-tag>
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

    <!-- Skill Submit Modal -->
    <a-modal
      v-model:open="showSubmitModal"
      :title="t('market.submitSkill')"
      :ok-text="t('market.submitConfirm')"
      :confirm-loading="submitting"
      @ok="handleSubmitSkill"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('market.submitSkillId')">
          <a-input v-model:value="submitForm.skill_id" :placeholder="t('market.submitSkillIdPh')" />
        </a-form-item>
        <a-form-item :label="t('market.submitName')">
          <a-input v-model:value="submitForm.name" :placeholder="t('market.submitNamePh')" />
        </a-form-item>
        <a-form-item :label="t('market.submitVersion')">
          <a-input v-model:value="submitForm.version" placeholder="1.0.0" />
        </a-form-item>
        <a-form-item :label="t('market.submitDesc')">
          <a-textarea v-model:value="submitForm.description" :rows="3" :placeholder="t('market.submitDescPh')" />
        </a-form-item>
        <a-form-item :label="t('market.submitCategory')">
          <a-input v-model:value="submitForm.category" placeholder="general" />
        </a-form-item>
        <a-form-item :label="t('market.submitUrl')">
          <a-input v-model:value="submitForm.download_url" :placeholder="t('market.submitUrlPh')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Admin: Skill Submissions Review -->
    <GlassPanel v-if="isAdmin" class="market-review" variant="subtle">
      <div class="review-header">
        <h3 class="section-title">{{ t('market.adminReview') }}</h3>
        <GlassButton variant="ghost" size="sm" :loading="submissionsLoading" @click="fetchSubmissions">
          {{ t('common.refresh') }}
        </GlassButton>
      </div>
      <a-empty v-if="!submissions.length" :description="t('market.reviewEmpty')" />
      <a-list v-else :data-source="submissions" row-key="id">
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta
              :title="`${item.name} (v${item.version ?? '1.0.0'})`"
              :description="`${item.skill_id} · ${t('market.reviewBy')} ${item.submitted_by_name ?? item.submitted_by ?? '—'}${item.description ? ' · ' + item.description : ''}`"
            />
            <template #actions>
              <a-button type="primary" size="small" @click="handleReviewSubmission(item, true)">
                {{ t('market.reviewApprove') }}
              </a-button>
              <a-button danger size="small" @click="handleReviewSubmission(item, false)">
                {{ t('market.reviewReject') }}
              </a-button>
            </template>
          </a-list-item>
        </template>
      </a-list>
    </GlassPanel>

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
import * as skillPoolApi from '@/api/modules/skill-pool'
import { useAuthStore } from '@/stores/auth'
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
  /** P0-4 声明式权限：null=未声明；dict=声明生效（运行时 fail-closed） */
  permissions?: Record<string, unknown> | null
  /** P2-15 沙箱声明位 */
  sandbox_required?: boolean | null
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

// P0-4/P2-15 声明徽标：有 permissions 声明或 sandbox_required 时展示
const hasPermissionDeclaration = (skill: MarketSkill) =>
  skill.permissions != null && typeof skill.permissions === 'object'
const sandboxDeclared = (skill: MarketSkill) => skill.sandbox_required === true
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
    await skillPoolApi.installSkillFromZip(file)
    message.success({ content: t('market.installSuccess'), key: 'zip-upload' })
    fetchSkills()
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('market.installFailed')
    message.error({ content: msg, key: 'zip-upload' })
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
    await skillPoolApi.installSkillFromUrl(url)
    message.success(t('market.installSuccess'))
    showUrlModal.value = false
    installUrl.value = ''
    fetchSkills()
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('market.installFailed')
    message.error(msg)
  } finally {
    urlInstalling.value = false
  }
}

async function fetchCategories() {
  // Categories are derived locally from the loaded skills list — no dedicated
  // backend endpoint exists. We group by `skill.category` and de-duplicate.
  const counts = new Map<string, { name: string; icon?: string; count: number }>()
  for (const s of skills.value) {
    const id = s.category ?? 'general'
    const entry = counts.get(id)
    if (entry) entry.count += 1
    else counts.set(id, { name: id, icon: '📁', count: 1 })
  }
  categories.value = Array.from(counts, ([id, v]) => ({ id, ...v }))
}

async function fetchSkills() {
  loading.value = true
  try {
    const res = await skillPoolApi.getPublicSkills()
    const data: any = (res as any)?.data ?? res
    // 市场域返回 skill_id/downloads; 归一化为页内 Skill 形状(id/install_count)
    skills.value = (Array.isArray(data) ? data : data?.items ?? []).map((s: any) => ({
      ...s,
      id: s.id ?? s.skill_id,
      install_count: s.install_count ?? s.downloads ?? 0,
      _installing: false,
    }))
    // Refresh category counts based on the freshly loaded list.
    fetchCategories()
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('market.loadError')
    message.error(msg)
  } finally {
    loading.value = false
  }
}

async function toggleInstall(skill: MarketSkill) {
  skill._installing = true
  try {
    if (skill.installed) {
      await skillPoolApi.uninstallSkill(skill.id, 'default')
      skill.installed = false
      skill.install_count = Math.max(0, (skill.install_count ?? 1) - 1)
      message.success(t('market.uninstallSuccess'))
    } else {
      await skillPoolApi.installSkill(skill.id, 'default')
      skill.installed = true
      skill.install_count = (skill.install_count ?? 0) + 1
      message.success(t('market.installSuccess'))
    }
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('market.actionError')
    message.error(msg)
  } finally {
    skill._installing = false
  }
}

// --- 技能提交与审核（2026-09-01 闭环） ---
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')

const showSubmitModal = ref(false)
const submitting = ref(false)
const submitForm = ref({
  skill_id: '',
  name: '',
  version: '1.0.0',
  description: '',
  category: 'general',
  download_url: '',
})

function openSubmitModal() {
  submitForm.value = {
    skill_id: '',
    name: '',
    version: '1.0.0',
    description: '',
    category: 'general',
    download_url: '',
  }
  showSubmitModal.value = true
}

async function handleSubmitSkill() {
  const f = submitForm.value
  if (!f.skill_id.trim() || !f.name.trim()) {
    message.error(t('market.submitMissingRequired'))
    return
  }
  submitting.value = true
  try {
    await skillPoolApi.submitSkillForReview({
      skill_id: f.skill_id.trim(),
      name: f.name.trim(),
      version: f.version.trim() || '1.0.0',
      description: f.description.trim(),
      category: f.category.trim() || 'general',
      download_url: f.download_url.trim(),
    })
    message.success(t('market.submitSuccess'))
    showSubmitModal.value = false
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.message || t('market.submitError')
    message.error(msg)
  } finally {
    submitting.value = false
  }
}

const submissions = ref<skillPoolApi.SkillSubmission[]>([])
const submissionsLoading = ref(false)

async function fetchSubmissions() {
  if (!isAdmin.value) return
  submissionsLoading.value = true
  try {
    const res: any = await skillPoolApi.listSkillSubmissions('pending')
    const data = res?.data ?? res
    submissions.value = data?.items ?? []
  } catch {
    message.error(t('market.reviewLoadError'))
  } finally {
    submissionsLoading.value = false
  }
}

async function handleReviewSubmission(item: skillPoolApi.SkillSubmission, approve: boolean) {
  try {
    await skillPoolApi.reviewSkillSubmission(item.id, approve)
    message.success(t('market.reviewSuccess'))
    await fetchSubmissions()
    fetchSkills()
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.message || t('market.reviewError')
    message.error(msg)
  }
}

onMounted(() => {
  fetchSkills()
  fetchSubmissions()
})
</script>

<style scoped>
.market-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 技能审核面板 */
.market-review .review-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
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
