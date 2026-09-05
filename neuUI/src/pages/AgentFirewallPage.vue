<template>
  <div class="pg">
    <!-- 页面标题 -->
    <div class="hd glass-effect">
      <h2 class="t">
        <SafetyOutlined :style="{ color: '#ef4444' }" />
        防火墙与合规
      </h2>
      <a-button type="primary" @click="loadGlobalRules">
        <template #icon><ReloadOutlined /></template>
        刷新
      </a-button>
    </div>

    <!-- 统计卡片 -->
    <div class="sr">
      <div class="s glass-effect">
        <div class="s-icon"><SafetyCertificateOutlined /></div>
        <div class="s-info">
          <div class="s-num">{{ stats.blockedCount || 0 }}</div>
          <div class="s-label">已拦截</div>
        </div>
      </div>
      <div class="s glass-effect">
        <div class="s-icon"><CheckCircleOutlined /></div>
        <div class="s-info">
          <div class="s-num">{{ stats.compliantRate || '100%' }}</div>
          <div class="s-label">合规率</div>
        </div>
      </div>
      <div class="s glass-effect">
        <div class="s-icon"><FileProtectOutlined /></div>
        <div class="s-info">
          <div class="s-num">{{ stats.ruleCount || 0 }}</div>
          <div class="s-label">活跃规则</div>
        </div>
      </div>
    </div>

    <!-- 标签页 -->
    <a-tabs v-model:activeKey="activeTab" class="glass-effect">
      <a-tab-pane key="global" tab="全局规则">
        <div class="section">
          <div class="section-header">
            <h3>全局安全规则</h3>
          </div>

          <a-form layout="vertical" class="rules-form">
            <a-form-item label="拦截的文件扩展名">
              <a-select
                v-model:value="globalRules.blocked_extensions"
                mode="tags"
                placeholder="输入扩展名后按回车"
                style="width: 100%"
              />
            </a-form-item>

            <a-form-item label="拦截的路径">
              <a-select
                v-model:value="globalRules.blocked_paths"
                mode="tags"
                placeholder="输入路径后按回车"
                style="width: 100%"
              />
            </a-form-item>

            <a-form-item label="拦截的模式">
              <a-select
                v-model:value="globalRules.blocked_patterns"
                mode="tags"
                placeholder="输入正则模式后按回车"
                style="width: 100%"
              />
            </a-form-item>

            <a-row :gutter="16">
              <a-col :span="12">
                <a-form-item label="每分钟请求限制">
                  <a-input-number
                    v-model:value="globalRules.rate_limit_per_minute"
                    :min="1"
                    :max="10000"
                    style="width: 100%"
                  />
                </a-form-item>
              </a-col>
              <a-col :span="12">
                <a-form-item label="最大载荷大小 (bytes)">
                  <a-input-number
                    v-model:value="globalRules.max_payload_bytes"
                    :min="1024"
                    :max="104857600"
                    :step="1024"
                    style="width: 100%"
                  />
                </a-form-item>
              </a-col>
            </a-row>

            <a-row :gutter="16">
              <a-col :span="12">
                <a-form-item label="IP 白名单">
                  <a-select
                    v-model:value="globalRules.ip_whitelist"
                    mode="tags"
                    placeholder="输入 IP 地址"
                    style="width: 100%"
                  />
                </a-form-item>
              </a-col>
              <a-col :span="12">
                <a-form-item label="IP 黑名单">
                  <a-select
                    v-model:value="globalRules.ip_blacklist"
                    mode="tags"
                    placeholder="输入 IP 地址"
                    style="width: 100%"
                  />
                </a-form-item>
              </a-col>
            </a-row>

            <a-form-item>
              <a-space>
                <a-button type="primary" @click="handleUpdateGlobalRules" :loading="loading">
                  保存规则
                </a-button>
                <a-button @click="loadGlobalRules">重置</a-button>
              </a-space>
            </a-form-item>
          </a-form>
        </div>
      </a-tab-pane>

      <a-tab-pane key="user" tab="用户规则">
        <div class="section">
          <div class="section-header">
            <h3>用户级防火墙规则</h3>
          </div>

          <a-form layout="vertical" class="rules-form">
            <a-row :gutter="16">
              <a-col :span="12">
                <a-form-item label="额外拦截的扩展名">
                  <a-select
                    v-model:value="userRules.extra_blocked_extensions"
                    mode="tags"
                    placeholder="输入扩展名后按回车"
                    style="width: 100%"
                  />
                </a-form-item>
              </a-col>
              <a-col :span="12">
                <a-form-item label="额外拦截的路径">
                  <a-select
                    v-model:value="userRules.extra_blocked_paths"
                    mode="tags"
                    placeholder="输入路径后按回车"
                    style="width: 100%"
                  />
                </a-form-item>
              </a-col>
            </a-row>

            <a-form-item>
              <a-button type="primary" @click="handleUpdateUserRules" :loading="loading">
                保存用户规则
              </a-button>
            </a-form-item>
          </a-form>
        </div>
      </a-tab-pane>

      <a-tab-pane key="sandbox" tab="沙箱设置">
        <div class="section">
          <div class="section-header">
            <h3>Agent 间沙箱隔离</h3>
          </div>

          <a-form layout="vertical" class="rules-form">
            <a-form-item label="启用 Agent 隔离">
              <a-switch v-model:checked="sandbox.agent_isolation" />
              <div class="form-help">
                启用后，不同 Agent 之间将无法直接访问彼此的内存、文件和配置
              </div>
            </a-form-item>

            <a-form-item>
              <a-button type="primary" @click="handleUpdateSandbox" :loading="loading">
                保存沙箱设置
              </a-button>
            </a-form-item>
          </a-form>
        </div>
      </a-tab-pane>

      <a-tab-pane key="check" tab="路径检查">
        <div class="section">
          <div class="section-header">
            <h3>文件路径安全检查</h3>
          </div>

          <a-form layout="inline" class="check-form">
            <a-form-item label="路径">
              <a-input
                v-model:value="checkPath"
                placeholder="输入要检查的文件路径"
                style="width: 400px"
              />
            </a-form-item>
            <a-form-item>
              <a-button type="primary" @click="handleCheckPath" :loading="checking">
                检查
              </a-button>
            </a-form-item>
          </a-form>

          <a-alert
            v-if="checkResult !== null"
            :type="checkResult.allowed ? 'success' : 'error'"
            :message="checkResult.allowed ? '路径安全' : '路径被拦截'"
            :description="checkResult.reason"
            show-icon
            style="margin-top: 16px"
          />
        </div>
      </a-tab-pane>
    </a-tabs>

    <!-- 拦截记录 -->
    <div class="log glass-effect">
      <h3>
        <WarningOutlined />
        拦截记录
      </h3>
      <a-timeline v-if="blockLogs.length > 0">
        <a-timeline-item
          v-for="log in blockLogs"
          :key="log.id"
          :color="getLogColor(log.type)"
        >
          <div class="log-item">
            <div class="log-header">
              <a-tag :color="getLogColor(log.type)">{{ log.type }}</a-tag>
              <span class="log-time">{{ formatTime(log.timestamp) }}</span>
            </div>
            <div class="log-message">{{ log.message }}</div>
            <div class="log-detail" v-if="log.details">{{ log.details }}</div>
          </div>
        </a-timeline-item>
      </a-timeline>
      <a-empty v-else description="暂无拦截记录" />
    </div>
  </div>
