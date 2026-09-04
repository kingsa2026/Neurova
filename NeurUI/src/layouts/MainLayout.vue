<template>
  <div class="nr-layout" :class="{ 'sidebar-collapsed': appStore.sidebarCollapsed }">
    <StarBackground v-if="appStore.isDark" />

    <!-- Sidebar -->
    <GlassNav :collapsed="appStore.sidebarCollapsed" @brand-click="router.push('/dashboard')">
      <template #brand>
        <img :src="appStore.isDark ? '/img/NEUROVA-LOGO350white.png' : '/img/NEUROVA-LOGO350black.png'" alt="Neurova" class="nr-logo-img" />
      </template>

      <!-- Agent Switcher -->
      <AgentSwitcher
        :collapsed="appStore.sidebarCollapsed"
      />

      <!-- ==================== 上半区: Agent 隔离功能 ==================== -->
      <div v-if="!appStore.sidebarCollapsed" class="nr-nav-zone-title">{{ t('nav.agentZone') }}</div>

      <template v-if="agentStore.currentAgent">
        <!-- Agent: 高频平铺 -->
        <GlassNavItem to="/chat" :label="t('nav.chat')" :collapsed="appStore.sidebarCollapsed" active-path="/chat" v-if="can('/chat')">
          <template #icon><MessageOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/memory`" :label="t('nav.memory')" :collapsed="appStore.sidebarCollapsed" v-if="can('/agent/:id/memory')">
          <template #icon><DatabaseOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/files`" :label="t('nav.agentfiles')" :collapsed="appStore.sidebarCollapsed" v-if="can('/agent/:id/files')">
          <template #icon><FileOutlined /></template>
        </GlassNavItem>

        <!-- Agent: 知识与认知（低频折叠） -->
        <GlassNavGroup
          v-if="canAgent('experience-knowledge') || canAgent('knowledge-graph') || canAgent('metacognition') || canAgent('reflection') || canAgent('growth') || canAgent('emotion') || canAgent('personality')"
          :label-key="'nav.knowledgeCognition'"
          storage-key="agent-cognition"
          :collapsed="appStore.sidebarCollapsed"
          :first-item-to="`/agent/${agentStore.currentAgentId}/experience-knowledge`"
          :count="7"
        >
          <template #icon><BulbOutlined /></template>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/experience-knowledge`" :label="t('nav.experience')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('experience-knowledge')">
            <template #icon><BulbOutlined /></template>
          </GlassNavItem>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/knowledge-graph`" :label="t('nav.knowledgeGraph')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('knowledge-graph')">
            <template #icon><ShareAltOutlined /></template>
          </GlassNavItem>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/metacognition`" :label="t('nav.metacognition')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('metacognition')">
            <template #icon><ExperimentOutlined /></template>
          </GlassNavItem>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/reflection`" :label="t('nav.reflection')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('reflection')">
            <template #icon><BulbOutlined /></template>
          </GlassNavItem>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/growth`" :label="t('nav.growth')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('growth')">
            <template #icon><RiseOutlined /></template>
          </GlassNavItem>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/emotion`" :label="t('nav.emotion')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('emotion')">
            <template #icon><HeartOutlined /></template>
          </GlassNavItem>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/personality`" :label="t('nav.personality')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('personality')">
            <template #icon><SmileOutlined /></template>
          </GlassNavItem>
        </GlassNavGroup>

        <!-- Agent: 能力（低频折叠） -->
        <GlassNavGroup
          v-if="canAgent('skills') || canAgent('rules') || canAgent('media')"
          :label-key="'nav.agentCapabilities'"
          storage-key="agent-capabilities"
          :collapsed="appStore.sidebarCollapsed"
          :first-item-to="`/agent/${agentStore.currentAgentId}/skills`"
          :count="3"
        >
          <template #icon><ThunderboltOutlined /></template>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/skills`" :label="t('nav.skills')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('skills')">
            <template #icon><ThunderboltOutlined /></template>
          </GlassNavItem>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/rules`" :label="t('nav.rules')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('rules')">
            <template #icon><SafetyOutlined /></template>
          </GlassNavItem>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/media`" :label="t('nav.media')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('media')">
            <template #icon><PlayCircleOutlined /></template>
          </GlassNavItem>
        </GlassNavGroup>

        <!-- Agent: 运行（低频折叠） -->
        <GlassNavGroup
          v-if="canAgent('scheduler') || canAgent('channel') || canAgent('sleep') || canAgent('computer') || canAgent('trace')"
          :label-key="'nav.agentRuntime'"
          storage-key="agent-runtime"
          :collapsed="appStore.sidebarCollapsed"
          :first-item-to="`/agent/${agentStore.currentAgentId}/scheduler`"
          :count="5"
        >
          <template #icon><SettingOutlined /></template>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/scheduler`" :label="t('nav.scheduler')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('scheduler')">
            <template #icon><ClockCircleOutlined /></template>
          </GlassNavItem>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/channel`" :label="t('nav.channels')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('channel')">
            <template #icon><ApiOutlined /></template>
          </GlassNavItem>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/sleep/status`" :label="t('nav.sleep')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('sleep')">
            <template #icon><CoffeeOutlined /></template>
          </GlassNavItem>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/computer`" :label="t('nav.computer')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('computer')">
            <template #icon><DesktopOutlined /></template>
          </GlassNavItem>
          <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/trace`" :label="t('nav.debug')" :collapsed="appStore.sidebarCollapsed" v-if="canAgent('trace')">
            <template #icon><CodeOutlined /></template>
          </GlassNavItem>
        </GlassNavGroup>
      </template>

      <!-- Agent 空态引导卡: 未选择 Agent 时保持上半区形态稳定 -->
      <div v-else-if="!appStore.sidebarCollapsed" class="nr-agent-empty">
        <p class="nr-agent-empty-title">{{ t('nav.agentEmptyTitle') }}</p>
        <p class="nr-agent-empty-desc">{{ t('nav.agentEmptyDesc') }}</p>
        <div class="nr-agent-empty-actions">
          <GlassButton variant="secondary" size="sm" @click="router.push('/agents')">
            {{ t('nav.agentEmptySelect') }}
          </GlassButton>
          <GlassButton variant="ghost" size="sm" @click="router.push('/agents/create')">
            {{ t('nav.agentEmptyCreate') }}
          </GlassButton>
        </div>
      </div>

      <!-- 分区线: Agent 区 / 用户区 -->
      <div class="nr-nav-divider" :class="{ collapsed: appStore.sidebarCollapsed }" />

      <!-- ==================== 下半区: 用户隔离功能 ==================== -->
      <div v-if="!appStore.sidebarCollapsed" class="nr-nav-zone-title">{{ t('nav.userZone') }}</div>
      <GlassNavItem to="/dashboard" :label="t('nav.dashboard')" :collapsed="appStore.sidebarCollapsed">
        <template #icon><DashboardOutlined /></template>
      </GlassNavItem>
      <GlassNavItem to="/agents" :label="t('nav.agents')" :collapsed="appStore.sidebarCollapsed" v-if="can('/agents')">
        <template #icon><RobotOutlined /></template>
      </GlassNavItem>
      <GlassNavItem to="/knowledge" :label="t('nav.knowledge')" :collapsed="appStore.sidebarCollapsed" v-if="can('/knowledge')">
        <template #icon><BookOutlined /></template>
      </GlassNavItem>
      <GlassNavItem to="/skill-pool" :label="t('nav.skillPool')" :collapsed="appStore.sidebarCollapsed" v-if="can('/skill-pool')">
        <template #icon><AppstoreOutlined /></template>
      </GlassNavItem>
      <GlassNavItem to="/marketplace/skills" :label="t('nav.skillMarket')" :collapsed="appStore.sidebarCollapsed" v-if="can('/marketplace/skills')">
        <template #icon><ShopOutlined /></template>
      </GlassNavItem>
      <GlassNavItem to="/aigc" :label="t('nav.aigc')" :collapsed="appStore.sidebarCollapsed" v-if="can('/aigc')">
        <template #icon><RocketOutlined /></template>
      </GlassNavItem>
      <GlassNavItem to="/files" :label="t('nav.files')" :collapsed="appStore.sidebarCollapsed" v-if="can('/files')">
        <template #icon><FileOutlined /></template>
      </GlassNavItem>
      <GlassNavItem to="/neuron" :label="t('nav.neuron')" :collapsed="appStore.sidebarCollapsed" v-if="can('/neuron')">
        <template #icon><NodeIndexOutlined /></template>
      </GlassNavItem>

      <!-- 用户: 协作（低频折叠，含全局渠道接入） -->
      <GlassNavGroup
        v-if="can('/collaboration') || can('/channels')"
        :label-key="'nav.collaboration'"
        storage-key="user-collaboration"
        :collapsed="appStore.sidebarCollapsed"
        first-item-to="/collaboration/hub"
        :count="12"
      >
        <template #icon><TeamOutlined /></template>
        <GlassNavItem to="/collaboration/hub" :label="t('nav.collabHub')" :collapsed="appStore.sidebarCollapsed" v-if="can('/collaboration')">
          <template #icon><DashboardOutlined /></template>
        </GlassNavItem>
        <GlassNavItem to="/collaboration/sessions" :label="t('nav.collabSessions')" :collapsed="appStore.sidebarCollapsed" v-if="can('/collaboration')">
          <template #icon><TeamOutlined /></template>
        </GlassNavItem>
        <GlassNavItem to="/collaboration/workflows" :label="t('nav.workflows')" :collapsed="appStore.sidebarCollapsed" v-if="can('/collaboration')">
          <template #icon><RocketOutlined /></template>
        </GlassNavItem>
        <GlassNavItem to="/collaboration/canvas" :label="t('nav.collabCanvas')" :collapsed="appStore.sidebarCollapsed" v-if="can('/collaboration')">
          <template #icon><BgColorsOutlined /></template>
        </GlassNavItem>
        <GlassNavItem to="/collaboration/templates" :label="t('nav.collaborationtemplates')" :collapsed="appStore.sidebarCollapsed" v-if="can('/collaboration')">
          <template #icon><NodeIndexOutlined /></template>
        </GlassNavItem>
        <GlassNavItem to="/collaboration/history" :label="t('nav.collaborationhistory')" :collapsed="appStore.sidebarCollapsed" v-if="can('/collaboration')">
          <template #icon><HistoryOutlined /></template>
        </GlassNavItem>
        <GlassNavItem to="/collaboration/projects" :label="t('nav.projects')" :collapsed="appStore.sidebarCollapsed" v-if="can('/collaboration')">
          <template #icon><ProjectOutlined /></template>
        </GlassNavItem>
        <GlassNavItem to="/collaboration/teams" :label="t('nav.teams')" :collapsed="appStore.sidebarCollapsed" v-if="can('/collaboration')">
          <template #icon><TeamOutlined /></template>
        </GlassNavItem>
        <GlassNavItem to="/collaboration/tasks" :label="t('nav.tasks')" :collapsed="appStore.sidebarCollapsed" v-if="can('/collaboration')">
          <template #icon><ClockCircleOutlined /></template>
        </GlassNavItem>
        <GlassNavItem to="/collaboration/webhooks" :label="t('nav.webhooks')" :collapsed="appStore.sidebarCollapsed" v-if="can('/collaboration')">
          <template #icon><BranchesOutlined /></template>
        </GlassNavItem>
        <GlassNavItem to="/collaboration/session-sync" :label="t('nav.sessionsync')" :collapsed="appStore.sidebarCollapsed" v-if="can('/collaboration')">
          <template #icon><ApiOutlined /></template>
        </GlassNavItem>
        <GlassNavItem to="/channels" :label="t('nav.channels')" :collapsed="appStore.sidebarCollapsed" v-if="can('/channels')">
          <template #icon><GlobalOutlined /></template>
        </GlassNavItem>
      </GlassNavGroup>

      <GlassNavItem to="/notifications" :label="t('nav.notifications')" :collapsed="appStore.sidebarCollapsed" v-if="can('/notifications')">
        <template #icon><BellOutlined /></template>
      </GlassNavItem>
      <GlassNavItem to="/usage-stats" :label="t('nav.usageStats')" :collapsed="appStore.sidebarCollapsed" v-if="can('/usage-stats')">
        <template #icon><LineChartOutlined /></template>
      </GlassNavItem>
      <GlassNavItem to="/analytics" :label="t('nav.analytics')" :collapsed="appStore.sidebarCollapsed" v-if="can('/analytics')">
        <template #icon><BarChartOutlined /></template>
      </GlassNavItem>
      <GlassNavItem to="/memory/search-settings" :label="t('nav.searchSettings')" :collapsed="appStore.sidebarCollapsed" v-if="can('/memory/search-settings')">
        <template #icon><ControlOutlined /></template>
      </GlassNavItem>

      <!-- Footer -->
      <template #footer>
        <div class="nr-nav-user" v-if="authStore.currentUser">
          <div class="nr-nav-avatar">{{ authStore.currentUser.username?.charAt(0)?.toUpperCase() || 'U' }}</div>
          <div v-if="!appStore.sidebarCollapsed" class="nr-nav-user-info">
            <span class="nr-nav-user-name">{{ authStore.currentUser.username }}</span>
            <span class="nr-nav-user-role">{{ authStore.currentUser.role }}</span>
          </div>
          <GlassButton
            v-if="!appStore.sidebarCollapsed"
            variant="ghost"
            size="sm"
            :title="t('identity.title')"
            @click="showIdentity = true"
          >
            <IdcardOutlined />
          </GlassButton>
          <GlassButton v-if="!appStore.sidebarCollapsed" variant="ghost" size="sm" @click="handleLogout">
            <LogoutOutlined />
          </GlassButton>
        </div>
      </template>
    </GlassNav>

    <ClientIdentityModal
      v-model:open="showIdentity"
      :client-id="clientId"
      :platform="platform"
      :report-enabled="reportEnabled"
      @toggle-report="toggleErrorReport"
      @submit-manual="submitManualFeedback"
    />

    <!-- Main Content -->
    <div class="nr-main">
      <!-- Header -->
      <header class="nr-header">
        <div class="nr-header-left">
          <button class="nr-toggle-btn" @click="appStore.toggleSidebar">
            <MenuUnfoldOutlined v-if="appStore.sidebarCollapsed" />
            <MenuFoldOutlined v-else />
          </button>
          <a-breadcrumb class="nr-breadcrumb">
            <a-breadcrumb-item v-for="crumb in breadcrumbs" :key="crumb.path">
              <router-link :to="crumb.path">{{ crumb.label }}</router-link>
            </a-breadcrumb-item>
          </a-breadcrumb>
        </div>
        <!-- Global navigation moved to top bar -->
        <TopNavMenu />
        <div class="nr-header-right">
          <!-- Theme toggle -->
          <ThemeToggle />

          <!-- Language selector -->
          <a-dropdown>
            <button class="nr-header-action">
              <GlobalOutlined />
            </button>
            <template #overlay>
              <a-menu @click="(info: any) => changeLocale(info.key as string)">
                <a-menu-item v-for="loc in supportedLocales" :key="loc.code">
                  <span>{{ loc.flag }} {{ loc.name }}</span>
                </a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>

          <!-- Notifications -->
          <a-badge :count="unreadCount" :offset="[-4, 4]">
            <router-link to="/notifications" class="nr-header-action" @click="notifStore.fetchUnreadCount">
              <BellOutlined />
            </router-link>
          </a-badge>
        </div>
      </header>

      <!-- Page Content -->
      <main class="nr-content">
        <router-view v-slot="{ Component, route }">
          <transition name="fade-slide" mode="out-in">
            <component :is="Component" :key="route.path" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useAgentStore } from '@/stores/agents'
