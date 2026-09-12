<template>
  <div class="nr-channel-integration">
    <!-- Header -->
    <div class="nr-ci-header">
      <div class="nr-ci-title-row">
      <a-select v-model:value="agentId" size="small" style="width: 200px; margin-left: 12px"
        :options="[{ value: 'default', label: t('channel.defaultAgent') }, ...agentStore.agentOptions.map((o: any) => ({ value: o.id, label: o.name }))]"
        @change="onAgentChange" />
        <h2>{{ t('channel.integration') }}</h2>
        <!-- B4-a：机器人身份冲突检测（多渠道复用同一凭据会串回调） -->
        <GlassButton variant="ghost" size="sm" @click="runConflictCheck">
          {{ t('channel.conflictCheck') }}
        </GlassButton>
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

    <!-- P0-5 入站持久化队列状态条 -->
    <div v-if="ingressStats?.enabled" class="nr-ci-ingress">
      <span class="nr-ci-ingress-title">{{ t('channel.ingressQueue') }}</span>
      <span class="nr-ci-ingress-item">
        {{ t('channel.ingressPending') }}: <b>{{ ingressStats.pending ?? 0 }}</b>
      </span>
      <span class="nr-ci-ingress-item">
        {{ t('channel.ingressProcessing') }}: <b>{{ ingressStats.processing ?? 0 }}</b>
      </span>
      <span class="nr-ci-ingress-item" :class="{ warn: (ingressStats.dead_letter ?? 0) > 0 }">
        {{ t('channel.ingressDead') }}: <b>{{ ingressStats.dead_letter ?? 0 }}</b>
      </span>
      <span class="nr-ci-ingress-item">
        {{ t('channel.ingressProcessed') }}: <b>{{ ingressStats.processed_total ?? 0 }}</b>
      </span>
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
              {{ ch.enabled ? t('channel.disable') : t('channel.enable') }}
            </GlassButton>
            <GlassButton variant="secondary" size="sm" @click="openConfigModal(ch)">
              {{ t('channel.configure') }}
            </GlassButton>
            <GlassButton variant="secondary" size="sm" @click="testChannel(ch)">
              {{ t('channel.test') }}
            </GlassButton>
            <!-- B4-a：渠道重启（disconnect→connect，配置变更生效）；
                 负一屏走独立 API 且无适配器类型，不渲染 -->
            <GlassButton
              v-if="ch.backendType"
              variant="ghost"
              size="sm"
              @click="restartAdapter(ch)"
            >
              {{ t('channel.restart') }}
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
            <!-- 负一屏推送：复用专用设置组件（含授权码指引/测试推送/统计/删除） -->
            <NegativeScreenSettings v-if="currentChannel?.channelKey === 'negative-screen'" />
            <template v-else>
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
                    <a-select v-model:value="configForm[field.key]" style="width: 100%">
                      <a-select-option v-for="opt in field.options" :key="opt.value" :value="opt.value">
                        {{ opt.label }}
                      </a-select-option>
                    </a-select>
                  </template>
                  <template v-else>
                    <input
                      v-model="configForm[field.key]"
                      :type="field.type === 'password' ? 'password' : (field.inputType || 'text')"
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
                    <a-select v-model:value="configForm[field.key]" style="width: 100%">
                      <a-select-option v-for="opt in field.options" :key="opt.value" :value="opt.value">
                        {{ opt.label }}
                      </a-select-option>
                    </a-select>
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
                      :type="field.type === 'password' ? 'password' : (field.inputType || 'text')"
                      :placeholder="field.placeholder"
                      class="nr-ci-input"
                    />
                  </template>
                </div>
              </div>
            </div>
            </template>
          </div>

          <!-- Modal Footer（负一屏自带保存/删除，隐藏通用 footer） -->
          <div v-if="currentChannel?.channelKey !== 'negative-screen'" class="nr-ci-modal-footer">
            <GlassButton variant="ghost" @click="clearQueue(currentChannel!)">{{ t('channel.clearQueue') }}</GlassButton>
            <GlassButton variant="ghost" @click="closeConfigModal">{{ t('common.cancel') }}</GlassButton>
            <GlassButton variant="primary" :loading="saving" @click="saveConfig">{{ t('common.save') }}</GlassButton>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- F-3：iLink 扫码对话框（save/test 返回 needs_scan 时弹出） -->
    <WechatQrcodeDialog
      :visible="qrDialogVisible"
      :qr-url="qrUrl"
      :qr-id="qrId"
      @update:visible="onQrDialogClose"
      @confirmed="onQrConfirmed"
      @regenerate="onQrRegenerate"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { listChannelConfigs, createChannelConfig, testChannelConfig, getIngressStats, restartChannelAdapter, clearChannelQueue, checkChannelConflicts, listPluginChannelSchemas, createWechatIlinkQrcode, type ChannelIngressStats } from '@/api/modules/channel-configs'
