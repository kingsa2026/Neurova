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
            row-key="rule_id"
            :pagination="{ pageSize: 10 }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'value'">
                <code class="pattern-code">{{ record.value }}</code>
              </template>
              <template v-if="column.key === 'action'">
                <a-tag :color="actionColor(record.action)">{{ record.action }}</a-tag>
              </template>
              <template v-if="column.key === 'enabled'">
                <a-switch :checked="record.enabled" size="small" @change="(val: boolean) => toggleRule(record, val)" />
              </template>
              <template v-if="column.key === 'actions'">
                <div class="rule-actions">
                  <GlassButton variant="ghost" size="sm" @click="editRule(record)">{{ t('common.edit') }}</GlassButton>
                  <a-popconfirm :title="t('common.confirm') + '?'" @confirm="deleteRule(record.rule_id)">
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
            row-key="rule_id"
            :pagination="{ pageSize: 10 }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'value'">
                <code class="pattern-code">{{ record.value }}</code>
              </template>
              <template v-if="column.key === 'action'">
                <a-tag :color="actionColor(record.action)">{{ record.action }}</a-tag>
              </template>
              <template v-if="column.key === 'enabled'">
                <a-switch :checked="record.enabled" size="small" @change="(val: boolean) => toggleRule(record, val)" />
              </template>
              <template v-if="column.key === 'actions'">
                <div class="rule-actions">
                  <GlassButton variant="ghost" size="sm" @click="editRule(record)">{{ t('common.edit') }}</GlassButton>
                  <a-popconfirm :title="t('common.confirm') + '?'" @confirm="deleteRule(record.rule_id)">
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
            row-key="rule_id"
            :pagination="{ pageSize: 10 }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'value'">
                <code class="pattern-code">{{ record.value }}</code>
              </template>
              <template v-if="column.key === 'action'">
                <a-tag :color="actionColor(record.action)">{{ record.action }}</a-tag>
              </template>
              <template v-if="column.key === 'enabled'">
                <a-switch :checked="record.enabled" size="small" @change="(val: boolean) => toggleRule(record, val)" />
              </template>
              <template v-if="column.key === 'actions'">
                <div class="rule-actions">
                  <GlassButton variant="ghost" size="sm" @click="editRule(record)">{{ t('common.edit') }}</GlassButton>
                  <a-popconfirm :title="t('common.confirm') + '?'" @confirm="deleteRule(record.rule_id)">
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
            row-key="value"
            :pagination="{ pageSize: 20 }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'type'">
                <a-tag :color="record.type === 'ip' ? 'blue' : 'orange'">{{ record.type }}</a-tag>
              </template>
              <template v-if="column.key === 'value'">
                <code class="pattern-code">{{ record.value }}</code>
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
                <span class="stat-value">{{ stats.total_rules ?? 0 }}</span>
              </div>
            </GlassPanel>
            <GlassPanel variant="subtle" padding="16px 20px">
              <div class="stat-item">
                <span class="stat-label">{{ t('firewall.activeRules') }}</span>
                <span class="stat-value">{{ stats.active_rules ?? 0 }}</span>
              </div>
            </GlassPanel>
            <GlassPanel variant="subtle" padding="16px 20px">
              <div class="stat-item">
                <span class="stat-label">{{ t('firewall.blockedToday') }}</span>
                <span class="stat-value stat-danger">{{ stats.blocked_ips ?? 0 }}</span>
              </div>
            </GlassPanel>
            <GlassPanel variant="subtle" padding="16px 20px">
              <div class="stat-item">
                <span class="stat-label">{{ t('firewall.warningsToday') }}</span>
                <span class="stat-value stat-warning">{{ stats.blocked_paths ?? 0 }}</span>
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
        <a-form-item :label="t('firewall.value')">
          <a-input v-model:value="ruleForm.pattern" :placeholder="t('firewall.patternPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('firewall.action')">
          <a-select v-model:value="ruleForm.action" style="width: 100%">
            <a-select-option value="block">{{ t('firewall.block') }}</a-select-option>
            <a-select-option value="allow">{{ t('firewall.allow') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('firewall.active')">
          <a-switch v-model:checked="ruleForm.active" />
        </a-form-item>
        <a-form-item :label="t('firewall.firewallLayer')">
          <a-select v-model:value="ruleForm.layer" style="width: 100%">
            <a-select-option value="L0">{{ t('firewall.l0GatewayDesc') }}</a-select-option>
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
import { useAgentPage } from '@/composables/useAgentPage'
import GlassButton from '@/components/GlassButton.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import { message } from 'ant-design-vue'
import {
  getFirewallRules,
  createFirewallRule,
  updateFirewallRule,
  deleteFirewallRule,
  getBlockedEntries,
  getFirewallStats,
} from '@/api/modules/firewall'
import type { FirewallRule, RuleCreatePayload, FirewallStats } from '@/api/modules/firewall'

const { t } = useI18n()
const { agentId } = useAgentPage()
// 读写两侧端点都是全局的（/firewall/*，无 agent 维度，P1-10 审计 2026-11-14：
// 旧页面的 /agents/{id}/firewall/rules/* 路径后端不存在，改/停/删恒 404）。
// 身份跟随 store 只影响展示标签（T-21 同根因扫荡，工单集 §45.2）。

// --- State ---
const activeTab = ref('l0_gateway')
const loadingL0 = ref(false)
const loadingL1 = ref(false)
const loadingL2 = ref(false)
const loadingBlocked = ref(false)
const loadingStats = ref(false)
const saving = ref(false)
const l0Rules = ref<FirewallRule[]>([])
const l1Rules = ref<FirewallRule[]>([])
const l2Rules = ref<FirewallRule[]>([])
const blockedLogs = ref<Array<{ type: string; value: string }>>([])
const showForm = ref(false)
const editingRule = ref<FirewallRule | null>(null)
const stats = ref<Partial<FirewallStats>>({})

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
  active: true,
  layer: 'L0',
})

