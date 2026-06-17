<template>
  <div class="nr-channel-integration">
    <!-- Header -->
    <div class="nr-ci-header">
      <div class="nr-ci-title-row">
        <h2>{{ t('channel.integration') }}</h2>
      </div>
      <p class="nr-ci-desc">{{ t('channel.integrationDesc') }}</p>
    </div>

    <!-- Tabs + Search -->
    <div class="nr-ci-toolbar">
      <div class="nr-ci-tabs">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="nr-ci-tab"
          :class="{ active: activeTab === tab.key }"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>
      <div class="nr-ci-search">
        <GlassInput
          v-model:model-value="search"
          :placeholder="t('common.search')"
          @update:model-value="search = $event"
        />
      </div>
    </div>

    <!-- Channel Grid -->
    <a-spin :spinning="loadingConfigs">
    <div v-if="filteredChannels.length > 0" class="nr-ci-grid">
      <GlassCard
        v-for="ch in filteredChannels"
        :key="ch.channelKey"
        variant="default"
        padding="0"
      >
        <div class="nr-ci-card">
          <div class="nr-ci-card-body">
            <div class="nr-ci-icon" :style="ch.iconSrc ? {} : { background: ch.color }">
              <img v-if="ch.iconSrc" :src="ch.iconSrc" :alt="ch.name" class="nr-ci-icon-img" />
              <span v-else>{{ ch.icon }}</span>
            </div>
            <div class="nr-ci-info">
              <span class="nr-ci-name">{{ ch.name }}</span>
              <div class="nr-ci-meta">
                <span class="nr-ci-type-badge" :class="ch.type">{{ ch.type === 'builtin' ? t('channel.builtin') : t('channel.customChannel') }}</span>
                <span v-if="ch.connected" class="nr-ci-conn-badge connected">{{ t('channel.connected') }}</span>
              </div>
            </div>
            <div class="nr-ci-status">
              <span class="nr-ci-status-dot" :class="{ enabled: ch.enabled }" />
              <span class="nr-ci-status-text">{{ ch.enabled ? t('channel.enabled') : t('channel.disabled') }}</span>
            </div>
          </div>
          <div class="nr-ci-card-actions">
            <GlassButton
              :variant="ch.enabled ? 'ghost' : 'primary'"
              size="sm"
              @click="toggleChannel(ch)"
            >
              {{ ch.enabled ? t('channel.disabled') : t('channel.enable') }}
            </GlassButton>
            <GlassButton variant="secondary" size="sm" @click="openConfigModal(ch)">
              {{ t('channel.configure') }}
            </GlassButton>
            <GlassButton variant="secondary" size="sm" @click="testChannel(ch)">
              {{ t('channel.test') }}
            </GlassButton>
          </div>
        </div>
      </GlassCard>
    </div>
    <a-empty v-else :description="t('channel.noChannels')" />
    </a-spin>

    <!-- Toast notification -->
    <Teleport to="body">
      <div v-if="toastMessage" class="nr-ci-toast">{{ toastMessage }}</div>
    </Teleport>

    <!-- Config Modal -->
    <Teleport to="body">
      <div v-if="showConfigModal" class="nr-ci-modal-backdrop" @click.self="closeConfigModal">
        <div class="nr-ci-modal">
          <!-- Modal Header -->
          <div class="nr-ci-modal-header">
            <div class="nr-ci-modal-title">
              <div class="nr-ci-modal-icon" :style="currentChannel?.iconSrc ? {} : { background: currentChannel?.color }">
                <img v-if="currentChannel?.iconSrc" :src="currentChannel.iconSrc" :alt="currentChannel.name" class="nr-ci-icon-img" />
                <span v-else>{{ currentChannel?.icon }}</span>
              </div>
              <div>
                <h3>{{ currentChannel?.name }}</h3>
                <p>{{ t('channel.configureDesc') }}</p>
              </div>
            </div>
            <button class="nr-ci-modal-close" @click="closeConfigModal">&times;</button>
          </div>

          <!-- Modal Body -->
          <div class="nr-ci-modal-body">
            <!-- Common Settings -->
            <div class="nr-ci-section">
              <div class="nr-ci-section-title">{{ t('channel.commonSettings') }}</div>
              <div class="nr-ci-fields">
                <div v-for="field in commonFields" :key="field.key" class="nr-ci-field" :class="field.type">
                  <label class="nr-ci-label">{{ field.label }}</label>
                  <template v-if="field.type === 'toggle'">
                    <button
                      class="nr-ci-toggle"
                      :class="{ active: configForm[field.key] }"
                      @click="configForm[field.key] = !configForm[field.key]"
                    >
                      <span class="nr-ci-toggle-thumb" />
                    </button>
                  </template>
                  <template v-else-if="field.type === 'select'">
                    <select v-model="configForm[field.key]" class="nr-ci-select">
                      <option v-for="opt in field.options" :key="opt.value" :value="opt.value">
                        {{ opt.label }}
                      </option>
                    </select>
                  </template>
                  <template v-else>
                    <input
                      v-model="configForm[field.key]"
                      :type="field.inputType || 'text'"
                      :placeholder="field.placeholder"
                      class="nr-ci-input"
                    />
                  </template>
                </div>
              </div>
            </div>

            <!-- Platform Settings -->
            <div v-if="currentChannelFields.length > 0" class="nr-ci-section">
              <div class="nr-ci-section-title">{{ t('channel.platformSettings') }}</div>
              <div class="nr-ci-fields">
                <div v-for="field in currentChannelFields" :key="field.key" class="nr-ci-field" :class="field.type">
                  <label class="nr-ci-label">
                    {{ field.label }}
                    <span v-if="field.required" class="nr-ci-required">*</span>
                  </label>
                  <template v-if="field.type === 'toggle'">
                    <button
                      class="nr-ci-toggle"
                      :class="{ active: configForm[field.key] }"
                      @click="configForm[field.key] = !configForm[field.key]"
                    >
                      <span class="nr-ci-toggle-thumb" />
                    </button>
                  </template>
                  <template v-else-if="field.type === 'select'">
                    <select v-model="configForm[field.key]" class="nr-ci-select">
                      <option v-for="opt in field.options" :key="opt.value" :value="opt.value">
                        {{ opt.label }}
                      </option>
                    </select>
                  </template>
                  <template v-else-if="field.type === 'number'">
                    <input
                      v-model.number="configForm[field.key]"
                      type="number"
                      :placeholder="field.placeholder"
                      class="nr-ci-input"
                    />
                  </template>
                  <template v-else>
                    <input
                      v-model="configForm[field.key]"
                      :type="field.inputType || 'text'"
                      :placeholder="field.placeholder"
                      class="nr-ci-input"
                    />
                  </template>
                </div>
              </div>
            </div>
          </div>

          <!-- Modal Footer -->
          <div class="nr-ci-modal-footer">
            <GlassButton variant="ghost" @click="closeConfigModal">{{ t('common.cancel') }}</GlassButton>
            <GlassButton variant="primary" :loading="saving" @click="saveConfig">{{ t('common.save') }}</GlassButton>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { listChannelConfigs, createChannelConfig, testChannelConfig } from '@/api/modules/channel-configs'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import GlassInput from '@/components/GlassInput.vue'

