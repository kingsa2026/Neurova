<template>
  <div class="setting-page">
    <h2 class="page-title">{{ t('system.settings') }}</h2>
    <p class="page-global-hint">{{ t('common.globalSettingHint') }}</p>

    <template v-if="!isAdmin">
      <div class="admin-gate">{{ t('common.adminOnlyHint') }}</div>
    </template>
    <template v-else>
    <a-tabs v-model:activeKey="activeTab" tab-position="left" class="settings-tabs">
      <!-- General -->
      <a-tab-pane key="general" :tab="t('settings.general')">
        <GlassCard :title="t('settings.generalSettings')">
          <a-form layout="vertical" :model="general" :rules="{ app_name: [{ required: true, message: t('common.required') }], language: [{ required: true, message: t('common.required') }] }">
            <a-form-item :label="t('settings.appName')">
              <a-input v-model:value="general.app_name" />
            </a-form-item>
            <a-form-item :label="t('theme.language')">
              <a-select v-model:value="general.language" style="width: 100%">
                <a-select-option v-for="loc in supportedLocales" :key="loc.code" :value="loc.code">
                  {{ loc.flag }} {{ loc.name }}
                </a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item :label="t('theme.appearance')">
              <a-switch v-model:checked="isDark" :checked-children="t('theme.dark')" :un-checked-children="t('theme.light')" @change="onThemeToggle" />
            </a-form-item>
          </a-form>
          <template #footer>
            <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSection('general')">{{ t('common.save') }}</GlassButton>
          </template>
        </GlassCard>
      </a-tab-pane>

      <!-- Security -->
      <!-- LLM 默认模型设置在 LLM 服务商管理页（ModelPage 表头，真实链路=apiActivateModel
           + getActiveModel 回读）；此前系统设置里的 default_provider/default_model 是
           /v1/settings 假存（进程内 dict 重启即丢）上的第三入口，且 prefill 会用假数据
           覆盖真实 active 状态，已随温度迁出一起删除 -->
      <a-tab-pane key="security" :tab="t('settings.security')">
        <GlassCard :title="t('settings.securitySettings')">
          <a-form layout="vertical" :model="security" :rules="{ jwt_secret: [{ required: true, message: t('common.required') }] }">
            <a-form-item :label="t('settings.jwtSecret')">
              <a-input-password v-model:value="security.jwt_secret" />
            </a-form-item>
            <a-form-item :label="t('settings.jwtExpiry')">
              <a-input-number v-model:value="security.jwt_expiry_hours" :min="1" :max="8760" style="width: 100%" />
            </a-form-item>
            <a-form-item :label="t('settings.minPasswordLength')">
              <a-input-number v-model:value="security.min_password_length" :min="6" :max="64" style="width: 100%" />
            </a-form-item>
            <a-form-item :label="t('settings.requireSpecial')">
              <a-switch v-model:checked="security.require_special" />
            </a-form-item>
          </a-form>
          <template #footer>
            <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSection('security')">{{ t('common.save') }}</GlassButton>
          </template>
        </GlassCard>
        <!-- 桌面沙箱提供方：值存 advanced 段（与运行权限档同族，后端热读），
             未配置时 sandbox/auto 档变更动作 fail-closed 拒绝 -->
        <GlassCard :title="t('settings.desktopProviderTitle')">
          <p class="section-hint">{{ t('settings.desktopProviderHint') }}</p>
          <a-form layout="vertical">
            <a-form-item :label="t('settings.desktopProviderTitle')">
              <a-select v-model:value="advanced.desktop_provider" style="width: 100%">
                <a-select-option value="">{{ t('settings.desktopProviderNone') }}</a-select-option>
                <a-select-option value="sandbox">{{ t('settings.desktopProviderSandbox') }}</a-select-option>
                <a-select-option value="rdp">{{ t('settings.desktopProviderRdp') }}</a-select-option>
              </a-select>
            </a-form-item>
          </a-form>
          <template #footer>
            <GlassButton variant="primary" size="sm" :loading="saving" @click="saveDesktopProvider">{{ t('common.save') }}</GlassButton>
          </template>
        </GlassCard>
      </a-tab-pane>

      <!-- Storage -->
      <a-tab-pane key="storage" :tab="t('settings.storage')">
        <GlassCard :title="t('settings.storageSettings')">
          <a-form layout="vertical" :model="storage" :rules="{ media_path: [{ required: true, message: t('common.required') }] }">
            <a-form-item :label="t('settings.mediaStoragePath')">
              <a-input v-model:value="storage.media_path" />
            </a-form-item>
            <a-form-item :label="t('settings.maxUploadSize')">
              <a-input-number v-model:value="storage.max_upload_mb" :min="1" :max="1024" style="width: 100%" />
            </a-form-item>
            <a-form-item :label="t('settings.cacheTtl')">
              <a-input-number v-model:value="storage.cache_ttl_minutes" :min="1" style="width: 100%" />
            </a-form-item>
          </a-form>
          <template #footer>
            <div class="storage-actions">
              <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSection('storage')">{{ t('common.save') }}</GlassButton>
              <GlassButton variant="danger" size="sm" :loading="clearingCache" @click="clearCache">{{ t('settings.refreshCache') }}</GlassButton>
            </div>
          </template>
        </GlassCard>
      </a-tab-pane>

      <!-- Model：LLM 429 重试/切换容错参数（ZCode 对齐 2026-09-11） -->
      <a-tab-pane key="model" :tab="t('settings.modelTab')">
        <GlassCard :title="t('settings.llmRetryTitle')">
          <p class="governance-hint">{{ t('settings.llmRetryHint') }}</p>
          <a-form layout="vertical">
            <a-form-item :label="t('settings.llmRetryMaxRetries')">
              <a-input-number
                v-model:value="llmRetry.max_retries"
                :min="0"
                :max="50"
                :step="1"
                style="width: 100%"
              />
              <p class="governance-hint">{{ t('settings.llmRetryMaxRetriesHint') }}</p>
            </a-form-item>
            <a-form-item :label="t('settings.llmRetryInterval')">
              <a-input-number
                v-model:value="llmRetry.interval"
                :min="1"
                :max="600"
                :step="1"
                style="width: 100%"
              />
              <p class="governance-hint">{{ t('settings.llmRetryIntervalHint') }}</p>
            </a-form-item>
            <a-form-item :label="t('settings.llmRetryWaitCap')">
              <a-input-number
                v-model:value="llmRetry.wait_cap"
                :min="1"
                :max="3600"
                :step="10"
                style="width: 100%"
              />
              <p class="governance-hint">{{ t('settings.llmRetryWaitCapHint') }}</p>
            </a-form-item>
            <a-form-item :label="t('settings.llmRetryMaxSwitches')">
              <a-input-number
                v-model:value="llmRetry.max_switches"
                :min="1"
                :max="20"
                :step="1"
                style="width: 100%"
              />
              <p class="governance-hint">{{ t('settings.llmRetryMaxSwitchesHint') }}</p>
            </a-form-item>
          </a-form>
          <template #footer>
            <GlassButton variant="primary" size="sm" :loading="savingLlmRetry" @click="saveLlmRetry">{{ t('common.save') }}</GlassButton>
          </template>
        </GlassCard>
      </a-tab-pane>

      <!-- Advanced -->
      <a-tab-pane key="advanced" :tab="t('settings.advanced')">
        <div class="advanced-stack">
        <GlassCard :title="t('settings.advancedSettings')">
          <a-form layout="vertical" :model="advanced" :rules="{ log_level: [{ required: true, message: t('common.required') }] }">
            <a-form-item :label="t('settings.debugMode')">
              <a-switch v-model:checked="advanced.debug_mode" />
            </a-form-item>
            <a-form-item :label="t('settings.logLevel')">
              <a-select v-model:value="advanced.log_level" style="width: 100%">
                <a-select-option value="debug">{{ t('settings.debug') }}</a-select-option>
                <a-select-option value="info">{{ t('settings.info') }}</a-select-option>
                <a-select-option value="warning">{{ t('settings.warning') }}</a-select-option>
                <a-select-option value="error">{{ t('settings.error') }}</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item :label="t('settings.enableTelemetry')">
              <a-switch v-model:checked="advanced.telemetry" />
            </a-form-item>
            <a-form-item :label="t('settings.maxOutputTokens')" :extra="t('settings.maxOutputTokensHint')">
              <a-input-number
                v-model:value="advanced.max_output_tokens"
                :min="1024"
                :max="200000"
                :step="1024"
                style="width: 100%"
              />
            </a-form-item>
            <a-form-item :label="t('settings.desktopRuntimeMode')" :extra="t('settings.desktopRuntimeModeHint')">
              <a-select v-model:value="advanced.desktop_runtime_mode" style="width: 100%">
                <a-select-option value="full">{{ t('settings.runtimeFull') }}</a-select-option>
                <a-select-option value="sandbox">{{ t('settings.runtimeSandbox') }}</a-select-option>
                <a-select-option value="review">{{ t('settings.runtimeReview') }}</a-select-option>
                <a-select-option value="auto">{{ t('settings.runtimeAuto') }}</a-select-option>
              </a-select>
            </a-form-item>
          </a-form>
          <template #footer>
            <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSection('advanced')">{{ t('common.save') }}</GlassButton>
          </template>
        </GlassCard>

        <!-- 凭据管理（SSH 多主机 + 社交平台），按当前用户隔离；与"我的凭据"页共用组件 -->
        <CredentialManager />

        <!-- Agent 运行限制（Token 预算上限 + 单次会话最大 Loop 轮次） -->
        <GlassCard :title="t('settings.agentLimitsTitle')">
          <p class="governance-hint">{{ t('settings.agentLimitsHint') }}</p>
          <a-form layout="vertical">
            <a-form-item :label="t('settings.agentTokenBudget')">
              <a-input-number
                v-model:value="agentLimits.token_budget"
                :min="1000"
                :max="10000000"
                :step="10000"
                style="width: 100%"
              />
              <p class="governance-hint">{{ t('settings.agentTokenBudgetHint') }}</p>
            </a-form-item>
            <a-form-item :label="t('settings.agentMaxRounds')">
              <a-input-number
                v-model:value="agentLimits.max_loop_rounds"
                :min="2"
                :max="200"
                :step="1"
                style="width: 100%"
              />
              <p class="governance-hint">{{ t('settings.agentMaxRoundsHint') }}</p>
            </a-form-item>
          </a-form>
          <template #footer>
            <GlassButton variant="primary" size="sm" :loading="savingAgentLimits" @click="saveAgentLimits">{{ t('common.save') }}</GlassButton>
          </template>
        </GlassCard>

        <!-- 进化治理（RSI 部署阶段 + 对话规则提取 LLM 成本门控） -->
        <GlassCard :title="t('settings.governanceTitle')">
          <p class="governance-hint">{{ t('settings.governanceHint') }}</p>
          <a-form layout="vertical">
            <a-form-item :label="t('settings.governanceRsiPhase')">
              <a-select v-model:value="governance.rsi_phase" style="width: 100%">
                <a-select-option :value="0">{{ t('settings.governancePhase0') }}</a-select-option>
                <a-select-option :value="1">{{ t('settings.governancePhase1') }}</a-select-option>
                <a-select-option :value="2">{{ t('settings.governancePhase2') }}</a-select-option>
                <a-select-option :value="3">{{ t('settings.governancePhase3') }}</a-select-option>
                <a-select-option :value="4">{{ t('settings.governancePhase4') }}</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item :label="t('settings.governanceConversationRules')">
              <a-switch v-model:checked="governance.conversation_rules_enabled" />
            </a-form-item>
          </a-form>
          <template #footer>
            <GlassButton variant="primary" size="sm" :loading="savingGovernance" @click="saveGovernance">{{ t('common.save') }}</GlassButton>
          </template>
        </GlassCard>
        </div>
      </a-tab-pane>
    </a-tabs>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getSettings, updateSettings, clearCache as clearCacheApi, getGovernanceSettings, updateGovernanceSettings, getAgentLimits, updateAgentLimits, getLlmRetrySettings, updateLlmRetrySettings } from '@/api/modules/settings'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { supportedLocales } from '@/i18n'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import CredentialManager from '@/components/settings/CredentialManager.vue'
