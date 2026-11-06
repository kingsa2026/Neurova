<template>
  <div class="enterprise-sources-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('ontology.entTitle') }}</h2>
        <p class="page-subtitle">{{ t('ontology.entSubtitle') }}</p>
      </div>
    </div>

    <!-- 诚实性（§15.4）：描述符提交是真调用；「能不能连」仍由后端两态如实回显 -->
    <GlassPanel class="panel">
      <div class="panel-head">
        <span class="panel-title" data-testid="ent-list-title">{{ t('ontology.entListTitle') }}</span>
        <a-tag color="warning" data-testid="ent-reserved-tag">{{ t('ontology.entReservedTitle') }}</a-tag>
      </div>
      <p class="honest-note" data-testid="ent-reserved-note">{{ t('ontology.entReservedNote') }}</p>

      <p v-if="listError" class="honest-note honest-note--error" data-testid="ent-list-error">
        {{ t('ontology.entListFailed') }}
      </p>
      <a-empty v-else-if="!sources.length" :description="t('ontology.entListEmpty')" data-testid="ent-list-empty" />
      <table v-else class="source-table" data-testid="ent-list">
        <thead>
          <tr>
            <th>{{ t('ontology.entSourceId') }}</th>
            <th>{{ t('ontology.entSourceType') }}</th>
            <th>{{ t('ontology.entEnabled') }}</th>
            <th>{{ t('ontology.entCursorField') }}</th>
            <th>adapter</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in sources" :key="row.source_id" :data-testid="`ent-row-${row.source_id}`">
            <td class="mono">{{ row.source_id }}</td>
            <td class="mono">{{ row.descriptor.sourceType || '-' }}</td>
            <td>
              <a-tag :color="row.enabled ? 'success' : 'default'" data-testid="ent-enabled-tag">
                {{ row.enabled ? 'on' : 'off' }}
              </a-tag>
            </td>
            <td class="mono">{{ row.cursor || '-' }}</td>
            <td>
              <a-tag
                :color="row.adapter_registered ? 'success' : 'warning'"
                data-testid="ent-adapter-tag"
              >
                {{ row.adapter_registered
                  ? t('ontology.entAdapterRegistered')
                  : t('ontology.entAdapterReserved') }}
              </a-tag>
            </td>
          </tr>
        </tbody>
      </table>
    </GlassPanel>

    <GlassPanel class="panel">
      <div class="panel-head">
        <span class="panel-title">{{ t('ontology.entFakeAdapterTitle') }}</span>
      </div>
      <p class="honest-note" data-testid="ent-fake-adapter-note">{{ t('ontology.entFakeAdapterNote') }}</p>
    </GlassPanel>

    <!-- 描述符编辑器：提交走真 REST（编译期校验在服务器单点），非法描述符整条拒并显式回因 -->
    <GlassPanel class="panel">
      <div class="panel-head">
        <span class="panel-title" data-testid="ent-descriptor-title">{{ t('ontology.entDescriptorTitle') }}</span>
        <span v-if="!isAdmin" class="admin-note" data-testid="ent-admin-note">
          {{ t('ontology.entAdminOnly') }}
        </span>
      </div>
      <div class="descriptor-grid">
        <label class="field">
          <span>{{ t('ontology.entSourceId') }}</span>
          <a-input v-model:value="form.sourceId" size="sm" data-testid="ent-source-id" />
        </label>
        <label class="field">
          <span>{{ t('ontology.entSourceType') }}</span>
          <a-select v-model:value="form.sourceType" size="sm" data-testid="ent-source-type">
            <a-select-option value="sql">sql</a-select-option>
            <a-select-option value="erp_api">erp_api</a-select-option>
            <a-select-option value="event_stream">event_stream</a-select-option>
          </a-select>
        </label>
        <label class="field">
          <span>{{ t('ontology.entColumns') }}</span>
          <a-input
            v-model:value="form.columns"
            size="sm"
            data-testid="ent-columns"
            placeholder="order_id, risk_level"
          />
        </label>
        <label class="field">
          <span>{{ t('ontology.entSubject') }}</span>
          <a-input
            v-model:value="form.subject"
            size="sm"
            data-testid="ent-subject"
            placeholder="orders:{order_id}"
          />
        </label>
        <label class="field">
          <span>{{ t('ontology.entPredicate') }}</span>
          <a-input
            v-model:value="form.predicate"
            size="sm"
            data-testid="ent-predicate"
            placeholder="hasRiskLevel"
          />
        </label>
        <label class="field">
          <span>{{ t('ontology.entObjectKind') }}</span>
          <a-select v-model:value="form.objectKind" size="sm" data-testid="ent-object-kind">
            <a-select-option value="column">column</a-select-option>
            <a-select-option value="template">template</a-select-option>
            <a-select-option value="term">term</a-select-option>
            <a-select-option value="literal">literal</a-select-option>
          </a-select>
        </label>
        <label class="field">
          <span>{{ t('ontology.entObjectValue') }}</span>
          <a-input v-model:value="form.objectValue" size="sm" data-testid="ent-object-value" />
        </label>
        <label class="field">
          <span>{{ t('ontology.entQualifiers') }}</span>
          <a-input v-model:value="form.qualifiers" size="sm" data-testid="ent-qualifiers" placeholder="{}" />
        </label>
        <label class="field">
          <span>{{ t('ontology.entValidFrom') }}</span>
          <a-input
            v-model:value="form.validFrom"
            size="sm"
            data-testid="ent-valid-from"
            placeholder="updated_at"
          />
        </label>
        <label class="field">
          <span>{{ t('ontology.entValidUntil') }}</span>
          <a-input v-model:value="form.validUntil" size="sm" data-testid="ent-valid-until" />
        </label>
        <label class="field field--check">
          <a-checkbox v-model:checked="form.enabled" :disabled="!isAdmin" data-testid="ent-enabled">
            {{ t('ontology.entEnabled') }}
          </a-checkbox>
        </label>
      </div>
      <p v-if="submitError" class="honest-note honest-note--error" data-testid="ent-submit-error">
        {{ submitError }}
      </p>
      <div class="form-actions">
        <GlassButton
          size="sm"
          :loading="submitting"
          :disabled="!isAdmin"
          data-testid="ent-submit"
          @click="submitDescriptor"
        >
          {{ t('ontology.entSubmitBtn') }}
        </GlassButton>
        <!-- 真实连接按钮：禁用并给出原因（描述符落库 ≠ 源已接通） -->
        <a-tooltip :title="t('ontology.entConnectDisabled')">
          <GlassButton size="sm" disabled data-testid="ent-connect-disabled">
            {{ t('ontology.entConnectBtn') }}
          </GlassButton>
        </a-tooltip>
      </div>
    </GlassPanel>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAuthStore } from '@/stores/auth'
