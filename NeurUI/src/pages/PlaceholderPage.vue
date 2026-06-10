<template>
  <div class="placeholder-page">
    <GlassCard>
      <div class="placeholder-content">
        <div class="placeholder-icon">🚧</div>
        <h2 class="placeholder-title">{{ t('common.loading').replace('...', '') }} Soon</h2>
        <p class="placeholder-desc">
          <strong>{{ featureName }}</strong> is currently under development and will be available in a future release.
        </p>
      </div>
    </GlassCard>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import GlassCard from '@/components/GlassCard.vue'

const { t } = useI18n()
const route = useRoute()

const featureName = computed(() => {
  const name = route.name as string || route.path
  return name.replace(/([A-Z])/g, ' $1').trim()
})
</script>

<style scoped>
.placeholder-page { display: flex; justify-content: center; align-items: center; min-height: 400px; }
.placeholder-content { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 16px; padding: 40px; }
.placeholder-icon { font-size: 64px; }
.placeholder-title { font-family: var(--nr-font-display); font-size: 24px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.placeholder-desc { font-size: 15px; color: var(--nr-text-secondary); margin: 0; max-width: 400px; }
.placeholder-desc strong { color: var(--nr-text-primary); }
</style>
