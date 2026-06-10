<template>
  <div class="task-page">
    <div class="page-header">
      <h2>{{ t('collab.tasks') }}</h2>
      <div class="header-actions">
        <a-select v-model:value="activeBoard" :placeholder="t('common.type')" style="width: 200px" @change="fetchTasks">
          <a-select-option v-for="b in boards" :key="b.id" :value="b.id">{{ b.name }}</a-select-option>
        </a-select>
        <GlassButton v-if="activeBoard" variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
      </div>
    </div>

    <!-- Board stats -->
    <div v-if="activeBoard" class="stats-row">
      <GlassCard v-for="s in boardStats" :key="s.label" :title="s.label" variant="subtle" padding="14px 18px">
        <span class="stat-value">{{ s.value }}</span>
      </GlassCard>
    </div>

    <!-- Kanban board -->
    <a-spin :spinning="loading">
      <a-empty v-if="!loading && !activeBoard" :description="t('common.noData')" />
      <div v-else class="kanban-board">
        <div v-for="col in columns" :key="col.key" class="kanban-column">
          <div class="column-header">
            <h4>{{ col.title }}</h4>
            <a-badge :count="tasksByStatus(col.key).length" :number-style="{ backgroundColor: col.color }" />
          </div>
          <div class="column-body">
            <div
              v-for="task in tasksByStatus(col.key)"
              :key="task.id"
              class="task-card"
              @click="handleViewTask(task)"
            >
              <GlassPanel variant="subtle" padding="12px 16px">
                <div class="task-title">{{ task.title }}</div>
                <div class="task-meta">
                  <a-tag v-if="task.priority" :color="task.priority === 'high' ? 'red' : task.priority === 'medium' ? 'orange' : 'blue'">{{ task.priority }}</a-tag>
                  <span v-if="task.assignee" class="meta-text">{{ task.assignee }}</span>
                  <span v-if="task.dueDate" class="meta-text">{{ task.dueDate }}</span>
                </div>
                <div class="task-move-actions">
                  <GlassButton
                    v-for="target in columns.filter((c) => c.key !== col.key)"
                    :key="target.key"
                    variant="ghost"
                    size="sm"
                    @click.stop="handleMove(task.id, target.key)"
                  >
                    {{ target.title }}
                  </GlassButton>
                </div>
              </GlassPanel>
            </div>
          </div>
        </div>
      </div>
    </a-spin>

    <!-- Task detail modal -->
    <a-modal v-model:open="showDetail" :title="selectedTask?.title" :footer="null" width="560px">
      <div v-if="selectedTask" class="task-detail">
        <p><strong>{{ t('common.description') }}:</strong> {{ selectedTask.description }}</p>
        <p><strong>{{ t('common.status') }}:</strong> {{ selectedTask.status }}</p>
        <p><strong>{{ t('common.type') }}Priority:</strong> {{ selectedTask.priority }}</p>
        <p v-if="selectedTask.assignee"><strong>Assignee:</strong> {{ selectedTask.assignee }}</p>
        <p v-if="selectedTask.dueDate"><strong>Due:</strong> {{ selectedTask.dueDate }}</p>
      </div>
    </a-modal>

    <!-- Create task modal -->
    <a-modal v-model:open="showCreateModal" :title="t('common.create')" @ok="handleCreate" :confirm-loading="creating">
      <a-form layout="vertical">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="createForm.title" :placeholder="t('common.name')" />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-input v-model:value="createForm.description" type="textarea" :rows="3" :placeholder="t('common.description')" />
        </a-form-item>
        <a-form-item label="Priority">
          <a-select v-model:value="createForm.priority">
            <a-select-option value="low">Low</a-select-option>
            <a-select-option value="medium">Medium</a-select-option>
            <a-select-option value="high">High</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="Assignee">
          <a-input v-model:value="createForm.assignee" placeholder="Assignee" />
        </a-form-item>
        <a-form-item label="Due Date">
          <a-input v-model:value="createForm.dueDate" type="date" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import GlassPanel from '@/components/GlassPanel.vue'

