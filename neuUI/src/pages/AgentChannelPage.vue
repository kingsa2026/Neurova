<template>
  <div >
    <div >
      <h2 ><ApiOutlined :style="{ color: '#10b981' }" /> 渠道管理</h2>
      <div >
        <a-button @click="loadChannels" :loading="loading"><ReloadOutlined /> 刷新</a-button>
        <a-button type="primary" @click="openDrawer()"><PlusOutlined /> 添加渠道</a-button>
      </div>
    </div>
    <div >
      <div >渠道数量<b >{{ channels.length }}</b></div>
      <div >已启用<b >{{ channels.filter((c) => c.enabled !== false).length }}</b></div>
      <div >渠道类型<b >{{ availableChannels.length }}</b></div>
    </div>
    <a-alert v-if="error" :message="error" type="error" show-icon closable @close="error = ''" />
    <a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" />
    <div v-if="!loading && channels.length" >
      <div v-for="channel in channels" :key="channel.channel"  @click="openDrawer(channel)">
        <span  :>
          <CheckCircleFilled v-if="channel.enabled" />
          <MinusCircleFilled v-else />
        </span>
        <div >
          <div  :style="{ background: getChannelColor(channel.channel) }">
            <component :is="getChannelIcon(channel.channel)" />
          </div>
          <div >
            <h4>{{ channel.display_name || getChannelLabel(channel.channel) || channel.channel }}</h4>
            <div >
              <a-tag size="small" :color="channel.enabled !== false ? 'green' : 'default'">
                {{ channel.enabled !== false ? '启用' : '禁用' }}
              </a-tag>
              <a-tag v-if="channel.health" size="small" :color="channel.health === 'healthy' ? 'blue' : 'red'">
                {{ channel.health }}
              </a-tag>
            </div>
          </div>
        </div>
        <div >
          <div >
            <ApiOutlined  />
            <span >Webhook: /api/v1/channels/webhook/{{ channel.channel }}?agent_id={{ agentId }}</span>
          </div>
          <div  v-if="channel.totalRequests !== undefined">
            <span >请求: {{ channel.totalRequests || 0 }} | 错误: {{ channel.totalErrors || 0 }}</span>
          </div>
        </div>
        <div  @click.stop>
          <a-button size="small" type="primary" ghost @click="openDrawer(channel)"><SettingOutlined /> 配置</a-button>
          <a-button size="small" @click="handleToggle(channel)">{{ channel.enabled !== false ? '禁用' : '启用' }}</a-button>
          <a-button size="small" danger @click="handleRemove(channel)"><DeleteOutlined /></a-button>
        </div>
      </div>
    </div>
    <div v-else-if="!loading" >
      <ApiOutlined style="font-size:48px;color:rgba(255,255,255,0.1)" />
      <p>暂无渠道配置</p>
      <a-button type="primary" @click="openDrawer()">添加第一个渠道</a-button>
    </div>
    <!-- 移动设备配对 -->
    <div >
      <MobilePairingPanel :agent-id="agentId" />
    </div>
    <!-- 配置/添加 Drawer -->
    <a-drawer
      v-model:open="drawerOpen"
      :title="drawerChannel ? '配置渠道' : '添加渠道'"
      :width="580"
      placement="right"
      @close="closeDrawer"
    >
      <a-form layout="vertical">
        <template v-if="!drawerChannel">
          <a-form-item label="渠道类型" required>
            <a-select v-model:value="drawerForm.channel" placeholder="选择渠道类型" @change="onChannelTypeChange">
              <a-select-option v-for="ch in availableChannels" :key="ch.value" :value="ch.value">{{ ch.label }}</a-select-option>
            </a-select>
          </a-form-item>
        </template>
        <template v-else>
          <a-alert :message="'渠道: ' + (drawerChannel.display_name || drawerChannel.channel)" type="info" show-icon style="margin-bottom:16px" />
        </template>
        <!-- 渠道专属字段 -->
        <template v-if="currentFields.length">
          <a-divider>渠道配置</a-divider>
          <template v-for="field in currentFields" :key="field.name">
            <a-form-item v-if="field.type === 'text'" :label="field.label" :required="field.required">
              <a-input v-model:value="drawerForm.fields[field.name]" :placeholder="field.name" />
            </a-form-item>
            <a-form-item v-else-if="field.type === 'password'" :label="field.label" :required="field.required">
              <a-input-password v-model:value="drawerForm.fields[field.name]" :placeholder="field.name" />
            </a-form-item>
            <a-form-item v-else-if="field.type === 'switch'" :label="field.label">
              <a-switch v-model:checked="drawerForm.fields[field.name]" />
            </a-form-item>
            <a-form-item v-else-if="field.type === 'select'" :label="field.label">
              <a-select v-model:value="drawerForm.fields[field.name]">
                <a-select-option v-for="o in field.options" :key="o" :value="o">{{ o }}</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item v-else-if="field.type === 'number'" :label="field.label" :required="field.required">
              <a-input-number v-model:value="drawerForm.fields[field.name]" style="width:100%" />
            </a-form-item>
          </template>
        </template>
        <!-- 通用字段 -->
        <template v-if="currentCommonFields.length">
          <a-divider>通用配置</a-divider>
          <template v-for="field in currentCommonFields" :key="'c_'+field.name">
            <a-form-item v-if="field.type === 'switch'" :label="field.label">
              <a-switch v-model:checked="drawerForm.fields[field.name]" />
            </a-form-item>
            <a-form-item v-else-if="field.type === 'select'" :label="field.label">
              <a-select v-model:value="drawerForm.fields[field.name]">
                <a-select-option v-for="o in field.options" :key="o" :value="o">{{ o }}</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item v-else :label="field.label">
              <a-input v-model:value="drawerForm.fields[field.name]" :placeholder="field.default?.toString() || ''" />
            </a-form-item>
          </template>
        </template>
      </a-form>
      <template #footer>
        <a-button @click="closeDrawer">取消</a-button>
        <a-button type="primary" :loading="saving" @click="handleSave">
          {{ drawerChannel ? '保存' : '添加' }}
        </a-button>
      </template>
    </a-drawer>
  </div>
