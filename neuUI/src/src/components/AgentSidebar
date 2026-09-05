&lt;template&gt;
  &lt;div &gt;
    &lt;!-- Agent 切换器 --&gt;
    &lt;div  @click="toggleDropdown"&gt;
      &lt;div &gt;
        &lt;a-avatar size="small" &gt;
          {{ currentAgentName.charAt(0).toUpperCase() }}
        &lt;/a-avatar&gt;
        &lt;span &gt;{{ currentAgentName || '选择 Agent' }}&lt;/span&gt;
        &lt;CaretDownOutlined  /&gt;
      &lt;/div&gt;
      &lt;div v-if="showDropdown" &gt;
        &lt;div
          v-for="agent in agents"
          :key="agent.id || agent.agentId"
          :
          @click.stop="switchAgent(agent.id || agent.agentId)"
        &gt;
          &lt;a-avatar size="small" &gt;
            {{ (agent.name || 'A').charAt(0).toUpperCase() }}
          &lt;/a-avatar&gt;
          &lt;span &gt;{{ agent.name || '未命名' }}&lt;/span&gt;
          &lt;CheckOutlined v-if="(agent.id || agent.agentId) === currentAgentId"  /&gt;
        &lt;/div&gt;
        &lt;div  /&gt;
        &lt;div  @click.stop="$router.push('/agents/create')"&gt;
          &lt;PlusOutlined  /&gt;
          &lt;span &gt;创建新 Agent&lt;/span&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- Agent 专属菜单 --&gt;
    &lt;div &gt;
      &lt;a-menu
        v-model:selectedKeys="selectedKeys"
        mode="inline"
        @click="onMenuClick"
      &gt;
        &lt;a-menu-item key="chat"&gt;
          &lt;template #icon&gt;&lt;MessageOutlined /&gt;&lt;/template&gt;
          聊天
        &lt;/a-menu-item&gt;
        &lt;a-sub-menu key="memory" title="记忆与认知"&gt;
          &lt;template #icon&gt;&lt;RobotOutlined /&gt;&lt;/template&gt;
          &lt;a-menu-item key="memory"&gt;记忆管理&lt;/a-menu-item&gt;
          &lt;a-menu-item key="experience"&gt;经验知识库&lt;/a-menu-item&gt;
          &lt;a-menu-item key="knowledge-graph"&gt;知识图谱&lt;/a-menu-item&gt;
          &lt;a-menu-item key="metacognition"&gt;元认知&lt;/a-menu-item&gt;
          &lt;a-menu-item key="reflection"&gt;反思管理&lt;/a-menu-item&gt;
          &lt;a-menu-item key="growth"&gt;成长系统&lt;/a-menu-item&gt;
        &lt;/a-sub-menu&gt;
        &lt;a-sub-menu key="skills" title="技能与学习"&gt;
          &lt;template #icon&gt;&lt;ThunderboltOutlined /&gt;&lt;/template&gt;
          &lt;a-menu-item key="skills"&gt;Agent 技能&lt;/a-menu-item&gt;
        &lt;/a-sub-menu&gt;
        &lt;a-sub-menu key="knowledge" title="知识与文件"&gt;
          &lt;template #icon&gt;&lt;FileTextOutlined /&gt;&lt;/template&gt;
          &lt;a-menu-item key="files"&gt;文件管理&lt;/a-menu-item&gt;
          &lt;a-menu-item key="media"&gt;媒体处理&lt;/a-menu-item&gt;
        &lt;/a-sub-menu&gt;
        &lt;a-sub-menu key="schedule" title="调度与规则"&gt;
          &lt;template #icon&gt;&lt;ScheduleOutlined /&gt;&lt;/template&gt;
          &lt;a-menu-item key="scheduler"&gt;调度器&lt;/a-menu-item&gt;
          &lt;a-menu-item key="rules"&gt;规则管理&lt;/a-menu-item&gt;
        &lt;/a-sub-menu&gt;
        &lt;a-sub-menu key="personality" title="情感与人格"&gt;
          &lt;template #icon&gt;&lt;SmileOutlined /&gt;&lt;/template&gt;
          &lt;a-menu-item key="emotion"&gt;情绪分析&lt;/a-menu-item&gt;
          &lt;a-menu-item key="personality"&gt;人格配置&lt;/a-menu-item&gt;
        &lt;/a-sub-menu&gt;
        &lt;a-sub-menu key="sleep" title="睡眠管理"&gt;
          &lt;template #icon&gt;&lt;BulbOutlined /&gt;&lt;/template&gt;
          &lt;a-menu-item key="sleep-status"&gt;睡眠状态&lt;/a-menu-item&gt;
          &lt;a-menu-item key="sleep-settings"&gt;睡眠设置&lt;/a-menu-item&gt;
        &lt;/a-sub-menu&gt;
        &lt;a-menu-item key="firewall"&gt;
          &lt;template #icon&gt;&lt;SafetyOutlined /&gt;&lt;/template&gt;
          防火墙
        &lt;/a-menu-item&gt;
        &lt;a-sub-menu key="trace" title="轨迹与调试"&gt;
          &lt;template #icon&gt;&lt;BugOutlined /&gt;&lt;/template&gt;
          &lt;a-menu-item key="trajectory"&gt;轨迹回放&lt;/a-menu-item&gt;
          &lt;a-menu-item key="trace"&gt;调用追踪&lt;/a-menu-item&gt;
        &lt;/a-sub-menu&gt;
        &lt;a-sub-menu key="channels" title="渠道与通信"&gt;
          &lt;template #icon&gt;&lt;GlobalOutlined /&gt;&lt;/template&gt;
          &lt;a-menu-item key="channel"&gt;渠道管理&lt;/a-menu-item&gt;
          &lt;a-menu-item key="channel-sharing"&gt;上下文共享&lt;/a-menu-item&gt;
        &lt;/a-sub-menu&gt;
        &lt;a-menu-item key="computer"&gt;
          &lt;template #icon&gt;&lt;DesktopOutlined /&gt;&lt;/template&gt;
          计算机使用
        &lt;/a-menu-item&gt;
      &lt;/a-menu&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAgentStore } from '@/stores/agents'
