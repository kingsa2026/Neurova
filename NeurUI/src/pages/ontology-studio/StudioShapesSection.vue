<template>
  <div class="shapes-section" data-testid="studio-shapes">
    <div class="shapes-head">
      <div>
        <h4 class="section-title">{{ t('ontology.shapesTitle') }}</h4>
        <p class="shapes-note">{{ t('ontology.shapesNote') }}</p>
      </div>
      <GlassButton
        v-if="isAdmin"
        size="sm"
        data-testid="shapes-new"
        @click="showForm = !showForm"
      >
        {{ t('ontology.shapesNewBtn') }}
      </GlassButton>
    </div>

    <p v-if="!isAdmin" class="admin-note" data-testid="shapes-admin-note">{{ t('ontology.shapesAdminOnly') }}</p>

    <div v-if="isAdmin && showForm" class="shape-form" data-testid="shape-form">
      <label class="field"><span>shape_id</span><a-input v-model:value="form.shape_id" size="sm" data-testid="shape-id" /></label>
      <label class="field">
        <span>{{ t('ontology.shapesFieldTargetKind') }}</span>
        <a-select v-model:value="form.target_kind" size="sm" data-testid="shape-target-kind">
          <a-select-option value="relation">relation</a-select-option>
          <a-select-option value="concept">concept</a-select-option>
        </a-select>
      </label>
      <label class="field"><span>target_term_id</span><a-input v-model:value="form.target_term_id" size="sm" data-testid="shape-target-term" /></label>
      <label class="field">
        <span>{{ t('ontology.shapesFieldConstraintKind') }}</span>
        <a-select v-model:value="form.constraint_kind" size="sm" data-testid="shape-constraint-kind">
          <a-select-option v-for="kind in CONSTRAINT_KINDS" :key="kind" :value="kind">{{ kind }}</a-select-option>
        </a-select>
      </label>
      <label class="field"><span>{{ t('ontology.shapesFieldConstraintJson') }}</span><a-textarea v-model:value="form.constraint_text" :rows="3" data-testid="shape-constraint-json" /></label>
      <label class="field">
        <span>{{ t('ontology.shapesFieldSeverity') }}</span>
        <a-select v-model:value="form.severity" size="sm" data-testid="shape-severity">
          <a-select-option v-for="sev in SEVERITIES" :key="sev" :value="sev">{{ sev }}</a-select-option>
        </a-select>
      </label>
      <label class="field"><span>{{ t('ontology.shapesFieldMessage') }}</span><a-input v-model:value="form.message" size="sm" data-testid="shape-message" /></label>
      <label class="field field--inline"><span>{{ t('ontology.shapesFieldEnabled') }}</span><a-checkbox v-model:checked="form.enabled" data-testid="shape-enabled" /></label>
      <div class="form-actions">
        <GlassButton size="sm" :loading="saving" data-testid="shape-create" @click="createShape">
          {{ t('common.confirm') }}
        </GlassButton>
        <GlassButton size="sm" variant="secondary" @click="showForm = false">{{ t('common.cancel') }}</GlassButton>
      </div>
    </div>

    <a-spin :spinning="loading">
      <table v-if="shapes.length" class="shapes-table" data-testid="shapes-table">
        <thead><tr><th>shape_id</th><th>{{ t('ontology.shapesThTarget') }}</th><th>{{ t('ontology.shapesThConstraint') }}</th><th>{{ t('ontology.shapesFieldSeverity') }}</th><th>{{ t('ontology.shapesFieldMessage') }}</th><th></th></tr></thead>
        <tbody>
          <tr v-for="shape in pagedShapes" :key="shape.shape_id" :data-testid="`shape-row-${shape.shape_id}`">
            <td class="mono">{{ shape.shape_id }}</td>
            <td class="mono">{{ shape.target_kind }}:{{ shape.target_term_id || '-' }}</td>
            <td class="mono">{{ shape.constraint_kind }} {{ shortJson(shape.constraint) }}</td>
            <td><a-tag :color="severityColor(shape.severity)">{{ shape.severity }}</a-tag></td>
            <td>{{ shape.message || '-' }}</td>
            <td>
              <a-button
                v-if="isAdmin"
                type="text"
                danger
                size="sm"
                :data-testid="`shape-delete-${shape.shape_id}`"
                @click="deleteShape(shape.shape_id)"
              >{{ t('common.delete') }}</a-button>
            </td>
          </tr>
        </tbody>
      </table>
      <a-pagination
        v-if="shapes.length"
        v-model:current="shapesPage"
        :page-size="20"
        :total="shapes.length"
        :show-size-changer="false"
        class="list-pagination"
      />
      <a-empty v-else-if="!loading" data-testid="shapes-empty" :description="t('ontology.shapesEmpty')" />
    </a-spin>

    <!-- U1：SHACL 运行时体检（POST /ontology/validate/shacl，只读 dry-run；
         supported=false = 环境缺 pyshacl 的诚实降级态，不当错误吞掉） -->
    <div class="shacl-panel" data-testid="shacl-panel">
      <h4 class="section-title">{{ t('ontology.shaclRunTitle') }}</h4>
      <p class="shapes-note">{{ t('ontology.shaclRunNote') }}</p>
      <div class="shacl-form">
        <a-input
          v-model:value="shaclSubject"
          class="mono"
          :placeholder="t('ontology.shaclSubjectPh')"
          data-testid="shacl-subject"
        />
        <GlassButton size="sm" :loading="shaclLoading" data-testid="shacl-run" @click="runShaclCheck">
          {{ t('ontology.shaclRunBtn') }}
        </GlassButton>
      </div>
      <div v-if="shaclError" class="inline-error" data-testid="shacl-error">{{ shaclError }}</div>
      <div v-if="shaclReport" class="shacl-result" data-testid="shacl-result">
        <a-alert
          v-if="!shaclReport.supported"
          type="warning"
          show-icon
          data-testid="shacl-unsupported"
          :message="t('ontology.shaclUnsupported')"
          :description="shaclReport.reason || ''"
        />
        <template v-else>
          <p class="shacl-verdict" data-testid="shacl-conforms">
            <a-tag :color="shaclReport.conforms ? 'green' : 'red'">
              {{ shaclReport.conforms ? t('ontology.shaclConformsTrue') : t('ontology.shaclConformsFalse') }}
            </a-tag>
            <span class="mono">mode={{ shaclReport.mode }}</span>
          </p>
          <p v-if="shaclReport.note" class="shapes-note" data-testid="shacl-note">{{ shaclReport.note }}</p>
          <template v-if="shaclReport.violations.length">
            <h5 class="shacl-violations-title">{{ t('ontology.shaclViolationsTitle', { count: shaclReport.violations.length }) }}</h5>
            <table class="shapes-table" data-testid="shacl-violations">
              <thead>
                <tr><th>severity</th><th>component</th><th>message</th><th>value</th></tr>
              </thead>
              <tbody>
                <tr v-for="(violation, index) in shaclReport.violations" :key="index" :data-testid="`shacl-violation-${index}`">
                  <td><a-tag :color="shaclSeverityColor(violation.severity)">{{ violation.severity }}</a-tag></td>
                  <td class="mono">{{ violation.component }}</td>
                  <td>{{ violation.message }}</td>
                  <td class="mono">{{ violation.value || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </template>
          <p v-else class="shapes-note" data-testid="shacl-no-violations">{{ t('ontology.shaclNoViolations') }}</p>
        </template>
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
  createOntologyShape,
  deleteOntologyShape,
  listOntologyShapes,
  validateShacl,
} from '@/api/modules/ontology'
import type { OntologyShape, ShaclValidateReport } from '@/types/ontology'
import { severityColor } from '@/utils/ontologyFormat'

const props = defineProps<{ isAdmin: boolean }>()
const { t } = useI18n()

const CONSTRAINT_KINDS = ['in', 'pattern', 'minCount', 'maxCount', 'class'] as const
const SEVERITIES = ['violation', 'warning', 'info'] as const

const shapes = ref<OntologyShape[]>([])

const shapesPage = ref(1)
const pagedShapes = computed(() => shapes.value.slice((shapesPage.value - 1) * 20, shapesPage.value * 20))
watch(() => shapes.value.length, () => { shapesPage.value = 1 })
const loading = ref(false)
const saving = ref(false)
const showForm = ref(false)

const form = reactive({
  shape_id: '',
  target_kind: 'relation' as 'relation' | 'concept',
  target_term_id: '',
  constraint_kind: 'in',
  constraint_text: '{"values": ["High", "Low"]}',
  severity: 'violation' as 'violation' | 'warning' | 'info',
  message: '',
  enabled: true,
})

function shortJson(value: Record<string, unknown>): string {
  const text = JSON.stringify(value ?? {})
  return text.length > 48 ? text.slice(0, 45) + '...' : text
}

async function reload() {
  loading.value = true
  try {
    const res = await listOntologyShapes()
    shapes.value = res.data?.items ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

async function createShape() {
  if (!form.shape_id.trim() || !form.constraint_kind) {
    message.warning(t('common.required'))
    return
  }
  let constraint: Record<string, unknown>
  try {
    constraint = JSON.parse(form.constraint_text || '{}') as Record<string, unknown>
  } catch {
    message.warning(t('ontology.invalidJson'))
    return
  }
  saving.value = true
  try {
    await createOntologyShape({
      shape_id: form.shape_id.trim(),
      target_kind: form.target_kind,
      target_term_id: form.target_term_id.trim(),
      constraint_kind: form.constraint_kind,
      constraint,
      severity: form.severity,
      message: form.message.trim(),
      enabled: form.enabled,
    })
    message.success(t('common.confirm'))
    showForm.value = false
    form.shape_id = ''
    form.target_term_id = ''
    form.message = ''
    await reload()
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

async function deleteShape(shapeId: string) {
  try {
    await deleteOntologyShape(shapeId)
    message.success(t('common.delete'))
    await reload()
  } catch {
    message.error(t('common.error'))
  }
}

// ── U1：SHACL 运行时体检（只读 dry-run；无主体=全库）─────────────────────

const shaclSubject = ref('')
const shaclLoading = ref(false)
const shaclError = ref('')
const shaclReport = ref<ShaclValidateReport | null>(null)

/** SHACL 严重度（Violation/Warning/Info）→ 既有 severityColor 三级色（小写归一）。 */
function shaclSeverityColor(severity: string): string {
  return severityColor(String(severity || '').toLowerCase())
}

async function runShaclCheck() {
  shaclLoading.value = true
  shaclError.value = ''
  shaclReport.value = null
  try {
    const subjectKey = shaclSubject.value.trim()
    const res = await validateShacl(subjectKey ? { subject_key: subjectKey } : {})
    shaclReport.value = (res.data ?? null) as ShaclValidateReport | null
  } catch (err) {
    // 失败显式暴露（不吞）：优先回显后端 detail 原话
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    shaclError.value = typeof detail === 'string' && detail ? detail : t('common.error')
  } finally {
    shaclLoading.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.shapes-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.section-title {
  margin: 0 0 4px;
  font-size: 13px;
  font-weight: 600;
}
.shapes-note {
  margin: 0;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.admin-note {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.shape-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 12px 0;
  padding: 10px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.25));
  border-radius: 8px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}
.field--inline {
  flex-direction: row;
  align-items: center;
}
.form-actions {
  display: flex;
  gap: 8px;
}
.list-pagination {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}
.shapes-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 10px;
  font-size: 12px;
}
.shapes-table th,
.shapes-table td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--nr-border, rgba(128, 128, 128, 0.18));
}
.mono {
  font-family: var(--nr-font-mono, monospace);
}
.shacl-panel {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--nr-border, rgba(128, 128, 128, 0.18));
}
.shacl-form {
  display: flex;
  gap: 8px;
  margin: 8px 0;
}
.shacl-form .ant-input-wrapper,
.shacl-form input {
  flex: 1;
}
.shacl-result {
  margin-top: 6px;
}
.shacl-violations-title {
  margin: 8px 0 4px;
  font-size: 12px;
  font-weight: 600;
}
.shacl-verdict {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 6px 0;
}
.inline-error {
  margin: 6px 0;
  color: var(--nr-error, #ef4444);
  font-size: 12px;
}
</style>