// --- Helpers ---

const actionColor = (action: string) => {
  const map: Record<string, string> = {
    block: 'red',
    allow: 'green',
    warn: 'orange',
    redact: 'purple',
  }
  return map[action] || 'default'
}

const l0Columns = computed(() => [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('firewall.value'), key: 'value' },
  { title: t('firewall.action'), key: 'action', width: 90 },
  { title: t('firewall.active'), key: 'enabled', width: 80 },
  { title: t('common.actions'), key: 'actions', width: 160 },
])

const l1Columns = computed(() => [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('firewall.value'), key: 'value' },
  { title: t('firewall.action'), key: 'action', width: 90 },
  { title: t('firewall.active'), key: 'enabled', width: 80 },
  { title: t('common.actions'), key: 'actions', width: 160 },
])

const l2Columns = computed(() => [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('firewall.value'), key: 'value' },
  { title: t('firewall.action'), key: 'action', width: 90 },
  { title: t('firewall.active'), key: 'enabled', width: 80 },
  { title: t('common.actions'), key: 'actions', width: 160 },
])

const blockedColumns = computed(() => [
  { title: t('firewall.ruleType'), key: 'type', width: 100 },
  { title: t('firewall.value'), key: 'value' },
])

// --- CRUD ---
const resetForm = () => {
  ruleForm.value = { name: '', pattern: '', action: 'block', active: true, layer: 'L0' }
  editingRule.value = null
}

const openCreate = () => {
  resetForm()
  // Pre-fill the layer based on the active tab
  if (activeTab.value === 'l0_gateway') ruleForm.value.layer = 'L0'
  else if (activeTab.value === 'l2_file') ruleForm.value.layer = 'L2'
  showForm.value = true
}

const editRule = (rule: FirewallRule) => {
  editingRule.value = rule
  ruleForm.value = {
    name: rule.name,
    pattern: rule.value,
    action: rule.action,
    active: rule.enabled,
    layer: rule.rule_type === 'path' ? 'L2' : 'L0',
  }
  showForm.value = true
}

const fetchAllRules = async () => {
  loadingL0.value = loadingL1.value = loadingL2.value = true
  try {
    const res = await getFirewallRules()
    const all: FirewallRule[] = Array.isArray(res) ? res : []
    // 后端规则无 layer 维度，按 rule_type 分层：path → L2 文件保护，
    // 其余（ip/rate_limit）→ L0 网关；L1 隔离层后端无独立规则存储，
    // 该页签保持空态，不造假数据。
    l0Rules.value = all.filter((r) => r.rule_type !== 'path')
    l1Rules.value = []
    l2Rules.value = all.filter((r) => r.rule_type === 'path')
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingL0.value = loadingL1.value = loadingL2.value = false
  }
}

const fetchBlocked = async () => {
  loadingBlocked.value = true
  try {
    const res: any = await getBlockedEntries()
    // API returns {code,data:{blocked_ips:[],blocked_paths:[]}}
    const data = res?.data ?? res ?? {}
    blockedLogs.value = [
      ...(data.blocked_ips ?? []).map((ip: string) => ({ type: 'ip', value: ip })),
      ...(data.blocked_paths ?? []).map((p: string) => ({ type: 'path', value: p })),
    ]
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingBlocked.value = false
  }
}

const fetchStats = async () => {
  loadingStats.value = true
  try {
    const res: any = await getFirewallStats()
    stats.value = res?.data ?? res ?? {}
  } catch {
    // 统计读数失败不拦截主功能，保留空读数（不造假 0 假成功提示）
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
    // 后端 PUT/POST 体是 FirewallRuleCreate(name, value, rule_type, action,
    // enabled, window)（firewall.py，P1-10 核对）。表单的 pattern/active/layer
    // 在这里映射为契约字段；L1 隔离层后端无独立规则型，落 ip 型。
    const layerRuleType: Record<string, string> = { L0: 'ip', L1: 'ip', L2: 'path' }
    const payload: RuleCreatePayload = {
      name: ruleForm.value.name,
      rule_type: layerRuleType[ruleForm.value.layer] ?? 'ip',
      action: ruleForm.value.action,
      value: ruleForm.value.pattern,
      enabled: ruleForm.value.active,
    }
    if (editingRule.value) {
      await updateFirewallRule(editingRule.value.rule_id, payload)
    } else {
      await createFirewallRule(payload)
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

const toggleRule = async (rule: FirewallRule, active: boolean) => {
  try {
    // PUT 体必须满足 FirewallRuleCreate 必填的 name/value；规则身份
    // （rule_type/action/旧值）由 rule_id 携带，这里带全量契约字段。
    await updateFirewallRule(rule.rule_id, {
      name: rule.name,
      rule_type: rule.rule_type,
      action: rule.action,
      value: rule.value,
      enabled: active,
    })
    message.success(t('common.success'))
    await fetchAllRules()
    await fetchStats()
  } catch {
    message.error(t('common.error'))
  }
}

const deleteRule = async (ruleId: string) => {
  try {
    await deleteFirewallRule(ruleId)
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
.stat-danger { color: var(--nr-error); }
.stat-warning { color: var(--nr-warning); }

/* Layer overview banner */
.layer-overview { margin-bottom: 4px; }
.layer-flow { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.layer-badge { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 6px; font-weight: 700; font-size: 13px; color: var(--nr-text-primary); }
.layer-l0 { background: var(--nr-info); }
.layer-l1 { background: var(--nr-success); }
.layer-l2 { background: var(--nr-warning); }
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
