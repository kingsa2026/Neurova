&lt;template&gt;
  &lt;div &gt;
    &lt;!-- 加载状态 --&gt;
    &lt;div  v-if="agentStore.loading"&gt;
      &lt;a-spin size="small" /&gt;
      &lt;span&gt;加载 Agent...&lt;/span&gt;
    &lt;/div&gt;
    &lt;!-- 有 Agent 时显示 --&gt;
    &lt;template v-else-if="agentStore.agents.length &gt; 0"&gt;
      &lt;!-- Agent 切换器 --&gt;
      &lt;div  @click="showAgentSelector = !showAgentSelector"&gt;
        &lt;div &gt;
          &lt;RobotOutlined v-if="!currentAgent" /&gt;
          &lt;span v-else &gt;{{ currentAgent.name?.charAt(0)?.toUpperCase() || 'A' }}&lt;/span&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ currentAgent?.name || '选择 Agent' }}&lt;/div&gt;
          &lt;div  :&gt;
            {{ currentAgent?.status === 'active' ? '在线' : '离线' }}
          &lt;/div&gt;
        &lt;/div&gt;
        &lt;DownOutlined  : /&gt;
      &lt;/div&gt;
      &lt;!-- Agent 选择器下拉 --&gt;
      &lt;div  v-if="showAgentSelector"&gt;
        &lt;div
          v-for="agent in agentStore.agents"
          :key="agent.id || agent.agentId"
          :
          @click="switchAgent(agent)"
        &gt;
          &lt;div &gt;
            {{ agent.name?.charAt(0)?.toUpperCase() || 'A' }}
          &lt;/div&gt;
          &lt;div &gt;
            &lt;div &gt;{{ agent.name }}&lt;/div&gt;
            &lt;div &gt;{{ agent.description || '暂无描述' }}&lt;/div&gt;
          &lt;/div&gt;
        &lt;/div&gt;
        &lt;div  @click="navigate('/agents/create')"&gt;
          &lt;PlusOutlined /&gt;
          &lt;span&gt;创建新 Agent&lt;/span&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;!-- Agent 专属页面导航 --&gt;
      &lt;div  v-if="agentStore.currentAgentId"&gt;
        &lt;div &gt;Agent 功能&lt;/div&gt;
        &lt;div
          v-for="item in agentNavItems"
          :key="item.path"
          :
          @click="navigate(item.path)"
        &gt;
          &lt;component :is="item.icon"  /&gt;
          &lt;span &gt;{{ item.label }}&lt;/span&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;!-- 未选择 Agent 提示 --&gt;
      &lt;div  v-else&gt;
        &lt;InfoCircleOutlined /&gt;
        &lt;span&gt;请先选择 Agent&lt;/span&gt;
      &lt;/div&gt;
    &lt;/template&gt;
    &lt;!-- 无 Agent 时显示 --&gt;
    &lt;div  v-else&gt;
      &lt;InfoCircleOutlined /&gt;
      &lt;span&gt;暂无 Agent，请先创建&lt;/span&gt;
      &lt;a-button type="link" size="small" @click="navigate('/agents/create')"&gt;创建 Agent&lt;/a-button&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAgentStore } from '@/stores/agents'