</template>

<script setup lang="ts">
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

const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/firewall', () => loadData())

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
const checkResult = ref<{ allowed: boolean; reason: string } | null>(null)

interface BlockLog {
  id: string
  type: string
  message: string
  details?: string
  timestamp: number
}
const blockLogs = ref<BlockLog[]>([])

async function loadGlobalRules() {
  try {
    loading.value = true
    const res = await request.get(`/agents/${agentId.value}/firewall/global`)
    if (res.code === 0 && res.data) {
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
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 360000)}小时前`
  return new Date(timestamp).toLocaleDateString()
}

async function loadData() {
  // 加载统计数据
  try {
    const res = await request.get(`/agents/${agentId.value}/firewall/stats`)
    if (res.code === 0 && res.data) {
      stats.value = res.data
    }
  } catch { /* 使用默认值 */ }

  // 加载拦截记录
  try {
    const res = await request.get(`/agents/${agentId.value}/firewall/logs`)
    if (res.code === 0 && res.data) {
      blockLogs.value = res.data
    }
  } catch { /* 使用空数组 */ }
}

onMounted(async () => {
  if (!agentStore.agents.length) await agentStore.loadAgents()
  // 确保有选中的 agent
  if (agentStore.agents.length && !agentId.value) {
    agentId.value = agentStore.agents[0].id
    agentStore.setCurrentAgent(agentId.value)
  }
  loadGlobalRules()
  loadData()
})
</script>

<style scoped>
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
</style>
