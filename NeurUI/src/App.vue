<template>
  <a-config-provider :get-popup-container="getPopupContainer">
    <div :data-theme="appStore.theme" class="nr-app">
      <div class="star-bg" v-if="appStore.isDark" />
      <router-view />
    </div>
  </a-config-provider>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useAgentStore } from '@/stores/agents'

const appStore = useAppStore()
const authStore = useAuthStore()
const agentStore = useAgentStore()

const getPopupContainer = (triggerNode?: HTMLElement) =>
  (triggerNode?.parentNode || document.body) as HTMLElement

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
