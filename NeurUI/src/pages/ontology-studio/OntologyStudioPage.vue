<template>
  <div class="ontology-studio-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('ontology.studioTitle') }}</h2>
        <p class="page-subtitle">
          {{ currentAgent?.name || '' }}
          <a-tag v-if="schema?.tenant_scoped" color="blue" class="tenant-tag" data-testid="studio-tenant-scoped">
            {{ t('ontology.tenantScoped') }}
          </a-tag>
          <a-tag v-if="schema" color="default" data-testid="studio-schema-version">
            {{ t('ontology.schemaVersion') }}: v{{ schema.schema_version }}
          </a-tag>
        </p>
      </div>
      <GlassButton variant="secondary" :loading="loading" data-testid="studio-refresh" @click="loadAll">
        {{ t('common.refresh') }}
      </GlassButton>
    </div>

    <a-alert
      v-if="loadError"
      type="error"
      show-icon
      class="load-error"
      data-testid="studio-load-error"
      :message="t('ontology.termsLoadFailed')"
    />

    <div class="studio-layout">
      <!-- 左：画布占位（简化静态 upper-lite 树；2D/3D 交互画布在图谱工作台，此处给真链接） -->
      <GlassCard class="canvas-card">
        <div class="canvas-head">
          <span class="canvas-title">{{ t('ontology.canvasTitle') }}</span>
        </div>
        <div class="upper-tree" data-testid="studio-upper-tree">
          <div class="tree-root">{{ UPPER_LITE_TREE.root }}</div>
          <div class="tree-children">
            <div v-for="branch in UPPER_LITE_TREE.children" :key="branch.label" class="tree-branch">
              <div class="tree-node tree-node--mid">{{ branch.label }}</div>
              <div class="tree-children">
                <div v-for="leaf in branch.children" :key="leaf" class="tree-node tree-node--leaf">
                  {{ leaf }}
                </div>
              </div>
            </div>
          </div>
        </div>
        <p class="canvas-note" data-testid="canvas-note">{{ t('ontology.canvasNote') }}</p>
        <router-link
          class="canvas-link"
          data-testid="studio-graph-workbench-link"
          :to="`/agent/${agentId}/graph-workbench`"
        >{{ t('nav.graphWorkbench') }}</router-link>
      </GlassCard>

      <!-- 右：纵向分区导航（§15.3：避免 7 个横排 tab 挤压画布） -->
      <GlassCard class="sections-card">
        <div class="sections-nav" role="tablist">
          <button
            v-for="sec in SECTIONS"
            :key="sec.key"
            type="button"
            role="tab"
            class="section-tab"
            :class="{ 'is-active': activeSection === sec.key }"
            :data-testid="`studio-nav-${sec.key}`"
            @click="activeSection = sec.key"
          >
            {{ t(`ontology.${sec.labelKey}`) }}
          </button>
        </div>

        <div class="section-body">
          <StudioOverviewSection
            v-if="activeSection === 'overview'"
            :schema="schema"
            :pending-candidates="pendingCount"
            :loading="loading"
          />
          <StudioCqSection v-else-if="activeSection === 'cq'" />
          <StudioTermsSection v-else-if="activeSection === 'terms'" :is-admin="isAdmin" />
          <StudioRelationsSection v-else-if="activeSection === 'relations'" :schema="schema" :is-admin="isAdmin" @candidates-changed="onCandidatesChanged" />
          <StudioShapesSection v-else-if="activeSection === 'shapes'" :is-admin="isAdmin" />
          <StudioReasoningSection v-else-if="activeSection === 'reasoning'" :schema="schema" />
          <StudioReleaseSection v-else-if="activeSection === 'release'" :is-admin="isAdmin" />
        </div>
      </GlassCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAgentPage } from '@/composables/useAgentPage'
