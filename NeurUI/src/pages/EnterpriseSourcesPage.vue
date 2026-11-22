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

    <!-- 目录主视图：源选择器 + schema 目录（P1-1；抽屉内容提取为内联面板常驻） -->
    <div ref="catalogSectionRef" class="catalog-section">
      <GlassPanel :title="t('ontology.catalogPanelTitle')">
        <div class="catalog-source-row">
          <span class="source-label">{{ t('ontology.catalogSourceLabel') }}</span>
          <a-select
            v-model:value="activeCatalogSourceId"
            class="source-select"
            :options="catalogSourceOptions"
            size="small"
            data-testid="catalog-source-select"
          />
          <span v-if="!sources.length" class="field-hint">{{ t('ontology.catalogSourceEmpty') }}</span>
        </div>
        <SourceCatalogPanel :source-id="activeCatalogSourceId" :is-admin="isAdmin" />
      </GlassPanel>
    </div>

    <!-- 连接器列表（次级分区：行「目录」按钮改为切换上方目录面板的当前源） -->
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
                variant="ghost" size="sm"
                data-testid="ent-interval-btn"
                @click="openIntervalModal(record)"
              >{{ t('ontology.entIntervalBtn') }}</GlassButton>
              <GlassButton
                variant="ghost" size="sm"
                data-testid="ent-share-tenants-btn"
                @click="openShareTenantsModal(record)"
              >{{ t('ontology.entShareTenantsBtn') }}</GlassButton>
              <GlassButton
                variant="ghost" size="sm"
                data-testid="ent-history-btn"
                @click="openHistoryDrawer(record.source_id)"
              >{{ t('ontology.entHistoryBtn') }}</GlassButton>
              <GlassButton
                variant="ghost" size="sm"
                data-testid="ent-catalog-btn"
                @click="openCatalog(record.source_id)"
              >{{ t('ontology.catalogViewBtn') }}</GlassButton>
              <GlassButton
                variant="ghost" size="sm"
                data-testid="ent-nl2sql-btn"
                @click="openNl2SqlDrawer(record.source_id)"
              >{{ t('ontology.nl2sqlTitle') }}</GlassButton>
              <!-- P1-26：webhook 抽屉此前不可达（openWebhookDrawer 零调用）——操作列补入口 -->
              <GlassButton
                variant="ghost" size="sm"
                data-testid="ent-webhook-btn"
                @click="openWebhookDrawer"
              >{{ t('ontology.entWebhookBtn') }}</GlassButton>
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

    <!-- 同步间隔设置（可靠性方案 D2：改完即时注册/摘除 job） -->
    <a-modal
      v-model:open="showIntervalModal"
      :title="t('ontology.entIntervalTitle')"
      width="460px"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('ontology.entIntervalLabel')" required>
          <a-input-number
            v-model:value="intervalSeconds"
            :min="0"
            :max="86400"
            class="mono"
            data-testid="ent-interval-input"
          />
          <p class="field-hint">{{ t('ontology.entIntervalHint') }}</p>
        </a-form-item>
      </a-form>
      <template #footer>
        <GlassButton variant="secondary" size="sm" @click="showIntervalModal = false">
          {{ t('common.cancel') }}
        </GlassButton>
        <GlassButton variant="primary" size="sm" :loading="intervalSaving"
          data-testid="ent-interval-save" @click="saveSyncInterval">
          {{ t('common.save') }}
        </GlassButton>
      </template>
    </a-modal>

    <!-- 租户级共享策略（§8.3-P2：下一轮同步成功后按清单投影复制到目标租户分区） -->
    <a-modal
      v-model:open="showShareTenantsModal"
      :title="t('ontology.entShareTenantsTitle')"
      width="460px"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('ontology.entShareTenantsLabel')" required>
          <a-input
            v-model:value="shareTenantsInput"
            class="mono"
            data-testid="ent-share-tenants-input"
          />
          <p class="field-hint">{{ t('ontology.entShareTenantsHint') }}</p>
        </a-form-item>
      </a-form>
      <template #footer>
        <GlassButton variant="secondary" size="sm" @click="showShareTenantsModal = false">
          {{ t('common.cancel') }}
        </GlassButton>
        <GlassButton variant="primary" size="sm" :loading="shareTenantsSaving"
          data-testid="ent-share-tenants-save" @click="saveShareTenants">
          {{ t('common.save') }}
        </GlassButton>
      </template>
    </a-modal>

    <!-- 同步历史（可靠性方案 D1：每轮拉取一行） -->
    <a-drawer
      v-model:open="showHistoryDrawer"
      :title="t('ontology.entHistoryTitle') + ' — ' + historySourceId"
      width="720px"
    >
      <a-table
        :data-source="historyItems"
        :loading="historyLoading"
        :pagination="false"
        size="small"
        data-testid="ent-history-table"
        row-key="started_at"
      >
        <a-table-column :title="t('ontology.entHistColTime')" data-index="started_at" width="170">
          <template #default="{ text }"><span class="mono">{{ formatTime(text) }}</span></template>
        </a-table-column>
        <a-table-column :title="t('ontology.entHistColTrigger')" data-index="trigger_kind" width="90">
          <template #default="{ text }">{{ triggerKindLabel(text) }}</template>
        </a-table-column>
        <a-table-column :title="t('ontology.entHistColStatus')" data-index="status" width="90" />
        <a-table-column :title="t('ontology.entHistColAdmitted')" data-index="admitted" width="80" />
        <a-table-column :title="t('ontology.entHistColRejected')" data-index="rejected" width="80" />
        <a-table-column :title="t('ontology.entHistColReason')" data-index="reason" ellipsis />
      </a-table>
    </a-drawer>

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

      <!-- 步 0：选连接对象（按连接器族分组展示；组序即 KIND_GROUPS） -->
      <div v-if="wizardStep === 0" class="kind-cards" data-testid="ent-kind-cards">
        <template v-for="group in KIND_GROUPS" :key="group.titleKey">
          <div class="kind-group-title">{{ t(group.titleKey) }}</div>
          <div
            v-for="card in kindCardsIn(group)"
            :key="card.kind"
            class="kind-card"
            :class="{ active: wizardForm.kind === card.kind }"
            @click="wizardForm.kind = card.kind"
          >
            <div class="kind-name">{{ t(card.labelKey) }}</div>
            <div class="kind-desc">{{ t(card.descKey) }}</div>
          </div>
        </template>
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

          <!-- 湖仓/HTTP（W10；U-conn 扩展批纳入 bigquery/databricks）：base_url＋credential_env 指针＋kind 专属字段 -->
          <template v-if="isLakehouseKind(wizardForm.kind)">
            <a-form-item :label="t('ontology.entKindBaseUrl')" required>
              <a-input v-model:value="wizardForm.base_url" data-testid="ent-base-url" />
            </a-form-item>
            <a-form-item
              :label="t('ontology.entKindCredentialEnv')"
              :required="wizardForm.kind === 'bigquery' || wizardForm.kind === 'databricks'"
            >
              <p
                v-if="wizardForm.kind === 'bigquery' || wizardForm.kind === 'databricks'"
                class="field-hint"
              >{{ t('ontology.entKindCredEnvPointerHint') }}</p>
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
            <!-- U-conn 扩展批：bigquery/databricks（湖仓 SQL REST，query 驱动） -->
            <a-form-item v-if="wizardForm.kind === 'bigquery'" :label="t('ontology.entKindProjectId')" required>
              <a-input v-model:value="wizardForm.project_id" data-testid="ent-bq-project" />
            </a-form-item>
            <a-form-item v-if="wizardForm.kind === 'databricks'" :label="t('ontology.entKindWarehouseId')" required>
              <a-input v-model:value="wizardForm.warehouse_id" data-testid="ent-db-warehouse" />
            </a-form-item>
            <a-form-item
              v-if="wizardForm.kind === 'bigquery' || wizardForm.kind === 'databricks'"
              :label="t('ontology.entKindQuery')" required
            >
              <a-textarea v-model:value="wizardForm.query" :rows="3" data-testid="ent-sql-rest-query" />
            </a-form-item>
            <a-form-item v-if="wizardForm.kind === 'bigquery'" :label="t('ontology.entKindWatermarkColumn')">
              <a-input v-model:value="wizardForm.watermark_column" data-testid="ent-bq-watermark" />
            </a-form-item>
          </template>
          <!-- SaaS REST（U-conn 扩展批）：base_url＋kind 专属字段＋凭据 env 指针（salesforce 单指针，其余对象双指针） -->
          <template v-if="isSaasRestKind(wizardForm.kind)">
            <a-form-item :label="t('ontology.entKindBaseUrl')" required>
              <a-input v-model:value="wizardForm.base_url" data-testid="ent-base-url" />
            </a-form-item>
            <a-form-item v-if="wizardForm.kind === 'salesforce'" :label="t('ontology.entKindSoql')" required>
              <a-textarea v-model:value="wizardForm.soql" :rows="3" data-testid="ent-soql" />
            </a-form-item>
            <a-form-item v-if="wizardForm.kind === 'salesforce'" :label="t('ontology.entKindCredentialEnv')" required>
              <p class="field-hint">{{ t('ontology.entKindCredEnvPointerHint') }}</p>
              <a-input v-model:value="wizardForm.credentialEnv" data-testid="ent-cred-env" />
            </a-form-item>
            <a-form-item v-if="wizardForm.kind === 'servicenow'" :label="t('ontology.entKindTable')" required>
              <a-input v-model:value="wizardForm.table" data-testid="ent-sn-table" />
            </a-form-item>
            <a-form-item v-if="wizardForm.kind === 'servicenow'" :label="t('ontology.entKindEncodedQuery')">
              <a-input v-model:value="wizardForm.query" data-testid="ent-sn-query" />
            </a-form-item>
            <a-form-item v-if="wizardForm.kind === 'looker'" :label="t('ontology.entKindQueryId')" required>
              <a-input v-model:value="wizardForm.query_id" data-testid="ent-looker-query-id" />
            </a-form-item>
            <a-form-item v-if="wizardForm.kind === 'airflow'" :label="t('ontology.entKindDagId')" required>
              <a-input v-model:value="wizardForm.dag_id" data-testid="ent-airflow-dag" />
            </a-form-item>
            <!-- credentialEnv 对象型：拆成两个输入框，各自填环境变量名（值不落明文） -->
            <template v-if="wizardForm.kind === 'servicenow' || wizardForm.kind === 'airflow'">
              <a-form-item :label="t('ontology.entKindCredUserEnv')" required>
                <p class="field-hint">{{ t('ontology.entKindCredEnvPointerHint') }}</p>
                <a-input v-model:value="wizardForm.credUserEnv" data-testid="ent-cred-user" />
              </a-form-item>
              <a-form-item :label="t('ontology.entKindCredPasswordEnv')" required>
                <a-input v-model:value="wizardForm.credPasswordEnv" data-testid="ent-cred-password" />
              </a-form-item>
            </template>
            <template v-if="wizardForm.kind === 'looker'">
              <a-form-item :label="t('ontology.entKindCredClientIdEnv')" required>
                <p class="field-hint">{{ t('ontology.entKindCredEnvPointerHint') }}</p>
                <a-input v-model:value="wizardForm.credClientIdEnv" data-testid="ent-cred-client-id" />
              </a-form-item>
              <a-form-item :label="t('ontology.entKindCredClientSecretEnv')" required>
                <a-input v-model:value="wizardForm.credClientSecretEnv" data-testid="ent-cred-client-secret" />
              </a-form-item>
            </template>
          </template>
          <!-- NoSQL（U-conn 扩展批：cassandra CQL 只读拉取） -->
          <template v-if="wizardForm.kind === 'cassandra'">
            <a-form-item :label="t('ontology.entKindContactPoints')" required>
              <a-input v-model:value="wizardForm.contact_points" data-testid="ent-cassandra-contact-points" />
            </a-form-item>
            <a-form-item :label="t('ontology.entKindKeyspace')" required>
              <a-input v-model:value="wizardForm.keyspace" data-testid="ent-cassandra-keyspace" />
            </a-form-item>
            <a-form-item :label="t('ontology.entKindTable')" required>
              <a-input v-model:value="wizardForm.table" data-testid="ent-cassandra-table" />
            </a-form-item>
            <a-form-item :label="t('ontology.entKindCql')" required>
              <a-textarea v-model:value="wizardForm.cql" :rows="3" data-testid="ent-cassandra-cql" />
            </a-form-item>
            <a-form-item :label="t('ontology.entKindCredUserEnv')" required>
              <p class="field-hint">{{ t('ontology.entKindCredEnvPointerHint') }}</p>
              <a-input v-model:value="wizardForm.credUserEnv" data-testid="ent-cred-user" />
            </a-form-item>
            <a-form-item :label="t('ontology.entKindCredPasswordEnv')" required>
              <a-input v-model:value="wizardForm.credPasswordEnv" data-testid="ent-cred-password" />
            </a-form-item>
          </template>
          <!-- 代码仓（U-conn 扩展批：git 仓库文件清单；公共仓免凭据） -->
          <template v-if="wizardForm.kind === 'git'">
            <a-form-item :label="t('ontology.entKindRepoUrl')" required>
              <a-input v-model:value="wizardForm.repo_url" data-testid="ent-git-repo-url" />
            </a-form-item>
            <a-form-item :label="t('ontology.entKindBranch')">
              <a-input v-model:value="wizardForm.branch" data-testid="ent-git-branch" />
            </a-form-item>
            <a-form-item :label="t('ontology.entKindFileGlob')">
              <a-input v-model:value="wizardForm.file_glob" data-testid="ent-git-file-glob" />
            </a-form-item>
            <a-form-item :label="t('ontology.entKindCredUserEnv') + t('ontology.entFieldOptional')">
              <p class="field-hint">{{ t('ontology.entKindCredEnvPointerHint') }}</p>
              <a-input v-model:value="wizardForm.credUserEnv" data-testid="ent-cred-user" />
            </a-form-item>
            <a-form-item :label="t('ontology.entKindCredTokenEnv') + t('ontology.entFieldOptional')">
              <a-input v-model:value="wizardForm.credTokenEnv" data-testid="ent-cred-token" />
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

    <!-- P1-4：问数抽屉（自然语言→SQL→只读执行；env 门控默认关，403 如实转述） -->
    <SourceNl2SqlDrawer
      :open="nl2sqlDrawerOpen"
      :source-id="nl2sqlDrawerSourceId"
      :is-admin="isAdmin"
      @close="nl2sqlDrawerOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import SourceCatalogPanel from '@/components/enterprise/SourceCatalogPanel.vue'