const { t } = useI18n()

// ─── Types ───
interface FieldSchema {
  key: string
  label: string
  type: 'text' | 'password' | 'toggle' | 'select' | 'number'
  placeholder?: string
  required?: boolean
  defaultValue?: any
  options?: { value: string; label: string }[]
  inputType?: string
}

interface ChannelItem {
  name: string
  icon: string
  iconSrc?: string
  type: 'builtin' | 'custom'
  enabled: boolean
  color: string
  channelKey: string
  backendType: string
  connected: boolean
}

// ─── Common config fields (all channels) ───
const commonFields = computed<FieldSchema[]>(() => [
  { key: 'bot_prefix', label: 'Bot Prefix', type: 'text', placeholder: '@bot', defaultValue: '@bot' },
  { key: 'show_tool_messages', label: t('nav.showToolMessages'), type: 'toggle', defaultValue: false },
  { key: 'show_thinking', label: t('nav.showThinking'), type: 'toggle', defaultValue: false },
  { key: 'stream_mode', label: t('nav.streamMode'), type: 'toggle', defaultValue: true },
  { key: 'private_chat_strategy', label: t('nav.privateChatStrategy'), type: 'select', defaultValue: 'open', options: [
    { value: 'open', label: t('nav.open') }, { value: 'closed', label: t('nav.closed') }, { value: 'whitelist', label: t('nav.whitelist') },
  ]},
  { key: 'group_chat_strategy', label: t('nav.groupChatStrategy'), type: 'select', defaultValue: 'open', options: [
    { value: 'open', label: t('nav.open') }, { value: 'closed', label: t('nav.closed') }, { value: 'whitelist', label: t('nav.whitelist') },
  ]},
  { key: 'require_mention', label: t('nav.requireMention'), type: 'toggle', defaultValue: false },
])

