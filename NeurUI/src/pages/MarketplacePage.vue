<template>
  <div class="marketplace-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('nav.marketplace') }}</h2>
      <div class="header-actions">
        <a-input-search v-model:value="searchQuery" :placeholder="t('common.search')" style="width: 300px" @search="onSearch" allow-clear />
        <GlassButton v-if="isAdmin" variant="ghost" size="sm" :loading="syncing" @click="syncSources">{{ t('marketplace.syncSources') }}</GlassButton>
        <GlassButton v-if="isAdmin && activeTab === 'browse'" variant="primary" size="sm" @click="openCreate">{{ t('marketplace.publishSkill') }}</GlassButton>
      </div>
    </div>

    <a-tabs v-model:activeKey="activeTab" @change="onTabChange">
      <!-- Neu 市场（管理员上架 + 远端同步目录） -->
      <a-tab-pane key="browse" :tab="t('marketplace.tabNeuMarket')">
        <a-spin :spinning="loading">
          <div class="items-grid">
            <GlassCard v-for="item in items" :key="item.skill_id" :title="item.name" variant="default">
              <template #header>
                <div class="item-header">
                  <span class="item-name">{{ item.name }}</span>
                  <span class="item-tags">
                    <a-tag v-if="item.source && item.source !== 'local'" color="cyan">{{ item.source }}</a-tag>
                    <a-tag :color="item.type === 'plugin' ? 'blue' : 'purple'">{{ item.type }}</a-tag>
                  </span>
                </div>
              </template>
              <div class="item-body">
                <p class="item-desc">{{ item.description }}</p>
                <div class="item-meta">
                  <span class="item-author">{{ item.author }}</span>
                  <span class="item-version">v{{ item.version }}</span>
                  <a-rate :value="item.rating ?? 0" disabled allow-half size="small" />
                </div>
              </div>
              <template #footer>
                <div class="item-actions">
                  <GlassButton
                    v-if="!item.installed"
                    variant="primary"
                    size="sm"
                    :loading="installingId === item.skill_id"
                    @click="installItem(item)"
                  >
                    {{ t('skill.install') }}
                  </GlassButton>
                  <GlassButton v-else variant="ghost" size="sm" disabled>{{ t('marketplace.installed') }}</GlassButton>
                  <GlassButton variant="ghost" size="sm" @click="viewDetails(item)">{{ t('common.open') }}</GlassButton>
                  <template v-if="isAdmin">
                    <GlassButton variant="ghost" size="sm" @click="openEdit(item)">{{ t('marketplace.editSkill') }}</GlassButton>
                    <GlassButton variant="danger" size="sm" @click="removeMarketSkill(item)">{{ t('marketplace.removeSkill') }}</GlassButton>
                  </template>
                </div>
              </template>
            </GlassCard>
          </div>
          <a-empty v-if="!items.length && !loading" :description="t('common.noData')" />
          <div class="pagination-wrap" v-if="browseTotal > pageSize">
            <a-pagination
              v-model:current="browsePage"
              :page-size="pageSize"
              :total="browseTotal"
              :show-size-changer="false"
              @change="fetchBrowse"
            />
          </div>
        </a-spin>
      </a-tab-pane>

      <!-- 阿里云技能 -->
      <a-tab-pane key="aliyun" :tab="t('marketplace.tabAliyun')">
        <a-spin :spinning="loading">
          <div class="items-grid">
            <GlassCard v-for="item in sourceItems" :key="item.skill_id" :title="item.name" variant="default">
              <template #header>
                <div class="item-header">
                  <span class="item-name">{{ item.name }}</span>
                  <a-tag color="cyan">{{ item.source }}</a-tag>
                </div>
              </template>
              <div class="item-body">
                <p class="item-desc">{{ item.description }}</p>
                <div class="item-meta">
                  <span class="item-author">{{ item.author }}</span>
                  <span class="item-version">v{{ item.version }}</span>
                  <span class="item-downloads">{{ item.downloads }} ⬇</span>
                </div>
              </div>
              <template #footer>
                <div class="item-actions">
                  <GlassButton
                    v-if="!item.installed"
                    variant="primary"
                    size="sm"
                    :loading="installingId === item.skill_id"
                    @click="installItem(item)"
                  >
                    {{ t('skill.install') }}
                  </GlassButton>
                  <GlassButton v-else variant="ghost" size="sm" disabled>{{ t('marketplace.installed') }}</GlassButton>
                  <GlassButton variant="ghost" size="sm" @click="viewDetails(item)">{{ t('common.open') }}</GlassButton>
                </div>
              </template>
            </GlassCard>
          </div>
          <a-empty v-if="!sourceItems.length && !loading" :description="t('common.noData')" />
          <div class="pagination-wrap" v-if="sourceTotal > pageSize">
            <a-pagination
              v-model:current="sourcePage"
              :page-size="pageSize"
              :total="sourceTotal"
              :show-size-changer="false"
              @change="fetchSource('aliyun')"
            />
          </div>
        </a-spin>
      </a-tab-pane>

      <!-- 讯飞技能 -->
      <a-tab-pane key="xfyun" :tab="t('marketplace.tabXfyun')">
        <a-spin :spinning="loading">
          <div class="items-grid">
            <GlassCard v-for="item in sourceItems" :key="item.skill_id" :title="item.name" variant="default">
              <template #header>
                <div class="item-header">
                  <span class="item-name">{{ item.name }}</span>
                  <a-tag color="cyan">{{ item.source }}</a-tag>
                </div>
              </template>
              <div class="item-body">
                <p class="item-desc">{{ item.description }}</p>
                <div class="item-meta">
                  <span class="item-author">{{ item.author }}</span>
                  <span class="item-version">v{{ item.version }}</span>
                  <span class="item-downloads">{{ item.downloads }} ⬇</span>
                </div>
              </div>
              <template #footer>
                <div class="item-actions">
                  <GlassButton
                    v-if="!item.installed"
                    variant="primary"
                    size="sm"
                    :loading="installingId === item.skill_id"
                    @click="installItem(item)"
                  >
                    {{ t('skill.install') }}
                  </GlassButton>
                  <GlassButton v-else variant="ghost" size="sm" disabled>{{ t('marketplace.installed') }}</GlassButton>
                  <GlassButton variant="ghost" size="sm" @click="viewDetails(item)">{{ t('common.open') }}</GlassButton>
                </div>
              </template>
            </GlassCard>
          </div>
          <a-empty v-if="!sourceItems.length && !loading" :description="t('common.noData')" />
          <div class="pagination-wrap" v-if="sourceTotal > pageSize">
            <a-pagination
              v-model:current="sourcePage"
              :page-size="pageSize"
              :total="sourceTotal"
              :show-size-changer="false"
              @change="fetchSource('xfyun')"
            />
          </div>
        </a-spin>
      </a-tab-pane>

      <!-- 已安装 -->
      <a-tab-pane key="installed" :tab="t('marketplace.installed')">
        <a-spin :spinning="loading">
          <div class="items-grid">
            <GlassCard v-for="item in installedItems" :key="item.skill_id" :title="item.name" variant="default">
              <template #header>
                <div class="item-header">
                  <span class="item-name">{{ item.name }}</span>
                  <a-tag color="green">{{ t('marketplace.installed') }}</a-tag>
                </div>
              </template>
              <p class="item-desc">{{ item.description }}</p>
              <div class="item-meta" v-if="hasUpdate(item)">
                <a-tag color="orange">{{ t('marketplace.updateAvailable', { v: latestVersions[item.skill_id] }) }}</a-tag>
              </div>
              <template #footer>
                <div class="item-actions">
                  <GlassButton
                    v-if="hasUpdate(item)"
                    variant="primary"
                    size="sm"
                    :loading="updatingId === item.skill_id"
                    @click="updateItem(item)"
                  >
                    {{ t('marketplace.update') }}
                  </GlassButton>
                  <GlassButton variant="danger" size="sm" @click="uninstallItem(item.skill_id)">
                    {{ t('skill.uninstall') }}
                  </GlassButton>
                </div>
              </template>
            </GlassCard>
          </div>
          <a-empty v-if="!installedItems.length && !loading" :description="t('common.noData')" />
        </a-spin>
      </a-tab-pane>
    </a-tabs>

    <!-- Detail modal -->
    <a-modal v-model:open="showDetail" :title="detailItem?.name" :footer="null" width="560px">
      <div v-if="detailItem" class="detail-content">
        <p>{{ detailItem.description }}</p>
        <a-descriptions :column="1" size="small" bordered>
          <a-descriptions-item :label="t('marketplace.author')">{{ detailItem.author }}</a-descriptions-item>
          <a-descriptions-item :label="t('marketplace.version')">{{ detailItem.version }}</a-descriptions-item>
          <a-descriptions-item :label="t('marketplace.type')">{{ detailItem.type }}</a-descriptions-item>
          <a-descriptions-item :label="t('marketplace.downloads')">{{ detailItem.downloads ?? 0 }}</a-descriptions-item>
        </a-descriptions>
      </div>
    </a-modal>

    <!-- 管理员: 上架/编辑技能 Modal -->
    <a-modal
      v-model:open="showPublish"
      :title="editingSkill ? t('marketplace.formUpdateTitle') : t('marketplace.formCreateTitle')"
      @ok="savePublish"
      :confirm-loading="publishing"
    >
      <a-form layout="vertical" :model="publishForm">
        <a-form-item :label="t('marketplace.skillId')">
          <a-input v-model:value="publishForm.skill_id" :disabled="!!editingSkill" />
        </a-form-item>
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="publishForm.name" />
        </a-form-item>
        <a-form-item :label="t('marketplace.version')">
          <a-input v-model:value="publishForm.version" />
        </a-form-item>
        <a-form-item :label="t('marketplace.category')">
          <a-input v-model:value="publishForm.category" />
        </a-form-item>
        <a-form-item :label="t('marketplace.author')">
          <a-input v-model:value="publishForm.author" />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-textarea v-model:value="publishForm.description" :rows="3" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const authStore = useAuthStore()
