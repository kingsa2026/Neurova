<template>
  <div class="terms-section" data-testid="studio-terms">
    <div class="terms-toolbar">
      <a-input-search
        v-model:value="filter"
        size="sm"
        allow-clear
        class="terms-search"
        :placeholder="t('ontology.termSearch')"
      />
      <GlassButton v-if="isAdmin" size="sm" data-testid="terms-new" @click="openCreate">
        {{ t('ontology.newTerm') }}
      </GlassButton>
    </div>

    <div class="terms-layout">
      <!-- 树：concept 父子层级（upper-lite 父链 + 业务术语） -->
      <div class="terms-tree" data-testid="terms-tree">
        <div v-if="!rootTerms.length && !loading" class="terms-empty">{{ t('ontology.termsEmpty') }}</div>
        <div v-for="term in rootTerms" :key="term.term_id" class="tree-node">
          <div class="tree-row" @click="selectTerm(term)">
            <a-tag :color="kindColor(term.kind)" class="kind-tag">{{ term.kind }}</a-tag>
            <span class="term-name" :class="{ 'is-deprecated': term.deprecated }">{{ term.term_id }}</span>
            <a-tag v-if="term.deprecated" color="orange">{{ t('ontology.deprecatedTag') }}</a-tag>
          </div>
          <div v-if="childrenOf(term.term_id).length" class="tree-children">
            <div v-for="child in childrenOf(term.term_id)" :key="child.term_id" class="tree-row tree-row--child" @click="selectTerm(child)">
              <a-tag :color="kindColor(child.kind)" class="kind-tag">{{ child.kind }}</a-tag>
              <span class="term-name" :class="{ 'is-deprecated': child.deprecated }">{{ child.term_id }}</span>
              <a-tag v-if="child.deprecated" color="orange">{{ t('ontology.deprecatedTag') }}</a-tag>
            </div>
          </div>
        </div>
      </div>

      <!-- 表 + 编辑器 -->
      <div class="terms-main">
        <table class="terms-table" data-testid="terms-table">
          <thead>
            <tr>
              <th>{{ t('ontology.termId') }}</th>
              <th>{{ t('ontology.termKind') }}</th>
              <th>{{ t('ontology.termLabel') }}</th>
              <th>{{ t('ontology.termParent') }}</th>
              <th>{{ t('ontology.termVersion') }}</th>
              <th v-if="isAdmin">{{ t('common.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="term in pagedTerms"
              :key="term.term_id"
              :class="{ 'is-selected': selectedId === term.term_id }"
              @click="selectTerm(term)"
            >
              <td class="mono">{{ term.term_id }}</td>
              <td>{{ term.kind }}</td>
              <td>{{ term.label }}</td>
              <td class="mono">{{ term.parent_term_id || '-' }}</td>
              <td>{{ term.version }}</td>
              <td v-if="isAdmin">
                <a-button type="text" size="sm" @click.stop="openEdit(term)">✎</a-button>
                <a-popconfirm :title="t('ontology.termDeleteConfirm')" @confirm="deleteTerm(term)">
                  <a-button type="text" size="sm" danger data-testid="term-delete">✕</a-button>
                </a-popconfirm>
              </td>
            </tr>
            <tr v-if="!filteredTerms.length && !loading">
              <td colspan="6">
                <a-empty :description="t('ontology.termsEmpty')" />
              </td>
            </tr>
          </tbody>
        </table>
        <a-pagination
          v-if="filteredTerms.length"
          v-model:current="termsCurrentPage"
          :page-size="20"
          :total="filteredTerms.length"
          :show-size-changer="false"
          class="list-pagination"
        />

        <!-- 详情/编辑器：结构化字段；labels/module/identityKeys 只读展示 -->
    <div v-if="editorVisible" class="term-editor-wrap" data-testid="term-editor">
      <div class="term-editor">
        <div class="term-editor-head">
          <h4 class="editor-title">{{ editingId ? t('ontology.editTerm') : t('ontology.newTerm') }}</h4>
          <a-button type="text" size="sm" data-testid="term-editor-close" @click="closeEditor">✕</a-button>
        </div>
          <div class="editor-grid">
            <label class="field">
              <span>{{ t('ontology.termId') }}</span>
              <a-input v-model:value="form.term_id" size="sm" :disabled="!!editingId" data-testid="term-term-id" />
            </label>
            <label class="field">
              <span>{{ t('ontology.termKind') }}</span>
              <a-select v-model:value="form.kind" size="sm">
                <a-select-option value="concept">concept</a-select-option>
                <a-select-option value="relation">relation</a-select-option>
                <a-select-option value="property">property</a-select-option>
              </a-select>
            </label>
            <label class="field">
              <span>{{ t('ontology.termLabel') }}</span>
              <a-input v-model:value="form.label" size="sm" />
            </label>
            <label class="field">
              <span>{{ t('ontology.termDefinition') }}</span>
              <a-textarea v-model:value="form.definition" size="sm" :rows="2" />
            </label>
            <label v-if="form.kind === 'property'" class="field">
              <span>{{ t('ontology.termDatatype') }}</span>
              <a-select v-model:value="form.datatype" size="sm" allow-clear>
                <a-select-option value="boolean">boolean</a-select-option>
                <a-select-option value="date">date</a-select-option>
                <a-select-option value="number">number</a-select-option>
                <a-select-option value="text">text</a-select-option>
                <a-select-option value="url">url</a-select-option>
              </a-select>
            </label>
            <label class="field">
              <span>{{ t('ontology.termNamespace') }}</span>
              <a-select v-model:value="form.namespace" size="sm" allow-clear>
                <a-select-option v-for="(base, prefix) in namespaceOptions" :key="prefix" :value="prefix">
                  {{ prefix }}（{{ base }}）
                </a-select-option>
              </a-select>
            </label>
            <label class="field">
              <span>{{ t('ontology.termParent') }}</span>
              <a-select v-model:value="form.parent_term_id" size="sm" allow-clear>
                <a-select-option v-for="concept in conceptTerms" :key="concept.term_id" :value="concept.term_id">
                  {{ concept.term_id }}
                </a-select-option>
              </a-select>
            </label>
            <label class="field">
              <span>{{ t('ontology.termDomain') }}</span>
              <a-input v-model:value="form.domain_text" size="sm" placeholder="A, B" />
            </label>
            <label class="field">
              <span>{{ t('ontology.termRange') }}</span>
              <a-input v-model:value="form.range_terms_text" size="sm" placeholder="A, B" />
            </label>
            <label class="field">
              <span>{{ t('ontology.termRangeKinds') }}</span>
              <a-input v-model:value="form.range_kinds_text" size="sm" placeholder="concept" />
            </label>
            <label class="field">
              <span>{{ t('ontology.termCardinality') }}</span>
              <a-input-number v-model:value="form.cardinality" size="sm" :min="1" class="w-full" />
            </label>
            <label class="field">
              <span>{{ t('ontology.termDisjoint') }}</span>
              <a-input v-model:value="form.disjoint_text" size="sm" placeholder="A, B" />
            </label>
            <label class="field">
              <span>{{ t('ontology.termRequiredProps') }}</span>
              <a-input v-model:value="form.required_props_text" size="sm" placeholder="prop1, prop2" />
            </label>
            <label class="field">
              <span>{{ t('ontology.termAliases') }}</span>
              <a-input v-model:value="form.aliases_text" size="sm" placeholder="a, b" />
            </label>
            <label class="field">
              <span>{{ t('ontology.termExternalIris') }}</span>
              <a-input v-model:value="form.external_iris_text" size="sm" placeholder='[{"kind": "skos_exactMatch", "iri": "http://…"}]' />
            </label>
            <label class="field">
              <span>{{ t('ontology.termReplacedBy') }}</span>
              <a-input v-model:value="form.replaced_by" size="sm" />
            </label>
            <label class="field">
              <span>{{ t('ontology.termModule') }}</span>
              <a-select v-model:value="form.module" size="sm" data-testid="term-module">
                <a-select-option value="">-</a-select-option>
                <a-select-option value="core">core</a-select-option>
                <a-select-option value="domain">domain</a-select-option>
              </a-select>
            </label>
            <label class="field">
              <span>{{ t('ontology.termLabels') }}</span>
              <a-input
                v-model:value="form.labels_text"
                size="sm"
                data-testid="term-labels"
                placeholder='{"zh": "风险订单", "en": "Risk Order"}'
              />
            </label>
            <label class="field">
              <span>{{ t('ontology.termAltLabels') }}</span>
              <a-input
                v-model:value="form.alt_labels_text"
                size="sm"
                data-testid="term-alt-labels"
                placeholder='{"zh": ["高危单"]}'
              />
            </label>
            <label class="field">
              <span>{{ t('ontology.termIdentityKeys') }}</span>
              <a-input
                v-model:value="form.identity_keys_text"
                size="sm"
                data-testid="term-identity-keys"
                placeholder="external_id"
              />
            </label>
            <label class="field">
              <span>{{ t('ontology.termQualifierSchema') }}</span>
              <a-input
                v-model:value="form.qualifier_schema_text"
                size="sm"
                data-testid="term-qualifier-schema"
                placeholder='{"carrier": {"required": true}}'
              />
            </label>
            <label class="field">
              <span>{{ t('ontology.termVersion') }}</span>
              <a-input v-model:value="form.version" size="sm" />
            </label>
            <label class="field">
              <span>{{ t('ontology.termBasis') }}</span>
              <a-input v-model:value="form.basis" size="sm" />
            </label>
            <label class="field field--check">
              <a-checkbox v-model:checked="form.deprecated">{{ t('ontology.termDeprecated') }}</a-checkbox>
            </label>
          </div>
          <p class="field-hint">{{ t('ontology.termFunctionalNote') }}</p>

          <div class="editor-actions">
            <GlassButton size="sm" :loading="saving" data-testid="term-save" @click="saveTerm">
              {{ t('common.confirm') }}
            </GlassButton>
            <GlassButton size="sm" variant="secondary" @click="closeEditor">
              {{ t('common.cancel') }}
            </GlassButton>
          </div>
        </div>
    </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  createOntologyTerm,
  deleteOntologyTerm,
  listOntologyNamespaces,
  listOntologyTerms,
  updateOntologyTerm,
} from '@/api/modules/ontology'
import type { OntologyTerm, OntologyTermWrite } from '@/types/ontology'
import { impactCount, ontologyErrorDetail, splitList } from '@/utils/ontologyFormat'

const props = defineProps<{ isAdmin: boolean }>()

const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const filter = ref('')
const terms = ref<OntologyTerm[]>([])

const editorVisible = ref(false)
const editingId = ref('')
const selectedId = ref('')

interface TermForm {
  term_id: string
  kind: 'concept' | 'relation' | 'property'
  label: string
  definition: string
  datatype: string
  namespace: string
  parent_term_id: string
  domain_text: string
  range_terms_text: string
  range_kinds_text: string
  cardinality: number | null
  disjoint_text: string
  required_props_text: string
  aliases_text: string
  external_iris_text: string
  replaced_by: string
  module: string
  labels_text: string
  alt_labels_text: string
  identity_keys_text: string
  qualifier_schema_text: string
  version: string
  basis: string
  deprecated: boolean
}

function emptyForm(): TermForm {
  return {
    term_id: '',
    kind: 'concept',
    label: '',
    parent_term_id: '',
    domain_text: '',
    range_terms_text: '',
    range_kinds_text: '',
    cardinality: null,
    disjoint_text: '',
    required_props_text: '',
    aliases_text: '',
    definition: '',
    datatype: '',
    namespace: '',
    external_iris_text: '',
    replaced_by: '',
    module: '',
    labels_text: '',
    alt_labels_text: '',
    identity_keys_text: '',
    qualifier_schema_text: '',
    version: 'v1',
    basis: '',
    deprecated: false,
  }
}

const form = reactive<TermForm>(emptyForm())

const conceptTerms = computed(() => terms.value.filter((item) => item.kind === 'concept'))

const filteredTerms = computed(() => {
  /* 分页在模板层做切片 */
  const needle = filter.value.trim().toLowerCase()
  if (!needle) return terms.value
  return terms.value.filter((term) => {
    const haystack = [term.term_id, term.label, ...(term.aliases ?? [])].join(' ').toLowerCase()
    return haystack.includes(needle)
  })
})

const termsCurrentPage = ref(1)
const pagedTerms = computed(() => filteredTerms.value.slice((termsCurrentPage.value - 1) * 20, termsCurrentPage.value * 20))
watch(() => filteredTerms.value.length, () => { termsCurrentPage.value = 1 })

/** 树根 = 无父术语的 concept；子层挂各自 parent。悬空 parent 的术语按根显示。 */
const rootTerms = computed(() =>
  filteredTerms.value.filter(
    (term) => term.kind === 'concept' && (!term.parent_term_id || !terms.value.some((item) => item.term_id === term.parent_term_id)),
  ),
)

function childrenOf(termId: string): OntologyTerm[] {
  return filteredTerms.value.filter((term) => term.parent_term_id === termId)
}

function kindColor(kind: string): string {
  if (kind === 'concept') return 'blue'
  if (kind === 'relation') return 'purple'
  return 'green'
}

/** 空容器在表单里显示为空文本（与「显式写 {} 清空」区分开）。 */
function jsonText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object' && Object.keys(value as object).length === 0) return ''
  return JSON.stringify(value)
}

function parseJsonMap(text: string): Record<string, never> | null {
  const trimmed = text.trim()
  return trimmed ? (JSON.parse(trimmed) as Record<string, never>) : null
}

// G3 结构化列表：外部 IRI 映射的客户端解析——格式（数组元素 kind/iri）客户端预检，
// kind 闭集的权威校验在注册表（EXTERNAL_IRI_KINDS），这里只挡明显笔误。
const EXTERNAL_IRI_KINDS = ['skos_exactMatch', 'skos_closeMatch', 'skos_relatedMatch', 'equivalentClass']

// G4：可用命名空间（GET /ontology/namespaces，空项 = 缺省 kbg: 由下拉 allow-clear 表达）
const namespaceOptions = ref<Record<string, string>>({})
onMounted(() => {
  void listOntologyNamespaces().then((res: any) => {
    namespaceOptions.value = res?.data ?? res ?? {}
  }).catch(() => { namespaceOptions.value = {} })
})

function parseExternalIris(text: string): Array<{ kind: string; iri: string }> | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    throw new Error(t('ontology.externalIrisFormatError'))
  }
  if (!Array.isArray(parsed)) {
    throw new Error(t('ontology.externalIrisFormatError'))
  }
  for (const entry of parsed as Array<{ kind?: string; iri?: string }>) {
    const kind = String(entry.kind ?? '').trim()
    const iri = String(entry.iri ?? '').trim()
    if (!EXTERNAL_IRI_KINDS.includes(kind) || !iri) {
      throw new Error(t('ontology.externalIrisEntryError'))
    }
  }
  return (parsed as Array<{ kind: string; iri: string }>).map((e) => ({ kind: String(e.kind ?? '').trim(), iri: String(e.iri ?? '').trim() }))
}