import { listEnterpriseSources, submitEnterpriseSource } from '@/api/modules/ontology'
import type { EnterpriseDescriptor, EnterpriseSourceConfig } from '@/types/ontology'
import { splitList } from '@/utils/ontologyFormat'

const { t } = useI18n()
const authStore = useAuthStore()

const isAdmin = computed(() => {
  const user = authStore.user as { role?: string } | null | undefined
  return user?.role === 'admin'
})

const sources = ref<EnterpriseSourceConfig[]>([])
const listError = ref(false)
const submitting = ref(false)
const submitError = ref('')

const form = reactive({
  sourceId: '',
  sourceType: 'sql',
  columns: '',
  subject: '',
  predicate: '',
  objectKind: 'column',
  objectValue: '',
  qualifiers: '{}',
  validFrom: '',
  validUntil: '',
  enabled: false,
})

/** 表单项 → 后端描述符形状：编译期判据住在 validateDescriptor 单点，前端不抄第二套规则。 */
function buildDescriptor(): EnterpriseDescriptor {
  const kind = form.objectKind as EnterpriseDescriptor['object']['kind']
  const value = form.objectValue.trim()
  const object: EnterpriseDescriptor['object'] = { kind }
  if (kind === 'column') object.column = value
  else if (kind === 'template') object.template = value
  else if (kind === 'term') object.termId = value
  else object.value = value

  const body: EnterpriseDescriptor = {
    sourceType: form.sourceType,
    columns: splitList(form.columns),
    subject: { template: form.subject.trim() },
    predicate: { termId: form.predicate.trim() },
    object,
    qualifiers: JSON.parse(form.qualifiers.trim() || '{}') as Record<string, string>,
  }
  if (form.validFrom.trim()) body.validFrom = form.validFrom.trim()
  if (form.validUntil.trim()) body.validUntil = form.validUntil.trim()
  return body
}

async function loadSources() {
  listError.value = false
  try {
    const res = await listEnterpriseSources()
    sources.value = res.data?.items ?? []
  } catch {
    listError.value = true
  }
}

async function submitDescriptor() {
  if (!form.sourceId.trim()) {
    submitError.value = t('common.required')
    return
  }
  submitting.value = true
  submitError.value = ''
  try {
    await submitEnterpriseSource({
      source_id: form.sourceId.trim(),
      descriptor: buildDescriptor(),
      enabled: form.enabled,
    })
    message.success(t('ontology.entSubmitted'))
    await loadSources()
  } catch (error) {
    // 400 的拒因是后端编译期校验原话（带定位），显式露出不降级成 warning
    submitError.value = rejectReason(error)
  } finally {
    submitting.value = false
  }
}

function rejectReason(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' && detail ? detail : t('common.error')
}

onMounted(loadSources)
</script>

<style scoped>
.enterprise-sources-page {
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
.panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.panel-title {
  font-weight: 600;
  font-size: 14px;
}
.honest-note {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.honest-note--error {
  color: var(--nr-error);
}
.admin-note {
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.source-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.source-table th,
.source-table td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
}
.mono {
  font-family: var(--nr-font-mono, monospace);
}
.descriptor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 8px 12px;
  margin-bottom: 12px;
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
.form-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
</style>
