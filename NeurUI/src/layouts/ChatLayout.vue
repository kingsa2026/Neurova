<template>
  <div class="nr-chat-layout" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <!-- iOS 氛围壁纸统一由 App.vue 的 .star-bg 提供（深/浅两套主题共用） -->

    <!-- Chat Sidebar -->
    <GlassNav :collapsed="sidebarCollapsed" @brand-click="router.push('/dashboard')">
      <template #brand>
        <span class="nr-logo">N</span>
        <span v-if="!sidebarCollapsed" class="nr-brand-text">Neurova</span>
      </template>

      <!-- Agent Switcher -->
      <AgentSwitcher
        :collapsed="sidebarCollapsed"
        @select="onAgentSelect"
      />

      <!-- Chat (highlighted) -->
      <GlassNavItem
        :to="`/agent/${agentStore.currentAgentId}/chat`"
        :label="t('nav.chat')"
        :collapsed="sidebarCollapsed"
        class="nr-chat-highlight"
      >
        <template #icon><MessageOutlined /></template>
      </GlassNavItem>

      <!-- Control -->
      <div v-if="!sidebarCollapsed" class="nr-nav-section">{{ t('nav.control') }}</div>
      <GlassNavItem to="/notifications" :label="t('nav.inbox')" :collapsed="sidebarCollapsed">
        <template #icon><BellOutlined /></template>
      </GlassNavItem>
      <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/channel`" :label="t('nav.channels')" :collapsed="sidebarCollapsed">
        <template #icon><GlobalOutlined /></template>
      </GlassNavItem>
      <GlassNavItem to="/collaboration/session-sync" :label="t('nav.conversations')" :collapsed="sidebarCollapsed">
        <template #icon><MessageOutlined /></template>
      </GlassNavItem>
      <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/scheduler`" :label="t('nav.scheduler')" :collapsed="sidebarCollapsed">
        <template #icon><ClockCircleOutlined /></template>
      </GlassNavItem>
      <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/sleep/status`" :label="t('nav.heartbeat')" :collapsed="sidebarCollapsed">
        <template #icon><HeartOutlined /></template>
      </GlassNavItem>

      <!-- Workspace -->
      <div v-if="!sidebarCollapsed" class="nr-nav-section">{{ t('nav.workspace') }}</div>
      <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/files`" :label="t('nav.files')" :collapsed="sidebarCollapsed">
        <template #icon><FolderOutlined /></template>
      </GlassNavItem>
      <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/skills`" :label="t('nav.skills')" :collapsed="sidebarCollapsed">
        <template #icon><ThunderboltOutlined /></template>
      </GlassNavItem>
      <GlassNavItem to="/tool-layers" :label="t('nav.tools')" :collapsed="sidebarCollapsed">
        <template #icon><ToolOutlined /></template>
      </GlassNavItem>
      <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/trace`" :label="t('nav.mcp')" :collapsed="sidebarCollapsed">
        <template #icon><ApiOutlined /></template>
      </GlassNavItem>
      <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/rules`" :label="t('nav.acp')" :collapsed="sidebarCollapsed">
        <template #icon><AppstoreOutlined /></template>
      </GlassNavItem>
      <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/personality`" :label="t('nav.runtimeConfig')" :collapsed="sidebarCollapsed">
        <template #icon><SettingOutlined /></template>
      </GlassNavItem>
      <GlassNavItem :to="`/agent/${agentStore.currentAgentId}/trajectory`" :label="t('nav.agentStats')" :collapsed="sidebarCollapsed">
        <template #icon><BarChartOutlined /></template>
      </GlassNavItem>

      <!-- Footer: collapse toggle + back to dashboard -->
      <template #footer>
        <div class="nr-chat-sidebar-footer">
          <button class="nr-toggle-btn" @click="sidebarCollapsed = !sidebarCollapsed">
            <MenuUnfoldOutlined v-if="sidebarCollapsed" />
            <MenuFoldOutlined v-else />
          </button>
          <router-link v-if="!sidebarCollapsed" to="/dashboard" class="nr-back-link">
            <DashboardOutlined />
            <span>{{ t('nav.dashboard') }}</span>
          </router-link>
        </div>
      </template>
    </GlassNav>

    <!-- Main Content -->
    <div class="nr-chat-main">
      <!-- 悬浮皮肤/主题切换（右上角） -->
      <div class="nr-chat-theme-tools">
        <SkinSwitcher />
        <ThemeToggle class="nr-chat-theme-toggle" />
      </div>
      <main class="nr-chat-content">
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
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import { useAgentStore } from '@/stores/agents'
import GlassNav from '@/components/GlassNav.vue'
import GlassNavItem from '@/components/GlassNavItem.vue'
import AgentSwitcher from '@/components/AgentSwitcher.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import SkinSwitcher from '@/components/SkinSwitcher.vue'
import type { Agent } from '@/types/agent'
import {
  MessageOutlined, BellOutlined, GlobalOutlined, ClockCircleOutlined,
  HeartOutlined, FolderOutlined, ThunderboltOutlined, ToolOutlined,
  ApiOutlined, AppstoreOutlined, SettingOutlined, BarChartOutlined,
  DashboardOutlined, MenuFoldOutlined, MenuUnfoldOutlined,
} from '@ant-design/icons-vue'

