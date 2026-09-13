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
            <GlassCard               v-for="server in pagedServers" :key="server.server_id" variant="default">
              <template #header>
                <div class="server-header">
                  <span class="server-name">{{ server.name }}</span>
                  <a-tag :color="server.status === 'connected' ? 'green' : server.status === 'error' ? 'red' : 'default'">
                    {{ server.status }}
                  </a-tag>
                </div>
              </template>
              <div class="server-body">
                <p class="server-url">{{ server.transport }}{{ server.url ? ` · ${server.url}` : '' }}</p>
                <p class="server-tools">{{ server.tools_count || 0 }} {{ t('tool.tools').toLowerCase() }}</p>
              </div>
              <template #footer>
                <div class="server-actions">
                  <GlassButton
                    v-if="server.oauth_grant === 'authorization_code'"
                    variant="ghost" size="sm"
                    :loading="authorizingId === server.server_id"
                    @click="authorizeServer(server.server_id)"
                  >
                    {{ t('tool.oauthAuthorize') }}
                  </GlassButton>
                  <GlassButton variant="ghost" size="sm" @click="testServer(server.server_id)">
                    {{ t('common.refresh') }}
                  </GlassButton>
                  <a-popconfirm :title="t('common.confirm') + '?'" @confirm="unregisterServer(server.server_id)">
                    <GlassButton variant="danger" size="sm">
                      {{ t('common.delete') }}
                    </GlassButton>
                  </a-popconfirm>
                </div>
              </template>
            </GlassCard>
          </div>
          <a-pagination v-if="servers.length > pageSize" v-model:current="currentPage" :pageSize="pageSize" :total="servers.length" size="small" style="margin-top: 16px; text-align: center" />
          <a-empty v-if="!servers.length && !loadingServers" :description="t('common.noData')" />
        </a-spin>
      </a-tab-pane>

      <!-- Tools list tab -->
      <a-tab-pane key="tools" :tab="t('tool.tools')">
        <a-spin :spinning="loadingTools">
          <a-table :columns="toolColumns" :data-source="tools" row-key="id" :pagination="{ pageSize: 15 }" size="small">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'">
                <span>{{ record.name }}</span>
                <a-tag v-if="record.sandbox_required" color="orange" style="margin-left: 6px">
                  {{ t('tool.sandboxRequired') }}
                </a-tag>
              </template>
              <template v-else-if="column.key === 'status'">
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

      <!-- MCP 工具包白名单目录（P0-2）：精选能力包一键安装 -->
      <a-tab-pane key="catalog" :tab="t('tool.toolkits')">
        <a-spin :spinning="loadingCatalog">
          <div class="servers-grid">
            <GlassCard v-for="entry in catalog" :key="entry.id" variant="default">
              <template #header>
                <div class="server-header">
                  <span class="server-name">{{ entry.name }}</span>
                  <a-tag v-if="entry.requires" color="blue">{{ t('tool.requires') }}: {{ entry.requires }}</a-tag>
                </div>
              </template>
              <div class="server-body">
                <p class="server-tools">{{ entry.description }}</p>
                <p class="server-url">{{ entry.source }}</p>
              </div>
              <template #footer>
                <div class="server-actions">
                  <GlassButton variant="primary" size="sm" @click="openInstall(entry)">
                    {{ t('skill.install') }}
                  </GlassButton>
                </div>
              </template>
            </GlassCard>
          </div>
          <a-empty v-if="!catalog.length && !loadingCatalog" :description="t('common.noData')" />
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
      <a-form layout="vertical" :model="newServer" :rules="{ name: [{ required: true, message: t('common.required') }], url: [{ required: true, message: t('common.required') }] }">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="newServer.name" />
        </a-form-item>
        <a-form-item :label="t('tool.serverUrl')">
          <a-input v-model:value="newServer.url" placeholder="http://localhost:3000" />
        </a-form-item>
        <a-form-item :label="t('tool.authToken')">
          <a-input-password v-model:value="newServer.auth_token" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 工具包安装弹窗（P0-2）：按目录条目的 required_secrets 动态收凭据 -->
    <a-modal
      v-model:open="showInstall"
      :title="`${t('skill.install')} · ${installingEntry?.name || ''}`"
      :confirm-loading="installing"
      @ok="confirmInstall"
    >
      <a-alert
        v-if="installingEntry?.requires === 'docker'"
        type="warning"
        :message="`${t('tool.requires')}: Docker`"
        style="margin-bottom: 12px"
      />
      <a-alert
        v-for="spec in (installingEntry?.required_secrets || []).filter((s: any) => s.read_only_required)"
        :key="spec.key"
        type="error"
        :message="t('tool.readOnlyRequired')"
        style="margin-bottom: 12px"
      />
      <p class="server-tools" style="margin-bottom: 12px">{{ t('tool.catalogSecrets') }}</p>
      <a-form layout="vertical" :model="installSecrets">
        <a-form-item
          v-for="spec in (installingEntry?.required_secrets || [])"
          :key="spec.key"
          :label="spec.prompt"
          :required="spec.required"
        >
          <a-input-password v-model:value="installSecrets[spec.key]" :placeholder="spec.key" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Execute tool modal -->
    <a-modal v-model:open="showExecute" :title="t('tool.execute')" @ok="runTool" :confirm-loading="executing">
      <p v-if="selectedTool" class="exec-tool-name">{{ selectedTool.name }}</p>
      <a-form-item :label="t('tool.parameters')">
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
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'
import {
  listMCPServers, listTools, registerMCPServer, unregisterMCPServer, testMCPServer, authorizeMCPOAuth, installTool as installToolApi, executeTool as executeToolApi,
  listMCPCatalog, installMCPCatalogEntry,
  type MCPServer, type Tool, type MCPCatalogEntry,
} from '@/api/modules/tool-layers'