import {
  CaretDownOutlined, CheckOutlined, PlusOutlined,
  MessageOutlined, RobotOutlined, ThunderboltOutlined,
  FileTextOutlined, ScheduleOutlined, SmileOutlined,
  BulbOutlined, SafetyOutlined, BugOutlined,
  GlobalOutlined, DesktopOutlined,
} from '@ant-design/icons-vue'
const router = useRouter()
const route = useRoute()
const agentStore = useAgentStore()
const showDropdown = ref(false)
const selectedKeys = ref&lt;string[]&gt;([])
const agents = computed(() =&gt; agentStore.agents)
const currentAgentId = computed(() =&gt; agentStore.currentAgentId)
const currentAgentName = computed(() =&gt; agentStore.currentAgent?.name || '未选择')
// 菜单 key → 路由映射
const keyToRoute: Record&lt;string, string&gt; = {
  'chat': '/agent/:agentId/chat',
  'memory': '/agent/:agentId/memory',
  'experience': '/agent/:agentId/experience-knowledge',
  'knowledge-graph': '/agent/:agentId/knowledge-graph',
  'metacognition': '/agent/:agentId/metacognition',
  'reflection': '/agent/:agentId/reflection',
  'growth': '/agent/:agentId/growth',
  'skills': '/agent/:agentId/skills',
  'files': '/agent/:agentId/files',
  'media': '/agent/:agentId/media',
  'scheduler': '/agent/:agentId/scheduler',
  'rules': '/agent/:agentId/rules',
  'emotion': '/agent/:agentId/emotion',
  'personality': '/agent/:agentId/personality',
  'sleep-status': '/agent/:agentId/sleep/status',
  'sleep-settings': '/agent/:agentId/sleep/settings',
  'firewall': '/agent/:agentId/firewall',
  'trajectory': '/agent/:agentId/trajectory',
  'trace': '/agent/:agentId/trace',
  'channel': '/agent/:agentId/channel',
  'channel-sharing': '/agent/:agentId/channel-sharing',
  'computer': '/agent/:agentId/computer',
}
function resolvePath(template: string): string {
  if (template.includes(':agentId')) {
    const id = currentAgentId.value || ':agentId'
    return template.replace(':agentId', id)
  }
  return template
}
function switchAgent(agentId: string) {
  agentStore.setCurrentAgent(agentId)
  showDropdown.value = false
  const match = route.path.match(/^\/agent\/[^/]+/)
  if (match) {
    const rest = route.path.replace(/^\/agent\/[^/]+/, '')
    router.push(`/agent/${agentId}${rest || '/chat'}`)
  }
}
function onMenuClick({ key }: { key: string }) {
  const template = keyToRoute[key]
  if (template) {
    const path = resolvePath(template)
    router.push(path)
  }
}
function toggleDropdown() {
  showDropdown.value = !showDropdown.value
}
function onDocClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.agent-switcher')) {
    showDropdown.value = false
  }
}
onMounted(() =&gt; {
  document.addEventListener('click', onDocClick)
  if (agentStore.agents.length === 0) {
    agentStore.loadAgents()
  }
})
onUnmounted(() =&gt; {
  document.removeEventListener('click', onDocClick)
})
&lt;/script&gt;
&lt;style scoped&gt;
.agent-sidebar {
  width: 220px;
  height: 100%;
  background: linear-gradient(180deg, rgba(10, 14, 39, 0.98), rgba(15, 21, 45, 0.96));
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  overflow: hidden;
}
/* Agent 切换器 */
.agent-switcher {
  padding: 12px 12px 8px;
  flex-shrink: 0;
  position: relative;
}
.switcher-current {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  cursor: pointer;
  transition: all 0.2s;
}
.switcher-current:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.15);
}
.switcher-avatar {
  background: linear-gradient(135deg, #3b82f6, #8b5cf6) !important;
  flex-shrink: 0;
}
.switcher-name {
  flex: 1;
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.85);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.switcher-caret {
  font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.35);
  flex-shrink: 0;
}
/* 下拉列表 */
.switcher-dropdown {
  position: absolute;
  top: 100%;
  left: 12px;
  right: 12px;
  margin-top: 4px;
  background: rgba(15, 21, 50, 0.99);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  padding: 4px;
  z-index: 1000;
  max-height: 280px;
  overflow-y: auto;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
}
.switcher-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  font-size: 0.85rem;
}
.switcher-option:hover {
  background: rgba(255, 255, 255, 0.06);
}
.switcher-option.active {
  background: rgba(96, 165, 250, 0.1);
}
.option-avatar {
  background: linear-gradient(135deg, #3b82f6, #8b5cf6) !important;
  flex-shrink: 0;
}
.option-icon {
  color: rgba(255, 255, 255, 0.5);
  font-size: 0.85rem;
  width: 24px;
  text-align: center;
  flex-shrink: 0;
}
.option-name {
  flex: 1;
  color: rgba(255, 255, 255, 0.75);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.option-check {
  color: #60a5fa;
  font-size: 0.75rem;
  flex-shrink: 0;
}
.switcher-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.06);
  margin: 4px 0;
}
/* 菜单滚动区 */
.agent-menu-scroll {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 4px 0;
}
.agent-menu {
  background: transparent !important;
  border-right: none !important;
}
:deep(.agent-menu .ant-menu-item) {
  color: rgba(255, 255, 255, 0.55) !important;
  border-radius: 6px !important;
  margin: 1px 6px !important;
  padding: 0 10px !important;
  height: 34px !important;
  line-height: 34px !important;
  font-size: 0.82rem;
}
:deep(.agent-menu .ant-menu-item:hover) {
  color: #e2e8f0 !important;
  background: rgba(255, 255, 255, 0.05) !important;
}
:deep(.agent-menu .ant-menu-item-selected) {
  background: rgba(96, 165, 250, 0.12) !important;
  color: #93c5fd !important;
}
:deep(.agent-menu .ant-menu-submenu-title) {
  color: rgba(255, 255, 255, 0.55) !important;
  border-radius: 6px !important;
  margin: 1px 6px !important;
  padding: 0 10px !important;
  height: 34px !important;
  line-height: 34px !important;
  font-size: 0.82rem;
}
:deep(.agent-menu .ant-menu-submenu-title:hover) {
  color: #e2e8f0 !important;
  background: rgba(255, 255, 255, 0.05) !important;
}
:deep(.agent-menu .ant-menu-submenu-selected &gt; .ant-menu-submenu-title) {
  color: #93c5fd !important;
}
:deep(.agent-menu .ant-menu-sub) {
  background: transparent !important;
}
:deep(.agent-menu .ant-menu-sub .ant-menu-item) {
  padding-left: 20px !important;
}
&lt;/style&gt;
&nbsp;