import { useNotificationStore } from '@/stores/notifications'
import { subscribeUnreadStream } from '@/api/modules/notifications'
import { supportedLocales } from '@/i18n'
import StarBackground from '@/components/StarBackground.vue'
import GlassNav from '@/components/GlassNav.vue'
import GlassNavItem from '@/components/GlassNavItem.vue'
import GlassNavGroup from '@/components/GlassNavGroup.vue'
import GlassButton from '@/components/GlassButton.vue'
import AgentSwitcher from '@/components/AgentSwitcher.vue'
import TopNavMenu from '@/components/TopNavMenu.vue'
import ClientIdentityModal from '@/components/ClientIdentityModal.vue'
import { message } from 'ant-design-vue'
import {
  getClientId,
  detectPlatform,
  isErrorReporterEnabled,
  setReportEnabledPref,
  reportManualFeedback,
} from '@/utils/errorReporter'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { canAccessModule } from '@/utils/permissions'
import {
  DashboardOutlined, RobotOutlined, MessageOutlined, DatabaseOutlined,
  ShareAltOutlined, ExperimentOutlined, BulbOutlined, RiseOutlined,
  HeartOutlined, ThunderboltOutlined, FileOutlined, ApiOutlined,
  ClockCircleOutlined, SafetyOutlined, CodeOutlined,
  DesktopOutlined, ControlOutlined,
  SettingOutlined, BellOutlined, GlobalOutlined,
  LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined,
  CoffeeOutlined, HistoryOutlined, LineChartOutlined, BarChartOutlined,
  UserOutlined, PlayCircleOutlined, SmileOutlined, IdcardOutlined,
  BookOutlined, AppstoreOutlined, RocketOutlined, NodeIndexOutlined,
  TeamOutlined, ProjectOutlined, BranchesOutlined, BgColorsOutlined,
  ShopOutlined,
} from '@ant-design/icons-vue'