import { message } from 'ant-design-vue'

const { t, locale } = useI18n()
const authStore = useAuthStore()
/** 全局系统设置仅管理员可操作; 非管理员不渲染设置表单 */
const isAdmin = computed(() => authStore.user?.role === 'admin')
const appStore = useAppStore()

const activeTab = ref('general')
const saving = ref(false)
const clearingCache = ref(false)
const isDark = ref(appStore.isDark)

const general = ref({ app_name: 'Neurova', language: locale.value })
const security = ref({ jwt_secret: '', jwt_expiry_hours: 24, min_password_length: 8, require_special: true })
const storage = ref({ media_path: '/data/media', max_upload_mb: 50, cache_ttl_minutes: 60 })
const advanced = ref({ debug_mode: false, log_level: 'info', telemetry: false, max_output_tokens: 131072, desktop_runtime_mode: 'full', desktop_provider: '' })

// 进化治理设置（独立于扁平 settings 的治理面）
const governance = ref({ conversation_rules_enabled: false, rsi_phase: 0 })
const savingGovernance = ref(false)

/** Agent 运行限制（Token 预算上限 / 单次会话最大 Loop 轮次） */
const agentLimits = ref({ token_budget: 100000, max_loop_rounds: 20 })
const savingAgentLimits = ref(false)

