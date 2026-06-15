<template>
  <div class="team-page">
    <div class="page-header">
      <h2>{{ t('collab.teams') }}</h2>
      <GlassButton variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
    </div>

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
            <a-tag color="blue">{{ team.members?.length ?? 0 }} {{ t('collab.members') }}</a-tag>
          </div>
          <div class="team-members">
            <a-tag v-for="m in (team.members ?? []).slice(0, 5)" :key="m">{{ m }}</a-tag>
            <a-tag v-if="(team.members?.length ?? 0) > 5">+{{ team.members!.length - 5 }}</a-tag>
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

    <!-- Add member modal -->
    <a-modal v-model:open="showMemberModal" :title="t('collab.addMember')" @ok="handleAddMember" :confirm-loading="addingMember">
      <a-form layout="vertical">
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
import { listTeams, createTeam, updateTeam, deleteTeam as deleteTeamApi, addTeamMembers } from '@/api/modules/teams'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()

interface Team {
  id: string
  name: string
  description: string
  members?: string[]
}

const teams = ref<Team[]>([])
const loading = ref(false)
const showTeamModal = ref(false)
const showMemberModal = ref(false)
const saving = ref(false)
const addingMember = ref(false)
const editingId = ref<string | null>(null)
const activeTeamId = ref<string | null>(null)
const newMembers = ref<string[]>([])
const memberPrompt = ref('')
const currentPage = ref(1)
const pageSize = ref(12)

const teamForm = reactive({ name: '', description: '' })

const pagedTeams = computed(() =>
  teams.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value),
)

function resetTeamForm() {
  teamForm.name = ''
  teamForm.description = ''
  editingId.value = null
}

function openCreate() { resetTeamForm(); showTeamModal.value = true }
function openEdit(team: Team) {
  editingId.value = team.id
  teamForm.name = team.name
  teamForm.description = team.description
  showTeamModal.value = true
}

function openAddMember(team: Team) {
  activeTeamId.value = team.id
  newMembers.value = []
  memberPrompt.value = ''
  showMemberModal.value = true
}

async function fetchTeams() {
  loading.value = true
  try {
    const res = await listTeams()
    teams.value = res ?? []
  } catch { message.error(t('common.error')) } finally { loading.value = false }
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

onMounted(fetchTeams)
</script>

<style scoped>
.team-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.team-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.team-meta { margin-bottom: 10px; }
.team-members { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.team-actions { display: flex; gap: 6px; }
</style>
