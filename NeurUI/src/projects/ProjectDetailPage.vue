<template>
  <div class="project-detail-page">
    <div class="page-header">
      <div class="header-left">
        <GlassButton variant="ghost" size="sm" @click="router.push('/projects')">← {{ t('project.list') }}</GlassButton>
        <h2 v-if="project">{{ project.name }}</h2>
        <a-spin v-else size="small" />
      </div>
    </div>

    <p v-if="project?.description" class="proj-desc">{{ project.description }}</p>

    <a-tabs v-model:activeKey="activeTab">
      <!-- 概览 -->
      <a-tab-pane key="overview" :tab="t('project.tabOverview')">
        <div v-if="project" class="stats-row">
          <GlassCard :title="t('workflow.tabCanvases')" variant="subtle" padding="14px 18px">
            <span class="stat-value">{{ projectCanvasCount }}</span>
          </GlassCard>
          <GlassCard :title="t('project.teams')" variant="subtle" padding="14px 18px">
            <span class="stat-value">{{ teams.length }}</span>
          </GlassCard>
          <GlassCard :title="t('project.tasks')" variant="subtle" padding="14px 18px">
            <span class="stat-value">{{ tasks.length }}</span>
          </GlassCard>
        </div>
      </a-tab-pane>

      <!-- 团队 -->
      <a-tab-pane key="teams" :tab="t('project.tabTeams')">
        <div class="tab-actions">
          <GlassButton variant="primary" size="sm" @click="showCreateTeam = true">{{ t('project.createTeam') }}</GlassButton>
        </div>
        <div v-if="teams.length === 0" class="empty-state"><a-empty :description="t('common.noData')" /></div>
        <GlassCard
          v-for="team in teams"
          :key="team.team_id"
          :title="team.name"
          :subtitle="team.description"
          variant="default"
          padding="16px 20px"
          class="block-card"
        >
          <div class="member-list">
            <a-tag v-for="(info, aid) in team.members" :key="aid" color="blue">
              {{ info.agent_name || aid }}（{{ info.role || 'member' }}）
            </a-tag>
            <span v-if="Object.keys(team.members).length === 0" class="meta-text">{{ t('common.noData') }}</span>
          </div>
          <div class="add-member">
            <a-input v-model:value="memberForm[team.team_id].agentId" size="small" placeholder="Agent ID" style="width: 160px" />
            <a-input v-model:value="memberForm[team.team_id].agentName" size="small" :placeholder="t('common.name')" style="width: 140px" />
            <GlassButton variant="ghost" size="sm" @click="handleAddMember(team)">+ {{ t('project.addMember') }}</GlassButton>
          </div>
        </GlassCard>

        <!-- 新建团队 -->
        <a-modal v-model:open="showCreateTeam" :title="t('project.createTeam')" :confirm-loading="creatingTeam" @ok="handleCreateTeam">
          <a-form layout="vertical">
            <a-form-item :label="t('common.name')" required>
              <a-input v-model:value="teamForm.name" @pressEnter="handleCreateTeam" />
            </a-form-item>
            <a-form-item :label="t('common.description')">
              <a-textarea v-model:value="teamForm.description" :rows="2" />
            </a-form-item>
          </a-form>
        </a-modal>
      </a-tab-pane>

      <!-- 任务 -->
      <a-tab-pane key="tasks" :tab="t('project.tabTasks')">
        <div class="tab-actions">
          <GlassButton variant="primary" size="sm" @click="openCreateTask">{{ t('project.createTask') }}</GlassButton>
        </div>
        <div v-if="tasks.length === 0" class="empty-state"><a-empty :description="t('common.noData')" /></div>
        <GlassCard
          v-for="task in tasks"
          :key="task.task_id"
          :title="task.name"
          variant="default"
          padding="16px 20px"
          class="block-card"
        >
          <div class="wf-meta">
            <a-tag :color="task.status === 'active' ? 'green' : 'orange'">{{ task.status }}</a-tag>
            <span class="meta-text">workflow: {{ task.workflow_id }}</span>
            <span class="meta-text">{{ scheduleText(task.schedule_config) }}</span>
          </div>
          <div class="wf-actions">
            <GlassButton v-if="task.status === 'active'" variant="ghost" size="sm" @click="handlePauseTask(task)">{{ t('project.pause') }}</GlassButton>
            <GlassButton v-else variant="ghost" size="sm" @click="handleResumeTask(task)">{{ t('project.resume') }}</GlassButton>
          </div>
        </GlassCard>

        <!-- 新建任务 -->
        <a-modal v-model:open="showCreateTask" :title="t('project.createTask')" :confirm-loading="creatingTask" @ok="handleCreateTask">
          <a-form layout="vertical">
            <a-form-item :label="t('common.name')" required>
              <a-input v-model:value="taskForm.name" />
            </a-form-item>
            <a-form-item label="Workflow ID" required>
              <a-select
                v-model:value="taskForm.workflowId"
                :options="canvasOptions"
                show-search
                option-filter-prop="label"
                placeholder="选择画布工作流"
              />
            </a-form-item>
            <a-form-item :label="t('project.scheduleType')">
              <a-radio-group v-model:value="taskForm.scheduleType">
                <a-radio value="specify">{{ t('project.specify') }}</a-radio>
                <a-radio value="weekly">{{ t('project.weekly') }}</a-radio>
                <a-radio value="interval">{{ t('project.interval') }}</a-radio>
              </a-radio-group>
            </a-form-item>
            <template v-if="taskForm.scheduleType === 'specify'">
              <a-form-item :label="t('project.runDate')" required>
                <a-date-picker v-model:value="taskForm.specifyDate" style="width: 100%" />
              </a-form-item>
              <a-form-item :label="t('project.runTime')" required>
                <a-time-picker v-model:value="taskForm.specifyTime" format="HH:mm" style="width: 100%" />
              </a-form-item>
            </template>
            <template v-else-if="taskForm.scheduleType === 'weekly'">
              <a-form-item :label="t('project.weekdays')" required>
                <a-checkbox-group v-model:value="taskForm.weekdays" :options="weekdayOptions" />
              </a-form-item>
              <a-form-item :label="t('project.runTime')" required>
                <a-time-picker v-model:value="taskForm.weeklyTime" format="HH:mm" style="width: 100%" />
              </a-form-item>
            </template>
            <a-form-item v-else :label="t('project.intervalSeconds')">
              <a-input-number v-model:value="taskForm.intervalSeconds" :min="10" style="width: 100%" />
            </a-form-item>
          </a-form>
        </a-modal>
      </a-tab-pane>

      <!-- 工作流 -->
      <a-tab-pane key="workflows" :tab="t('project.tabWorkflows')">
        <div class="tab-actions">
          <GlassButton variant="primary" size="sm" @click="router.push('/collaboration/workflows')">{{ t('project.newWorkflow') }}</GlassButton>
        </div>
        <div v-if="projectCanvases.length === 0" class="empty-state"><a-empty :description="t('common.noData')" /></div>
        <div v-else class="workflow-grid">
          <GlassCard
            v-for="cv in projectCanvases"
            :key="cv.id"
            :title="cv.name"
            variant="default"
            padding="16px 20px"
          >
            <div class="wf-meta">
              <span class="meta-text">{{ t('workflow.nodes') }}: {{ cv.node_count ?? 0 }}</span>
              <span v-if="cv.updated_at" class="meta-text">{{ formatTime(cv.updated_at) }}</span>
            </div>
            <div class="wf-actions">
              <GlassButton variant="primary" size="sm" @click="router.push(`/collaboration/canvas/${cv.id}`)">{{ t('common.open') }}</GlassButton>
            </div>
          </GlassCard>
        </div>
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import type { Dayjs } from 'dayjs'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  getProjectInfo,
  listProjectTeams,
  createProjectTeam,
  addTeamMember,
  listProjectTasks,
  createProjectTask,
  pauseProjectTask,
  resumeProjectTask,
  type ProjectInfo,
  type ProjectTeamDto,
  type ProjectTaskDto,
} from '@/api/modules/projects'
import { listCanvases, type CanvasSummary } from '@/api/modules/collaboration'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const projectId = computed(() => String(route.params.id || ''))
const activeTab = ref('overview')

