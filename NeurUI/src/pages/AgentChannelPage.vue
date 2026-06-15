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
          :title="ch.name"
          variant="default"
          padding="18px 22px"
        >
          <div class="ch-meta">
            <a-tag color="blue">{{ ch.type }}</a-tag>
            <a-badge :status="ch.enabled ? 'processing' : 'default'" :text="ch.enabled ? t('common.active') : t('common.inactive')" />
            <span v-if="ch.lastMessage" class="meta-text">{{ ch.lastMessage }}</span>
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

async function fetchChannels() {
  loading.value = true
  try {
    const res = await listChannels()
    channels.value = res ?? []
  } catch { message.error(t('common.error')) } finally { loading.value = false }
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
.channel-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }
.ch-meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.meta-text { font-size: 12px; color: var(--nr-text-tertiary); }
.ch-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
</style>
