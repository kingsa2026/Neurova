<template>
  <div class="views-section" data-testid="studio-views">
    <div class="views-nav" role="tablist">
      <button
        v-for="view in VIEWS"
        :key="view.key"
        type="button"
        role="tab"
        class="view-tab"
        :class="{ 'is-active': activeView === view.key }"
        :data-testid="`views-nav-${view.key}`"
        @click="activeView = view.key"
      >
        {{ t(`ontology.${view.titleKey}`) }}
      </button>
    </div>
    <div class="views-body">
      <StudioDecisionGraph v-if="activeView === 'decisionGraph'" />
      <StudioDerivationGenealogy v-else-if="activeView === 'genealogy'" />
      <StudioBitemporalTimeline v-else />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * U7 三视图分区（只读）：决策因果图 / 推导谱系 / 双时态时间线。
 * 纵向子导航沿用 Studio 分区写法（§15.3 避免横排挤压）；数据全部来自
 * 既有 REST 读面（决策台账/推导账本/access query 双时态），不新增端点。
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import StudioDecisionGraph from './StudioDecisionGraph.vue'
import StudioDerivationGenealogy from './StudioDerivationGenealogy.vue'
import StudioBitemporalTimeline from './StudioBitemporalTimeline.vue'

type ViewKey = 'decisionGraph' | 'genealogy' | 'timeline'

const VIEWS: Array<{ key: ViewKey; titleKey: string }> = [
  { key: 'decisionGraph', titleKey: 'decisionGraphTitle' },
  { key: 'genealogy', titleKey: 'genealogyTitle' },
  { key: 'timeline', titleKey: 'timelineTitle' },
]

const { t } = useI18n()
const activeView = ref<ViewKey>('decisionGraph')
</script>

<style scoped>
.views-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.views-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  border-bottom: 1px solid var(--nr-border, rgba(128, 128, 128, 0.25));
  padding-bottom: 8px;
}
.view-tab {
  border: none;
  background: transparent;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  color: var(--nr-text-secondary, inherit);
}
.view-tab.is-active {
  background: var(--nr-fill-secondary, rgba(128, 128, 128, 0.15));
  color: var(--nr-text-primary, inherit);
  font-weight: 600;
}
.views-body {
  min-width: 0;
}
</style>
