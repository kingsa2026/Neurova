<template>
  <nav class="nr-topnav" :aria-label="t('nav.globalNav')">
    <!-- 快捷入口 -->
    <router-link
      v-for="quick in quickItems"
      :key="quick.to"
      :to="quick.to"
      class="nr-topnav-quick"
      :class="{ 'is-active': isActiveRoute(quick.to) }"
    >
      <component :is="quick.icon" />
      <span class="nr-topnav-quick-label">{{ t(quick.labelKey) }}</span>
    </router-link>

    <!-- 分类下拉 -->
    <a-dropdown
      v-for="cat in categories"
      :key="cat.key"
      :trigger="['hover']"
      placement="bottomLeft"
    >
      <div class="nr-topnav-cat" :class="{ 'is-active': isCategoryActive(cat) }">
        <component :is="cat.icon" />
        <span class="nr-topnav-cat-label">{{ t(cat.labelKey) }}</span>
        <DownOutlined class="nr-topnav-cat-arrow" />
      </div>
      <template #overlay>
        <div class="nr-glass-dropdown">
          <router-link
            v-for="item in cat.items"
            :key="item.to"
            :to="item.to"
            class="nr-glass-dropdown-item"
            :class="{ 'is-active': isActiveRoute(item.to) }"
          >
            <component :is="item.icon" />
            <span>{{ t(item.labelKey) }}</span>
          </router-link>
        </div>
      </template>
    </a-dropdown>
  </nav>
</template>

<script setup lang="ts">
import { type Component } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  DashboardOutlined, RobotOutlined,
  DownOutlined,
  BookOutlined, AppstoreOutlined, ShopOutlined, RocketOutlined,
  NodeIndexOutlined, FileOutlined,
  CloudServerOutlined, ToolOutlined, CodeOutlined,
  BarChartOutlined, MonitorOutlined, HeartOutlined, PieChartOutlined,
  FileTextOutlined,
  TeamOutlined, ProjectOutlined, ClockCircleOutlined,
  BranchesOutlined, ApiOutlined, HistoryOutlined,
  SettingOutlined, UserOutlined, BellOutlined, AlertOutlined, AudioOutlined,
  BgColorsOutlined, ApartmentOutlined,
} from '@ant-design/icons-vue'

const route = useRoute()
const { t } = useI18n()

// ── 快捷入口(仅全局管理级) ──
const quickItems: { to: string; labelKey: string; icon: Component }[] = [
  { to: '/agents', labelKey: 'nav.agents', icon: RobotOutlined },
]

// ── 6 个全局分类 ──
interface NavItem { to: string; labelKey: string; icon: Component }
interface NavCategory {
  key: string
  labelKey: string
  icon: Component
  items: NavItem[]
}

const categories: NavCategory[] = [
  {
    key: 'knowledge',
    labelKey: 'nav.knowledge',
    icon: BookOutlined,
    items: [
      { to: '/knowledge', labelKey: 'nav.knowledge', icon: BookOutlined },
      { to: '/skill-pool', labelKey: 'nav.skillPool', icon: AppstoreOutlined },
      { to: '/marketplace/skills', labelKey: 'nav.skillMarket', icon: ShopOutlined },
      { to: '/aigc', labelKey: 'nav.aigc', icon: RocketOutlined },
    ],
  },
  {
    key: 'neuron',
    labelKey: 'nav.neuron',
    icon: RocketOutlined,
    items: [
      { to: '/neuron', labelKey: 'nav.neuron', icon: RocketOutlined },
      { to: '/files', labelKey: 'nav.files', icon: FileOutlined },
    ],
  },
  {
    key: 'development',
    labelKey: 'nav.development',
    icon: CloudServerOutlined,
    items: [
      { to: '/models', labelKey: 'nav.models', icon: CloudServerOutlined },
      { to: '/tool-layers', labelKey: 'nav.toolLayers', icon: ToolOutlined },
      { to: '/sandbox', labelKey: 'nav.sandbox', icon: CodeOutlined },
    ],
  },
  {
    key: 'operations',
    labelKey: 'nav.operations',
    icon: MonitorOutlined,
    items: [
      { to: '/stats', labelKey: 'nav.stats', icon: BarChartOutlined },
      { to: '/monitor', labelKey: 'nav.monitor', icon: MonitorOutlined },
      { to: '/health', labelKey: 'nav.health', icon: HeartOutlined },
      { to: '/logs', labelKey: 'nav.logs', icon: FileTextOutlined },
    ],
  },
  {
    key: 'collaboration',
    labelKey: 'nav.collaboration',
    icon: TeamOutlined,
    items: [
      // 协作中心枢纽（聚合入口）
      { to: '/collaboration/hub', labelKey: 'nav.collabHub', icon: DashboardOutlined },
      // 会话管理
      { to: '/collaboration/sessions', labelKey: 'nav.collabSessions', icon: TeamOutlined },
      // 工作流（从 knowledge 分类移入协作）
      { to: '/collaboration/workflows', labelKey: 'nav.workflows', icon: RocketOutlined },
      // 画布设计器（新增）
      { to: '/collaboration/canvas', labelKey: 'nav.collabCanvas', icon: BgColorsOutlined },
      // 模板与历史
      { to: '/collaboration/templates', labelKey: 'nav.collaborationtemplates', icon: NodeIndexOutlined },
      { to: '/collaboration/history', labelKey: 'nav.collaborationhistory', icon: HistoryOutlined },
      // 项目管理
      { to: '/collaboration/projects', labelKey: 'nav.projects', icon: ProjectOutlined },
      { to: '/collaboration/teams', labelKey: 'nav.teams', icon: ApartmentOutlined },
      { to: '/collaboration/tasks', labelKey: 'nav.tasks', icon: ClockCircleOutlined },
      // 集成通道
      { to: '/collaboration/webhooks', labelKey: 'nav.webhooks', icon: BranchesOutlined },
      { to: '/collaboration/session-sync', labelKey: 'nav.sessionsync', icon: ApiOutlined },
      // NEURON 依赖图谱（协作底层）
      { to: '/collaboration/neuron', labelKey: 'nav.neuron', icon: RocketOutlined },
    ],
  },
  {
    // 系统设置组（统筹：配置/访问/审计/工具按逻辑排序）
    key: 'admin',
    labelKey: 'nav.admin',
    icon: SettingOutlined,
    items: [
      // 配置域
      { to: '/settings', labelKey: 'nav.settings', icon: SettingOutlined },
      { to: '/settings/voice-transcription', labelKey: 'nav.voiceTranscription', icon: AudioOutlined },
      { to: '/models', labelKey: 'nav.models', icon: CloudServerOutlined },
      { to: '/notifications', labelKey: 'nav.notifications', icon: BellOutlined },
      // 访问域
      { to: '/enhanced-users', labelKey: 'nav.enhancedusers', icon: UserOutlined },
      { to: '/groups', labelKey: 'nav.groups', icon: TeamOutlined },
      { to: '/firewall', labelKey: 'nav.firewall', icon: AlertOutlined },
      // 审计与工具
      { to: '/audit', labelKey: 'nav.audit', icon: HistoryOutlined },
      { to: '/benchmark', labelKey: 'nav.benchmark', icon: DashboardOutlined },
      { to: '/marketplace', labelKey: 'nav.marketplace', icon: ShopOutlined },
    ],
  },
]

