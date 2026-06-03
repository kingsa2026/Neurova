<template>
  <div >
    <TransitionGroup name="memory-item" tag="div" >
      <div
        v-for="memory in memories"
        :key="memory.id"
      >
        <!-- 时间轴连接器 -->
        <div >
          <div  :style="{ background: getMemoryColor(getMemoryCategory(memory)) }">
            <component :is="getMemoryIcon(getMemoryCategory(memory))"  />
          </div>
          <div ></div>
        </div>
        <!-- 记忆卡片 -->
        <div >
          <div >
            <span  :style="{ color: getMemoryColor(getMemoryCategory(memory)) }">{{ getMemoryTypeLabel(getMemoryCategory(memory)) }}</span>
            <span >{{ formatTime(memory.timestamp) }}</span>
          </div>
          <div >{{ memory.content || memory.summary || '' }}</div>
          <div v-if="memory.tags && memory.tags.length > 0" >
            <a-tag v-for="tag in memory.tags" :key="tag" >
              {{ tag }}
            </a-tag>
          </div>
        </div>
      </div>
    </TransitionGroup>
    <div v-if="memories.length === 0" >
      <p >暂无记忆</p>
    </div>
  </div>
</template>
<script setup lang="ts">
import {
  MessageCircle,
  FileText,
  User,
  Users,
  Lightbulb,
  AlertTriangle,
  CheckSquare,
  Sparkles,
  Heart,
  Cpu,
  FileEdit,
  HelpCircle,
  Wrench,
  Zap,
  Activity,
  Camera,
  Settings,
  MessageSquare,
  type LucideIcon,
} from '@lucide/vue'
interface Memory {
  id: string
  type?: string
  category?: string
  content?: string
  summary?: string
  timestamp: number
  tags?: string[]
}
const props = defineProps<{
  memories: Memory[]
}>()
function getMemoryCategory(memory: Memory): string {
  // 优先使用 category 字段，其次 type 字段
  return memory.category || memory.type || 'conversation'
}
function getMemoryColor(type: string): string {
  const colorMap: Record<string, string> = {
    // 后端标准分类（MemoryCategory 枚举）
    'conversation': '#3b82f6',      // 对话 - 蓝色
    'fact': '#8b5cf6',              // 事实 - 紫色
    'profile': '#10b981',            // 用户画像 - 绿色
    'relationship': '#ec4899',       // 关系 - 粉色
    'experience': '#f59e0b',        // 经验 - 橙色
    'lesson': '#ef4444',            // 教训 - 红色
    'task': '#06b6d4',             // 任务 - 青色
    'creative': '#a855f7',          // 创意 - 紫色
    'emotional': '#f43f5e',        // 情感 - 玫瑰色
    'identity': '#6366f1',          // 身份 - 靛蓝色
    'reflection_log': '#14b8a6',   // 反思日志 - 青绿色
    'question_queue': '#f97316',    // 问题队列 - 橙色
    'skill': '#0ea5e9',            // 技能 - 天蓝色
    'core_command': '#dc2626',      // 核心指令 - 深红色
    'heartbeat_task': '#7c3aed',   // 心跳任务 - 紫色
    'context_snapshot': '#059669',  // 上下文快照 - 翠绿色
    'tool_usage': '#0284c7',        // 工具使用 - 蓝色
    // 兼容旧类型
    'vector': '#3b82f6',           // 向量记忆 -> 对话
    'working': '#10b981',          // 工作记忆 -> 用户画像
  }
  return colorMap[type] || '#6b7280'
}
function getMemoryIcon(type: string): LucideIcon {
  const iconMap: Record<string, LucideIcon> = {
    // 后端标准分类
    'conversation': MessageCircle,
    'fact': FileText,
    'profile': User,
    'relationship': Users,
    'experience': Lightbulb,
    'lesson': AlertTriangle,
    'task': CheckSquare,
    'creative': Sparkles,
    'emotional': Heart,
    'identity': Cpu,
    'reflection_log': FileEdit,
    'question_queue': HelpCircle,
    'skill': Wrench,
    'core_command': Zap,
    'heartbeat_task': Activity,
    'context_snapshot': Camera,
    'tool_usage': Settings,
    // 兼容旧类型
    'vector': MessageCircle,
    'working': User,
  }
  return iconMap[type] || FileText
}
function getMemoryTypeLabel(type: string): string {
  const labelMap: Record<string, string> = {
    // 后端标准分类
    'conversation': '对话记忆',
    'fact': '事实记忆',
    'profile': '用户画像',
    'relationship': '关系记忆',
    'experience': '经验记忆',
    'lesson': '教训记忆',
    'task': '任务记忆',
    'creative': '创意记忆',
    'emotional': '情感记忆',
    'identity': '身份记忆',
    'reflection_log': '反思日志',
    'question_queue': '问题队列',
    'skill': '技能记忆',
    'core_command': '核心指令',
    'heartbeat_task': '心跳任务',
    'context_snapshot': '上下文快照',
    'tool_usage': '工具使用',
    // 兼容旧类型
    'vector': '对话记忆',
    'working': '工作记忆',
  }
  return labelMap[type] || type
}
function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return date.toLocaleDateString('zh-CN')
}
</script>
<style scoped>
.memory-timeline {
  padding: 16px;
  max-height: 600px;
  overflow-y: auto;
}
.memories-container {
  position: relative;
}
.timeline-item {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
  transition: all 0.5s ease;
}
.timeline-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 32px;
  flex-shrink: 0;
}
.timeline-dot {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.9rem;
  z-index: 1;
}
.memory-icon {
  width: 16px;
  height: 16px;
  color: white;
}
.timeline-line {
  width: 2px;
  flex: 1;
  background: rgba(255, 255, 255, 0.1);
  margin-top: 4px;
}
.memory-card {
  flex: 1;
  padding: 16px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  transition: all 0.3s;
  min-width: 0;
}
.memory-card:hover {
  transform: translateX(4px);
  border-color: rgba(255, 255, 255, 0.2);
}
.memory-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.memory-type {
  font-size: 0.85rem;
  font-weight: 600;
}
.memory-time {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.4);
}
.memory-content {
  color: rgba(255, 255, 255, 0.8);
  line-height: 1.6;
  font-size: 0.95rem;
  word-break: break-word;
}
.memory-tags {
  margin-top: 8px;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.memory-tag {
  background: rgba(96, 165, 250, 0.1) !important;
  border-color: rgba(96, 165, 250, 0.3) !important;
  color: #60a5fa !important;
  font-size: 0.8rem;
}
.empty-state {
  text-align: center;
  padding: 48px 0;
}
.empty-text {
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.95rem;
}
/* TransitionGroup 动画 */
.memory-item-enter-active {
  animation: slideIn 0.5s ease;
}
.memory-item-leave-active {
  animation: slideOut 0.3s ease;
}
.memory-item-move {
  transition: transform 0.5s ease;
}
@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateX(-20px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}
@keyframes slideOut {
  from {
    opacity: 1;
    transform: translateX(0);
  }
  to {
    opacity: 0;
    transform: translateX(20px);
  }
}
</style>
 