const { t } = useI18n()

interface Task {
  id: string
  title: string
  description: string
  status: string
  priority?: string
  assignee?: string
  dueDate?: string
}

interface Board {
  id: string
  name: string
}

const boards = ref<Board[]>([])
const tasks = ref<Task[]>([])
const loading = ref(false)
const activeBoard = ref<string | undefined>(undefined)
const showCreateModal = ref(false)
const showDetail = ref(false)
const creating = ref(false)
const selectedTask = ref<Task | null>(null)

const createForm = reactive({ title: '', description: '', priority: 'medium', assignee: '', dueDate: '' })

const columns = [
  { key: 'todo', title: 'To Do', color: '#6366f1' },
  { key: 'in-progress', title: 'In Progress', color: '#f59e0b' },
  { key: 'done', title: 'Done', color: '#10b981' },
]

const tasksByStatus = (status: string) => tasks.value.filter((t) => t.status === status)

const boardStats = computed(() => [
  { label: t('common.total'), value: tasks.value.length },
  { label: 'To Do', value: tasksByStatus('todo').length },
  { label: 'In Progress', value: tasksByStatus('in-progress').length },
  { label: 'Done', value: tasksByStatus('done').length },
])

function openCreate() {
  createForm.title = ''
  createForm.description = ''
  createForm.priority = 'medium'
  createForm.assignee = ''
  createForm.dueDate = ''
  showCreateModal.value = true
}

function handleViewTask(task: Task) {
  selectedTask.value = task
  showDetail.value = true
}

async function fetchBoards() {
  try {
    const res = await request.get('/tasks/boards') as unknown as Board[]
    boards.value = res ?? []
    if (boards.value.length > 0 && !activeBoard.value) {
      activeBoard.value = boards.value[0].id
      await fetchTasks()
    }
  } catch { boards.value = [] }
}

async function fetchTasks() {
  if (!activeBoard.value) return
  loading.value = true
  try {
    const res = await request.get(`/tasks/boards/${activeBoard.value}/tasks`) as unknown as Task[]
    tasks.value = res ?? []
  } catch { tasks.value = [] } finally { loading.value = false }
}

async function handleCreate() {
  if (!createForm.title || !activeBoard.value) return
  creating.value = true
  try {
    await request.post(`/tasks/boards/${activeBoard.value}/tasks`, { ...createForm, status: 'todo' })
    showCreateModal.value = false
    await fetchTasks()
  } catch { /* handled */ } finally { creating.value = false }
}

async function handleMove(taskId: string, targetStatus: string) {
  try {
    await request.put(`/tasks/tasks/${taskId}/move`, { status: targetStatus })
    await fetchTasks()
  } catch { /* handled */ }
}

onMounted(fetchBoards)
</script>

<style scoped>
.task-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.header-actions { display: flex; gap: 8px; align-items: center; }
.stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
.stat-value { font-family: var(--nr-font-display); font-size: 24px; font-weight: 700; color: var(--nr-text-primary); }
.kanban-board { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.kanban-column { display: flex; flex-direction: column; gap: 10px; }
.column-header { display: flex; justify-content: space-between; align-items: center; padding: 0 4px; }
.column-header h4 { color: var(--nr-text-primary); margin: 0; font-size: 14px; }
.column-body { display: flex; flex-direction: column; gap: 8px; min-height: 120px; }
.task-card { cursor: pointer; transition: transform 0.2s; }
.task-card:hover { transform: translateY(-2px); }
.task-title { color: var(--nr-text-primary); font-size: 14px; font-weight: 500; margin-bottom: 6px; }
.task-meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.meta-text { font-size: 11px; color: var(--nr-text-tertiary); }
.task-move-actions { display: flex; gap: 4px; margin-top: 8px; flex-wrap: wrap; }
.task-detail { display: flex; flex-direction: column; gap: 10px; }
.task-detail p { color: var(--nr-text-secondary); font-size: 14px; margin: 0; }
</style>