function selectTerm(term: OntologyTerm) {
  selectedId.value = term.term_id
}

async function loadTerms() {
  loading.value = true
  try {
    const res = await listOntologyTerms({ limit: 500 })
    terms.value = res.data?.items ?? []
  } catch {
    message.error(t('ontology.termsLoadFailed'))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, emptyForm())
  editingId.value = ''
  editorVisible.value = true
}

function openEdit(term: OntologyTerm) {
  Object.assign(form, emptyForm())
  form.term_id = term.term_id
  form.kind = (term.kind as TermForm['kind']) ?? 'concept'
  form.label = term.label ?? ''
  form.definition = term.definition ?? ''
  form.datatype = term.datatype ?? ''
  form.namespace = term.namespace ?? ''
  form.parent_term_id = term.parent_term_id ?? ''
  form.domain_text = (term.domain_terms ?? []).join(', ')
  form.range_terms_text = (term.range_terms ?? []).join(', ')
  form.range_kinds_text = (term.range_kinds ?? []).join(', ')
  form.cardinality = term.cardinality ?? null
  form.disjoint_text = (term.disjoint_with ?? []).join(', ')
  form.required_props_text = (term.required_props ?? []).join(', ')
  form.aliases_text = (term.aliases ?? []).join(', ')
  form.external_iris_text = term.external_iris && term.external_iris.length
    ? JSON.stringify(term.external_iris)
    : ''
  form.replaced_by = term.replaced_by ?? ''
  form.module = term.module ?? ''
  form.labels_text = jsonText(term.labels)
  form.alt_labels_text = jsonText(term.alt_labels)
  form.identity_keys_text = (term.identity_keys ?? []).join(', ')
  form.qualifier_schema_text = jsonText(term.qualifier_schema)
  form.version = term.version ?? 'v1'
  form.deprecated = !!term.deprecated
  editingId.value = term.term_id
  editorVisible.value = true
}

