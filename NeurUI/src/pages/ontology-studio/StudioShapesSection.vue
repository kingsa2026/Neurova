<template>
  <div class="shapes-section" data-testid="studio-shapes">
    <div class="shapes-head">
      <div>
        <h4 class="section-title">{{ t('ontology.shapesTitle') }}</h4>
        <p class="shapes-note">
          JSON DSL: in / pattern / minCount / maxCount / class. Builtin six
          constraints stay in the single evaluator; duplicate dimensions are rejected.
        </p>
      </div>
      <GlassButton
        v-if="isAdmin"
        size="sm"
        data-testid="shapes-new"
        @click="showForm = !showForm"
      >
        New shape
      </GlassButton>
    </div>

    <p v-if="!isAdmin" class="admin-note" data-testid="shapes-admin-note">Admin only</p>

    <div v-if="isAdmin && showForm" class="shape-form" data-testid="shape-form">
      <label class="field"><span>shape_id</span><a-input v-model:value="form.shape_id" size="sm" data-testid="shape-id" /></label>
      <label class="field">
        <span>target_kind</span>
        <a-select v-model:value="form.target_kind" size="sm" data-testid="shape-target-kind">
          <a-select-option value="relation">relation</a-select-option>
          <a-select-option value="concept">concept</a-select-option>
        </a-select>
      </label>
      <label class="field"><span>target_term_id</span><a-input v-model:value="form.target_term_id" size="sm" data-testid="shape-target-term" /></label>
      <label class="field">
        <span>constraint_kind</span>
        <a-select v-model:value="form.constraint_kind" size="sm" data-testid="shape-constraint-kind">
          <a-select-option v-for="kind in CONSTRAINT_KINDS" :key="kind" :value="kind">{{ kind }}</a-select-option>
        </a-select>
      </label>
      <label class="field"><span>constraint JSON</span><a-textarea v-model:value="form.constraint_text" :rows="3" data-testid="shape-constraint-json" /></label>
      <label class="field">
        <span>severity</span>
        <a-select v-model:value="form.severity" size="sm" data-testid="shape-severity">
          <a-select-option v-for="sev in SEVERITIES" :key="sev" :value="sev">{{ sev }}</a-select-option>
        </a-select>
      </label>
      <label class="field"><span>message</span><a-input v-model:value="form.message" size="sm" data-testid="shape-message" /></label>
      <label class="field field--inline"><span>enabled</span><a-checkbox v-model:checked="form.enabled" data-testid="shape-enabled" /></label>
      <div class="form-actions">
        <GlassButton size="sm" :loading="saving" data-testid="shape-create" @click="createShape">
          {{ t('common.confirm') }}
        </GlassButton>
        <GlassButton size="sm" variant="secondary" @click="showForm = false">{{ t('common.cancel') }}</GlassButton>
      </div>
    </div>

    <a-spin :spinning="loading">
      <table v-if="shapes.length" class="shapes-table" data-testid="shapes-table">
        <thead><tr><th>shape_id</th><th>target</th><th>constraint</th><th>severity</th><th>message</th><th></th></tr></thead>
        <tbody>
          <tr v-for="shape in shapes" :key="shape.shape_id" :data-testid="`shape-row-${shape.shape_id}`">
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
      <a-empty v-else-if="!loading" data-testid="shapes-empty" description="No shapes" />
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  createOntologyShape,
  deleteOntologyShape,
  listOntologyShapes,
} from '@/api/modules/ontology'
import type { OntologyShape } from '@/types/ontology'
import { severityColor } from '@/utils/ontologyFormat'

const props = defineProps<{ isAdmin: boolean }>()
const { t } = useI18n()

const CONSTRAINT_KINDS = ['in', 'pattern', 'minCount', 'maxCount', 'class'] as const
const SEVERITIES = ['violation', 'warning', 'info'] as const

const shapes = ref<OntologyShape[]>([])
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
</style>
