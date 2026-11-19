<template>
  <div class="neuacp-member-form">
    <a-form layout="vertical" class="neuacp-form">
      <a-form-item :label="t('neuacp.toolType')" required>
        <a-select
          class="neuacp-tool-select"
          :value="form.tool"
          :placeholder="t('neuacp.toolType')"
          :loading="catalogLoading"
          @change="handleToolChange"
        >
          <a-select-option
            v-for="item in catalog"
            :key="item.tool"
            :value="item.tool"
            :disabled="!!item.disabled"
          >
            <span class="tool-option">
              <span class="tool-name">{{ item.tool }}</span>
              <span class="tool-kind">{{ toolKindLabel(item) }}</span>
              <span v-if="item.requires_node" class="tool-chip tool-node">{{ t('neuacp.requiresNode') }}</span>
              <span v-if="item.installed" class="tool-chip tool-installed">{{ t('neuacp.installed') }}</span>
              <template v-else>
                <span class="tool-chip tool-hint">{{ t('neuacp.notInstalled') }}</span>
                <span v-if="item.install_hint" class="tool-hint-text">{{ t('neuacp.installHint', { hint: item.install_hint }) }}</span>
              </template>
            </span>
          </a-select-option>
        </a-select>
        <div v-if="catalogError" class="field-error">{{ t('neuacp.catalogLoadFailed') }}</div>
        <div v-else-if="installHintText" class="field-hint">{{ installHintText }}</div>
      </a-form-item>

      <div class="field-row">
        <a-form-item :label="t('neuacp.memberName')" required>
          <a-input v-model:value="form.name" :placeholder="t('neuacp.memberName')" />
        </a-form-item>
        <a-form-item :label="t('neuacp.role')">
          <a-select v-model:value="form.role">
            <a-select-option value="coder">{{ t('neuacp.roleCoder') }}</a-select-option>
            <a-select-option value="reviewer">{{ t('neuacp.roleReviewer') }}</a-select-option>
            <a-select-option value="member">{{ t('neuacp.roleMember') }}</a-select-option>
          </a-select>
        </a-form-item>
      </div>

      <a-form-item :label="t('neuacp.dutyPrompt')">
        <a-textarea v-model:value="form.prompt" :rows="3" :placeholder="t('neuacp.dutyPrompt')" />
      </a-form-item>

      <a-form-item :label="t('neuacp.cwd')" required>
        <a-input v-model:value="form.cwd" :placeholder="t('neuacp.cwd')" />
        <div class="field-hint">{{ t('neuacp.cwdHint') }}</div>
      </a-form-item>

      <a-form-item :label="t('neuacp.command')" required>
        <a-input v-model:value="form.command" :placeholder="commandPlaceholder" />
        <div class="field-hint">{{ t('neuacp.commandHint') }}</div>
      </a-form-item>

      <div class="field-row">
        <a-form-item :label="t('neuacp.transport')">
          <a-select v-model:value="form.transport">
            <a-select-option value="stdio">{{ t('neuacp.transportStdio') }}</a-select-option>
            <a-select-option value="ssh">{{ t('neuacp.transportSsh') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('neuacp.permissionMode')">
          <a-select :value="form.permissionMode" @change="onPermissionModeChange">
            <a-select-option value="chain">{{ t('neuacp.permissionChain') }}</a-select-option>
            <a-select-option value="auto" :disabled="!isAdmin">{{ t('neuacp.permissionAuto') }}</a-select-option>
          </a-select>
        </a-form-item>
      </div>

      <template v-if="form.transport === 'ssh'">
        <div class="field-row">
          <a-form-item :label="t('neuacp.sshHost')">
            <a-input v-model:value="form.sshHost" :placeholder="t('neuacp.sshHost')" />
          </a-form-item>
          <a-form-item :label="t('neuacp.sshPort')">
            <a-input v-model:value="form.sshPort" :placeholder="t('neuacp.sshPort')" />
          </a-form-item>
        </div>
        <div class="field-row">
          <a-form-item :label="t('neuacp.sshUser')">
            <a-input v-model:value="form.sshUser" :placeholder="t('neuacp.sshUser')" />
          </a-form-item>
          <a-form-item :label="t('neuacp.sshKeyRef')">
            <a-input v-model:value="form.sshKeyRef" :placeholder="t('neuacp.sshKeyRef')" />
          </a-form-item>
        </div>
      </template>

      <a-form-item :label="t('neuacp.envKeys')">
        <a-select
          v-model:value="form.envKeys"
          mode="tags"
          class="neuacp-envkeys"
          :placeholder="t('neuacp.envKeys')"
          :open="false"
        />
        <div class="field-hint">{{ t('neuacp.envKeysHint') }}</div>
      </a-form-item>

      <div class="test-connection">
        <GlassButton variant="secondary" size="sm" :loading="testing" @click="handleTestConnection">
          {{ testing ? t('neuacp.testing') : t('neuacp.testConnection') }}
        </GlassButton>
        <div
          v-if="testResult"
          class="test-result"
          :class="testResult.ok ? 'is-ok' : 'is-fail'"
        >
          <template v-if="testResult.ok">
            <span>{{ t('neuacp.testOk') }}</span>
            <span v-if="testResult.protocolVersion"> · {{ t('neuacp.protocolVersion') }}: {{ testResult.protocolVersion }}</span>
            <span v-if="capabilitySummary"> · {{ t('neuacp.serverCapabilities') }}: {{ capabilitySummary }}</span>
          </template>
          <template v-else>
            <span>{{ t('neuacp.testFailed') }}: {{ testResult.error }}</span>
          </template>
        </div>
      </div>

      <div class="form-actions">
        <GlassButton variant="primary" size="sm" :loading="submitting" @click="handleSubmit">
          {{ t('collab.addMember') }}
        </GlassButton>
        <GlassButton variant="ghost" size="sm" @click="emit('cancel')">{{ t('common.cancel') }}</GlassButton>
      </div>
    </a-form>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message, Modal } from 'ant-design-vue'
import { addTeamMembers } from '@/api/modules/teams'
import { fetchNeuacpCatalog, testNeuacpConnection } from '@/api/modules/neuacp'
import { useAuthStore } from '@/stores/auth'
import GlassButton from '@/components/GlassButton.vue'
import type {
  NeuacpCatalogItem,
  NeuacpExecutorSpec,
  NeuacpTestResult,
  TeamMemberAddBody,
} from '@/types/agent'

const props = defineProps<{ teamId: string }>()

const emit = defineEmits<{
  (e: 'submitted'): void
  (e: 'cancel'): void
}>()

const { t } = useI18n()
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')

const catalog = ref<NeuacpCatalogItem[]>([])
const catalogLoading = ref(false)
const catalogError = ref(false)
const testing = ref(false)
const submitting = ref(false)
const testResult = ref<NeuacpTestResult | null>(null)

const form = reactive({
  tool: '',
  name: '',
  role: 'coder',
  prompt: '',
  cwd: '',
  command: '',
  transport: 'stdio' as 'stdio' | 'ssh',
  sshHost: '',
  sshPort: '22',
  sshUser: '',
  sshKeyRef: '',
  envKeys: [] as string[],
  permissionMode: 'chain' as 'chain' | 'auto',
})

const selectedCatalog = computed(() => catalog.value.find((item) => item.tool === form.tool))

const commandPlaceholder = computed(() => {
  const cmd = selectedCatalog.value?.command
  return cmd && cmd.length ? cmd.join(' ') : t('neuacp.command')
})

const installHintText = computed(() => {
  const hint = selectedCatalog.value?.install_hint
  return hint ? t('neuacp.installHint', { hint }) : ''
})

const capabilitySummary = computed(() => {
  const caps = testResult.value?.serverCapabilities
  if (!caps || typeof caps !== 'object') return ''
  return Object.keys(caps).join(', ')
})

/** 目录项标注：插件形态 / npx 适配器 / ACP 原生（依据 catalog 契约字段推导）。 */
function toolKindLabel(item: NeuacpCatalogItem): string {
  if (item.kind === 'plugin') return t('neuacp.kindPlugin')
  const first = (item.command?.[0] ?? '').toString().toLowerCase()
  return first === 'npx' ? t('neuacp.toolAdapter') : t('neuacp.toolNative')
}

function parseCommand(text: string): string[] {
  return String(text || '').trim().split(/\s+/).filter(Boolean)
}

function handleToolChange(tool: string) {
  form.tool = String(tool ?? '')
  const item = catalog.value.find((entry) => entry.tool === form.tool)
  // 启动命令预填 catalog 默认值，允许覆盖（单一事实源：目录给默认，名册给生效值）
  form.command = item?.command?.length ? item.command.join(' ') : form.command
}

function onPermissionModeChange(value: unknown) {
  const next = String(value ?? 'chain')
  if (next === form.permissionMode) return
  if (next === 'auto') {
    // D4 裁定：auto 仅 admin，且选中需二次确认
    if (!isAdmin.value) {
      form.permissionMode = 'chain'
      message.warning(t('neuacp.externalAdminOnly'))
      return
    }
    Modal.confirm({
      title: t('neuacp.autoConfirmTitle'),
      content: t('neuacp.autoConfirmContent'),
      okText: t('common.confirm'),
      cancelText: t('common.cancel'),
      onOk: () => { form.permissionMode = 'auto' },
      onCancel: () => { form.permissionMode = 'chain' },
    })
    return
  }
  form.permissionMode = 'chain'
}

function buildExecutor(): NeuacpExecutorSpec {
  return {
    kind: selectedCatalog.value?.kind ?? 'acp',
    tool: form.tool,
    transport: form.transport,
    command: parseCommand(form.command),
    cwd: form.cwd.trim(),
    env_keys: form.envKeys.map((key) => key.trim()).filter(Boolean),
    permission_mode: form.permissionMode,
    remote:
      form.transport === 'ssh'
        ? {
            host: form.sshHost.trim(),
            port: Number(form.sshPort) || 22,
            user: form.sshUser.trim(),
            key_ref: form.sshKeyRef.trim(),
          }
        : null,
  }
}

async function loadCatalog() {
  catalogLoading.value = true
  catalogError.value = false
  try {
    const res = await fetchNeuacpCatalog()
    catalog.value = Array.isArray(res) ? res : []
    if (!form.tool) {
      const first = catalog.value.find((item) => !item.disabled)
      if (first) handleToolChange(first.tool)
    }
  } catch {
    catalogError.value = true
  } finally {
    catalogLoading.value = false
  }
}

async function handleTestConnection() {
  const problems: string[] = []
  if (!form.tool) problems.push(t('neuacp.toolRequired'))
  if (parseCommand(form.command).length === 0) problems.push(t('neuacp.commandRequired'))
  if (problems.length) {
    problems.forEach((text) => message.warning(text))
    return
  }
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await testNeuacpConnection(buildExecutor())
  } catch (err) {
    testResult.value = { ok: false, error: err instanceof Error ? err.message : String(err) }
  } finally {
    testing.value = false
  }
}

