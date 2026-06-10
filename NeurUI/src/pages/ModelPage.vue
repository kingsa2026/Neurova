<template>
  <div class="model-page">
    <h2 class="page-title">{{ t('model.title') }}</h2>

    <!-- Providers section -->
    <div class="section-header">
      <h3>{{ t('model.providers') }}</h3>
      <GlassButton variant="primary" size="sm" @click="showAddProvider = true">
        {{ t('model.add') }}
      </GlassButton>
    </div>

    <a-spin :spinning="loading">
      <div class="providers-grid">
        <GlassCard
          v-for="provider in providers"
          :key="provider.id"
          :title="provider.name"
          variant="default"
        >
          <template #header>
            <div class="provider-header">
              <span class="provider-name">{{ provider.name }}</span>
              <a-tag :color="provider.status === 'active' ? 'green' : 'red'">
                {{ provider.status === 'active' ? t('common.active') : t('common.inactive') }}
              </a-tag>
            </div>
          </template>
          <div class="provider-body">
            <p class="provider-url">{{ provider.base_url }}</p>
            <p class="provider-models">{{ provider.models?.length || 0 }} {{ t('model.title').toLowerCase() }}</p>
          </div>
          <template #footer>
            <div class="provider-actions">
              <GlassButton variant="ghost" size="sm" :loading="testingId === provider.id" @click="testConnection(provider.id)">
                {{ t('model.test') }}
              </GlassButton>
              <GlassButton variant="ghost" size="sm" @click="discoverModels(provider.id)">
                {{ t('model.discover') }}
              </GlassButton>
            </div>
          </template>
        </GlassCard>
      </div>
    </a-spin>

    <!-- Active model -->
    <GlassCard :title="t('model.active')" class="active-model-card" style="margin-top: 24px">
      <div v-if="activeModel" class="active-model">
        <div class="active-model-info">
          <span class="model-name">{{ activeModel.name }}</span>
          <span class="model-provider">{{ activeModel.provider }}</span>
        </div>
        <GlassButton variant="secondary" size="sm" @click="showSwitchModel = true">
          {{ t('model.switch') }}
        </GlassButton>
      </div>
      <a-empty v-else :description="t('common.noData')" />
    </GlassCard>

    <!-- Models list -->
    <GlassCard :title="t('model.title')" class="models-list-card" style="margin-top: 24px">
      <a-table :columns="modelColumns" :data-source="models" :loading="loading" row-key="id" :pagination="{ pageSize: 10 }" size="small">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-badge :status="record.active ? 'success' : 'default'" :text="record.active ? t('common.active') : t('common.inactive')" />
          </template>
          <template v-if="column.key === 'actions'">
            <GlassButton variant="ghost" size="sm" @click="switchModel(record)">
              {{ t('model.switch') }}
            </GlassButton>
          </template>
        </template>
      </a-table>
    </GlassCard>

    <!-- Add provider modal -->
    <a-modal v-model:open="showAddProvider" :title="t('model.add')" @ok="addProvider" :confirm-loading="saving">
      <a-form layout="vertical" :model="newProvider">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="newProvider.name" />
        </a-form-item>
        <a-form-item :label="t('model.baseUrl')">
          <a-input v-model:value="newProvider.base_url" placeholder="https://api.openai.com/v1" />
        </a-form-item>
        <a-form-item :label="t('model.apiKey')">
          <a-input-password v-model:value="newProvider.api_key" />
        </a-form-item>
        <a-form-item :label="t('model.modelsLabel')">
          <a-select v-model:value="newProvider.models" mode="tags" :placeholder="'model-name'" style="width: 100%" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Switch model modal -->
    <a-modal v-model:open="showSwitchModel" :title="t('model.switch')" @ok="confirmSwitchModel">
      <a-select v-model:value="selectedModelId" style="width: 100%" :placeholder="t('model.switch')">
        <a-select-option v-for="m in models" :key="m.id" :value="m.id">
          {{ m.name }} ({{ m.provider }})
        </a-select-option>
      </a-select>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const testingId = ref<string | null>(null)
const providers = ref<any[]>([])
const models = ref<any[]>([])
const activeModel = ref<any>(null)
const showAddProvider = ref(false)
const showSwitchModel = ref(false)
const selectedModelId = ref<string>('')

const newProvider = ref({
  name: '',
  base_url: '',
  api_key: '',
  models: [] as string[],
})

const modelColumns = computed(() => [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('model.providers'), dataIndex: 'provider', key: 'provider' },
  { title: t('common.status'), key: 'status' },
  { title: t('common.actions'), key: 'actions', width: 140 },
])

const fetchProviders = async () => {
  loading.value = true
  try {
    const res: any = await request.get('/providers')
    providers.value = res?.data ?? res ?? []
  } catch (e) {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const fetchModels = async () => {
  try {
    const res: any = await request.get('/models')
    const list = res?.data ?? res ?? []
    models.value = Array.isArray(list) ? list : list.models ?? []
    activeModel.value = list.active ?? models.value.find((m: any) => m.active) ?? null
  } catch (e) {
    message.error(t('common.error'))
  }
}

const addProvider = async () => {
  saving.value = true
  try {
    await request.post('/providers', newProvider.value)
    message.success(t('common.success'))
    showAddProvider.value = false
    newProvider.value = { name: '', base_url: '', api_key: '', models: [] }
    await fetchProviders()
  } catch (e) {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

const testConnection = async (id: string) => {
  testingId.value = id
  try {
    await request.post(`/providers/${id}/test`)
    message.success(t('common.success'))
  } catch (e) {
    message.error(t('common.error'))
  } finally {
    testingId.value = null
  }
}

const discoverModels = async (id: string) => {
  testingId.value = id
  try {
    await request.post(`/providers/${id}/discover`)
    message.success(t('common.success'))
    await fetchModels()
  } catch (e) {
    message.error(t('common.error'))
  } finally {
    testingId.value = null
  }
}

const switchModel = (model: any) => {
  selectedModelId.value = model.id
  showSwitchModel.value = true
}

const confirmSwitchModel = async () => {
  try {
    await request.post('/models/switch', { model_id: selectedModelId.value })
    message.success(t('common.success'))
    showSwitchModel.value = false
    await fetchModels()
  } catch (e) {
    message.error(t('common.error'))
  }
}

onMounted(() => {
  fetchProviders()
  fetchModels()
})
</script>

<style scoped>
.model-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.section-header { display: flex; justify-content: space-between; align-items: center; }
.section-header h3 { font-size: 16px; font-weight: 600; color: var(--nr-text-primary); margin: 0; }
.providers-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.provider-header { display: flex; justify-content: space-between; align-items: center; }
.provider-name { font-weight: 600; color: var(--nr-text-primary); }
.provider-body { display: flex; flex-direction: column; gap: 4px; }
.provider-url { font-size: 12px; color: var(--nr-text-tertiary); font-family: var(--nr-font-mono); word-break: break-all; }
.provider-models { font-size: 12px; color: var(--nr-text-secondary); }
.provider-actions { display: flex; gap: 8px; }
.active-model { display: flex; justify-content: space-between; align-items: center; }
.active-model-info { display: flex; flex-direction: column; gap: 4px; }
.model-name { font-weight: 600; font-size: 16px; color: var(--nr-text-primary); }
.model-provider { font-size: 12px; color: var(--nr-text-tertiary); }
</style>
