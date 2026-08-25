<template>
  <div class="agent-channel-page">
    <div class="page-header">
      <h2>{{ t('channel.title') }}</h2>
      <GlassButton variant="primary" size="sm" @click="openCreate">{{ t('channel.create') }}</GlassButton>
    </div>

    <!-- Channel list -->
    <a-spin :spinning="loading">
      <a-empty v-if="!loading && channels.length === 0" :description="t('common.noData')" />
      <div v-else class="channel-grid">
        <GlassCard
          v-for="ch in pagedChannels"
          :key="ch.id"
          variant="default"
          padding="18px 22px"
        >
          <div class="ch-header">
            <img v-if="ch.iconSrc" :src="ch.iconSrc" class="ch-icon" :alt="ch.name" />
            <span v-else class="ch-icon" :style="{ background: ch.color || '#6366f1' }">🔌</span>
            <div>
              <div class="ch-name">{{ ch.name }}</div>
              <a-tag color="blue">{{ ch.type }}</a-tag>
            </div>
          </div>
          <div class="ch-meta">
            <a-badge :status="ch.enabled ? 'processing' : 'default'" :text="ch.enabled ? t('common.active') : t('common.inactive')" />
          </div>
          <div class="ch-actions">
            <GlassButton variant="secondary" size="sm" :loading="testingId === ch.id" @click="handleTest(ch.id)">{{ t('channel.test') }}</GlassButton>
            <a-switch :checked="ch.enabled" size="small" @change="(val: boolean) => handleToggle(ch.id, val)" />
            <GlassButton variant="ghost" size="sm" @click="openEdit(ch)">{{ t('common.edit') }}</GlassButton>
            <a-popconfirm :title="t('common.confirm') + '?'" @confirm="handleDelete(ch.id)">
              <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
            </a-popconfirm>
          </div>
        </GlassCard>
      </div>
      <a-pagination v-if="channels.length > pageSize" v-model:current="currentPage" :pageSize="pageSize" :total="channels.length" size="small" style="margin-top: 16px; text-align: center" />
    </a-spin>

    <!-- Create/Edit modal -->
    <a-modal v-model:open="showModal" :title="editingId ? t('common.edit') : t('channel.create')" @ok="handleSave" :confirm-loading="saving" width="560px">
      <a-form layout="vertical" :rules="{ name: [{ required: true, message: t('common.required') }] }">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="form.name" :placeholder="t('common.name')" />
        </a-form-item>
        <a-form-item :label="t('common.type')">
          <a-select v-model:value="form.type" :placeholder="t('common.type')">
            <a-select-option value="telegram">{{ t('channel.telegram') }}</a-select-option>
            <a-select-option value="discord">{{ t('channel.discord') }}</a-select-option>
            <a-select-option value="slack">{{ t('channel.slack') }}</a-select-option>
            <a-select-option value="wechat">{{ t('channel.wechat') }}</a-select-option>
            <a-select-option value="dingtalk">{{ t('channel.dingtalk') }}</a-select-option>
            <a-select-option value="feishu">{{ t('channel.feishu') }}</a-select-option>
            <a-select-option value="custom">{{ t('channel.custom') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('channel.tokenApiKey')">
          <a-input v-model:value="form.token" type="password" :placeholder="t('channel.tokenApiKey')" />
        </a-form-item>
        <a-form-item :label="t('channel.webhookUrl')">
          <a-input v-model:value="form.webhookUrl" placeholder="https://..." />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-input v-model:value="form.description" type="textarea" :rows="2" :placeholder="t('common.description')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  listChannels, createChannel, updateChannel, deleteChannel, testChannel, toggleChannel,
  type Channel,
} from '@/api/modules/channels'

const { t } = useI18n()

const channels = ref<Channel[]>([])
const loading = ref(false)
const showModal = ref(false)
const saving = ref(false)
const editingId = ref<string | null>(null)
const testingId = ref<string | null>(null)
const currentPage = ref(1)
const pageSize = ref(12)

const form = reactive({ name: '', type: '', token: '', webhookUrl: '', description: '' })

const pagedChannels = computed(() =>
  channels.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value),
)

function resetForm() {
  form.name = ''
  form.type = ''
  form.token = ''
  form.webhookUrl = ''
  form.description = ''
  editingId.value = null
}

function openCreate() { resetForm(); showModal.value = true }
function openEdit(ch: Channel) {
  editingId.value = ch.id
  form.name = ch.name
  form.type = ch.type
  form.token = ch.token ?? ''
  form.webhookUrl = ch.webhookUrl ?? ''
  form.description = ch.description ?? ''
  showModal.value = true
}

