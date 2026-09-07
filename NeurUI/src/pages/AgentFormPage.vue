<template>
  <div class="agent-form-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ isEditing ? t('agent.edit') : t('agent.create') }}</h2>
        <p class="page-subtitle">{{ t('agent.config') }}</p>
      </div>
      <GlassButton variant="ghost" @click="$router.push('/agents')">
        {{ t('common.back') }}
      </GlassButton>
    </div>

    <a-spin :spinning="pageLoading">
      <a-form :model="formState" layout="vertical" class="agent-form" :rules="{ name: [{ required: true, message: t('common.required') }] }">
        <!-- Basic info -->
        <GlassCard :title="t('common.info')" style="margin-bottom: 20px">
          <a-row :gutter="16">
            <a-col :span="12">
              <a-form-item :label="t('agent.name')" required>
                <a-input v-model:value="formState.name" :placeholder="t('agent.name')" />
              </a-form-item>
            </a-col>
            <a-col :span="12">
              <a-form-item label="Agent ID" :extra="isEditing ? t('agent.idReadonly') : t('agent.idHint')">
                <a-input
                  v-model:value="formState.agent_id"
                  :placeholder="isEditing ? agentId : t('agent.idPlaceholder')"
                  :disabled="isEditing"
                  :readonly="isEditing"
                />
              </a-form-item>
            </a-col>
          </a-row>
          <a-row :gutter="16">
            <a-col :span="12">
              <a-form-item :label="t('agent.provider')">
                <a-select
                  v-model:value="formState.provider"
                  :placeholder="t('agent.selectProvider')"
                  :options="providerOptions"
                  :loading="loadingProviders"
                  show-search
                  :filter-option="(input: string, option: any) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())"
                  @change="onProviderChange"
                  allow-clear
                />
              </a-form-item>
            </a-col>
          </a-row>

          <a-form-item :label="t('agent.description')">
            <a-textarea v-model:value="formState.description" :rows="2" :placeholder="t('agent.description')" />
          </a-form-item>

          <a-row :gutter="16">
            <a-col :span="12">
              <a-form-item :label="t('agent.model')">
                <a-select
                  v-model:value="formState.model"
                  :placeholder="t('agent.selectModel')"
                  :options="currentModelOptions"
                  :disabled="!formState.provider"
                  show-search
                  :filter-option="(input: string, option: any) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())"
                  allow-clear
                />
              </a-form-item>
            </a-col>
          </a-row>
        </GlassCard>

        <!-- System prompt & behavior -->
        <GlassCard :title="t('agent.systemPrompt')" style="margin-bottom: 20px">
          <a-form-item :label="t('agent.systemPrompt')">
            <a-textarea v-model:value="formState.systemPrompt" :rows="6" :placeholder="t('agent.systemPromptPlaceholder')" />
          </a-form-item>

          <a-row :gutter="16">
            <a-col :span="12">
              <a-form-item :label="t('agent.temperature')">
                <a-slider v-model:value="formState.temperature" :min="0" :max="2" :step="0.1" />
                <span class="slider-value">{{ formState.temperature }}</span>
              </a-form-item>
            </a-col>
            <a-col :span="12">
              <a-form-item :label="t('agent.maxTokens')">
                <a-input-number v-model:value="formState.maxTokens" :min="100" :max="128000" :step="100" style="width: 100%" />
              </a-form-item>
            </a-col>
          </a-row>
        </GlassCard>

        <!-- Personality & Constitution -->
        <GlassCard :title="t('agent.personality')" style="margin-bottom: 20px">
          <a-form-item :label="t('agent.personality')">
            <a-textarea v-model:value="formState.personality" :rows="3" :placeholder="t('agent.personality')" />
          </a-form-item>
          <a-form-item :label="t('agent.constitution')">
            <a-textarea v-model:value="formState.constitution" :rows="3" :placeholder="t('agent.constitution')" />
          </a-form-item>
        </GlassCard>

        <!-- TTS configuration -->
        <GlassCard :title="t('agent.tts')" style="margin-bottom: 20px">
          <a-form-item :label="t('agent.ttsEnabled')">
            <a-switch v-model:checked="formState.ttsEnabled" />
          </a-form-item>

          <template v-if="formState.ttsEnabled">
            <a-form-item :label="t('agent.ttsVoice')">
              <!-- 音色分组：本地 moss 内置音色（16k 试听即真实输出听感）+ 在线 edge-tts；
                   播放按钮试听当前选中音色（预制静态文件 /tts-preview/，脚本 scripts/generate_tts_previews.py） -->
              <div class="voice-row">
                <a-select v-model:value="formState.ttsVoice" :placeholder="t('agent.ttsVoice')" style="flex: 1" allow-clear>
                  <a-select-opt-group :label="t('agent.voiceGroupLocal')">
                    <a-select-option v-for="v in mossVoiceOptions" :key="v.value" :value="v.value">
                      {{ v.label }}
                    </a-select-option>
                  </a-select-opt-group>
                  <a-select-opt-group :label="t('agent.voiceGroupOnline')">
                    <a-select-option v-for="v in edgeVoiceOptions" :key="v.value" :value="v.value">
                      {{ v.label }}
                    </a-select-option>
                  </a-select-opt-group>
                </a-select>
                <GlassButton
                  variant="ghost"
                  class="voice-preview-btn"
                  :disabled="!formState.ttsVoice || previewLoading"
                  @click="previewVoice"
                >
                  {{ previewLoading ? t('agent.voicePreviewLoading') : t('agent.voicePreview') }}
                </GlassButton>
              </div>
            </a-form-item>

            <a-row :gutter="16">
              <a-col :span="12">
                <a-form-item :label="t('agent.ttsSpeed')">
                  <a-slider v-model:value="formState.ttsSpeed" :min="0.5" :max="2" :step="0.1" />
                  <span class="slider-value">{{ formState.ttsSpeed }}</span>
                </a-form-item>
              </a-col>
              <a-col :span="12">
                <a-form-item :label="t('agent.ttsPitch')">
                  <a-slider v-model:value="formState.ttsPitch" :min="0.5" :max="2" :step="0.1" />
                  <span class="slider-value">{{ formState.ttsPitch }}</span>
                </a-form-item>
              </a-col>
            </a-row>
          </template>
        </GlassCard>

        <!-- Actions -->
        <div class="form-actions">
          <GlassButton variant="ghost" @click="$router.push('/agents')">
            {{ t('common.cancel') }}
          </GlassButton>
          <GlassButton variant="primary" :loading="saving" @click="handleSave">
            {{ t('common.save') }}
          </GlassButton>
        </div>
      </a-form>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAgentStore } from '@/stores/agents'
