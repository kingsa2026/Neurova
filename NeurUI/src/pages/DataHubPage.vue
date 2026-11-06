<template>
  <div class="data-hub-page" data-testid="data-hub-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('dataHub.title') }}</h2>
        <p class="page-subtitle">{{ t('dataHub.subtitle') }}</p>
      </div>
    </div>

    <a-alert
      type="info"
      show-icon
      class="hint-alert"
      data-testid="hub-hint"
      :message="t('dataHub.hint')"
    />

    <template v-if="visibleGroups.length">
      <section v-for="group in visibleGroups" :key="group.key" class="hub-group">
        <h3 class="group-title" :data-testid="`hub-group-${group.key}`">{{ t(group.titleKey) }}</h3>
        <div class="card-grid">
          <GlassCard
            v-for="entry in group.items"
            :key="entry.id"
            variant="subtle"
            class="hub-card"
            :data-testid="`hub-card-${entry.id}`"
          >
            <div class="card-head">
              <component :is="entry.icon" class="card-icon" />
              <span class="card-title">{{ t(entry.titleKey) }}</span>
            </div>
            <p class="card-desc">{{ t(entry.descKey) }}</p>
            <div class="card-actions">
              <a :href="entry.to" class="card-link" @click.prevent="go(entry.to)">
                {{ t('dataHub.enter') }}
              </a>
            </div>
          </GlassCard>
        </div>
      </section>
    </template>
    <a-empty v-else :description="t('dataHub.emptyHint')" data-testid="hub-empty" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  BookOutlined,
  CloudServerOutlined,
  DeploymentUnitOutlined,
  ExperimentOutlined,
  ExportOutlined,
  NodeIndexOutlined,
  ShareAltOutlined,
} from '@ant-design/icons-vue'
import GlassCard from '@/components/GlassCard.vue'
import { useAgentStore } from '@/stores/agents'
import { useAuthStore } from '@/stores/auth'
import { canAccessModule } from '@/utils/permissions'

const { t } = useI18n()
const router = useRouter()
const agentStore = useAgentStore()
const authStore = useAuthStore()

interface HubEntry {
  id: string
  /** 权限目录 key（与 config/modules.ts 逐字一致，不在这里另造一套判定口径） */
  moduleKey: string
  titleKey: string
  /** 描述优先复用目标页自己的 subtitle；该页没有副标题时才新建 dataHub.desc* 键 */
  descKey: string
  icon: unknown
  to: string
}

const agentId = computed(() => agentStore.currentAgentId || 'default')

const GROUPS: Array<{ key: string; titleKey: string; items: HubEntry[] }> = [
  {
    key: 'knowledge',
    titleKey: 'dataHub.groupKnowledge',
    items: [
      {
        id: 'knowledge',
        moduleKey: '/knowledge',
        titleKey: 'nav.knowledge',
        descKey: 'knowledge.subtitle',
        icon: BookOutlined,
        to: '/knowledge',
      },
      {
        id: 'enterprise-sources',
        moduleKey: '/knowledge/enterprise-sources',
        titleKey: 'nav.enterpriseSources',
        descKey: 'ontology.entSubtitle',
        icon: CloudServerOutlined,
        to: '/knowledge/enterprise-sources',
      },
    ],
  },
  {
    key: 'semantic',
    titleKey: 'dataHub.groupSemantic',
    items: [
      {
        id: 'ontology-studio',
        moduleKey: '/agent/:id/ontology-studio',
        titleKey: 'nav.knowledgeGraph',
        descKey: 'ontology.studioSubtitle',
        icon: ShareAltOutlined,
        to: `/agent/${agentId.value}/ontology-studio`,
      },
      {
        // 图谱工作台（2D/3D 画布＋地理图层）：一级入口。
        // 此前该页只剩书签可达（UI-0 把唯一菜单项的路径与标签一起改指本体工作台，
        // 权限目录也从未登记过它）——现已补回目录与菜单，旧 URL 继续保留。
        id: 'graph-workbench',
        moduleKey: '/agent/:id/graph-workbench',
        titleKey: 'nav.graphWorkbench',
        descKey: 'dataHub.descGraph',
        icon: DeploymentUnitOutlined,
        to: `/agent/${agentId.value}/graph-workbench`,
      },
      {
        id: 'facts',
        moduleKey: '/agent/:id/facts',
        titleKey: 'nav.factExplorer',
        descKey: 'ontology.factSubtitle',
        icon: NodeIndexOutlined,
        to: `/agent/${agentId.value}/facts`,
      },
    ],
  },
  {
    key: 'interop',
    titleKey: 'dataHub.groupInterop',
    items: [
      {
        id: 'interop',
        moduleKey: '/knowledge/interop',
        titleKey: 'nav.knowledgeInterop',
        descKey: 'ontology.interopSubtitle',
        icon: ExportOutlined,
        to: '/knowledge/interop',
      },
      {
        id: 'knowledge-eval',
        moduleKey: '/knowledge-eval',
        titleKey: 'nav.knowledgeEval',
        descKey: 'knowledgeEval.subtitle',
        icon: ExperimentOutlined,
        to: '/knowledge-eval',
      },
    ],
  },
]

const visibleGroups = computed(() => {
  const ctx = authStore.user ?? {}
  return GROUPS
    .map((group) => ({
      ...group,
      items: group.items.filter((entry) => canAccessModule(entry.moduleKey, ctx)),
    }))
    .filter((group) => group.items.length)
})

function go(to: string) {
  router.push(to)
}
</script>

<style scoped>
.data-hub-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
}
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}
.page-title {
  margin: 0;
  font-size: 20px;
  color: var(--nr-text-primary, inherit);
}
.page-subtitle {
  margin: 4px 0 0;
  color: var(--nr-text-secondary, inherit);
}
.hint-alert {
  margin-bottom: 4px;
}
.hub-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.group-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--nr-text-primary, inherit);
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-icon {
  color: var(--nr-text-secondary, inherit);
}
.card-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--nr-text-primary, inherit);
}
.card-desc {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--nr-text-secondary, inherit);
}
.card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 10px;
}
.card-link {
  font-size: 12px;
  color: var(--nr-accent, inherit);
  cursor: pointer;
}
</style>