const project = ref<ProjectInfo | null>(null)
const teams = ref<ProjectTeamDto[]>([])
const tasks = ref<ProjectTaskDto[]>([])
const allCanvases = ref<CanvasSummary[]>([])

const projectCanvases = computed(() =>
  allCanvases.value.filter((c) => c.project_id === projectId.value),
)
const projectCanvasCount = computed(() => projectCanvases.value.length)

const canvasOptions = computed(() =>
  allCanvases.value.map((c) => ({ label: c.name, value: c.id })),
)

function unwrap<T>(res: unknown): T | null {
  const r = res as { data?: T } | null
  return (r?.data ?? (res as T)) as T | null
}

async function fetchAll() {
  try {
    project.value = unwrap<ProjectInfo>(await getProjectInfo(projectId.value))
  } catch { /* 404 由拦截器提示 */ }
  await refreshTeams()
  try {
    tasks.value = unwrap<{ tasks: ProjectTaskDto[] }>(await listProjectTasks(projectId.value))?.tasks ?? []
  } catch { tasks.value = [] }
  try {
    const canvases = unwrap<CanvasSummary[]>(await listCanvases())
    allCanvases.value = Array.isArray(canvases) ? canvases : []
  } catch { allCanvases.value = [] }
}

/** 拉取团队列表并预初始化成员表单（保证 v-model 响应性） */
async function refreshTeams() {
  try {
    teams.value = unwrap<{ teams: ProjectTeamDto[] }>(await listProjectTeams(projectId.value))?.teams ?? []
  } catch {
    teams.value = []
  }
  for (const tm of teams.value) {
    if (!memberForm[tm.team_id]) memberForm[tm.team_id] = { agentId: '', agentName: '' }
  }
}