// ─── Channel-specific fields ───
const channelFieldsMap = computed<Record<string, FieldSchema[]>>(() => ({
  xiaoyi: [
    { key: 'access_key', label: 'Access Key', type: 'text', required: true },
    { key: 'secret_key', label: 'Secret Key', type: 'password', required: true },
    { key: 'agent_id', label: 'Agent ID', type: 'text', required: true },
    { key: 'ws_url', label: 'WebSocket URL', type: 'text', placeholder: 'wss://hag.cloud.huawei.com/openclaw/v1/ws/link' },
  ],
  dingtalk: [
    { key: 'app_id', label: 'Client ID', type: 'text', required: true, placeholder: t('nav.dingtalkAppKey') },
    { key: 'app_secret', label: 'Client Secret', type: 'password', required: true, placeholder: t('nav.dingtalkAppSecret') },
    { key: 'use_stream', label: t('nav.streamMode'), type: 'toggle', defaultValue: true },
    { key: 'reply_at_sender', label: t('nav.replyAtSender'), type: 'toggle', defaultValue: false },
  ],
  feishu: [
    { key: 'app_id', label: 'App ID', type: 'text', required: true },
    { key: 'app_secret', label: 'App Secret', type: 'password', required: true },
    { key: 'encrypt_key', label: 'Encrypt Key', type: 'password' },
    { key: 'verification_token', label: 'Verification Token', type: 'password' },
    { key: 'region', label: t('nav.region'), type: 'select', defaultValue: 'feishu', options: [
      { value: 'feishu', label: t('nav.feishuChina') }, { value: 'lark', label: t('nav.larkInternational') },
    ]},
    { key: 'media_directory', label: t('nav.mediaDirectory'), type: 'text', placeholder: './media' },
    { key: 'group_share_session', label: t('nav.groupShareSession'), type: 'toggle', defaultValue: false },
  ],
  discord: [
    { key: 'bot_token', label: 'Bot Token', type: 'password', required: true },
    { key: 'http_proxy', label: 'HTTP Proxy', type: 'text', placeholder: 'http://127.0.0.1:7890' },
    { key: 'http_proxy_auth', label: 'HTTP Proxy Auth', type: 'text', placeholder: 'user:pass' },
    { key: 'receive_bot_messages', label: t('nav.receiveBotMessages'), type: 'toggle', defaultValue: false },
  ],
  telegram: [
    { key: 'bot_token', label: 'Bot Token', type: 'password', required: true, placeholder: '123456:ABC-DEF...' },
    { key: 'http_proxy', label: 'HTTP Proxy', type: 'text', placeholder: 'http://127.0.0.1:7890' },
    { key: 'http_proxy_auth', label: 'HTTP Proxy Auth', type: 'text' },
    { key: 'show_typing', label: 'Show Typing', type: 'toggle', defaultValue: true },
  ],
  qq: [
    { key: 'app_id', label: 'App ID', type: 'text', required: true },
    { key: 'client_secret', label: 'Client Secret', type: 'password', required: true },
    { key: 'instant_confirm', label: t('nav.instantConfirm'), type: 'toggle', defaultValue: false },
  ],
  wechat: [
    { key: 'bot_token', label: 'Bot Token', type: 'password', required: true },
    { key: 'token_file', label: t('nav.tokenFile'), type: 'text', placeholder: './token.json' },
    { key: 'media_directory', label: t('nav.mediaDirectory'), type: 'text', placeholder: './media' },
    { key: 'message_merge', label: t('nav.messageMerge'), type: 'toggle', defaultValue: false },
  ],
  wecom: [
    { key: 'app_id', label: 'Bot ID (CorpID)', type: 'text', required: true },
    { key: 'app_secret', label: 'Secret', type: 'password', required: true },
    { key: 'media_directory', label: t('nav.mediaDirectory'), type: 'text', placeholder: './media' },
    { key: 'welcome_message', label: t('nav.welcomeMessage'), type: 'text', placeholder: 'Hello! I am Neurova' },
    { key: 'group_share_session', label: t('nav.groupShareSession'), type: 'toggle', defaultValue: false },
  ],
  yuanbao: [
    { key: 'app_id', label: 'App ID', type: 'text', required: true },
    { key: 'app_secret', label: 'App Secret', type: 'password', required: true },
    { key: 'api_domain', label: 'API Domain', type: 'text', placeholder: 'https://api.yuanbao.com' },
    { key: 'media_directory', label: t('nav.mediaDirectory'), type: 'text', placeholder: './media' },
  ],
  matrix: [
    { key: 'homeserver_url', label: 'Homeserver URL', type: 'text', required: true, placeholder: 'https://matrix.org' },
    { key: 'user_id', label: 'User ID', type: 'text', required: true, placeholder: '@bot:matrix.org' },
    { key: 'access_token', label: 'Access Token', type: 'password', required: true },
    { key: 'device_name', label: 'Device Name', type: 'text', placeholder: 'Neurova' },
    { key: 'disable_dm', label: t('nav.disableDm'), type: 'toggle', defaultValue: false },
    { key: 'disable_group', label: t('nav.disableGroup'), type: 'toggle', defaultValue: false },
  ],
  sip: [
    { key: 'sip_mode', label: 'SIP Mode', type: 'select', defaultValue: 'dev', options: [
      { value: 'dev', label: 'Development (pyVoIP)' }, { value: 'production', label: 'Production (LiveKit)' },
    ]},
    { key: 'sip_server', label: 'SIP Server', type: 'text' },
    { key: 'sip_username', label: 'SIP Username', type: 'text', required: true },
    { key: 'sip_password', label: 'SIP Password', type: 'password', required: true },
    { key: 'sip_port', label: 'SIP Port', type: 'number', defaultValue: 5061 },
    { key: 'transport_protocol', label: 'Transport Protocol', type: 'select', defaultValue: 'UDP', options: [
      { value: 'UDP', label: 'UDP' }, { value: 'TCP', label: 'TCP' }, { value: 'TLS', label: 'TLS' },
    ]},
    { key: 'dashscope_api_key', label: 'DashScope API Key', type: 'password' },
    { key: 'tts_provider', label: 'TTS Provider', type: 'text' },
    { key: 'tts_language', label: 'TTS Language', type: 'text', placeholder: 'zh-CN' },
    { key: 'stt_provider', label: 'STT Provider', type: 'text' },
  ],
  mattermost: [
    { key: 'mattermost_url', label: 'Mattermost URL', type: 'text', required: true, placeholder: 'https://mattermost.example.com' },
    { key: 'bot_token', label: 'Bot Token', type: 'password', required: true },
    { key: 'media_directory', label: '媒体文件目录', type: 'text', placeholder: './media' },
    { key: 'show_typing', label: 'Show Typing', type: 'toggle', defaultValue: true },
    { key: 'thread_follow_without_mention', label: 'Thread Follow Without Mention', type: 'toggle', defaultValue: false },
  ],
  mqtt: [
    { key: 'host', label: 'MQTT Host', type: 'text', defaultValue: '127.0.0.1' },
    { key: 'port', label: 'Port', type: 'number', defaultValue: 1883 },
    { key: 'username', label: 'Username', type: 'text' },
    { key: 'password', label: 'Password', type: 'password' },
    { key: 'subscribe_topic', label: 'Subscribe Topic', type: 'text', placeholder: 'server/+/up' },
  ],
  twilio: [
    { key: 'app_id', label: 'Account SID', type: 'text', required: true },
    { key: 'app_secret', label: 'Auth Token', type: 'password', required: true },
    { key: 'from_number', label: 'Phone Number', type: 'text', required: true, placeholder: '+1234567890' },
  ],
  onebot: [
    { key: 'access_token', label: 'Access Token', type: 'password', required: true },
    { key: 'http_api_url', label: 'HTTP API URL', type: 'text', defaultValue: 'http://127.0.0.1:3000' },
    { key: 'ws_api_url', label: 'WS API URL', type: 'text', defaultValue: 'ws://127.0.0.1:3001' },
    { key: 'media_directory', label: t('nav.mediaDirectory'), type: 'text', placeholder: './media' },
  ],
}))