const router = useRouter()
const route = useRoute()
const { t, te, locale } = useI18n()
const appStore = useAppStore()
const authStore = useAuthStore()
const agentStore = useAgentStore()
const notifStore = useNotificationStore()

// 设备标识（错误日志上报链路）：用户可查看/复制自己的客户端唯一代号
const showIdentity = ref(false)
const clientId = getClientId()
const platform = detectPlatform()
const reportEnabled = ref(isErrorReporterEnabled())

function toggleErrorReport() {
  const next = !reportEnabled.value
  setReportEnabledPref(next)
  reportEnabled.value = next
  message.success(next ? t('identity.reportOn') : t('identity.reportOff'))
}

function submitManualFeedback(text: string) {
  reportManualFeedback(text)
  message.success(t('identity.manualSent'))
}

// 铃铛未读数：SSE 流优先（补课 2.2），断流降级 60s 轮询
const unreadCount = computed(() => notifStore.unreadTotal)
let unreadTimer: ReturnType<typeof setInterval> | null = null
let closeUnreadStream: (() => void) | null = null

const startUnreadStream = () => {
  closeUnreadStream = subscribeUnreadStream((count) => {
    notifStore.setUnreadTotal(count)
  })
  // 3s 宽限：若 SSE 首帧/连接未建立（404/断网），降级轮询
  setTimeout(() => {
    if (notifStore.unreadTotal === 0 && !closeUnreadStream) startPolling()
  }, 3000)
}