/** LLM 429 重试/切换容错参数（ZCode 对齐 2026-09-11） */
const llmRetry = ref({ max_retries: 10, interval: 10, wait_cap: 120, max_switches: 5 })
const savingLlmRetry = ref(false)
const llmRetryLoaded = ref(false)

const fetchLlmRetry = async () => {
  try {
    const res = await getLlmRetrySettings()
    const data = (res as any)?.data?.data ?? (res as any)?.data
    if (data) {
      llmRetry.value = { ...llmRetry.value, ...data }
      llmRetryLoaded.value = true
    }
  } catch (err) {
    console.error('[Settings] fetchLlmRetry failed:', err)
    llmRetryLoaded.value = false
    // 读取失败不阻断设置页（保留默认值）
  }
}

const saveLlmRetry = async () => {
  if (!llmRetryLoaded.value) {
    // F-12：未成功加载 → 表单里是前端默认值，提交会覆盖线上配置
    message.warning(t('settings.notLoadedSaveBlocked'))
    return
  }
  savingLlmRetry.value = true
  try {
    await updateLlmRetrySettings({ ...llmRetry.value })
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    savingLlmRetry.value = false
  }
}
// F-12：加载成功标志——未成功加载就保存会把默认值回写覆盖线上配置
const agentLimitsLoaded = ref(false)
const governanceLoaded = ref(false)

