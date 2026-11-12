<template>
  <div class="runtime-section" data-testid="studio-runtime">
    <a-alert
      type="info"
      show-icon
      data-testid="runtime-note"
      :message="t('ontology.runtimeNoPersistNote')"
    />
    <a-tabs v-model:active-key="activeTab" class="runtime-tabs">
      <!-- 函数 tab（W2） -->
      <a-tab-pane key="functions" :tab="t('ontology.runtimeFunctionsTitle')">
        <table class="runtime-table" data-testid="functions-table">
          <thead>
            <tr>
              <th>{{ t('ontology.runtimeFunctionId') }}</th>
              <th>{{ t('ontology.runtimeFunctionExpr') }}</th>
              <th>{{ t('ontology.runtimeFunctionOutput') }}</th>
              <th>{{ t('ontology.runtimeFunctionMat') }}</th>
              <th>{{ t('ontology.ruleEnabled') }}</th>
              <th v-if="isAdmin">{{ t('common.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="fn in functions" :key="fn.function_id">
              <td class="mono">{{ fn.function_id }}</td>
              <td class="mono expr">{{ fn.expr_text }}</td>
              <td class="mono">{{ fn.output_predicate }}</td>
              <td>
                <a-tag :color="fn.materialization === 'enforce' ? 'green' : 'default'">
                  {{ fn.materialization }}
                </a-tag>
              </td>
              <td>{{ fn.enabled ? t('common.yes') : t('common.no') }}</td>
              <td v-if="isAdmin">
                <GlassButton size="sm" variant="secondary" data-testid="fn-delete"
                             @click="removeFunction(fn.function_id)">
                  {{ t('common.delete') }}
                </GlassButton>
              </td>
            </tr>
            <tr v-if="!functions.length">
              <td colspan="6"><a-empty :description="t('ontology.runtimeFunctionEmpty')" /></td>
            </tr>
          </tbody>
        </table>

        <template v-if="isAdmin">
          <h4 class="section-title">{{ t('ontology.runtimeFunctionRegister') }}</h4>
          <div class="register-form" data-testid="fn-register">
            <a-input v-model:value="fnForm.function_id" class="mono"
                     :placeholder="t('ontology.runtimeFunctionId')" data-testid="fn-id" />
            <a-input v-model:value="fnForm.expr_text" class="mono wide"
                     :placeholder="t('ontology.runtimeFunctionExprPh')" data-testid="fn-expr" />
            <a-input v-model:value="fnForm.output_predicate" class="mono"
                     :placeholder="t('ontology.runtimeFunctionOutputPh')" data-testid="fn-output" />
            <GlassButton size="sm" data-testid="fn-submit" @click="submitFunction">
              {{ t('common.save') }}
            </GlassButton>
          </div>
          <div v-if="fnError" class="inline-error" data-testid="fn-error">{{ fnError }}</div>
        </template>

        <h4 class="section-title">{{ t('ontology.runtimeComputeTitle') }}</h4>
        <div class="register-form" data-testid="fn-compute">
          <a-input v-model:value="computeForm.function_id" class="mono"
                   :placeholder="t('ontology.runtimeFunctionId')" data-testid="compute-id" />
          <a-input v-model:value="computeForm.subject" class="mono"
                   :placeholder="t('ontology.runtimeComputeSubject')" data-testid="compute-subject" />
          <GlassButton size="sm" data-testid="compute-run" @click="runCompute">
            {{ t('ontology.runtimeComputeRun') }}
          </GlassButton>
        </div>
        <div v-if="computeError" class="inline-error" data-testid="compute-error">{{ computeError }}</div>
        <div v-if="computeResult" class="compute-readout" data-testid="compute-readout">
          <div class="mono">{{ t('ontology.runtimeComputeValue') }}: {{ computeResult.value ?? '-' }}</div>
          <div class="mono expr">{{ computeResult.expr_text }}</div>
          <div class="mono">{{ t('ontology.runtimeComputeInputs') }}: {{ inputsText }}</div>
        </div>
      </a-tab-pane>

      <!-- 动作 tab（W4） -->
      <a-tab-pane key="actions" :tab="t('ontology.runtimeActionsTitle')">
        <table class="runtime-table" data-testid="actions-table">
          <thead>
            <tr>
              <th>{{ t('ontology.runtimeActionId') }}</th>
              <th>{{ t('ontology.runtimeActionTool') }}</th>
              <th>{{ t('ontology.runtimeActionPre') }}</th>
              <th>{{ t('ontology.runtimeActionImpact') }}</th>
              <th>{{ t('ontology.runtimeActionState') }}</th>
              <th>{{ t('ontology.runtimeFunctionMat') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="action in actions" :key="action.action_id">
              <td class="mono">{{ action.action_id }}</td>
              <td class="mono">{{ action.bound_tool }}</td>
              <td class="mono expr">{{ preconditionText(action) }}</td>
              <td class="mono">{{ action.impact.join(', ') || '-' }}</td>
              <td class="mono expr">{{ stateChangeText(action) }}</td>
              <td>
                <a-tag :color="action.risk_tier === 'high' ? 'red' : action.risk_tier === 'medium' ? 'orange' : 'default'">
                  {{ action.risk_tier }}
                </a-tag>
              </td>
            </tr>
            <tr v-if="!actions.length">
              <td colspan="6"><a-empty :description="t('ontology.runtimeActionEmpty')" /></td>
            </tr>
          </tbody>
        </table>
        <template v-if="isAdmin">
          <h4 class="section-title">{{ t('ontology.runtimeActionRegister') }}</h4>
          <div class="register-form" data-testid="action-register">
            <a-input v-model:value="actionForm.action_id" class="mono"
                     :placeholder="t('ontology.runtimeActionId')" data-testid="action-id" />
            <a-input v-model:value="actionForm.bound_tool" class="mono"
                     :placeholder="t('ontology.runtimeActionTool')" data-testid="action-tool" />
            <GlassButton size="sm" data-testid="action-submit" @click="submitAction">
              {{ t('common.save') }}
            </GlassButton>
          </div>
          <div v-if="actionError" class="inline-error" data-testid="action-error">{{ actionError }}</div>
        </template>
      </a-tab-pane>

      <!-- 状态机 tab（W3） -->
      <a-tab-pane key="states" :tab="t('ontology.runtimeStatesTitle')">
        <table class="runtime-table" data-testid="states-table">
          <thead>
            <tr>
              <th>{{ t('ontology.runtimeStateTerm') }}</th>
              <th>{{ t('ontology.runtimeStateInit') }}</th>
              <th>{{ t('ontology.runtimeStateTransitions') }}</th>
              <th>{{ t('ontology.ruleEnabled') }}</th>
              <th v-if="isAdmin">{{ t('common.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="machine in machines" :key="machine.term_id">
              <td class="mono">{{ machine.term_id }}</td>
              <td class="mono">{{ machine.initial_state }}</td>
              <td class="mono expr">
                {{ machine.transitions.map((tr) => `${tr.from}→${tr.to}`).join('; ') }}
              </td>
              <td>{{ machine.enabled ? t('common.yes') : t('common.no') }}</td>
              <td v-if="isAdmin">
                <GlassButton size="sm" variant="secondary" data-testid="machine-delete"
                             @click="removeMachine(machine.term_id)">
                  {{ t('common.delete') }}
                </GlassButton>
              </td>
            </tr>
            <tr v-if="!machines.length">
              <td colspan="5"><a-empty :description="t('ontology.runtimeStateEmpty')" /></td>
            </tr>
          </tbody>
        </table>

        <template v-if="isAdmin">
          <h4 class="section-title">{{ t('ontology.runtimeStateRegister') }}</h4>
          <div class="register-form" data-testid="machine-register">
            <a-input v-model:value="machineForm.term_id" class="mono"
                     :placeholder="t('ontology.runtimeStateTerm')" data-testid="machine-term" />
            <a-input v-model:value="machineForm.states_text" class="mono wide"
                     :placeholder="t('ontology.runtimeStateStatesPh')" data-testid="machine-states" />
            <a-input v-model:value="machineForm.transitions_text" class="mono wide"
                     :placeholder="t('ontology.runtimeStateTransPh')" data-testid="machine-transitions" />
            <a-input v-model:value="machineForm.initial_state" class="mono"
                     :placeholder="t('ontology.runtimeStateInitPh')" data-testid="machine-initial" />
            <GlassButton size="sm" data-testid="machine-submit" @click="submitMachine">
              {{ t('common.save') }}
            </GlassButton>
          </div>
          <div v-if="machineError" class="inline-error" data-testid="machine-error">{{ machineError }}</div>
        </template>
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import GlassButton from '@/components/GlassButton.vue'
import {
  computeOntologyFunction,
  createOntologyFunction,
  createOntologyStateMachine,
  deleteOntologyFunction,
  deleteOntologyStateMachine,
  listOntologyFunctions,
  listOntologyStateMachines,
} from '@/api/modules/ontology'
import type {
  OntologyActionRow,
  OntologyComputeResult,
  OntologyFunctionRow,
  OntologyStateMachineRow,
} from '@/types/ontology'
import { createOntologyAction, listOntologyActions } from '@/api/modules/ontology' 
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const authStore = useAuthStore()

const isAdmin = computed(() => {
  const user = authStore.user as { role?: string } | null | undefined
  return user?.role === 'admin'
})

const activeTab = ref<'functions' | 'actions' | 'states'>('functions')
const functions = ref<OntologyFunctionRow[]>([])
const machines = ref<OntologyStateMachineRow[]>([])
const actions = ref<OntologyActionRow[]>([])
const actionForm = ref({ action_id: '', bound_tool: '' })
const actionError = ref('')

const fnForm = ref({ function_id: '', expr_text: '', output_predicate: '' })
const fnError = ref('')
const computeForm = ref({ function_id: '', subject: '' })
const computeError = ref('')
const computeResult = ref<OntologyComputeResult | null>(null)

const machineForm = ref({ term_id: '', states_text: '', transitions_text: '', initial_state: '' })
const machineError = ref('')

const inputsText = computed(() => {
  const inputs = computeResult.value?.inputs
  if (!inputs || typeof inputs !== 'object') return ''
  return Object.entries(inputs as Record<string, unknown>)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(', ')
})

async function reload() {
  fnError.value = ''
  try {
    const res = await listOntologyFunctions()
    functions.value = res.data ?? []
  } catch {
    fnError.value = t('ontology.runtimeLoadError')
  }
  try {
    const res = await listOntologyStateMachines()
    machines.value = res.data ?? []
  } catch {
    machineError.value = t('ontology.runtimeLoadError')
  }
  try {
    const res = await listOntologyActions()
    actions.value = res.data ?? []
  } catch {
    actionError.value = t('ontology.runtimeLoadError')
  }
}

function preconditionText(action: OntologyActionRow): string {
  const facts = (action.precondition?.facts ?? []) as Array<Record<string, unknown>>
  const parts = facts.map((f) => `${String(f.predicate)} ${String(f.op ?? 'exists')}`)
  const expr = String(action.precondition?.expr ?? '')
  if (expr) parts.push(`expr: ${expr}`)
  return parts.join('; ') || '-'
}

function stateChangeText(action: OntologyActionRow): string {
  const sc = action.state_change ?? {}
  if (!sc.subjectParam && !sc.toState) return '-'
  return `${String(sc.subjectParam)}→${String(sc.toState)}`
}

async function submitAction() {
  actionError.value = ''
  try {
    await createOntologyAction({
      action_id: actionForm.value.action_id.trim(),
      bound_tool: actionForm.value.bound_tool.trim(),
    })
    actionForm.value = { action_id: '', bound_tool: '' }
    await reload()
  } catch (err) {
    actionError.value = extractError(err) || t('ontology.runtimeLoadError')
  }
}

async function submitFunction() {
  fnError.value = ''
  try {
    await createOntologyFunction({
      function_id: fnForm.value.function_id.trim(),
      expr_text: fnForm.value.expr_text.trim(),
      output_predicate: fnForm.value.output_predicate.trim(),
    })
    fnForm.value = { function_id: '', expr_text: '', output_predicate: '' }
    await reload()
  } catch (err) {
    // 登记即编译：白名单外/越界谓词的后端 400 原样回显（诚实形态）
    fnError.value = extractError(err) || t('ontology.runtimeLoadError')
  }
}

async function removeFunction(functionId: string) {
  fnError.value = ''
  try {
    await deleteOntologyFunction(functionId)
    await reload()
  } catch (err) {
    fnError.value = extractError(err) || t('ontology.runtimeLoadError')
  }
}

async function runCompute() {
  computeError.value = ''
  computeResult.value = null
  try {
    const res = await computeOntologyFunction({
      function_id: computeForm.value.function_id.trim(),
      subject: computeForm.value.subject.trim(),
    })
    computeResult.value = res.data ?? null
  } catch (err) {
    computeError.value = extractError(err) || t('ontology.runtimeLoadError')
  }
}

async function submitMachine() {
  machineError.value = ''
  try {
    const states = JSON.parse(machineForm.value.states_text) as unknown
    const transitions = JSON.parse(machineForm.value.transitions_text) as unknown
    await createOntologyStateMachine({
      term_id: machineForm.value.term_id.trim(),
      states: states as string[],
      transitions: transitions as Array<{ from: string; to: string }>,
      initial_state: machineForm.value.initial_state.trim(),
    })
    machineForm.value = { term_id: '', states_text: '', transitions_text: '', initial_state: '' }
    await reload()
  } catch (err) {
    machineError.value = extractError(err) || t('ontology.runtimeLoadError')
  }
}

async function removeMachine(termId: string) {
  machineError.value = ''
  try {
    await deleteOntologyStateMachine(termId)
    await reload()
  } catch (err) {
    machineError.value = extractError(err) || t('ontology.runtimeLoadError')
  }
}

function extractError(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof detail === 'string' && detail ? detail : ''
}

onMounted(reload)

// 测试面：分区行为断言经暴露方法驱动（数据仍走 api 单源）
defineExpose({ submitFunction, runCompute })
</script>

<style scoped>
.section-title {
  margin: 14px 0 6px;
  font-size: 13px;
  font-weight: 600;
}
.runtime-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.runtime-table th,
.runtime-table td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
}
.mono {
  font-family: var(--nr-font-mono, monospace);
}
.expr {
  max-width: 360px;
  overflow-wrap: anywhere;
}
.register-form {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.register-form .a-input {
  min-width: 180px;
}
.register-form .wide {
  min-width: 280px;
}
.inline-error {
  color: var(--nr-error, #ef4444);
  font-size: 12px;
  margin: 4px 0;
}
.compute-readout {
  font-size: 12px;
  padding: 8px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
  border-radius: 6px;
}
</style>