/** 市场上架/编辑/下架仅管理员 */
const isAdmin = computed(() => authStore.user?.role === 'admin')

const activeTab = ref('browse')
const loading = ref(false)
const installingId = ref<string | null>(null)
const updatingId = ref<string | null>(null)
const searchQuery = ref('')
const items = ref<any[]>([])
const installedItems = ref<any[]>([])
const latestVersions = ref<Record<string, string>>({})
const showDetail = ref(false)
const detailItem = ref<any>(null)

// ── 来源 Tab 分页（服务端分页: with_total 信封） ──
// Tab key → 后端 source 参数；browse(Neu 市场)不传 source
const TAB_SOURCES: Record<string, string | undefined> = {
  browse: undefined,
  aliyun: 'aliyun',
  xfyun: 'xfyun',
}
const pageSize = 12
const browsePage = ref(1)
const browseTotal = ref(0)
const sourcePage = ref(1)
const sourceTotal = ref(0)
const sourceItems = ref<any[]>([])

/** Tab 切换: 重置分页并按需拉取 */
async function onTabChange(key: string | number) {
  const k = String(key)
  if (k === 'browse') {
    browsePage.value = 1
    await fetchBrowse()
  } else if (TAB_SOURCES[k]) {
    sourcePage.value = 1
    await fetchSource(TAB_SOURCES[k]!)
  } else {
    await fetchMarketplace() // installed tab
  }
}

