<template>
  <div :data-theme="appStore.theme" class="nr-app">
    <div class="star-bg" v-if="appStore.isDark" />
    <router-view v-slot="{ Component, route }">
      <transition name="fade-slide" mode="out-in">
        <component :is="Component" :key="route.path" />
      </transition>
    </router-view>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useAgentStore } from '@/stores/agents'

const appStore = useAppStore()
const authStore = useAuthStore()
const agentStore = useAgentStore()

onMounted(() => {
  appStore.init()
  document.documentElement.setAttribute('data-theme', appStore.theme)
  if (authStore.isAuthenticated) {
    authStore.fetchCurrentUser()
    agentStore.loadAgents()
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