import { getNegativeScreenConfig, updateNegativeScreenConfig, testNegativeScreenPush } from '@/api/modules/negative-screen'
import NegativeScreenSettings from '@/components/NegativeScreenSettings.vue'
import WechatQrcodeDialog from '@/components/WechatQrcodeDialog.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import GlassInput from '@/components/GlassInput.vue'
import { useAgentStore } from '@/stores/agents'
import {
  buildChannelCatalog, buildChannelFieldsMap, buildCommonFields,
  pluginSchemaToFields, COMMON_FIELD_KEYS,
  type FieldSchema, type ChannelCatalogItem,
} from '@/config/channelFields'

type ChannelItem = ChannelCatalogItem

const { t } = useI18n()
const agentStore = useAgentStore()

// agent 隔离（Phase C）：渠道配置按 agent 归属视图；'default' 为默认 agent
const agentId = ref<string>('default')


// ─── 字段表与卡片目录：共享模块单一来源（agent 隔离 Phase C） ───
const commonFields = computed<FieldSchema[]>(() => buildCommonFields(t))

const channelFieldsMap = computed<Record<string, FieldSchema[]>>(() => buildChannelFieldsMap(t))

// ─── Channel definitions（共享目录 + 负一屏专属卡）───
const NEG_SCREEN_CARD: ChannelItem = { name: t('settings.negativeScreen'), icon: '📲', type: 'builtin', enabled: false, color: '#e11d48', channelKey: 'negative-screen', backendType: '', connected: false }
const channels = ref<ChannelItem[]>([...buildChannelCatalog(t), NEG_SCREEN_CARD])

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

// ─── F-3：iLink 扫码闭环状态 ───
const qrDialogVisible = ref(false)
const qrUrl = ref('')
const qrId = ref('')
/** 打开扫码对话框时的上下文：保存流程确认后需重发保存注册适配器 */
const qrContext = ref<{ channel: ChannelItem; fromSave: boolean; extra: Record<string, any> } | null>(null)
/** 已保存配置的 extra（F-2：测试连接发送真实已存凭据，而非恒空 {}） */
const savedExtras = ref<Record<string, Record<string, any>>>({})

// ─── Helpers ───
function openConfigModal(ch: ChannelItem) {
  currentChannel.value = ch
  // 负一屏推送：配置由内嵌的 NegativeScreenSettings 组件自理，无需填充通用表单
  if (ch.channelKey === 'negative-screen') {
    showConfigModal.value = true
    return
  }
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
  // 修复（慢性病 b）：重开表单回填该 agent 该渠道的已存值（原永远空表单，
  // 保存即用默认覆盖——用户看到"参数又不对了"的根因之一）
  Object.assign(defaults, savedExtras.value[ch.backendType] || {})
  Object.keys(configForm).forEach((k) => delete configForm[k])
  Object.assign(configForm, defaults)
  showConfigModal.value = true
}

function closeConfigModal() {
  showConfigModal.value = false
  currentChannel.value = null
}

function toggleChannel(ch: ChannelItem) {
  if (ch.channelKey === 'negative-screen') {
    toggleNegativeScreen(ch)
    return
  }
  ch.enabled = !ch.enabled
}

// 负一屏推送：启用状态持久化到 /negative-screen（非本地翻转）
async function toggleNegativeScreen(ch: ChannelItem) {
  const next = !ch.enabled
  try {
    await updateNegativeScreenConfig({ enabled: next })
    ch.enabled = next
  } catch {
    showToast(t('negativeScreen.saveFailed'))
  }
}

function onAgentChange() {
  // 切换 agent：清缓存视图并重拉该 agent 的渠道配置
  savedExtras.value = {}
  loadConfigs()
}

