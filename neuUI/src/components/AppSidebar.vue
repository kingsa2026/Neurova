&lt;template&gt;
  &lt;div &gt;
    &lt;a-menu
      v-model:selectedKeys="selectedKeys"
      mode="horizontal"
      @click="onMenuClick"
    &gt;
      &lt;a-menu-item key="/dashboard"&gt;首页&lt;/a-menu-item&gt;
      &lt;a-sub-menu key="agents-menu" title="Agent"&gt;
        &lt;a-menu-item key="/agents"&gt;Agent 列表&lt;/a-menu-item&gt;
        &lt;a-menu-item key="/agents/create"&gt;创建 Agent&lt;/a-menu-item&gt;
      &lt;/a-sub-menu&gt;
      &lt;a-menu-item key="/knowledge"&gt;知识库&lt;/a-menu-item&gt;
      &lt;a-menu-item key="/models"&gt;模型管理&lt;/a-menu-item&gt;
      &lt;a-sub-menu key="system-menu" title="系统"&gt;
        &lt;a-menu-item key="/settings"&gt;系统设置&lt;/a-menu-item&gt;
        &lt;a-menu-item key="/notifications"&gt;通知中心&lt;/a-menu-item&gt;
      &lt;/a-sub-menu&gt;
    &lt;/a-menu&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
const router = useRouter()
const route = useRoute()
const selectedKeys = ref&lt;string[]&gt;(['/dashboard'])
const validRoutes = [
  '/dashboard', '/agents', '/agents/create',
  '/knowledge', '/models',
  '/settings', '/notifications',
]
watch(
  () =&gt; route.path,
  (path) =&gt; {
    if (validRoutes.includes(path)) {
      selectedKeys.value = [path]
    }
  },
  { immediate: true }
)
function onMenuClick({ key }: { key: string }) {
  router.push(key)
}
&lt;/script&gt;
&lt;style scoped&gt;
.top-menu {
  background: transparent !important;
  border-bottom: none !important;
  line-height: 46px;
  font-size: 0.85rem;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
:deep(.top-menu .ant-menu-item),
:deep(.top-menu .ant-menu-submenu) {
  color: rgba(255, 255, 255, 0.6) !important;
  border-radius: 6px !important;
  margin: 0 2px !important;
}
:deep(.top-menu .ant-menu-item:hover),
:deep(.top-menu .ant-menu-submenu:hover) {
  color: #e2e8f0 !important;
  background: rgba(255, 255, 255, 0.05) !important;
}
:deep(.top-menu .ant-menu-item-selected) {
  color: #93c5fd !important;
  background: rgba(96, 165, 250, 0.1) !important;
  border-bottom: 2px solid #60a5fa !important;
}
:deep(.top-menu .ant-menu-submenu-selected) {
  color: #93c5fd !important;
}
:deep(.top-menu .ant-menu-submenu-title:hover) {
  color: #e2e8f0 !important;
}
:deep(.top-menu .anticon) {
  font-size: 0.85rem;
}
/* 下拉弹出层 */
:deep(.ant-menu-submenu-popup .ant-menu) {
  background: rgba(15, 21, 50, 0.98) !important;
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  border-radius: 10px !important;
  padding: 4px !important;
}
:deep(.ant-menu-submenu-popup .ant-menu-item) {
  color: rgba(255, 255, 255, 0.7) !important;
  border-radius: 6px !important;
}
:deep(.ant-menu-submenu-popup .ant-menu-item:hover) {
  background: rgba(255, 255, 255, 0.06) !important;
  color: #e2e8f0 !important;
}
:deep(.ant-menu-submenu-popup .ant-menu-item-selected) {
  color: #93c5fd !important;
  background: rgba(96, 165, 250, 0.1) !important;
}
&lt;/style&gt;
&nbsp;