const { t } = useI18n()

const activeTab = ref('servers')
const loadingServers = ref(false)
const loadingTools = ref(false)
const saving = ref(false)
const executing = ref(false)
const servers = ref<MCPServer[]>([])
const tools = ref<Tool[]>([])
const publicTools = ref<Tool[]>([])
const showRegister = ref(false)
const showExecute = ref(false)
const selectedTool = ref<Tool | null>(null)
const toolParams = ref('{}')
const execResult = ref('')
const currentPage = ref(1)
const pageSize = ref(12)

const newServer = ref({ name: '', url: '', auth_token: '' })

const pagedServers = computed(() =>
  servers.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value),
)

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
    const res = await listMCPServers()
    servers.value = res ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingServers.value = false
  }
}

const fetchTools = async () => {
  loadingTools.value = true
  try {
    const list = await listTools()
    tools.value = Array.isArray(list) ? list : []
    publicTools.value = tools.value.filter((tool) => tool.public)
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingTools.value = false
  }
}

const registerServer = async () => {
  saving.value = true
  try {
    await registerMCPServer(newServer.value)
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
    await unregisterMCPServer(id)
    message.success(t('common.success'))
    await fetchServers()
  } catch {
    message.error(t('common.error'))
  }
}

const authorizingId = ref<string | null>(null)

const authorizeServer = async (id: string) => {
  const key = `oauth-${id}`
  authorizingId.value = id
  message.loading({ content: t('tool.oauthAuthorize'), key, duration: 0 })
  try {
    await authorizeMCPOAuth(id)
    message.success({ content: t('common.success'), key })
  } catch (e: any) {
    message.error({
      content: e?.response?.data?.detail || e?.message || t('common.error'),
      key,
      duration: 6,
    })
  } finally {
    authorizingId.value = null
  }
}

const testServer = async (id: string) => {
  try {
    await testMCPServer(id)
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
    await installToolApi(tool.id)
    message.success(t('common.success'))
    await fetchTools()
  } catch {
    message.error(t('common.error'))
  }
}

const runTool = async () => {
  if (!selectedTool.value) return
  executing.value = true
  try {
    const params = JSON.parse(toolParams.value)
    const res = await executeToolApi(selectedTool.value.id, params)
    execResult.value = JSON.stringify(res, null, 2)
  } catch (e: any) {
    execResult.value = e.message || t('common.error')
  } finally {
    executing.value = false
  }
}

// ── MCP 工具包白名单目录（P0-2）──
const loadingCatalog = ref(false)
const installing = ref(false)
const showInstall = ref(false)
const catalog = ref<MCPCatalogEntry[]>([])
const installingEntry = ref<MCPCatalogEntry | null>(null)
const installSecrets = ref<Record<string, string>>({})

const fetchCatalog = async () => {
  loadingCatalog.value = true
  try {
    const res = await listMCPCatalog()
    catalog.value = Array.isArray(res) ? res : []
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingCatalog.value = false
  }
}

const openInstall = (entry: MCPCatalogEntry) => {
  installingEntry.value = entry
  installSecrets.value = {}
  showInstall.value = true
}

const confirmInstall = async () => {
  if (!installingEntry.value) return
  installing.value = true
  try {
    await installMCPCatalogEntry(installingEntry.value.id, installSecrets.value)
    message.success(t('common.success'))
    showInstall.value = false
    await fetchServers()
    activeTab.value = 'servers'
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || t('common.error'))
  } finally {
    installing.value = false
  }
}

onMounted(() => {
  fetchServers()
  fetchTools()
  fetchCatalog()
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