const router = useRouter()
const { t } = useI18n()
const appStore = useAppStore()
const agentStore = useAgentStore()

const sidebarCollapsed = ref(false)

function onAgentSelect(_agent: Agent) {
  // AgentStore already updated by AgentSwitcher internally
  // Route navigation handled by AgentSwitcher (autoNavigate=true)
}
</script>

<style scoped>
.nr-chat-layout {
  display: flex;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  position: relative;
  z-index: 1;
}

.nr-chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  z-index: 1;
}

.nr-chat-content {
  flex: 1;
  overflow: hidden;
  position: relative;
}

/* Highlight the chat nav item */
:deep(.nr-chat-highlight a) {
  background: var(--nr-gradient-primary) !important;
  color: white !important;
}
:deep(.nr-chat-highlight a:hover) {
  opacity: 0.9;
}
:deep(.nr-chat-highlight .nr-nav-label) {
  color: white !important;
  font-weight: 600 !important;
}

/* Sidebar footer */
.nr-chat-sidebar-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
}

.nr-toggle-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: var(--nr-glass-bg);
  color: var(--nr-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  transition: all 0.2s;
}
.nr-toggle-btn:hover {
  background: var(--nr-glass-bg-active);
  color: var(--nr-text-primary);
}

.nr-back-link {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--nr-text-muted);
  text-decoration: none;
  transition: color 0.2s;
  padding: 6px 8px;
  border-radius: 6px;
}
.nr-back-link:hover {
  color: var(--nr-text-primary);
  background: var(--nr-glass-bg);
}

/* 悬浮皮肤/主题切换工具组 */
.nr-chat-theme-tools {
  position: absolute;
  top: 14px;
  right: 20px;
  z-index: 60;
  display: flex;
  align-items: center;
  gap: 8px;
}
.nr-chat-theme-toggle {
  position: static;
}

/* Nav section label */
.nr-nav-section {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--nr-text-muted);
  padding: 12px 12px 4px;
  margin-top: 4px;
}

.nr-logo {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: var(--nr-gradient-primary);
  color: white;
  font-family: var(--nr-font-display);
  font-weight: 800;
  font-size: 16px;
  box-shadow: inset 0 0.5px 0 rgba(255, 255, 255, 0.25), 0 2px 8px rgba(10, 132, 255, 0.3);
}
.nr-brand-text {
  font-family: var(--nr-font-display);
  font-weight: 700;
  font-size: 17px;
  color: var(--nr-text-primary);
  letter-spacing: -0.02em;
  white-space: nowrap;
}
</style>