// ── 团队 ──
const showCreateTeam = ref(false)
const creatingTeam = ref(false)
const teamForm = reactive({ name: '', description: '' })

async function handleCreateTeam() {
  if (!teamForm.name.trim()) return
  creatingTeam.value = true
  try {
    await createProjectTeam(projectId.value, { name: teamForm.name.trim(), description: teamForm.description })
    showCreateTeam.value = false
    teamForm.name = ''
    teamForm.description = ''
    await refreshTeams()
  } catch { /* handled */ } finally {
    creatingTeam.value = false
  }
}

const memberForm = reactive<Record<string, { agentId: string; agentName: string }>>({})

async function handleAddMember(team: ProjectTeamDto) {
  const form = memberForm[team.team_id]
  if (!form?.agentId.trim()) return
  try {
    await addTeamMember(projectId.value, team.team_id, {
      agent_id: form.agentId.trim(),
      agent_name: form.agentName.trim(),
      role: 'member',
    })
    form.agentId = ''
    form.agentName = ''
    await refreshTeams()
  } catch { /* handled */ }
}

// ── 任务 ──
const showCreateTask = ref(false)
const creatingTask = ref(false)

type ScheduleType = 'specify' | 'weekly' | 'interval'
const taskForm = reactive({
  name: '',
  workflowId: undefined as string | undefined,
  scheduleType: 'specify' as ScheduleType,
  specifyDate: undefined as Dayjs | undefined,
  specifyTime: undefined as Dayjs | undefined,
  weekdays: [1, 2, 3, 4, 5] as number[],
  weeklyTime: undefined as Dayjs | undefined,
  intervalSeconds: 300,
})

// cron 星期字段：0=周日，1-6=周一至周六
const weekdayOptions = computed(() => [
  { label: t('project.mon'), value: 1 },
  { label: t('project.tue'), value: 2 },
  { label: t('project.wed'), value: 3 },
  { label: t('project.thu'), value: 4 },
  { label: t('project.fri'), value: 5 },
  { label: t('project.sat'), value: 6 },
  { label: t('project.sun'), value: 0 },
])

