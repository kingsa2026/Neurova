<template>
  <div class="nr-auth-page">
    <StarBackground v-if="appStore.isDark" />
    <div class="nr-legal-container">
      <GlassPanel variant="elevated" :radius="24" padding="36px 40px">
        <div class="nr-auth-header">
          <BrandLogo size="lg" />
          <h2 class="nr-auth-title">{{ title }}</h2>
          <p class="nr-auth-subtitle">{{ updated }}</p>
        </div>

        <div class="nr-legal-scroll">
          <section v-for="sec in sections" :key="sec.title" class="nr-legal-section">
            <h3 class="nr-legal-title">{{ t(sec.title) }}</h3>
            <p class="nr-legal-body">{{ t(sec.body) }}</p>
          </section>
        </div>

        <div class="nr-auth-footer">
          <router-link to="/login" class="nr-auth-link">
            {{ t('auth.login') }}
          </router-link>
        </div>
      </GlassPanel>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import StarBackground from '@/components/StarBackground.vue'
import BrandLogo from '@/components/BrandLogo.vue'
import GlassPanel from '@/components/GlassPanel.vue'

const props = defineProps<{ type: 'terms' | 'privacy' }>()

const { t } = useI18n()
const appStore = useAppStore()

const title = computed(() => (props.type === 'terms' ? t('legal.termsTitle') : t('legal.privacyTitle')))
const updated = computed(() => (props.type === 'terms' ? t('legal.termsUpdated') : t('legal.privacyUpdated')))

// 固定键名（字面量），内容键经脚本注入 11 语言包
const termsSections = [
  { title: 'legal.termsS1', body: 'legal.termsS1Body' },
  { title: 'legal.termsS2', body: 'legal.termsS2Body' },
  { title: 'legal.termsS3', body: 'legal.termsS3Body' },
  { title: 'legal.termsS4', body: 'legal.termsS4Body' },
  { title: 'legal.termsS5', body: 'legal.termsS5Body' },
  { title: 'legal.termsS6', body: 'legal.termsS6Body' },
  { title: 'legal.termsS7', body: 'legal.termsS7Body' },
  { title: 'legal.termsS8', body: 'legal.termsS8Body' },
  { title: 'legal.termsS9', body: 'legal.termsS9Body' },
  { title: 'legal.termsS10', body: 'legal.termsS10Body' },
]

const privacySections = [
  { title: 'legal.privacyS1', body: 'legal.privacyS1Body' },
  { title: 'legal.privacyS2', body: 'legal.privacyS2Body' },
  { title: 'legal.privacyS3', body: 'legal.privacyS3Body' },
  { title: 'legal.privacyS4', body: 'legal.privacyS4Body' },
  { title: 'legal.privacyS5', body: 'legal.privacyS5Body' },
  { title: 'legal.privacyS6', body: 'legal.privacyS6Body' },
  { title: 'legal.privacyS7', body: 'legal.privacyS7Body' },
  { title: 'legal.privacyS8', body: 'legal.privacyS8Body' },
  { title: 'legal.privacyS9', body: 'legal.privacyS9Body' },
]

const sections = computed(() => (props.type === 'terms' ? termsSections : privacySections))

onMounted(() => {
  document.title = `${title.value} · Neurova`
})
</script>

<style scoped>
.nr-auth-page {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--nr-bg-deep);
  overflow: hidden;
  overflow-y: auto;
}

.nr-legal-container {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 720px;
  padding: 20px;
  margin: 40px auto;
  animation: auth-enter 0.6s cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes auth-enter {
  from {
    opacity: 0;
    transform: translateY(24px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.nr-auth-header {
  text-align: center;
  margin-bottom: 24px;
}

.nr-auth-title {
  font-family: var(--nr-font-display);
  font-size: 24px;
  font-weight: 700;
  color: var(--nr-text-primary);
  letter-spacing: -0.03em;
  margin: 0 0 6px;
}

.nr-auth-subtitle {
  font-size: 14px;
  color: var(--nr-text-tertiary);
  margin: 0;
}

.nr-legal-scroll {
  max-height: 52vh;
  overflow-y: auto;
  padding: 8px 12px 8px 0;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.nr-legal-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--nr-text-primary);
  margin: 0 0 8px;
}

.nr-legal-body {
  font-size: 13px;
  line-height: 1.9;
  color: var(--nr-text-secondary);
  margin: 0;
  white-space: pre-wrap;
}

.nr-auth-footer {
  text-align: center;
  font-size: 13px;
  color: var(--nr-text-tertiary);
  padding-top: 16px;
  margin-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.nr-auth-link {
  color: var(--nr-primary-light);
  text-decoration: none;
  font-weight: 500;
  margin-left: 4px;
  transition: color 0.2s;
}

.nr-auth-link:hover {
  color: white;
  text-decoration: underline;
}
</style>