async function handleSubmit() {
  const problems: string[] = []
  if (!form.tool) problems.push(t('neuacp.toolRequired'))
  if (!form.name.trim()) problems.push(t('neuacp.nameRequired'))
  if (!form.cwd.trim()) problems.push(t('neuacp.cwdRequired'))
  if (parseCommand(form.command).length === 0) problems.push(t('neuacp.commandRequired'))
  if (problems.length) {
    problems.forEach((text) => message.warning(text))
    return
  }
  if (form.permissionMode === 'auto' && !isAdmin.value) {
    form.permissionMode = 'chain'
    message.warning(t('neuacp.externalAdminOnly'))
    return
  }
  submitting.value = true
  try {
    const body: TeamMemberAddBody = {
      members: [form.name.trim()],
      prompt: form.prompt,
      role: form.role,
      executor: buildExecutor(),
    }
    await addTeamMembers(props.teamId, body)
    message.success(t('neuacp.addSuccess'))
    emit('submitted')
  } catch {
    message.error(t('common.error'))
  } finally {
    submitting.value = false
  }
}

onMounted(loadCatalog)

defineExpose({
  form,
  catalog,
  testResult,
  isAdmin,
  loadCatalog,
  handleToolChange,
  handleTestConnection,
  handleSubmit,
  onPermissionModeChange,
})
</script>