// Built-in channel types for this agent
const builtInChannels = ref<{ id: string; name: string; type: string; enabled: boolean; iconSrc: string; color: string }[]>([
  { id: 'xiaoyi', name: '小艺', type: 'xiaoyi', enabled: true, iconSrc: 'https://gw.alicdn.com/imgextra/i1/O1CN01EPS9Z81OKhIEcwpCd_!!6000000001687-2-tps-476-476.png', color: '#ec4899' },
  { id: 'dingtalk', name: '钉钉', type: 'dingtalk', enabled: false, iconSrc: 'https://img.alicdn.com/imgextra/i1/O1CN01w5mzV01tFtE37wkJI_!!6000000005873-2-tps-48-48.png', color: '#2563eb' },
  { id: 'feishu', name: '飞书', type: 'feishu', enabled: false, iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN01wCpTM41LOPeyP7wKc_!!6000000001289-2-tps-48-48.png', color: '#7c3aed' },
  { id: 'discord', name: 'Discord', type: 'discord', enabled: false, iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01OsQiMO1ZYrJXp3TmX_!!6000000003207-2-tps-42-48.png', color: '#5865f2' },
  { id: 'telegram', name: 'Telegram', type: 'telegram', enabled: true, iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN013VVoKf1jsgcNn40KA_!!6000000004604-2-tps-48-48.png', color: '#0088cc' },
  { id: 'qq', name: 'QQ', type: 'qq', enabled: false, iconSrc: 'https://img.alicdn.com/imgextra/i3/O1CN01ApVkC91JeKBkQfgj9_!!6000000001053-2-tps-41-48.png', color: '#e62117' },
  { id: 'wechat', name: '微信', type: 'wechat', enabled: false, iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01ikAjLG1jhh721iEUc_!!6000000004580-2-tps-48-48.png', color: '#07c160' },
  { id: 'wecom', name: '企业微信', type: 'wecom', enabled: false, iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01oWpOyx1TPnmnrzxlq_!!6000000002375-2-tps-48-48.png', color: '#3370ff' },
  { id: 'yuanbao', name: '元宝', type: 'yuanbao', enabled: false, iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN0164yBmJ1a2AftSglge_!!6000000003271-2-tps-225-225.png', color: '#f59e0b' },
  { id: 'matrix', name: 'Matrix', type: 'matrix', enabled: false, iconSrc: 'https://img.alicdn.com/imgextra/i3/O1CN01YfEzZu1DWdqgAdqtu_!!6000000000224-2-tps-48-48.png', color: '#0dbd8b' },
  { id: 'sip', name: 'SIP', type: 'sip', enabled: false, iconSrc: 'https://gw.alicdn.com/imgextra/i1/O1CN016SJ9AO1SpA6L3j0KH_!!6000000002295-2-tps-400-400.png', color: '#64748b' },
  { id: 'mattermost', name: 'Mattermost', type: 'mattermost', enabled: false, iconSrc: 'https://gw.alicdn.com/imgextra/i2/O1CN01A2bvSh1eVig4fDBEF_!!6000000003877-2-tps-400-400.png', color: '#0058cc' },
  { id: 'mqtt', name: 'MQTT', type: 'mqtt', enabled: false, iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN014ALZcD1iBnv2GeYdE_!!6000000004375-2-tps-64-64.png', color: '#667f80' },
  { id: 'twilio', name: 'Twilio', type: 'voice', enabled: false, iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01nwY8ZK1eY0etBKDWb_!!6000000003882-2-tps-48-48.png', color: '#f22f46' },
  { id: 'onebot', name: 'OneBot', type: 'qqbot', enabled: false, iconSrc: 'https://gw.alicdn.com/imgextra/i3/O1CN01xqM0EN1oKrRiAFX3K_!!6000000005207-2-tps-400-400.png', color: '#10b981' },
  { id: 'imessage', name: 'iMessage', type: 'imessage', enabled: false, iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN01QtLiI31uAgL02USNH_!!6000000005997-2-tps-48-48.png', color: '#34aadc' },
])

async function fetchChannels() {
  loading.value = true
  try {
    const res: any = await listChannels()
    const data = res?.data ?? res ?? []
    const list = Array.isArray(data) ? data : (data?.data ?? [])
    if (list.length > 0) {
      // Merge API channels with built-in
      for (const apiCh of list) {
        const built = builtInChannels.value.find(b => b.id === apiCh.id || b.type === apiCh.type)
        if (built) {
          built.enabled = apiCh.enabled ?? built.enabled
        } else {
          builtInChannels.value.push({ id: apiCh.id, name: apiCh.name, type: apiCh.type, enabled: apiCh.enabled ?? true, iconSrc: '', color: '#6366f1' })
        }
      }
    }
    channels.value = builtInChannels.value
  } catch {
    // Still show built-in channels even if API fails
    channels.value = builtInChannels.value
  } finally { loading.value = false }
}

async function handleSave() {
  saving.value = true
  try {
    if (editingId.value) {
      await updateChannel(editingId.value, { ...form })
    } else {
      await createChannel({ ...form })
    }
    showModal.value = false
    resetForm()
    await fetchChannels()
  } catch { message.error(t('common.error')) } finally { saving.value = false }
}

async function handleTest(id: string) {
  testingId.value = id
  try {
    await testChannel(id)
  } catch { message.error(t('common.error')) } finally { testingId.value = null }
}

async function handleToggle(id: string, enabled: boolean) {
  try {
    await toggleChannel(id, enabled)
    await fetchChannels()
  } catch { message.error(t('common.error')) }
}

async function handleDelete(id: string) {
  try {
    await deleteChannel(id)
    await fetchChannels()
  } catch { message.error(t('common.error')) }
}

onMounted(fetchChannels)
</script>

<style scoped>
.agent-channel-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.channel-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.ch-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.ch-icon { width: 40px; height: 40px; border-radius: 10px; object-fit: cover; display: flex; align-items: center; justify-content: center; font-size: 20px; flex-shrink: 0; }
.ch-name { font-size: 15px; font-weight: 600; color: var(--nr-text-primary); }
.ch-meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.meta-text { font-size: 12px; color: var(--nr-text-tertiary); }
.ch-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
</style>