const startPolling = () => {
  if (unreadTimer) return
  notifStore.fetchUnreadCount()
  unreadTimer = setInterval(() => notifStore.fetchUnreadCount(), 60_000)
}

onMounted(() => {
  if (authStore.user) {
    notifStore.fetchUnreadCount()
    startUnreadStream()
    // 刷新用户组 allowed_modules：管理员调整组配置后无需重新登录即生效
    authStore.fetchCurrentUser()
  }
})

onUnmounted(() => {
  if (unreadTimer) clearInterval(unreadTimer)
  if (closeUnreadStream) closeUnreadStream()
})

const changeLocale = (code: string) => {
  locale.value = code
  appStore.setLocale(code)
}

const handleLogout = async () => {
  await authStore.logout()
  router.push('/login')
}

const breadcrumbs = computed(() => {
  const matched = route.matched.filter(r => r.meta?.title || r.name)
  const crumbs = [{ path: '/dashboard', label: t('nav.home') }]
  for (const r of matched) {
    if (r.path && r.path !== '/') {
      const name = r.name as string
      // 用 te() 先做存在性检查，避免对缺失键逐个触发 intlify 告警；
      // 依次尝试 小写 / camelCase / 原名 三种键格式，都不存在则回退路由名
      const candidates = [
        `nav.${name.toLowerCase()}`,
        `nav.${name.charAt(0).toLowerCase() + name.slice(1)}`,
        `nav.${name}`,
      ]
      const hit = candidates.find(k => te(k))
      crumbs.push({ path: r.path, label: hit ? t(hit) : name })
    }
  }
  return crumbs
})