async function loadConfigs() {
  loadingConfigs.value = true
  try {
    // B4-d：插件渠道动态接入——先追加卡片（在已存配置合并前，否则状态回填错过新卡片）
    try {
      const schemaRes: any = await listPluginChannelSchemas()
      const schemas = schemaRes?.data?.schemas ?? schemaRes?.schemas ?? []
      schemas.forEach((s: any) => {
        pluginFields.value[s.channel_type] = pluginSchemaToFields(s.config_fields ?? [])
        const existing = channels.value.find((c) => c.backendType === s.channel_type)
        if (!existing) {
          channels.value.push({
            name: s.name || s.channel_type,
            icon: '🔌',
            type: 'custom',
            enabled: false,
            color: '#8b5cf6',
            channelKey: s.channel_type,
            backendType: s.channel_type,
            connected: false,
          })
        }
      })
    } catch {
      /* schema 拉取失败不阻塞页面（无插件渠道时恒空） */
    }

    const data: any = await listChannelConfigs(agentId.value)
    if (Array.isArray(data)) {
      data.forEach((cfg: any) => {
        const ch = channels.value.find((c) => c.backendType === cfg.channel_type)
        if (ch) {
          ch.enabled = cfg.enabled
          ch.connected = cfg.connected || false
        }
        // F-2：缓存已存 extra，测试连接时发送真实凭据
        savedExtras.value[cfg.channel_type] = cfg.extra ?? {}
      })
    }
    // 负一屏推送走独立 API 回读启用状态
    const negCh = channels.value.find((c) => c.channelKey === 'negative-screen')
    if (negCh) {
      try {
        const cfg = await getNegativeScreenConfig()
        negCh.enabled = !!cfg.enabled
      } catch {
        /* 保持默认停用 */
      }
    }
  } catch (e) {
    message.error(t('common.error'))
  } finally {
    loadingConfigs.value = false
  }
  // P0-5：入站持久化队列状态（失败静默——面板隐藏即可）
  try {
    ingressStats.value = (await getIngressStats()) as ChannelIngressStats
  } catch {
    ingressStats.value = null
  }
}

// P0-5 入站持久化队列状态
const ingressStats = ref<ChannelIngressStats | null>(null)

async function saveConfig() {
  if (!currentChannel.value) return
  // 负一屏推送的保存走内嵌组件，通用保存不适用
  if (currentChannel.value.channelKey === 'negative-screen') return
  saving.value = true
  const ch = currentChannel.value
  try {
    // 修复（慢性病 a）：公共字段随表单全部进 extra（原被排除后无处安放→静默丢弃）
    const extra: Record<string, any> = {}
    Object.keys(configForm).forEach((key) => {
      if (key !== 'enabled') extra[key] = configForm[key]
    })

    const payload = {
      channel_type: ch.backendType,
      enabled: configForm.enabled !== false,
      app_id: extra.app_id || '',
      app_secret: extra.app_secret || '',
            // 修复（慢性病 c）：连接流模式取平台自己的 use_stream，不再拿公共 stream_mode 顶包
      use_stream: configForm.use_stream !== undefined ? !!configForm.use_stream : true,
      webhook_url: '',
      webhook_token: '',
      encrypt_key: extra.encrypt_key || '',
      verification_token: extra.verification_token || '',
      extra,
    }

    await createChannelConfig(payload as any, agentId.value).then(async (res: any) => {
      const data = res?.data ?? res
      savedExtras.value[ch.backendType] = { ...extra }
      if (data?.needs_scan) {
        // F-3：wechat iLink 无 token——配置已持久化，进入扫码闭环；
        // 确认后由 onQrConfirmed 重发保存以注册适配器
        await openQrcodeFlow(ch, extra, true)
        return
      }
      ch.enabled = payload.enabled
      showToast(t('channel.configSaved'))
      closeConfigModal()
    })
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
    // 负一屏推送：后端用已存配置发测试推送
    if (ch.channelKey === 'negative-screen') {
      const d = await testNegativeScreenPush({
        task_name: t('ui.testPushTaskName'),
        task_content: t('ui.testPushContent') + new Date().toLocaleString(),
        task_result: t('ui.testPushResult'),
      })
      // gap1：失败必须透出网关错误原文（如 "Parameter x-trace-id is empty"），否则用户无从排查
      showToast(d.success ? t('negativeScreen.testPushSuccess') : t('negativeScreen.testPushFailed') + (d.error ? ': ' + d.error : ''))
      return
    }
    // F-2：测试连接发送真实已存凭据（旧逻辑恒发 extra: {} → wechat 恒假阳性）
    const saved = savedExtras.value[ch.backendType] ?? {}
    const payload: Record<string, any> = {
      channel_type: ch.backendType,
      enabled: true,
      app_id: saved.app_id || '',
      app_secret: saved.app_secret || '',
      use_stream: true,
      webhook_url: '',
      webhook_token: '',
      encrypt_key: saved.encrypt_key || '',
      verification_token: saved.verification_token || '',
      extra: saved,
    }
    const result: any = await testChannelConfig(ch.backendType, payload as any, agentId.value)
    const data = result?.data ?? result
    if (data?.needs_scan) {
      // F-3：wechat iLink 无 token → 扫码闭环（诚实失败，不假成功）
      await openQrcodeFlow(ch, saved, false)
      return
    }
    showToast(data?.success ? t('channel.testSuccess') : t('channel.testFailed'))
  } catch (e: any) {
    showToast(t('channel.testFailed'))
  } finally {
    testingChannel.value = null
  }
}

// ── F-3：iLink 扫码闭环 ────────────────────────────────────────────────

