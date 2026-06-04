<template>
  <div class="pg">
    <div class="hd glass-effect">
      <h2 class="t"><UserSwitchOutlined :style="{color:'#60a5fa'}"/> 增强用户</h2>
      <a-space>
        <a-input-search v-model:value="searchText" placeholder="搜索用户..." style="width:200px" @search="loadUsers" allow-clear />
        <a-select v-model:value="filterRole" placeholder="筛选角色" style="width:120px" allow-clear @change="loadUsers">
          <a-select-option value="admin">管理员</a-select-option>
          <a-select-option value="user">用户</a-select-option>
          <a-select-option value="developer">开发者</a-select-option>
        </a-select>
        <a-select v-model:value="filterStatus" placeholder="筛选状态" style="width:120px" allow-clear @change="loadUsers">
          <a-select-option value="active">活跃</a-select-option>
          <a-select-option value="inactive">停用</a-select-option>
        </a-select>
        <a-button type="primary" @click="showCreateModal = true"><PlusOutlined /> 添加用户</a-button>
      </a-space>
    </div>

    <!-- 统计 -->
    <div class="stats">
      <div class="s glass-effect">总用户<b class="c1">{{ total }}</b></div>
      <div class="s glass-effect">活跃<b class="c1">{{ activeCount }}</b></div>
      <div class="s glass-effect">停用<b class="c1">{{ inactiveCount }}</b></div>
    </div>

    <!-- 加载状态 -->
    <a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" />

    <!-- 用户列表 -->
    <div class="grid" v-else>
      <div v-for="u in users" :key="u.user_id" class="card glass-effect card-hover" @click="viewUser(u)">
        <a-avatar :size="56" :style="{background:'linear-gradient(135deg,#3b82f6,#8b5cf6)'}">{{ u.username[0] }}</a-avatar>
        <h4>{{ u.username }}</h4>
        <a-tag size="small" :color="getRoleColor(u.group_type)">{{ getRoleText(u.group_type) }}</a-tag>
        <div class="ud">
          <span>邮箱: {{ u.email }}</span>
          <span>状态: <a-tag size="small" :color="u.status==='active'?'green':'default'">{{ u.status === 'active' ? '活跃' : '停用' }}</a-tag></span>
          <span>注册: {{ formatDate(u.created_at) }}</span>
          <span v-if="u.last_login">最后登录: {{ formatDate(u.last_login) }}</span>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div class="pagination" v-if="total > pageSize">
      <a-pagination v-model:current="currentPage" :total="total" :pageSize="pageSize" @change="loadUsers" show-quick-jumper />
    </div>

    <!-- 用户详情模态框 -->
    <a-modal v-model:open="viewVisible" :title="currentUser?.username" width="600px" @ok="viewVisible=false">
      <a-descriptions v-if="currentUser" :column="2" bordered size="small">
        <a-descriptions-item label="用户名" :span="2">{{ currentUser.username }}</a-descriptions-item>
        <a-descriptions-item label="邮箱">{{ currentUser.email }}</a-descriptions-item>
        <a-descriptions-item label="角色">{{ getRoleText(currentUser.group_type) }}</a-descriptions-item>
        <a-descriptions-item label="状态">{{ currentUser.status === 'active' ? '活跃' : '停用' }}</a-descriptions-item>
        <a-descriptions-item label="语言">{{ currentUser.language || '未设置' }}</a-descriptions-item>
        <a-descriptions-item label="时区">{{ currentUser.timezone || '未设置' }}</a-descriptions-item>
        <a-descriptions-item label="主题">{{ currentUser.theme || '默认' }}</a-descriptions-item>
        <a-descriptions-item label="通知">{{ currentUser.notifications ? '已开启' : '已关闭' }}</a-descriptions-item>
        <a-descriptions-item label="注册时间" :span="2">{{ formatDate(currentUser.created_at) }}</a-descriptions-item>
        <a-descriptions-item label="最后登录" :span="2">{{ currentUser.last_login ? formatDate(currentUser.last_login) : '未登录' }}</a-descriptions-item>
      </a-descriptions>

      <template #footer>
        <a-space>
          <a-button @click="editUser(currentUser)" :loading="loadingUserDetail">编辑</a-button>
          <a-button danger @click="deleteUser(currentUser?.user_id)" :loading="deleting">删除</a-button>
          <a-button type="primary" @click="viewVisible=false">关闭</a-button>
        </a-space>
      </template>
    </a-modal>

    <!-- 编辑用户模态框 -->
    <a-modal v-model:open="editVisible" title="编辑用户" @ok="saveUser" :confirmLoading="saving">
      <a-form layout="vertical">
        <a-form-item label="用户名">
          <a-input v-model:value="editingUser.username" />
        </a-form-item>
        <a-form-item label="邮箱">
          <a-input v-model:value="editingUser.email" />
        </a-form-item>
        <a-form-item label="角色">
          <a-select v-model:value="editingUser.group_type">
            <a-select-option value="admin">管理员</a-select-option>
            <a-select-option value="user">用户</a-select-option>
            <a-select-option value="developer">开发者</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="状态">
          <a-select v-model:value="editingUser.status">
            <a-select-option value="active">活跃</a-select-option>
            <a-select-option value="inactive">停用</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="语言">
          <a-select v-model:value="editingUser.language">
            <a-select-option value="zh-CN">中文</a-select-option>
            <a-select-option value="en-US">English</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="时区">
          <a-input v-model:value="editingUser.timezone" placeholder="Asia/Shanghai" />
        </a-form-item>
        <a-form-item label="主题">
          <a-select v-model:value="editingUser.theme">
            <a-select-option value="dark">深色</a-select-option>
            <a-select-option value="light">浅色</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="通知">
          <a-switch v-model:checked="editingUser.notifications" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 创建用户模态框 -->
    <a-modal v-model:open="showCreateModal" title="添加用户" @ok="createUser" :confirmLoading="creating">
      <a-form layout="vertical">
        <a-form-item label="用户名" :rules="[{ required: true }]">
          <a-input v-model:value="newUser.username" placeholder="输入用户名" />
        </a-form-item>
        <a-form-item label="邮箱" :rules="[{ required: true, type: 'email' }]">
          <a-input v-model:value="newUser.email" placeholder="输入邮箱" />
        </a-form-item>
        <a-form-item label="密码" :rules="[{ required: true }]">
          <a-input-password v-model:value="newUser.password" placeholder="输入密码" />
        </a-form-item>
        <a-form-item label="角色">
          <a-select v-model:value="newUser.group_type">
            <a-select-option value="admin">管理员</a-select-option>
            <a-select-option value="user">用户</a-select-option>
            <a-select-option value="developer">开发者</a-select-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { UserSwitchOutlined, PlusOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { enhancedUserAPI, type EnhancedUser } from '@/api/modules/enhanced-users'

const loading = ref(false)
const users = ref<EnhancedUser[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const searchText = ref('')
const filterRole = ref<string>()
const filterStatus = ref<string>()

const viewVisible = ref(false)
const editVisible = ref(false)
const showCreateModal = ref(false)
const currentUser = ref<EnhancedUser | null>(null)
const loadingUserDetail = ref(false)
const saving = ref(false)
const creating = ref(false)
const deleting = ref(false)

interface EditingUser {
  user_id?: string
  username: string
  email: string
  group_type: string
  status: string
  language?: string
  timezone?: string
  theme?: string
  notifications?: boolean
}
const editingUser = ref<EditingUser>({ username: '', email: '', group_type: 'user', status: 'active' })
const newUser = ref({
  username: '',
  email: '',
  password: '',
  group_type: 'user'
})

const activeCount = computed(() => users.value.filter(u => u.status === 'active').length)
const inactiveCount = computed(() => users.value.filter(u => u.status !== 'active').length)

const getRoleColor = (role: string) => {
  const map: Record<string, string> = { admin: 'purple', developer: 'blue', user: 'default' }
  return map[role] || 'default'
}

const getRoleText = (role: string) => {
  const map: Record<string, string> = { admin: '管理员', developer: '开发者', user: '用户' }
  return map[role] || role
}

const formatDate = (d: string) => {
  if (!d) return '未设置'
  const dt = new Date(d)
  return `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`
}

const loadUsers = async () => {
  loading.value = true
  try {
    const res = await enhancedUserAPI.list({
      group_type: filterRole.value,
      status: filterStatus.value,
      limit: pageSize.value,
      offset: (currentPage.value - 1) * pageSize.value
    })
    if (res?.data) {
      users.value = Array.isArray(res.data) ? res.data : []
      total.value = res.data?.total || users.value.length
    }
  } catch (err) {
    console.error('加载用户失败', err)
    message.error('加载用户失败')
  } finally {
    loading.value = false
  }
}

const viewUser = (u: EnhancedUser) => {
  currentUser.value = u
  viewVisible.value = true
}

const editUser = (u: EnhancedUser | null) => {
  if (!u) return
  editingUser.value = { ...u }
  viewVisible.value = false
  editVisible.value = true
}

const saveUser = async () => {
  if (!editingUser.value.user_id) return
  saving.value = true
  try {
    await enhancedUserAPI.update(editingUser.value.user_id, editingUser.value)
    message.success('保存成功')
    editVisible.value = false
    loadUsers()
  } catch (err) {
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

const createUser = async () => {
  if (!newUser.value.username || !newUser.value.email || !newUser.value.password) {
    message.error('请填写必填项')
    return
  }
  creating.value = true
  try {
    await enhancedUserAPI.create(newUser.value as unknown as Parameters<typeof enhancedUserAPI.create>[0])
    message.success('创建成功')
    showCreateModal.value = false
    newUser.value = { username: '', email: '', password: '', group_type: 'user' }
    loadUsers()
  } catch (err) {
    message.error('创建失败')
  } finally {
    creating.value = false
  }
}

const deleteUser = async (id: string | number | undefined) => {
  if (!id) return
  deleting.value = true
  try {
    await enhancedUserAPI.delete(id)
    message.success('删除成功')
    viewVisible.value = false
    loadUsers()
  } catch (err) {
    message.error('删除失败')
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  loadUsers()
})
</script>

<style scoped>
.pg { display: flex; flex-direction: column; gap: 14px; }
.hd { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-radius: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; display: flex; align-items: center; gap: 8px; }
.stats { display: flex; gap: 12px; }
.s { flex: 1; padding: 14px 18px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center; color: rgba(255,255,255,0.5); font-size: 0.85rem; }
.s b { font-size: 1.4rem; }
.c1 { color: #60a5fa; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; }
.card { padding: 24px 20px; border-radius: 12px; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 10px; transition: transform 0.2s; }
.card:hover { transform: translateY(-2px); }
.card h4 { color: #e2e8f0; margin: 0; }
.ud { display: flex; flex-direction: column; align-items: center; gap: 4px; color: rgba(255,255,255,0.35); font-size: 0.78rem; }
.pagination { display: flex; justify-content: center; margin-top: 16px; }
</style>
