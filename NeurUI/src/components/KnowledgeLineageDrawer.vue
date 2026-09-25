<template>
  <a-drawer
    :open="open"
    :title="t('knowledge.lineageTitle')"
    width="560"
    @update:open="emit('update:open', $event)"
  >
    <a-spin :spinning="loading">
      <a-empty v-if="!lineage" :description="t('knowledge.lineageEmpty')" />
      <template v-else>
        <p class="lineage-head">
          <strong>{{ lineage.subject_label }}</strong>
          <span class="lineage-predicate">{{ lineage.predicate }}</span>
          <span>{{ lineage.object_term }}</span>
          <a-tag v-if="lineage.derivation" color="purple">{{ t('knowledge.lineageDerivedBy', { rule: lineage.derivation.rule_id }) }}</a-tag>
          <a-tag v-else>{{ t(lineage.provenance_state === 'evidenced' ? 'knowledge.lineageStateEvidenced' : 'knowledge.lineageStateUnevidenced') }}</a-tag>
        </p>

        <!-- 缺维必须显式说出来：只隐藏空白区等于把"没溯源"演成"已溯源" -->
        <a-alert
          v-if="lineage.missing.length"
          type="warning"
          :message="t('knowledge.lineageMissing')"
          :description="lineage.missing.map(describeMissingDimension).join('、')"
          show-icon
        />

        <a-timeline v-if="lineage.hops.length" class="lineage-timeline">
          <a-timeline-item
            v-for="(hop, idx) in lineage.hops"
            :key="hopKind(hop) + idx"
            :color="hopKind(hop) === 'derivation' ? 'purple' : 'blue'"
          >
            <template v-if="hopKind(hop) === 'assertion'">
              <p class="hop-title">
                {{ t('knowledge.lineageAssertion', {
                  actor: `${(hop as LineageAssertionHop).actor_type}:${(hop as LineageAssertionHop).actor_id}`,
                  at: (hop as LineageAssertionHop).asserted_at,
                }) }}
              </p>
              <p class="hop-statement">{{ (hop as LineageAssertionHop).statement_text }}</p>
              <p class="hop-meta">
                <span>{{ t('knowledge.lineageMedium') }}: {{ (hop as LineageAssertionHop).medium_ref || '—' }}</span>
                <span>{{ t('knowledge.lineageActivity') }}: {{ (hop as LineageAssertionHop).activity_kind || '—' }}</span>
                <span v-if="(hop as LineageAssertionHop).digest">
                  {{ t('knowledge.lineageChain') }}: #{{ (hop as LineageAssertionHop).seq }}
                </span>
              </p>
            </template>
            <template v-else>
              <p class="hop-title">{{ t('knowledge.lineagePremises') }}</p>
              <ul class="hop-premises">
                <li v-for="premise in (hop as LineageDerivationHop).premises" :key="premise.fact_id">
                  <button class="premise-link" type="button" @click="emit('open-fact', premise.fact_id)">
                    {{ premise.subject_label }} {{ premise.predicate }} {{ premise.object_term }}
                  </button>
                  <p v-for="text in premise.statement_texts" :key="text" class="hop-statement">{{ text }}</p>
                  <p v-if="!premise.statement_texts.length" class="hop-gap">
                    {{ describeMissingDimension('assertions') }}
                  </p>
                </li>
              </ul>
            </template>
          </a-timeline-item>
        </a-timeline>
        <a-empty v-else :description="t('knowledge.lineageNoHops')" />

        <a-button class="lineage-export" :loading="exporting" @click="downloadTurtle">
          {{ t('knowledge.lineageExportTurtle') }}
        </a-button>
      </template>
    </a-spin>
  </a-drawer>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import {
  getFactLineage,
  getFactTurtle,
  type FactLineage,
  type LineageAssertionHop,
  type LineageDerivationHop,
  type LineageHop,
} from '@/api/modules/knowledge'

const props = defineProps<{ open: boolean; factId: string }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void; (e: 'open-fact', factId: string): void }>()
const { t } = useI18n()

const lineage = ref<FactLineage | null>(null)
const loading = ref(false)
const exporting = ref(false)

function hopKind(hop: LineageHop): 'assertion' | 'derivation' {
  return hop.kind
}

/**
 * 后端报的是数据里的维度名（蛇形），locale 键必须是两段式驼峰——中间这张表就是翻译本身。
 * 认不出的维度不许显示成裸键，所以留了一条带原文的兜底。
 */
const LINEAGE_DIM_KEYS: Record<string, string> = {
  assertions: 'knowledge.lineageMissingAssertions',
  activity: 'knowledge.lineageMissingActivity',
  medium_ref: 'knowledge.lineageMissingMedium',
  derivation: 'knowledge.lineageMissingDerivation',
  premise_statements: 'knowledge.lineageMissingPremiseStatements',
}

function describeMissingDimension(dim: string): string {
  const key = LINEAGE_DIM_KEYS[dim]
  return key ? t(key) : t('knowledge.lineageMissingOther', { dim })
}

async function load(factId: string) {
  if (!factId) return
  loading.value = true
  lineage.value = null
  try {
    lineage.value = await getFactLineage(factId)
  } catch {
    message.error(t('knowledge.lineageLoadFailed'))
  } finally {
    loading.value = false
  }
}

async function downloadTurtle() {
  if (!lineage.value) return
  exporting.value = true
  try {
    const text = await getFactTurtle(lineage.value.fact_id)
    const url = URL.createObjectURL(new Blob([text], { type: 'text/turtle' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `${lineage.value.fact_id}.ttl`
    link.click()
    URL.revokeObjectURL(url)
  } catch {
    message.error(t('knowledge.lineageExportFailed'))
  } finally {
    exporting.value = false
  }
}

watch(() => [props.open, props.factId], ([open, factId]) => {
  if (open && factId) load(String(factId))
}, { immediate: true })
</script>

<style scoped>
.lineage-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: baseline;
  margin-bottom: 12px;
}

.lineage-predicate {
  font-family: var(--font-mono, monospace);
  opacity: 0.7;
}

.hop-title {
  margin: 0 0 4px;
  font-weight: 600;
}

.hop-statement {
  margin: 2px 0;
  white-space: pre-wrap;
}

.hop-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 4px 0 0;
  font-size: 12px;
  opacity: 0.75;
}

.hop-premises {
  margin: 0;
  padding-left: 18px;
}

.hop-gap {
  font-size: 12px;
  color: var(--color-warning, #d89614);
}

.premise-link {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font: inherit;
  text-decoration: underline dotted;
}

.lineage-export {
  margin-top: 16px;
}
</style>