import {
  RobotOutlined,
  DownOutlined,
  PlusOutlined,
  InfoCircleOutlined,
  MessageOutlined,
  DatabaseOutlined,
  BulbOutlined,
  ThunderboltOutlined,
  SmileOutlined,
  HeartOutlined,
  RestOutlined,
  SettingOutlined,
  DashboardOutlined,
  HistoryOutlined,
  ApiOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons-vue'
const router = useRouter()
const route = useRoute()
const agentStore = useAgentStore()
const showAgentSelector = ref(false)
// Agent 专属页面导航项
const agentNavItems = [
  { path: '/chat', label: '聊天', icon: MessageOutlined },
  { path: '/memory', label: '记忆管理', icon: DatabaseOutlined },
  { path: '/experience-knowledge', label: '经验知识库', icon: BulbOutlined },
  { path: '/skills', label: 'Agent 技能', icon: ThunderboltOutlined },
  { path: '/personality', label: '人格配置', icon: SmileOutlined },
  { path: '/emotion', label: '情绪分析', icon: HeartOutlined },
  { path: '/sleep/status', label: '睡眠状态', icon: RestOutlined },
  { path: '/sleep/settings', label: '睡眠设置', icon: SettingOutlined },
  { path: '/benchmark', label: '基准测试', icon: DashboardOutlined },
  { path: '/trajectory', label: '轨迹回放', icon: HistoryOutlined },
  { path: '/channel', label: '渠道管理', icon: ApiOutlined },
  { path: '/scheduler', label: '调度器', icon: ClockCircleOutlined },
]
const currentAgent = computed(() =&gt; agentStore.currentAgent)
// 切换 Agent
function switchAgent(agent: Record&lt;string, unknown&gt;) {
  const agentId = (agent.id as string) || (agent.agentId as string)
  agentStore.setCurrentAgent(agentId)
  showAgentSelector.value = false
  // 切换到该 Agent 的聊天页面
  router.push(`/agent/${agentId}/chat`)
}
// 导航
function navigate(path: string) {
  if (!agentStore.currentAgentId) return
  // 替换路径中的 /agent/:agentId/ 部分
  const fullPath = `/agent/${agentStore.currentAgentId}${path}`
  router.push(fullPath)
  showAgentSelector.value = false
}
// 判断菜单项是否激活
function isActive(path: string) {
  const fullPath = `/agent/${agentStore.currentAgentId}${path}`
  return route.path.startsWith(fullPath.split('?')[0])
}
// 点击外部关闭下拉
function handleClickOutside(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (!target.closest('.agent-switcher') &amp;&amp; !target.closest('.agent-selector-dropdown')) {
    showAgentSelector.value = false
  }
}
onMounted(() =&gt; {
  document.addEventListener('click', handleClickOutside)
  // 加载 Agent 列表
  if (agentStore.agents.length === 0) {
    agentStore.loadAgents()
  }
})
&lt;/script&gt;
&lt;style scoped&gt;
.agent-sidebar-panel {
  flex-shrink: 0;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  padding: 8px;
  max-height: 50vh;
  overflow-y: auto;
}
/* Agent 切换器 */
.agent-switcher {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.agent-switcher:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.1);
}
.agent-avatar {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 16px;
  flex-shrink: 0;
}
.avatar-text {
  font-weight: 600;
  font-size: 14px;
}
.agent-info {
  flex: 1;
  min-width: 0;
}
.agent-name {
  font-size: 13px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.9);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.agent-status {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.35);
  margin-top: 2px;
}
.agent-status.active {
  color: #52c41a;
}
.agent-switcher-arrow {
  color: rgba(255, 255, 255, 0.35);
  font-size: 10px;
  transition: transform 0.2s ease;
}
.agent-switcher-arrow.rotated {
  transform: rotate(180deg);
}
/* Agent 选择器下拉 */
.agent-selector-dropdown {
  margin-top: 4px;
  background: rgba(15, 21, 45, 0.98);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 4px;
  max-height: 240px;
  overflow-y: auto;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}
.agent-option {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.agent-option:hover {
  background: rgba(255, 255, 255, 0.06);
}
.agent-option.active {
  background: rgba(96, 165, 250, 0.12);
}
.agent-option-avatar {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}
.agent-option-info {
  flex: 1;
  min-width: 0;
}
.agent-option-name {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.9);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.agent-option-desc {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.35);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 2px;
}
.agent-option--create {
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  margin-top: 4px;
  padding-top: 8px;
  color: rgba(255, 255, 255, 0.5);
  justify-content: center;
  gap: 6px;
}
.agent-option--create:hover {
  color: #60a5fa;
}
/* Agent 专属页面导航 */
.agent-nav {
  margin-top: 8px;
}
.agent-nav-title {
  font-size: 11px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.25);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  padding: 6px 12px 4px;
}
.agent-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 12px;
  margin: 2px 4px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  color: rgba(255, 255, 255, 0.55);
  font-size: 13px;
}
.agent-nav-item:hover {
  color: rgba(255, 255, 255, 0.85);
  background: rgba(255, 255, 255, 0.05);
}
.agent-nav-item.active {
  color: #93c5fd;
  background: rgba(96, 165, 250, 0.1);
  font-weight: 500;
}
.agent-nav-icon {
  font-size: 15px;
  flex-shrink: 0;
}
.agent-nav-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 加载状态 */
.agent-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 16px 12px;
  color: rgba(255, 255, 255, 0.45);
  font-size: 12px;
}
/* 未选择 Agent 提示 */
.agent-empty {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  color: rgba(255, 255, 255, 0.35);
  font-size: 12px;
  justify-content: center;
  flex-wrap: wrap;
}
/* 滚动条 */
.agent-sidebar-panel::-webkit-scrollbar {
  width: 4px;
}
.agent-sidebar-panel::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
}
&lt;/style&gt;
&nbsp;