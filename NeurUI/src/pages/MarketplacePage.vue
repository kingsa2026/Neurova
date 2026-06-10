<template>
  <div class="marketplace-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('nav.marketplace') }}</h2>
      <a-input-search v-model:value="searchQuery" :placeholder="t('common.search')" style="width: 300px" @search="fetchMarketplace" allow-clear />
    </div>

    <a-tabs v-model:activeKey="activeTab" @change="fetchMarketplace">
      <!-- Browse tab -->
      <a-tab-pane key="browse" :tab="t('marketplace.browse')">
        <a-spin :spinning="loading">
          <div class="items-grid">
            <GlassCard v-for="item in items" :key="item.id" :title="item.name" variant="default">
              <template #header>
                <div class="item-header">
                  <span class="item-name">{{ item.name }}</span>
                  <a-tag :color="item.type === 'plugin' ? 'blue' : 'purple'">{{ item.type }}</a-tag>
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
                    :loading="installingId === item.id"
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
          <a-empty v-if="!items.length && !loading" :description="t('common.noData')" />
        </a-spin>
      </a-tab-pane>

      <!-- Installed tab -->
      <a-tab-pane key="installed" :tab="t('marketplace.installed')">
        <a-spin :spinning="loading">
          <div class="items-grid">
            <GlassCard v-for="item in installedItems" :key="item.id" :title="item.name" variant="default">
              <template #header>
                <div class="item-header">
                  <span class="item-name">{{ item.name }}</span>
                  <a-tag color="green">{{ t('marketplace.installed') }}</a-tag>
                </div>
              </template>
              <p class="item-desc">{{ item.description }}</p>
              <template #footer>
                <div class="item-actions">
                  <a-switch :checked="item.enabled" size="small" @change="(val: boolean) => toggleItem(item.id, val)" />
                  <GlassButton variant="danger" size="sm" @click="uninstallItem(item.id)">
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()

const activeTab = ref('browse')
const loading = ref(false)
const installingId = ref<string | null>(null)
const searchQuery = ref('')
const items = ref<any[]>([])
const installedItems = ref<any[]>([])
const showDetail = ref(false)
const detailItem = ref<any>(null)

const fetchMarketplace = async () => {
  loading.value = true
  try {
    const params: any = {}
    if (searchQuery.value) params.search = searchQuery.value

    if (activeTab.value === 'browse') {
      const [pluginRes, skillRes]: any[] = await Promise.all([
        request.get('/plugins/market', { params }),
        request.get('/marketplace/skills', { params }),
      ])
      const plugins = pluginRes?.data ?? pluginRes ?? []
      const skills = skillRes?.data ?? skillRes ?? []
      items.value = [...(Array.isArray(plugins) ? plugins : plugins.items ?? []), ...(Array.isArray(skills) ? skills : skills.items ?? [])]
    } else {
      const res: any = await request.get('/marketplace/installed', { params })
      installedItems.value = res?.data ?? res ?? []
    }
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const installItem = async (item: any) => {
  installingId.value = item.id
  try {
    await request.post('/marketplace/install', { id: item.id, type: item.type })
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
    await request.post('/marketplace/uninstall', { id })
    message.success(t('common.success'))
    installedItems.value = installedItems.value.filter(i => i.id !== id)
  } catch {
    message.error(t('common.error'))
  }
}

const toggleItem = async (id: string, enabled: boolean) => {
  try {
    await request.put(`/marketplace/installed/${id}`, { enabled })
    const item = installedItems.value.find(i => i.id === id)
    if (item) item.enabled = enabled
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  }
}

const viewDetails = (item: any) => {
  detailItem.value = item
  showDetail.value = true
}

onMounted(fetchMarketplace)
</script>

<style scoped>
.marketplace-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
.items-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.item-header { display: flex; justify-content: space-between; align-items: center; }
.item-name { font-weight: 600; color: var(--nr-text-primary); }
.item-body { display: flex; flex-direction: column; gap: 8px; }
.item-desc { font-size: 13px; color: var(--nr-text-secondary); margin: 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.item-meta { display: flex; align-items: center; gap: 12px; font-size: 11px; color: var(--nr-text-muted); }
.item-author { font-weight: 500; }
.item-version { font-family: var(--nr-font-mono); }
.item-actions { display: flex; gap: 8px; align-items: center; }
.detail-content p { color: var(--nr-text-secondary); font-size: 14px; }
</style>
