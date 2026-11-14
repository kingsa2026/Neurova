<template>
  <div class="enterprise-sources-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('ontology.entTitle') }}</h2>
        <p class="page-subtitle">{{ t('ontology.entSubtitle') }}</p>
      </div>
      <GlassButton v-if="isAdmin" variant="primary" size="sm" data-testid="ent-add-btn" @click="openCreate">
        {{ t('ontology.entAddBtn') }}
      </GlassButton>
    </div>

    <!-- 连接器列表 -->
    <GlassPanel :title="t('ontology.entListTitle')">
      <div v-if="listError" class="honest-note honest-note--error" data-testid="ent-list-error">
        {{ t('ontology.entListFailed') }}
      </div>
      <a-table
        :columns="columns"
        :data-source="sources"
        :loading="loading"
        row-key="source_id"
        :pagination="sources.length > 10 ? { pageSize: 10 } : false"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'source_id'">
            <span class="mono source-id">{{ record.source_id }}</span>
          </template>
          <template v-else-if="column.key === 'type'">
            <a-tag color="geekblue" data-testid="ent-type-tag">{{ typeLabel(record) }}</a-tag>
            <a-tag v-if="vendorLabel(record)" color="blue">{{ vendorLabel(record) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'created_at'">
            <span class="mono">{{ formatTime(record.created_at) }}</span>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-badge
              :status="statusBadge(record.source_id).status"
              :text="statusBadge(record.source_id).text"
              data-testid="ent-health-badge"
            />
            <GlassButton
              v-if="isAdmin"
              variant="ghost"
              size="sm"
              class="status-check-btn"
              :loading="healthMap[record.source_id] === 'checking'"
              data-testid="ent-health-btn"
              @click="checkHealth(record.source_id)"
            >{{ t('ontology.entTestBtn') }}</GlassButton>
          </template>
          <template v-else-if="column.key === 'ingested_count'">
            <span class="mono" data-testid="ent-count">{{ record.ingested_count ?? 0 }}</span>
          </template>
          <template v-else-if="column.key === 'enabled'">
            <a-switch
              :checked="record.enabled"
              :disabled="!isAdmin || togglingId === record.source_id"
              size="small"
              data-testid="ent-enabled-tag"
              @change="() => toggleEnabled(record)"
            />
          </template>
          <template v-else-if="column.key === 'actions'">
            <div v-if="isAdmin" class="action-btns">
              <GlassButton
                variant="ghost" size="sm"
                :loading="ingestingId === record.source_id"
                data-testid="ent-ingest-btn"
                @click="triggerIngest(record.source_id)"
              >{{ t('ontology.entIngestBtn') }}</GlassButton>
              <GlassButton
                v-if="record.descriptor?.chatSource === 'archive'"
                variant="ghost" size="sm"
                data-testid="ent-media-btn"
                @click="openMediaFetch(record)"
              >{{ t('ontology.entMediaBtn') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" data-testid="ent-edit-btn" @click="openEdit(record)">
                {{ t('common.edit') }}
              </GlassButton>
              <a-popconfirm :title="t('ontology.entDeleteConfirm')" @confirm="removeSource(record.source_id)">
                <GlassButton variant="danger" size="sm" data-testid="ent-delete-btn">
                  {{ t('common.delete') }}
                </GlassButton>
              </a-popconfirm>
            </div>
            <span v-else class="mono">—</span>
          </template>
        </template>
        <template #empty><a-empty :description="t('ontology.entListEmpty')" /></template>
      </a-table>
    </GlassPanel>

    <!-- 诚实态说明：配置落库 ≠ 适配器已接通 -->
    <GlassPanel :title="t('ontology.entFakeAdapterTitle')">
      <p class="honest-note">{{ t('ontology.entFakeAdapterNote') }}</p>
    </GlassPanel>

    <!-- 媒体取回弹层（存档源逐条触发） -->
    <a-modal
      v-model:open="showMediaModal"
      :title="t('ontology.entMediaBtn')"
      width="480px"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('ontology.entMediaMsgId')" required>
          <p class="field-hint">{{ t('ontology.entMediaMsgIdHint') }}</p>
          <a-input v-model:value="mediaMsgId" data-testid="ent-media-msgid" />
        </a-form-item>
        <p v-if="mediaOutcome" class="honest-note" data-testid="ent-media-outcome">{{ mediaOutcome }}</p>
      </a-form>
      <template #footer>
        <GlassButton variant="secondary" size="sm" @click="showMediaModal = false">
          {{ t('common.cancel') }}
        </GlassButton>
        <GlassButton variant="primary" size="sm" :loading="mediaBusy" data-testid="ent-media-confirm"
          @click="runMediaFetch">
          {{ t('ontology.entMediaBtn') }}
        </GlassButton>
      </template>
    </a-modal>

    <!-- 新增/编辑向导（分步弹层） -->
    <a-modal
      v-model:open="showWizard"
      :title="wizardTitle"
      width="680px"
      :footer="null"
      :mask-closable="false"
    >
      <a-steps :current="wizardStep" size="small" class="wizard-steps" data-testid="ent-wizard-steps">
        <a-step :title="t('ontology.entStepKind')" />
        <a-step :title="t('ontology.entStepConnection')" />
        <a-step :title="t('ontology.entStepMapping')" />
        <a-step :title="t('ontology.entStepConfirm')" />
      </a-steps>

      <!-- 步 0：选连接对象 -->
      <div v-if="wizardStep === 0" class="kind-cards" data-testid="ent-kind-cards">
        <div
          v-for="card in KIND_CARDS"
          :key="card.kind"
          class="kind-card"
          :class="{ active: wizardForm.kind === card.kind }"
          @click="wizardForm.kind = card.kind"
        >
          <div class="kind-name">{{ t(card.labelKey) }}</div>
          <div class="kind-desc">{{ t(card.descKey) }}</div>
        </div>
      </div>

      <!-- 步 1：连接参数 -->
      <div v-else-if="wizardStep === 1" class="wizard-form">
        <a-form layout="vertical">
          <a-form-item :label="t('ontology.entSourceId')" required>
            <a-input
              v-model:value="wizardForm.source_id"
              :disabled="!!editingSource"
              data-testid="ent-wizard-source-id"
            />
          </a-form-item>

          <!-- 湖仓/HTTP（W10）：base_url＋credentialEnv 指针＋kind 专属字段 -->
          <template v-if="isLakehouseKind(wizardForm.kind)">
            <a-form-item :label="t('ontology.entKindBaseUrl')" required>
              <a-input v-model:value="wizardForm.base_url" data-testid="ent-base-url" />
            </a-form-item>
            <a-form-item :label="t('ontology.entKindCredentialEnv')">
              <a-input v-model:value="wizardForm.credentialEnv" data-testid="ent-cred-env" />
            </a-form-item>
            <a-form-item v-if="wizardForm.kind === 'unity_catalog'" :label="t('ontology.entKindUnityTable')" required>
              <a-input v-model:value="wizardForm.table" data-testid="ent-uc-table" />
            </a-form-item>
            <a-form-item v-if="wizardForm.kind === 'snowflake'" :label="t('ontology.entKindSfQuery')" required>
              <a-input v-model:value="wizardForm.sf_query" data-testid="ent-sf-query" />
            </a-form-item>
            <a-form-item v-if="wizardForm.kind === 'snowflake'" :label="t('ontology.entKindSfWatermark')">
              <a-input v-model:value="wizardForm.watermark_column" data-testid="ent-sf-watermark" />
            </a-form-item>
            <a-form-item v-if="wizardForm.kind === 'sap_odata'" :label="t('ontology.entKindSapEntitySet')" required>
              <a-input v-model:value="wizardForm.entity_set" data-testid="ent-sap-entity" />
            </a-form-item>
            <a-form-item v-if="wizardForm.kind === 'http_pull'" :label="t('ontology.entKindHttpUrl')" required>
              <a-input v-model:value="wizardForm.url" data-testid="ent-http-url" />
            </a-form-item>
          </template>
          <!-- 数据库（sql） -->
          <template v-if="wizardForm.kind === 'sql'">
            <a-row :gutter="12">
              <a-col :span="12">
                <a-form-item :label="t('ontology.entVariantDriver')" required>
                  <a-select v-model:value="wizardForm.driver" :options="SQL_DRIVERS" />
                </a-form-item>
              </a-col>
              <a-col :span="12">
                <a-form-item :label="t('ontology.entKindCursorColumn')" required>
                  <a-input v-model:value="wizardForm.cursorColumn" />
                </a-form-item>
              </a-col>
            </a-row>
            <a-row :gutter="12">
              <a-col v-if="wizardForm.driver !== 'sqlite'" :span="12">
                <a-form-item :label="t('ontology.entKindHost')" required>
                  <a-input v-model:value="wizardForm.host" />
                </a-form-item>
              </a-col>
              <a-col v-if="wizardForm.driver !== 'sqlite'" :span="12">
                <a-form-item :label="t('ontology.entKindPort')">
                  <a-input v-model:value="wizardForm.port" />
                </a-form-item>
              </a-col>
            </a-row>
            <a-form-item :label="t('ontology.entKindDatabase')" required>
              <a-input v-model:value="wizardForm.database" :placeholder="t('ontology.entKindDatabaseHint')" />
            </a-form-item>
            <a-form-item :label="t('ontology.entKindTableOrQuery')" required>
              <a-radio-group v-model:value="wizardForm.sqlMode">
                <a-radio value="table">{{ t('ontology.entKindTable') }}</a-radio>
                <a-radio value="query">{{ t('ontology.entKindQuery') }}</a-radio>
              </a-radio-group>
              <a-input v-if="wizardForm.sqlMode === 'table'" v-model:value="wizardForm.table" />
              <a-textarea v-else v-model:value="wizardForm.query" :rows="3" :placeholder="t('ontology.entKindQueryHint')" />
            </a-form-item>
            <a-form-item :label="t('ontology.entKindCredentialEnv')">
              <p class="field-hint">{{ t('ontology.entKindCredentialEnvHint') }}</p>
              <a-textarea v-model:value="wizardForm.credentialEnv" :rows="2" />
            </a-form-item>
          </template>

          <!-- ERP（erp_api） -->
          <template v-else-if="wizardForm.kind === 'erp'">
            <a-form-item :label="t('ontology.entVariantVendor')" required>
              <a-radio-group v-model:value="wizardForm.vendor">
                <a-radio value="kingdee">{{ t('ontology.entVendorKingdee') }}</a-radio>
                <a-radio value="yongyou">{{ t('ontology.entVendorYongyou') }}</a-radio>
              </a-radio-group>
            </a-form-item>
            <a-form-item :label="t('ontology.entKindBaseUrl')" required>
              <a-input v-model:value="wizardForm.baseUrl" />
            </a-form-item>
            <a-form-item v-if="wizardForm.vendor === 'kingdee'" :label="t('ontology.entKindFormId')" required>
              <a-input v-model:value="wizardForm.formId" />
            </a-form-item>
            <a-form-item v-if="wizardForm.vendor === 'yongyou'" :label="t('ontology.entKindTokenPath')">
              <a-input v-model:value="wizardForm.tokenPath" :placeholder="t('ontology.entKindPathOptional')" />
            </a-form-item>
            <a-form-item :label="t('ontology.entKindCredentialEnv')" required>
              <p class="field-hint">{{ t('ontology.entKindCredentialEnvErpHint') }}</p>
              <a-textarea v-model:value="wizardForm.credentialEnv" :rows="2" />
            </a-form-item>
          </template>

          <!-- 企微 / 微信小微（chat）：来源两态（批 C7c 甲案） -->
          <template v-else-if="wizardForm.kind === 'wecom' || wizardForm.kind === 'wechat'">
            <a-form-item :label="t('ontology.entChatSource')" required>
              <a-radio-group v-model:value="wizardForm.chatSource" data-testid="ent-chat-source">
                <a-radio value="capture">{{ t('ontology.entChatSourceCapture') }}</a-radio>
                <a-radio value="archive" :disabled="wizardForm.kind === 'wechat'">
                  {{ t('ontology.entChatSourceArchive') }}
                </a-radio>
              </a-radio-group>
              <p class="field-hint">{{ t('ontology.entChatSourceHint') }}</p>
            </a-form-item>
            <a-form-item v-if="wizardForm.chatSource === 'capture'" :label="t('ontology.entKindIngressDb')">
              <p class="field-hint">{{ t('ontology.entKindIngressDbHint') }}</p>
              <a-input v-model:value="wizardForm.ingressDb" :placeholder="t('ontology.entKindPathOptional')" />
            </a-form-item>
            <template v-if="wizardForm.chatSource === 'archive'">
              <a-form-item :label="t('ontology.entArchiveSdkPath')" required>
                <p class="field-hint">{{ t('ontology.entArchiveSdkPathHint') }}</p>
                <a-input v-model:value="wizardForm.archiveSdkPath" data-testid="ent-archive-sdk" />
              </a-form-item>
              <a-form-item :label="t('ontology.entArchiveSecretEnv')" required>
                <p class="field-hint">{{ t('ontology.entArchiveSecretEnvHint') }}</p>
                <a-input v-model:value="wizardForm.archiveSecretEnv" data-testid="ent-archive-secret" />
              </a-form-item>
              <a-form-item :label="t('ontology.entArchivePrivateKeys')" required>
                <p class="field-hint">{{ t('ontology.entArchivePrivateKeysHint') }}</p>
                <a-textarea v-model:value="wizardForm.archivePrivateKeys" :rows="2" data-testid="ent-archive-keys" />
              </a-form-item>
              <a-form-item :label="t('ontology.entArchiveRoomAllowlist')">
                <p class="field-hint">{{ t('ontology.entArchiveAllowlistHint') }}</p>
                <a-textarea v-model:value="wizardForm.archiveRoomAllowlist" :rows="2" />
              </a-form-item>
              <a-form-item :label="t('ontology.entArchiveUserAllowlist')">
                <a-textarea v-model:value="wizardForm.archiveUserAllowlist" :rows="2" />
              </a-form-item>
            </template>
          </template>

          <!-- 文件（file） -->
          <template v-else-if="wizardForm.kind === 'file'">
            <a-form-item :label="t('ontology.entVariantFormat')" required>
              <a-select v-model:value="wizardForm.format" :options="FILE_FORMATS" />
            </a-form-item>
            <a-form-item :label="t('ontology.entVariantPath')" required>
              <a-input v-model:value="wizardForm.path" />
            </a-form-item>
          </template>
        </a-form>
      </div>

      <!-- 步 2：字段映射 -->
      <div v-else-if="wizardStep === 2" class="wizard-form">
        <a-form layout="vertical">
          <a-form-item :label="t('ontology.entColumns')" required>
            <a-input v-model:value="wizardForm.columns" :placeholder="t('ontology.entColumnsHint')" />
          </a-form-item>
          <a-form-item :label="t('ontology.entSubject')" required>
            <a-radio-group v-model:value="wizardForm.subjectMode">
              <a-radio value="column">{{ t('ontology.entSubjectColumn') }}</a-radio>
              <a-radio value="template">{{ t('ontology.entSubjectTemplate') }}</a-radio>
            </a-radio-group>
            <a-input v-if="wizardForm.subjectMode === 'column'" v-model:value="wizardForm.subjectColumn" />
            <a-input v-else v-model:value="wizardForm.subjectTemplate" placeholder="order:{order_id}" />
          </a-form-item>
          <a-form-item :label="t('ontology.entPredicate')" required>
            <a-input v-model:value="wizardForm.predicateTermId" :placeholder="t('ontology.entPredicateHint')" />
          </a-form-item>
          <a-form-item :label="t('ontology.entObject')" required>
            <a-select v-model:value="wizardForm.objectKind" :options="OBJECT_KINDS" />
            <a-input v-model:value="wizardForm.objectValue" class="object-value" />
          </a-form-item>
          <a-form-item :label="t('ontology.entQualifiers')">
            <a-input v-model:value="wizardForm.qualifiers" placeholder="name=column" />
          </a-form-item>
          <a-row :gutter="12">
            <a-col :span="12">
              <a-form-item :label="t('ontology.entValidFrom')">
                <a-input v-model:value="wizardForm.validFrom" />
              </a-form-item>
            </a-col>
            <a-col :span="12">
              <a-form-item :label="t('ontology.entValidUntil')">
                <a-input v-model:value="wizardForm.validUntil" />
              </a-form-item>
            </a-col>
          </a-row>
        </a-form>
      </div>

      <!-- 步 3：确认与测试 -->
      <div v-else class="wizard-confirm">
        <a-descriptions size="small" :column="1" bordered>
          <a-descriptions-item :label="t('ontology.entSourceId')">
            <span class="mono">{{ wizardForm.source_id }}</span>
          </a-descriptions-item>
          <a-descriptions-item :label="t('ontology.entSourceType')">
            {{ t(typeCardOf(wizardForm.kind).labelKey) }}
          </a-descriptions-item>
          <a-descriptions-item :label="t('ontology.entColumns')">
            <span class="mono">{{ wizardForm.columns }}</span>
          </a-descriptions-item>
          <a-descriptions-item :label="t('ontology.entPredicate')">
            <span class="mono">{{ wizardForm.predicateTermId }}</span>
          </a-descriptions-item>
        </a-descriptions>
        <a-form-item :label="t('ontology.entEnabled')" class="confirm-enabled">
          <a-switch v-model:checked="wizardForm.enabled" />
        </a-form-item>
        <div class="test-row">
          <GlassButton
            variant="secondary"
            size="sm"
            :disabled="!editingSource"
            :loading="testingConnection"
            data-testid="ent-wizard-test-btn"
            @click="testConnectionInWizard"
          >{{ t('ontology.entTestBtn') }}</GlassButton>
          <span v-if="!editingSource" class="field-hint">{{ t('ontology.entTestOnlySaved') }}</span>
          <span v-else-if="wizardTestResult" class="mono test-result" :class="'test-' + wizardTestResult.status">
            {{ wizardTestResult.status }}{{ wizardTestResult.reason ? ' — ' + wizardTestResult.reason : '' }}
          </span>
        </div>
      </div>

      <!-- 向导底部按钮 -->
      <div class="wizard-footer">
        <GlassButton v-if="wizardStep > 0" variant="secondary" size="sm" @click="wizardStep--">
          {{ t('common.prev') }}
        </GlassButton>
        <GlassButton
          v-if="wizardStep < 3"
          variant="primary" size="sm"
          :disabled="!canProceed"
          data-testid="ent-wizard-next"
          @click="wizardStep++"
        >{{ t('common.next') }}</GlassButton>
        <GlassButton
          v-else
          variant="primary" size="sm"
          :loading="saving"
          :disabled="!isAdmin"
          data-testid="ent-wizard-save"
          @click="saveWizard"
        >{{ t('common.save') }}</GlassButton>
      </div>
    </a-modal>
    <!-- U5：webhook 接收面抽屉——密钥指纹掩码/轮换、模拟推送三态、幂等去重读数 -->
    <a-drawer v-model:open="webhookDrawerOpen" :title="t('ontology.entWebhookBtn')" width="480px"
              data-testid="webhook-drawer">
      <p class="honest-note">{{ t('ontology.entWebhookNote') }}</p>
      <div class="webhook-row" data-testid="webhook-enabled-readout">
        <span>{{ t('ontology.entWebhookEnabled') }}</span>
        <a-tag :color="webhookConfig?.enabled ? 'green' : 'red'" data-testid="webhook-enabled-tag">
          {{ webhookConfig?.enabled ? t('common.yes') : t('common.no') }}
        </a-tag>
      </div>
      <div class="webhook-row">
        <span>{{ t('ontology.entWebhookSecretEnv') }}</span>
        <span class="mono">{{ webhookConfig?.secret_env || '-' }}</span>
      </div>
      <div class="webhook-row" data-testid="webhook-fingerprint">
        <span>{{ t('ontology.entWebhookFingerprint') }}</span>
        <span class="mono">{{ webhookConfig?.secret_fingerprint || t('ontology.entWebhookNoSecret') }}</span>
      </div>
      <!-- P2-9：入站接收 URL（由前端 API 基址推导；验签由接收器 fail-closed 把关） -->
      <div class="webhook-row webhook-url-row" data-testid="webhook-receive-url">
        <span>{{ t('ontology.entWebhookReceiveUrl') }}</span>
        <span class="mono webhook-url">{{ webhookReceiveUrl }}</span>
      </div>
      <GlassButton variant="secondary" size="sm" :loading="webhookRotating" data-testid="webhook-rotate"
                   @click="doRotateSecret">{{ t('ontology.entWebhookRotate') }}</GlassButton>
      <a-divider>{{ t('ontology.entWebhookSimTitle') }}</a-divider>
      <div class="webhook-sim-actions">
        <GlassButton size="sm" :loading="webhookSimulating === 'ok'" data-testid="webhook-sim-ok"
                     @click="doSimulate('ok')">{{ t('ontology.entWebhookSimOk') }}</GlassButton>
        <GlassButton size="sm" :loading="webhookSimulating === 'duplicate'" data-testid="webhook-sim-duplicate"
                     @click="doSimulate('duplicate')">{{ t('ontology.entWebhookSimDuplicate') }}</GlassButton>
        <GlassButton size="sm" :loading="webhookSimulating === 'bad_signature'" data-testid="webhook-sim-bad"
                     @click="doSimulate('bad_signature')">{{ t('ontology.entWebhookSimBad') }}</GlassButton>
      </div>
      <pre v-if="webhookSimResult" class="mono webhook-result" data-testid="webhook-sim-result">{{ webhookSimResult }}</pre>
      <div class="webhook-row" data-testid="webhook-dedup-stats">
        <span>{{ t('ontology.entWebhookDedup') }}</span>
        <span class="mono">{{ t('ontology.entWebhookDedupValue', { rows: webhookDedup?.rows ?? 0, sources: webhookDedup?.sources ?? 0 }) }}</span>
      </div>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAuthStore } from '@/stores/auth'
import {
  deleteEnterpriseSource,
  getEnterpriseSourceHealth,
  listEnterpriseSources,
  submitEnterpriseSource,
  triggerEnterpriseIngest,
  triggerEnterpriseMedia,
  getWebhookConfig,
  rotateWebhookSecret,
  simulateWebhookPush,
  getWebhookDedupStats,
} from '@/api/modules/ontology'
import type { EnterpriseDescriptor, EnterpriseSourceConfig } from '@/types/ontology'
import { extractApiDetail } from '@/utils/error'
import { splitList } from '@/utils/ontologyFormat'
import config from '@/config'

const { t } = useI18n()
const authStore = useAuthStore()

const isAdmin = computed(() => {
  const user = authStore.user as { role?: string } | null | undefined
  return user?.role === 'admin'
})

// ── 列表 ────────────────────────────────────────────────────

const sources = ref<EnterpriseSourceConfig[]>([])
const loading = ref(false)
const listError = ref(false)
const ingestingId = ref('')
const togglingId = ref('')

/** 连接状态探测读数（行内"检测"按钮拉取；不自动全量探测——sql 连接可能挂起） */
const healthMap = ref<Record<string, { status: string; reason: string } | 'checking'>>({})

const columns = computed(() => [
  { title: t('ontology.entColConnector'), key: 'source_id' },
  { title: t('ontology.entColType'), key: 'type', width: 170 },
  { title: t('ontology.entColCreatedAt'), key: 'created_at', width: 170 },
  { title: t('ontology.entColStatus'), key: 'status', width: 220 },
  { title: t('ontology.entColCount'), key: 'ingested_count', width: 110 },
  { title: t('ontology.entColEnabled'), key: 'enabled', width: 80 },
  { title: t('ontology.entColActions'), key: 'actions', width: 250 },
])

const formatTime = (iso?: string) => (iso ? String(iso).replace('T', ' ').slice(0, 19) : '—')

const typeLabel = (row: EnterpriseSourceConfig) => {
  const d = row.descriptor as Record<string, string>
  if (d.sourceType === 'sql') return t('ontology.entTypeDatabase')
  if (d.sourceType === 'erp_api') return t('ontology.entTypeErp')
  if (d.sourceType === 'file') return t('ontology.entTypeFile')
  if (d.sourceType === 'chat') return d.vendor === 'wecom' ? t('ontology.entTypeWecom') : t('ontology.entTypeWechat')
  return String(d.sourceType || '—')
}

const vendorLabel = (row: EnterpriseSourceConfig) => {
  const d = row.descriptor as Record<string, string>
  if (d.sourceType === 'erp_api') return d.vendor === 'kingdee' ? t('ontology.entVendorKingdee') : t('ontology.entVendorYongyou')
  if (d.sourceType === 'chat') return d.vendor === 'wecom' ? t('ontology.entVendorWecom') : t('ontology.entVendorWechat')
  return ''
}

const statusBadge = (sourceId: string): { status: 'success' | 'warning' | 'error' | 'default'; text: string } => {
  const h = healthMap.value[sourceId]
  if (h === 'checking' || !h) return { status: 'default', text: t('ontology.entTestNotChecked') }
  const label = h.status === 'ok' ? t('ontology.entTestOk')
    : h.status === 'degraded' ? t('ontology.entTestDegraded')
    : t('ontology.entTestError')
  // 异常/受限时 reason 原话随徽标露出（不降级成笼统"异常"）
  return { status: h.status === 'ok' ? 'success' : h.status === 'degraded' ? 'warning' : 'error',
           text: h.reason ? `${label} — ${h.reason}` : label }
}

const loadSources = async () => {
  loading.value = true
  listError.value = false
  try {
    const res = await listEnterpriseSources()
    sources.value = res.data?.items ?? []
  } catch {
    listError.value = true
  } finally {
    loading.value = false
  }
}

const checkHealth = async (sourceId: string) => {
  healthMap.value[sourceId] = 'checking'
  try {
    const res = await getEnterpriseSourceHealth(sourceId)
    healthMap.value[sourceId] = {
      status: res.data?.status ?? 'error',
      reason: res.data?.reason ?? '',
    }
  } catch (err) {
    healthMap.value[sourceId] = { status: 'error', reason: extractApiDetail(err) || '' }
  }
}

const toggleEnabled = async (row: EnterpriseSourceConfig) => {
  togglingId.value = row.source_id
  try {
    await submitEnterpriseSource({
      source_id: row.source_id,
      descriptor: row.descriptor as unknown as EnterpriseDescriptor,
      enabled: !row.enabled,
    })
    await loadSources()
  } catch (err) {
    message.error(extractApiDetail(err) || t('common.error'))
  } finally {
    togglingId.value = ''
  }
}

const triggerIngest = async (sourceId: string) => {
  ingestingId.value = sourceId
  try {
    const res = await triggerEnterpriseIngest(sourceId)
    const result = res.data?.result as { admitted?: number; rejected?: number; truncated?: boolean; skipped?: boolean; reason?: string }
    if (result?.skipped) {
      message.info(`${t('ontology.entIngestSkipped')}: ${result.reason ?? ''}`)
    } else {
      message.success(
        `${t('ontology.entIngestResult')}: ${result?.admitted ?? 0} / ${result?.rejected ?? 0}` +
        (result?.truncated ? ` (${t('ontology.entIngestTruncated')})` : ''),
      )
    }
    await loadSources()
  } catch (err) {
    message.error(extractApiDetail(err) || t('common.error'))
  } finally {
    ingestingId.value = ''
  }
}

const removeSource = async (sourceId: string) => {
  try {
    await deleteEnterpriseSource(sourceId)
    message.success(t('ontology.entDeleteDone'))
    await loadSources()
  } catch (err) {
    message.error(extractApiDetail(err) || t('common.error'))
  }
}

// ── 向导（新增/编辑共用，四步） ──────────────────────────────

type ConnectKind = 'sql' | 'erp' | 'wecom' | 'wechat' | 'file' | 'unity_catalog' | 'snowflake' | 'sap_odata' | 'http_pull'

const KIND_CARDS: { kind: ConnectKind; labelKey: string; descKey: string }[] = [
  { kind: 'sql', labelKey: 'ontology.entTypeDatabase', descKey: 'ontology.entKindDatabaseDesc' },
  { kind: 'erp', labelKey: 'ontology.entTypeErp', descKey: 'ontology.entKindErpDesc' },
  { kind: 'wecom', labelKey: 'ontology.entTypeWecom', descKey: 'ontology.entKindWecomDesc' },
  { kind: 'wechat', labelKey: 'ontology.entTypeWechat', descKey: 'ontology.entKindWechatDesc' },
  { kind: 'file', labelKey: 'ontology.entTypeFile', descKey: 'ontology.entKindFileDesc' },
  // W10（specs/2026-11-12 §11）：湖仓三连接器＋http_pull（REST 面，零新增依赖）
  { kind: 'unity_catalog', labelKey: 'ontology.entTypeUnityCatalog', descKey: 'ontology.entKindUnityCatalogDesc' },
  { kind: 'snowflake', labelKey: 'ontology.entTypeSnowflake', descKey: 'ontology.entKindSnowflakeDesc' },
  { kind: 'sap_odata', labelKey: 'ontology.entTypeSapOdata', descKey: 'ontology.entKindSapOdataDesc' },
  { kind: 'http_pull', labelKey: 'ontology.entTypeHttpPull', descKey: 'ontology.entKindHttpPullDesc' },
]

const SQL_DRIVERS = ['postgresql', 'mysql', 'mssql', 'oracle', 'sqlite'].map((d) => ({ label: d, value: d }))
const FILE_FORMATS = ['csv', 'tsv', 'json', 'jsonl'].map((f) => ({ label: f, value: f }))
const OBJECT_KINDS = ['column', 'template', 'term', 'literal'].map((k) => ({
  label: t('ontology.entObjectKind') + ': ' + k, value: k,
}))

// U5：webhook 接收面抽屉（读数＋轮换＋模拟推送；凭据零明文——只回指纹）
const webhookDrawerOpen = ref(false)
const webhookConfig = ref<{ enabled: boolean; secret_env: string; secret_fingerprint: string } | null>(null)
const webhookDedup = ref<{ rows: number; sources: number } | null>(null)
const webhookRotating = ref(false)
const webhookSimulating = ref<'' | 'ok' | 'duplicate' | 'bad_signature'>('')
const webhookSimResult = ref('')

// P2-9：入站接收 URL——外部系统按此 URL 推送（POST，HMAC 头见后端契约）。
// 由前端 API 基址推导，不在后端响应里回传（部署面自己拼绝对地址即可）。
const webhookReceiveUrl = computed(() => {
  const base = config.apiBaseUrl || '/api/v1'
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  return `${origin}${base}/knowledge/ontology/webhook/receive`
})

async function openWebhookDrawer() {
  webhookDrawerOpen.value = true
  try {
    const res: any = await getWebhookConfig()
    webhookConfig.value = res?.data ?? null
  } catch {
    webhookConfig.value = null
  }
  try {
    const res: any = await getWebhookDedupStats()
    webhookDedup.value = res?.data ?? null
  } catch {
    webhookDedup.value = null
  }
}

async function doRotateSecret() {
  webhookRotating.value = true
  try {
    const res: any = await rotateWebhookSecret()
    if (webhookConfig.value && res?.data?.secret_fingerprint) {
      webhookConfig.value = { ...webhookConfig.value, secret_fingerprint: res.data.secret_fingerprint }
    }
    message.success(t('ontology.entWebhookRotated'))
  } catch (err) {
    message.error(extractApiDetail(err) || t('common.error'))
  } finally {
    webhookRotating.value = false
  }
}

async function doSimulate(mode: 'ok' | 'duplicate' | 'bad_signature') {
  webhookSimulating.value = mode
  try {
    const res: any = await simulateWebhookPush(mode)
    webhookSimResult.value = JSON.stringify(res?.data ?? res, null, 2)
  } catch (err) {
    webhookSimResult.value = extractApiDetail(err) || t('common.error')
  } finally {
    webhookSimulating.value = ''
  }
}
const typeCardOf = (kind: string) => KIND_CARDS.find((c) => c.kind === kind) ?? KIND_CARDS[0]

const LAKEHOUSE_KINDS: ConnectKind[] = ['unity_catalog', 'snowflake', 'sap_odata', 'http_pull']
const isLakehouseKind = (kind: ConnectKind | '') => LAKEHOUSE_KINDS.includes(kind as ConnectKind)

const showWizard = ref(false)
const wizardStep = ref(0)
const editingSource = ref<EnterpriseSourceConfig | null>(null)
const saving = ref(false)
const testingConnection = ref(false)
const wizardTestResult = ref<{ status: string; reason: string } | null>(null)

const emptyForm = () => ({
  source_id: '',
  kind: '' as ConnectKind | '',
  driver: 'postgresql',
  cursorColumn: '',
  base_url: '',
  sf_query: '',
  watermark_column: '',
  entity_set: '',
  url: '',
  host: '',
  port: '',
  database: '',
  sqlMode: 'table' as 'table' | 'query',
  table: '',
  query: '',
  credentialEnv: '',
  vendor: 'kingdee',
  baseUrl: '',
  formId: '',
  tokenPath: '',
  ingressDb: '',
  chatSource: 'capture' as 'capture' | 'archive',
  archiveSdkPath: '',
  archiveSecretEnv: '',
  archivePrivateKeys: '',
  archiveRoomAllowlist: '',
  archiveUserAllowlist: '',
  format: 'csv',
  path: '',
  columns: '',
  subjectMode: 'column' as 'column' | 'template',
  subjectColumn: '',
  subjectTemplate: '',
  predicateTermId: '',
  objectKind: 'column' as 'column' | 'template' | 'term' | 'literal',
  objectValue: '',
  qualifiers: '',
  validFrom: '',
  validUntil: '',
  enabled: false,
})

const wizardForm = reactive(emptyForm())

// 媒体取回弹层（批 C7c 第三块：存档源逐条可控触发，方案 §10-甲）
const showMediaModal = ref(false)
const mediaSourceId = ref('')
const mediaMsgId = ref('')
const mediaOutcome = ref('')
const mediaBusy = ref(false)

const openMediaFetch = (row: EnterpriseSourceConfig) => {
  mediaSourceId.value = row.source_id
  mediaMsgId.value = ''
  mediaOutcome.value = ''
  showMediaModal.value = true
}

const runMediaFetch = async () => {
  if (!mediaMsgId.value.trim()) return
  mediaBusy.value = true
  mediaOutcome.value = ''
  try {
    const resp = await triggerEnterpriseMedia(mediaSourceId.value, mediaMsgId.value.trim())
    const data = resp.data as { status?: string; path?: string; size?: number } | undefined
    if (data?.status === 'staged') {
      mediaOutcome.value = t('ontology.entMediaStaged', { size: data.size ?? 0, path: data.path ?? '' })
      message.success(t('ontology.entMediaStaged', { size: data.size ?? 0, path: data.path ?? '' }))
    } else if (data?.status === 'already_staged') {
      mediaOutcome.value = t('ontology.entMediaAlready', { path: data.path ?? '' })
    } else {
      mediaOutcome.value = t('ontology.entMediaNoMedia')
    }
  } catch (err) {
    const detail = extractApiDetail(err) || t('common.error')
    mediaOutcome.value = detail
    message.error(detail)
  } finally {
    mediaBusy.value = false
  }
}

const wizardTitle = computed(() =>
  editingSource.value ? t('ontology.entEditTitle') : t('ontology.entWizardTitle'),
)

/** 步进守门：步 0 选型；步 1 逐类型必填；步 2 映射必填 */
const canProceed = computed(() => {
  if (wizardStep.value === 0) return !!wizardForm.kind
  if (wizardStep.value === 1) {
    if (!wizardForm.source_id.trim()) return false
    if (wizardForm.kind === 'sql') {
      return !!wizardForm.driver && !!wizardForm.database && !!wizardForm.cursorColumn
        && (wizardForm.sqlMode === 'table' ? !!wizardForm.table : !!wizardForm.query)
        && (wizardForm.driver === 'sqlite' || !!wizardForm.host)
    }
    if (wizardForm.kind === 'erp') {
      return !!wizardForm.baseUrl && !!wizardForm.credentialEnv.trim()
        && (wizardForm.vendor === 'yongyou' || !!wizardForm.formId)
    }
    if (wizardForm.kind === 'wecom' || wizardForm.kind === 'wechat') {
      if (wizardForm.chatSource !== 'archive') return true
      return !!wizardForm.archiveSdkPath.trim() && !!wizardForm.archiveSecretEnv.trim()
        && !!wizardForm.archivePrivateKeys.trim()
    }
    if (wizardForm.kind === 'file') return !!wizardForm.format && !!wizardForm.path
    return false
  }
  if (wizardStep.value === 2) {
    return !!wizardForm.columns.trim() && !!wizardForm.predicateTermId.trim()
      && !!wizardForm.objectValue.trim()
      && (wizardForm.subjectMode === 'column' ? !!wizardForm.subjectColumn.trim() : !!wizardForm.subjectTemplate.trim())
  }
  return true
})

const parsePairs = (text: string): Record<string, string> => {
  const out: Record<string, string> = {}
  for (const line of String(text || '').split('\n')) {
    const idx = line.indexOf('=')
    if (idx > 0) out[line.slice(0, idx).trim()] = line.slice(idx + 1).trim()
  }
  return out
}

const buildDescriptor = (): EnterpriseDescriptor => {
  // 向导 kind → 后端 sourceType：erp→erp_api、wecom/wechat→chat（vendor=kind）
  const sourceType = wizardForm.kind === 'erp' ? 'erp_api'
    : (wizardForm.kind === 'wecom' || wizardForm.kind === 'wechat') ? 'chat'
    : String(wizardForm.kind)
  const d: EnterpriseDescriptor = {
    sourceType,
    columns: splitList(wizardForm.columns),
    subject: wizardForm.subjectMode === 'column'
      ? { column: wizardForm.subjectColumn }
      : { template: wizardForm.subjectTemplate },
    predicate: { termId: wizardForm.predicateTermId },
    object: { kind: wizardForm.objectKind },
    validFrom: wizardForm.validFrom || undefined,
    validUntil: wizardForm.validUntil || undefined,
  }
  if (wizardForm.objectKind === 'column') d.object.column = wizardForm.objectValue
  else if (wizardForm.objectKind === 'template') d.object.template = wizardForm.objectValue
  else if (wizardForm.objectKind === 'term') d.object.termId = wizardForm.objectValue
  else d.object.value = wizardForm.objectValue
  const qualifiers = parsePairs(wizardForm.qualifiers)
  if (Object.keys(qualifiers).length) d.qualifiers = qualifiers

  if (wizardForm.kind === 'sql') {
    d.driver = wizardForm.driver
    d.database = wizardForm.database
    d.cursorColumn = wizardForm.cursorColumn
    if (wizardForm.driver !== 'sqlite') {
      d.host = wizardForm.host
      if (wizardForm.port) d.port = wizardForm.port
    }
    if (wizardForm.sqlMode === 'table') d.table = wizardForm.table
    else d.query = wizardForm.query
    const env = parsePairs(wizardForm.credentialEnv)
    if (Object.keys(env).length) d.credentialEnv = env
  } else if (wizardForm.kind === 'erp') {
    d.vendor = wizardForm.vendor
    d.baseUrl = wizardForm.baseUrl
    if (wizardForm.vendor === 'kingdee') d.formId = wizardForm.formId
    if (wizardForm.vendor === 'yongyou' && wizardForm.tokenPath) d.tokenPath = wizardForm.tokenPath
    d.credentialEnv = parsePairs(wizardForm.credentialEnv)
  } else if (wizardForm.kind === 'wecom' || wizardForm.kind === 'wechat') {
    d.vendor = wizardForm.kind
    if (wizardForm.chatSource === 'archive' && wizardForm.kind === 'wecom') {
      d.chatSource = 'archive'
      d.archiveSdkPath = wizardForm.archiveSdkPath
      d.archiveSecretEnv = wizardForm.archiveSecretEnv
      const keys = parsePairs(wizardForm.archivePrivateKeys)
      if (Object.keys(keys).length) d.archivePrivateKeys = keys
      const rooms = splitList(wizardForm.archiveRoomAllowlist)
      if (rooms.length) d.archiveRoomAllowlist = rooms
      const users = splitList(wizardForm.archiveUserAllowlist)
      if (users.length) d.archiveUserAllowlist = users
    } else {
      if (wizardForm.ingressDb) d.ingressDb = wizardForm.ingressDb
    }
  } else if (wizardForm.kind === 'file') {
    d.format = wizardForm.format
    d.path = wizardForm.path
  }
  return d
}

const openCreate = () => {
  editingSource.value = null
  Object.assign(wizardForm, emptyForm())
  wizardStep.value = 0
  wizardTestResult.value = null
  showWizard.value = true
}

/** 编辑预填：从已落库描述符反填向导表单；步 0 选型锁定（契约只读） */
const openEdit = (row: EnterpriseSourceConfig) => {
  editingSource.value = row
  const d = row.descriptor as Record<string, any>
  const kind: ConnectKind = d.sourceType === 'sql' ? 'sql'
    : d.sourceType === 'erp_api' ? 'erp'
    : d.sourceType === 'chat' ? (d.vendor === 'wecom' ? 'wecom' : 'wechat')
    : d.sourceType === 'file' ? 'file' : 'sql'
  Object.assign(wizardForm, emptyForm(), {
    source_id: row.source_id,
    kind,
    driver: d.driver || 'postgresql',
    cursorColumn: d.cursorColumn || '',
    host: d.host || '',
    port: d.port ? String(d.port) : '',
    database: d.database || '',
    sqlMode: d.query ? 'query' : 'table',
    table: d.table || '',
    query: d.query || '',
    credentialEnv: Object.entries(d.credentialEnv || {}).map(([k, v]) => `${k}=${v}`).join('\n'),
    vendor: d.vendor === 'yongyou' ? 'yongyou' : 'kingdee',
    baseUrl: d.baseUrl || '',
    formId: d.formId || '',
    tokenPath: d.tokenPath || '',
    ingressDb: d.ingressDb || '',
    chatSource: d.chatSource === 'archive' ? 'archive' : 'capture',
    archiveSdkPath: d.archiveSdkPath || '',
    archiveSecretEnv: d.archiveSecretEnv || '',
    archivePrivateKeys: Object.entries(d.archivePrivateKeys || {}).map(([k, v]) => `${k}=${v}`).join('\n'),
    archiveRoomAllowlist: Array.isArray(d.archiveRoomAllowlist) ? d.archiveRoomAllowlist.join(', ') : '',
    archiveUserAllowlist: Array.isArray(d.archiveUserAllowlist) ? d.archiveUserAllowlist.join(', ') : '',
    format: d.format || 'csv',
    path: d.path || '',
    columns: Array.isArray(d.columns) ? d.columns.join(', ') : '',
    subjectMode: d.subject?.template ? 'template' : 'column',
    subjectColumn: d.subject?.column || '',
    subjectTemplate: d.subject?.template || '',
    predicateTermId: d.predicate?.termId || '',
    objectKind: d.object?.kind || 'column',
    objectValue: d.object?.column || d.object?.template || d.object?.termId || d.object?.value || '',
    qualifiers: Object.entries(d.qualifiers || {}).map(([k, v]) => `${k}=${v}`).join('\n'),
    validFrom: d.validFrom || '',
    validUntil: d.validUntil || '',
    enabled: row.enabled,
  })
  wizardStep.value = 1 // 选型步对编辑锁定：直接进连接参数
  wizardTestResult.value = null
  showWizard.value = true
}

const testConnectionInWizard = async () => {
  if (!editingSource.value) return
  testingConnection.value = true
  wizardTestResult.value = null
  try {
    const res = await getEnterpriseSourceHealth(editingSource.value.source_id)
    wizardTestResult.value = { status: res.data?.status ?? 'error', reason: res.data?.reason ?? '' }
  } catch (err) {
    wizardTestResult.value = { status: 'error', reason: extractApiDetail(err) || '' }
  } finally {
    testingConnection.value = false
  }
}

const saveWizard = async () => {
  saving.value = true
  try {
    await submitEnterpriseSource({
      source_id: wizardForm.source_id.trim(),
      descriptor: buildDescriptor(),
      enabled: wizardForm.enabled,
    })
    message.success(t('ontology.entSubmitted'))
    showWizard.value = false
    await loadSources()
  } catch (err) {
    message.error(extractApiDetail(err) || t('common.error'))
  } finally {
    saving.value = false
  }
}

onMounted(loadSources)
</script>

<style scoped>
.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.webhook-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  padding: 6px 0;
}
/* P2-9：接收 URL 行——长 URL 可换行可复制 */
.webhook-url-row {
  align-items: flex-start;
}
.webhook-url {
  word-break: break-all;
  text-align: right;
  max-width: 320px;
}
.webhook-sim-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.webhook-result {
  max-height: 240px;
  overflow: auto;
  font-size: 11px;
  padding: 8px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
  border-radius: 6px;
  white-space: pre-wrap;
}

.enterprise-sources-page { display: flex; flex-direction: column; gap: 16px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-subtitle { margin: 4px 0 0; font-size: 12px; color: var(--nr-text-secondary); }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.mono { font-family: var(--nr-font-mono, monospace); font-size: 12px; }
.source-id { color: var(--nr-text-primary); }
.honest-note { font-size: 12px; color: var(--nr-text-secondary); margin: 0; }
.honest-note--error { color: var(--nr-error); }
.action-btns { display: flex; gap: 6px; flex-wrap: wrap; }
.status-check-btn { margin-left: 8px; }
/* 向导 */
.wizard-steps { margin-bottom: 18px; }
.kind-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
.kind-card { border: 1px solid var(--nr-glass-border); border-radius: 10px; padding: 14px 12px; cursor: pointer; text-align: center; transition: border-color .15s; }
.kind-card:hover { border-color: var(--nr-primary); }
.kind-card.active { border-color: var(--nr-primary); background: var(--nr-primary-soft); }
.kind-name { font-weight: 600; color: var(--nr-text-primary); }
.kind-desc { font-size: 11px; color: var(--nr-text-muted); margin-top: 4px; }
.wizard-form { margin-top: 4px; }
.field-hint { font-size: 11px; color: var(--nr-text-secondary); margin: 0 0 6px; }
.object-value { margin-top: 8px; }
.wizard-confirm .confirm-enabled { margin-top: 14px; }
.test-row { display: flex; align-items: center; gap: 10px; }
.test-result { font-size: 12px; }
.test-ok { color: var(--nr-success); }
.test-degraded { color: var(--nr-warning); }
.test-error { color: var(--nr-error); }
.wizard-footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
</style>
