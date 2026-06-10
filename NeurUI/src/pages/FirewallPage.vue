<template>
  <div class="firewall-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.firewall') }}</h2>
      <GlassButton variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
    </div>

    <!-- Three-layer overview with cascade visualization -->
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
            :columns="ruleColumns"
            :data-source="rules"
            row-key="id"
            :pagination="{ pageSize: 20 }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'layer'">
                <a-tag :color="layerColor(record.layer)">{{ record.layer || 'L0' }}</a-tag>
              </template>
              <template v-if="column.key === 'pattern'">
                <code class="pattern-code">{{ record.pattern }}</code>
              </template>
              <template v-if="column.key === 'action'">
                <a-tag :color="record.action === 'block' ? 'red' : record.action === 'allow' ? 'green' : 'orange'">{{ record.action }}</a-tag>
              </template>
              <template v-if="column.key === 'active'">
                <a-switch :checked="record.active" size="small" @change="(val: boolean) => toggleRule(record.id, val)" />
              </template>
              <template v-if="column.key === 'actions'">
                <div class="rule-actions">
                  <GlassButton variant="ghost" size="sm" @click="editRule(record)">{{ t('common.edit') }}</GlassButton>
                  <GlassButton variant="danger" size="sm" @click="deleteRule(record.id)">{{ t('common.delete') }}</GlassButton>
                </div>
              </template>
            </template>
          </a-table>
        </a-spin>
      </a-tab-pane>

      <!-- Blocked requests log -->
      <a-tab-pane key="blocked" :tab="t('firewall.blockedRequests')">
        <a-spin :spinning="loadingBlocked">
          <a-table :columns="blockedColumns" :data-source="blockedLogs" row-key="id" :pagination="{ pageSize: 20 }" size="small">
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
            </template>
          </a-table>
        </a-spin>
      </a-tab-pane>
    </a-tabs>

    <!-- Create/Edit rule modal -->
    <a-modal v-model:open="showForm" :title="editingRule ? t('common.edit') : t('common.create')" @ok="saveRule" :confirm-loading="saving">
      <a-form layout="vertical" :model="ruleForm">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="ruleForm.name" />
        </a-form-item>
        <a-form-item :label="t('firewall.pattern')">
          <a-input v-model:value="ruleForm.pattern" :placeholder="t('firewall.patternPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('firewall.action')">
          <a-select v-model:value="ruleForm.action" style="width: 100%">
            <a-select-option value="block">{{ t('firewall.block') }}</a-select-option>
            <a-select-option value="allow">{{ t('firewall.allow') }}</a-select-option>
            <a-select-option value="warn">{{ t('firewall.warn') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('firewall.priority')">
          <a-input-number v-model:value="ruleForm.priority" :min="0" :max="1000" style="width: 100%" />
        </a-form-item>
        <a-form-item :label="t('firewall.firewallLayer')">
          <a-select v-model:value="ruleForm.layer" style="width: 100%">
            <a-select-option value="L0">{{ t('firewall.l0GatewayDesc') }}</a-select-option>
            <a-select-option value="L1">{{ t('firewall.l1IsolationDesc') }}</a-select-option>
            <a-select-option value="L2">{{ t('firewall.l2FileProtectionDesc') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('firewall.active')">
          <a-switch v-model:checked="ruleForm.active" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassButton from '@/components/GlassButton.vue'
import { message, Modal } from 'ant-design-vue'

const { t } = useI18n()

const activeTab = ref('rules')
const loading = ref(false)
const loadingBlocked = ref(false)
const saving = ref(false)
const rules = ref<any[]>([])
const blockedLogs = ref<any[]>([])
const showForm = ref(false)
const editingRule = ref<any>(null)

const ruleForm = ref({ name: '', pattern: '', action: 'block', priority: 100, active: true, layer: 'L0' })

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const layerColor = (layer: string) => {
  const map: Record<string, string> = { L0: 'blue', L1: 'green', L2: 'orange' }
  return map[layer] || 'default'
}

const ruleColumns = computed(() => [
  { title: t('firewall.layer'), key: 'layer', width: 70 },
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('firewall.pattern'), key: 'pattern' },
  { title: t('firewall.action'), key: 'action', width: 80 },
  { title: t('firewall.priority'), dataIndex: 'priority', key: 'priority', width: 80 },
  { title: t('common.active'), key: 'active', width: 80 },
  { title: t('common.actions'), key: 'actions', width: 140 },
])

const blockedColumns = computed(() => [
  { title: t('firewall.time'), key: 'timestamp', width: 180 },
  { title: t('firewall.layer'), key: 'layer', width: 70 },
  { title: t('firewall.rule'), key: 'rule' },
  { title: t('firewall.source'), dataIndex: 'source', key: 'source' },
  { title: t('firewall.content'), dataIndex: 'content', key: 'content', ellipsis: true },
])

const fetchRules = async () => {
  loading.value = true
  try {
    const res: any = await request.get('/firewall/rules')
    rules.value = res?.data ?? res ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const fetchBlocked = async () => {
  loadingBlocked.value = true
  try {
    const res: any = await request.get('/firewall/blocked')
    blockedLogs.value = res?.data ?? res ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingBlocked.value = false
  }
}

const openCreate = () => {
  editingRule.value = null
  ruleForm.value = { name: '', pattern: '', action: 'block', priority: 100, active: true, layer: 'L0' }
  showForm.value = true
}

const editRule = (rule: any) => {
  editingRule.value = rule
  ruleForm.value = { name: rule.name, pattern: rule.pattern, action: rule.action, priority: rule.priority, active: rule.active, layer: rule.layer || 'L0' }
  showForm.value = true
}

const saveRule = async () => {
  saving.value = true
  try {
    if (editingRule.value) {
      await request.put(`/firewall/rules/${editingRule.value.id}`, ruleForm.value)
    } else {
      await request.post('/firewall/rules', ruleForm.value)
    }
    message.success(t('common.success'))
    showForm.value = false
    await fetchRules()
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

const toggleRule = async (id: string, active: boolean) => {
  try {
    await request.put(`/firewall/rules/${id}`, { active })
    message.success(t('common.success'))
    await fetchRules()
  } catch {
    message.error(t('common.error'))
  }
}

const deleteRule = (id: string) => {
  Modal.confirm({
    title: t('common.confirm'),
    content: t('agent.deleteConfirm'),
    onOk: async () => {
      try {
        await request.delete(`/firewall/rules/${id}`)
        message.success(t('common.success'))
        await fetchRules()
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
.cascade-badge { width: 36px; height: 36px; display: inline-flex; align-items: center; justify-content: center; border-radius: 8px; font-weight: 700; font-size: 14px; color: #fff; }
.cascade-l0 { background: #3b82f6; }
.cascade-l1 { background: #10b981; }
.cascade-l2 { background: #f59e0b; }
.cascade-label { font-size: 12px; font-weight: 600; color: var(--nr-text-primary); }
.cascade-desc { font-size: 11px; color: var(--nr-text-tertiary); text-align: center; }
.cascade-arrow { font-size: 18px; color: var(--nr-text-tertiary); margin-top: -16px; }

/* Priority model */
.priority-model { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding-top: 12px; border-top: 1px solid var(--nr-glass-border, rgba(255,255,255,0.06)); }
.priority-label { font-size: 12px; font-weight: 600; color: var(--nr-text-secondary); }
.priority-code { font-family: var(--nr-font-mono); font-size: 11px; background: rgba(99,102,241,0.1); padding: 2px 8px; border-radius: 4px; color: var(--nr-primary-light, #6366f1); }
.priority-arrow { font-size: 12px; color: var(--nr-text-tertiary); }
</style>
