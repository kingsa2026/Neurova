<template>
  <div class="scheduler-page">
    <div class="page-header">
      <h2>{{ t('nav.scheduler') }}</h2>
      <GlassButton variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
    </div>

    <!-- Scheduler status -->
    <GlassPanel variant="subtle" padding="16px 20px">
      <div class="scheduler-status">
        <a-badge :status="schedulerRunning ? 'processing' : 'default'" :text="schedulerRunning ? t('common.active') : t('common.inactive')" />
        <span class="meta-text">{{ t('common.total') }}: {{ tasks.length }}</span>
      </div>
    </GlassPanel>

    <!-- Task list -->
    <a-spin :spinning="loading">
      <a-empty v-if="!loading && tasks.length === 0" :description="t('common.noData')" />
      <div v-else class="task-list">
        <GlassCard
          v-for="task in pagedTasks"
          :key="task.task_id"
          :title="task.name"
          variant="default"
          padding="16px 20px"
        >
          <div class="task-meta">
            <a-tag color="blue">{{ taskScheduleLabel(task) }}</a-tag>
            <a-tag color="default" v-if="task.agent_id">{{ task.agent_id }}</a-tag>
            <a-tag :color="task.status === 'completed' ? 'green' : task.status === 'failed' ? 'red' : 'blue'">{{ task.status }}</a-tag>
            <span class="meta-text" v-if="task.next_run_at">{{ t('nav.scheduler') }}: {{ formatTs(task.next_run_at) }}</span>
            <span class="meta-text" v-if="task.last_run_at">{{ t('scheduler.lastRun') }}{{ formatTs(task.last_run_at) }}</span>
            <span class="meta-text" v-if="task.run_count">{{ t('scheduler.runCount') }}: {{ task.run_count }}</span>
          </div>
          <div class="task-actions">
            <GlassButton variant="secondary" size="sm" :loading="runningId === task.task_id" @click="handleRunNow(task.task_id)">{{ t('scheduler.runNow') }}</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="openEdit(task)">{{ t('common.edit') }}</GlassButton>
            <a-popconfirm :title="t('common.confirm') + '?'" @confirm="handleDelete(task.task_id)">
              <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
            </a-popconfirm>
          </div>
        </GlassCard>
      </div>
      <a-pagination v-if="tasks.length > pageSize" v-model:current="currentPage" :pageSize="pageSize" :total="tasks.length" size="small" style="margin-top: 16px; text-align: center" />
    </a-spin>

    <!-- Create/Edit modal -->
    <a-modal v-model:open="showModal" :title="editingId ? t('common.edit') : t('common.create')" @ok="handleSave" :confirm-loading="saving" width="520px">
      <a-form layout="vertical" :rules="{ name: [{ required: true, message: t('common.required') }] }">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="form.name" :placeholder="t('common.name')" />
        </a-form-item>
        <a-form-item :label="t('scheduler.execAgent')">
          <a-select v-model:value="form.agentSel" :placeholder="t('scheduler.execAgentPlaceholder')">
            <a-select-option v-for="opt in agentStore.agentOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}{{ opt.isWorkflow ? ' (Workflow)' : '' }}
            </a-select-option>
          </a-select>
          <span class="form-hint">{{ t('scheduler.execAgentHint') }}</span>
        </a-form-item>
        <a-form-item :label="t('scheduler.scheduleType')">
          <a-select v-model:value="form.scheduleType">
            <a-select-option value="cron">{{ t('scheduler.cronExpression') }}</a-select-option>
            <a-select-option value="interval">{{ t('scheduler.intervalSeconds') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item v-if="form.scheduleType === 'cron'" :label="t('scheduler.cronExpression')">
          <div class="cron-builder">
            <a-select v-model:value="form.frequency" style="width: 130px">
              <a-select-option value="daily">{{ t('scheduler.daily') }}</a-select-option>
              <a-select-option value="weekly">{{ t('scheduler.weekly') }}</a-select-option>
              <a-select-option value="monthly">{{ t('scheduler.monthly') }}</a-select-option>
            </a-select>
            <a-time-picker v-model:value="form.time" value-format="HH:mm" format="HH:mm" style="width: 110px" />
            <!-- 每周循环: 周一到周日自选 -->
            <a-checkbox-group v-if="form.frequency === 'weekly'" v-model:value="form.weekdays" class="cron-weekdays">
              <a-checkbox v-for="d in WEEK_DOW" :key="d" :value="d">{{ t(weekdayLabelKey(d)) }}</a-checkbox>
            </a-checkbox-group>
            <!-- 每月: 日期选择 -->
            <a-select v-else-if="form.frequency === 'monthly'" v-model:value="form.dayOfMonth" style="width: 120px">
              <a-select-option v-for="d in 31" :key="d" :value="d">{{ d }}</a-select-option>
            </a-select>
            <a class="cron-advanced-toggle" @click="form.advanced = !form.advanced">
              {{ form.advanced ? t('scheduler.builderMode') : t('scheduler.advancedMode') }}
            </a>
            <a-input v-if="form.advanced" v-model:value="form.cron" placeholder="0 */5 * * *" class="cron-advanced-input" />
          </div>
          <div class="cron-preview">{{ buildCronLabel() }}</div>
        </a-form-item>
        <a-form-item v-if="form.scheduleType === 'interval'" :label="t('scheduler.intervalSeconds')">
          <a-input v-model:value="form.interval" type="number" placeholder="300" />
        </a-form-item>
        <a-form-item :label="t('scheduler.action')">
          <a-select v-model:value="form.action" :placeholder="t('common.actions')">
            <a-select-option value="send_message">{{ t('scheduler.sendMessage') }}</a-select-option>
            <a-select-option value="run_workflow">{{ t('scheduler.runWorkflow') }}</a-select-option>
            <a-select-option value="execute_skill">{{ t('scheduler.executeSkill') }}</a-select-option>
            <a-select-option value="custom">{{ t('scheduler.custom') }}</a-select-option>
          </a-select>
        </a-form-item>

        <!-- 发送消息: 文本输入 -->
        <a-form-item v-if="form.action === 'send_message'" :label="t('scheduler.message')">
          <a-textarea v-model:value="form.actionParams.message" :rows="3" :placeholder="t('scheduler.messagePlaceholder')" />
        </a-form-item>

        <!-- 运行工作流: 当前账号已保存工作流选择 -->
        <a-form-item v-if="form.action === 'run_workflow'" :label="t('scheduler.workflow')">
          <a-select v-model:value="form.actionParams.workflow_id" :placeholder="t('scheduler.workflowPlaceholder')">
            <a-select-option v-for="w in workflowOptions" :key="w.id" :value="w.id">{{ w.name }}</a-select-option>
          </a-select>
          <a-input v-model:value="form.actionParams.workflowInput" :placeholder="t('scheduler.workflowInput')" style="margin-top: 8px" />
        </a-form-item>

        <!-- 执行技能: 当前 agent 生效技能 + 指令文本 -->
        <a-form-item v-if="form.action === 'execute_skill'" :label="t('scheduler.skill')">
          <a-select v-model:value="form.actionParams.skill_id" :placeholder="t('scheduler.skillPlaceholder')">
            <a-select-option v-for="s in skillOptions" :key="s.id" :value="s.id">{{ s.name }}</a-select-option>
          </a-select>
          <a-textarea v-model:value="form.actionParams.instruction" :rows="2" :placeholder="t('scheduler.instructionPlaceholder')" style="margin-top: 8px" />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-input v-model:value="form.description" type="textarea" :rows="2" :placeholder="t('common.description')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import * as schedulerApi from '@/api/modules/scheduler'
import { getWorkflows, type WorkflowDefinition } from '@/api/modules/neurflow'
import { getAgentSkills, type Skill } from '@/api/modules/skill-pool'
import { useAgentPage } from '@/composables/useAgentPage'
import { useAgentStore } from '@/stores/agents'
import { buildCron, parseCron, WEEK_DOW, weekdayLabelKey, type CronFrequency } from '@/utils/schedulerCron'

const { t } = useI18n()

const { agentId } = useAgentPage()
const agentStore = useAgentStore()
const tasks = ref<schedulerApi.ScheduledTask[]>([])
const loading = ref(false)
const showModal = ref(false)
const saving = ref(false)
const editingId = ref<string | null>(null)
const runningId = ref<string | null>(null)
const schedulerRunning = ref(true)
const currentPage = ref(1)
const pageSize = ref(12)

// 动作联动数据源: 已保存工作流(无 agent 归属) + 执行 agent 生效技能
const workflowOptions = ref<WorkflowDefinition[]>([])
const skillOptions = ref<Skill[]>([])

async function loadWorkflows() {
  try {
    // 工作流无 agent 归属: 全部已保存(不按状态过滤, PUBLISHED 过滤曾致下拉为空)
    const res = await getWorkflows({ limit: 200 })
    const data = res?.data ?? res ?? {}
    workflowOptions.value = Array.isArray(data) ? data : (data.workflows ?? [])
  } catch {
    workflowOptions.value = []
  }
}

async function loadSkills() {
  if (!agentId.value) { skillOptions.value = []; return }
  try {
    const res = await getAgentSkills(agentId.value)
    skillOptions.value = (res?.data ?? res ?? []) as Skill[]
  } catch {
    skillOptions.value = []
  }
}

watch(agentId, () => { void loadSkills() })

const form = reactive({
  name: '',
  scheduleType: 'cron' as 'cron' | 'interval',
  cron: '',
  interval: '',
  action: '',
  description: '',
  // 可视化 Cron 构建
  frequency: 'daily' as CronFrequency,
  time: '09:00',
  weekdays: [1, 2, 3, 4, 5] as number[],
  dayOfMonth: 1,
  advanced: false,
  // 执行 Agent: 调度任务由用户显式指定(工作流无归属, 不绑定页面路由 agent)
  agentSel: '',
  // 动作参数
  actionParams: {
    message: '',
    workflow_id: '',
    workflowInput: '',
    skill_id: '',
    instruction: '',
  },
})

/** 当前表达式预览(构建器生成 或 advanced 原文) */
function buildCronLabel(): string {
  if (form.scheduleType !== 'cron') return ''
  if (form.advanced && form.cron.trim()) return form.cron.trim()
  return buildCron(form.frequency, form.time, form.weekdays, form.dayOfMonth)
}

/** 按动作类型组装 parameters(与后端 handler 契约一致) */
function buildActionParams(): Record<string, unknown> {
  const p = form.actionParams
  if (form.action === 'send_message') return { message: p.message }
  if (form.action === 'run_workflow') {
    const params: Record<string, unknown> = { workflow_id: p.workflow_id }
    if (p.workflowInput) { params.inputs = { message: p.workflowInput } }
    return params
  }
  if (form.action === 'execute_skill') {
    const params: Record<string, unknown> = { skill_id: p.skill_id }
    if (p.instruction) { params.instruction = p.instruction }
    return params
  }
  return {}
}

/** 编辑回填: 恢复动作参数 */
function applyActionParams(parameters?: Record<string, unknown>) {
  const p = parameters ?? {}
  form.actionParams.message = (p.message as string) ?? ''
  form.actionParams.workflow_id = (p.workflow_id as string) ?? ''
  form.actionParams.workflowInput = ((p.inputs as Record<string, unknown> | undefined)?.message as string) ?? ''
  form.actionParams.skill_id = (p.skill_id as string) ?? ''
  form.actionParams.instruction = (p.instruction as string) ?? ''
}

const pagedTasks = computed(() =>
  tasks.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value),
)

function formatTs(ts?: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${d.getMonth() + 1}-${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

function taskScheduleLabel(task: schedulerApi.ScheduledTask): string {
  if (task.cron_expression) return task.cron_expression
  if (task.interval_seconds) return `${t('scheduler.intervalSeconds')}: ${task.interval_seconds}s`
  if (task.scheduled_at) return formatTs(task.scheduled_at)
  return ''
}

function resetForm() {
  form.name = ''
  form.scheduleType = 'cron'
  form.cron = ''
  form.interval = ''
  form.action = ''
  form.description = ''
  form.frequency = 'daily'
  form.time = '09:00'
  form.weekdays = [1, 2, 3, 4, 5]
  form.dayOfMonth = 1
  form.advanced = false
  form.agentSel = agentId.value || ''
  form.actionParams = { message: '', workflow_id: '', workflowInput: '', skill_id: '', instruction: '' }
  editingId.value = null
}

function openCreate() { resetForm(); showModal.value = true }
function openEdit(task: schedulerApi.ScheduledTask) {
  editingId.value = task.task_id
  form.name = task.name
  form.scheduleType = (task.cron_expression || task.interval_seconds) ? 'cron' : 'interval'
  const parsed = parseCron(task.cron_expression ?? '')
  form.frequency = parsed.frequency
  form.time = parsed.time
  form.weekdays = parsed.weekdays
  form.dayOfMonth = parsed.dayOfMonth
  form.advanced = parsed.advanced
  form.cron = task.cron_expression ?? ''
  form.interval = task.interval_seconds?.toString() ?? ''
  form.action = task.action ?? ''
  form.description = task.description ?? ''
  form.agentSel = task.agent_id || agentId.value || ''
  applyActionParams(task.parameters)
  showModal.value = true
}

async function fetchTasks() {
  loading.value = true
  try {
    // 调度任务为全局列表: 不按页面路由 agent 过滤(任务由用户指定执行 agent)
    const res = await schedulerApi.getScheduledTasks({})
    const data = res?.data
    tasks.value = (Array.isArray(data) ? data : []) as schedulerApi.ScheduledTask[]
  } catch { message.error(t('common.error')) } finally { loading.value = false }
}

async function handleSave() {
  saving.value = true
  try {
    const base: Record<string, unknown> = {
      name: form.name,
      action: form.action,
      description: form.description,
      agent_id: form.agentSel || agentId.value || '',
      parameters: buildActionParams(),
    }
    if (form.scheduleType === 'cron') {
      base.cron_expression = buildCronLabel()
    } else {
      base.interval_seconds = Number(form.interval) || 300
    }
    if (editingId.value) {
      await schedulerApi.updateScheduledTask(editingId.value, base as unknown as Partial<schedulerApi.TaskCreatePayload>)
    } else {
      await schedulerApi.createScheduledTask(base as unknown as schedulerApi.TaskCreatePayload)
    }
    showModal.value = false
    resetForm()
    await fetchTasks()
  } catch { message.error(t('common.error')) } finally { saving.value = false }
}

async function handleRunNow(id: string) {
  runningId.value = id
  try {
    await schedulerApi.runScheduledTask(id)
    message.success(t('common.success'))
    await fetchTasks()
  } catch { message.error(t('common.error')) } finally { runningId.value = null }
}

async function handleDelete(id: string) {
  try {
    await schedulerApi.deleteScheduledTask(id)
    await fetchTasks()
  } catch { message.error(t('common.error')) }
}

onMounted(() => {
  void fetchTasks()
  void loadWorkflows()
  void loadSkills()
  void agentStore.loadAgents()
})
</script>

<style scoped>
.cron-builder { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.cron-weekdays { display: flex; flex-wrap: wrap; gap: 4px; }
.cron-advanced-toggle { font-size: 12px; color: var(--nr-accent, #7c9eff); cursor: pointer; }
.cron-advanced-input { width: 100%; }
.cron-preview { margin-top: 6px; font-size: 12px; font-family: monospace; color: var(--nr-text-secondary, #8a8a92); }
.form-hint { display: block; margin-top: 4px; font-size: 12px; color: var(--nr-text-tertiary, #666); }
.scheduler-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.scheduler-status { display: flex; gap: 16px; align-items: center; }
.meta-text { font-size: 12px; color: var(--nr-text-tertiary); }
.task-list { display: flex; flex-direction: column; gap: 12px; }
.task-meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.task-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
</style>
