<template>
  <div >
    <!-- 加载状态 -->
    <div  v-if="agentStore.loading">
      <a-spin size="small" />
      <span>加载 Agent...</span>
    </div>
    <!-- 有 Agent 时显示 -->
    <template v-else-if="agentStore.agents.length > 0">
      <!-- Agent 切换器 -->
      <div  @click="showAgentSelector = !showAgentSelector">
        <div >
          <RobotOutlined v-if="!currentAgent" />
          <span v-else >{{ currentAgent.name?.charAt(0)?.toUpperCase() || 'A' }}</span>
        </div>
        <div >
          <div >{{ currentAgent?.name || '选择 Agent' }}</div>
          <div  :>
            {{ currentAgent?.status === 'active' ? '在线' : '离线' }}
          </div>
        </div>
        <DownOutlined  : />
      </div>
      <!-- Agent 选择器下拉 -->
      <div  v-if="showAgentSelector">
        <div
          v-for="agent in agentStore.agents"
          :key="agent.id || agent.agentId"
          :
          @click="switchAgent(agent)"
        >
          <div >
            {{ agent.name?.charAt(0)?.toUpperCase() || 'A' }}
          </div>
          <div >
            <div >{{ agent.name }}</div>
            <div >{{ agent.description || '暂无描述' }}</div>
          </div>
        </div>
        <div  @click="navigate('/agents/create')">
          <PlusOutlined />
          <span>创建新 Agent</span>
        </div>
      </div>
      <!-- Agent 专属页面导航 -->
      <div  v-if="agentStore.currentAgentId">
        <div >Agent 功能</div>
        <div
          v-for="item in agentNavItems"
          :key="item.path"
          :
          @click="navigate(item.path)"
        >
          <component :is="item.icon"  />
          <span >{{ item.label }}</span>
        </div>
      </div>
      <!-- 未选择 Agent 提示 -->
      <div  v-else>
        <InfoCircleOutlined />
        <span>请先选择 Agent</span>
      </div>
    </template>
    <!-- 无 Agent 时显示 -->
    <div  v-else>
      <InfoCircleOutlined />
      <span>暂无 Agent，请先创建</span>
      <a-button type="link" size="small" @click="navigate('/agents/create')">创建 Agent</a-button>
    </div>
  </div>
</template>
<script setup lang="ts">
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
const currentAgent = computed(() => agentStore.currentAgent)
// 切换 Agent
function switchAgent(agent: Record<string, unknown>) {
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
  if (!target.closest('.agent-switcher') && !target.closest('.agent-selector-dropdown')) {
    showAgentSelector.value = false
  }
}
onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  // 加载 Agent 列表
  if (agentStore.agents.length === 0) {
    agentStore.loadAgents()
  }
})
</script>
<style scoped>
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
</style>
 