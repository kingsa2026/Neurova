<template>
  <div class="pool-page">
    <!-- Header -->
    <GlassPanel class="pool-header">
      <div class="header-row">
        <h2 class="page-title">{{ t('skillPool.title') }}</h2>
        <div class="header-actions">
          <GlassButton variant="secondary" size="sm" @click="showUrlModal = true">
            {{ t('skillPool.installFromUrl') }}
          </GlassButton>
          <GlassButton variant="secondary" size="sm" @click="triggerZipUpload">
            {{ t('skillPool.importZip') }}
          </GlassButton>
          <GlassButton variant="primary" size="sm" @click="openCreateModal">
            {{ t('skillPool.createSkill') }}
          </GlassButton>
        </div>
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
              v-for="skill in pagedPublic"
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
          <a-pagination v-if="filteredPublic.length > pageSize" v-model:current="publicPage" :pageSize="pageSize" :total="filteredPublic.length" size="small" style="margin-top: 16px; text-align: center" />
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
              v-for="skill in pagedPrivate"
              :key="skill.id"
              :title="skill.name"
              :subtitle="skill.description"
            >
              <div class="skill-body">
                <div class="skill-meta">
                  <a-tag color="blue">{{ t('skillPool.private') }}</a-tag>
                  <span class="meta-text">v{{ skill.version ?? '1.0' }}</span>
                </div>
                <div class="skill-actions">
                  <GlassButton variant="ghost" size="sm" @click="editSkill(skill)">
                    {{ t('common.edit') }}
                  </GlassButton>
                  <GlassButton variant="secondary" size="sm" @click="publishToPublic(skill)">
                    {{ t('skillPool.publishToPublic') }}
                  </GlassButton>
                  <GlassButton variant="danger" size="sm" @click="deleteSkill(skill)">
                    {{ t('common.delete') }}
                  </GlassButton>
                </div>
              </div>
            </GlassCard>
          </div>
          <a-pagination v-if="filteredPrivate.length > pageSize" v-model:current="privatePage" :pageSize="pageSize" :total="filteredPrivate.length" size="small" style="margin-top: 16px; text-align: center" />
          <a-empty v-else :description="t('skillPool.noPrivate')" />
        </a-spin>
      </a-tab-pane>

      <!-- Wave H-W5 三层库流转确认队列（agent→user 推送 / 公共库升级，确认才落库） -->
      <a-tab-pane key="transfers" :tab="t('skillPool.transferTab')">
        <p class="tab-hint">{{ t('skillPool.transfersHint') }}</p>
        <a-spin :spinning="transfersLoading">
          <div v-if="transfers.length" class="skills-grid">
            <GlassCard v-for="tr in transfers" :key="tr.transfer_id" :title="tr.name || tr.skill_id" :subtitle="`v${tr.version}`">
              <div class="skill-body">
                <div class="skill-meta">
                  <a-tag :color="tr.kind === 'upgrade' ? 'orange' : 'green'">
                    {{ tr.kind === 'upgrade' ? t('skillPool.transferKindUpgrade') : t('skillPool.transferKindInitial') }}
                  </a-tag>
                  <span class="meta-text">{{ t('skillPool.transferFrom') }} {{ tr.src_pool }}{{ tr.src_owner ? `/${tr.src_owner}` : '' }}</span>
                </div>
                <div style="display: flex; gap: 8px">
                  <GlassButton variant="primary" size="sm" :loading="transferBusy === tr.transfer_id" @click="doAcceptTransfer(tr)">
                    {{ t('skillPool.transferAccept') }}
                  </GlassButton>
                  <GlassButton variant="ghost" size="sm" :disabled="transferBusy === tr.transfer_id" @click="doRejectTransfer(tr)">
                    {{ t('skillPool.transferReject') }}
                  </GlassButton>
                </div>
              </div>
            </GlassCard>
          </div>
          <a-empty v-else :description="t('skillPool.noTransfers')" />
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
      <a-form layout="vertical" :rules="{ name: [{ required: true, message: t('common.required') }] }">
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

    <!-- URL Install Modal -->
    <a-modal
      v-model:open="showUrlModal"
      :title="t('skillPool.urlInputTitle')"
      :ok-text="t('skillPool.install')"
      :confirm-loading="urlInstalling"
      @ok="handleUrlInstall"
      @cancel="showUrlModal = false"
    >
      <div style="margin-bottom: 8px; color: var(--nr-text-secondary); font-size: 13px;">
        {{ t('skillPool.urlInputDesc') }}
      </div>
      <a-input
        v-model:value="installUrl"
        :placeholder="t('skillPool.urlInputPlaceholder')"
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
import { ref, computed, onMounted, watch } from 'vue'
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

