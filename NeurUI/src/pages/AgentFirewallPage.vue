<template>
  <div class="agent-firewall-page">
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">{{ t('system.firewall') }}</h2>
        <a-tag color="blue">{{ agentId }}</a-tag>
      </div>
      <div class="header-actions">
        <GlassButton variant="ghost" size="sm" :loading="loadingL0 || loadingL1 || loadingL2" @click="fetchRules">{{ t('common.refresh') }}</GlassButton>
        <GlassButton variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
      </div>
    </div>

    <div class="layer-overview">
      <GlassPanel variant="subtle" padding="12px 16px">
        <div class="layer-flow">
          <span class="layer-badge layer-l0">L0</span>
          <span class="layer-arrow">&rarr;</span>
          <span class="layer-badge layer-l1">L1</span>
          <span class="layer-arrow">&rarr;</span>
          <span class="layer-badge layer-l2">L2</span>
          <span class="layer-desc">{{ t('firewall.threeLayerDesc') }}</span>
        </div>
      </GlassPanel>
    </div>

    <a-tabs v-model:activeKey="activeTab">
      <!-- L0: Gateway Layer -->
      <a-tab-pane key="l0_gateway" :tab="t('firewall.gatewayTab')">
        <div class="layer-header">
          <a-tag color="blue">L0 {{ t('firewall.gateway') }}</a-tag>
          <span class="layer-description">{{ t('firewall.gatewayDescription') }}</span>
        </div>

        <!-- Gateway Settings -->
        <div class="gateway-settings">
          <GlassPanel variant="subtle" padding="16px 20px">
            <div class="settings-row">
              <div class="setting-item">
                <span class="setting-label">{{ t('firewall.rateLimit') }}</span>
                <span class="setting-value">{{ gatewayConfig.rateLimit || '120/min' }}</span>
              </div>
              <div class="setting-item">
                <span class="setting-label">{{ t('firewall.inputValidation') }}</span>
                <a-tag :color="gatewayConfig.inputValidation ? 'green' : 'default'">{{ gatewayConfig.inputValidation ? t('common.enabled') : t('common.disabled') }}</a-tag>
              </div>
              <div class="setting-item">
                <span class="setting-label">{{ t('firewall.outputSanitization') }}</span>
                <a-tag :color="gatewayConfig.outputSanitization ? 'green' : 'default'">{{ gatewayConfig.outputSanitization ? t('common.enabled') : t('common.disabled') }}</a-tag>
              </div>
            </div>
          </GlassPanel>
        </div>

        <!-- IP Rules Section -->
        <h4 class="section-title">{{ t('firewall.ipRules') }}</h4>
        <a-spin :spinning="loadingL0">
          <a-empty v-if="!loadingL0 && l0Rules.length === 0" :description="t('common.noData')" />
          <a-table
            v-else
            :columns="l0Columns"
            :data-source="l0Rules"
            row-key="id"
            :pagination="{ pageSize: 10 }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'pattern'">
                <code class="pattern-code">{{ record.pattern }}</code>
              </template>
              <template v-if="column.key === 'action'">
                <a-tag :color="actionColor(record.action)">{{ record.action }}</a-tag>
              </template>
              <template v-if="column.key === 'scope'">
                <a-tag :color="record.scope === 'inbound' ? 'cyan' : record.scope === 'outbound' ? 'purple' : 'default'">{{ record.scope || 'both' }}</a-tag>
              </template>
              <template v-if="column.key === 'active'">
                <a-switch :checked="record.active" size="small" @change="(val: boolean) => toggleRule(record.id, val)" />
              </template>
              <template v-if="column.key === 'actions'">
                <div class="rule-actions">
                  <GlassButton variant="ghost" size="sm" @click="editRule(record)">{{ t('common.edit') }}</GlassButton>
                  <a-popconfirm :title="t('common.confirm') + '?'" @confirm="deleteRule(record.id)">
                    <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
                  </a-popconfirm>
                </div>
              </template>
            </template>
          </a-table>
        </a-spin>
      </a-tab-pane>

      <!-- L1: Isolation Control Layer -->
      <a-tab-pane key="l1_isolation" :tab="t('firewall.isolationTab')">
        <div class="layer-header">
          <a-tag color="green">L1 {{ t('firewall.isolation') }}</a-tag>
          <span class="layer-description">{{ t('firewall.isolationDescription') }}</span>
        </div>

        <!-- Isolation Status -->
        <div class="isolation-status">
          <GlassPanel variant="subtle" padding="16px 20px">
            <div class="settings-row">
              <div class="setting-item">
                <span class="setting-label">{{ t('firewall.agentIsolation') }}</span>
                <a-switch :checked="isolationConfig.agentIsolation" size="small" @change="(val: boolean) => { isolationConfig.agentIsolation = val }" />
              </div>
              <div class="setting-item">
                <span class="setting-label">{{ t('firewall.userIsolation') }}</span>
                <a-switch :checked="isolationConfig.userIsolation" size="small" @change="(val: boolean) => { isolationConfig.userIsolation = val }" />
              </div>
              <div class="setting-item">
                <span class="setting-label">{{ t('firewall.currentIsolationKey') }}</span>
                <code class="pattern-code">agent:{{ agentId }}</code>
              </div>
            </div>
          </GlassPanel>
        </div>

        <!-- Effective Rules (merged view) -->
        <h4 class="section-title">
          {{ t('firewall.effectiveRules') }}
          <a-tooltip :title="t('firewall.effectiveRulesTooltip')">
            <span class="info-icon">&#9432;</span>
          </a-tooltip>
        </h4>
        <a-spin :spinning="loadingL1">
          <a-empty v-if="!loadingL1 && l1Rules.length === 0" :description="t('common.noData')" />
          <a-table
            v-else
            :columns="l1Columns"
            :data-source="l1Rules"
            row-key="id"
            :pagination="{ pageSize: 10 }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'pattern'">
                <code class="pattern-code">{{ record.pattern }}</code>
              </template>
              <template v-if="column.key === 'action'">
                <a-tag :color="actionColor(record.action)">{{ record.action }}</a-tag>
              </template>
              <template v-if="column.key === 'source'">
                <a-tag :color="record.source === 'global' ? 'default' : record.source === 'user' ? 'cyan' : 'purple'">{{ record.source || 'agent' }}</a-tag>
              </template>
              <template v-if="column.key === 'scope'">
                <a-tag :color="record.scope === 'inbound' ? 'cyan' : record.scope === 'outbound' ? 'purple' : 'default'">{{ record.scope || 'both' }}</a-tag>
              </template>
              <template v-if="column.key === 'active'">
                <a-switch :checked="record.active" size="small" @change="(val: boolean) => toggleRule(record.id, val)" />
              </template>
              <template v-if="column.key === 'actions'">
                <div class="rule-actions">
                  <GlassButton variant="ghost" size="sm" @click="editRule(record)">{{ t('common.edit') }}</GlassButton>
                  <a-popconfirm :title="t('common.confirm') + '?'" @confirm="deleteRule(record.id)">
                    <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
                  </a-popconfirm>
                </div>
              </template>
            </template>
          </a-table>
        </a-spin>
      </a-tab-pane>

      <!-- L2: File Protection Layer -->
      <a-tab-pane key="l2_file" :tab="t('firewall.fileProtectionTab')">
        <div class="layer-header">
          <a-tag color="orange">L2 {{ t('firewall.fileProtection') }}</a-tag>
          <span class="layer-description">{{ t('firewall.fileProtectionDesc') }}</span>
        </div>

        <!-- Protected Paths -->
        <h4 class="section-title">{{ t('firewall.protectedPaths') }}</h4>
        <div class="protected-paths">
          <GlassPanel variant="subtle" padding="12px 16px">
            <div class="path-list">
              <div v-for="path in protectedPaths" :key="path" class="path-item">
                <code class="pattern-code">{{ path }}</code>
              </div>
              <div v-if="protectedPaths.length === 0" class="path-empty">{{ t('firewall.noProtectedPaths') }}</div>
            </div>
          </GlassPanel>
        </div>

        <!-- File Access Rules -->
        <h4 class="section-title">{{ t('firewall.fileAccessRules') }}</h4>
        <a-spin :spinning="loadingL2">
          <a-empty v-if="!loadingL2 && l2Rules.length === 0" :description="t('common.noData')" />
          <a-table
            v-else
            :columns="l2Columns"
            :data-source="l2Rules"
            row-key="id"
            :pagination="{ pageSize: 10 }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'pattern'">
                <code class="pattern-code">{{ record.pattern }}</code>
              </template>
              <template v-if="column.key === 'action'">
                <a-tag :color="actionColor(record.action)">{{ record.action }}</a-tag>
              </template>
              <template v-if="column.key === 'active'">
                <a-switch :checked="record.active" size="small" @change="(val: boolean) => toggleRule(record.id, val)" />
              </template>
              <template v-if="column.key === 'actions'">
                <div class="rule-actions">
                  <GlassButton variant="ghost" size="sm" @click="editRule(record)">{{ t('common.edit') }}</GlassButton>
                  <a-popconfirm :title="t('common.confirm') + '?'" @confirm="deleteRule(record.id)">
                    <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
                  </a-popconfirm>
                </div>
              </template>
            </template>
          </a-table>
        </a-spin>
      </a-tab-pane>

      <!-- Blocked Requests Log -->
      <a-tab-pane key="blocked" :tab="t('firewall.blockedRequests')">
        <a-spin :spinning="loadingBlocked">
          <a-empty v-if="!loadingBlocked && blockedLogs.length === 0" :description="t('common.noData')" />
          <a-table
            v-else
            :columns="blockedColumns"
            :data-source="blockedLogs"
            row-key="id"
            :pagination="{ pageSize: 20 }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'timestamp'">
                <span class="mono">{{ formatTime(record.timestamp) }}</span>
              </template>
              <template v-if="column.key === 'layer'">
                <a-tag :color="layerColor(record.layer)">{{ record.layer || 'L0' }}</a-tag>
              </template>
              <template v-if="column.key === 'rule'">
                <a-tag>{{ record.rule_name || record.rule_id }}</a-tag>
              </template>
              <template v-if="column.key === 'action'">
                <a-tag :color="actionColor(record.action)">{{ record.action }}</a-tag>
              </template>
            </template>
          </a-table>
        </a-spin>
      </a-tab-pane>

      <!-- Stats tab -->
      <a-tab-pane key="stats" :tab="t('firewall.statistics')">
        <a-spin :spinning="loadingStats">
          <div class="stats-grid">
            <GlassPanel variant="subtle" padding="16px 20px">
              <div class="stat-item">
                <span class="stat-label">{{ t('firewall.totalRules') }}</span>
                <span class="stat-value">{{ stats.totalRules ?? 0 }}</span>
              </div>
            </GlassPanel>
            <GlassPanel variant="subtle" padding="16px 20px">
              <div class="stat-item">
                <span class="stat-label">{{ t('firewall.activeRules') }}</span>
                <span class="stat-value">{{ stats.activeRules ?? 0 }}</span>
              </div>
            </GlassPanel>
            <GlassPanel variant="subtle" padding="16px 20px">
              <div class="stat-item">
                <span class="stat-label">{{ t('firewall.blockedToday') }}</span>
                <span class="stat-value stat-danger">{{ stats.blockedToday ?? 0 }}</span>
              </div>
            </GlassPanel>
            <GlassPanel variant="subtle" padding="16px 20px">
              <div class="stat-item">
                <span class="stat-label">{{ t('firewall.warningsToday') }}</span>
                <span class="stat-value stat-warning">{{ stats.warningsToday ?? 0 }}</span>
              </div>
            </GlassPanel>
          </div>
        </a-spin>
      </a-tab-pane>
    </a-tabs>

    <!-- Create/Edit rule modal -->
    <a-modal
      v-model:open="showForm"
      :title="editingRule ? t('firewall.editRule') : t('firewall.createRule')"
      @ok="saveRule"
      :confirm-loading="saving"
      width="560px"
    >
      <a-form layout="vertical" :model="ruleForm">
        <a-form-item :label="t('firewall.ruleName')">
          <a-input v-model:value="ruleForm.name" :placeholder="t('firewall.ruleNamePlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('firewall.pattern')">
          <a-input v-model:value="ruleForm.pattern" :placeholder="t('firewall.patternPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('firewall.action')">
          <a-select v-model:value="ruleForm.action" style="width: 100%">
            <a-select-option value="block">{{ t('firewall.block') }}</a-select-option>
            <a-select-option value="allow">{{ t('firewall.allow') }}</a-select-option>
            <a-select-option value="warn">{{ t('firewall.warn') }}</a-select-option>
            <a-select-option value="redact">{{ t('firewall.redact') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('firewall.scope')">
          <a-select v-model:value="ruleForm.scope" style="width: 100%">
            <a-select-option value="inbound">{{ t('firewall.inbound') }}</a-select-option>
            <a-select-option value="outbound">{{ t('firewall.outbound') }}</a-select-option>
            <a-select-option value="both">{{ t('firewall.both') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('firewall.priority')">
          <a-input-number v-model:value="ruleForm.priority" :min="0" :max="1000" style="width: 100%" />
        </a-form-item>
        <a-form-item :label="t('firewall.description')">
          <a-input v-model:value="ruleForm.description" type="textarea" :rows="2" :placeholder="t('firewall.description')" />
        </a-form-item>
        <a-form-item :label="t('firewall.active')">
          <a-switch v-model:checked="ruleForm.active" />
        </a-form-item>
        <a-form-item :label="t('firewall.firewallLayer')">
          <a-select v-model:value="ruleForm.layer" style="width: 100%">
            <a-select-option value="L0">{{ t('firewall.l0GatewayDesc') }}</a-select-option>
            <a-select-option value="L1">{{ t('firewall.l1IsolationDesc') }}</a-select-option>
            <a-select-option value="L2">{{ t('firewall.l2FileProtectionDesc') }}</a-select-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { request } from '@/api'
import GlassButton from '@/components/GlassButton.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()
const route = useRoute()
const agentId = route.params.agentId as string

// --- State ---
const activeTab = ref('l0_gateway')
const loadingL0 = ref(false)
const loadingL1 = ref(false)
const loadingL2 = ref(false)
const loadingBlocked = ref(false)
const loadingStats = ref(false)
const saving = ref(false)
const l0Rules = ref<any[]>([])
const l1Rules = ref<any[]>([])
const l2Rules = ref<any[]>([])
const blockedLogs = ref<any[]>([])
const showForm = ref(false)
const editingRule = ref<any>(null)
const stats = ref<Record<string, number>>({})

const gatewayConfig = reactive({
  rateLimit: '120/min',
  inputValidation: true,
  outputSanitization: true,
})

const isolationConfig = reactive({
  agentIsolation: true,
  userIsolation: true,
})

const protectedPaths = ref<string[]>([
  '/etc/passwd', '/etc/shadow', '/etc/hosts',
  '~/.ssh', '~/.gnupg', '~/.aws',
  '**/.env', '**/credentials*', '**/*.key', '**/*.pem',
])

const ruleForm = ref({
  name: '',
  pattern: '',
  action: 'block',
  scope: 'both',
  priority: 100,
  active: true,
  description: '',
  layer: 'L0',
})

// --- Helpers ---
const formatTime = (ts: string) => (ts ? new Date(ts).toLocaleString() : '')

const actionColor = (action: string) => {
  const map: Record<string, string> = {
    block: 'red',
    allow: 'green',
    warn: 'orange',
    redact: 'purple',
  }
  return map[action] || 'default'
}

const layerColor = (layer: string) => {
  const map: Record<string, string> = {
    L0: 'blue',
    L1: 'green',
    L2: 'orange',
  }
  return map[layer] || 'default'
}

const l0Columns = computed(() => [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('firewall.pattern'), key: 'pattern' },
  { title: t('firewall.action'), key: 'action', width: 90 },
  { title: t('firewall.scope'), key: 'scope', width: 100 },
  { title: t('firewall.priority'), dataIndex: 'priority', key: 'priority', width: 80 },
  { title: t('firewall.active'), key: 'active', width: 80 },
  { title: t('common.actions'), key: 'actions', width: 160 },
])

const l1Columns = computed(() => [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('firewall.pattern'), key: 'pattern' },
  { title: t('firewall.action'), key: 'action', width: 90 },
  { title: t('firewall.source'), key: 'source', width: 90 },
  { title: t('firewall.scope'), key: 'scope', width: 100 },
  { title: t('firewall.active'), key: 'active', width: 80 },
  { title: t('common.actions'), key: 'actions', width: 160 },
])

const l2Columns = computed(() => [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('firewall.patternPath'), key: 'pattern' },
  { title: t('firewall.action'), key: 'action', width: 90 },
  { title: t('firewall.priority'), dataIndex: 'priority', key: 'priority', width: 80 },
  { title: t('firewall.active'), key: 'active', width: 80 },
  { title: t('common.actions'), key: 'actions', width: 160 },
])

const blockedColumns = computed(() => [
  { title: t('firewall.time'), key: 'timestamp', width: 180 },
  { title: t('firewall.layer'), key: 'layer', width: 70 },
  { title: t('firewall.rule'), key: 'rule' },
  { title: t('firewall.action'), key: 'action', width: 90 },
  { title: t('firewall.source'), dataIndex: 'source', key: 'source' },
  { title: t('firewall.content'), dataIndex: 'content', key: 'content', ellipsis: true },
])

// --- CRUD ---
const resetForm = () => {
  ruleForm.value = { name: '', pattern: '', action: 'block', scope: 'both', priority: 100, active: true, description: '', layer: 'L0' }
  editingRule.value = null
}

const openCreate = () => {
  resetForm()
  // Pre-fill the layer based on the active tab
  if (activeTab.value === 'l0_gateway') ruleForm.value.layer = 'L0'
  else if (activeTab.value === 'l1_isolation') ruleForm.value.layer = 'L1'
  else if (activeTab.value === 'l2_file') ruleForm.value.layer = 'L2'
  showForm.value = true
}

const editRule = (rule: any) => {
  editingRule.value = rule
  ruleForm.value = {
    name: rule.name,
    pattern: rule.pattern,
    action: rule.action,
    scope: rule.scope || 'both',
    priority: rule.priority,
    active: rule.active,
    description: rule.description || '',
    layer: rule.layer || 'L0',
  }
  showForm.value = true
}

const fetchL0Rules = async () => {
  loadingL0.value = true
  try {
    const res: any = await request.get(`/agents/${agentId}/firewall/rules`, { params: { layer: 'L0' } })
    const all = res?.data ?? res ?? []
    l0Rules.value = Array.isArray(all) ? all.filter((r: any) => r.layer === 'L0' || !r.layer) : []
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingL0.value = false
  }
}

const fetchL1Rules = async () => {
  loadingL1.value = true
  try {
    const res: any = await request.get(`/agents/${agentId}/firewall/rules`, { params: { layer: 'L1' } })
    const all = res?.data ?? res ?? []
    l1Rules.value = Array.isArray(all) ? all.filter((r: any) => r.layer === 'L1' || r.source === 'global' || r.source === 'user') : []
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingL1.value = false
  }
}

const fetchL2Rules = async () => {
  loadingL2.value = true
  try {
    const res: any = await request.get(`/agents/${agentId}/firewall/rules`, { params: { layer: 'L2' } })
    const all = res?.data ?? res ?? []
    l2Rules.value = Array.isArray(all) ? all.filter((r: any) => r.layer === 'L2') : []
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingL2.value = false
  }
}

const fetchAllRules = async () => {
  // Fetch once and distribute across layers
  try {
    const res: any = await request.get(`/firewall/rules`)
    // API may return {code,data:[...]} or direct array
    const raw = res?.data ?? res ?? []
    const all: any[] = Array.isArray(raw) ? raw : (raw?.data ?? [])
    if (Array.isArray(all)) {
      l0Rules.value = all.filter((r) => (r.layer === 'L0' || !r.layer) && (r.category === 'ip' || r.category === 'gateway' || !r.category || r.category === 'input' || r.category === 'output'))
      l1Rules.value = all.filter((r) => r.layer === 'L1' || r.source === 'global' || r.source === 'user')
      l2Rules.value = all.filter((r) => r.layer === 'L2' || r.category === 'file')
      // If the API doesn't use layer tags yet, put everything in L0 as fallback
      if (l0Rules.value.length === 0 && l1Rules.value.length === 0 && l2Rules.value.length === 0) {
        l0Rules.value = all
      }
    }
  } catch {
    message.error(t('common.error'))
  }
}

const fetchBlocked = async () => {
  loadingBlocked.value = true
  try {
    const res: any = await request.get(`/firewall/blocked`)
    // API returns {code,data:{blocked_ips:[],blocked_paths:[]}}
    const raw = res?.data ?? res ?? {}
    const data = raw?.data ?? raw ?? {}
    // Flatten blocked_ips and blocked_paths into a single array
    const ips = (data.blocked_ips ?? []).map((ip: string) => ({ type: 'ip', value: ip, blocked_at: '-' }))
    const paths = (data.blocked_paths ?? []).map((p: string) => ({ type: 'path', value: p, blocked_at: '-' }))
    blockedLogs.value = [...ips, ...paths]
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingBlocked.value = false
  }
}

const fetchStats = async () => {
  loadingStats.value = true
  try {
    const res: any = await request.get(`/firewall/stats`)
    stats.value = res?.data ?? res ?? {}
  } catch {
    // silently ignore stats errors
  } finally {
    loadingStats.value = false
  }
}

const fetchRules = () => fetchAllRules()

const saveRule = async () => {
  if (!ruleForm.value.name || !ruleForm.value.pattern) {
    message.warning(t('firewall.namePatternRequired'))
    return
  }
  saving.value = true
  try {
    if (editingRule.value) {
      await request.put(`/agents/${agentId}/firewall/rules/${editingRule.value.id}`, ruleForm.value)
    } else {
      await request.post(`/agents/${agentId}/firewall/rules`, ruleForm.value)
    }
    message.success(t('common.success'))
    showForm.value = false
    resetForm()
    await fetchAllRules()
    await fetchStats()
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

const toggleRule = async (id: string, active: boolean) => {
  try {
    await request.put(`/agents/${agentId}/firewall/rules/${id}`, { active })
    message.success(t('common.success'))
    await fetchAllRules()
    await fetchStats()
  } catch {
    message.error(t('common.error'))
  }
}

const deleteRule = async (id: string) => {
  try {
    await request.delete(`/agents/${agentId}/firewall/rules/${id}`)
    message.success(t('common.success'))
    await fetchAllRules()
    await fetchStats()
  } catch {
    message.error(t('common.error'))
  }
}

onMounted(() => {
  fetchAllRules()
  fetchBlocked()
  fetchStats()
})
</script>

<style scoped>
.agent-firewall-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.header-left { display: flex; align-items: center; gap: 12px; }
.header-actions { display: flex; gap: 8px; }
.pattern-code { font-family: var(--nr-font-mono); font-size: 12px; background: rgba(99,102,241,0.1); padding: 2px 6px; border-radius: 4px; color: var(--nr-primary-light, #6366f1); }
.rule-actions { display: flex; gap: 4px; }
.mono { font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-tertiary); }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px; }
.stat-item { display: flex; flex-direction: column; gap: 4px; }
.stat-label { font-size: 12px; color: var(--nr-text-tertiary); text-transform: uppercase; letter-spacing: 0.5px; }
.stat-value { font-family: var(--nr-font-display); font-size: 28px; font-weight: 700; color: var(--nr-text-primary); }
.stat-danger { color: #ef4444; }
.stat-warning { color: #f59e0b; }

/* Layer overview banner */
.layer-overview { margin-bottom: 4px; }
.layer-flow { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.layer-badge { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 6px; font-weight: 700; font-size: 13px; color: #fff; }
.layer-l0 { background: #3b82f6; }
.layer-l1 { background: #10b981; }
.layer-l2 { background: #f59e0b; }
.layer-arrow { color: var(--nr-text-tertiary); font-size: 16px; }
.layer-desc { font-size: 12px; color: var(--nr-text-secondary); margin-left: 8px; }

/* Layer tab headers */
.layer-header { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.layer-description { font-size: 13px; color: var(--nr-text-secondary); }

/* Settings rows used in L0/L1 panels */
.gateway-settings, .isolation-status { margin-bottom: 16px; }
.settings-row { display: flex; gap: 32px; flex-wrap: wrap; }
.setting-item { display: flex; flex-direction: column; gap: 4px; }
.setting-label { font-size: 11px; color: var(--nr-text-tertiary); text-transform: uppercase; letter-spacing: 0.5px; }
.setting-value { font-family: var(--nr-font-mono); font-size: 14px; font-weight: 600; color: var(--nr-text-primary); }

/* Section titles inside tabs */
.section-title { font-size: 14px; font-weight: 600; color: var(--nr-text-primary); margin: 16px 0 8px; display: flex; align-items: center; gap: 6px; }
.info-icon { font-size: 14px; color: var(--nr-text-tertiary); cursor: help; }

/* Protected paths list */
.protected-paths { margin-bottom: 16px; }
.path-list { display: flex; flex-wrap: wrap; gap: 8px; }
.path-item { display: inline-block; }
.path-empty { font-size: 13px; color: var(--nr-text-tertiary); }
</style>
