&lt;template&gt;
  &lt;a-layout-header &gt;
    &lt;div &gt;
      &lt;!-- 移动端菜单按钮 --&gt;
      &lt;a-button type="text"  @click="emit('toggle-sidebar')"&gt;
        &lt;MenuOutlined /&gt;
      &lt;/a-button&gt;
      &lt;!-- 面包屑 --&gt;
      &lt;a-breadcrumb &gt;
        &lt;a-breadcrumb-item v-for="item in breadcrumbs" :key="item.path || item.title"&gt;
          &lt;router-link v-if="item.path" :to="item.path" &gt;
            {{ item.icon }} {{ item.title }}
          &lt;/router-link&gt;
          &lt;span v-else &gt;{{ item.title }}&lt;/span&gt;
        &lt;/a-breadcrumb-item&gt;
      &lt;/a-breadcrumb&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;!-- 搜索 --&gt;
      &lt;a-input-search
        placeholder="搜索功能..."
        :bordered="false"
      /&gt;
      &lt;!-- 通知 --&gt;
      &lt;a-badge :count="3" size="small"&gt;
        &lt;a-button type="text"  @click="$router.push('/notifications')"&gt;
          &lt;BellOutlined /&gt;
        &lt;/a-button&gt;
      &lt;/a-badge&gt;
      &lt;!-- 用户下拉 --&gt;
      &lt;a-dropdown&gt;
        &lt;div &gt;
          &lt;a-avatar size="small" &gt;
            {{ usernameC }}
          &lt;/a-avatar&gt;
          &lt;span &gt;{{ authStore.currentUser?.username || '用户' }}&lt;/span&gt;
          &lt;CaretDownOutlined  /&gt;
        &lt;/div&gt;
        &lt;template #overlay&gt;
          &lt;a-menu &gt;
            &lt;a-menu-item key="profile" @click="$router.push('/settings')"&gt;
              &lt;UserOutlined /&gt;
              &lt;span&gt;个人设置&lt;/span&gt;
            &lt;/a-menu-item&gt;
            &lt;a-menu-divider /&gt;
            &lt;a-menu-item key="logout" @click="handleLogout"&gt;
              &lt;LogoutOutlined /&gt;
              &lt;span&gt;退出登录&lt;/span&gt;
            &lt;/a-menu-item&gt;
          &lt;/a-menu&gt;
        &lt;/template&gt;
      &lt;/a-dropdown&gt;
    &lt;/div&gt;
  &lt;/a-layout-header&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  MenuOutlined,
  BellOutlined,
  UserOutlined,
  LogoutOutlined,
  CaretDownOutlined,
} from '@ant-design/icons-vue'
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const emit = defineEmits&lt;{
  'toggle-sidebar': []
}&gt;()
// 用户名首字母
const usernameC = computed(() =&gt; {
  return (authStore.currentUser?.username || 'U')[0].toUpperCase()
})
// 面包屑
const breadcrumbs = computed(() =&gt; {
  const items: { title: string; path?: string; icon?: string }[] = []
  // 首页
  items.push({ title: '首页', path: '/dashboard', icon: '🏠' })
  const path = route.path
  const meta = route.meta as Record&lt;string, unknown&gt;
  const title = meta?.title
  if (path !== '/dashboard' &amp;&amp; title) {
    items.push({ title })
  }
  return items
})
async function handleLogout() {
  await authStore.logout()
  router.push('/login')
}
&lt;/script&gt;
&lt;style scoped&gt;
.app-header {
  background: rgba(10, 14, 39, 0.85) !important;
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  padding: 0 24px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.mobile-menu-btn {
  display: none;
  color: rgba(255, 255, 255, 0.6) !important;
}
/* 面包屑 */
:deep(.header-breadcrumb) {
  font-size: 0.85rem;
}
:deep(.header-breadcrumb .ant-breadcrumb-link) {
  color: rgba(255, 255, 255, 0.45);
}
.breadcrumb-link {
  color: rgba(255, 255, 255, 0.45) !important;
  transition: color 0.2s;
}
.breadcrumb-link:hover {
  color: #93c5fd !important;
}
.breadcrumb-current {
  color: rgba(255, 255, 255, 0.8);
}
:deep(.header-breadcrumb .ant-breadcrumb-separator) {
  color: rgba(255, 255, 255, 0.2);
}
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
/* 搜索 */
:deep(.header-search) {
  width: 200px;
}
:deep(.header-search .ant-input) {
  background: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  color: rgba(255, 255, 255, 0.7) !important;
  border-radius: 20px !important;
  font-size: 0.82rem;
  height: 34px;
}
:deep(.header-search .ant-input::placeholder) {
  color: rgba(255, 255, 255, 0.25) !important;
}
.header-icon-btn {
  color: rgba(255, 255, 255, 0.5) !important;
  font-size: 1.1rem;
}
.header-icon-btn:hover {
  color: rgba(255, 255, 255, 0.85) !important;
}
/* 用户 */
.user-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px 4px 4px;
  border-radius: 20px;
  cursor: pointer;
  transition: background 0.2s;
  border: 1px solid transparent;
}
.user-trigger:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.1);
}
.user-avatar {
  background: linear-gradient(135deg, #3b82f6, #8b5cf6) !important;
}
.user-name {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.7);
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-caret {
  font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.35);
}
/* 下拉菜单 */
:deep(.user-menu) {
  background: rgba(20, 25, 50, 0.96) !important;
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  padding: 4px;
}
:deep(.user-menu .ant-dropdown-menu-item) {
  color: rgba(255, 255, 255, 0.75) !important;
  border-radius: 6px;
}
:deep(.user-menu .ant-dropdown-menu-item:hover) {
  background: rgba(255, 255, 255, 0.06) !important;
}
@media (max-width: 768px) {
  .mobile-menu-btn { display: inline-flex; }
  :deep(.header-search) { width: 140px; }
}
&lt;/style&gt;
&nbsp;