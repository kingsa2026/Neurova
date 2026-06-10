<template>
  <div class="context-channel-page">
    <div class="page-header">
      <h2>{{ t('channel.sharing') }}</h2>
      <GlassButton variant="ghost" size="sm" @click="$router.back()">{{ t('common.back') }}</GlassButton>
    </div>

    <GlassPanel variant="subtle" padding="16px 20px">
      <p class="section-desc">{{ t('channel.sharing') }} - {{ t('channel.config') }}</p>
    </GlassPanel>

    <!-- Available channels -->
    <a-spin :spinning="loading">
      <a-empty v-if="!loading && channelSharings.length === 0" :description="t('common.noData')" />
      <div v-else class="sharing-list">
        <GlassCard
          v-for="item in channelSharings"
          :key="item.channelId"
          :title="item.channelName"
          variant="default"
          padding="16px 20px"
        >
          <div class="sharing-row">
            <div class="sharing-info">
              <a-tag :color="item.type">{{ item.type }}</a-tag>
              <a-badge :status="item.sharingEnabled ? 'processing' : 'default'" :text="item.sharingEnabled ? t('common.active') : t('common.inactive')" />
              <span v-if="item.lastSync" class="meta-text">{{ t('channel.session') }}: {{ item.lastSync }}</span>
            </div>
            <div class="sharing-actions">
              <a-switch :checked="item.sharingEnabled" size="small" @change="(val: boolean) => handleToggle(item.channelId, val)" />
              <GlassButton variant="secondary" size="sm" :loading="testingId === item.channelId" @click="handleTest(item.channelId)">{{ t('channel.test') }}</GlassButton>
            </div>
          </div>
        </GlassCard>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()

interface ChannelSharing {
  channelId: string
  channelName: string
  type: string
  sharingEnabled: boolean
  lastSync?: string
}

const channelSharings = ref<ChannelSharing[]>([])
const loading = ref(false)
const testingId = ref<string | null>(null)

async function fetchSharings() {
  loading.value = true
  try {
    const res = await request.get('/channel-sharing') as unknown as ChannelSharing[]
    channelSharings.value = res ?? []
  } catch { channelSharings.value = [] } finally { loading.value = false }
}

async function handleToggle(channelId: string, enabled: boolean) {
  try {
    if (enabled) {
      await request.post('/channel-sharing/enable', { channelId })
    } else {
      await request.post('/channel-sharing/disable', { channelId })
    }
    await fetchSharings()
  } catch { /* handled */ }
}

async function handleTest(channelId: string) {
  testingId.value = channelId
  try {
    await request.post('/channel-sharing/test', { channelId })
  } catch { /* handled */ } finally { testingId.value = null }
}

onMounted(fetchSharings)
</script>

<style scoped>
.context-channel-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.section-desc { color: var(--nr-text-tertiary); font-size: 13px; margin: 0; }
.sharing-list { display: flex; flex-direction: column; gap: 12px; }
.sharing-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
.sharing-info { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.meta-text { font-size: 12px; color: var(--nr-text-tertiary); }
.sharing-actions { display: flex; gap: 8px; align-items: center; }
</style>
