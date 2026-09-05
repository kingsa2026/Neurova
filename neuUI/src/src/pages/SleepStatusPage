&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;MedicineBoxOutlined :style="{ color: '#6366f1' }" /&gt;
        &lt;h2 &gt;睡眠状态&lt;/h2&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;a-select
          v-model:value="currentAgentId"
          style="width: 200px"
          placeholder="选择 Agent"
          @change="loadData"
        &gt;
          &lt;a-select-option
            v-for="agent in agents"
            :key="agent.agent_id"
            :value="agent.agent_id"
          &gt;
            {{ agent.name }}
          &lt;/a-select-option&gt;
        &lt;/a-select&gt;
        &lt;a-button v-if="sleepStatus?.stage !== 'active'" type="primary" @click="wakeAgent"&gt;
          &lt;BulbOutlined /&gt; 唤醒 Agent
        &lt;/a-button&gt;
        &lt;a-button v-else @click="startSleep"&gt;
          &lt;RestOutlined /&gt; 启动睡眠
        &lt;/a-button&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- 状态卡片 --&gt;
    &lt;div &gt;
      &lt;div
        v-for="stage in sleepStages"
        :key="stage.id"
        :
        @click="setTargetStage(stage.id)"
      &gt;
        &lt;div  :style="{ background: stage.color }"&gt;
          {{ stage.label }}
        &lt;/div&gt;
        &lt;div &gt;
          &lt;img :src="stage.gif" :alt="stage.label" /&gt;
        &lt;/div&gt;
        &lt;div  v-if="sleepStatus?.stage === stage.id"&gt;
          {{ formatDuration(sleepStatus.duration_seconds) }}
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- 脑波动画 --&gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;h3&gt;脑波活动&lt;/h3&gt;
        &lt;span  :style="{ color: currentStage?.color }"&gt;
          {{ sleepStatus?.brainwave_pattern || 'Beta 波' }}
        &lt;/span&gt;
      &lt;/div&gt;
      &lt;BrainwaveVisualizer :stage="sleepStatus?.stage || 'active'" /&gt;
    &lt;/div&gt;
    &lt;!-- 统计卡片 --&gt;
    &lt;div &gt;
      &lt;div
        v-for="stat in statCards"
        :key="stat.id"
        @click="openDetailModal(stat.id)"
      &gt;
        &lt;div  :style="{ background: stat.color }"&gt;
          &lt;component :is="stat.icon" /&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stat.value }}&lt;/div&gt;
          &lt;div &gt;{{ stat.label }}&lt;/div&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;RightOutlined /&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- 详情弹窗 --&gt;
    &lt;a-modal
      v-model:open="detailModalVisible"
      :title="detailModalTitle"
      :width="800"
      :footer="null"
    &gt;
      &lt;template v-if="currentDetailType === 'dreams'"&gt;
        &lt;DreamLogDetail :agentId="currentAgentId" /&gt;
      &lt;/template&gt;
      &lt;template v-else-if="currentDetailType === 'insights'"&gt;
        &lt;DreamInsightDetail :agentId="currentAgentId" /&gt;
      &lt;/template&gt;
      &lt;template v-else-if="currentDetailType === 'merges'"&gt;
        &lt;MemoryMergeDetail :agentId="currentAgentId" /&gt;
      &lt;/template&gt;
      &lt;template v-else-if="currentDetailType === 'conflicts'"&gt;
        &lt;ConflictResolutionDetail :agentId="currentAgentId" /&gt;
      &lt;/template&gt;
    &lt;/a-modal&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAgentStore } from '@/stores/agents'
