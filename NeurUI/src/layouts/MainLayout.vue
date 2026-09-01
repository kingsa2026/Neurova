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

      <!-- Quick access -->
      <GlassNavItem to="/agents" :label="t('nav.agents')" :collapsed="appStore.sidebarCollapsed" active-path="/agents">
        <template #icon><RobotOutlined /></template>
      </GlassNavItem>
      <!-- 全局对话: 仅无 Agent 选中时显示 -->
      <GlassNavItem v-if="!agentStore.currentAgent" to="/chat" :label="t('nav.chat')" :collapsed="appStore.sidebarCollapsed">
        <template #icon><MessageOutlined /></template>
      </GlassNavItem>
      <!-- 渠道: 仅无 Agent 选中时显示全局版 -->
      <GlassNavItem v-if="!agentStore.currentAgent" to="/channels" :label="t('nav.channels')" :collapsed="appStore.sidebarCollapsed">
        <template #icon><GlobalOutlined /></template>
      </GlassNavItem>

      <!-- ==================== Agent-scoped (when agent selected) ==================== -->
      <template v-if="agentStore.currentAgent">
        <!-- Agent: Core -->
        <div v-if="!appStore.sidebarCollapsed" class="nr-nav-section">{{ t('nav.agentCore') }}</div>
        <GlassNavItem to="/chat" :label="t('nav.chat')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><MessageOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/memory`" :label="t('nav.memory')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><DatabaseOutlined /></template>
        </GlassNavItem>
        <GlassNavItem to="/memory/settings" :label="t('nav.memorySettings')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><ControlOutlined /></template>
        </GlassNavItem>
        <GlassNavItem to="/memory/search-settings" :label="t('nav.searchSettings')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><ExperimentOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/experience-knowledge`" :label="t('nav.experience')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><BulbOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/knowledge-graph`" :label="t('nav.knowledgeGraph')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><ShareAltOutlined /></template>
        </GlassNavItem>

        <!-- Agent: Cognition -->
        <div v-if="!appStore.sidebarCollapsed" class="nr-nav-section">{{ t('nav.agentCognition') }}</div>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/metacognition`" :label="t('nav.metacognition')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><ExperimentOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/reflection`" :label="t('nav.reflection')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><BulbOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/growth`" :label="t('nav.growth')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><RiseOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/emotion`" :label="t('nav.emotion')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><HeartOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/personality`" :label="t('nav.personality')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><SmileOutlined /></template>
        </GlassNavItem>

        <!-- Agent: Capabilities -->
        <div v-if="!appStore.sidebarCollapsed" class="nr-nav-section">{{ t('nav.agentCapabilities') }}</div>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/skills`" :label="t('nav.skills')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><ThunderboltOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/rules`" :label="t('nav.rules')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><SafetyOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/files`" :label="t('nav.files')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><FileOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/media`" :label="t('nav.media')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><PlayCircleOutlined /></template>
        </GlassNavItem>

        <!-- Agent: Runtime -->
        <div v-if="!appStore.sidebarCollapsed" class="nr-nav-section">{{ t('nav.agentRuntime') }}</div>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/scheduler`" :label="t('nav.scheduler')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><ClockCircleOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/channel`" :label="t('nav.channels')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><ApiOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/channel-sharing`" :label="t('nav.channelSharing')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><LinkOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/sleep/status`" :label="t('nav.sleep')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><CoffeeOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/sleep/settings`" :label="t('nav.sleepsettings')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><CoffeeOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/computer`" :label="t('nav.computer')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><DesktopOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/trace`" :label="t('nav.trace')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><CodeOutlined /></template>
        </GlassNavItem>
        <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/trajectory`" :label="t('nav.trajectory')" :collapsed="appStore.sidebarCollapsed">
          <template #icon><FileTextOutlined /></template>
        </GlassNavItem>
      </template>

      <!-- Footer -->
      <template #footer>
        <div class="nr-nav-user" v-if="authStore.currentUser">
          <div class="nr-nav-avatar">{{ authStore.currentUser.username?.charAt(0)?.toUpperCase() || 'U' }}</div>
          <div v-if="!appStore.sidebarCollapsed" class="nr-nav-user-info">
            <span class="nr-nav-user-name">{{ authStore.currentUser.username }}</span>
            <span class="nr-nav-user-role">{{ authStore.currentUser.role }}</span>
          </div>
          <GlassButton v-if="!appStore.sidebarCollapsed" variant="ghost" size="sm" @click="handleLogout">
            <LogoutOutlined />
          </GlassButton>
        </div>
      </template>
    </GlassNav>

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
import GlassButton from '@/components/GlassButton.vue'
import AgentSwitcher from '@/components/AgentSwitcher.vue'
import TopNavMenu from '@/components/TopNavMenu.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import {
  DashboardOutlined, RobotOutlined, MessageOutlined, DatabaseOutlined,
  ShareAltOutlined, ExperimentOutlined, BulbOutlined, RiseOutlined,
  HeartOutlined, ThunderboltOutlined, FileOutlined, ApiOutlined,
  ClockCircleOutlined, SafetyOutlined, CodeOutlined,
  DesktopOutlined, PlusOutlined, ControlOutlined, LinkOutlined,
  SettingOutlined, BellOutlined, GlobalOutlined,
  LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined,
  CoffeeOutlined, FileTextOutlined, HistoryOutlined,
  UserOutlined, PlayCircleOutlined, SmileOutlined,
} from '@ant-design/icons-vue'

const router = useRouter()
const route = useRoute()
const { t, te, locale } = useI18n()
const appStore = useAppStore()
const authStore = useAuthStore()
const agentStore = useAgentStore()
const notifStore = useNotificationStore()

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

/* Nav section label */
.nr-nav-section {
  font-size: 10px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--nr-text-muted);
  padding: 12px 12px 4px; margin-top: 4px;
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
