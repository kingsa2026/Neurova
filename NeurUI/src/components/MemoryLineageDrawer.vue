<template>
  <a-drawer
    :open="open"
    :title="t('memory.lineageTitle')"
    width="560"
    @update:open="emit('update:open', $event)"
  >
    <a-spin :spinning="loading">
      <a-empty v-if="!lineage" :description="t('memory.lineageEmpty')" />
      <template v-else>
        <p class="lineage-head">
          <a-tag color="blue">{{ t('memory.lineageCurrent') }}</a-tag>
          <span class="lineage-root">{{ lineage.root_id }}</span>
        </p>
        <a-alert
          v-if="lineage.edges.length"
          type="info"
          :message="t('memory.lineageHint')"
          show-icon
          class="lineage-hint"
        />
        <a-empty v-if="lineage.nodes.length <= 1" :description="t('memory.lineageNoHops')" />
        <a-timeline v-else class="lineage-timeline">
          <a-timeline-item
            v-for="gen in generations"
            :key="gen.level"
            :color="gen.nodes.some((n) => n.is_root) ? 'blue' : 'gray'"
          >
            <p class="gen-title">{{ t('memory.lineageGeneration', { n: gen.level + 1 }) }}</p>
            <div v-for="node in gen.nodes" :key="node.id" class="gen-node">
              <div class="node-header">
                <a-tag v-if="node.is_root" color="blue" size="small">{{ t('memory.lineageCurrent') }}</a-tag>
                <a-tag v-if="isRetired(node)" color="default" size="small">{{ t('memory.lineageRetired') }}</a-tag>
                <span class="node-id">{{ node.id }}</span>
                <span class="node-time">{{ node.created_at }}</span>
              </div>
              <p class="node-content">{{ node.content }}</p>
              <div v-for="edge in edgesInto(node.id)" :key="edge.from + edge.relation" class="node-edges">
                <a-tag :color="edge.relation === 'superseded_by' ? 'orange' : 'geekblue'" size="small">
                  {{ edge.relation === 'superseded_by' ? t('memory.lineageSuperseded') : t('memory.lineageMerged') }}
                </a-tag>
                <span class="edge-from">{{ edge.from }} → {{ edge.to }}</span>
                <span v-if="edge.basis" class="edge-basis">{{ t('memory.lineageBasis') }}: {{ edge.basis }}</span>
              </div>
            </div>
          </a-timeline-item>
        </a-timeline>
      </template>
    </a-spin>
  </a-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { getMemoryLineage, type MemoryLineage, type MemoryLineageNode } from '@/api/modules/memory'

const props = defineProps<{ open: boolean; agentId: string; memoryId: string }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()
const { t } = useI18n()

const lineage = ref<MemoryLineage | null>(null)
const loading = ref(false)

const RETIRED_STAGES = new Set(['forgotten', 'archived'])
const isRetired = (node: MemoryLineageNode) => RETIRED_STAGES.has(node.lifecycle_stage)

/** 世代分层：边一律旧→新，层级 = 自起点的最长路径（合并 DAG 也成立）。 */
const generations = computed(() => {
  const data = lineage.value
  if (!data) return []
  const level = new Map<string, number>()
  const incoming = new Map<string, string[]>()
  for (const node of data.nodes) level.set(node.id, 0)
  for (const edge of data.edges) {
    incoming.set(edge.to, [...(incoming.get(edge.to) ?? []), edge.from])
  }
  // 松弛足够多轮（节点数上限即轮数上限）收敛最长路径
  for (let round = 0; round < data.nodes.length; round += 1) {
    let changed = false
    for (const edge of data.edges) {
      const next = (level.get(edge.from) ?? 0) + 1
      if (next > (level.get(edge.to) ?? 0)) {
        level.set(edge.to, next)
        changed = true
      }
    }
    if (!changed) break
  }
  const grouped = new Map<number, MemoryLineageNode[]>()
  for (const node of data.nodes) {
    const lvl = level.get(node.id) ?? 0
    grouped.set(lvl, [...(grouped.get(lvl) ?? []), node])
  }
  return [...grouped.entries()]
    .sort(([a], [b]) => a - b)
    .map(([lvl, nodes]) => ({ level: lvl, nodes }))
})

const edgesInto = (nodeId: string) =>
  (lineage.value?.edges ?? []).filter((e) => e.to === nodeId)

async function load(memoryId: string) {
  if (!memoryId) return
  loading.value = true
  lineage.value = null
  try {
    const res = await getMemoryLineage(props.agentId, memoryId)
    lineage.value = (res as any)?.data?.data ?? (res as any)?.data ?? null
  } catch {
    message.error(t('memory.lineageLoadFailed'))
  } finally {
    loading.value = false
  }
}

watch(() => [props.open, props.memoryId], ([open, memoryId]) => {
  if (open && memoryId) load(String(memoryId))
}, { immediate: true })
</script>

<style scoped>
.lineage-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.lineage-root {
  font-family: var(--nr-font-mono, monospace);
  font-size: 12px;
  color: var(--nr-text-secondary);
}
.lineage-hint {
  margin-bottom: 12px;
}
.gen-title {
  margin: 0 0 6px;
  font-weight: 600;
  color: var(--nr-text-primary);
}
.gen-node {
  padding: 6px 0 10px;
  border-bottom: 1px dashed var(--nr-border-secondary, rgba(255, 255, 255, 0.08));
}
.node-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.node-id {
  font-family: var(--nr-font-mono, monospace);
  font-size: 11px;
  color: var(--nr-text-muted);
}
.node-time {
  font-size: 11px;
  color: var(--nr-text-muted);
}
.node-content {
  margin: 4px 0;
  font-size: 13px;
  color: var(--nr-text-secondary);
  white-space: pre-wrap;
}
.node-edges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}
.edge-from {
  font-size: 11px;
  color: var(--nr-text-muted);
  font-family: var(--nr-font-mono, monospace);
}
.edge-basis {
  font-size: 11px;
  color: var(--nr-text-secondary);
}
</style>