import { useAuthStore } from '@/stores/auth'
import { getOntologySchema, listRelationCandidates } from '@/api/modules/ontology'
import type { OntologySchemaData } from '@/types/ontology'
import { UPPER_LITE_TREE } from '@/config/ontologyStatic'
import StudioOverviewSection from './StudioOverviewSection.vue'
import StudioCqSection from './StudioCqSection.vue'
import StudioTermsSection from './StudioTermsSection.vue'
import StudioRelationsSection from './StudioRelationsSection.vue'
import StudioShapesSection from './StudioShapesSection.vue'
import StudioReasoningSection from './StudioReasoningSection.vue'
import StudioReleaseSection from './StudioReleaseSection.vue'

type SectionKey = 'overview' | 'cq' | 'terms' | 'relations' | 'shapes' | 'reasoning' | 'release'

const SECTIONS: Array<{ key: SectionKey; labelKey: string }> = [
  { key: 'overview', labelKey: 'navOverview' },
  { key: 'cq', labelKey: 'navCq' },
  { key: 'terms', labelKey: 'navTerms' },
  { key: 'relations', labelKey: 'navRelations' },
  { key: 'shapes', labelKey: 'navShapes' },
  { key: 'reasoning', labelKey: 'navReasoning' },
  { key: 'release', labelKey: 'navRelease' },
]

const { t } = useI18n()
const { agentId, currentAgent } = useAgentPage()
const authStore = useAuthStore()

const isAdmin = computed(() => {
  const user = authStore.user as { role?: string } | null | undefined
  return user?.role === 'admin'
})

const loading = ref(false)
const loadError = ref(false)
const schema = ref<OntologySchemaData | null>(null)
const pendingCount = ref(0)
const activeSection = ref<SectionKey>('overview')

async function loadAll() {
  loading.value = true
  loadError.value = false
  try {
    const res = await getOntologySchema()
    schema.value = (res.data ?? null) as OntologySchemaData | null
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
  await reloadPending()
}

async function reloadPending() {
  try {
    const res = await listRelationCandidates('pending', 100)
    pendingCount.value = res.data?.items?.length ?? 0
  } catch {
    // 候选读取失败不掩盖 schema 面板；待审计数保持现值并静默——审计面另有 403/401 显式报错
    pendingCount.value = 0
  }
}

function onCandidatesChanged() {
  void reloadPending()
}

onMounted(loadAll)
</script>

<style scoped>
.ontology-studio-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
}
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.page-title {
  margin: 0;
  font-size: 20px;
  color: var(--nr-text-primary, inherit);
}
.page-subtitle {
  margin: 4px 0 0;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--nr-text-secondary, inherit);
}
.load-error {
  margin-bottom: 4px;
}
.studio-layout {
  display: grid;
  grid-template-columns: minmax(280px, 380px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
@media (max-width: 960px) {
  .studio-layout {
    grid-template-columns: 1fr;
  }
}
.canvas-card,
.sections-card {
  min-width: 0;
}
.canvas-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
}
.canvas-title {
  font-weight: 600;
}
.upper-tree {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.tree-root {
  padding: 6px 18px;
  border-radius: 10px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.35));
  font-weight: 600;
}
.tree-children {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
}
.tree-branch {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.tree-node {
  padding: 4px 12px;
  border-radius: 8px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.35));
  font-size: 13px;
}
.tree-node--leaf {
  opacity: 0.85;
}
.canvas-note {
  margin-top: 12px;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.canvas-link {
  display: inline-block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--nr-accent, inherit);
}
.sections-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-bottom: 1px solid var(--nr-border, rgba(128, 128, 128, 0.25));
  padding-bottom: 8px;
  margin-bottom: 12px;
}
@media (min-width: 961px) {
  .sections-nav {
    flex-direction: row;
    flex-wrap: wrap;
  }
}
.section-tab {
  border: none;
  background: transparent;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  color: var(--nr-text-secondary, inherit);
  text-align: left;
}
.section-tab.is-active {
  background: var(--nr-fill-secondary, rgba(128, 128, 128, 0.15));
  color: var(--nr-text-primary, inherit);
  font-weight: 600;
}
</style>
