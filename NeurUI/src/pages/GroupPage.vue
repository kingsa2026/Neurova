<template>
  <div class="group-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.groups') }}</h2>
      <GlassButton variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
    </div>

    <!-- Group list -->
    <a-spin :spinning="loading">
      <div class="groups-grid">
        <GlassCard v-for="group in pagedGroups" :key="group.id" :title="group.name" variant="default">
          <template #header>
            <div class="group-header">
              <span class="group-name">{{ group.name }}</span>
              <a-tag>{{ group.members_count ?? 0 }} {{ t('collab.members') }}</a-tag>
            </div>
          </template>
          <p class="group-desc">{{ group.description || '-' }}</p>
          <template #footer>
            <div class="group-actions">
              <GlassButton variant="ghost" size="sm" @click="viewMembers(group)">{{ t('collab.members') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" @click="editGroup(group)">{{ t('common.edit') }}</GlassButton>
              <GlassButton variant="danger" size="sm" @click="deleteGroup(group.id)">{{ t('common.delete') }}</GlassButton>
            </div>
          </template>
        </GlassCard>
      </div>
      <a-pagination v-if="groups.length > pageSize" v-model:current="currentPage" :pageSize="pageSize" :total="groups.length" size="small" style="margin-top: 16px; text-align: center" />
      <a-empty v-if="!groups.length && !loading" :description="t('common.noData')" />
    </a-spin>

    <!-- Create/Edit group modal -->
    <a-modal v-model:open="showForm" :title="editingGroup ? t('common.edit') : t('common.create')" @ok="saveGroup" :confirm-loading="saving">
      <a-form layout="vertical" :model="groupForm" :rules="{ name: [{ required: true, message: t('common.required') }] }">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="groupForm.name" />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-textarea v-model:value="groupForm.description" :rows="3" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Members modal -->
    <a-modal v-model:open="showMembers" :title="t('collab.members')" :footer="null" width="560px">
      <div class="members-header">
        <a-input v-model:value="newMemberName" :placeholder="t('collab.addMember')" style="width: 200px" />
        <GlassButton variant="primary" size="sm" @click="addMember">{{ t('collab.addMember') }}</GlassButton>
      </div>
      <a-list :data-source="members" size="small" style="margin-top: 12px">
        <template #renderItem="{ item }">
          <a-list-item>
            <div class="member-item">
              <span>{{ item.username }}</span>
              <a-tag>{{ item.role || 'member' }}</a-tag>
              <a-popconfirm :title="t('common.confirm') + '?'" @confirm="removeMember(item.id)">
                <GlassButton variant="ghost" size="sm">{{ t('common.delete') }}</GlassButton>
              </a-popconfirm>
            </div>
          </a-list-item>
        </template>
        <template #empty><a-empty :description="t('common.noData')" /></template>
      </a-list>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { listGroups, updateGroup, createGroup, deleteGroup as deleteGroupApi, listGroupMembers, addGroupMember, removeGroupMember } from '@/api/modules/groups'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message, Modal } from 'ant-design-vue'

const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const groups = ref<any[]>([])
const members = ref<any[]>([])
const showForm = ref(false)
const showMembers = ref(false)
const editingGroup = ref<any>(null)
const selectedGroupId = ref<string>('')
const newMemberName = ref('')
const currentPage = ref(1)
const pageSize = ref(12)

const groupForm = ref({ name: '', description: '' })

const pagedGroups = computed(() =>
  groups.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value),
)

const fetchGroups = async () => {
  loading.value = true
  try {
    const res = await listGroups()
    groups.value = res ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editingGroup.value = null
  groupForm.value = { name: '', description: '' }
  showForm.value = true
}

const editGroup = (group: any) => {
  editingGroup.value = group
  groupForm.value = { name: group.name, description: group.description || '' }
  showForm.value = true
}

const saveGroup = async () => {
  saving.value = true
  try {
    if (editingGroup.value) {
      await updateGroup(editingGroup.value.id, groupForm.value)
    } else {
      await createGroup(groupForm.value)
    }
    message.success(t('common.success'))
    showForm.value = false
    await fetchGroups()
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

const deleteGroup = (id: string) => {
  Modal.confirm({
    title: t('common.confirm'),
    content: t('agent.deleteConfirm'),
    onOk: async () => {
      try {
        await deleteGroupApi(id)
        message.success(t('common.success'))
        await fetchGroups()
      } catch {
        message.error(t('common.error'))
      }
    },
  })
}

const viewMembers = async (group: any) => {
  selectedGroupId.value = group.id
  showMembers.value = true
  try {
    const res = await listGroupMembers(group.id)
    members.value = res ?? []
  } catch {
    members.value = []
  }
}

const addMember = async () => {
  if (!newMemberName.value) return
  try {
    await addGroupMember(selectedGroupId.value, { username: newMemberName.value })
    message.success(t('common.success'))
    newMemberName.value = ''
    await viewMembers({ id: selectedGroupId.value })
    await fetchGroups()
  } catch {
    message.error(t('common.error'))
  }
}

const removeMember = async (memberId: string) => {
  try {
    await removeGroupMember(selectedGroupId.value, memberId)
    message.success(t('common.success'))
    await viewMembers({ id: selectedGroupId.value })
    await fetchGroups()
  } catch {
    message.error(t('common.error'))
  }
}

onMounted(fetchGroups)
</script>

<style scoped>
.group-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.groups-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.group-header { display: flex; justify-content: space-between; align-items: center; }
.group-name { font-weight: 600; color: var(--nr-text-primary); }
.group-desc { font-size: 13px; color: var(--nr-text-secondary); }
.group-actions { display: flex; gap: 6px; }
.members-header { display: flex; gap: 8px; align-items: center; }
.member-item { display: flex; align-items: center; gap: 8px; width: 100%; }
</style>
