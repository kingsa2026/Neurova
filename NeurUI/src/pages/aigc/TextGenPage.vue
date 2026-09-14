<script setup lang="ts">
/**
 * AIGC 文本生成页（2026-09-14 R1 自 AIGCPage 拆分）。
 * 契约保持：model=auto/缺省 → 后端 LLMRouter CHAT 自动路由；结果 markdown 渲染走
 * 共享 renderMarkdown（marked+DOMPurify，安全审计 M3）。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { generateText as apiGenerateText } from '@/api/modules/generation'
import { useAigcModels } from '@/composables/useAigcModels'
import { renderMarkdown } from '@/utils/markdown'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()
const { textModelOptions } = useAigcModels()

const prompt = ref('')
const model = ref('auto')
const generating = ref(false)
const result = ref('')

const renderedText = computed(() => renderMarkdown(result.value, t('common.copy')))

async function generate() {
  if (!prompt.value.trim()) return
  generating.value = true
  result.value = ''
  try {
    const res: any = await apiGenerateText({
      prompt: prompt.value,
      model: model.value,
    })
    const data = res?.data ?? res
    result.value = data?.content ?? data?.text ?? ''
  } catch {
    message.error(t('aigc.generateError'))
  } finally {
    generating.value = false
  }
}
</script>

<template>
  <div class="aigc-gen-layout">
    <GlassPanel class="aigc-input-panel" variant="subtle">
      <a-form layout="vertical">
        <a-form-item :label="t('aigc.prompt')">
          <a-textarea v-model:value="prompt" :rows="6" :placeholder="t('aigc.textPromptPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('aigc.model')">
          <a-select v-model:value="model" class="model-select-text" :options="textModelOptions" :placeholder="t('aigc.selectModel')" show-search />
        </a-form-item>
        <GlassButton variant="primary" :loading="generating" @click="generate">
          {{ t('aigc.generate') }}
        </GlassButton>
      </a-form>
    </GlassPanel>
    <GlassCard :title="t('aigc.result')" class="aigc-result-panel">
      <div v-if="result" class="aigc-text-result" v-html="renderedText" />
      <a-empty v-else :description="t('aigc.noResult')" />
    </GlassCard>
  </div>
</template>
