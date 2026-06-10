<template>
  <GlassPanel :variant="variant" :radius="radius" :padding="padding" :glow="glow">
    <div class="nr-glass-card">
      <div v-if="title || $slots.header" class="nr-glass-card-header">
        <slot name="header">
          <div v-if="icon" class="nr-glass-card-icon">
            <component :is="icon" v-if="typeof icon === 'object'" />
            <span v-else>{{ icon }}</span>
          </div>
          <h3 v-if="title" class="nr-glass-card-title">{{ title }}</h3>
          <p v-if="subtitle" class="nr-glass-card-subtitle">{{ subtitle }}</p>
        </slot>
      </div>
      <div class="nr-glass-card-body">
        <slot />
      </div>
      <div v-if="$slots.footer" class="nr-glass-card-footer">
        <slot name="footer" />
      </div>
    </div>
  </GlassPanel>
</template>

<script setup lang="ts">
import GlassPanel from './GlassPanel.vue'

withDefaults(defineProps<{
  title?: string
  subtitle?: string
  icon?: string | object
  variant?: 'default' | 'elevated' | 'subtle' | 'prominent'
  radius?: number
  padding?: string
  glow?: boolean
}>(), {
  variant: 'default',
  radius: 20,
  padding: '0',
  glow: false,
})
</script>

<style scoped>
.nr-glass-card { display: flex; flex-direction: column; gap: 16px; }
.nr-glass-card-header { display: flex; flex-direction: column; gap: 6px; }
.nr-glass-card-icon { font-size: 24px; color: var(--nr-primary-light); margin-bottom: 4px; }
.nr-glass-card-title {
  font-family: var(--nr-font-display); font-size: 18px; font-weight: 600;
  color: var(--nr-text-primary); letter-spacing: -0.02em; line-height: 1.3;
}
.nr-glass-card-subtitle { font-size: 13px; color: var(--nr-text-tertiary); }
.nr-glass-card-body { flex: 1; }
.nr-glass-card-footer { padding-top: 12px; border-top: 1px solid var(--nr-glass-border); }
</style>
