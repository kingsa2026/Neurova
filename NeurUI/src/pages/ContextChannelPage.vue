<template>
  <div class="context-channel-page">
    <div class="page-header">
      <h2>{{ t('channel.sharing') }}</h2>
      <GlassButton variant="ghost" size="sm" @click="$router.back()">{{ t('common.back') }}</GlassButton>
    </div>

    <AgentPageTabs :tabs="channelTabs" />

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
import AgentPageTabs from '@/components/AgentPageTabs.vue'
import { useAgentPage } from '@/composables/useAgentPage'

const { t } = useI18n()
const { agentId } = useAgentPage()

const channelTabs = [
  { labelKey: 'nav.agentchannel', to: `/agent/${agentId.value}/channel` },
  { labelKey: 'nav.agentchannelsharing', to: `/agent/${agentId.value}/channel-sharing` },
]

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
const sharingEnabled = ref(false)

async function fetchSharings() {
  loading.value = true
  try {
    // 契约：GET /channel-sharing 返回配置信封 {code, data:{config}}；
    // 逐渠道列表在 GET /channel-sharing/available-channels 的 data.channels
    // （{type, label, description, is_shared}）。此前按数组解析该信封，
    // v-for 遍历对象导致卡片标题全空（无渠道名）。
    const [cfgRes, availRes] = await Promise.all([
      request.get('/channel-sharing') as Promise<unknown>,
      request.get('/channel-sharing/available-channels') as Promise<unknown>,
    ])
    sharingEnabled.value = !!((cfgRes as { data?: { config?: { enabled?: boolean } } })?.data?.config?.enabled)
    const channels =
      (availRes as { data?: { channels?: Array<{ type: string; label: string; is_shared: boolean }> } })?.data
        ?.channels ?? []
    channelSharings.value = channels.map((c) => ({
      channelId: c.type,
      channelName: c.label,
      type: c.type,
      sharingEnabled: c.is_shared,
    }))
  } catch { channelSharings.value = [] } finally { loading.value = false }
}

async function handleToggle(channelId: string, enabled: boolean) {
  try {
    // 逐渠道开关 = 维护 shared_channels 集合：其余已共享渠道 + 本渠道
    const others = channelSharings.value
      .filter((c) => c.channelId !== channelId && c.sharingEnabled)
      .map((c) => c.channelId)
    const next = [...others, ...(enabled ? [channelId] : [])]
    await request.post('/channel-sharing/channels', { channels: next, shared_context: sharingEnabled.value })
    await fetchSharings()
  } catch { /* handled */ }
}

async function handleTest(channelId: string) {
  testingId.value = channelId
  try {
    await request.post('/channel-sharing/test', { channel: channelId })
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