import { listProviders } from '@/api/modules/providers'
import { listModels } from '@/api/modules/models'
import { normalizeModel } from '@/types/model'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()

const agentId = computed(() => route.params.id as string | undefined)
const isEditing = computed(() => !!agentId.value)
const pageLoading = ref(false)
const saving = ref(false)

// Provider / Model dropdown state
const providerOptions = ref<{ value: string; label: string }[]>([])
const allModelOptions = ref<{ value: string; label: string; provider_id: string }[]>([])
const loadingProviders = ref(false)

const currentModelOptions = computed(() => {
  if (!formState.value.provider) return []
  return allModelOptions.value.filter((m) => m.provider_id === formState.value.provider)
})

const onProviderChange = (providerId: string | undefined) => {
  // Clear model if it doesn't belong to the new provider
  if (providerId && formState.value.model) {
    const valid = allModelOptions.value.some(
      (m) => m.value === formState.value.model && m.provider_id === providerId,
    )
    if (!valid) formState.value.model = ''
  }
}

const fetchProvidersAndModels = async () => {
  loadingProviders.value = true
  try {
    const [providersRes, modelsRes] = await Promise.all([listProviders(), listModels()])

    // Normalize providers response
    const rawProviders = Array.isArray(providersRes)
      ? providersRes
      : (providersRes as any)?.data ?? (providersRes as any)?.providers ?? []

    // Filter to enabled providers with models
    const enabled = rawProviders.filter(
      (p: any) => p.is_active !== false && (p.models_count ?? 0) > 0,
    )
    providerOptions.value = enabled.map((p: any) => ({
      value: p.provider_id || p.id,
      label: p.name || p.provider_id || p.id,
    }))

    // Normalize models response
    const rawModels = Array.isArray(modelsRes)
      ? modelsRes
      : (modelsRes as any)?.data ?? (modelsRes as any)?.models ?? []

    allModelOptions.value = (rawModels as unknown[])
      .map((item) => normalizeModel(item as Record<string, any>))
      .filter((m) => m.provider_id && m.provider_id !== 'system')
      .map((m) => ({
        value: m.id,
        label: m.name || m.id,
        provider_id: m.provider_id,
      }))
  } catch (err: any) {
    console.warn('[AgentFormPage] fetchProvidersAndModels failed:', err)
  } finally {
    loadingProviders.value = false
  }
}

const formState = ref({
  agent_id: '',
  name: '',
  description: '',
  model: '',
  provider: '',
  systemPrompt: '',
  temperature: 0.7,
  maxTokens: 4096,
  personality: '',
  constitution: '',
  ttsEnabled: false,
  ttsVoice: '',
  ttsSpeed: 1.0,
  ttsPitch: 1.0,
})

// ── 音色选项与试听（预制静态文件 /tts-preview/，scripts/generate_tts_previews.py 生成）──
interface VoiceOption {
  value: string
  label: string
}