// ─── Channel definitions ───
const channels = ref<ChannelItem[]>([
  { name: 'Console', icon: '🖥', type: 'builtin', enabled: true, color: '#6366f1', channelKey: 'console', backendType: 'api', connected: false },
  { name: '小艺', icon: '', iconSrc: 'https://gw.alicdn.com/imgextra/i1/O1CN01EPS9Z81OKhIEcwpCd_!!6000000001687-2-tps-476-476.png', type: 'builtin', enabled: true, color: '#ec4899', channelKey: 'xiaoyi', backendType: 'xiaoyi', connected: false },
  { name: '钉钉', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i1/O1CN01w5mzV01tFtE37wkJI_!!6000000005873-2-tps-48-48.png', type: 'builtin', enabled: false, color: '#2563eb', channelKey: 'dingtalk', backendType: 'dingtalk', connected: false },
  { name: '飞书', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN01wCpTM41LOPeyP7wKc_!!6000000001289-2-tps-48-48.png', type: 'builtin', enabled: true, color: '#7c3aed', channelKey: 'feishu', backendType: 'feishu', connected: false },
  { name: 'Discord', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01OsQiMO1ZYrJXp3TmX_!!6000000003207-2-tps-42-48.png', type: 'builtin', enabled: false, color: '#5865f2', channelKey: 'discord', backendType: 'discord', connected: false },
  { name: 'Telegram', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN013VVoKf1jsgcNn40KA_!!6000000004604-2-tps-48-48.png', type: 'builtin', enabled: true, color: '#0088cc', channelKey: 'telegram', backendType: 'telegram', connected: false },
  { name: 'QQ', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i3/O1CN01ApVkC91JeKBkQfgj9_!!6000000001053-2-tps-41-48.png', type: 'builtin', enabled: false, color: '#e62117', channelKey: 'qq', backendType: 'qq', connected: false },
  { name: '微信', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01ikAjLG1jhh721iEUc_!!6000000004580-2-tps-48-48.png', type: 'builtin', enabled: false, color: '#07c160', channelKey: 'wechat', backendType: 'wechat', connected: false },
  { name: '企业微信', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01oWpOyx1TPnmnrzxlq_!!6000000002375-2-tps-48-48.png', type: 'builtin', enabled: false, color: '#3370ff', channelKey: 'wecom', backendType: 'wecom', connected: false },
  { name: '元宝', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN0164yBmJ1a2AftSglge_!!6000000003271-2-tps-225-225.png', type: 'builtin', enabled: false, color: '#f59e0b', channelKey: 'yuanbao', backendType: 'yuanbao', connected: false },
  { name: 'Matrix', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i3/O1CN01YfEzZu1DWdqgAdqtu_!!6000000000224-2-tps-48-48.png', type: 'builtin', enabled: false, color: '#0dbd8b', channelKey: 'matrix', backendType: 'matrix', connected: false },
  { name: 'SIP', icon: '', iconSrc: 'https://gw.alicdn.com/imgextra/i1/O1CN016SJ9AO1SpA6L3j0KH_!!6000000002295-2-tps-400-400.png', type: 'builtin', enabled: false, color: '#64748b', channelKey: 'sip', backendType: 'sip', connected: false },
  { name: 'Mattermost', icon: '', iconSrc: 'https://gw.alicdn.com/imgextra/i2/O1CN01A2bvSh1eVig4fDBEF_!!6000000003877-2-tps-400-400.png', type: 'builtin', enabled: false, color: '#0058cc', channelKey: 'mattermost', backendType: 'mattermost', connected: false },
  { name: 'MQTT', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN014ALZcD1iBnv2GeYdE_!!6000000004375-2-tps-64-64.png', type: 'builtin', enabled: false, color: '#667f80', channelKey: 'mqtt', backendType: 'mqtt', connected: false },
  { name: 'Twilio', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01nwY8ZK1eY0etBKDWb_!!6000000003882-2-tps-48-48.png', type: 'builtin', enabled: false, color: '#f22f46', channelKey: 'twilio', backendType: 'voice', connected: false },
  { name: 'OneBot', icon: '', iconSrc: 'https://gw.alicdn.com/imgextra/i3/O1CN01xqM0EN1oKrRiAFX3K_!!6000000005207-2-tps-400-400.png', type: 'builtin', enabled: false, color: '#10b981', channelKey: 'onebot', backendType: 'qqbot', connected: false },
  { name: 'iMessage', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN01QtLiI31uAgL02USNH_!!6000000005997-2-tps-48-48.png', type: 'builtin', enabled: false, color: '#34aadc', channelKey: 'imessage', backendType: 'imessage', connected: false },
])

// ─── State ───
const search = ref('')
const activeTab = ref<'all' | 'builtin' | 'custom'>('all')
const showConfigModal = ref(false)
const currentChannel = ref<ChannelItem | null>(null)
const configForm = reactive<Record<string, any>>({})
const saving = ref(false)
const loadingConfigs = ref(false)
const testingChannel = ref<string | null>(null)
const toastMessage = ref('')

// ─── Helpers ───
function openConfigModal(ch: ChannelItem) {
  currentChannel.value = ch
  const defaults: Record<string, any> = {
    enabled: ch.enabled,
    bot_prefix: '@bot',
    show_tool_messages: false,
    show_thinking: false,
    stream_mode: true,
    private_chat_strategy: 'open',
    group_chat_strategy: 'open',
    require_mention: false,
  }
  const specificFields = channelFieldsMap.value[ch.channelKey] || []
  specificFields.forEach((f) => {
    if (f.defaultValue !== undefined) defaults[f.key] = f.defaultValue
  })
  Object.keys(configForm).forEach((k) => delete configForm[k])
  Object.assign(configForm, defaults)
  showConfigModal.value = true
}

function closeConfigModal() {
  showConfigModal.value = false
  currentChannel.value = null
}

function toggleChannel(ch: ChannelItem) {
  ch.enabled = !ch.enabled
}

async function loadConfigs() {
  loadingConfigs.value = true
  try {
    const data: any = await listChannelConfigs()
    if (Array.isArray(data)) {
      data.forEach((cfg: any) => {
        const ch = channels.value.find((c) => c.backendType === cfg.channel_type)
        if (ch) {
          ch.enabled = cfg.enabled
          ch.connected = cfg.connected || false
        }
      })
    }
  } catch (e) {
    message.error(t('common.error'))
  } finally {
    loadingConfigs.value = false
  }
}

async function saveConfig() {
  if (!currentChannel.value) return
  saving.value = true
  const ch = currentChannel.value
  try {
    const commonKeys = ['bot_prefix', 'show_tool_messages', 'show_thinking', 'stream_mode', 'private_chat_strategy', 'group_chat_strategy', 'require_mention']
    const extra: Record<string, any> = {}
    Object.keys(configForm).forEach((key) => {
      if (!commonKeys.includes(key) && key !== 'enabled') {
        extra[key] = configForm[key]
      }
    })

    const payload = {
      channel_type: ch.backendType,
      enabled: configForm.enabled !== false,
      app_id: extra.app_id || '',
      app_secret: extra.app_secret || '',
      use_stream: configForm.stream_mode ?? true,
      webhook_url: '',
      webhook_token: '',
      encrypt_key: extra.encrypt_key || '',
      verification_token: extra.verification_token || '',
      extra,
    }

    await createChannelConfig(payload as any)

    ch.enabled = payload.enabled
    showToast(t('channel.configSaved'))
    closeConfigModal()
  } catch (e: any) {
    console.error('Save config error:', e)
    showToast(e?.message || t('channel.configSaveFailed'))
  } finally {
    saving.value = false
  }
}

async function testChannel(ch: ChannelItem) {
  testingChannel.value = ch.channelKey
  try {
    const payload: Record<string, any> = {
      channel_type: ch.backendType,
      enabled: true,
      app_id: '',
      app_secret: '',
      use_stream: true,
      webhook_url: '',
      webhook_token: '',
      encrypt_key: '',
      verification_token: '',
      extra: {},
    }
    const result: any = await testChannelConfig(ch.backendType, payload as any)
    showToast(result?.success ? t('channel.testSuccess') : t('channel.testFailed'))
  } catch (e: any) {
    showToast(t('channel.testFailed'))
  } finally {
    testingChannel.value = null
  }
}

function showToast(msg: string) {
  toastMessage.value = msg
  setTimeout(() => { toastMessage.value = '' }, 3000)
}

// ─── Computed ───
const currentChannelFields = computed(() => {
  if (!currentChannel.value) return []
  return channelFieldsMap.value[currentChannel.value.channelKey] || []
})

const filteredChannels = computed(() => {
  let list = channels.value
  if (activeTab.value !== 'all') {
    list = list.filter((ch) => ch.type === activeTab.value)
  }
  if (search.value) {
    const q = search.value.toLowerCase()
    list = list.filter((ch) => ch.name.toLowerCase().includes(q))
  }
  return list
})

const tabs = computed(() => [
  { key: 'all' as const, label: t('channel.all') },
  { key: 'builtin' as const, label: t('channel.builtin') },
  { key: 'custom' as const, label: t('channel.customChannel') },
])

onMounted(() => { search.value = ''; loadConfigs() })
</script>

<style scoped>
.nr-channel-integration {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.nr-ci-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nr-ci-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.nr-ci-title-row h2 {
  color: var(--nr-text-primary);
  font-family: var(--nr-font-display);
  font-weight: 700;
  font-size: 22px;
  margin: 0;
}

.nr-ci-desc {
  color: var(--nr-text-tertiary);
  font-size: 14px;
  margin: 0;
}

.nr-ci-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.nr-ci-tabs {
  display: flex;
  gap: 4px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 10px;
  padding: 3px;
}

.nr-ci-tab {
  padding: 6px 18px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--nr-text-secondary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.nr-ci-tab:hover {
  color: var(--nr-text-primary);
  background: rgba(255, 255, 255, 0.04);
}

.nr-ci-tab.active {
  background: var(--nr-primary);
  color: white;
}

.nr-ci-search {
  width: 220px;
}

/* Card Grid */
.nr-ci-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.nr-ci-card {
  display: flex;
  flex-direction: column;
}

.nr-ci-card-body {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px 12px;
}

.nr-ci-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 16px;
  font-weight: 700;
  flex-shrink: 0;
  letter-spacing: -0.02em;
  overflow: hidden;
}

.nr-ci-icon-img {
  width: 28px;
  height: 28px;
  object-fit: contain;
  border-radius: 4px;
}

.nr-ci-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.nr-ci-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--nr-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nr-ci-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.nr-ci-type-badge {
  font-size: 11px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 4px;
  align-self: flex-start;
}

.nr-ci-type-badge.builtin {
  background: rgba(99, 102, 241, 0.12);
  color: var(--nr-primary-light);
}

.nr-ci-type-badge.custom {
  background: rgba(245, 158, 11, 0.12);
  color: var(--nr-warning);
}

.nr-ci-conn-badge {
  font-size: 10px;
  font-weight: 500;
  padding: 1px 5px;
  border-radius: 3px;
}

.nr-ci-conn-badge.connected {
  background: rgba(34, 197, 94, 0.12);
  color: var(--nr-success);
}

.nr-ci-status {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.nr-ci-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.15);
  transition: background 0.2s;
}

.nr-ci-status-dot.enabled {
  background: #22c55e;
}

.nr-ci-status-text {
  font-size: 12px;
  color: var(--nr-text-tertiary);
}

.nr-ci-card-actions {
  display: flex;
  gap: 8px;
  padding: 10px 20px 16px;
  flex-wrap: wrap;
}

/* Toast */
.nr-ci-toast {
  position: fixed;
  top: 24px;
  right: 24px;
  z-index: 10001;
  padding: 10px 20px;
  border-radius: 10px;
  background: rgba(30, 30, 40, 0.95);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--nr-text-primary);
  font-size: 13px;
  font-weight: 500;
  animation: nrCiToastIn 0.25s ease;
}

@keyframes nrCiToastIn {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ======================== Modal ======================== */
.nr-ci-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: nrCiFadeIn 0.2s ease;
}

@keyframes nrCiFadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.nr-ci-modal {
  width: 580px;
  max-width: 92vw;
  max-height: 82vh;
  display: flex;
  flex-direction: column;
  border-radius: 16px;
  background: rgba(22, 22, 30, 0.96);
  backdrop-filter: blur(24px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.5);
  animation: nrCiSlideUp 0.25s ease;
}

@keyframes nrCiSlideUp {
  from { opacity: 0; transform: translateY(16px) scale(0.97); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

.nr-ci-modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 20px 24px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.nr-ci-modal-title {
  display: flex;
  align-items: center;
  gap: 14px;
}

.nr-ci-modal-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 18px;
  font-weight: 700;
  flex-shrink: 0;
  overflow: hidden;
}

.nr-ci-modal-title h3 {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: var(--nr-text-primary);
}

.nr-ci-modal-title p {
  margin: 2px 0 0;
  font-size: 13px;
  color: var(--nr-text-tertiary);
}

.nr-ci-modal-close {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--nr-text-secondary);
  font-size: 20px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.nr-ci-modal-close:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--nr-text-primary);
}

.nr-ci-modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
}

.nr-ci-section {
  margin-bottom: 20px;
}

.nr-ci-section:last-child {
  margin-bottom: 0;
}

.nr-ci-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-text-secondary);
  margin-bottom: 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.nr-ci-fields {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.nr-ci-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.nr-ci-field.toggle {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.02);
}

.nr-ci-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--nr-text-secondary);
}

.nr-ci-required {
  color: var(--nr-error);
  margin-left: 2px;
}

.nr-ci-input {
  width: 100%;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--nr-glass-border, rgba(255, 255, 255, 0.08));
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  color: var(--nr-text-primary);
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s;
}

.nr-ci-input:focus {
  border-color: var(--nr-primary);
}

.nr-ci-input::placeholder {
  color: var(--nr-text-muted, rgba(255, 255, 255, 0.25));
}

.nr-ci-select {
  width: 100%;
  height: 36px;
  padding: 0 10px;
  border: 1px solid var(--nr-glass-border, rgba(255, 255, 255, 0.08));
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  color: var(--nr-text-primary);
  font-size: 13px;
  outline: none;
  cursor: pointer;
}

.nr-ci-select:focus {
  border-color: var(--nr-primary);
}

.nr-ci-select option {
  background: var(--nr-bg-surface);
  color: var(--nr-text-primary);
}

.nr-ci-toggle {
  width: 40px;
  height: 22px;
  border: none;
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.12);
  cursor: pointer;
  position: relative;
  transition: background 0.2s;
  flex-shrink: 0;
  padding: 0;
}

.nr-ci-toggle.active {
  background: var(--nr-primary);
}

.nr-ci-toggle-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: white;
  transition: transform 0.2s;
}

.nr-ci-toggle.active .nr-ci-toggle-thumb {
  transform: translateX(18px);
}

.nr-ci-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 24px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}
</style>
