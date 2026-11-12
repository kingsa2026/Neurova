<template>
  <div class="interop-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('ontology.interopTitle') }}</h2>
        <p class="page-subtitle">{{ t('ontology.interopSubtitle') }}</p>
      </div>
    </div>

    <!-- 导出格式卡：五格式 REST 已接线；RDF 1.1 基线，RDF 1.2 只观察 -->
    <GlassPanel class="panel">
      <div class="panel-head">
        <span class="panel-title" data-testid="interop-export-title">{{ t('ontology.exportTitle') }}</span>
        <span class="admin-note">{{ t('ontology.exportAdminOnly') }}</span>
      </div>
      <p class="honest-note" data-testid="interop-export-note">RDF 1.1 baseline; RDF 1.2 observe only.</p>
      <div class="format-grid">
        <div v-for="format in FORMATS" :key="format.key" class="format-card format-card--live" :data-testid="`export-${format.key}-card`">
          <div class="format-name">{{ format.name }}</div>
          <p class="format-desc">{{ format.desc }}</p>
          <GlassButton
            size="sm"
            :loading="exportingFormat === format.key"
            :data-testid="`export-${format.key}-btn`"
            @click="downloadFormat(format)"
          >
            {{ t('ontology.exportDownload') }}
          </GlassButton>
        </div>
      </div>
    </GlassPanel>

    <!-- 稳定 IRI 解析（B12）：kbg:/外部 IRI → 术语行；失败显式报错 -->
    <GlassPanel class="panel">
      <div class="panel-head">
        <span class="panel-title" data-testid="iri-title">{{ t('ontology.iriTitle') }}</span>
      </div>
      <div class="iri-bar">
        <a-input
          v-model:value="iriInput"
          size="sm"
          class="iri-input"
          data-testid="iri-input"
          :placeholder="t('ontology.iriHint')"
          @press-enter="resolveIri"
        />
        <GlassButton size="sm" :loading="resolving" data-testid="iri-resolve-btn" @click="resolveIri">
          {{ t('ontology.iriResolveBtn') }}
        </GlassButton>
      </div>
      <p v-if="!iriResult && !iriError" class="iri-empty" data-testid="iri-empty">{{ t('ontology.iriEmpty') }}</p>
      <a-alert
        v-else-if="iriError"
        type="error"
        show-icon
        data-testid="iri-error"
        :message="t('ontology.iriNotFound')"
      />
      <div v-else-if="iriResult" class="iri-result" data-testid="iri-result">
        <div class="detail-row">
          <span class="k">term_id</span>
          <span class="v mono">{{ iriResult.term_id }}</span>
          <a-button type="text" size="sm" data-testid="iri-copy" @click="copyIri">
            {{ t('ontology.copyIri') }}
          </a-button>
        </div>
        <div class="detail-row">
          <span class="k">{{ t('ontology.termLabel') }}</span>
          <span class="v">{{ iriResult.term?.label || '-' }}</span>
        </div>
        <div class="detail-row">
          <span class="k">{{ t('ontology.termKind') }}</span>
          <span class="v">{{ iriResult.term?.kind || '-' }}</span>
        </div>
        <div class="detail-row">
          <span class="k">{{ t('ontology.termExternalIris') }}</span>
          <span class="v mono">{{ jsonOrDash(iriResult.term?.external_iris) }}</span>
        </div>
      </div>
    </GlassPanel>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { message } from 'ant-design-vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  exportOntologyJsonLd,
  exportOntologyOwl,
  exportOntologyProv,
  exportOntologyCsv,
  exportOntologyCypher,
  exportOntologyGexf,
  exportOntologyGraphML,
  exportOntologyShacl,
  exportOntologyTtl,
  resolveOntologyIri,
} from '@/api/modules/ontology'
import type { IriResolution } from '@/types/ontology'
import { jsonOrDash } from '@/utils/ontologyFormat'

const authStore = useAuthStore()

const { t } = useI18n()

interface ExportFormat {
  key: string
  name: string
  desc: string
  filename: string
  mime: string
  run: () => Promise<string>
}

