<template>
  <div class="nr-mobile-pairing-page">
    <div class="nr-mp-head">
      <div>
        <h2>{{ t('nav.mobilePairing') }}</h2>
        <p class="nr-mp-desc">{{ t('channel.mobilePairingDesc') }}</p>
      </div>
    </div>
    <!-- 账号级能力（2026-11-16 从 Agent 渠道页迁出）：面板自身按登录账号
         分账（后端 _get_current_user_id），此处只做入口承载，不重复实现。 -->
    <MobilePairingPanel />
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import MobilePairingPanel from '@/components/MobilePairingPanel.vue'

const { t } = useI18n()
</script>

<style scoped>
.nr-mobile-pairing-page {
  padding: 24px;
  max-width: 860px;
  margin: 0 auto;
}

.nr-mp-head {
  margin-bottom: 20px;
}

.nr-mp-head h2 {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 650;
}

.nr-mp-desc {
  margin: 0;
  font-size: 13px;
  opacity: 0.64;
  line-height: 1.6;
}
</style>
