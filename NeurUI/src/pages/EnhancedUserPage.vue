<template>
  <div class="enhanced-user-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('system.users') }}</h2>
        <p class="page-global-hint">{{ t('common.globalSettingHint') }}</p>
      </div>
      <div class="header-actions">
        <GlassButton variant="ghost" size="sm" @click="doBackupUsers">{{ t('common.export') }}</GlassButton>
        <GlassButton variant="primary" size="sm" @click="showCreate = true">{{ t('common.create') }}</GlassButton>
      </div>
    </div>

    <!-- 非管理员:仅提示 -->
    <template v-if="!isAdmin">
      <div class="admin-gate">{{ t('common.adminOnlyHint') }}</div>
    </template>
    <template v-else>
    <!-- Search -->
    <GlassCard>
      <div class="filters-row">
        <a-input-search v-model:value="searchQuery" :placeholder="t('common.search')" style="width: 300px" @search="fetchUsers" allow-clear />
      </div>
    </GlassCard>

    <!-- User table -->
    <GlassCard style="margin-top: 16px">
      <a-table
        :columns="columns"
        :data-source="users"
        :loading="loading"
        row-key="id"
        :pagination="{ current: page, pageSize: pageSize, total, showSizeChanger: true, onChange: onPageChange }"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'username'">
            <div class="user-cell">
              <div class="user-avatar">{{ record.username?.charAt(0)?.toUpperCase() }}</div>
              <span class="user-name">{{ record.username }}</span>
            </div>
          </template>
          <template v-if="column.key === 'role'">
            <a-tag :color="record.role === 'admin' ? 'purple' : record.role === 'editor' ? 'blue' : 'default'">{{ record.role }}</a-tag>
          </template>
          <template v-if="column.key === 'group'">
            <a-tag v-if="deptGroupOf(record.username)" color="geekblue">{{ deptGroupOf(record.username)?.name }}</a-tag>
            <span v-else class="mono">—</span>
          </template>
          <template v-if="column.key === 'status'">
            <a-badge :status="record.active ? 'success' : 'default'" :text="record.active ? t('common.active') : t('common.inactive')" />
          </template>
          <template v-if="column.key === 'quota'">
            <span class="mono">{{ record.quota_used ?? 0 }} / {{ record.quota_limit ?? '∞' }}</span>
          </template>
          <template v-if="column.key === 'actions'">
            <div class="action-btns">
              <GlassButton variant="ghost" size="sm" @click="editUser(record)">{{ t('common.edit') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" @click="changePassword(record)">{{ t('user.changePassword') }}</GlassButton>
              <GlassButton variant="danger" size="sm" @click="doDeleteUser(record.id)">{{ t('common.delete') }}</GlassButton>
            </div>
          </template>
        </template>
      </a-table>
    </GlassCard>

    <!-- Create/Edit user modal -->
    <a-modal v-model:open="showCreate" :title="editingUser ? t('common.edit') : t('common.create')" @ok="saveUser" :confirm-loading="saving">
      <a-form layout="vertical" :model="userForm">
        <a-form-item :label="t('auth.username')">
          <a-input v-model:value="userForm.username" :disabled="!!editingUser" />
        </a-form-item>
        <a-form-item :label="t('auth.email')">
          <a-input v-model:value="userForm.email" />
        </a-form-item>
        <a-form-item v-if="!editingUser" :label="t('auth.password')">
          <a-input-password v-model:value="userForm.password" />
        </a-form-item>
        <a-form-item :label="t('auth.role')">
          <a-select v-model:value="userForm.role" style="width: 100%">
            <a-select-option value="user">{{ t('auth.user') }}</a-select-option>
            <a-select-option value="editor">{{ t('auth.editor') }}</a-select-option>
            <a-select-option value="admin">{{ t('auth.admin') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('auth.active')">
          <a-switch v-model:checked="userForm.active" />
        </a-form-item>
        <a-form-item :label="t('system.userGroup')">
          <p class="modules-hint">{{ t('system.reloginHint') }}</p>
          <a-select
            v-model:value="userForm.group_id"
            :options="deptGroupOptions"
            allow-clear
            :placeholder="t('system.parentGroupNone')"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Change password modal -->
    <a-modal v-model:open="showPasswordModal" :title="t('auth.changePassword')" @ok="savePassword" :confirm-loading="saving">
      <a-form layout="vertical">
        <a-form-item :label="t('auth.password')">
          <a-input-password v-model:value="newPassword" />
        </a-form-item>
        <a-form-item :label="t('auth.confirmPassword')">
          <a-input-password v-model:value="confirmPassword" />
        </a-form-item>
      </a-form>
    </a-modal>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { enhancedUsersApi } from '@/api/modules'
import { listGroups, addGroupMember, removeGroupMember, type Group } from '@/api/modules/groups'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message, Modal } from 'ant-design-vue'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const authStore = useAuthStore()
/** 用户管理为全局管理数据; 仅管理员可访问与操作 */
const isAdmin = computed(() => authStore.user?.role === 'admin')

const loading = ref(false)
const saving = ref(false)
const users = ref<enhancedUsersApi.User[]>([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const searchQuery = ref('')
const showCreate = ref(false)
const showPasswordModal = ref(false)
const editingUser = ref<enhancedUsersApi.User | null>(null)
const selectedUserId = ref<string>('')
const newPassword = ref('')
const confirmPassword = ref('')

const userForm = ref<{ username: string; email: string; password: string; role: string; active: boolean; group_id: string }>({ username: '', email: '', password: '', role: 'user', active: true, group_id: '' })

// 部门分组（specs/2026-11-07 批 F1）：归属按 username 记账（groups members）
const groups = ref<Group[]>([])
const deptGroups = computed(() => groups.value.filter(g => !g.is_system))
const deptGroupOptions = computed(() => deptGroups.value.map(g => ({ label: g.name, value: g.group_id })))
const deptGroupOf = (username?: string) =>
  deptGroups.value.find(g => (g.members || []).includes(username || '')) || null

const fetchGroups = async () => {
  try {
    groups.value = (await listGroups()) ?? []
  } catch {
    groups.value = []
  }
}

const columns = computed(() => [
  { title: t('auth.username'), key: 'username' },
  { title: t('auth.email'), dataIndex: 'email', key: 'email' },
  { title: t('system.userGroup'), key: 'group', width: 140 },
  { title: t('auth.role'), key: 'role', width: 100 },
  { title: t('common.status'), key: 'status', width: 100 },
  { title: t('auth.quota'), key: 'quota', width: 120 },
  { title: t('common.actions'), key: 'actions', width: 240 },
])

const fetchUsers = async () => {
  loading.value = true
  try {
    const params: enhancedUsersApi.UserListParams = { page: page.value, page_size: pageSize.value }
    if (searchQuery.value) params.search = searchQuery.value
    const res = await enhancedUsersApi.listUsers(params)
    users.value = res?.items ?? res?.users ?? (Array.isArray(res) ? res : [])
    total.value = res?.total ?? users.value.length
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

onMounted(fetchGroups)

const saveUser = async () => {
  saving.value = true
  try {
    if (editingUser.value) {
      await enhancedUsersApi.updateUser(editingUser.value.id, { email: userForm.value.email, role: userForm.value.role, active: userForm.value.active })
      // 部门归属变更（单主组）：先出旧部门再入新部门（后端 409 文案透出）
      const previous = deptGroupOf(userForm.value.username)
      const target = userForm.value.group_id || ''
      if ((previous?.group_id || '') !== target) {
        if (previous?.group_id) {
          await removeGroupMember(previous.group_id, userForm.value.username)
        }
        if (target) {
          await addGroupMember(target, { username: userForm.value.username })
        }
      }
    } else {
      await enhancedUsersApi.createUser(userForm.value)
      if (userForm.value.group_id) {
        await addGroupMember(userForm.value.group_id, { username: userForm.value.username })
      }
    }
    message.success(t('common.success'))
    showCreate.value = false
    editingUser.value = null
    userForm.value = { username: '', email: '', password: '', role: 'user', active: true, group_id: '' }
    await fetchUsers()
    await fetchGroups()
  } catch (err) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    message.error(detail || t('common.error'))
  } finally {
    saving.value = false
  }
}

const editUser = (user: enhancedUsersApi.User) => {
  editingUser.value = user
  userForm.value = {
    username: user.username,
    email: user.email ?? '',
    password: '',
    role: user.role ?? 'user',
    active: user.active ?? true,
    group_id: deptGroupOf(user.username)?.group_id || '',
  }
  showCreate.value = true
}

const changePassword = (user: enhancedUsersApi.User) => {
  selectedUserId.value = user.id
  newPassword.value = ''
  confirmPassword.value = ''
  showPasswordModal.value = true
}

const savePassword = async () => {
  if (newPassword.value !== confirmPassword.value) {
    message.error(t('validation.passwordMismatch'))
    return
  }
  saving.value = true
  try {
    await enhancedUsersApi.updatePassword(selectedUserId.value, { password: newPassword.value })
    message.success(t('common.success'))
    showPasswordModal.value = false
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

const doDeleteUser = (id: string) => {
  Modal.confirm({
    title: t('common.confirm'),
    content: t('agent.deleteConfirm'),
    onOk: async () => {
      try {
        await enhancedUsersApi.deleteUser(id)
        message.success(t('common.success'))
        await fetchUsers()
      } catch {
        message.error(t('common.error'))
      }
    },
  })
}

const doBackupUsers = async () => {
  try {
    const res = await enhancedUsersApi.backupUsers()
    const blob = new Blob([res], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'users-backup.json'
    a.click()
    URL.revokeObjectURL(url)
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  }
}

const onPageChange = (p: number, ps: number) => { page.value = p; pageSize.value = ps; fetchUsers() }

onMounted(fetchUsers)
</script>

<style scoped>
.enhanced-user-page { display: flex; flex-direction: column; gap: 16px; }
/* 全局说明与权限提示 */
.page-global-hint { margin: 4px 0 0; font-size: 12px; color: var(--nr-text-secondary, #8a8a92); }
.admin-gate { margin: 24px auto; max-width: 480px; padding: 16px; border: 1px dashed var(--nr-border, rgba(255, 255, 255, 0.12)); border-radius: 10px; text-align: center; font-size: 13px; color: var(--nr-text-secondary, #8a8a92); }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; gap: 8px; }
.filters-row { display: flex; gap: 12px; align-items: center; }
.user-cell { display: flex; align-items: center; gap: 10px; }
.user-avatar { width: 30px; height: 30px; border-radius: 8px; background: var(--nr-gradient-primary, linear-gradient(135deg, #6366f1, #8b5cf6)); color: white; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px; flex-shrink: 0; }
.user-name { font-weight: 500; color: var(--nr-text-primary); }
.action-btns { display: flex; gap: 4px; }
.mono { font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-secondary); }
</style>