const activeTab = ref<'public' | 'private' | 'pending' | 'transfers'>('public')

// Wave H-W5 流转确认队列（三层库：agent→user 推送 / 公共库升级卡）
const transfers = ref<skillPoolApi.SkillTransfer[]>([])
const transfersLoading = ref(false)
const transferBusy = ref('')

async function fetchTransfers() {
  transfersLoading.value = true
  try {
    const res = await skillPoolApi.listSkillTransfers('pending')
    const data: any = res?.data
    transfers.value = Array.isArray(data) ? data : data?.items ?? []
  } catch {
    transfers.value = []
  } finally {
    transfersLoading.value = false
  }
}

async function doAcceptTransfer(tr: skillPoolApi.SkillTransfer) {
  transferBusy.value = tr.transfer_id
  try {
    await skillPoolApi.acceptSkillTransfer(tr.transfer_id)
    message.success(t('skillPool.transferAccepted'))
    fetchTransfers()
    fetchPrivate()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || err?.message || t('skillPool.transferError'))
  } finally {
    transferBusy.value = ''
  }
}

async function doRejectTransfer(tr: skillPoolApi.SkillTransfer) {
  transferBusy.value = tr.transfer_id
  try {
    await skillPoolApi.rejectSkillTransfer(tr.transfer_id)
    message.success(t('skillPool.transferRejected'))
    fetchTransfers()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || err?.message || t('skillPool.transferError'))
  } finally {
    transferBusy.value = ''
  }
}

// C10 治理收紧：待审产物审批面
const pendingLoading = ref(false)
const pendingExperiences = ref<any[]>([])
const pendingSkills = ref<any[]>([])

async function fetchPending() {
  pendingLoading.value = true
  try {
    const [expRes, skillRes] = await Promise.all([
      skillPoolApi.listPendingSkills('_all'),
      skillPoolApi.listPendingExperiences('_all'),
    ])
    const unwrap = (r: any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? [])
    pendingSkills.value = unwrap(skillRes)
    pendingExperiences.value = unwrap(expRes)
  } catch (err: any) {
    message.error(err?.response?.data?.error || err?.message || t('skillPool.loadError'))
  } finally {
    pendingLoading.value = false
  }
}

async function handleApproveExperience(recordId: string) {
  try {
    await skillPoolApi.approvePendingExperience('_all', recordId)
    message.success(t('skillPool.approve') + ' ✓')
    await fetchPending()
  } catch (err: any) {
    message.error(err?.response?.data?.error || err?.message)
  }
}

async function handleRejectExperience(recordId: string) {
  try {
    await skillPoolApi.rejectPendingExperience('_all', recordId)
    await fetchPending()
  } catch (err: any) {
    message.error(err?.response?.data?.error || err?.message)
  }
}

async function handleApproveSkill(templateId: string) {
  try {
    await skillPoolApi.approvePendingSkill('_all', templateId)
    message.success(t('skillPool.approve') + ' ✓')
    await fetchPending()
  } catch (err: any) {
    message.error(err?.response?.data?.error || err?.message)
  }
}

async function handleRejectSkill(templateId: string) {
  try {
    await skillPoolApi.rejectPendingSkill('_all', templateId)
    await fetchPending()
  } catch (err: any) {
    message.error(err?.response?.data?.error || err?.message)
  }
}

watch(activeTab, (tab) => { if (tab === 'pending') fetchPending() })
const publicSkills = ref<PoolSkill[]>([])
const privateSkills = ref<PoolSkill[]>([])
const publicLoading = ref(false)
const privateLoading = ref(false)
const publicSearch = ref('')
const privateSearch = ref('')
const publicPage = ref(1)
const privatePage = ref(1)
const pageSize = ref(12)

// Modal state
const modalVisible = ref(false)
const saving = ref(false)
const editingSkill = ref<PoolSkill | null>(null)
const form = ref({ name: '', description: '', category: '', code: '' })

// URL / ZIP import state
const showUrlModal = ref(false)
const installUrl = ref('')
const urlInstalling = ref(false)
const zipFileInput = ref<HTMLInputElement | null>(null)

function triggerZipUpload() {
  zipFileInput.value?.click()
}

