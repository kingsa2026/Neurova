<template>
  <div class="tool-layer-page">
    <h2 class="page-title">{{ t('tool.title') }}</h2>

    <a-tabs v-model:activeKey="activeTab">
      <!-- MCP Servers tab -->
      <a-tab-pane key="servers" :tab="t('tool.mcpServers')">
        <div class="section-header">
          <span />
          <GlassButton variant="primary" size="sm" @click="showRegister = true">
            {{ t('tool.register') }}
          </GlassButton>
        </div>
        <a-spin :spinning="loadingServers">
          <div class="servers-grid">
            <GlassCard v-for="server in servers" :key="server.id" variant="default">
              <template #header>
                <div class="server-header">
                  <span class="server-name">{{ server.name }}</span>
                  <a-tag :color="server.status === 'connected' ? 'green' : server.status === 'error' ? 'red' : 'default'">
                    {{ server.status }}
                  </a-tag>
                </div>
              </template>
              <div class="server-body">
                <p class="server-url">{{ server.url }}</p>
                <p class="server-tools">{{ server.tool_count || 0 }} {{ t('tool.tools').toLowerCase() }}</p>
              </div>
              <template #footer>
                <div class="server-actions">
                  <GlassButton variant="ghost" size="sm" @click="testServer(server.id)">
                    {{ t('common.refresh') }}
                  </GlassButton>
                  <GlassButton variant="danger" size="sm" @click="unregisterServer(server.id)">
                    {{ t('common.delete') }}
                  </GlassButton>
                </div>
              </template>
            </GlassCard>
          </div>
          <a-empty v-if="!servers.length && !loadingServers" :description="t('common.noData')" />
        </a-spin>
      </a-tab-pane>

      <!-- Tools list tab -->
      <a-tab-pane key="tools" :tab="t('tool.tools')">
        <a-spin :spinning="loadingTools">
          <a-table :columns="toolColumns" :data-source="tools" row-key="id" :pagination="{ pageSize: 15 }" size="small">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'status'">
                <a-badge :status="record.enabled ? 'success' : 'default'" :text="record.enabled ? t('common.active') : t('common.inactive')" />
              </template>
              <template v-if="column.key === 'actions'">
                <GlassButton variant="ghost" size="sm" @click="executeTool(record)">
                  {{ t('tool.execute') }}
                </GlassButton>
              </template>
            </template>
          </a-table>
        </a-spin>
      </a-tab-pane>

      <!-- Public tools tab -->
      <a-tab-pane key="public" :tab="t('tool.public')">
        <a-spin :spinning="loadingTools">
          <a-table :columns="toolColumns" :data-source="publicTools" row-key="id" :pagination="{ pageSize: 15 }" size="small">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'actions'">
                <GlassButton variant="ghost" size="sm" @click="installTool(record)">
                  {{ t('skill.install') }}
                </GlassButton>
              </template>
            </template>
          </a-table>
        </a-spin>
      </a-tab-pane>
    </a-tabs>

    <!-- Register server modal -->
    <a-modal v-model:open="showRegister" :title="t('tool.register')" @ok="registerServer" :confirm-loading="saving">
      <a-form layout="vertical" :model="newServer">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="newServer.name" />
        </a-form-item>
        <a-form-item label="URL">
          <a-input v-model:value="newServer.url" placeholder="http://localhost:3000" />
        </a-form-item>
        <a-form-item label="Auth Token">
          <a-input-password v-model:value="newServer.auth_token" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Execute tool modal -->
    <a-modal v-model:open="showExecute" :title="t('tool.execute')" @ok="runTool" :confirm-loading="executing">
      <p v-if="selectedTool" class="exec-tool-name">{{ selectedTool.name }}</p>
      <a-form-item label="Parameters (JSON)">
        <a-textarea v-model:value="toolParams" :rows="6" placeholder='{"key": "value"}' />
      </a-form-item>
      <div v-if="execResult" class="exec-result">
        <pre>{{ execResult }}</pre>
      </div>
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

