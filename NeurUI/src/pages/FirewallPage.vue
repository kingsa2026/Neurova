<template>
  <div class="firewall-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.firewall') }}</h2>
      <GlassButton variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
    </div>

    <!-- Three-layer overview (conceptual map of the enforcement layers) -->
    <div class="layer-cascade-panel">
      <div class="cascade-header">
        <span class="cascade-title">{{ t('firewall.threeLayerArchitecture') }}</span>
      </div>
      <div class="cascade-flow">
        <div class="cascade-layer">
          <div class="cascade-badge cascade-l0">L0</div>
          <div class="cascade-label">{{ t('firewall.gateway') }}</div>
          <div class="cascade-desc">{{ t('firewall.gatewayDesc') }}</div>
        </div>
        <div class="cascade-arrow">&rarr;</div>
        <div class="cascade-layer">
          <div class="cascade-badge cascade-l1">L1</div>
          <div class="cascade-label">{{ t('firewall.isolation') }}</div>
          <div class="cascade-desc">{{ t('firewall.isolationDesc') }}</div>
        </div>
        <div class="cascade-arrow">&rarr;</div>
        <div class="cascade-layer">
          <div class="cascade-badge cascade-l2">L2</div>
          <div class="cascade-label">{{ t('firewall.fileProtection') }}</div>
          <div class="cascade-desc">{{ t('firewall.fileProtectionDesc') }}</div>
        </div>
      </div>
      <div class="priority-model">
        <span class="priority-label">{{ t('firewall.rulePriority') }}</span>
        <code class="priority-code">{{ t('firewall.effectiveRules') }}</code>
        <span class="priority-arrow">&rarr;</span>
        <code class="priority-code">{{ t('firewall.effectiveRulesTooltip') }}</code>
        <span class="priority-arrow">&rarr;</span>
        <code class="priority-code">{{ t('firewall.agentIsolation') }}</code>
      </div>
    </div>

    <a-tabs v-model:activeKey="activeTab">
      <!-- Rules tab -->
      <a-tab-pane key="rules" :tab="t('system.rules')">
        <a-spin :spinning="loading">
          <a-table
            v-if="rules.length > 0"
            :columns="ruleColumns"
            :data-source="rules"
            row-key="rule_id"
            :pagination="{ pageSize: 20 }"
            :locale="{ emptyText: '' }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'rule_type'">
                <a-tag :color="ruleTypeColor(record.rule_type)">{{ ruleTypeLabel(record.rule_type) }}</a-tag>
              </template>
              <template v-if="column.key === 'value'">
                <code class="pattern-code">{{ record.value }}</code>
              </template>
              <template v-if="column.key === 'action'">
                <a-tag :color="actionColor(record.action)">{{ actionLabel(record.action) }}</a-tag>
              </template>
              <template v-if="column.key === 'created_at'">
                <span class="mono">{{ formatTime(record.created_at) }}</span>
              </template>
              <template v-if="column.key === 'actions'">
                <div class="rule-actions">
                  <GlassButton variant="ghost" size="sm" @click="editRule(record)">{{ t('common.edit') }}</GlassButton>
                  <GlassButton
                    v-if="record.rule_type !== 'rate_limit'"
                    variant="danger"
                    size="sm"
                    @click="deleteRule(record)"
                  >
                    {{ t('common.delete') }}
                  </GlassButton>
                </div>
              </template>
            </template>
          </a-table>
          <a-empty v-else :description="t('common.noData')" />
        </a-spin>
      </a-tab-pane>

      <!-- Blocked entries (IP blacklist / path blacklist as enforced) -->
      <a-tab-pane key="blocked" :tab="t('firewall.blockedRequests')">
        <a-spin :spinning="loadingBlocked">
          <a-table
            v-if="blockedRows.length > 0"
            :columns="blockedColumns"
            :data-source="blockedRows"
            row-key="key"
            :pagination="{ pageSize: 20 }"
            :locale="{ emptyText: '' }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'kind'">
                <a-tag :color="record.kind === 'ip' ? 'blue' : 'orange'">{{ record.kind === 'ip' ? t('firewall.ruleTypeIp') : t('firewall.ruleTypePath') }}</a-tag>
              </template>
              <template v-if="column.key === 'value'">
                <code class="pattern-code">{{ record.value }}</code>
              </template>
            </template>
          </a-table>
          <a-empty v-else :description="t('common.noData')" />
        </a-spin>
      </a-tab-pane>
    </a-tabs>

    <!-- Create/Edit rule modal -->
    <a-modal v-model:open="showForm" :title="editingRule ? t('common.edit') : t('common.create')" @ok="saveRule" :confirm-loading="saving">
      <a-form layout="vertical" :model="ruleForm" :rules="{ name: [{ required: true, message: t('common.required') }], value: [{ required: true, message: t('common.required') }] }">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="ruleForm.name" />
        </a-form-item>
        <a-form-item :label="t('firewall.ruleType')">
          <a-select v-model:value="ruleForm.rule_type" style="width: 100%" :disabled="!!editingRule" @change="onRuleTypeChange">
            <a-select-option value="ip">{{ t('firewall.ruleTypeIp') }}</a-select-option>
            <a-select-option value="path">{{ t('firewall.ruleTypePath') }}</a-select-option>
            <a-select-option value="rate_limit">{{ t('firewall.ruleTypeRateLimit') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('firewall.action')">
          <a-select v-model:value="ruleForm.action" style="width: 100%">
            <a-select-option v-for="opt in actionOptions" :key="opt" :value="opt">{{ actionLabel(opt) }}</a-select-option>
          </a-select>
        </a-form-item>
        <template v-if="ruleForm.rule_type === 'rate_limit'">
          <a-form-item :label="t('firewall.window')">
            <a-select v-model:value="ruleForm.window" style="width: 100%" :disabled="!!editingRule">
              <a-select-option value="minute">{{ t('firewall.windowMinute') }}</a-select-option>
              <a-select-option value="hour">{{ t('firewall.windowHour') }}</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item :label="t('firewall.value')">
            <a-input-number v-model:value="rateValue" :min="1" style="width: 100%" />
          </a-form-item>
        </template>
        <a-form-item v-else :label="t('firewall.value')">
          <a-input v-model:value="ruleForm.value" :placeholder="valuePlaceholder" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import GlassButton from '@/components/GlassButton.vue'
import { message, Modal } from 'ant-design-vue'
import * as firewallApi from '@/api/modules/firewall'
import type { FirewallRule } from '@/api/modules/firewall'

const { t } = useI18n()

const activeTab = ref('rules')
const loading = ref(false)
const loadingBlocked = ref(false)
const saving = ref(false)
const rules = ref<FirewallRule[]>([])
const blockedRows = ref<{ key: string; kind: 'ip' | 'path'; value: string }[]>([])
const showForm = ref(false)
const editingRule = ref<FirewallRule | null>(null)

const ruleForm = ref({ name: '', rule_type: 'ip', action: 'block', value: '', window: 'minute' })
const rateValue = ref<number>(60)

// 后端真实语义：ip→block/allow，path→block，rate_limit→limit
const actionOptions = computed(() => {
  if (ruleForm.value.rule_type === 'ip') return ['block', 'allow']
  if (ruleForm.value.rule_type === 'rate_limit') return ['limit']
  return ['block']
})

const valuePlaceholder = computed(() =>
  ruleForm.value.rule_type === 'ip' ? '1.2.3.4' : '/data/secret',
)

const formatTime = (ts: number) => ts ? new Date(ts * 1000).toLocaleString() : ''

const ruleTypeLabel = (rt: string) => ({
  ip: t('firewall.ruleTypeIp'),
  path: t('firewall.ruleTypePath'),
  rate_limit: t('firewall.ruleTypeRateLimit'),
}[rt] || rt)

const actionLabel = (a: string) => ({
  block: t('firewall.block'),
  allow: t('firewall.allow'),
  limit: t('firewall.actionLimit'),
}[a] || a)

const ruleTypeColor = (rt: string) => ({ ip: 'blue', path: 'orange', rate_limit: 'purple' }[rt] || 'default')
const actionColor = (a: string) => ({ block: 'red', allow: 'green', limit: 'orange' }[a] || 'default')

const onRuleTypeChange = () => {
  ruleForm.value.action = actionOptions.value[0]
}

const ruleColumns = computed(() => [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('firewall.ruleType'), key: 'rule_type', width: 100 },
  { title: t('firewall.action'), key: 'action', width: 80 },
  { title: t('firewall.value'), key: 'value' },
  { title: t('firewall.time'), key: 'created_at', width: 180 },
  { title: t('common.actions'), key: 'actions', width: 140 },
])

const blockedColumns = computed(() => [
  { title: t('firewall.ruleType'), key: 'kind', width: 100 },
  { title: t('firewall.value'), key: 'value' },
])

const fetchRules = async () => {
  loading.value = true
  try {
    const res: any = await firewallApi.getFirewallRules()
    rules.value = Array.isArray(res) ? res : []
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const fetchBlocked = async () => {
  loadingBlocked.value = true
  try {
    const res: any = await firewallApi.getBlockedEntries()
    const lists = res?.data ?? res ?? {}
    blockedRows.value = [
      ...(lists.blocked_ips ?? []).map((ip: string) => ({ key: `ip-${ip}`, kind: 'ip' as const, value: ip })),
      ...(lists.blocked_paths ?? []).map((p: string) => ({ key: `path-${p}`, kind: 'path' as const, value: p })),
    ]
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingBlocked.value = false
  }
}

const openCreate = () => {
  editingRule.value = null
  ruleForm.value = { name: '', rule_type: 'ip', action: 'block', value: '', window: 'minute' }
  rateValue.value = 60
  showForm.value = true
}

const editRule = (rule: FirewallRule) => {
  editingRule.value = rule
  ruleForm.value = {
    name: rule.name,
    rule_type: rule.rule_type,
    action: rule.action,
    value: rule.value,
    window: rule.rule_id === 'rate_limit_hour' ? 'hour' : 'minute',
  }
  if (rule.rule_type === 'rate_limit') rateValue.value = Number(rule.value) || 60
  showForm.value = true
}

const saveRule = async () => {
  saving.value = true
  try {
    const isRate = ruleForm.value.rule_type === 'rate_limit'
    const payload = {
      name: ruleForm.value.name,
      rule_type: ruleForm.value.rule_type,
      action: ruleForm.value.action,
      value: isRate ? String(rateValue.value) : ruleForm.value.value,
      window: isRate ? ruleForm.value.window : undefined,
    }
    if (editingRule.value) {
      // 速率规则按合成 id PUT 真更新；ip/path 按原 rule_id 更新值
      await firewallApi.updateFirewallRule(editingRule.value.rule_id, payload)
    } else {
      await firewallApi.createFirewallRule(payload)
    }
    message.success(t('common.success'))
    showForm.value = false
    await Promise.all([fetchRules(), fetchBlocked()])
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || t('common.error'))
  } finally {
    saving.value = false
  }
}

const deleteRule = (rule: FirewallRule) => {
  Modal.confirm({
    title: t('common.confirm'),
    content: t('agent.deleteConfirm'),
    onOk: async () => {
      try {
        await firewallApi.deleteFirewallRule(rule.rule_id)
        message.success(t('common.success'))
        await Promise.all([fetchRules(), fetchBlocked()])
      } catch {
        message.error(t('common.error'))
      }
    },
  })
}

onMounted(() => {
  fetchRules()
  fetchBlocked()
})
</script>

<style scoped>
.firewall-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.pattern-code { font-family: var(--nr-font-mono); font-size: 12px; background: rgba(99,102,241,0.1); padding: 2px 6px; border-radius: 4px; color: var(--nr-primary-light, #6366f1); }
.rule-actions { display: flex; gap: 4px; }
.mono { font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-tertiary); }

/* Cascade panel */
.layer-cascade-panel {
  border: 1px solid var(--nr-glass-border, rgba(255,255,255,0.08));
  border-radius: 10px;
  padding: 16px 20px;
  background: var(--nr-glass-bg-subtle, rgba(255,255,255,0.03));
}
.cascade-header { margin-bottom: 12px; }
.cascade-title { font-size: 14px; font-weight: 600; color: var(--nr-text-primary); }
.cascade-flow { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.cascade-layer { display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 100px; }
.cascade-badge { width: 36px; height: 36px; display: inline-flex; align-items: center; justify-content: center; border-radius: 8px; font-weight: 700; font-size: 14px; color: var(--nr-text-primary); }
.cascade-l0 { background: var(--nr-info); }
.cascade-l1 { background: var(--nr-success); }
.cascade-l2 { background: var(--nr-warning); }
.cascade-label { font-size: 12px; font-weight: 600; color: var(--nr-text-primary); }
.cascade-desc { font-size: 11px; color: var(--nr-text-tertiary); text-align: center; }
.cascade-arrow { font-size: 18px; color: var(--nr-text-tertiary); margin-top: -16px; }

/* Priority model */
.priority-model { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding-top: 12px; border-top: 1px solid var(--nr-glass-border, rgba(255,255,255,0.06)); }
.priority-label { font-size: 12px; font-weight: 600; color: var(--nr-text-secondary); }
.priority-code { font-family: var(--nr-font-mono); font-size: 11px; background: rgba(99,102,241,0.1); padding: 2px 8px; border-radius: 4px; color: var(--nr-primary-light, #6366f1); }
.priority-arrow { font-size: 12px; color: var(--nr-text-tertiary); }
</style>