import SourceNl2SqlDrawer from '@/components/enterprise/SourceNl2SqlDrawer.vue'
import { useAuthStore } from '@/stores/auth'
import {
  deleteEnterpriseSource,
  getEnterpriseSourceHealth,
  getEnterpriseShareTenants,
  getEnterpriseSyncHistory,
  getEnterpriseSyncInterval,
  listEnterpriseSources,
  submitEnterpriseSource,
  triggerEnterpriseIngest,
  triggerEnterpriseMedia,
  updateEnterpriseShareTenants,
  updateEnterpriseSyncInterval,
  getWebhookConfig,
  rotateWebhookSecret,
  simulateWebhookPush,
  getWebhookDedupStats,
} from '@/api/modules/ontology'
import type { EnterpriseSyncHistoryItem } from '@/api/modules/ontology'
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

// 触发来源标签映射（manual/interval/startup/audit 走 i18n；未知值诚实回退原值，不猜标签）
const TRIGGER_KIND_I18N_KEYS: Record<string, string> = {
  manual: 'ontology.entTriggerManual',
  interval: 'ontology.entTriggerInterval',
  startup: 'ontology.entTriggerStartup',
  audit: 'ontology.entTriggerAudit',
}
const triggerKindLabel = (kind: unknown) => {
  const labelKey = TRIGGER_KIND_I18N_KEYS[String(kind ?? '')]
  return labelKey ? t(labelKey) : String(kind ?? '')
}

