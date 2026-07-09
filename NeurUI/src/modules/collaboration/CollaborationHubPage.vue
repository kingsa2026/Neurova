<template>
  <!--
    CollaborationHubPage.vue — 协作模块中心枢纽
    职责：聚合展示协作域所有子模块的概览 + 统一快捷入口
    设计：深模块，单一职责（导航枢纽，不承载业务逻辑）
  -->
  <div class="collab-hub">
    <div class="hub-header">
      <h2>{{ t('collab.title') }}</h2>
      <p class="hub-subtitle">{{ t('collab.hubSubtitle') }}</p>
    </div>

    <!-- 概览统计卡片 -->
    <div class="hub-stats">
      <GlassCard
        v-for="stat in statCards"
        :key="stat.key"
        :title="t(stat.labelKey)"
        variant="subtle"
        padding="16px 20px"
        @click="navigateTo(stat.route)"
      >
        <div class="stat-content">
          <span class="stat-value">{{ stat.value }}</span>
          <component :is="stat.icon" class="stat-icon" />
        </div>
      </GlassCard>
    </div>

    <!-- 功能模块导航网格 -->
    <div class="hub-modules">
      <h3 class="section-title">{{ t('collab.modules') }}</h3>
      <div class="module-grid">
        <div
          v-for="mod in modules"
          :key="mod.route"
          class="module-card"
          @click="navigateTo(mod.route)"
        >
          <div class="module-icon-wrap">
            <component :is="mod.icon" class="module-icon" />
          </div>
          <div class="module-info">
            <h4>{{ t(mod.labelKey) }}</h4>
            <p>{{ t(mod.descKey) }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 最近活动 -->
    <div class="hub-recent">
      <h3 class="section-title">{{ t('collab.recentActivity') }}</h3>
      <GlassPanel variant="default" padding="18px 24px">
        <a-spin :spinning="loadingSessions">
          <a-empty v-if="!loadingSessions && recentSessions.length === 0" :description="t('common.noData')" />
          <div v-else class="recent-list">
            <div v-for="session in recentSessions.slice(0, 5)" :key="session.id" class="recent-item">
              <div class="recent-info">
                <span class="recent-name">{{ session.name }}</span>
                <a-badge :status="session.status === 'active' ? 'processing' : 'default'" :text="session.status" />
              </div>
              <GlassButton variant="ghost" size="sm" @click="navigateTo('/collaboration/sessions')">
                {{ t('common.open') }}
              </GlassButton>
            </div>
          </div>
        </a-spin>
      </GlassPanel>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 协作中心页 — 统一入口枢纽
 *
 * 不承载业务逻辑，仅作为协作域所有子模块的导航中心：
 * - 概览统计（会话/项目/任务/工作流数量，来自 store.stats 真实数据）
 * - 功能模块导航网格（11 个子模块入口）
 * - 最近活动会话预览（来自 store.history 共享状态）
 */
import { computed, onMounted, type Component } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  TeamOutlined, NodeIndexOutlined, HistoryOutlined, ProjectOutlined,
  ClockCircleOutlined, BranchesOutlined, ApiOutlined, RocketOutlined,
  BgColorsOutlined, ApartmentOutlined, FileTextOutlined,
} from '@ant-design/icons-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useCollaboration } from '@/composables/useCollaboration'

const router = useRouter()
const { t } = useI18n()

// ── 统一通过 composable 访问 store ──
// history / loading / stats 均来自 store 共享状态；loadHistory / loadStats 触发拉取
const { history, loading, stats: collabStats, loadHistory, loadStats } = useCollaboration()

// 最近活动：取 history 前 5 条（history 已是 CollabSession[]，无需本地类型）
const recentSessions = computed(() => history.value.slice(0, 5))
const loadingSessions = loading