function closeEditor() {
  editorVisible.value = false
  editingId.value = ''
}

function buildPayload(): OntologyTermWrite {
  return {
    term_id: form.term_id.trim(),
    kind: form.kind,
    label: form.label.trim(),
    definition: form.definition.trim() || null,
    datatype: form.kind === 'property' ? form.datatype || null : null,
    namespace: form.namespace || null,
    parent_term_id: form.parent_term_id || null,
    domain: splitList(form.domain_text),
    range_terms: splitList(form.range_terms_text),
    range_kinds: splitList(form.range_kinds_text),
    cardinality: form.cardinality,
    disjoint_with: splitList(form.disjoint_text),
    required_props: splitList(form.required_props_text),
    aliases: splitList(form.aliases_text),
    external_iris: parseExternalIris(form.external_iris_text),
    deprecated: form.deprecated,
    replaced_by: form.replaced_by.trim() || null,
    // 空文本 → null（PUT 语义「保留现值」）；写 {} 才是显式清空声明
    labels: parseJsonMap(form.labels_text) as Record<string, string> | null,
    alt_labels: parseJsonMap(form.alt_labels_text) as Record<string, string[]> | null,
    module: form.module || null,
    identity_keys: form.identity_keys_text.trim() ? splitList(form.identity_keys_text) : null,
    qualifier_schema: parseJsonMap(form.qualifier_schema_text),
    version: form.version.trim() || undefined,
    basis: form.basis.trim(),
  }
}