import { message } from 'ant-design-vue'
import { MedicineBoxOutlined, BulbOutlined, RestOutlined, RightOutlined, MessageOutlined, MergeCellsOutlined, SafetyCertificateOutlined } from '@ant-design/icons-vue'
import { sleepAPI, type SleepStage, type SleepStatus } from '@/api/modules/sleep'
import BrainwaveVisualizer from '@/components/BrainwaveVisualizer.vue'
import DreamLogDetail from '@/components/sleep/DreamLogDetail.vue'
import DreamInsightDetail from '@/components/sleep/DreamInsightDetail.vue'
import MemoryMergeDetail from '@/components/sleep/MemoryMergeDetail.vue'
import ConflictResolutionDetail from '@/components/sleep/ConflictResolutionDetail.vue'
import { useAgentPage } from '@/composables/useAgentPage'
// 使用 composable
const { agentId, agentStore, initAgent } = useAgentPage(
  '/agent/:agentId/sleep/status',
  (newAgentId) =&gt; {
    // agent 变化时的回调：重新加载数据
    loadData()
  }
)
const currentAgentId = agentId // 别名，保持模板兼容
const agents = computed(() =&gt; agentStore.agents)
const sleepStatus = ref&lt;SleepStatus | null&gt;(null)
const detailModalVisible = ref(false)
const currentDetailType = ref&lt;string&gt;('')
const detailModalTitle = ref('')
// 睡眠阶段配置
const sleepStages = [
  { id: 'active' as SleepStage, label: '活跃', color: '#6366f1', gif: '/img/sleep1.gif' },
  { id: 'light' as SleepStage, label: '浅睡', color: '#8b5cf6', gif: '/img/sleep2.gif' },
  { id: 'rem' as SleepStage, label: '眼动期', color: '#ec4899', gif: '/img/sleep2.gif' },
  { id: 'deep' as SleepStage, label: '深睡', color: '#1e40af', gif: '/img/sleep4.gif' },
]
// 统计卡片配置
const statCards = [
  { id: 'dreams', label: '梦境日志', icon: MessageOutlined, color: '#8b5cf6', value: '0' },
  { id: 'insights', label: '梦境洞察', icon: BulbOutlined, color: '#ec4899', value: '0' },
  { id: 'merges', label: '合并记忆', icon: MergeCellsOutlined, color: '#6366f1', value: '0' },
  { id: 'conflicts', label: '解决冲突', icon: SafetyCertificateOutlined, color: '#10b981', value: '0' },
]
const currentStage = computed(() =&gt; 
  sleepStages.find(s =&gt; s.id === sleepStatus.value?.stage)
)
// 格式化时长
function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  if (hours &gt; 0) {
    return `${hours}小时 ${remainingMinutes}分钟`
  }
  return `${remainingMinutes}分钟`
}
// 加载数据
async function loadData() {
  try {
    const [statusRes, dreamsRes, insightsRes, mergesRes, conflictsRes] = await Promise.all([
      sleepAPI.getStatus(currentAgentId.value),
      sleepAPI.getDreamLogs(currentAgentId.value, { limit: 1 }),
      sleepAPI.getDreamInsights(currentAgentId.value, { limit: 1 }),
      sleepAPI.getMemoryMerges(currentAgentId.value, { limit: 1 }),
      sleepAPI.getConflictResolutions(currentAgentId.value, { limit: 1 }),
    ])
    sleepStatus.value = statusRes
    statCards[0].value = dreamsRes.total.toString()
    statCards[1].value = insightsRes.total.toString()
    statCards[2].value = mergesRes.total.toString()
    statCards[3].value = conflictsRes.total.toString()
  } catch (error) {
    console.error('加载睡眠状态失败:', error)
  }
}
// 唤醒Agent
async function wakeAgent() {
  try {
    await sleepAPI.wakeUp(currentAgentId.value)
    message.success('Agent 已唤醒')
    await loadData()
  } catch (error) {
    message.error('唤醒失败')
  }
}
// 启动睡眠
async function startSleep() {
  try {
    await sleepAPI.startSleep(currentAgentId.value)
    message.success('已启动睡眠')
    await loadData()
  } catch (error) {
    message.error('启动睡眠失败')
  }
}
// 打开详情弹窗
function openDetailModal(type: string) {
  currentDetailType.value = type
  const typeNames: Record&lt;string, string&gt; = {
    dreams: '梦境日志',
    insights: '梦境洞察',
    merges: '合并记忆',
    conflicts: '解决冲突',
  }
  detailModalTitle.value = typeNames[type] || type
  detailModalVisible.value = true
}
// 设置目标阶段
function setTargetStage(stage: SleepStage) {
  if (stage !== 'active') {
    startSleep()
  }
}
onMounted(() =&gt; {
  loadData()
  // 定期刷新（30秒，避免触发限流）
  const interval = setInterval(loadData, 30000)
  return () =&gt; clearInterval(interval)
})
&lt;/script&gt;
&lt;style scoped&gt;
.pg { display: flex; flex-direction: column; gap: 14px; }
.hd { padding: 16px 24px; border-radius: 12px; display: flex; justify-content: space-between; align-items: center; }
.hd-left { display: flex; align-items: center; gap: 12px; }
.hd-right { display: flex; gap: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; }
.status-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.status-card { padding: 20px; border-radius: 16px; cursor: pointer; transition: all 0.3s ease; position: relative; display: flex; flex-direction: column; align-items: center; }
.status-card:hover { transform: translateY(-4px); }
.status-card.active { border: 3px solid #6366f1; box-shadow: 0 0 30px rgba(99, 102, 241, 0.4), inset 0 0 20px rgba(99, 102, 241, 0.1); animation: pulse-glow 2s ease-in-out infinite; }
@keyframes pulse-glow {
  0%, 100% { box-shadow: 0 0 30px rgba(99, 102, 241, 0.4), inset 0 0 20px rgba(99, 102, 241, 0.1); }
  50% { box-shadow: 0 0 50px rgba(99, 102, 241, 0.6), inset 0 0 30px rgba(99, 102, 241, 0.15); }
}
.stage-badge { position: absolute; top: 12px; left: 12px; padding: 4px 12px; border-radius: 20px; color: white; font-size: 0.75rem; font-weight: 600; }
.stage-gif { width: 100%; aspect-ratio: 1; max-width: 120px; margin: 20px 0; display: flex; align-items: center; justify-content: center; }
.stage-gif img { width: 100%; height: 100%; object-fit: contain; border-radius: 12px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3); transition: all 0.3s ease; }
.status-card.active .stage-gif img { border: 2px solid rgba(255, 255, 255, 0.5); box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4); transform: scale(1.05); }
.stage-duration { color: #e2e8f0; font-size: 0.85rem; }
.brainwave-container { padding: 24px; border-radius: 12px; }
.brainwave-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.brainwave-header h3 { color: #e2e8f0; margin: 0; font-size: 1.1rem; }
.brainwave-label { font-weight: 600; font-size: 0.9rem; }
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.stat-card { padding: 20px; border-radius: 12px; display: flex; align-items: center; gap: 16px; cursor: pointer; transition: all 0.3s ease; }
.stat-card:hover { transform: translateX(4px); background: rgba(255, 255, 255, 0.06) !important; }
.stat-icon { width: 48px; height: 48px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 1.2rem; color: white; }
.stat-info { flex: 1; }
.stat-value { color: #e2e8f0; font-size: 1.5rem; font-weight: 700; }
.stat-label { color: rgba(255, 255, 255, 0.5); font-size: 0.85rem; }
.stat-arrow { color: rgba(255, 255, 255, 0.3); }
@media (max-width: 1200px) {
  .status-grid { grid-template-columns: repeat(2, 1fr); }
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 768px) {
  .status-grid { grid-template-columns: 1fr; }
  .stats-grid { grid-template-columns: 1fr; }
}
&lt;/style&gt;
&nbsp;