const activeTab = ref('servers')
const loadingServers = ref(false)
const loadingTools = ref(false)
const saving = ref(false)
const executing = ref(false)
const servers = ref<any[]>([])
const tools = ref<any[]>([])
const publicTools = ref<any[]>([])
const showRegister = ref(false)
const showExecute = ref(false)
const selectedTool = ref<any>(null)
const toolParams = ref('{}')
const execResult = ref('')

const newServer = ref({ name: '', url: '', auth_token: '' })

const toolColumns = computed(() => [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('common.description'), dataIndex: 'description', key: 'description', ellipsis: true },
  { title: t('common.type'), dataIndex: 'type', key: 'type' },
  { title: t('common.status'), key: 'status' },
  { title: t('common.actions'), key: 'actions', width: 140 },
])

const fetchServers = async () => {
  loadingServers.value = true
  try {
    const res: any = await request.get('/tool-layers/mcp-servers')
    servers.value = res?.data ?? res ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingServers.value = false
  }
}

const fetchTools = async () => {
  loadingTools.value = true
  try {
    const res: any = await request.get('/tool-layers/tools')
    const list = res?.data ?? res ?? []
    tools.value = Array.isArray(list) ? list : list.tools ?? []
    publicTools.value = tools.value.filter((tool: any) => tool.public)
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingTools.value = false
  }
}

const registerServer = async () => {
  saving.value = true
  try {
    await request.post('/tool-layers/mcp-servers', newServer.value)
    message.success(t('common.success'))
    showRegister.value = false
    newServer.value = { name: '', url: '', auth_token: '' }
    await fetchServers()
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

const unregisterServer = async (id: string) => {
  try {
    await request.delete(`/tool-layers/mcp-servers/${id}`)
    message.success(t('common.success'))
    await fetchServers()
  } catch {
    message.error(t('common.error'))
  }
}

const testServer = async (id: string) => {
  try {
    await request.post(`/tool-layers/mcp-servers/${id}/test`)
    message.success(t('common.success'))
    await fetchServers()
  } catch {
    message.error(t('common.error'))
  }
}

const executeTool = (tool: any) => {
  selectedTool.value = tool
  toolParams.value = '{}'
  execResult.value = ''
  showExecute.value = true
}

const installTool = async (tool: any) => {
  try {
    await request.post('/tool-layers/tools/install', { tool_id: tool.id })
    message.success(t('common.success'))
    await fetchTools()
  } catch {
    message.error(t('common.error'))
  }
}

const runTool = async () => {
  executing.value = true
  try {
    const params = JSON.parse(toolParams.value)
    const res: any = await request.post(`/tool-layers/tools/${selectedTool.value.id}/execute`, params)
    execResult.value = JSON.stringify(res?.data ?? res, null, 2)
  } catch (e: any) {
    execResult.value = e.message || t('common.error')
  } finally {
    executing.value = false
  }
}

onMounted(() => {
  fetchServers()
  fetchTools()
})
</script>

<style scoped>
.tool-layer-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.section-header { display: flex; justify-content: flex-end; margin-bottom: 16px; }
.servers-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.server-header { display: flex; justify-content: space-between; align-items: center; }
.server-name { font-weight: 600; color: var(--nr-text-primary); }
.server-body { display: flex; flex-direction: column; gap: 4px; }
.server-url { font-size: 12px; color: var(--nr-text-tertiary); font-family: var(--nr-font-mono); word-break: break-all; }
.server-tools { font-size: 12px; color: var(--nr-text-secondary); }
.server-actions { display: flex; gap: 8px; }
.exec-tool-name { font-weight: 600; color: var(--nr-text-primary); margin-bottom: 12px; }
.exec-result { margin-top: 12px; padding: 12px; background: rgba(0,0,0,0.3); border-radius: 8px; max-height: 200px; overflow: auto; }
.exec-result pre { margin: 0; font-size: 12px; color: var(--nr-text-secondary); font-family: var(--nr-font-mono); white-space: pre-wrap; }
</style>
