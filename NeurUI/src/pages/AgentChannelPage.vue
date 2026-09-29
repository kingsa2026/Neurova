<template>
  <div class="nr-agent-channel">
    <div class="nr-ac-header">
      <div>
        <h2>{{ t('channel.agentChannels') }}</h2>
        <p class="nr-ac-desc">{{ t('channel.agentChannelsDesc') }}</p>
      </div>
      <a-select :value="agentId" size="small" style="width: 200px"
        :options="agentSelectOptions" @change="switchAgent" />
    </div>

    <!-- 空态归因：本页的 `channels` 恒为整份渠道目录（未配置的渠道也要能点"启用"），
         故"没有配置"不在 a-empty 那个分支上，而在**已配置行为 0**。把它与"读不到
         配置"合成一个样子正是本 bug 被拖了 6 天没人定位到落点的原因。 -->
    <div v-if="showEmptyAttribution" class="nr-ac-empty-attribution" data-testid="empty-attribution">
      <p class="nr-ac-empty-title">{{ t('channel.noConfigsForAgent', { agent: agentId }) }}</p>
      <p class="nr-ac-empty-hint">{{ t('channel.noConfigsForAgentHint') }}</p>
      <div class="nr-ac-empty-actions">
        <!-- 存量归属迁移的入口落在**用户看见存量那一屏**：只说"配置在默认视图下"
             而不给搬过来的入口，用户就得一直来回切视图用别人的身份配自己的 bot。
             入口只负责**打开弹层**（Issue #326 第 3 条）：搬迁是归属的不可逆变更，
             源与渠道都该由用户在弹层里看着选，而不是点一下就整表搬走。 -->
        <GlassButton size="sm" variant="primary" data-testid="migrate-legacy-channels"
          @click="showMigration = true">
          {{ t('channel.migrateLegacyChannels') }}
        </GlassButton>
        <GlassButton size="sm" variant="secondary" data-testid="switch-to-default"
          @click="switchAgent('default')">{{ t('channel.viewDefaultAgent') }}</GlassButton>
      </div>
      <ChannelMigrationDialog :open="showMigration" :target-agent-id="agentId"
        @close="showMigration = false" @migrated="onMigrated" />
    </div>

    <!-- 归属门（非属主/非管理员）与「真的没有配置」是两回事：渲染成同一个样子
         会让用户重蹈本 bug 的老路（分不清"没配"与"看不到"）。 -->
    <div v-if="accessDenied" class="nr-ac-empty-attribution" data-testid="access-denied">
      <p class="nr-ac-empty-title">{{ t('channel.accessDenied') }}</p>
      <p class="nr-ac-empty-hint">{{ accessDenied }}</p>
      <p class="nr-ac-empty-hint">{{ t('channel.accessDeniedHint') }}</p>
    </div>

    <a-spin :spinning="loading">
      <template v-if="channels.length > 0">
        <section v-if="enabledChannels.length > 0" class="nr-ac-panel" data-testid="panel-enabled">
          <div class="nr-ac-panel-head">
            <span class="nr-ac-panel-dot on" />
            <span>{{ t('channel.enabledSection') }}</span>
            <b class="nr-ac-panel-count">{{ enabledChannels.length }}</b>
          </div>
          <div class="nr-ac-grid">
            <GlassCard v-for="ch in enabledChannels" :key="ch.channelKey" class="nr-ac-card" :style="{ borderColor: ch.color }">
              <div class="nr-ac-card-head">
                <img v-if="ch.iconSrc" :src="ch.iconSrc" class="nr-ac-icon" :alt="ch.name" />
                <span v-else class="nr-ac-icon emoji">{{ ch.icon }}</span>
                <div class="nr-ac-title">
                  <span class="nr-ac-name">
                    {{ ch.name }}
                    <a-tag :color="ch.connected ? 'green' : 'orange'">
                      {{ ch.connected ? t('channel.connected') : t('channel.enabled') }}
                    </a-tag>
                  </span>
                  <span class="nr-ac-prefix">
                    {{ t('channel.botPrefixLabel') }}:
                    <b :class="{ unset: !botPrefixOf(ch) }">{{ botPrefixOf(ch) || t('channel.notSet') }}</b>
                  </span>
                </div>
              </div>
              <div class="nr-ac-actions">
                <GlassButton size="sm" variant="secondary" @click="openConfigModal(ch)">{{ t('channel.configure') }}</GlassButton>
                <GlassButton size="sm" variant="ghost" @click="toggleChannel(ch)">{{ t('channel.disable') }}</GlassButton>
                <GlassButton v-if="ch.configured" size="sm" variant="danger" @click="removeChannel(ch)">{{ t('common.delete') }}</GlassButton>
              </div>
            </GlassCard>
          </div>
        </section>

        <section v-if="disabledChannels.length > 0" class="nr-ac-panel nr-ac-panel--dashed" data-testid="panel-disabled">
          <div class="nr-ac-panel-head">
            <span class="nr-ac-panel-dot" />
            <span>{{ t('channel.disabledSection') }}</span>
          </div>
          <div class="nr-ac-grid-compact">
            <div v-for="ch in disabledChannels" :key="ch.channelKey" class="nr-ac-chip" @click="openConfigModal(ch)">
              <span class="nr-ac-chip-left">
                <span class="nr-ac-chip-icon" :style="ch.iconSrc ? {} : { background: ch.color }">
                  <img v-if="ch.iconSrc" :src="ch.iconSrc" :alt="ch.name" />
                  <span v-else>{{ ch.icon }}</span>
                </span>
                <span class="nr-ac-chip-name">{{ ch.name }}</span>
              </span>
              <GlassButton size="sm" variant="primary" @click.stop="toggleChannel(ch)">{{ t('channel.enable') }}</GlassButton>
            </div>
          </div>
        </section>
      </template>
      <!-- 空态必须**可归因**：整页「未启用」与「真读不到配置」此前共用一个 a-empty，
           用户读到的结论只有"配置全没了"。存量渠道归属默认视图（见
           docs/06-bugfix/bugfix-channel-agent-select-and-config-landing.md），
           故非 default 视图为空时点名当前身份，并给出一键切到默认视图的入口。 -->
      <a-empty v-else :description="t('channel.noChannels')" />
    </a-spin>

    <!-- Config modal（字段表与系统页共享单一来源；负一屏复用专属组件） -->
    <a-modal v-model:open="showModal" :title="`${current?.name} · ${t('channel.configure')}`" :confirm-loading="saving"
      :footer="current?.channelKey === 'negative-screen' ? null : undefined" @ok="saveConfig">
      <NegativeScreenSettings v-if="current?.channelKey === 'negative-screen'" />
      <a-form v-else layout="vertical">
        <!-- 扫码授权：飞书/钉钉/QQ/微信——扫码即取凭据回填表单 -->
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
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  listChannelConfigs, createChannelConfig, deleteChannelConfig,
} from '@/api/modules/channel-configs'
import {
  buildChannelCatalog, buildChannelFieldsMap, buildCommonFields,
  QRCODE_CHANNELS,
  type FieldSchema, type ChannelCatalogItem,
} from '@/config/channelFields'
import QrcodeAuthBlock from '@/components/QrcodeAuthBlock.vue'
import NegativeScreenSettings from '@/components/NegativeScreenSettings.vue'
import ChannelMigrationDialog from '@/components/ChannelMigrationDialog.vue'
import { getNegativeScreenConfig } from '@/api/modules/negative-screen'
import { useAgentStore } from '@/stores/agents'
import { buildAgentSelectOptions } from '@/config/agentOptions'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()

