<template>
  <div class="enhanced-user-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.users') }}</h2>
      <div class="header-actions">
        <GlassButton variant="ghost" size="sm" @click="backupUsers">{{ t('common.export') }}</GlassButton>
        <GlassButton variant="primary" size="sm" @click="showCreate = true">{{ t('common.create') }}</GlassButton>
      </div>
    </div>

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
              <GlassButton variant="danger" size="sm" @click="deleteUser(record.id)">{{ t('common.delete') }}</GlassButton>
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message, Modal } from 'ant-design-vue'

const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const users = ref<any[]>([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const searchQuery = ref('')
const showCreate = ref(false)
const showPasswordModal = ref(false)
const editingUser = ref<any>(null)
const selectedUserId = ref<string>('')
const newPassword = ref('')
const confirmPassword = ref('')

const userForm = ref({ username: '', email: '', password: '', role: 'user', active: true })

const columns = computed(() => [
  { title: t('auth.username'), key: 'username' },
  { title: t('auth.email'), dataIndex: 'email', key: 'email' },
  { title: t('auth.role'), key: 'role', width: 100 },
  { title: t('common.status'), key: 'status', width: 100 },
  { title: t('auth.quota'), key: 'quota', width: 120 },
  { title: t('common.actions'), key: 'actions', width: 240 },
])

const fetchUsers = async () => {
  loading.value = true
  try {
    const params: any = { page: page.value, page_size: pageSize.value }
    if (searchQuery.value) params.search = searchQuery.value
    const res: any = await request.get('/enhanced-users', { params })
    const data = res?.data ?? res ?? {}
    users.value = data.items ?? data.users ?? (Array.isArray(data) ? data : [])
    total.value = data.total ?? users.value.length
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const saveUser = async () => {
  saving.value = true
  try {
    if (editingUser.value) {
      await request.put(`/enhanced-users/${editingUser.value.id}`, { email: userForm.value.email, role: userForm.value.role, active: userForm.value.active })
    } else {
      await request.post('/enhanced-users', userForm.value)
    }
    message.success(t('common.success'))
    showCreate.value = false
    editingUser.value = null
    userForm.value = { username: '', email: '', password: '', role: 'user', active: true }
    await fetchUsers()
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

const editUser = (user: any) => {
  editingUser.value = user
  userForm.value = { username: user.username, email: user.email, password: '', role: user.role, active: user.active }
  showCreate.value = true
}

const changePassword = (user: any) => {
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
    await request.put(`/enhanced-users/${selectedUserId.value}/password`, { password: newPassword.value })
    message.success(t('common.success'))
    showPasswordModal.value = false
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

const deleteUser = (id: string) => {
  Modal.confirm({
    title: t('common.confirm'),
    content: t('agent.deleteConfirm'),
    onOk: async () => {
      try {
        await request.delete(`/enhanced-users/${id}`)
        message.success(t('common.success'))
        await fetchUsers()
      } catch {
        message.error(t('common.error'))
      }
    },
  })
}

const backupUsers = async () => {
  try {
    const res: any = await request.get('/enhanced-users/backup', { responseType: 'blob' })
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