// ── 路由状态判定 ──
function isActiveRoute(to: string): boolean {
  return route.path === to || route.path.startsWith(to + '/')
}

function isCategoryActive(cat: NavCategory): boolean {
  return cat.items.some(item => isActiveRoute(item.to))
}
</script>

<style scoped>
.nr-topnav {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 1;
  justify-content: center;
  overflow-x: auto;
  overflow-y: hidden;
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.nr-topnav::-webkit-scrollbar {
  display: none;
}

/* ── 快捷入口 ── */
.nr-topnav-quick {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 10px;
  color: var(--nr-text-secondary);
  font-size: 13px;
  font-weight: 450;
  text-decoration: none;
  transition: all 0.2s ease;
  white-space: nowrap;
}
.nr-topnav-quick:hover {
  color: var(--nr-text-primary);
  background: var(--nr-glass-bg-hover);
}
.nr-topnav-quick.is-active {
  color: var(--nr-primary-light);
  background: var(--nr-primary-soft);
  font-weight: 550;
}
.nr-topnav-quick-label {
  display: inline;
}

/* ── 分类下拉触发器 ── */
.nr-topnav-cat {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 10px;
  color: var(--nr-text-secondary);
  font-size: 13px;
  font-weight: 450;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
  user-select: none;
}
.nr-topnav-cat:hover,
.nr-topnav-cat.is-active {
  color: var(--nr-text-primary);
  background: var(--nr-glass-bg-hover);
}
.nr-topnav-cat.is-active {
  color: var(--nr-primary-light);
  background: var(--nr-primary-soft);
}
.nr-topnav-cat-arrow {
  font-size: 10px;
  opacity: 0.6;
  transition: transform 0.2s ease;
}

/* ── 液态玻璃弹出层 ── */
.nr-glass-dropdown {
  background: var(--nr-bg-overlay);
  backdrop-filter: blur(40px) saturate(180%);
  -webkit-backdrop-filter: blur(40px) saturate(180%);
  border: 1px solid var(--nr-glass-border);
  border-radius: 14px;
  padding: 6px;
  min-width: 180px;
  box-shadow: var(--nr-shadow-lg);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* ── 弹出层菜单项 ── */
.nr-glass-dropdown-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 10px;
  color: var(--nr-text-secondary);
  font-size: 13px;
  font-weight: 450;
  text-decoration: none;
  transition: all 0.18s ease;
  white-space: nowrap;
}
.nr-glass-dropdown-item:hover {
  color: var(--nr-text-primary);
  background: var(--nr-glass-bg-hover);
}
.nr-glass-dropdown-item.is-active {
  color: var(--nr-primary-light);
  background: var(--nr-primary-soft);
  font-weight: 550;
}

/* ── 响应式: 小屏隐藏快捷入口文字和分类标签 ── */
@media (max-width: 1024px) {
  .nr-topnav-quick-label,
  .nr-topnav-cat-label {
    display: none;
  }
  .nr-topnav-cat-arrow {
    display: none;
  }
}
</style>