const fetchAgentLimits = async () => {
  try {
    const res = await getAgentLimits()
    const data = (res as any)?.data?.data ?? (res as any)?.data
    if (data) {
      agentLimits.value = { ...agentLimits.value, ...data }
      agentLimitsLoaded.value = true
    }
  } catch (err) {
    console.error('[Settings] fetchAgentLimits failed:', err)
    agentLimitsLoaded.value = false
    // 读取失败不阻断设置页（保留默认值）
  }
}

const saveAgentLimits = async () => {
  if (!agentLimitsLoaded.value) {
    // F-12：未成功加载 → 表单里是前端默认值，提交会覆盖线上配置
    message.warning(t('settings.notLoadedSaveBlocked'))
    return
  }
  savingAgentLimits.value = true
  try {
    await updateAgentLimits({ ...agentLimits.value })
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    savingAgentLimits.value = false
  }
}

const fetchGovernance = async () => {
  try {
    const res = await getGovernanceSettings()
    const data = (res as any)?.data?.data ?? (res as any)?.data
    if (data) {
      governance.value = { ...governance.value, ...data }
      governanceLoaded.value = true
    }
  } catch (err) {
    console.error('[Settings] fetchGovernance failed:', err)
    governanceLoaded.value = false
    // 治理设置读取失败不阻断设置页（默认关）
  }
}