// 概览统计：真实数据来自 store.stats；stats 未加载时用 '—' 占位
const statCards = computed(() => {
  const s = collabStats.value
  return [
    { key: 'sessions', labelKey: 'collab.sessions', value: s?.sessions ?? '—', icon: TeamOutlined, route: '/collaboration/sessions' },
    { key: 'templates', labelKey: 'collab.templates', value: s?.templates ?? '—', icon: NodeIndexOutlined, route: '/collaboration/templates' },
    { key: 'workflows', labelKey: 'collab.workflows', value: s?.workflows ?? '—', icon: RocketOutlined, route: '/collaboration/workflows' },
    { key: 'projects', labelKey: 'collab.projects', value: s?.projects ?? '—', icon: ProjectOutlined, route: '/collaboration/projects' },
  ]
})

// 11 个功能模块导航
const modules: { route: string; labelKey: string; descKey: string; icon: Component }[] = [
  { route: '/collaboration/sessions', labelKey: 'collab.sessions', descKey: 'collab.sessionsDesc', icon: TeamOutlined },
  { route: '/collaboration/templates', labelKey: 'collab.templates', descKey: 'collab.templatesDesc', icon: NodeIndexOutlined },
  { route: '/collaboration/history', labelKey: 'collab.history', descKey: 'collab.historyDesc', icon: HistoryOutlined },
  { route: '/collaboration/workflows', labelKey: 'collab.workflows', descKey: 'collab.workflowsDesc', icon: RocketOutlined },
  { route: '/collaboration/canvas', labelKey: 'collab.canvas', descKey: 'collab.canvasDesc', icon: BgColorsOutlined },
  { route: '/collaboration/projects', labelKey: 'collab.projects', descKey: 'collab.projectsDesc', icon: ProjectOutlined },
  { route: '/collaboration/teams', labelKey: 'collab.teams', descKey: 'collab.teamsDesc', icon: ApartmentOutlined },
  { route: '/collaboration/tasks', labelKey: 'collab.tasks', descKey: 'collab.tasksDesc', icon: ClockCircleOutlined },
  { route: '/collaboration/webhooks', labelKey: 'collab.webhooks', descKey: 'collab.webhooksDesc', icon: BranchesOutlined },
  { route: '/collaboration/session-sync', labelKey: 'collab.sessionsync', descKey: 'collab.sessionsyncDesc', icon: ApiOutlined },
  { route: '/collaboration/neuron', labelKey: 'collab.neuron', descKey: 'collab.neuronDesc', icon: FileTextOutlined },
]

function navigateTo(route: string) {
  router.push(route)
}

onMounted(() => {
  loadHistory()
  loadStats()
})
</script>

<style scoped>
.collab-hub { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.hub-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0 0 4px 0; }
.hub-subtitle { color: var(--nr-text-secondary); font-size: 14px; margin: 0; }

.hub-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.stat-content { display: flex; justify-content: space-between; align-items: center; }
.stat-value { font-family: var(--nr-font-display); font-size: 24px; font-weight: 700; color: var(--nr-text-primary); }
.stat-icon { font-size: 20px; color: var(--nr-text-tertiary); }

.section-title { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-size: 16px; font-weight: 600; margin: 0 0 14px 0; }

.module-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
.module-card {
  display: flex; gap: 14px; align-items: flex-start;
  padding: 16px 18px; border-radius: 12px;
  background: var(--nr-bg-secondary, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08));
  cursor: pointer; transition: all 0.2s ease;
}
.module-card:hover { background: rgba(99, 102, 241, 0.08); border-color: rgba(99, 102, 241, 0.2); }
.module-icon-wrap { display: flex; align-items: center; justify-content: center; width: 40px; height: 40px; border-radius: 10px; background: rgba(99, 102, 241, 0.12); flex-shrink: 0; }
.module-icon { font-size: 20px; color: var(--nr-primary-light, #818cf8); }
.module-info h4 { color: var(--nr-text-primary); font-size: 14px; font-weight: 600; margin: 0 0 4px 0; }
.module-info p { color: var(--nr-text-tertiary); font-size: 12px; margin: 0; line-height: 1.4; }

.recent-list { display: flex; flex-direction: column; gap: 10px; }
.recent-item { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; border-radius: 8px; background: rgba(255, 255, 255, 0.03); }
.recent-info { display: flex; gap: 10px; align-items: center; }
.recent-name { color: var(--nr-text-primary); font-size: 13px; font-weight: 500; }
</style>