interface AgentChannel extends ChannelCatalogItem {
  configured: boolean
}

// agent 身份的唯一事实源是**路由**：URL 可分享、刷新不丢、前进后退可回放。
// 曾经的写法把身份落在本地 ref（`@change="fetchConfigs"` 只改 ref，URL 不动），
// 于是刷新一次就回退到路由里的旧 agent —— 用户以为"配置又没了"，
// 而 saveConfig / removeChannel 都按 ref 落盘，两个事实源说出不同身份时
// 用户按屏幕认知操作、系统按另一个身份写。
const agentId = computed<string>(() => String(route.params.agentId || '') || 'default')
const loading = ref(false)
const saving = ref(false)
const showModal = ref(false)
const current = ref<AgentChannel | null>(null)
const form = reactive<{ enabled: boolean; values: Record<string, any> }>({ enabled: true, values: {} })
const savedExtras = ref<Record<string, Record<string, unknown>>>({})

const channels = ref<AgentChannel[]>([])
// 迁移动作与它的错误归因都在弹层里（Issue #326 第 3 条）：页面只负责
// 打开它、并在成功后重取本视图——屏幕状态始终来自服务端那唯一的事实源。
const showMigration = ref(false)
const accessDenied = ref('')
const commonFields = computed<FieldSchema[]>(() => buildCommonFields(t))
const channelFieldsMap = computed<Record<string, FieldSchema[]>>(() => buildChannelFieldsMap(t))

