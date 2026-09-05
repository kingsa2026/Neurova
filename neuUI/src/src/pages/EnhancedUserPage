&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;UserSwitchOutlined :style="{color:'#60a5fa'}"/&gt; 增强用户&lt;/h2&gt;
      &lt;a-space&gt;
        &lt;a-input-search v-model:value="searchText" placeholder="搜索用户..." style="width:200px" @search="loadUsers" allow-clear /&gt;
        &lt;a-select v-model:value="filterRole" placeholder="筛选角色" style="width:120px" allow-clear @change="loadUsers"&gt;
          &lt;a-select-option value="admin"&gt;管理员&lt;/a-select-option&gt;
          &lt;a-select-option value="user"&gt;用户&lt;/a-select-option&gt;
          &lt;a-select-option value="developer"&gt;开发者&lt;/a-select-option&gt;
        &lt;/a-select&gt;
        &lt;a-select v-model:value="filterStatus" placeholder="筛选状态" style="width:120px" allow-clear @change="loadUsers"&gt;
          &lt;a-select-option value="active"&gt;活跃&lt;/a-select-option&gt;
          &lt;a-select-option value="inactive"&gt;停用&lt;/a-select-option&gt;
        &lt;/a-select&gt;
        &lt;a-button type="primary" @click="showCreateModal = true"&gt;&lt;PlusOutlined /&gt; 添加用户&lt;/a-button&gt;
      &lt;/a-space&gt;
    &lt;/div&gt;
    &lt;!-- 统计 --&gt;
    &lt;div &gt;
      &lt;div &gt;总用户&lt;b &gt;{{ total }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;活跃&lt;b &gt;{{ activeCount }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;停用&lt;b &gt;{{ inactiveCount }}&lt;/b&gt;&lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- 加载状态 --&gt;
    &lt;a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" /&gt;
    &lt;!-- 用户列表 --&gt;
    &lt;div  v-else&gt;
      &lt;div v-for="u in users" :key="u.user_id"  @click="viewUser(u)"&gt;
        &lt;a-avatar :size="56" :style="{background:'linear-gradient(135deg,#3b82f6,#8b5cf6)'}"&gt;{{ u.username[0] }}&lt;/a-avatar&gt;
        &lt;h4&gt;{{ u.username }}&lt;/h4&gt;
        &lt;a-tag size="small" :color="getRoleColor(u.group_type)"&gt;{{ getRoleText(u.group_type) }}&lt;/a-tag&gt;
        &lt;div &gt;
          &lt;span&gt;邮箱: {{ u.email }}&lt;/span&gt;
          &lt;span&gt;状态: &lt;a-tag size="small" :color="u.status==='active'?'green':'default'"&gt;{{ u.status === 'active' ? '活跃' : '停用' }}&lt;/a-tag&gt;&lt;/span&gt;
          &lt;span&gt;注册: {{ formatDate(u.created_at) }}&lt;/span&gt;
          &lt;span v-if="u.last_login"&gt;最后登录: {{ formatDate(u.last_login) }}&lt;/span&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- 分页 --&gt;
    &lt;div  v-if="total &gt; pageSize"&gt;
      &lt;a-pagination v-model:current="currentPage" :total="total" :pageSize="pageSize" @change="loadUsers" show-quick-jumper /&gt;
    &lt;/div&gt;
    &lt;!-- 用户详情模态框 --&gt;
    &lt;a-modal v-model:open="viewVisible" :title="currentUser?.username" width="600px" @ok="viewVisible=false"&gt;
      &lt;a-descriptions v-if="currentUser" :column="2" bordered size="small"&gt;
        &lt;a-descriptions-item label="用户名" :span="2"&gt;{{ currentUser.username }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="邮箱"&gt;{{ currentUser.email }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="角色"&gt;{{ getRoleText(currentUser.group_type) }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="状态"&gt;{{ currentUser.status === 'active' ? '活跃' : '停用' }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="语言"&gt;{{ currentUser.language || '未设置' }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="时区"&gt;{{ currentUser.timezone || '未设置' }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="主题"&gt;{{ currentUser.theme || '默认' }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="通知"&gt;{{ currentUser.notifications ? '已开启' : '已关闭' }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="注册时间" :span="2"&gt;{{ formatDate(currentUser.created_at) }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="最后登录" :span="2"&gt;{{ currentUser.last_login ? formatDate(currentUser.last_login) : '未登录' }}&lt;/a-descriptions-item&gt;
      &lt;/a-descriptions&gt;
      &lt;template #footer&gt;
        &lt;a-space&gt;
          &lt;a-button @click="editUser(currentUser)" :loading="loadingUserDetail"&gt;编辑&lt;/a-button&gt;
          &lt;a-button danger @click="deleteUser(currentUser?.user_id)" :loading="deleting"&gt;删除&lt;/a-button&gt;
          &lt;a-button type="primary" @click="viewVisible=false"&gt;关闭&lt;/a-button&gt;
        &lt;/a-space&gt;
      &lt;/template&gt;
    &lt;/a-modal&gt;
    &lt;!-- 编辑用户模态框 --&gt;
    &lt;a-modal v-model:open="editVisible" title="编辑用户" @ok="saveUser" :confirmLoading="saving"&gt;
      &lt;a-form layout="vertical"&gt;
        &lt;a-form-item label="用户名"&gt;
          &lt;a-input v-model:value="editingUser.username" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="邮箱"&gt;
          &lt;a-input v-model:value="editingUser.email" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="角色"&gt;
          &lt;a-select v-model:value="editingUser.group_type"&gt;
            &lt;a-select-option value="admin"&gt;管理员&lt;/a-select-option&gt;
            &lt;a-select-option value="user"&gt;用户&lt;/a-select-option&gt;
            &lt;a-select-option value="developer"&gt;开发者&lt;/a-select-option&gt;
          &lt;/a-select&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="状态"&gt;
          &lt;a-select v-model:value="editingUser.status"&gt;
            &lt;a-select-option value="active"&gt;活跃&lt;/a-select-option&gt;
            &lt;a-select-option value="inactive"&gt;停用&lt;/a-select-option&gt;
          &lt;/a-select&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="语言"&gt;
          &lt;a-select v-model:value="editingUser.language"&gt;
            &lt;a-select-option value="zh-CN"&gt;中文&lt;/a-select-option&gt;
            &lt;a-select-option value="en-US"&gt;English&lt;/a-select-option&gt;
          &lt;/a-select&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="时区"&gt;
          &lt;a-input v-model:value="editingUser.timezone" placeholder="Asia/Shanghai" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="主题"&gt;
          &lt;a-select v-model:value="editingUser.theme"&gt;
            &lt;a-select-option value="dark"&gt;深色&lt;/a-select-option&gt;
            &lt;a-select-option value="light"&gt;浅色&lt;/a-select-option&gt;
          &lt;/a-select&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="通知"&gt;
          &lt;a-switch v-model:checked="editingUser.notifications" /&gt;
        &lt;/a-form-item&gt;
      &lt;/a-form&gt;
    &lt;/a-modal&gt;
    &lt;!-- 创建用户模态框 --&gt;
    &lt;a-modal v-model:open="showCreateModal" title="添加用户" @ok="createUser" :confirmLoading="creating"&gt;
      &lt;a-form layout="vertical"&gt;
        &lt;a-form-item label="用户名" :rules="[{ required: true }]"&gt;
          &lt;a-input v-model:value="newUser.username" placeholder="输入用户名" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="邮箱" :rules="[{ required: true, type: 'email' }]"&gt;
          &lt;a-input v-model:value="newUser.email" placeholder="输入邮箱" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="密码" :rules="[{ required: true }]"&gt;
          &lt;a-input-password v-model:value="newUser.password" placeholder="输入密码" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="角色"&gt;
          &lt;a-select v-model:value="newUser.group_type"&gt;
            &lt;a-select-option value="admin"&gt;管理员&lt;/a-select-option&gt;
            &lt;a-select-option value="user"&gt;用户&lt;/a-select-option&gt;
            &lt;a-select-option value="developer"&gt;开发者&lt;/a-select-option&gt;
          &lt;/a-select&gt;
        &lt;/a-form-item&gt;
      &lt;/a-form&gt;
    &lt;/a-modal&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, computed, onMounted } from 'vue'
import { UserSwitchOutlined, PlusOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { enhancedUserAPI, type EnhancedUser } from '@/api/modules/enhanced-users'
const loading = ref(false)
const users = ref&lt;EnhancedUser[]&gt;([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const searchText = ref('')
const filterRole = ref&lt;string&gt;()
const filterStatus = ref&lt;string&gt;()
const viewVisible = ref(false)
const editVisible = ref(false)
const showCreateModal = ref(false)
const currentUser = ref&lt;EnhancedUser | null&gt;(null)
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
const editingUser = ref&lt;EditingUser&gt;({ username: '', email: '', group_type: 'user', status: 'active' })
const newUser = ref({
  username: '',
  email: '',
  password: '',
  group_type: 'user'
})
const activeCount = computed(() =&gt; users.value.filter(u =&gt; u.status === 'active').length)
const inactiveCount = computed(() =&gt; users.value.filter(u =&gt; u.status !== 'active').length)
const getRoleColor = (role: string) =&gt; {
  const map: Record&lt;string, string&gt; = { admin: 'purple', developer: 'blue', user: 'default' }
  return map[role] || 'default'
}
const getRoleText = (role: string) =&gt; {
  const map: Record&lt;string, string&gt; = { admin: '管理员', developer: '开发者', user: '用户' }
  return map[role] || role
}
const formatDate = (d: string) =&gt; {
  if (!d) return '未设置'
  const dt = new Date(d)
  return `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`
}
const loadUsers = async () =&gt; {
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
const viewUser = (u: EnhancedUser) =&gt; {
  currentUser.value = u
  viewVisible.value = true
}
const editUser = (u: EnhancedUser | null) =&gt; {
  if (!u) return
  editingUser.value = { ...u }
  viewVisible.value = false
  editVisible.value = true
}
const saveUser = async () =&gt; {
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
const createUser = async () =&gt; {
  if (!newUser.value.username || !newUser.value.email || !newUser.value.password) {
    message.error('请填写必填项')
    return
  }
  creating.value = true
  try {
    await enhancedUserAPI.create(newUser.value as unknown as Parameters&lt;typeof enhancedUserAPI.create&gt;[0])
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
const deleteUser = async (id: string | number | undefined) =&gt; {
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
onMounted(() =&gt; {
  loadUsers()
})
&lt;/script&gt;
&lt;style scoped&gt;
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
&lt;/style&gt;
&nbsp;