// ── 用户组功能模块可见性（allowed_modules 空 = 不限制；admin 恒全量）──
// 模块 key 即菜单路由 path（动态段 :id 占位），目录见 config/modules.ts
const can = (moduleKey: string) =>
  canAccessModule(moduleKey, authStore.user ?? {})

const canAgent = (name: string) =>
  can(`/agent/:id/${name}`)
</script>

<style scoped>
.nr-layout {
  display: flex; width: 100vw; height: 100vh; overflow: hidden;
  position: relative; z-index: 1;
}

.nr-main {
  flex: 1; display: flex; flex-direction: column;
  overflow: hidden; position: relative; z-index: 1;
}

.nr-header {
  height: var(--nr-header-h); display: flex; align-items: center;
  justify-content: space-between; padding: 0 24px;
  background: var(--nr-header-bg);
  backdrop-filter: blur(30px) saturate(180%);
  border-bottom: 1px solid var(--nr-glass-border);
  flex-shrink: 0; z-index: 5;
}

.nr-header-left { display: flex; align-items: center; gap: 16px; }
.nr-header-right { display: flex; align-items: center; gap: 8px; }

.nr-toggle-btn {
  width: 32px; height: 32px; border: none; border-radius: 8px;
  background: var(--nr-glass-bg); color: var(--nr-text-secondary);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  font-size: 16px; transition: all 0.2s;
}
.nr-toggle-btn:hover { background: var(--nr-glass-bg-active); color: var(--nr-text-primary); }

