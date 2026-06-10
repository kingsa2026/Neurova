<template>
  <div class="collab-init-page">
    <div class="page-header">
      <h2>{{ t('collab.initiate') }}</h2>
      <GlassButton variant="ghost" size="sm" @click="$router.back()">{{ t('common.back') }}</GlassButton>
    </div>

    <GlassPanel variant="default" padding="28px 32px">
      <a-steps :current="currentStep" size="small" class="init-steps">
        <a-step v-for="(label, idx) in stepLabels" :key="idx" :title="label" />
      </a-steps>

      <div class="step-content">
        <!-- Step 1: Select template -->
        <div v-if="currentStep === 0" class="step-panel">
          <h4>{{ t('collab.templates') }}</h4>
          <a-spin :spinning="loadingTemplates">
            <a-empty v-if="!loadingTemplates && templates.length === 0" :description="t('common.noData')" />
            <div v-else class="tpl-list">
              <div
                v-for="tpl in templates"
                :key="tpl.id"
                class="tpl-option"
                :class="{ selected: form.templateId === tpl.id }"
                @click="form.templateId = tpl.id"
              >
                <strong>{{ tpl.name }}</strong>
                <span class="tpl-desc">{{ tpl.description }}</span>
                <a-tag color="blue">{{ tpl.type }}</a-tag>
              </div>
            </div>
          </a-spin>
        </div>

        <!-- Step 2: Configure participants -->
        <div v-if="currentStep === 1" class="step-panel">
          <h4>{{ t('collab.members') }}</h4>
          <a-form layout="vertical">
            <a-form-item :label="t('collab.members')">
              <a-select v-model:value="form.participants" mode="tags" :placeholder="t('collab.members')" style="width: 100%" />
            </a-form-item>
          </a-form>
        </div>

        <!-- Step 3: Parameters -->
        <div v-if="currentStep === 2" class="step-panel">
          <h4>{{ t('agent.config') }}</h4>
          <a-form layout="vertical">
            <a-form-item :label="t('common.name')">
              <a-input v-model:value="form.name" :placeholder="t('common.name')" />
            </a-form-item>
            <a-form-item :label="t('common.description')">
              <a-input v-model:value="form.description" type="textarea" :rows="3" :placeholder="t('common.description')" />
            </a-form-item>
          </a-form>
        </div>

        <!-- Step 4: Review -->
        <div v-if="currentStep === 3" class="step-panel">
          <h4>{{ t('common.confirm') }}</h4>
          <div class="review-body">
            <p><strong>{{ t('common.name') }}:</strong> {{ form.name }}</p>
            <p><strong>{{ t('common.description') }}:</strong> {{ form.description }}</p>
            <p><strong>{{ t('collab.templates') }}:</strong> {{ selectedTemplateName }}</p>
            <p><strong>{{ t('collab.members') }}:</strong> {{ form.participants.join(', ') }}</p>
          </div>
        </div>
      </div>

      <div class="step-actions">
        <GlassButton v-if="currentStep > 0" variant="secondary" size="sm" @click="currentStep--">{{ t('common.prev') }}</GlassButton>
        <GlassButton v-if="currentStep < 3" variant="primary" size="sm" @click="currentStep++">{{ t('common.next') }}</GlassButton>
        <GlassButton v-if="currentStep === 3" variant="primary" size="sm" :loading="starting" @click="handleStart">{{ t('common.submit') }}</GlassButton>
      </div>
    </GlassPanel>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()
const router = useRouter()

interface Template {
  id: string
  name: string
  description: string
  type: string
}

const templates = ref<Template[]>([])
const loadingTemplates = ref(false)
const currentStep = ref(0)
const starting = ref(false)

const stepLabels = computed(() => [
  t('collab.templates'),
  t('collab.members'),
  t('agent.config'),
  t('common.confirm'),
])

const form = reactive({
  templateId: '' as string,
  participants: [] as string[],
  name: '',
  description: '',
})

const selectedTemplateName = computed(() => {
  const tpl = templates.value.find((t) => t.id === form.templateId)
  return tpl?.name ?? '-'
})

async function fetchTemplates() {
  loadingTemplates.value = true
  try {
    const res = await request.get('/collaboration/templates') as unknown as Template[]
    templates.value = res ?? []
  } catch {
    templates.value = []
  } finally {
    loadingTemplates.value = false
  }
}

async function handleStart() {
  starting.value = true
  try {
    await request.post('/collaboration/start', {
      templateId: form.templateId,
      participants: form.participants,
      name: form.name,
      description: form.description,
    })
    router.push('/collaboration')
  } catch { /* handled */ } finally {
    starting.value = false
  }
}

onMounted(fetchTemplates)
</script>

<style scoped>
.collab-init-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.init-steps { margin-bottom: 32px; }
.step-content { min-height: 240px; }
.step-panel { display: flex; flex-direction: column; gap: 16px; }
.step-panel h4 { color: var(--nr-text-primary); margin: 0; font-size: 15px; }
.tpl-list { display: flex; flex-direction: column; gap: 10px; }
.tpl-option {
  display: flex; flex-direction: column; gap: 4px;
  padding: 14px 18px; border-radius: 12px; cursor: pointer;
  border: 1px solid rgba(255,255,255,0.08); transition: all 0.2s;
}
.tpl-option:hover { background: rgba(255,255,255,0.04); }
.tpl-option.selected { border-color: var(--nr-primary-light, #6366f1); background: rgba(99,102,241,0.08); }
.tpl-desc { font-size: 13px; color: var(--nr-text-tertiary); }
.review-body { display: flex; flex-direction: column; gap: 8px; }
.review-body p { color: var(--nr-text-secondary); font-size: 14px; margin: 0; }
.step-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 24px; }
</style>