// moss 内置音色（本地引擎，跨引擎自动近似回落 edge；value=moss 内置名，后端 _EDGE_VOICE_ALIASES 反查）
const mossVoiceOptions: VoiceOption[] = [
  { value: 'Junhao', label: 'Junhao · 浩（中文男声）' },
  { value: 'Zhiming', label: 'Zhiming · 志明（中文男声·胡同）' },
  { value: 'Weiguo', label: 'Weiguo · 卫国（中文男声·说书）' },
  { value: 'Xiaoyu', label: 'Xiaoyu · 羽（中文女声·明星）' },
  { value: 'Yuewen', label: 'Yuewen · 悦文（中文女声·机车）' },
  { value: 'Lingyu', label: 'Lingyu · 灵雨（中文女声·深夜电台）' },
  { value: 'Trump', label: 'Trump（英文男声）' },
  { value: 'Adam', label: 'Adam（英文男声·新闻）' },
  { value: 'Ava', label: 'Ava（英文女声）' },
  { value: 'Bella', label: 'Bella（英文女声）' },
]
// edge-tts 在线音色（原四音色保留）
const edgeVoiceOptions: VoiceOption[] = [
  { value: 'zh-CN-XiaoxiaoNeural', label: `${t('agent.voiceXiaoxiao')} · 在线` },
  { value: 'zh-CN-XiaoyiNeural', label: `${t('agent.voiceXiaoyi')} · 在线` },
  { value: 'zh-CN-YunxiNeural', label: `${t('agent.voiceYunxi')} · 在线` },
  { value: 'zh-CN-YunyangNeural', label: `${t('agent.voiceYunyang')} · 在线` },
]

const previewLoading = ref(false)
let previewAudio: HTMLAudioElement | null = null

/** 试听当前选中音色：预制文件按 voice 名直接命中（moss.wav / edge.mp3）。 */
function previewVoice(): void {
  const voice = formState.value.ttsVoice
  if (!voice) return
  previewAudio?.pause()
  const file = voice.endsWith('Neural') ? `${voice}.mp3` : `${voice}.wav`
  previewAudio = new Audio(`/tts-preview/${encodeURIComponent(file)}`)
  previewLoading.value = true
  previewAudio.onended = () => (previewLoading.value = false)
  previewAudio.onerror = () => {
    previewLoading.value = false
    message.warning(t('agent.voicePreviewMissing'))
  }
  previewAudio.play().catch(() => (previewLoading.value = false))
}

const loadAgent = async () => {
  if (!agentId.value) return
  pageLoading.value = true
  try {
    const agent = agentStore.agents.find((a) => a.id === agentId.value)
    if (agent) {
      formState.value = {
        agent_id: agent.id,
        name: agent.name,
        description: agent.description || '',
        model: agent.model || '',
        provider: agent.provider || '',
        systemPrompt: agent.config?.systemPrompt || '',
        temperature: agent.config?.temperature ?? 0.7,
        maxTokens: agent.config?.maxTokens ?? 4096,
        personality: '',
        constitution: '',
        ttsEnabled: agent.config?.ttsEnabled ?? false,
        ttsVoice: agent.config?.ttsVoice || '',
        ttsSpeed: agent.config?.ttsSpeed ?? 1.0,
        ttsPitch: agent.config?.ttsPitch ?? 1.0,
      }
    }
  } catch (err: any) {
    message.error(err?.message || t('common.error'))
  } finally {
    pageLoading.value = false
  }
}

const handleSave = async () => {
  saving.value = true
  try {
    const payload: any = {
      name: formState.value.name,
      description: formState.value.description,
      model: formState.value.model,
      provider: formState.value.provider,
      config: {
        systemPrompt: formState.value.systemPrompt,
        temperature: formState.value.temperature,
        maxTokens: formState.value.maxTokens,
        ttsEnabled: formState.value.ttsEnabled,
        ttsVoice: formState.value.ttsVoice,
        ttsSpeed: formState.value.ttsSpeed,
        ttsPitch: formState.value.ttsPitch,
      },
    }
    // 新建时传入 agent_id
    if (!isEditing.value && formState.value.agent_id.trim()) {
      payload.agent_id = formState.value.agent_id.trim()
    }

    if (isEditing.value && agentId.value) {
      const result = await agentStore.updateAgent(agentId.value, payload)
      if (result) {
        message.success(t('common.success'))
        router.push('/agents')
      } else {
        message.error(agentStore.error || t('common.error'))
      }
    } else {
      const result = await agentStore.createAgent(payload)
      if (result) {
        message.success(t('common.success'))
        router.push('/agents')
      } else {
        message.error(agentStore.error || t('common.error'))
      }
    }
  } catch (err: any) {
    message.error(err?.message || t('common.error'))
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  // Fetch provider/model options first (parallel with agents)
  const agentsPromise = agentStore.agents.length === 0 ? agentStore.loadAgents() : Promise.resolve()
  await Promise.all([fetchProvidersAndModels(), agentsPromise])
  if (isEditing.value) {
    await loadAgent()
  }
})
</script>

<style scoped>
.agent-form-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.page-title {
  font-family: var(--nr-font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--nr-text-primary);
  margin: 0;
}

.voice-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.voice-preview-btn {
  white-space: nowrap;
}

.page-subtitle {
  margin: 4px 0 0;
  color: var(--nr-text-secondary);
  font-size: 13px;
}

.agent-form {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.slider-value {
  display: inline-block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--nr-text-secondary);
  font-family: var(--nr-font-mono);
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 0;
}
</style>