</template>
<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, h, type VNode } from 'vue'
import { message } from 'ant-design-vue'
import {
  ApiOutlined, PlusOutlined, ReloadOutlined, SettingOutlined,
  CheckCircleFilled, MinusCircleFilled, DeleteOutlined,
} from '@ant-design/icons-vue'
import { channelAPI } from '@/api/modules/channel'
import { useAgentPage } from '@/composables/useAgentPage'
import MobilePairingPanel from '@/components/MobilePairingPanel.vue'
interface ChannelData {
  channel: string
  display_name?: string
  enabled?: boolean
  health?: string
  totalRequests?: number
  totalErrors?: number
  adapter_config?: Record<string, unknown>
  config?: Record<string, unknown>
}
interface ChannelField {
  name: string
  label: string
  type: string
  required?: boolean
  default?: unknown
  options?: string[]
}
interface ChannelCapability {
  optional_fields?: ChannelField[]
  common_fields?: ChannelField[]
}
const { agentId, initAgent } = useAgentPage('/agent/:agentId/channel', () => loadChannels())
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const channels = ref<ChannelData[]>([])
const channelCapabilities = ref<Record<string, ChannelCapability>>({})
const availableChannels = [
  { value: 'feishu', label: '飞书' },
  { value: 'dingtalk', label: '钉钉' },
  { value: 'wecom', label: '企业微信' },
  { value: 'wechat', label: '微信' },
  { value: 'telegram', label: 'Telegram' },
  { value: 'discord', label: 'Discord' },
  { value: 'qq', label: 'QQ频道' },
  { value: 'qqbot', label: 'QQ Bot' },
  { value: 'xiaoyi', label: '小艺' },
  { value: 'sip', label: 'SIP' },
  { value: 'voice', label: '电话' },
  { value: 'mqtt', label: 'MQTT' },
  { value: 'websocket', label: 'WebSocket' },
  { value: 'mobile', label: '移动设备' },
]
const channelLabels = Object.fromEntries(availableChannels.map(c => [c.value, c.label]))
function getChannelLabel(name: string) { return channelLabels[name] || name }
const drawerOpen = ref(false)
const drawerChannel = ref<ChannelData | null>(null)
const drawerForm = reactive({ channel: '', fields: {} as Record<string, unknown> })
const currentFields = computed(() => {
  const key = drawerChannel.value?.channel || drawerForm.channel
  const cap = channelCapabilities.value[key]
  return cap?.optional_fields || []
})
const currentCommonFields = computed(() => {
  const key = drawerChannel.value?.channel || drawerForm.channel
  const cap = channelCapabilities.value[key]
  return cap?.common_fields || []
})
const channelIcons: Record<string, () => VNode> = {
  feishu: () => h('span', null, '📱'), wechat: () => h('span', null, '💬'),
  dingtalk: () => h('span', null, '🏢'), qq: () => h('span', null, '🐧'),
  qqbot: () => h('span', null, '🤖'), discord: () => h('span', null, '🎮'),
  telegram: () => h('span', null, '✈️'), wecom: () => h('span', null, '🏭'),
  xiaoyi: () => h('span', null, '🤖'), sip: () => h('span', null, '📞'),
  voice: () => h('span', null, '📞'), mqtt: () => h('span', null, '📡'),
  websocket: () => h('span', null, '🔌'), mobile: () => h('span', null, '📱'),
}
function getChannelColor(name: string) {
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']
  const idx = availableChannels.findIndex(c => c.value === name)
  return colors[idx >= 0 ? idx % colors.length : 0]
}
function getChannelIcon(name: string) { return channelIcons[name] || (() => h('span', null, '📡')) }
async function loadChannels() {
  loading.value = true; error.value = ''
  try {
    const res = await channelAPI.list()
    const data = res?.data || res
    channels.value = Array.isArray(data) ? data : (data?.channels || [])
  } catch (e: unknown) { error.value = (e as Error).message || '加载失败' }
  finally { loading.value = false }
}
async function fetchCapabilities(key: string) {
  try {
    const res = await channelAPI.getCapabilities()
    const caps = res?.data?.capabilities || res?.capabilities || {}
    channelCapabilities.value = caps as Record<string, ChannelCapability>
    const cap = caps[key]
    if (cap) {
      const fields: Record<string, unknown> = {}
      for (const f of (cap.optional_fields || []))
        fields[f.name] = f.default ?? (f.type === 'switch' ? false : f.type === 'number' ? 0 : '')
      for (const f of (cap.common_fields || []))
        fields[f.name] = f.default ?? (f.type === 'switch' ? false : '')
      drawerForm.fields = fields
    }
  } catch { /* ignore */ }
}
function onChannelTypeChange(value: string) {
  drawerForm.channel = value
  fetchCapabilities(value)
}
function openDrawer(channel?: ChannelData) {
  if (channel) {
    drawerChannel.value = channel
    drawerForm.channel = channel.channel
    drawerForm.fields = { ...(channel.adapter_config || channel.config || {}), enabled: channel.enabled !== false }
    fetchCapabilities(channel.channel)
  } else {
    drawerChannel.value = null
    drawerForm.channel = ''
    drawerForm.fields = {}
  }
  drawerOpen.value = true
}
function closeDrawer() { drawerOpen.value = false; drawerChannel.value = null }
async function handleSave() {
  const channel = drawerChannel.value?.channel || drawerForm.channel
  if (!channel) { message.warning('请选择渠道类型'); return }
  saving.value = true
  try {
    const config: Record<string, unknown> = { ...drawerForm.fields }
    config.agent_id = agentId.value || config.agent_id
    const res = await channelAPI.addOrUpdate(channel, { enabled: config.enabled !== false, config })
    if (res?.code === 0 || res?.success) {
      message.success(drawerChannel.value ? '已更新' : '已添加')
      closeDrawer()
      await loadChannels()
    } else { message.error(res?.message || '操作失败') }
  } catch (e: unknown) { message.error((e as Error).message || '操作失败') }
  finally { saving.value = false }
}
async function handleToggle(channel: ChannelData) {
  try {
    const api = channel.enabled === false ? channelAPI.enable : channelAPI.disable
    const res = await api(channel.channel)
    if (res?.code === 0 || res?.success) {
      channel.enabled = !channel.enabled
      message.success(channel.enabled ? '已启用' : '已禁用')
    } else { message.error(res?.message || '操作失败') }
  } catch (e: unknown) { message.error((e as Error).message || '操作失败') }
}
async function handleRemove(channel: ChannelData) {
  try {
    const res = await channelAPI.remove(channel.channel)
    if (res?.code === 0 || res?.success) {
      message.success('已删除')
      await loadChannels()
    } else { message.error(res?.message || '删除失败') }
  } catch (e: unknown) { message.error((e as Error).message || '删除失败') }
}
let sseSource: EventSource | null = null
let sseRetryTimer: ReturnType<typeof setTimeout> | null = null
function connectSSE() {
  if (sseSource) sseSource.close()
  if (sseRetryTimer) { clearTimeout(sseRetryTimer); sseRetryTimer = null }
  const token = localStorage.getItem('token')
  if (!token) return
  sseSource = new EventSource('/api/v1/channels/events')
  sseSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      if (data.event === 'error') {
        console.warn('SSE 错误事件:', data.message)
        sseSource?.close()
        sseSource = null
        return
      }
      if (data.event === 'init' || data.event === 'heartbeat') {
        for (const s of (data.channels || [])) {
          const ch = channels.value.find((c) => c.channel === s.channel)
          if (ch) {
            ch.health = s.health
            ch.totalRequests = s.totalRequests
            ch.totalErrors = s.totalErrors
          }
        }
      }
    } catch { /* ignore */ }
  }
  sseSource.onerror = () => {
    sseSource?.close()
    sseSource = null
    // 5 秒后自动重试
    sseRetryTimer = setTimeout(() => connectSSE(), 5000)
  }
}
onMounted(async () => {
  await initAgent()
  loadChannels().then(() => connectSSE())
})
onUnmounted(() => {
  if (sseRetryTimer) { clearTimeout(sseRetryTimer); sseRetryTimer = null }
  if (sseSource) { sseSource.close(); sseSource = null }
})
</script>
<style scoped>
.pg { display:flex;flex-direction:column;gap:14px;padding:24px; }
.hd { padding:14px 24px;border-radius:12px;display:flex;justify-content:space-between;align-items:center; }
.hd-actions { display:flex;gap:8px; }
.t { font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px; }
.sr { display:flex;gap:12px; }
.s { flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:0.85rem; }
.s b { font-size:1.4rem; }
.c1 { color:#10b981; }
.c2 { color:#f59e0b; }
.c3 { color:#34d399; }
.grid { display:grid;grid-template-columns:repeat(auto-fill, minmax(300px, 1fr));gap:14px; }
.card { padding:18px;border-radius:12px;display:flex;flex-direction:column;gap:10px;position:relative;cursor:pointer; }
.card-hover:hover { transform:translateY(-2px);transition:all 0.2s; }
.card-hover:hover { background:rgba(255,255,255,0.03); }
.status-dot { position:absolute;top:12px;right:14px;font-size:1.1rem; }
.status-dot.green { color:#34d399; }
.status-dot.gray { color:#64748b; }
.card-top { display:flex;align-items:center;gap:12px; }
.card-avatar { width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:1rem;flex-shrink:0; }
.card-meta { flex:1; }
.card-meta h4 { color:#e2e8f0;margin:0 0 4px;font-size:0.92rem; }
.card-tags { display:flex;gap:6px; }
.card-body { display:flex;flex-direction:column;gap:4px; }
.info-row { display:flex;align-items:center;gap:6px;color:rgba(255,255,255,0.35);font-size:0.78rem; }
.ii { font-size:0.8rem;opacity:0.5; }
.iv { font-family:monospace;font-size:0.75rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:260px; }
.card-actions { display:flex;gap:6px;flex-wrap:wrap;border-top:1px solid rgba(255,255,255,0.05);padding-top:10px; }
.empty-state { text-align:center;padding:60px 20px;border-radius:12px;display:flex;flex-direction:column;align-items:center;gap:14px; }
.empty-state p { color:rgba(255,255,255,0.3);margin:0; }
.pairing-section {
  border-radius: 12px;
  margin-top: 8px;
}
</style>
 