async function saveTerm() {
  if (!form.term_id.trim()) {
    message.warning(t('common.required'))
    return
  }
  saving.value = true
  try {
    const payload = buildPayload()
    if (editingId.value) {
      await updateOntologyTerm(editingId.value, payload)
    } else {
      await createOntologyTerm(payload)
    }
    message.success(t('ontology.termSaved'))
    closeEditor()
    await loadTerms()
  } catch (error) {
    // 400/409 的逐条原因由后端 detail 带回，原话显式露出；取不到才落通用文案
    const { message: reject } = ontologyErrorDetail(error)
    message.error(reject || t('ontology.termSaveFailed'))
  } finally {
    saving.value = false
  }
}

async function deleteTerm(term: OntologyTerm) {
  try {
    await deleteOntologyTerm(term.term_id)
    message.success(t('ontology.termDeleted'))
    if (selectedId.value === term.term_id) selectedId.value = ''
    await loadTerms()
  } catch (error) {
    const { message: reject, impact } = ontologyErrorDetail(error)
    if (impact) {
      // 被谁引用是「删不掉的唯一理由」，四计数逐条显出（含 referencing_rules，缺一即口径不全）
      message.error(`${reject || t('ontology.termDeleteFailed')}${t('ontology.termImpactCounters', {
        facts: impactCount(impact, 'fact_count'),
        typed: impactCount(impact, 'typed_subject_count'),
        children: impactCount(impact, 'child_terms'),
        rules: impactCount(impact, 'referencing_rules'),
      })}`)
      return
    }
    message.error(reject || t('ontology.termDeleteFailed'))
  }
}