const FORMATS: ExportFormat[] = [
  { key: 'ttl', name: 'Turtle', desc: t('ontology.exportTurtleDesc'), filename: 'ontology-export.ttl', mime: 'text/turtle', run: () => exportOntologyTtl() },
  { key: 'jsonld', name: 'JSON-LD', desc: 'JSON-LD @context + @graph', filename: 'ontology-export.jsonld', mime: 'application/ld+json', run: () => exportOntologyJsonLd() },
  { key: 'owl', name: 'OWL 2 RL', desc: 'subClass / inverse / transitive axioms', filename: 'ontology-export.owl.ttl', mime: 'text/turtle', run: () => exportOntologyOwl() },
  { key: 'shacl', name: 'SHACL', desc: 'shape registry → sh: shapes', filename: 'ontology-shapes.ttl', mime: 'text/turtle', run: () => exportOntologyShacl() },
  { key: 'prov', name: 'PROV-O', desc: 'activities / derivations', filename: 'ontology-prov.ttl', mime: 'text/turtle', run: () => exportOntologyProv() },
  { key: 'graphml', name: 'GraphML', desc: 'XML graph exchange', filename: 'ontology-export.graphml', mime: 'application/graphml+xml', run: () => exportOntologyGraphML() },
  { key: 'gexf', name: 'GEXF', desc: 'GEXF 1.3 graph exchange', filename: 'ontology-export.gexf', mime: 'application/gexf+xml', run: () => exportOntologyGexf() },
  { key: 'cypher', name: 'Cypher', desc: 'CREATE statements dump', filename: 'ontology-export.cypher', mime: 'text/plain', run: () => exportOntologyCypher() },
  { key: 'csv', name: 'CSV', desc: 'nodes / edges dual file', filename: 'ontology-export.csv', mime: 'text/csv', run: () => exportOntologyCsv() },
]

const exportingFormat = ref('')
const resolving = ref(false)
const iriInput = ref('')
const iriResult = ref<Extract<IriResolution, { kind: 'term' }> | null>(null)
const iriError = ref(false)

async function downloadFormat(format: ExportFormat) {
  exportingFormat.value = format.key
  try {
    const text = await format.run()
    const url = URL.createObjectURL(new Blob([text], { type: format.mime }))
    const link = document.createElement('a')
    link.href = url
    link.download = format.filename
    link.click()
    URL.revokeObjectURL(url)
  } catch {
    // 403（非管理员）等失败由拦截器记录；这里显式报错不吞
    message.error(t('common.error'))
  } finally {
    exportingFormat.value = ''
  }
}

async function resolveIri() {
  const iri = iriInput.value.trim()
  if (!iri) return
  resolving.value = true
  iriResult.value = null
  iriError.value = false
  try {
    const res = await resolveOntologyIri(iri)
    const payload = res.data as IriResolution | null
    if (payload && payload.kind === 'term' && payload.term_id) {
      iriResult.value = payload
    } else {
      iriError.value = true
    }
  } catch {
    iriError.value = true
  } finally {
    resolving.value = false
  }
}

async function copyIri() {
  if (!iriResult.value) return
  try {
    await navigator.clipboard.writeText(`kbg:${iriResult.value.term_id}`)
    message.success(t('ontology.copied'))
  } catch {
    message.info(`kbg:${iriResult.value.term_id}`)
  }
}

/** W11（P9 拍板②）：admin 真门——页面与路由此前无角色门控，
     仅 exportAdminOnly 文案提示（假门）。补真门与文案语义对齐。 */
const isAdmin = computed(() => {
  const user = authStore.user as { role?: string } | null | undefined
  return user?.role === 'admin'
})
</script>

<style scoped>
.interop-page {
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
.panel + .panel {
  margin-top: 0;
}
.panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}
.panel-title {
  font-weight: 600;
  font-size: 14px;
}
.admin-note {
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.honest-note {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.format-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}
.format-card {
  padding: 12px;
  border-radius: 10px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.25));
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}
.format-name {
  font-weight: 600;
}
.format-desc {
  margin: 0;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.iri-bar {
  display: flex;
  gap: 8px;
}
.iri-input {
  flex: 1;
}
.iri-empty {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.iri-result {
  margin-top: 10px;
}
.detail-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 6px;
}
.detail-row .k {
  min-width: 90px;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.detail-row .v {
  font-size: 13px;
  word-break: break-all;
}
.mono {
  font-family: var(--nr-font-mono, monospace);
  font-size: 12px;
}
</style>