/** 搜索: 重置当前 Tab 页码后拉取 */
async function onSearch() {
  if (activeTab.value === 'browse') {
    browsePage.value = 1
    await fetchBrowse()
  } else if (TAB_SOURCES[activeTab.value]) {
    sourcePage.value = 1
    await fetchSource(TAB_SOURCES[activeTab.value]!)
  } else {
    await fetchMarketplace()
  }
}

/** Neu 市场 Tab: 不带 source，服务端分页 */
async function fetchBrowse() {
  loading.value = true
  try {
    const params: any = { limit: pageSize, offset: (browsePage.value - 1) * pageSize, with_total: true }
    if (searchQuery.value) params.search = searchQuery.value
    const res: any = await request.get('/marketplace/skills', { params })
    const data = res?.data ?? res
    // 信封 {items,total} 或裸数组（老后端兜底）
    if (Array.isArray(data)) {
      items.value = data
      browseTotal.value = data.length
    } else {
      items.value = data?.items ?? []
      browseTotal.value = data?.total ?? 0
    }
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

/** 来源 Tab（阿里云/讯飞）: source 过滤 + 服务端分页 */
async function fetchSource(source: string) {
  loading.value = true
  try {
    const params: any = { source, limit: pageSize, offset: (sourcePage.value - 1) * pageSize, with_total: true }
    if (searchQuery.value) params.search = searchQuery.value
    const res: any = await request.get('/marketplace/skills', { params })
    const data = res?.data ?? res
    if (Array.isArray(data)) {
      sourceItems.value = data
      sourceTotal.value = data.length
    } else {
      sourceItems.value = data?.items ?? []
      sourceTotal.value = data?.total ?? 0
    }
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

// ── 管理员: 远端市场源同步（阿里云/讯飞 → catalog） ──
const syncing = ref(false)
async function syncSources() {
  syncing.value = true
  try {
    const res: any = await request.post('/marketplace/sync')
    const data = res?.data ?? res
    const totals = data?.totals ?? {}
    message.success(`+${totals.created ?? 0} / ~${totals.updated ?? 0} / -${totals.removed ?? 0}`)
    await fetchMarketplace()
  } catch {
    message.error(t('common.error'))
  } finally {
    syncing.value = false
  }
}

// ── 管理员: 上架/编辑 Modal ──
const showPublish = ref(false)
const publishing = ref(false)
const editingSkill = ref<any>(null)
const publishForm = ref({
  skill_id: '', name: '', version: '1.0.0', description: '',
  author: '', category: 'general', download_url: '',
})

function openCreate() {
  editingSkill.value = null
  publishForm.value = { skill_id: '', name: '', version: '1.0.0', description: '', author: '', category: 'general', download_url: '' }
  showPublish.value = true
}

function openEdit(item: any) {
  editingSkill.value = item
  publishForm.value = {
    skill_id: item.skill_id, name: item.name, version: item.version,
    description: item.description ?? '', author: item.author ?? '',
    category: item.category ?? 'general', download_url: item.download_url ?? '',
  }
  showPublish.value = true
}

async function savePublish() {
  publishing.value = true
  try {
    if (editingSkill.value) {
      const { skill_id, ...patch } = publishForm.value
      await request.put(`/marketplace/skills/${skill_id}`, patch)
    } else {
      await request.post('/marketplace/skills', publishForm.value)
    }
    message.success(t('common.success'))
    showPublish.value = false
    await fetchMarketplace()
  } catch {
    message.error(t('common.error'))
  } finally {
    publishing.value = false
  }
}

async function removeMarketSkill(item: any) {
  try {
    await request.delete(`/marketplace/skills/${item.skill_id}`)
    message.success(t('common.success'))
    // 刷新当前页（total 变化）
    await fetchBrowse()
  } catch {
    message.error(t('common.error'))
  }
}

/** 已安装技能升级到市场最新版(force 重装) */
async function updateItem(item: any) {
  updatingId.value = item.skill_id
  try {
    await request.post(`/marketplace/skills/${item.skill_id}/install`, { force: true })
    message.success(t('common.success'))
    await fetchMarketplace()
  } catch {
    message.error(t('common.error'))
  } finally {
    updatingId.value = null
  }
}

const fetchMarketplace = async () => {
  loading.value = true
  try {
    const params: any = {}
    if (searchQuery.value) params.search = searchQuery.value

    if (activeTab.value === 'browse') {
      await fetchBrowse()
      return
    }
    if (TAB_SOURCES[activeTab.value]) {
      await fetchSource(TAB_SOURCES[activeTab.value]!)
      return
    }

    // installed tab
    const [installRes, marketRes]: any[] = await Promise.all([
      request.get('/marketplace/installed', { params }),
      request.get('/marketplace/skills', {}),
    ])
    const installed = installRes?.data ?? installRes ?? []
    const market = marketRes?.data ?? marketRes ?? []
    installedItems.value = installed
    // 市场最新版本表: 已安装卡片显示"可更新"提示
    latestVersions.value = Object.fromEntries(
      (Array.isArray(market) ? market : []).map((s: any) => [s.skill_id, s.version]),
    )
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const installItem = async (item: any) => {
  installingId.value = item.skill_id
  try {
    await request.post(`/marketplace/skills/${item.skill_id}/install`)
    message.success(t('common.success'))
    item.installed = true
  } catch {
    message.error(t('common.error'))
  } finally {
    installingId.value = null
  }
}

const uninstallItem = async (id: string) => {
  try {
    await request.delete(`/marketplace/skills/${id}/install`)
    message.success(t('common.success'))
    installedItems.value = installedItems.value.filter(i => i.skill_id !== id)
  } catch {
    message.error(t('common.error'))
  }
}

const viewDetails = (item: any) => {
  detailItem.value = item
  showDetail.value = true
}

/** 已安装技能是否有市场新版本可更新 */
function hasUpdate(item: any): boolean {
  const latest = latestVersions.value[item.skill_id]
  return !!latest && latest !== item.version
}

onMounted(fetchMarketplace)
</script>

<style scoped>
.marketplace-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.page-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
.items-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.item-header { display: flex; justify-content: space-between; align-items: center; }
.item-tags { display: flex; gap: 4px; align-items: center; }
.item-name { font-weight: 600; color: var(--nr-text-primary); }
.item-body { display: flex; flex-direction: column; gap: 8px; }
.item-desc { font-size: 13px; color: var(--nr-text-secondary); margin: 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.item-meta { display: flex; align-items: center; gap: 12px; font-size: 11px; color: var(--nr-text-muted); }
.item-author { font-weight: 500; }
.item-version { font-family: var(--nr-font-mono); }
.item-actions { display: flex; gap: 8px; align-items: center; }
.pagination-wrap { display: flex; justify-content: center; padding: 16px 0 4px; }
.item-downloads { font-family: var(--nr-font-mono); }
.detail-content p { color: var(--nr-text-secondary); font-size: 14px; }
</style>