// 湖仓/SaaS/NoSQL/代码仓 sourceType → 列表类型标签（未知值仍诚实回退原值）
const TYPE_LABEL_I18N_KEYS: Record<string, string> = {
  unity_catalog: 'ontology.entTypeUnityCatalog',
  snowflake: 'ontology.entTypeSnowflake',
  sap_odata: 'ontology.entTypeSapOdata',
  http_pull: 'ontology.entTypeHttpPull',
  bigquery: 'ontology.entTypeBigquery',
  databricks: 'ontology.entTypeDatabricks',
  cassandra: 'ontology.entTypeCassandra',
  salesforce: 'ontology.entTypeSalesforce',
  servicenow: 'ontology.entTypeServicenow',
  looker: 'ontology.entTypeLooker',
  airflow: 'ontology.entTypeAirflow',
  git: 'ontology.entTypeGit',
}

const typeLabel = (row: EnterpriseSourceConfig) => {
  const d = row.descriptor as Record<string, string>
  if (d.sourceType === 'sql') return t('ontology.entTypeDatabase')
  if (d.sourceType === 'erp_api') return t('ontology.entTypeErp')
  if (d.sourceType === 'file') return t('ontology.entTypeFile')
  if (d.sourceType === 'chat') return d.vendor === 'wecom' ? t('ontology.entTypeWecom') : t('ontology.entTypeWechat')
  const labelKey = TYPE_LABEL_I18N_KEYS[String(d.sourceType || '')]
  return labelKey ? t(labelKey) : String(d.sourceType || '—')
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

// ── 同步间隔设置与同步历史（可靠性方案 D1/D2 前端适配） ──────────────────

const showIntervalModal = ref(false)
const intervalSourceId = ref('')
const intervalSeconds = ref(0)
const intervalSaving = ref(false)

const openIntervalModal = async (row: EnterpriseSourceConfig) => {
  intervalSourceId.value = row.source_id
  try {
    const res = await getEnterpriseSyncInterval(row.source_id)
    intervalSeconds.value = res.data?.seconds ?? 0
  } catch {
    intervalSeconds.value = 0
  }
  showIntervalModal.value = true
}

const saveSyncInterval = async () => {
  intervalSaving.value = true
  try {
    await updateEnterpriseSyncInterval(intervalSourceId.value, intervalSeconds.value ?? 0)
    message.success(t('ontology.entIntervalTitle'))
    showIntervalModal.value = false
    await loadSources()
  } catch (err) {
    message.error(extractApiDetail(err) || t('common.error'))
  } finally {
    intervalSaving.value = false
  }
}

// ── 租户级共享策略（§8.3-P2 前端适配） ──────────────────

const showShareTenantsModal = ref(false)
const shareTenantsSourceId = ref('')
const shareTenantsInput = ref('')
const shareTenantsSaving = ref(false)

const openShareTenantsModal = async (row: EnterpriseSourceConfig) => {
  shareTenantsSourceId.value = row.source_id
  try {
    const res = await getEnterpriseShareTenants(row.source_id)
    shareTenantsInput.value = (res.data?.share_tenants ?? []).join(', ')
  } catch {
    shareTenantsInput.value = ''
  }
  showShareTenantsModal.value = true
}

const saveShareTenants = async () => {
  shareTenantsSaving.value = true
  try {
    const tenantIds = shareTenantsInput.value
      .split(/[,，;；\s]+/)
      .map((s) => s.trim())
      .filter(Boolean)
    await updateEnterpriseShareTenants(shareTenantsSourceId.value, tenantIds)
    message.success(t('ontology.entShareTenantsTitle'))
    showShareTenantsModal.value = false
    await loadSources()
  } catch (err) {
    message.error(extractApiDetail(err) || t('common.error'))
  } finally {
    shareTenantsSaving.value = false
  }
}

const showHistoryDrawer = ref(false)
const historySourceId = ref('')
const historyLoading = ref(false)
const historyItems = ref<EnterpriseSyncHistoryItem[]>([])

const openHistoryDrawer = async (sourceId: string) => {
  historySourceId.value = sourceId
  showHistoryDrawer.value = true
  historyLoading.value = true
  try {
    const res = await getEnterpriseSyncHistory(sourceId)
    historyItems.value = res.data?.items ?? []
  } catch (err) {
    historyItems.value = []
    message.error(extractApiDetail(err) || t('common.error'))
  } finally {
    historyLoading.value = false
  }
}

// ── 向导（新增/编辑共用，四步） ──────────────────────────────

type ConnectKind = 'sql' | 'erp' | 'wecom' | 'wechat' | 'file'
  | 'unity_catalog' | 'snowflake' | 'sap_odata' | 'http_pull'
  | 'bigquery' | 'databricks' | 'cassandra'
  | 'salesforce' | 'servicenow' | 'looker' | 'airflow' | 'git'

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
  // U-conn 扩展批（对齐参照系连接器矩阵）：bigquery/databricks（湖仓 SQL REST）、
  // cassandra（NoSQL CQL）、salesforce/servicenow/looker/airflow（SaaS REST）、git（代码仓）
  { kind: 'bigquery', labelKey: 'ontology.entTypeBigquery', descKey: 'ontology.entKindBigqueryDesc' },
  { kind: 'databricks', labelKey: 'ontology.entTypeDatabricks', descKey: 'ontology.entKindDatabricksDesc' },
  { kind: 'cassandra', labelKey: 'ontology.entTypeCassandra', descKey: 'ontology.entKindCassandraDesc' },
  { kind: 'salesforce', labelKey: 'ontology.entTypeSalesforce', descKey: 'ontology.entKindSalesforceDesc' },
  { kind: 'servicenow', labelKey: 'ontology.entTypeServicenow', descKey: 'ontology.entKindServicenowDesc' },
  { kind: 'looker', labelKey: 'ontology.entTypeLooker', descKey: 'ontology.entKindLookerDesc' },
  { kind: 'airflow', labelKey: 'ontology.entTypeAirflow', descKey: 'ontology.entKindAirflowDesc' },
  { kind: 'git', labelKey: 'ontology.entTypeGit', descKey: 'ontology.entKindGitDesc' },
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

// 连接器族分组（单一出处）：步 0 卡片分组展示与步 1 共享字段模板门控都从这几组取。
// U-conn 扩展批：bigquery/databricks 归湖仓 SQL REST 组（沿用 W10 组名），
// salesforce/servicenow/looker/airflow 归 SaaS REST 组，cassandra 归 NoSQL 组，git 归代码仓组。
const LAKEHOUSE_KINDS: ConnectKind[] = ['unity_catalog', 'snowflake', 'sap_odata', 'http_pull', 'bigquery', 'databricks']
const SAAS_REST_KINDS: ConnectKind[] = ['salesforce', 'servicenow', 'looker', 'airflow']
const NOSQL_KINDS: ConnectKind[] = ['cassandra']
const CODE_KINDS: ConnectKind[] = ['git']
const isLakehouseKind = (kind: ConnectKind | '') => LAKEHOUSE_KINDS.includes(kind as ConnectKind)
const isSaasRestKind = (kind: ConnectKind | '') => SAAS_REST_KINDS.includes(kind as ConnectKind)

/** 步 0 卡片分组（标题走 i18n；组内卡序跟随 KIND_CARDS） */
const KIND_GROUPS: { titleKey: string; kinds: ConnectKind[] }[] = [
  { titleKey: 'ontology.entGroupCore', kinds: ['sql', 'erp', 'wecom', 'wechat', 'file'] },
  { titleKey: 'ontology.entGroupLakehouse', kinds: LAKEHOUSE_KINDS },
  { titleKey: 'ontology.entGroupNosql', kinds: NOSQL_KINDS },
  { titleKey: 'ontology.entGroupSaasRest', kinds: SAAS_REST_KINDS },
  { titleKey: 'ontology.entGroupCode', kinds: CODE_KINDS },
]
const kindCardsIn = (group: { kinds: ConnectKind[] }) => KIND_CARDS.filter((c) => group.kinds.includes(c.kind))

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
  project_id: '',
  warehouse_id: '',
  contact_points: '',
  keyspace: '',
  cql: '',
  soql: '',
  query_id: '',
  dag_id: '',
  repo_url: '',
  branch: '',
  file_glob: '',
  credUserEnv: '',
  credPasswordEnv: '',
  credClientIdEnv: '',
  credClientSecretEnv: '',
  credTokenEnv: '',
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

// P1-4：问数抽屉（逐源打开；门控/权限由后端裁决、前端如实转述）
const nl2sqlDrawerOpen = ref(false)
const nl2sqlDrawerSourceId = ref('')

// P1-1：目录主视图的当前源（选择器 v-model；行「目录」按钮切换同源并滚回目录区）
const catalogSectionRef = ref<HTMLElement | null>(null)
const activeCatalogSourceId = ref('')

const catalogSourceOptions = computed(() =>
  sources.value.map((s) => ({ label: s.source_id, value: s.source_id })))

/** 源清单变化时保持目录当前源有效：缺省取第一个源；当前源被删则回落第一个 */
watch(() => sources.value.map((s) => s.source_id).join(','), () => {
  const ids = sources.value.map((s) => s.source_id)
  if (!ids.includes(activeCatalogSourceId.value)) {
    activeCatalogSourceId.value = ids[0] ?? ''
  }
})

/** 行「目录」按钮：切换目录面板当前源并滚回目录区（替代原抽屉打开） */
function openCatalog(sourceId: string) {
  activeCatalogSourceId.value = sourceId
  void nextTick(() => {
    const el = catalogSectionRef.value
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  })
}

function openNl2SqlDrawer(sourceId: string) {
  nl2sqlDrawerSourceId.value = sourceId
  nl2sqlDrawerOpen.value = true
}
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
    // 湖仓 SQL REST（含 U-conn 扩展 bigquery/databricks）：base_url 必填；
    // 既有四连接器凭据不强制（后端 health 如实报缺凭据），bigquery/databricks 凭据指针必填
    if (isLakehouseKind(wizardForm.kind)) {
      if (!wizardForm.base_url.trim()) return false
      if ((wizardForm.kind === 'bigquery' || wizardForm.kind === 'databricks')
        && !wizardForm.credentialEnv.trim()) return false
      if (wizardForm.kind === 'unity_catalog') return !!wizardForm.table.trim()
      if (wizardForm.kind === 'snowflake') return !!wizardForm.sf_query.trim()
      if (wizardForm.kind === 'sap_odata') return !!wizardForm.entity_set.trim()
      if (wizardForm.kind === 'http_pull') return !!wizardForm.url.trim()
      if (wizardForm.kind === 'bigquery') {
        return !!wizardForm.project_id.trim() && !!wizardForm.query.trim()
      }
      if (wizardForm.kind === 'databricks') {
        return !!wizardForm.warehouse_id.trim() && !!wizardForm.query.trim()
      }
      return false
    }
    // SaaS REST（U-conn 扩展批）：base_url＋kind 主字段＋凭据 env 指针必填
    if (isSaasRestKind(wizardForm.kind)) {
      if (!wizardForm.base_url.trim()) return false
      if (wizardForm.kind === 'salesforce') {
        return !!wizardForm.soql.trim() && !!wizardForm.credentialEnv.trim()
      }
      if (wizardForm.kind === 'servicenow') {
        return !!wizardForm.table.trim()
          && !!wizardForm.credUserEnv.trim() && !!wizardForm.credPasswordEnv.trim()
      }
      if (wizardForm.kind === 'looker') {
        return !!wizardForm.query_id.trim()
          && !!wizardForm.credClientIdEnv.trim() && !!wizardForm.credClientSecretEnv.trim()
      }
      if (wizardForm.kind === 'airflow') {
        return !!wizardForm.dag_id.trim()
          && !!wizardForm.credUserEnv.trim() && !!wizardForm.credPasswordEnv.trim()
      }
      return false
    }
    // NoSQL：cassandra 全字段必填
    if (wizardForm.kind === 'cassandra') {
      return !!wizardForm.contact_points.trim() && !!wizardForm.keyspace.trim()
        && !!wizardForm.table.trim() && !!wizardForm.cql.trim()
        && !!wizardForm.credUserEnv.trim() && !!wizardForm.credPasswordEnv.trim()
    }
    // 代码仓：git 只强制 repo_url（branch/file_glob 有缺省；公共仓免凭据）
    if (wizardForm.kind === 'git') return !!wizardForm.repo_url.trim()
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

/** 对象型 credentialEnv（{逻辑名: 环境变量名}）：剔空；全空返回 undefined（git 公共仓免凭据不落空对象） */
const credEnvPair = (entries: Record<string, string>): Record<string, string> | undefined => {
  const out: Record<string, string> = {}
  for (const [logical, envName] of Object.entries(entries)) {
    const trimmed = String(envName || '').trim()
    if (trimmed) out[logical] = trimmed
  }
  return Object.keys(out).length ? out : undefined
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
  } else if (isLakehouseKind(wizardForm.kind)) {
    // 湖仓 SQL REST（W10 四连接器＋U-conn 扩展 bigquery/databricks）：
    // 后端描述符字段为 base_url＋credential_env（单 env 名指针，值不落明文）
    if (wizardForm.base_url.trim()) d.base_url = wizardForm.base_url.trim()
    if (wizardForm.credentialEnv.trim()) d.credential_env = wizardForm.credentialEnv.trim()
    if (wizardForm.kind === 'unity_catalog') d.table = wizardForm.table
    else if (wizardForm.kind === 'snowflake') {
      d.query = wizardForm.sf_query
      if (wizardForm.watermark_column.trim()) d.watermark_column = wizardForm.watermark_column.trim()
    } else if (wizardForm.kind === 'sap_odata') d.entity_set = wizardForm.entity_set
    else if (wizardForm.kind === 'http_pull') d.url = wizardForm.url
    else if (wizardForm.kind === 'bigquery') {
      d.project_id = wizardForm.project_id.trim()
      d.query = wizardForm.query
      if (wizardForm.watermark_column.trim()) d.watermark_column = wizardForm.watermark_column.trim()
    } else if (wizardForm.kind === 'databricks') {
      d.warehouse_id = wizardForm.warehouse_id.trim()
      d.query = wizardForm.query
    }
  } else if (isSaasRestKind(wizardForm.kind)) {
    // SaaS REST（U-conn 扩展批）：salesforce 走 credential_env 单指针，
    // servicenow/looker/airflow 走 credentialEnv 对象双指针（值均为环境变量名）
    if (wizardForm.base_url.trim()) d.base_url = wizardForm.base_url.trim()
    if (wizardForm.kind === 'salesforce') {
      d.soql = wizardForm.soql
      if (wizardForm.credentialEnv.trim()) d.credential_env = wizardForm.credentialEnv.trim()
    } else if (wizardForm.kind === 'servicenow') {
      d.table = wizardForm.table
      if (wizardForm.query.trim()) d.query = wizardForm.query.trim()
      const pair = credEnvPair({ username: wizardForm.credUserEnv, password: wizardForm.credPasswordEnv })
      if (pair) d.credentialEnv = pair
    } else if (wizardForm.kind === 'looker') {
      d.query_id = wizardForm.query_id.trim()
      const pair = credEnvPair({ client_id: wizardForm.credClientIdEnv, client_secret: wizardForm.credClientSecretEnv })
      if (pair) d.credentialEnv = pair
    } else if (wizardForm.kind === 'airflow') {
      d.dag_id = wizardForm.dag_id.trim()
      const pair = credEnvPair({ username: wizardForm.credUserEnv, password: wizardForm.credPasswordEnv })
      if (pair) d.credentialEnv = pair
    }
  } else if (wizardForm.kind === 'cassandra') {
    // NoSQL（U-conn 扩展批）：contact_points 逗号分隔原文上送（后端自行切分）
    d.contact_points = wizardForm.contact_points.trim()
    d.keyspace = wizardForm.keyspace.trim()
    d.table = wizardForm.table.trim()
    d.cql = wizardForm.cql
    const pair = credEnvPair({ username: wizardForm.credUserEnv, password: wizardForm.credPasswordEnv })
    if (pair) d.credentialEnv = pair
  } else if (wizardForm.kind === 'git') {
    // 代码仓（U-conn 扩展批）：branch/file_glob 可选（file_glob 后端缺省 **/*）；凭据可选（公共仓免凭据）
    d.repo_url = wizardForm.repo_url.trim()
    if (wizardForm.branch.trim()) d.branch = wizardForm.branch.trim()
    if (wizardForm.file_glob.trim()) d.file_glob = wizardForm.file_glob.trim()
    const pair = credEnvPair({ username: wizardForm.credUserEnv, token: wizardForm.credTokenEnv })
    if (pair) d.credentialEnv = pair
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
  // kind 反推：erp_api/chat 是前端 kind 的后端映射名，其余按 KIND_CARDS 直查（湖仓/SaaS/NoSQL/git 与 sourceType 同名）
  const directCard = KIND_CARDS.find((c) => c.kind === d.sourceType)
  const kind: ConnectKind = d.sourceType === 'sql' ? 'sql'
    : d.sourceType === 'erp_api' ? 'erp'
    : d.sourceType === 'chat' ? (d.vendor === 'wecom' ? 'wecom' : 'wechat')
    : d.sourceType === 'file' ? 'file'
    : directCard ? directCard.kind : 'sql'
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
    // 湖仓/SaaS 单指针（credential_env 字符串）优先；sql/erp 的对象映射展开成 k=v 行
    credentialEnv: d.credential_env
      || Object.entries(d.credentialEnv || {}).map(([k, v]) => `${k}=${v}`).join('\n'),
    // U-conn 扩展批：湖仓 SQL REST / SaaS REST / NoSQL / 代码仓字段反填
    base_url: d.base_url || '',
    project_id: d.project_id || '',
    warehouse_id: d.warehouse_id || '',
    watermark_column: d.watermark_column || '',
    entity_set: d.entity_set || '',
    contact_points: d.contact_points || '',
    keyspace: d.keyspace || '',
    cql: d.cql || '',
    soql: d.soql || '',
    query_id: d.query_id || '',
    dag_id: d.dag_id || '',
    repo_url: d.repo_url || '',
    branch: d.branch || '',
    file_glob: d.file_glob || '',
    credUserEnv: d.credentialEnv?.username || '',
    credPasswordEnv: d.credentialEnv?.password || '',
    credClientIdEnv: d.credentialEnv?.client_id || '',
    credClientSecretEnv: d.credentialEnv?.client_secret || '',
    credTokenEnv: d.credentialEnv?.token || '',
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
/* 目录主视图分区：滚回锚点 + 源选择器行（颜色全部走 tokens） */
.catalog-section { scroll-margin-top: 16px; }
.catalog-source-row { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.source-label { font-size: 12px; color: var(--nr-text-secondary); }
.source-select { min-width: 220px; }
.mono { font-family: var(--nr-font-mono, monospace); font-size: 12px; }
.source-id { color: var(--nr-text-primary); }
.honest-note { font-size: 12px; color: var(--nr-text-secondary); margin: 0; }
.honest-note--error { color: var(--nr-error); }
.action-btns { display: flex; gap: 6px; flex-wrap: wrap; }
.status-check-btn { margin-left: 8px; }
/* 向导 */
.wizard-steps { margin-bottom: 18px; }
.kind-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
/* U-conn 扩展批：步 0 按连接器族分组（组标题占满整行，颜色走 tokens） */
.kind-group-title { grid-column: 1 / -1; font-size: 11px; font-weight: 600; color: var(--nr-text-secondary); }
.kind-group-title:not(:first-child) { margin-top: 6px; }
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