.nr-header-action {
  width: 36px; height: 36px; border: none; border-radius: 10px;
  background: transparent; color: var(--nr-text-secondary);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  font-size: 18px; transition: all 0.2s; text-decoration: none;
}
.nr-header-action:hover { background: var(--nr-glass-bg-hover); color: var(--nr-text-primary); }

.nr-content {
  flex: 1; overflow-y: auto; overflow-x: hidden;
  padding: 24px; position: relative;
}

/* Breadcrumb override */
:deep(.nr-breadcrumb) { color: var(--nr-text-tertiary); font-size: 13px; }
:deep(.nr-breadcrumb a) { color: var(--nr-text-tertiary); transition: color 0.2s; }
:deep(.nr-breadcrumb a:hover) { color: var(--nr-text-primary); }

/* 分区标题（Agent 空间 / 个人空间） */
.nr-nav-zone-title {
  font-size: 10px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--nr-text-muted);
  padding: 12px 12px 4px; margin-top: 4px;
}

/* Agent 区 / 用户区 分隔线 */
.nr-nav-divider {
  height: 1px; margin: 10px 8px;
  background: var(--nr-glass-border);
}
.nr-nav-divider.collapsed { margin: 10px 6px; }

/* Agent 空态引导卡 */
.nr-agent-empty {
  margin: 8px 4px; padding: 14px 12px;
  border: 1px dashed var(--nr-glass-border);
  border-radius: 12px;
  background: var(--nr-glass-bg);
  text-align: center;
}
.nr-agent-empty-title {
  font-size: 13px; font-weight: 600; color: var(--nr-text-primary);
  margin-bottom: 6px;
}
.nr-agent-empty-desc {
  font-size: 11px; color: var(--nr-text-muted); line-height: 1.5;
  margin-bottom: 10px;
}
.nr-agent-empty-actions {
  display: flex; gap: 8px; justify-content: center;
}

/* User section */
.nr-nav-user {
  display: flex; align-items: center; gap: 10px; padding: 8px 4px;
}
.nr-nav-avatar {
  width: 32px; height: 32px; border-radius: 8px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: var(--nr-gradient-primary); color: white;
  font-weight: 700; font-size: 14px;
}
.nr-nav-user-info { display: flex; flex-direction: column; flex: 1; min-width: 0; }
.nr-nav-user-name { font-size: 13px; font-weight: 500; color: var(--nr-text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nr-nav-user-role { font-size: 11px; color: var(--nr-text-muted); text-transform: capitalize; }

.nr-logo-img { height: 32px; width: auto; max-width: 160px; object-fit: contain; }
</style>
