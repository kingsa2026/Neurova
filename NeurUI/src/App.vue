<template>
  <a-config-provider :get-popup-container="getPopupContainer" :theme="antdTheme">
    <div :data-theme="appStore.theme" class="nr-app">
      <div class="star-bg" v-if="appStore.isDark" />
      <router-view />
    </div>
  </a-config-provider>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { theme as antdThemeAlgo } from 'ant-design-vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useAgentStore } from '@/stores/agents'

const appStore = useAppStore()
const authStore = useAuthStore()
const agentStore = useAgentStore()

const getPopupContainer = (triggerNode?: HTMLElement) =>
  (triggerNode?.parentNode || document.body) as HTMLElement

/** Ant Design 主题跟随应用主题：深色用 darkAlgorithm，浅色用 defaultAlgorithm。 */
const antdTheme = computed(() =>
  appStore.isDark
    ? {
        algorithm: antdThemeAlgo.darkAlgorithm,
        token: {
          colorPrimary: '#6366f1',
          colorInfo: '#6366f1',
          colorBgBase: '#0a0e1a',
          colorTextBase: '#ffffff',
          borderRadius: 10,
        },
      }
    : {
        algorithm: antdThemeAlgo.defaultAlgorithm,
        token: {
          colorPrimary: '#4d6bfe',
          colorInfo: '#4d6bfe',
          colorBgBase: '#ffffff',
          colorTextBase: '#1f2329',
          borderRadius: 10,
        },
      },
)

onMounted(() => {
  appStore.init()
  document.documentElement.setAttribute('data-theme', appStore.theme)
  agentStore.loadAgents()
  if (authStore.isAuthenticated) {
    authStore.fetchCurrentUser()
  }
})
</script>

<style>
.nr-app {
  position: relative;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  z-index: 1;
}
</style>
