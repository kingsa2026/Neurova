&lt;template&gt;
  &lt;div &gt;
    &lt;!-- 页面标题 --&gt;
    &lt;div &gt;
      &lt;h2 &gt;
        &lt;SafetyOutlined :style="{ color: '#ef4444' }" /&gt;
        防火墙与合规
      &lt;/h2&gt;
      &lt;a-button type="primary" @click="loadGlobalRules"&gt;
        &lt;template #icon&gt;&lt;ReloadOutlined /&gt;&lt;/template&gt;
        刷新
      &lt;/a-button&gt;
    &lt;/div&gt;
    &lt;!-- 统计卡片 --&gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;div &gt;&lt;SafetyCertificateOutlined /&gt;&lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stats.blockedCount || 0 }}&lt;/div&gt;
          &lt;div &gt;已拦截&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;div &gt;&lt;CheckCircleOutlined /&gt;&lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stats.compliantRate || '100%' }}&lt;/div&gt;
          &lt;div &gt;合规率&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;div &gt;&lt;FileProtectOutlined /&gt;&lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stats.ruleCount || 0 }}&lt;/div&gt;
          &lt;div &gt;活跃规则&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- 标签页 --&gt;
    &lt;a-tabs v-model:activeKey="activeTab" &gt;
      &lt;a-tab-pane key="global" tab="全局规则"&gt;
        &lt;div &gt;
          &lt;div &gt;
            &lt;h3&gt;全局安全规则&lt;/h3&gt;
          &lt;/div&gt;
          &lt;a-form layout="vertical" &gt;
            &lt;a-form-item label="拦截的文件扩展名"&gt;
              &lt;a-select
                v-model:value="globalRules.blocked_extensions"
                mode="tags"
                placeholder="输入扩展名后按回车"
                style="width: 100%"
              /&gt;
            &lt;/a-form-item&gt;
            &lt;a-form-item label="拦截的路径"&gt;
              &lt;a-select
                v-model:value="globalRules.blocked_paths"
                mode="tags"
                placeholder="输入路径后按回车"
                style="width: 100%"
              /&gt;
            &lt;/a-form-item&gt;
            &lt;a-form-item label="拦截的模式"&gt;
              &lt;a-select
                v-model:value="globalRules.blocked_patterns"
                mode="tags"
                placeholder="输入正则模式后按回车"
                style="width: 100%"
              /&gt;
            &lt;/a-form-item&gt;
            &lt;a-row :gutter="16"&gt;
              &lt;a-col :span="12"&gt;
                &lt;a-form-item label="每分钟请求限制"&gt;
                  &lt;a-input-number
                    v-model:value="globalRules.rate_limit_per_minute"
                    :min="1"
                    :max="10000"
                    style="width: 100%"
                  /&gt;
                &lt;/a-form-item&gt;
              &lt;/a-col&gt;
              &lt;a-col :span="12"&gt;
                &lt;a-form-item label="最大载荷大小 (bytes)"&gt;
                  &lt;a-input-number
                    v-model:value="globalRules.max_payload_bytes"
                    :min="1024"
                    :max="104857600"
                    :step="1024"
                    style="width: 100%"
                  /&gt;
                &lt;/a-form-item&gt;
              &lt;/a-col&gt;
            &lt;/a-row&gt;
            &lt;a-row :gutter="16"&gt;
              &lt;a-col :span="12"&gt;
                &lt;a-form-item label="IP 白名单"&gt;
                  &lt;a-select
                    v-model:value="globalRules.ip_whitelist"
                    mode="tags"
                    placeholder="输入 IP 地址"
                    style="width: 100%"
                  /&gt;
                &lt;/a-form-item&gt;
              &lt;/a-col&gt;
              &lt;a-col :span="12"&gt;
                &lt;a-form-item label="IP 黑名单"&gt;
                  &lt;a-select
                    v-model:value="globalRules.ip_blacklist"
                    mode="tags"
                    placeholder="输入 IP 地址"
                    style="width: 100%"
                  /&gt;
                &lt;/a-form-item&gt;
              &lt;/a-col&gt;
            &lt;/a-row&gt;
            &lt;a-form-item&gt;
              &lt;a-space&gt;
                &lt;a-button type="primary" @click="handleUpdateGlobalRules" :loading="loading"&gt;
                  保存规则
                &lt;/a-button&gt;
                &lt;a-button @click="loadGlobalRules"&gt;重置&lt;/a-button&gt;
              &lt;/a-space&gt;
            &lt;/a-form-item&gt;
          &lt;/a-form&gt;
        &lt;/div&gt;
      &lt;/a-tab-pane&gt;
      &lt;a-tab-pane key="user" tab="用户规则"&gt;
        &lt;div &gt;
          &lt;div &gt;
            &lt;h3&gt;用户级防火墙规则&lt;/h3&gt;
          &lt;/div&gt;
          &lt;a-form layout="vertical" &gt;
            &lt;a-row :gutter="16"&gt;
              &lt;a-col :span="12"&gt;
                &lt;a-form-item label="额外拦截的扩展名"&gt;
                  &lt;a-select
                    v-model:value="userRules.extra_blocked_extensions"
                    mode="tags"
                    placeholder="输入扩展名后按回车"
                    style="width: 100%"
                  /&gt;
                &lt;/a-form-item&gt;
              &lt;/a-col&gt;
              &lt;a-col :span="12"&gt;
                &lt;a-form-item label="额外拦截的路径"&gt;
                  &lt;a-select
                    v-model:value="userRules.extra_blocked_paths"
                    mode="tags"
                    placeholder="输入路径后按回车"
                    style="width: 100%"
                  /&gt;
                &lt;/a-form-item&gt;
              &lt;/a-col&gt;
            &lt;/a-row&gt;
            &lt;a-form-item&gt;
              &lt;a-button type="primary" @click="handleUpdateUserRules" :loading="loading"&gt;
                保存用户规则
              &lt;/a-button&gt;
            &lt;/a-form-item&gt;
          &lt;/a-form&gt;
        &lt;/div&gt;
      &lt;/a-tab-pane&gt;
      &lt;a-tab-pane key="sandbox" tab="沙箱设置"&gt;
        &lt;div &gt;
          &lt;div &gt;
            &lt;h3&gt;Agent 间沙箱隔离&lt;/h3&gt;
          &lt;/div&gt;
          &lt;a-form layout="vertical" &gt;
            &lt;a-form-item label="启用 Agent 隔离"&gt;
              &lt;a-switch v-model:checked="sandbox.agent_isolation" /&gt;
              &lt;div &gt;
                启用后，不同 Agent 之间将无法直接访问彼此的内存、文件和配置
              &lt;/div&gt;
            &lt;/a-form-item&gt;
            &lt;a-form-item&gt;
              &lt;a-button type="primary" @click="handleUpdateSandbox" :loading="loading"&gt;
                保存沙箱设置
              &lt;/a-button&gt;
            &lt;/a-form-item&gt;
          &lt;/a-form&gt;
        &lt;/div&gt;
      &lt;/a-tab-pane&gt;
      &lt;a-tab-pane key="check" tab="路径检查"&gt;
        &lt;div &gt;
          &lt;div &gt;
            &lt;h3&gt;文件路径安全检查&lt;/h3&gt;
          &lt;/div&gt;
          &lt;a-form layout="inline" &gt;
            &lt;a-form-item label="路径"&gt;
              &lt;a-input
                v-model:value="checkPath"
                placeholder="输入要检查的文件路径"
                style="width: 400px"
              /&gt;
            &lt;/a-form-item&gt;
            &lt;a-form-item&gt;
              &lt;a-button type="primary" @click="handleCheckPath" :loading="checking"&gt;
                检查
              &lt;/a-button&gt;
            &lt;/a-form-item&gt;
          &lt;/a-form&gt;
          &lt;a-alert
            v-if="checkResult !== null"
            :type="checkResult.allowed ? 'success' : 'error'"
            :message="checkResult.allowed ? '路径安全' : '路径被拦截'"
            :description="checkResult.reason"
            show-icon
            style="margin-top: 16px"
          /&gt;
        &lt;/div&gt;
      &lt;/a-tab-pane&gt;
    &lt;/a-tabs&gt;
    &lt;!-- 拦截记录 --&gt;
    &lt;div &gt;
      &lt;h3&gt;
        &lt;WarningOutlined /&gt;
        拦截记录
      &lt;/h3&gt;
      &lt;a-timeline v-if="blockLogs.length &gt; 0"&gt;
        &lt;a-timeline-item
          v-for="log in blockLogs"
          :key="log.id"
          :color="getLogColor(log.type)"
        &gt;
          &lt;div &gt;
            &lt;div &gt;
              &lt;a-tag :color="getLogColor(log.type)"&gt;{{ log.type }}&lt;/a-tag&gt;
              &lt;span &gt;{{ formatTime(log.timestamp) }}&lt;/span&gt;
            &lt;/div&gt;
            &lt;div &gt;{{ log.message }}&lt;/div&gt;
            &lt;div  v-if="log.details"&gt;{{ log.details }}&lt;/div&gt;
          &lt;/div&gt;
        &lt;/a-timeline-item&gt;
      &lt;/a-timeline&gt;
      &lt;a-empty v-else description="暂无拦截记录" /&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  SafetyOutlined,
  SafetyCertificateOutlined,
  CheckCircleOutlined,
  FileProtectOutlined,
  ReloadOutlined,
  WarningOutlined,
} from '@ant-design/icons-vue'
import { request } from '@/api'
import { useAgentPage } from '@/composables/useAgentPage'
const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/firewall', () =&gt; loadData())
const loading = ref(false)
const checking = ref(false)
const activeTab = ref('global')
const stats = ref({
  blockedCount: 0,
  compliantRate: '100%',
  ruleCount: 0,
})
const globalRules = ref({
  blocked_extensions: [] as string[],
  blocked_paths: [] as string[],
  blocked_patterns: [] as string[],
  rate_limit_per_minute: 1000,
  max_payload_bytes: 10485760,
  ip_whitelist: [] as string[],
  ip_blacklist: [] as string[],
})
const userRules = ref({
  extra_blocked_extensions: [] as string[],
  extra_blocked_paths: [] as string[],
})
const sandbox = ref({
  agent_isolation: true,
})
const checkPath = ref('')
const checkResult = ref&lt;{ allowed: boolean; reason: string } | null&gt;(null)
interface BlockLog {
  id: string
  type: string
  message: string
  details?: string
  timestamp: number
}
const blockLogs = ref&lt;BlockLog[]&gt;([])
async function loadGlobalRules() {
  try {
    loading.value = true
    const res = await request.get(`/agents/${agentId.value}/firewall/global`)
    if (res.code === 0 &amp;&amp; res.data) {
      globalRules.value = res.data
    }
  } catch (error) {
    console.error('加载全局规则失败:', error)
    message.error('加载全局规则失败')
  } finally {
    loading.value = false
  }
}
async function handleUpdateGlobalRules() {
  try {
    loading.value = true
    await request.post(`/agents/${agentId.value}/firewall/global`, globalRules.value)
    message.success('全局规则已保存')
  } catch (error) {
    message.error('保存全局规则失败')
  } finally {
    loading.value = false
  }
}
async function handleUpdateUserRules() {
  try {
    loading.value = true
    await request.post(`/agents/${agentId.value}/firewall/user`, userRules.value)
    message.success('用户规则已保存')
  } catch (error) {
    message.error('保存用户规则失败')
  } finally {
    loading.value = false
  }
}
async function handleUpdateSandbox() {
  try {
    loading.value = true
    await request.post(`/agents/${agentId.value}/firewall/sandbox`, sandbox.value)
    message.success('沙箱设置已保存')
  } catch (error) {
    message.error('保存沙箱设置失败')
  } finally {
    loading.value = false
  }
}
async function handleCheckPath() {
  if (!checkPath.value.trim()) {
    message.warning('请输入要检查的路径')
    return
  }
  try {
    checking.value = true
    const res = await request.post(`/agents/${agentId.value}/firewall/check`, { path: checkPath.value })
    checkResult.value = {
      allowed: res.data.allowed ?? true,
      reason: res.data.reason || '',
    }
  } catch (error) {
    checkResult.value = {
      allowed: false,
      reason: '检查失败，请稍后重试',
    }
  } finally {
    checking.value = false
  }
}
function getLogColor(type: string) {
  switch (type) {
    case 'SQL注入':
      return 'red'
    case 'XSS':
      return 'red'
    case '敏感词':
      return 'orange'
    default:
      return 'blue'
  }
}
function formatTime(timestamp: number) {
  const diff = Date.now() - timestamp
  if (diff &lt; 60000) return '刚刚'
  if (diff &lt; 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff &lt; 86400000) return `${Math.floor(diff / 360000)}小时前`
  return new Date(timestamp).toLocaleDateString()
}
async function loadData() {
  // 加载统计数据
  try {
    const res = await request.get(`/agents/${agentId.value}/firewall/stats`)
    if (res.code === 0 &amp;&amp; res.data) {
      stats.value = res.data
    }
  } catch { /* 使用默认值 */ }
  // 加载拦截记录
  try {
    const res = await request.get(`/agents/${agentId.value}/firewall/logs`)
    if (res.code === 0 &amp;&amp; res.data) {
      blockLogs.value = res.data
    }
  } catch { /* 使用空数组 */ }
}
onMounted(async () =&gt; {
  if (!agentStore.agents.length) await agentStore.loadAgents()
  // 确保有选中的 agent
  if (agentStore.agents.length &amp;&amp; !agentId.value) {
    agentId.value = agentStore.agents[0].id
    agentStore.setCurrentAgent(agentId.value)
  }
  loadGlobalRules()
  loadData()
})
&lt;/script&gt;
&lt;style scoped&gt;
.pg {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px;
}
.hd {
  padding: 16px 24px;
  border-radius: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.t {
  font-size: 1.25rem;
  color: #e2e8f0;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.sr {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.s {
  padding: 20px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.s-icon {
  font-size: 2rem;
  color: #ef4444;
}
.s-info {
  flex: 1;
}
.s-num {
  font-size: 1.75rem;
  font-weight: 700;
  color: #e2e8f0;
  line-height: 1;
}
.s-label {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.6);
  margin-top: 4px;
}
.section {
  padding: 20px 0;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.section-header h3 {
  margin: 0;
  color: #e2e8f0;
}
.rules-form {
  max-width: 800px;
}
.check-form {
  margin-bottom: 20px;
}
.form-help {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.6);
  margin-top: 4px;
}
.log {
  padding: 20px;
  border-radius: 12px;
}
.log h3 {
  margin: 0 0 16px 0;
  color: #e2e8f0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.log-item {
  color: #e2e8f0;
}
.log-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.log-time {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.5);
}
.log-message {
  font-size: 0.9rem;
  margin-bottom: 2px;
}
.log-detail {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.6);
}
&lt;/style&gt;
&nbsp;