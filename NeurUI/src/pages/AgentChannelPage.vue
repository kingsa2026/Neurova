<template>
  <div class="nr-agent-channel">
    <div class="nr-ac-header">
      <div>
        <h2>{{ t('channel.agentChannels') }}</h2>
        <p class="nr-ac-desc">{{ t('channel.agentChannelsDesc') }}</p>
      </div>
      <a-select v-model:value="agentId" size="small" style="width: 200px"
        :options="agentSelectOptions" @change="fetchConfigs" />
    </div>

    <a-spin :spinning="loading">
      <div class="nr-ac-grid">
        <GlassCard v-for="ch in channels" :key="ch.channelKey" class="nr-ac-card" :style="{ borderColor: ch.enabled ? ch.color : undefined }">
          <div class="nr-ac-card-head">
            <img v-if="ch.iconSrc" :src="ch.iconSrc" class="nr-ac-icon" :alt="ch.name" />
            <span v-else class="nr-ac-icon emoji">{{ ch.icon }}</span>
            <div class="nr-ac-title">
              <span class="nr-ac-name">{{ ch.name }}</span>
              <a-tag :color="ch.connected ? 'green' : ch.enabled ? 'orange' : 'default'">
                {{ ch.connected ? t('channel.connected') : ch.enabled ? t('channel.enabledNotConnected') : t('common.disabled') }}
              </a-tag>
            </div>
          </div>
          <div class="nr-ac-actions">
            <GlassButton size="sm" variant="secondary" @click="openConfigModal(ch)">{{ t('channel.configure') }}</GlassButton>
            <GlassButton v-if="ch.configured" size="sm" variant="danger" @click="removeChannel(ch)">{{ t('common.delete') }}</GlassButton>
          </div>
        </GlassCard>
      </div>
    </a-spin>

    <!-- Config modal（字段表与系统页共享单一来源；负一屏复用专属组件） -->
    <a-modal v-model:open="showModal" :title="`${current?.name} · ${t('channel.configure')}`" :confirm-loading="saving"
      :footer="current?.channelKey === 'negative-screen' ? null : undefined" @ok="saveConfig">
      <NegativeScreenSettings v-if="current?.channelKey === 'negative-screen'" />
      <a-form v-else layout="vertical">
        <!-- 扫码授权（QwenPaw 两段式对齐）：飞书/钉钉/QQ/微信——扫码即取凭据回填表单 -->
        <QrcodeAuthBlock
          v-if="currentQrcodeMeta"
          :key="'qr-' + current?.channelKey"
          :channel="currentQrcodeMeta.channel"
          :label="t('channel.scanAuth')"
          :button-text="t('channel.getQrcode')"
          :hint-text="t('channel.scanHint')"
          :success-status="currentQrcodeMeta.successStatus"
          :success-credential-key="currentQrcodeMeta.successCredentialKey"
          :poll-interval="currentQrcodeMeta.pollInterval"
          :poll-timeout="currentQrcodeMeta.pollTimeout"
          :max-poll-count="currentQrcodeMeta.maxPollCount"
          :params="qrcodeParams"
          @success="onQrSuccess"
          @error="onQrError"
        />
        <a-form-item :label="t('common.enable')">
          <a-switch v-model:checked="form.enabled" />
        </a-form-item>
        <template v-for="field in allFields" :key="field.key">
          <a-form-item :label="field.label" :required="field.required">
            <a-switch v-if="field.type === 'toggle'" v-model:checked="form.values[field.key]" />
            <a-select v-else-if="field.type === 'select'" v-model:value="form.values[field.key]" style="width: 100%"
              :options="field.options" />
            <a-input-number v-else-if="field.type === 'number'" v-model:value="form.values[field.key]" style="width: 100%" />
            <a-input v-else :value="form.values[field.key]" :type="field.type === 'password' ? 'password' : 'text'"
              :placeholder="field.placeholder || ''" @update:value="(v: string) => form.values[field.key] = v" />
          </a-form-item>
        </template>
      </a-form>
    </a-modal>

    <WechatQrcodeDialog v-model:visible="qrVisible" :qr-url="qr.url" :qr-id="qr.qrId" @confirmed="onQrConfirmed" />
  </div>
</template>