const saveGovernance = async () => {
  if (!governanceLoaded.value) {
    // F-12：未成功加载 → 表单里是前端默认值，提交会覆盖线上配置
    message.warning(t('settings.notLoadedSaveBlocked'))
    return
  }
  savingGovernance.value = true
  try {
    await updateGovernanceSettings({ ...governance.value })
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    savingGovernance.value = false
  }
}

const onThemeToggle = () => {
  appStore.toggleTheme()
  isDark.value = appStore.isDark
}

const fetchSettings = async () => {
  try {
    const res = await getSettings()
    // 后端 GET /settings 返回 {settings: {...}} 包裹壳（拦截器已剥 axios 层）；
    // 兼容历史 ApiResponse.data 形状，两者皆缺视为空对象
    const body: any = res as any
    const data = body?.settings ?? body?.data
    if (data?.general) general.value = { ...general.value, ...data.general }
    if (data?.security) security.value = { ...security.value, ...data.security }
    if (data?.storage) storage.value = { ...storage.value, ...data.storage }
    if (data?.advanced) advanced.value = { ...advanced.value, ...data.advanced }
  } catch {
    message.error(t('common.error'))
  }
}

const saveSection = async (section: string) => {
  saving.value = true
  try {
    const sectionMap: Record<string, any> = { general: general.value, security: security.value, storage: storage.value, advanced: advanced.value }
    await updateSettings(section, sectionMap[section])

    if (section === 'general' && general.value.language !== locale.value) {
      locale.value = general.value.language
      appStore.setLocale(general.value.language)
    }

    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

/** 提供方卡独立保存：只写 advanced 段的 desktop_provider 键
 *（后端 save_app_settings 按 key merge，不触碰同段运行档/输出预算） */
const saveDesktopProvider = async () => {
  saving.value = true
  try {
    await updateSettings('advanced', { desktop_provider: advanced.value.desktop_provider })
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

const clearCache = async () => {
  clearingCache.value = true
  try {
    await clearCacheApi()
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    clearingCache.value = false
  }
}

onMounted(() => {
  fetchSettings()
  fetchGovernance()
  fetchAgentLimits()
  fetchLlmRetry()
})
</script>

<style scoped>
/* 全局设置说明 */
.page-global-hint {
  margin: -12px 0 0;
  font-size: 12px;
  color: var(--nr-text-secondary, #8a8a92);
}

/* 非管理员提示 */
.admin-gate {
  margin: 24px auto;
  max-width: 480px;
  padding: 16px;
  border: 1px dashed var(--nr-border, rgba(255, 255, 255, 0.12));
  border-radius: 10px;
  text-align: center;
  font-size: 13px;
  color: var(--nr-text-secondary, #8a8a92);
}
.setting-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.settings-tabs { min-height: 400px; }
:deep(.settings-tabs .ant-tabs-tab) { padding: 10px 16px !important; color: var(--nr-text-secondary) !important; }
:deep(.settings-tabs .ant-tabs-tab-active .ant-tabs-tab-btn) { color: var(--nr-text-primary) !important; }
.storage-actions { display: flex; gap: 8px; }
.advanced-stack { display: flex; flex-direction: column; gap: 16px; }
.ssh-host-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.ssh-host-row { display: flex; align-items: center; gap: 10px; }
.ssh-host-name { font-family: 'Consolas', 'Menlo', monospace; flex: 1; }
.ssh-add-form { border-top: 1px solid rgba(255, 255, 255, 0.08); padding-top: 12px; }
.social-status-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.social-status-row { display: flex; align-items: center; gap: 10px; }
.social-platform-name { font-family: 'Consolas', 'Menlo', monospace; flex: 1; text-transform: capitalize; }
.governance-hint { font-size: 12px; color: var(--nr-text-secondary, #8a8a92); margin: 0 0 12px; }
</style>