/** 生成二维码并打开扫码对话框；已有有效 token（ready）则直接走确认后路径 */
async function openQrcodeFlow(ch: ChannelItem, extra: Record<string, any>, fromSave: boolean) {
  try {
    const res: any = await createWechatIlinkQrcode({
      token_file: extra.token_file || '',
      bot_token: extra.bot_token || '',
    }, agentId.value)
    const data = res?.data ?? res
    if (data?.status === 'pending' && data.qr_id) {
      qrUrl.value = data.qr_url || ''
      qrId.value = data.qr_id
      qrContext.value = { channel: ch, fromSave, extra }
      qrDialogVisible.value = true
      return
    }
    if (data?.status === 'ready') {
      // 已有有效 token：无需扫码，直接收尾
      await finishQrcodeFlow(ch, fromSave)
      return
    }
    showToast(t('channel.qrGenerateFailed'))
  } catch (e: any) {
    showToast(e?.response?.data?.detail || t('channel.qrGenerateFailed'))
  }
}

/** 扫码确认收尾：保存流程 → 重发保存注册适配器；测试流程 → 刷新渠道状态 */
async function finishQrcodeFlow(ch: ChannelItem, fromSave: boolean) {
  closeQrcodeDialog()
  showToast(t('channel.qrLoginSuccess'))
  if (fromSave) {
    // token 已落盘：重发保存，本次 needs_scan=False，适配器正常注册
    await saveConfig()
  } else {
    ch.connected = true
    await loadConfigs()
  }
}

async function onQrConfirmed() {
  const ctx = qrContext.value
  if (!ctx) {
    closeQrcodeDialog()
    return
  }
  await finishQrcodeFlow(ctx.channel, ctx.fromSave)
}

async function onQrRegenerate() {
  const ctx = qrContext.value
  if (!ctx) return
  // 清空 qr_id 会让对话框停止旧轮询；openQrcodeFlow 会写入新 qr_id 重启轮询
  qrId.value = ''
  await openQrcodeFlow(ctx.channel, ctx.extra, ctx.fromSave)
}

function onQrDialogClose() {
  closeQrcodeDialog()
}

function closeQrcodeDialog() {
  qrDialogVisible.value = false
  qrId.value = ''
  qrUrl.value = ''
  qrContext.value = null
}

// ── B4-a：运行管理（重启 / 清空队列 / 身份冲突检测） ──────────────────────
async function restartAdapter(ch: ChannelItem) {
  try {
    const res: any = await restartChannelAdapter(ch.backendType)
    const data = res?.data ?? res
    if (data?.success) {
      showToast(t('channel.restartOk'))
    } else {
      showToast(`${t('channel.restartFail')}: ${data?.error ?? ''}`)
    }
  } catch (e: any) {
    showToast(e?.message || t('channel.restartFail'))
  }
}

async function clearQueue(ch: ChannelItem) {
  try {
    const res: any = await clearChannelQueue(ch.backendType)
    const data = res?.data ?? res
    showToast(`${t('channel.queueCleared')}: ${data?.cleared ?? 0}`)
  } catch (e: any) {
    showToast(e?.message || t('channel.restartFail'))
  }
}

async function runConflictCheck() {
  try {
    const res: any = await checkChannelConflicts()
    const data = res?.data ?? res
    const conflicts = data?.conflicts ?? []
    if (!conflicts.length) {
      showToast(t('channel.noConflicts'))
      return
    }
    const lines = conflicts
      .map((c: any) => `${c.identity}: ${(c.channels ?? []).join(', ')}`)
      .join('；')
    message.warning(`${t('channel.conflictFound')} ${lines}`)
  } catch (e: any) {
    showToast(e?.message || t('channel.restartFail'))
  }
}


function showToast(msg: string) {
  toastMessage.value = msg
  setTimeout(() => { toastMessage.value = '' }, 3000)
}

// ─── Computed ───
// B4-d：插件渠道动态表单字段（schema 端点下发，key=channel_type）
const pluginFields = ref<Record<string, { key: string; label: string; type: string; required?: boolean; defaultValue?: unknown; placeholder?: string }[]>>({})

const currentChannelFields = computed(() => {
  if (!currentChannel.value) return []
  return (
    channelFieldsMap.value[currentChannel.value.channelKey] ||
    pluginFields.value[currentChannel.value.channelKey] ||
    []
  )
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

onMounted(() => {
  agentStore.loadAgents?.()
  search.value = ''
  loadConfigs()
})
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

/* P0-5 入站持久化队列状态条 */
.nr-ci-ingress {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding: 10px 16px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 13px;
  color: var(--nr-text-secondary, inherit);
}

.nr-ci-ingress-title {
  font-weight: 600;
  color: var(--nr-text-primary, inherit);
}

.nr-ci-ingress-item.warn {
  color: var(--nr-warning, #faad14);
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