<script setup lang="ts">
/**
 * Agent 渠道页（2026-09-13 agent 隔离 Phase C 重建）。
 *
 * 历史：本页原挂在死壳 /v1/channels 上（后端假桥，GET 恒 []），随死壳一并删除；
 * 现按"渠道必须按 agent 隔离"重建——数据源切真集 /v1/channel-configs 的
 * agent 维度（多实例：同一平台不同 agent 各配各的 bot），字段表与系统渠道
 * 管理页共享 config/channelFields.ts 单一来源。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import WechatQrcodeDialog from '@/components/WechatQrcodeDialog.vue'
import {
  listChannelConfigs, createChannelConfig, deleteChannelConfig,
  createWechatIlinkQrcode,
} from '@/api/modules/channel-configs'
import {
  buildChannelCatalog, buildChannelFieldsMap, buildCommonFields,
  QRCODE_CHANNELS,
  type FieldSchema, type ChannelCatalogItem,
} from '@/config/channelFields'
import QrcodeAuthBlock from '@/components/QrcodeAuthBlock.vue'
import NegativeScreenSettings from '@/components/NegativeScreenSettings.vue'
import { useAgentStore } from '@/stores/agents'

const { t } = useI18n()
const route = useRoute()
const agentStore = useAgentStore()

interface AgentChannel extends ChannelCatalogItem {
  configured: boolean
}

const routeAgentId = String(route.params.agentId || '')
const agentId = ref(routeAgentId || 'default')
const loading = ref(false)
const saving = ref(false)
const showModal = ref(false)
const current = ref<AgentChannel | null>(null)
const qrVisible = ref(false)
const qr = reactive({ url: '', qrId: '' })
const form = reactive<{ enabled: boolean; values: Record<string, any> }>({ enabled: true, values: {} })
const savedExtras = ref<Record<string, Record<string, unknown>>>({})

const channels = ref<AgentChannel[]>([])
const commonFields = computed<FieldSchema[]>(() => buildCommonFields(t))
const channelFieldsMap = computed<Record<string, FieldSchema[]>>(() => buildChannelFieldsMap(t))

const allFields = computed<FieldSchema[]>(() => {
  if (!current.value) return []
  return [...commonFields.value, ...(channelFieldsMap.value[current.value.channelKey] || [])]
})

const agentSelectOptions = computed(() => [
  { value: 'default', label: t('channel.defaultAgent') },
  ...agentStore.agentOptions.map((o: any) => ({ value: o.id, label: o.name })),
])

function baseCatalog(): AgentChannel[] {
  // NV 独有渠道：鸿蒙负一屏推送（Phase C 换共享目录时只加在系统页，
  // Agent 页一并恢复——用户级配置，打开即复用 NegativeScreenSettings）
  return [...buildChannelCatalog(t), NEG_SCREEN_CARD].map((c) => ({ ...c, configured: false }))
}

// ─── NV 独有·负一屏推送卡（backendType='' → 不参与平台配置行匹配）───
const NEG_SCREEN_CARD: ChannelCatalogItem = { name: t('settings.negativeScreen'), icon: '📲', type: 'builtin', enabled: false, color: '#e11d48', channelKey: 'negative-screen', backendType: '', connected: false }

// ─── QwenPaw 对齐·通用扫码授权（飞书/钉钉/QQ/微信）────────────────────────
const currentQrcodeMeta = computed(() =>
  current.value ? QRCODE_CHANNELS[current.value.channelKey] : undefined,
)
const qrcodeParams = computed<Record<string, string>>(() => {
  const meta = currentQrcodeMeta.value
  const p: Record<string, string> = {}
  for (const key of meta?.paramsFromForm || []) {
    if (form.values[key]) p[key] = String(form.values[key])
  }
  return p
})
function onQrSuccess(credentials: Record<string, string>) {
  const meta = currentQrcodeMeta.value
  if (!meta) return
  // 凭据按渠道映射回填表单键（如钉钉 client_id→app_id）
  for (const [credKey, formKey] of Object.entries(meta.credentialToForm)) {
    if (credentials[credKey]) form.values[formKey] = credentials[credKey]
  }
  message.success(t('channel.scanAuthSuccess'))
}
function onQrError(type: 'fetch' | 'expired' | 'fail') {
  message.error(type === 'expired' ? t('channel.scanExpired') : t('channel.scanFailed'))
}

async function fetchConfigs() {
  loading.value = true
  try {
    const list: any = await listChannelConfigs(agentId.value)
    const rows: any[] = Array.isArray(list) ? list : (list?.data ?? [])
    savedExtras.value = {}
    channels.value = baseCatalog().map((c) => {
      const row = rows.find((r: any) => r.channel_type === c.backendType)
      if (row) {
        savedExtras.value[c.backendType] = row.extra ?? {}
        return { ...c, enabled: !!row.enabled, connected: !!row.connected, configured: true }
      }
      return c
    })
  } catch {
    channels.value = baseCatalog()
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

function openConfigModal(ch: AgentChannel) {
  current.value = ch
  const saved = savedExtras.value[ch.backendType] || {}
  const values: Record<string, any> = {}
  for (const f of allFieldsFor(ch)) {
    values[f.key] = saved[f.key] !== undefined ? saved[f.key]
      : (f.defaultValue !== undefined ? f.defaultValue : (f.type === 'toggle' ? false : ''))
  }
  form.values = values
  form.enabled = ch.enabled
  showModal.value = true
}

function allFieldsFor(ch: AgentChannel): FieldSchema[] {
  return [...commonFields.value, ...(channelFieldsMap.value[ch.channelKey] || [])]
}

async function saveConfig() {
  if (!current.value) return
  saving.value = true
  const extra: Record<string, any> = { ...form.values }
  try {
    const res: any = await createChannelConfig({
      channel_type: current.value.backendType,
      enabled: form.enabled,
      app_id: typeof extra.app_id === 'string' ? extra.app_id : '',
      app_secret: typeof extra.app_secret === 'string' ? extra.app_secret : '',
      use_stream: extra.use_stream !== undefined ? !!extra.use_stream : true,
      encrypt_key: typeof extra.encrypt_key === 'string' ? extra.encrypt_key : '',
      verification_token: typeof extra.verification_token === 'string' ? extra.verification_token : '',
      extra,
    }, agentId.value)
    const data = res?.data ?? res
    if (data?.needs_scan) {
      await startQrFlow(extra)
      return
    }
    message.success(t('common.success'))
    showModal.value = false
    await fetchConfigs()
  } catch (e: any) {
    // 409 等平台身份冲突透出后端原文（同 bot 已被其他 agent 配置等）
    message.error(e?.response?.data?.detail || e?.message || t('channel.configSaveFailed'))
  } finally {
    saving.value = false
  }
}

async function startQrFlow(extra: Record<string, any>) {
  try {
    const res: any = await createWechatIlinkQrcode(
      { token_file: String(extra.token_file || ''), bot_token: String(extra.bot_token || '') },
      agentId.value,
    )
    const d = res?.data ?? res
    if (d?.status === 'ready') {
      message.success(t('common.success'))
    } else if (d?.qr_url) {
      qr.url = d.qr_url
      qr.qrId = d.qr_id || ''
      qrVisible.value = true
    }
  } catch {
    message.error(t('channel.configSaveFailed'))
  }
}

function onQrConfirmed() {
  showModal.value = false
  fetchConfigs()
}

function removeChannel(ch: AgentChannel) {
  Modal.confirm({
    title: t('common.confirm'),
    content: t('channel.removeChannelConfirm', { name: ch.name }),
    okText: t('common.yes'),
    cancelText: t('common.no'),
    onOk: async () => {
      try {
        await deleteChannelConfig(ch.backendType, agentId.value)
        message.success(t('common.success'))
        await fetchConfigs()
      } catch {
        message.error(t('common.error'))
      }
    },
  })
}

onMounted(() => {
  agentStore.loadAgents?.()
  fetchConfigs()
})
</script>

<style scoped>
.nr-agent-channel { display: flex; flex-direction: column; gap: 16px; }
.nr-ac-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.nr-ac-header h2 { margin: 0; font-size: 18px; color: var(--nr-text-primary); }
.nr-ac-desc { margin: 4px 0 0; font-size: 12px; color: var(--nr-text-tertiary); }
.nr-ac-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.nr-ac-card { display: flex; flex-direction: column; gap: 12px; }
.nr-ac-card-head { display: flex; gap: 10px; align-items: center; }
.nr-ac-icon { width: 32px; height: 32px; object-fit: contain; }
.nr-ac-icon.emoji { font-size: 26px; }
.nr-ac-title { display: flex; flex-direction: column; gap: 4px; }
.nr-ac-name { font-weight: 600; color: var(--nr-text-primary); }
.nr-ac-actions { display: flex; gap: 8px; }
</style>
