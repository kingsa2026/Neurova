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
              <a-form-item :label="t('agent.provider')">
                <a-input v-model:value="formState.provider" :placeholder="t('agent.provider')" />
              </a-form-item>
            </a-col>
          </a-row>

          <a-form-item :label="t('agent.description')">
            <a-textarea v-model:value="formState.description" :rows="2" :placeholder="t('agent.description')" />
          </a-form-item>

          <a-row :gutter="16">
            <a-col :span="12">
              <a-form-item :label="t('agent.model')">
                <a-input v-model:value="formState.model" :placeholder="t('agent.model')" />
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
              <a-select v-model:value="formState.ttsVoice" :placeholder="t('agent.ttsVoice')" style="width: 100%">
                <a-select-option value="alloy">{{ t('aigc.voiceAlloy') }}</a-select-option>
                <a-select-option value="echo">{{ t('aigc.voiceEcho') }}</a-select-option>
                <a-select-option value="fable">{{ t('aigc.voiceFable') }}</a-select-option>
                <a-select-option value="onyx">{{ t('aigc.voiceOnyx') }}</a-select-option>
                <a-select-option value="nova">{{ t('aigc.voiceNova') }}</a-select-option>
                <a-select-option value="shimmer">{{ t('aigc.voiceShimmer') }}</a-select-option>
              </a-select>
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

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()

const agentId = computed(() => route.params.id as string | undefined)
const isEditing = computed(() => !!agentId.value)
const pageLoading = ref(false)
const saving = ref(false)

const formState = ref({
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

const loadAgent = async () => {
  if (!agentId.value) return
  pageLoading.value = true
  try {
    const agent = agentStore.agents.find((a) => a.id === agentId.value)
    if (agent) {
      formState.value = {
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
    const payload = {
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
  if (agentStore.agents.length === 0) {
    await agentStore.loadAgents()
  }
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