onMounted(loadTerms)

defineExpose({ loadTerms })
</script>

<style scoped>
.terms-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 10px;
}
.terms-search {
  max-width: 240px;
}
.terms-layout {
  display: grid;
  grid-template-columns: minmax(180px, 260px) minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}
@media (max-width: 760px) {
  .terms-layout {
    grid-template-columns: 1fr;
  }
}
.terms-tree,
.terms-main {
  min-width: 0;
}
.terms-empty {
  font-size: 13px;
  color: var(--nr-text-secondary, inherit);
}
.tree-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.tree-row--child {
  margin-left: 16px;
}
.tree-row:hover,
.tree-row.is-selected {
  background: var(--nr-fill-secondary, rgba(128, 128, 128, 0.12));
}
.term-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.term-name.is-deprecated {
  text-decoration: line-through;
  opacity: 0.7;
}
.terms-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.terms-table th,
.terms-table td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
}
.terms-table tbody tr {
  cursor: pointer;
}
.terms-table tbody tr.is-selected {
  background: var(--nr-fill-secondary, rgba(128, 128, 128, 0.12));
}
.mono {
  font-family: var(--nr-font-mono, monospace);
  font-size: 12px;
}
.term-editor-wrap {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: var(--nr-bg-inset-deep, rgba(0, 0, 0, 0.35));
  display: flex;
  align-items: center;
  justify-content: center;
}
.term-editor {
  width: 880px;
  max-width: calc(100vw - 48px);
  max-height: 82vh;
  overflow: auto;
  padding: 16px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.25));
  border-radius: 10px;
  background: var(--nr-bg-elevated, #111827);
}
.term-editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.editor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 8px 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}
.field--check {
  justify-content: flex-end;
}
.w-full {
  width: 100%;
}
.field-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.editor-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
.list-pagination {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}
</style>
