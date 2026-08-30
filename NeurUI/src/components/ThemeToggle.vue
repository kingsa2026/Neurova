<template>
  <button
    class="nr-theme-toggle"
    :title="appStore.isDark ? t('theme.light') : t('theme.dark')"
    :aria-label="appStore.isDark ? t('theme.light') : t('theme.dark')"
    @click="appStore.toggleTheme()"
  >
    <BulbOutlined v-if="appStore.isDark" />
    <StarOutlined v-else />
  </button>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import { BulbOutlined, StarOutlined } from '@ant-design/icons-vue'

const { t } = useI18n()
const appStore = useAppStore()
</script>

<style scoped>
.nr-theme-toggle {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--nr-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  transition: all 0.2s;
}
.nr-theme-toggle:hover {
  background: var(--nr-glass-bg-hover);
  color: var(--nr-text-primary);
}
</style>