// 列表布局：已激活大卡面板 / 未激活紧凑小卡面板
const enabledChannels = computed(() => channels.value.filter((c) => c.enabled))
const disabledChannels = computed(() => channels.value.filter((c) => !c.enabled))
function botPrefixOf(ch: AgentChannel): string {
  const extra = savedExtras.value[ch.backendType] || {}
  return typeof extra.bot_prefix === 'string' ? extra.bot_prefix : ''
}

const allFields = computed<FieldSchema[]>(() => {
  if (!current.value) return []
  return [...commonFields.value, ...(channelFieldsMap.value[current.value.channelKey] || [])]
})

// agent 身份的唯一组装点：`config/agentOptions.ts`（系统渠道页共用同一份）。
// 曾经此处读 `o.id / o.name`，而 store 契约是 `{label, value}` —— 选项落成
// 空白行，选中后 agentId=undefined 不发参数，后端把它兜成 default，
// 于是"给 X 配渠道"静默写进 default 的表。禁止在此再写第二份映射。
const agentSelectOptions = computed(() => [
  { value: 'default', label: t('channel.defaultAgent') },
  ...buildAgentSelectOptions(agentStore.agentOptions),
])

/**
 * 切 agent = 换 URL。身份只有一个写入口：路由。
 *
 * 只改本地 ref 的旧写法会让 URL 与屏幕说两个身份（刷新回退、链接不可分享、
 * 落盘归属与用户认知不一致），故此处**不**直接改任何本地身份变量：
 * 推路由 → `route.params.agentId` 变 → `agentId` computed 变 → `watch` 触发取数。
 */
function switchAgent(value: unknown) {
  const next = String(value ?? '')
  if (!next || next === agentId.value) return
  router.push({ name: 'AgentChannel', params: { agentId: next } })
}

// 空态归因只在"确实可能是别人的配置"时给：`default` 视图本身就是存量的
// 归属地，在那里为空就是真的没配过，加提示只会制造噪音。
// 判据是**已配置行数为 0**，不是 `channels.length`——后者恒等于整份渠道目录。
const showEmptyAttribution = computed(
  () => agentId.value !== 'default' && !loading.value && !accessDenied.value
    && channels.value.length > 0 && !channels.value.some((c) => c.configured),
)

function baseCatalog(): AgentChannel[] {
  // NV 独有渠道：鸿蒙负一屏推送（Phase C 换共享目录时只加在系统页，
  // Agent 页一并恢复——用户级配置，打开即复用 NegativeScreenSettings）
  return [...buildChannelCatalog(t), NEG_SCREEN_CARD].map((c) => ({ ...c, configured: false }))
}

// ─── NV 独有·负一屏推送卡（backendType='' → 不参与平台配置行匹配）───
const NEG_SCREEN_CARD: ChannelCatalogItem = { name: t('settings.negativeScreen'), icon: '📲', type: 'builtin', enabled: false, color: '#e11d48', channelKey: 'negative-screen', backendType: '', connected: false }

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
  accessDenied.value = ''
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
    // 负一屏是用户级独立 API（不在 channel-configs 里）——同步其真实启用态，
    // 否则永远显示未启用（与系统页 loadConfigs 的 negCh 分支对齐）。
    try {
      const neg: any = await getNegativeScreenConfig()
      const negCh = channels.value.find((c) => c.channelKey === 'negative-screen')
      if (negCh) negCh.enabled = !!(neg?.enabled ?? neg?.data?.enabled)
    } catch {
      /* 保持默认停用 */
    }
  } catch (e: any) {
    channels.value = baseCatalog()
    // 403 与"没有配置"必须可区分：前者是归属门（仅属主/管理员），后者是真没配过。
    // 合并成同一句"出错了"正是本 bug 被拖 6 天没人定位到落点的形态。
    const detail = e?.response?.data?.detail
    if (e?.response?.status === 403) {
      accessDenied.value = String(detail || t('channel.accessDenied'))
      return
    }
    message.error(detail ? t('channel.genericFailure', { reason: String(detail) }) : t('common.error'))
  } finally {
    loading.value = false
  }
}