async function handleZipFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  input.value = ''
  if (!file.name.endsWith('.zip')) {
    message.error(t('skillPool.zipInvalid'))
    return
  }
  message.loading({ content: t('skillPool.uploading'), key: 'zip-upload', duration: 0 })
  try {
    await skillPoolApi.installSkillFromZip(file, 'me')
    message.success({ content: t('skillPool.installSuccess'), key: 'zip-upload' })
    fetchPrivate()
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skillPool.installError')
    message.error({ content: msg, key: 'zip-upload' })
  }
}

async function handleUrlInstall() {
  const url = installUrl.value.trim()
  if (!url) return
  urlInstalling.value = true
  try {
    await skillPoolApi.installSkillFromUrl(url, undefined, 'me')
    message.success(t('skillPool.installSuccess'))
    showUrlModal.value = false
    installUrl.value = ''
    fetchPrivate()
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skillPool.installError')
    message.error(msg)
  } finally {
    urlInstalling.value = false
  }
}

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

const pagedPublic = computed(() =>
  filteredPublic.value.slice((publicPage.value - 1) * pageSize.value, publicPage.value * pageSize.value),
)

const pagedPrivate = computed(() =>
  filteredPrivate.value.slice((privatePage.value - 1) * pageSize.value, privatePage.value * pageSize.value),
)

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

// 三层库契约：GET 返回裸数组（拦截器已解包 body），主键字段是 skill_id——
// 归一化为前端统一 id（旧实现读 res.data 恒 undefined → 两页签生产恒空）。
function normLibraryRows(res: any): PoolSkill[] {
  const data = res?.data ?? res
  const arr = Array.isArray(data) ? data : data?.items ?? []
  return arr.map((s: any) => ({ ...s, id: s.skill_id ?? s.id ?? '', _installing: false }))
}

async function fetchPublic() {
  publicLoading.value = true
  try {
    const res = await skillPoolApi.listPublicLibrarySkills()
    publicSkills.value = normLibraryRows(res)
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skillPool.loadError')
    message.error(msg)
  } finally {
    publicLoading.value = false
  }
}

async function fetchPrivate() {
  privateLoading.value = true
  try {
    const res = await skillPoolApi.listMySkills()
    privateSkills.value = normLibraryRows(res)
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skillPool.loadError')
    message.error(msg)
  } finally {
    privateLoading.value = false
  }
}

async function saveSkill() {
  saving.value = true
  try {
    if (editingSkill.value) {
      await skillPoolApi.updateMySkill(editingSkill.value.id, { name: form.value.name, description: form.value.description, category: form.value.category })
      message.success(t('skillPool.updateSuccess'))
    } else {
      await skillPoolApi.createMySkill({ name: form.value.name, description: form.value.description, category: form.value.category })
      message.success(t('skillPool.createSuccess'))
    }
    modalVisible.value = false
    fetchPrivate()
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.response?.data?.error || err?.message || t('skillPool.saveError')
    message.error(msg)
  } finally {
    saving.value = false
  }
}

async function installPublic(skill: PoolSkill) {
  skill._installing = true
  try {
    // 三层语义：公共库→我的私库自助安装（副本+血缘，公共升级广播可达）
    await skillPoolApi.installPublicToMine(skill.id)
    skill.install_count = (skill.install_count ?? 0) + 1
    message.success(t('skillPool.installSuccess'))
    fetchPrivate()
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.response?.data?.error || err?.message || t('skillPool.installError')
    message.error(msg)
  } finally {
    skill._installing = false
  }
}

/** 发布到公共库（需求 3：用户私库技能→公共库，须管理员审批）——
 *  复用既有 submissions 审批流；旧 share/push 双按钮（断链路由）退役。 */
async function publishToPublic(skill: PoolSkill) {
  try {
    await skillPoolApi.submitSkillForReview({
      skill_id: skill.id,
      name: skill.name,
      description: skill.description ?? '',
      version: skill.version ?? '1.0.0',
      category: skill.category ?? 'general',
      // 服务端从本人用户私库快照 tool_sequence 载荷（公共副本保持可执行）
      pool_skill_id: skill.id,
    })
    message.success(t('skillPool.publishSubmitted'))
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.response?.data?.error || err?.message || t('skillPool.publishError')
    message.error(msg)
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
        await skillPoolApi.deleteMySkill(skill.id)
        privateSkills.value = privateSkills.value.filter((s) => s.id !== skill.id)
        message.success(t('skillPool.deleteSuccess'))
      } catch (err: any) {
        const msg = err?.response?.data?.detail || err?.response?.data?.error || err?.message || t('skillPool.deleteError')
        message.error(msg)
      }
    },
  })
}

onMounted(() => {
  fetchPublic()
  fetchPrivate()
  fetchTransfers()
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