<style scoped>
.neuacp-member-form { display: flex; flex-direction: column; gap: 4px; }
.neuacp-form :deep(.ant-form-item) { margin-bottom: 14px; }
.field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.field-hint { margin-top: 4px; font-size: 12px; color: var(--nr-text-tertiary); line-height: 1.5; }
.field-error { margin-top: 4px; font-size: 12px; color: var(--nr-error); }

.tool-option { display: inline-flex; align-items: center; gap: 8px; max-width: 100%; }
.tool-name { font-weight: 600; color: var(--nr-text-primary); }
.tool-kind { font-size: 12px; color: var(--nr-text-secondary); }
.tool-chip {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  border: 1px solid var(--nr-border);
  color: var(--nr-text-tertiary);
  white-space: nowrap;
}
.tool-node { color: var(--nr-warning); border-color: var(--nr-warning-soft-border); background: var(--nr-warning-soft-bg); }
.tool-installed { color: var(--nr-success); border-color: var(--nr-success-soft-border); background: var(--nr-success-soft-bg); }
.tool-hint { color: var(--nr-error); border-color: var(--nr-error-soft-border); background: var(--nr-error-soft-bg); }
.tool-hint-text { font-size: 11px; color: var(--nr-text-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.test-connection { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; }
.test-result {
  font-size: 12px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--nr-border);
  word-break: break-all;
}
.test-result.is-ok {
  color: var(--nr-success);
  background: var(--nr-success-soft-bg);
  border-color: var(--nr-success-soft-border);
}
.test-result.is-fail {
  color: var(--nr-error);
  background: var(--nr-error-soft-bg);
  border-color: var(--nr-error-soft-border);
}

.form-actions { display: flex; gap: 8px; justify-content: flex-end; }
</style>