/** 弹层回报迁移成功：重取本视图，并按服务端的返回点名搬了哪些。 */
async function onMigrated(payload: { from: string; to: string; channels: string[] }) {
  showMigration.value = false
  await fetchConfigs()
  if (payload.channels.length) {
    message.success(t('channel.migrateSuccess', { count: payload.channels.length, agent: payload.to }))
  } else {
    message.info(t('channel.migrateEmpty'))
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

// 与系统页一致：紧凑卡「启用」/大卡「禁用」本地翻转 enabled（真正落盘在保存时）；
// 负一屏是独立 API 的用户级开关，点「启用」直接打开其专属设置面板。
function toggleChannel(ch: AgentChannel) {
  if (ch.channelKey === 'negative-screen') {
    openConfigModal(ch)
    return
  }
  ch.enabled = !ch.enabled
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
    // 扫码由弹窗内 QrcodeAuthBlock 承担（取码→轮询→回填 bot_token→再保存）；
    // needs_scan 仅表示未带 token 保存，配置照常持久化，适配器待扫码后重存注册。
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
  // 两源都要拉：工作流编译出的 agent 由 loadWorkflowAgents 提供，
  // 此前从未调用 → 这类 agent 在本页永远不出现（同一"身份没走通"契约的命中点）。
  // 但**不阻塞** fetchConfigs：渠道列表按路由带来的 agent 身份取数，
  // 与 agent 选项列表无依赖关系 —— 把主内容挂在无关请求上，
  // 会让一次慢/失败的 /agents 拖空整页（选项本身是响应式的，到了就渲染）。
  agentStore.loadAgents?.()
  agentStore.loadWorkflowAgents?.()
})

// 身份变化即取数：`agentId` 源自路由，故首挂载与后续 URL 变化（选择器、前进后退、
// 外部跳转）走**同一条**取数路径 —— 不必也不许再写第二处 fetchConfigs 调用，
// 否则两条路各自演化，"切换后看到的是谁的配置"就没人能一眼答出。
watch(agentId, () => { fetchConfigs() }, { immediate: true })
</script>

<style scoped>
.nr-agent-channel { display: flex; flex-direction: column; gap: 16px; }
.nr-ac-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.nr-ac-header h2 { margin: 0; font-size: 18px; color: var(--nr-text-primary); }
.nr-ac-desc { margin: 4px 0 0; font-size: 12px; color: var(--nr-text-tertiary); }

/* 双面板布局 */
.nr-ac-panel {
  display: flex; flex-direction: column; gap: 16px; padding: 20px;
  border: 1px solid var(--nr-border-color, rgba(255, 255, 255, 0.08));
  border-radius: 16px; background: rgba(255, 255, 255, 0.015);
}
.nr-ac-panel--dashed { border-style: dashed; }
.nr-ac-empty-attribution { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.nr-ac-empty-title { margin: 0; font-size: 13px; font-weight: 600; color: var(--nr-text-secondary); }
.nr-ac-empty-hint { margin: 0; max-width: 420px; font-size: 12px; color: var(--nr-text-tertiary); }
.nr-ac-empty-actions { display: flex; gap: 8px; }
.nr-ac-empty-error { margin: 0; max-width: 420px; font-size: 12px; color: var(--nr-error, #ef4444); }
.nr-ac-panel-head {
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; font-weight: 600; color: var(--nr-text-primary);
}
.nr-ac-panel-count { color: var(--nr-success, #22c55e); }
.nr-ac-panel-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--nr-text-tertiary, #6b7280); }
.nr-ac-panel-dot.on { background: var(--nr-success, #22c55e); }

.nr-ac-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.nr-ac-card { display: flex; flex-direction: column; gap: 12px; }
.nr-ac-card-head { display: flex; gap: 10px; align-items: center; }
.nr-ac-icon { width: 32px; height: 32px; object-fit: contain; }
.nr-ac-icon.emoji { font-size: 26px; }
.nr-ac-title { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.nr-ac-name { display: flex; align-items: center; gap: 8px; font-weight: 600; color: var(--nr-text-primary); min-width: 0; }
.nr-ac-prefix { font-size: 12px; color: var(--nr-text-tertiary); }
.nr-ac-prefix b { font-weight: 600; color: var(--nr-text-secondary); }
.nr-ac-prefix b.unset { font-weight: 400; color: var(--nr-text-tertiary); }
.nr-ac-actions { display: flex; gap: 8px; }

/* 未激活紧凑小卡 */
.nr-ac-grid-compact { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
.nr-ac-chip {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  padding: 12px 14px; border: 1px solid var(--nr-border-color, rgba(255, 255, 255, 0.08));
  border-radius: 12px; background: rgba(255, 255, 255, 0.02); cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.nr-ac-chip:hover { border-color: var(--nr-accent, #6366f1); background: rgba(99, 102, 241, 0.06); }
.nr-ac-chip-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.nr-ac-chip-icon {
  width: 26px; height: 26px; border-radius: 7px; display: flex; align-items: center;
  justify-content: center; font-size: 15px; flex-shrink: 0; overflow: hidden;
}
.nr-ac-chip-icon img { width: 100%; height: 100%; object-fit: contain; }
.nr-ac-chip-name { font-size: 13px; font-weight: 600; color: var(--nr-text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