/** 按调度类型生成 schedule_config；校验失败返回 null */
function buildScheduleConfig(): Record<string, unknown> | null {
  if (taskForm.scheduleType === 'interval') {
    return { type: 'interval', interval_seconds: taskForm.intervalSeconds }
  }

  if (taskForm.scheduleType === 'weekly') {
    if (taskForm.weekdays.length === 0) return null
    const hh = taskForm.weeklyTime?.hour() ?? 9
    const mm = taskForm.weeklyTime?.minute() ?? 0
    const days = [...taskForm.weekdays].sort((a, b) => a - b)
    return {
      mode: 'weekly',
      type: 'cron',
      cron: `${mm} ${hh} * * ${days.join(',')}`,
      days,
      time: `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`,
    }
  }

  // 指定日期时间：一次性任务（cron 钉死到该日 + end_date 阻止次年重复触发）
  if (!taskForm.specifyDate) return null
  const hh = taskForm.specifyTime?.hour() ?? 9
  const mm = taskForm.specifyTime?.minute() ?? 0
  const runAt = taskForm.specifyDate.hour(hh).minute(mm).second(0)
  return {
    mode: 'specify',
    type: 'cron',
    cron: `${mm} ${hh} ${runAt.date()} ${runAt.month() + 1} *`,
    date: runAt.format('YYYY-MM-DD'),
    time: `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`,
    start_date: runAt.format('YYYY-MM-DDTHH:mm:ss'),
    end_date: runAt.add(1, 'minute').format('YYYY-MM-DDTHH:mm:ss'),
  }
}

function openCreateTask() {
  showCreateTask.value = true
}

async function handleCreateTask() {
  if (!taskForm.name.trim() || !taskForm.workflowId) return
  const scheduleConfig = buildScheduleConfig()
  if (!scheduleConfig) {
    message.warning(t('project.scheduleIncomplete'))
    return
  }
  creatingTask.value = true
  try {
    await createProjectTask(projectId.value, {
      name: taskForm.name.trim(),
      workflow_id: taskForm.workflowId,
      schedule_config: scheduleConfig as { type: 'cron' | 'interval' } & Record<string, unknown>,
    })
    showCreateTask.value = false
    tasks.value = unwrap<{ tasks: ProjectTaskDto[] }>(await listProjectTasks(projectId.value))?.tasks ?? []
  } catch { /* handled */ } finally {
    creatingTask.value = false
  }
}

async function handlePauseTask(task: ProjectTaskDto) {
  try {
    await pauseProjectTask(projectId.value, task.task_id)
    tasks.value = unwrap<{ tasks: ProjectTaskDto[] }>(await listProjectTasks(projectId.value))?.tasks ?? []
  } catch { /* handled */ }
}

async function handleResumeTask(task: ProjectTaskDto) {
  try {
    await resumeProjectTask(projectId.value, task.task_id)
    tasks.value = unwrap<{ tasks: ProjectTaskDto[] }>(await listProjectTasks(projectId.value))?.tasks ?? []
  } catch { /* handled */ }
}

function scheduleText(cfg: Record<string, unknown>): string {
  if (cfg.type === 'interval') return `${t('project.every')} ${cfg.interval_seconds ?? '-'}s`
  if (cfg.type === 'cron') {
    if (cfg.mode === 'specify') {
      return `${t('project.specify')}: ${cfg.date ?? '-'} ${cfg.time ?? ''}`
    }
    if (cfg.mode === 'weekly') {
      const days = Array.isArray(cfg.days) ? (cfg.days as number[]) : []
      const names = weekdayOptions.value.filter((o) => days.includes(o.value)).map((o) => o.label)
      return `${t('project.weekly')}: ${names.join('/') || '-'} ${cfg.time ?? ''}`
    }
    // 兼容旧数据：裸 cron 表达式
    return `cron: ${cfg.cron ?? '-'}`
  }
  return String(cfg.type ?? '-')
}

function formatTime(ts?: number): string {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleString()
}

onMounted(fetchAll)
</script>

<style scoped>
.project-detail-page { display: flex; flex-direction: column; gap: 16px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.header-left { display: flex; align-items: center; gap: 12px; }
.header-left h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.proj-desc { color: var(--nr-text-secondary); margin: 0; font-size: 14px; }
.stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.stat-value { font-family: var(--nr-font-display); font-size: 24px; font-weight: 700; color: var(--nr-text-primary); }
.tab-actions { display: flex; justify-content: flex-end; margin-bottom: 12px; }
.block-card { margin-bottom: 12px; }
.member-list { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.add-member { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.meta-text { font-size: 12px; color: var(--nr-text-tertiary); }
.wf-meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.wf-actions { display: flex; gap: 6px; }
.workflow-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
.empty-state { padding: 32px 0; }
</style>
