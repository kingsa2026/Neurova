import { defineStore, defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAppStore = defineStore('app', () => {
  // 主题
  const theme = ref<'light' | 'dark'>('dark')
  const isDark = computed(() => theme.value === 'dark')
  
  // 语言
  const locale = ref<string>('zh-CN')
  
  // 侧边栏折叠
  const sidebarCollapsed = ref<boolean>(false)
  
  // 当前 Agent ID
  const currentAgentId = ref<string>('')
  
  // 加载状态
  const globalLoading = ref<boolean>(false)
  const loadingText = ref<string>('')
  
  // 方法
  function setTheme(newTheme: 'light' | 'dark') {
    theme.value = newTheme
    localStorage.setItem('theme', newTheme)
  }
  
  function toggleTheme() {
    setTheme(isDark.value ? 'light' : 'dark')
  }
  
  function setLocale(newLocale: string) {
    locale.value = newLocale
    localStorage.setItem('locale', newLocale)
  }
  
  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
    localStorage.setItem('sidebarCollapsed', String(sidebarCollapsed.value))
  }
  
  function setCurrentAgentId(agentId: string) {
    currentAgentId.value = agentId
    localStorage.setItem('currentAgentId', agentId)
  }
  
  function setGlobalLoading(loading: boolean, text?: string) {
    globalLoading.value = loading
    loadingText.value = text || ''
  }
  
  // 初始化
  function init() {
    // 从 localStorage 恢复状态
    const savedTheme = localStorage.getItem('theme')
    if (savedTheme === 'light' || savedTheme === 'dark') {
      theme.value = savedTheme
    }
    
    const savedLocale = localStorage.getItem('locale')
    if (savedLocale) {
      locale.value = savedLocale
    }
    
    const savedSidebar = localStorage.getItem('sidebarCollapsed')
    if (savedSidebar) {
      sidebarCollapsed.value = savedSidebar === 'true'
    }
    
    const savedAgentId = localStorage.getItem('currentAgentId')
    if (savedAgentId) {
      currentAgentId.value = savedAgentId
    }
  }
  
  return {
    theme,
    isDark,
    locale,
    sidebarCollapsed,
    currentAgentId,
    globalLoading,
    loadingText,
    setTheme,
    toggleTheme,
    setLocale,
    toggleSidebar,
    setCurrentAgentId,
    setGlobalLoading,
    init
  }
})
