<template>
  <div class="team-page">
    <div class="page-header">
      <h2>{{ t('collab.teams') }}</h2>
      <GlassButton variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
    </div>

    <!-- 外部代理运行状态（admin 只读卡，§5.5 目录/连通性调试入口） -->
    <GlassCard v-if="isAdmin" :title="t('neuacp.statusTitle')" variant="subtle" padding="14px 18px">
      <div v-if="neuacpStatus" class="neuacp-status">
        <span>{{ t('neuacp.statusProcesses') }}: {{ neuacpStatus.processes?.length ?? 0 }}</span>
        <span v-if="neuacpStatus.note" class="neuacp-status-note">{{ t('neuacp.statusNote') }}: {{ neuacpStatus.note }}</span>
      </div>
      <div v-else-if="neuacpStatusError" class="neuacp-status-error">{{ t('neuacp.statusLoadFailed') }}</div>
      <div v-else>{{ t('neuacp.statusEmpty') }}</div>
    </GlassCard>

    <a-spin :spinning="loading">
      <a-empty v-if="!loading && teams.length === 0" :description="t('common.noData')" />
      <div v-else class="team-grid">
        <GlassCard
          v-for="team in pagedTeams"
          :key="team.id"
          :title="team.name"
          :subtitle="team.description"
          variant="default"
          padding="18px 22px"
        >
          <div class="team-meta">
            <!-- S10：团队来源标（agent 沉淀的团队带批准人） -->
            <a-tag
              v-if="team.origin === 'agent_proposed'"
              color="purple"
              :title="team.approved_by ? `${t('collab.teamApprovedBy')}: ${team.approved_by}` : t('collab.teamOriginAgent')"
            >◈ {{ t('collab.teamOriginAgent') }}</a-tag>
            <a-tag color="blue">{{ memberRows(team).length }} {{ t('collab.members') }}</a-tag>
          </div>
          <div class="team-members">
            <div v-for="m in memberRows(team)" :key="m.user_id" class="team-member-row">
              <span class="member-name">{{ m.name }}</span>
              <span class="member-role">{{ m.role }}</span>
              <span class="member-badge" :class="{ 'is-external': !!m.executor }">{{ executorBadgeText(m) }}</span>
              <span v-if="isAdmin" class="member-remove">
                <a-popconfirm :title="t('neuacp.removeMemberConfirm')" @confirm="handleRemoveMember(team, m)">
                  <GlassButton variant="danger" size="sm">{{ t('neuacp.removeMember') }}</GlassButton>
                </a-popconfirm>
              </span>
            </div>
          </div>
          <div class="team-actions">
            <GlassButton variant="ghost" size="sm" @click="openAddMember(team)">{{ t('collab.addMember') }}</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="openEdit(team)">{{ t('common.edit') }}</GlassButton>
            <a-popconfirm :title="t('common.confirm') + '?'" @confirm="handleDelete(team.id)">
              <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
            </a-popconfirm>
          </div>
        </GlassCard>
      </div>
      <a-pagination v-if="teams.length > pageSize" v-model:current="currentPage" :pageSize="pageSize" :total="teams.length" size="small" style="margin-top: 16px; text-align: center" />
    </a-spin>

    <!-- Create/Edit team modal -->
    <a-modal v-model:open="showTeamModal" :title="editingId ? t('common.edit') : t('common.create')" @ok="handleSave" :confirm-loading="saving">
      <a-form layout="vertical" :rules="{ name: [{ required: true, message: t('common.required') }] }">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="teamForm.name" :placeholder="t('common.name')" />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-input v-model:value="teamForm.description" type="textarea" :rows="3" :placeholder="t('common.description')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Add member modal：内置成员（现状交互）与外部编码代理（admin）两档 -->
    <a-modal
      v-model:open="showMemberModal"
      :title="t('collab.addMember')"
      :footer="memberTab === 'external' ? null : undefined"
      @ok="handleAddMember"
      :confirm-loading="addingMember"
    >
      <a-tabs v-if="isAdmin" v-model:activeKey="memberTab">
        <a-tab-pane key="builtin" :tab="t('neuacp.tabBuiltin')">
          <a-form layout="vertical">
            <a-form-item :label="t('collab.members')">
              <a-select v-model:value="newMembers" mode="tags" :placeholder="t('collab.members')" style="width: 100%" />
            </a-form-item>
            <a-form-item :label="t('agent.systemPrompt')">
              <a-input v-model:value="memberPrompt" type="textarea" :rows="4" :placeholder="t('agent.systemPrompt')" />
            </a-form-item>
          </a-form>
        </a-tab-pane>
        <a-tab-pane key="external" :tab="t('neuacp.tabExternal')">
          <TeamNeuacpMemberForm
            v-if="activeTeamId"
            :team-id="activeTeamId"
            @submitted="onExternalMemberAdded"
            @cancel="showMemberModal = false"
          />
        </a-tab-pane>
      </a-tabs>
      <a-form v-else layout="vertical">
        <a-form-item :label="t('collab.members')">
          <a-select v-model:value="newMembers" mode="tags" :placeholder="t('collab.members')" style="width: 100%" />
        </a-form-item>
        <a-form-item :label="t('agent.systemPrompt')">
          <a-input v-model:value="memberPrompt" type="textarea" :rows="4" :placeholder="t('agent.systemPrompt')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { listTeams, createTeam, updateTeam, deleteTeam as deleteTeamApi, addTeamMembers, type Team } from '@/api/modules/teams'
import { fetchNeuacpStatus, removeTeamMember } from '@/api/modules/neuacp'
import { useAuthStore } from '@/stores/auth'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import TeamNeuacpMemberForm from '@/components/team/TeamNeuacpMemberForm.vue'
import type { TeamMemberDetail, TeamWithDetail } from '@/types/agent'

const { t } = useI18n()
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')

const teams = ref<TeamWithDetail[]>([])
const loading = ref(false)
const showTeamModal = ref(false)
const showMemberModal = ref(false)
const saving = ref(false)
const addingMember = ref(false)
const editingId = ref<string | null>(null)
const activeTeamId = ref<string | null>(null)
const newMembers = ref<string[]>([])
const memberPrompt = ref('')
const memberTab = ref<'builtin' | 'external'>('builtin')
const currentPage = ref(1)
const pageSize = ref(12)
const neuacpStatus = ref<Awaited<ReturnType<typeof fetchNeuacpStatus>> | null>(null)
const neuacpStatusError = ref(false)

const teamForm = reactive({ name: '', description: '' })

const pagedTeams = computed(() =>
  teams.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value),
)

/** 名册行归一：优先 members_detail，缺省回退 members 字符串数组（旧后端兼容）。 */
function memberRows(team: TeamWithDetail): TeamMemberDetail[] {
  if (team.members_detail?.length) return team.members_detail
  return (team.members ?? []).map((uid) => ({ user_id: uid, name: uid, role: 'member' }))
}

/** 执行体徽标：内置 / ACP·工具名 / 插件·工具名。 */
function executorBadgeText(m: TeamMemberDetail): string {
  if (!m.executor) return t('neuacp.executorBuiltin')
  const tool = m.executor.tool || ''
  return m.executor.kind === 'plugin'
    ? t('neuacp.executorPlugin', { tool })
    : t('neuacp.executorAcp', { tool })
}

function resetTeamForm() {
  teamForm.name = ''
  teamForm.description = ''
  editingId.value = null
}

function openCreate() { resetTeamForm(); showTeamModal.value = true }
function openEdit(team: Team) {
  editingId.value = team.id
  teamForm.name = team.name
  teamForm.description = team.description ?? ''
  showTeamModal.value = true
}

function openAddMember(team: Team) {
  activeTeamId.value = team.id
  newMembers.value = []
  memberPrompt.value = ''
  memberTab.value = 'builtin'
  showMemberModal.value = true
}

async function fetchTeams() {
  loading.value = true
  try {
    const res = await listTeams()
    teams.value = (res ?? []) as TeamWithDetail[]
  } catch { message.error(t('common.error')) } finally { loading.value = false }
}

async function fetchNeuacpStatusCard() {
  if (!isAdmin.value) return
  try {
    neuacpStatus.value = await fetchNeuacpStatus()
    neuacpStatusError.value = false
  } catch {
    neuacpStatus.value = null
    neuacpStatusError.value = true
  }
}

async function handleSave() {
  saving.value = true
  try {
    if (editingId.value) {
      await updateTeam(editingId.value, { ...teamForm })
    } else {
      await createTeam({ ...teamForm })
    }
    showTeamModal.value = false
    resetTeamForm()
    await fetchTeams()
  } catch { message.error(t('common.error')) } finally { saving.value = false }
}

async function handleDelete(id: string) {
  try {
    await deleteTeamApi(id)
    await fetchTeams()
  } catch { message.error(t('common.error')) }
}

async function handleAddMember() {
  if (!activeTeamId.value || newMembers.value.length === 0) return
  addingMember.value = true
  try {
    await addTeamMembers(activeTeamId.value, {
      members: newMembers.value,
      prompt: memberPrompt.value,
    })
    showMemberModal.value = false
    await fetchTeams()
  } catch { message.error(t('common.error')) } finally { addingMember.value = false }
}

/** 外部编码代理成员表单提交成功：关弹窗并刷新名册。 */
async function onExternalMemberAdded() {
  showMemberModal.value = false
  await fetchTeams()
}

async function handleRemoveMember(team: TeamWithDetail, m: TeamMemberDetail) {
  try {
    await removeTeamMember(team.id, m.user_id)
    message.success(t('neuacp.removeSuccess'))
    await fetchTeams()
  } catch { message.error(t('common.error')) }
}

onMounted(() => {
  fetchTeams()
  fetchNeuacpStatusCard()
})
</script>

<style scoped>
.team-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.team-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.team-meta { margin-bottom: 10px; }
.team-members { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.team-member-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px;
  border-radius: 8px;
  border: 1px solid var(--nr-border-light);
  background: var(--nr-bg-inset);
}
.member-name { color: var(--nr-text-primary); font-size: 13px; font-weight: 600; }
.member-role { color: var(--nr-text-tertiary); font-size: 12px; }
.member-badge {
  margin-left: auto;
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 9px;
  border: 1px solid var(--nr-border);
  color: var(--nr-text-secondary);
  white-space: nowrap;
}
/* 外部成员主色描边（只用 --nr-* 令牌，双皮肤×双明暗自适配） */
.member-badge.is-external {
  color: var(--nr-primary-light);
  border-color: var(--nr-primary-light);
  background: var(--nr-primary-soft);
}
.member-remove { display: inline-flex; }
.neuacp-status { display: flex; gap: 16px; color: var(--nr-text-secondary); font-size: 13px; }
.neuacp-status-note { color: var(--nr-text-tertiary); }
.neuacp-status-error { color: var(--nr-error); font-size: 13px; }
.team-actions { display: flex; gap: 6px; }
</style>
