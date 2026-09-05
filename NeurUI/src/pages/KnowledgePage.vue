<template>
  <div class="knowledge-page">
    <!-- Header & Toolbar -->
    <GlassPanel class="kb-header">
      <div class="header-row">
        <div class="header-left">
          <h2 class="page-title">{{ t('knowledge.title') }}</h2>
          <a-input-search
            v-model:value="searchQuery"
            :placeholder="t('knowledge.searchPlaceholder')"
            allow-clear
            style="width: 260px"
            @search="handleSearch"
          />
          <a-checkbox v-model:checked="semanticSearch">{{ t('knowledge.semanticSearch') }}</a-checkbox>
          <a-radio-group v-model:value="activeScope" button-style="solid" size="small" @change="onScopeChange">
            <a-radio-button value="all">{{ t('knowledge.scopeAll') }}</a-radio-button>
            <a-radio-button value="public">{{ t('knowledge.scopePublic') }}</a-radio-button>
            <a-radio-button value="private">{{ t('knowledge.scopePrivate') }}</a-radio-button>
            <a-radio-button value="shared">{{ t('knowledge.scopeShared') }}</a-radio-button>
          </a-radio-group>
        </div>
        <div class="header-actions">
          <a-select
            v-model:value="activeCategory"
            :options="categoryOptions"
            :placeholder="t('knowledge.filterCategory')"
            allow-clear
            style="min-width: 160px"
            @change="fetchKnowledge"
          />
          <GlassButton variant="secondary" size="sm" @click="exportKnowledge">
            {{ t('knowledge.export') }}
          </GlassButton>
          <GlassButton variant="secondary" size="sm" @click="importVisible = true">
            {{ t('knowledge.import') }}
          </GlassButton>
          <GlassButton variant="ghost" size="sm" @click="configVisible = true; fetchKbConfigs()">
            {{ t('knowledge.remoteConfig') }}
          </GlassButton>
          <GlassButton variant="secondary" size="sm" @click="annotationOpen = true">
            {{ t('annotation.entry') }}
          </GlassButton>
          <GlassButton variant="primary" size="sm" @click="openCreateModal">
            {{ t('knowledge.create') }}
          </GlassButton>
        </div>
      </div>
    </GlassPanel>

    <!-- Knowledge Table -->
    <GlassPanel v-if="knowledgeItems.length > 0 || loading">
      <a-table
        :columns="columns"
        :data-source="knowledgeItems"
        :loading="loading"
        :locale="{ emptyText: '' }"
        :pagination="pagination"
        row-key="id"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'title'">
            <span class="kb-title-cell">{{ record.title }}</span>
            <a-tag v-if="(record.chunk_count ?? 1) > 1" color="geekblue" class="kb-conf-tag">
              {{ t('knowledge.chunkCount', { count: record.chunk_count }) }}
            </a-tag>
            <a-tag v-if="confidenceMap[record.id] !== undefined" color="purple" class="kb-conf-tag">
              {{ Math.round(confidenceMap[record.id] * 1000) / 10 }}%
            </a-tag>
          </template>
          <template v-if="column.key === 'category'">
            <a-tag color="blue">{{ record.category }}</a-tag>
          </template>
          <template v-if="column.key === 'visibility'">
            <a-space :size="4">
              <a-tag v-if="record.visibility === 'public'" color="green">{{ t('knowledge.visPublic') }}</a-tag>
              <a-tag v-else-if="isSharedToMe(record)" color="cyan">{{ t('knowledge.visShared') }}</a-tag>
              <a-tag v-else color="blue">{{ t('knowledge.visPrivate') }}</a-tag>
              <a-tag v-if="record.submission?.status === 'pending'" color="orange">{{ t('knowledge.pendingReview') }}</a-tag>
              <a-tag v-else-if="record.submission?.status === 'rejected'" color="red">{{ t('knowledge.visRejected') }}</a-tag>
            </a-space>
          </template>
          <template v-if="column.key === 'content'">
            <span class="kb-preview">{{ truncate(record.content, 80) }}</span>
            <div v-if="(record.chunk_hits?.length ?? 0) > 0" class="kb-chunk-hits">
              <span class="kb-chunk-label">{{ t('knowledge.chunkHit') }}</span>
              <div v-for="hit in record.chunk_hits" :key="hit.chunk_index" class="kb-chunk-item">
                <a-tag color="default" class="kb-chunk-idx">#{{ hit.chunk_index + 1 }}</a-tag>
                <span class="kb-chunk-text">{{ truncate(hit.content, 60) }}</span>
              </div>
            </div>
          </template>
          <template v-if="column.key === 'created_at'">
            {{ formatDate(record.created_at) }}
          </template>
          <template v-if="column.key === 'actions'">
            <a-space>
              <GlassButton
                v-if="canManage(record) && record.visibility === 'private'"
                variant="ghost"
                size="sm"
                @click="openShareModal(record)"
              >
                {{ t('knowledge.share') }}
              </GlassButton>
              <GlassButton
                v-if="canManage(record) && record.visibility === 'private' && record.submission?.status !== 'pending'"
                variant="ghost"
                size="sm"
                @click="handleSubmitPublic(record)"
              >
                {{ t('knowledge.submitPublic') }}
              </GlassButton>
              <GlassButton variant="ghost" size="sm" @click="editItem(record)">
                {{ t('common.edit') }}
              </GlassButton>
              <GlassButton variant="ghost" size="sm" @click="openRevisions(record)">
                {{ t('knowledge.revisionsBtn') }}
              </GlassButton>
              <GlassButton variant="danger" size="sm" @click="confirmDelete(record)">
                {{ t('common.delete') }}
              </GlassButton>
            </a-space>
          </template>
        </template>
      </a-table>
    </GlassPanel>
    <GlassPanel v-else>
      <a-empty :description="t('common.noData')" />
    </GlassPanel>

    <!-- Share Modal -->
    <a-modal
      v-model:open="shareVisible"
      :title="t('knowledge.shareTitle')"
      :confirm-loading="sharing"
      @ok="handleShare"
      @cancel="shareVisible = false"
    >
      <p class="kb-share-target">{{ shareTarget?.title }}</p>
      <a-input
        v-model:value="shareUsernames"
        :placeholder="t('knowledge.shareUsernamesPlaceholder')"
      />
    </a-modal>

    <!-- Admin: Public Submissions Review -->
    <GlassPanel v-if="isAdmin" class="kb-review">
      <div class="kb-review-header">
        <h3 class="kb-review-title">{{ t('knowledge.adminReview') }}</h3>
      </div>
      <a-empty v-if="!publicSubmissions.length" :description="t('knowledge.reviewEmpty')" />
      <a-list v-else :data-source="publicSubmissions" row-key="knowledge_id">
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta :title="item.title" :description="truncate(item.content, 60)" />
            <template #actions>
              <a-button type="primary" size="small" @click="handleReview(item, true)">
                {{ t('knowledge.reviewApprove') }}
              </a-button>
              <a-button danger size="small" @click="handleReview(item, false)">
                {{ t('knowledge.reviewReject') }}
              </a-button>
            </template>
          </a-list-item>
        </template>
      </a-list>
    </GlassPanel>

    <!-- P0-3 同值冲突队列（admin）：新条目疑似"同一事实的新说法" -->
    <GlassPanel v-if="isAdmin" class="kb-conflicts">
      <div class="kb-review-header">
        <h3 class="kb-review-title">{{ t('knowledge.conflictQueue') }}</h3>
      </div>
      <a-empty v-if="!conflicts.length" :description="t('knowledge.conflictEmpty')" />
      <a-list v-else :data-source="conflicts" row-key="conflict_id">
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta
              :title="item.title"
              :description="t('knowledge.conflictSimilarity', { score: (item.similarity * 100).toFixed(0) })"
            />
            <template #actions>
              <a-button size="small" @click="handleResolveConflict(item, 'keep_both')">
                {{ t('knowledge.conflictKeepBoth') }}
              </a-button>
              <a-button type="primary" size="small" @click="handleResolveConflict(item, 'supersede_old')">
                {{ t('knowledge.conflictSupersede') }}
              </a-button>
            </template>
          </a-list-item>
        </template>
      </a-list>
    </GlassPanel>

    <!-- P0-2 墓碑清单（admin）：软删条目可复活 -->
    <GlassPanel v-if="isAdmin" class="kb-tombstones">
      <div class="kb-review-header">
        <h3 class="kb-review-title">{{ t('knowledge.tombstones') }}</h3>
      </div>
      <a-empty v-if="!tombstones.length" :description="t('knowledge.tombstoneEmpty')" />
      <a-list v-else :data-source="tombstones" row-key="knowledge_id">
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta
              :title="item.title"
              :description="t('knowledge.tombstoneMeta', { by: item.deleted_by || '-', superseded: item.superseded_by ? t('knowledge.tombstoneSuperseded') : '' })"
            />
            <template #actions>
              <a-button size="small" @click="handleRestore(item)">
                {{ t('knowledge.tombstoneRestore') }}
              </a-button>
            </template>
          </a-list-item>
        </template>
      </a-list>
    </GlassPanel>

    <!-- P0-2 revision 历史（属主/管理员）：update 前旧值快照 -->
    <a-drawer v-model:open="revisionsOpen" :title="t('knowledge.revisionsTitle')" width="480">
      <a-empty v-if="!revisions.length" :description="t('knowledge.revisionsEmpty')" />
      <a-timeline v-else>
        <a-timeline-item v-for="(rev, idx) in revisions" :key="idx">
          <p class="rev-time">{{ formatDate(rev.updated_at) }}</p>
          <p v-for="field in rev.changed_fields" :key="field" class="rev-field">
            <span class="rev-name">{{ field }}</span>
            <span class="rev-old">{{ truncate(String(rev.old?.[field] ?? ''), 120) }}</span>
          </p>
        </a-timeline-item>
      </a-timeline>
    </a-drawer>

    <!-- P1-1 图谱实体消解队列（admin） -->
    <GlassPanel v-if="isAdmin" class="kb-resolution">
      <div class="kb-review-header">
        <h3 class="kb-review-title">{{ t('knowledge.resolutionQueue') }}</h3>
        <a-button size="small" :loading="resolutionRunning" @click="handleRunResolution">
          {{ t('knowledge.resolutionRun') }}
        </a-button>
      </div>
      <a-empty v-if="!resolutionReviews.length" :description="t('knowledge.resolutionEmpty')" />
      <a-list v-else :data-source="resolutionReviews" row-key="review_id">
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta
              :title="`${item.left_label} ↔ ${item.right_label}`"
              :description="t('knowledge.conflictSimilarity', { score: (item.similarity * 100).toFixed(0) })"
            />
            <template #actions>
              <a-button size="small" @click="handleResolveReview(item, 'kept')">
                {{ t('knowledge.resolutionKept') }}
              </a-button>
              <a-button type="primary" size="small" @click="handleResolveReview(item, 'merged')">
                {{ t('knowledge.resolutionMerged') }}
              </a-button>
            </template>
          </a-list-item>
        </template>
      </a-list>
    </GlassPanel>

    <!-- Create / Edit Modal -->
    <a-modal
      v-model:open="modalVisible"
      :title="editingItem ? t('knowledge.editItem') : t('knowledge.createItem')"
      :confirm-loading="saving"
      width="640px"
      @ok="saveItem"
      @cancel="modalVisible = false"
    >
      <a-form layout="vertical" :rules="{ title: [{ required: true, message: t('common.required') }] }">
        <a-form-item :label="t('knowledge.itemTitle')">
          <a-input v-model:value="form.title" :placeholder="t('knowledge.titlePlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('knowledge.itemCategory')">
          <a-input v-model:value="form.category" :placeholder="t('knowledge.categoryPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('knowledge.itemContent')">
          <a-textarea v-model:value="form.content" :rows="10" :placeholder="t('knowledge.contentPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('knowledge.itemTags')">
          <a-select
            v-model:value="form.tags"
            mode="tags"
            :placeholder="t('knowledge.tagsPlaceholder')"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Import Modal -->
    <a-modal
      v-model:open="importVisible"
      :title="t('knowledge.importTitle')"
      @ok="handleImport"
      :confirm-loading="importing"
    >
      <a-upload-dragger
        :file-list="importFiles"
        :before-upload="beforeImportUpload"
        :multiple="true"
        directory
        accept=".json,.jsonl,.csv,.txt,.md,.rst,.html,.htm,.xml,.yaml,.yml,.toml,.log,.rtf,.odt,.ods,.odp,.docx,.xlsx,.pptx,.pdf"
      >
        <p class="ant-upload-text">{{ t('knowledge.dragOrClick') }}</p>
        <p class="ant-upload-hint">{{ t('knowledge.importFormats') }}</p>
      </a-upload-dragger>

      <a-divider style="margin: 12px 0" />
      <a-input
        v-model:value="importUrlValue"
        :placeholder="t('knowledge.importUrlPlaceholder')"
        style="margin-bottom: 8px"
      />
      <a-button type="primary" block :loading="importingUrl" @click="handleImportUrl">
        {{ t('knowledge.importUrl') }}
      </a-button>
    </a-modal>

    <!-- Remote KB Configs (R-7 A) -->
    <a-modal
      v-model:open="configVisible"
      :title="t('knowledge.remoteConfig')"
      :footer="null"
      width="640px"
    >
      <!-- 分类型创建表单：字段与后端适配器契约一一对应 -->
      <a-form layout="vertical" style="margin-bottom: 8px">
        <div class="kb-config-create" style="margin-bottom: 8px">
          <a-form-item :label="t('knowledge.configName')" style="flex: 1; margin-bottom: 0">
            <a-input v-model:value="configForm.name" :placeholder="t('knowledge.configNamePlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('knowledge.configSource')" style="width: 150px; margin-bottom: 0">
            <a-select v-model:value="configForm.source_type" :options="configSourceOptions" @change="onConfigTypeChange" />
          </a-form-item>
        </div>

        <!-- iflow：API Key + base_url + dataset_id -->
        <template v-if="configForm.source_type === 'iflow'">
          <a-form-item :label="t('knowledge.configApiKey')">
            <a-input-password v-model:value="configForm.credential" :placeholder="t('knowledge.configApiKeyPlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('knowledge.configBaseUrl')">
            <a-input v-model:value="configForm.base_url" :placeholder="t('knowledge.configBaseUrlIflowPh')" />
          </a-form-item>
          <a-form-item :label="t('knowledge.configDatasetId')">
            <a-input v-model:value="configForm.dataset_id" :placeholder="t('knowledge.configDatasetIdPh')" />
          </a-form-item>
        </template>

        <!-- feishu：App ID + App Secret（加密通道）+ base_url + space_id -->
        <template v-else-if="configForm.source_type === 'feishu'">
          <a-form-item :label="t('knowledge.configAppId')">
            <a-input v-model:value="configForm.app_id" :placeholder="t('knowledge.configAppIdPh')" />
          </a-form-item>
          <a-form-item :label="t('knowledge.configAppSecret')">
            <a-input-password v-model:value="configForm.credential" :placeholder="t('knowledge.configAppSecretPh')" />
          </a-form-item>
          <a-form-item :label="t('knowledge.configBaseUrl')">
            <a-input v-model:value="configForm.base_url" :placeholder="t('knowledge.configBaseUrlFeishuPh')" />
          </a-form-item>
          <a-form-item :label="t('knowledge.configSpaceId')">
            <a-input v-model:value="configForm.space_id" :placeholder="t('knowledge.configSpaceIdPh')" />
          </a-form-item>
        </template>

        <!-- ima：base_url（本机 MCP）+ Token（加密通道）+ knowledge_base_id + allow_local -->
        <template v-else-if="configForm.source_type === 'ima'">
          <a-form-item :label="t('knowledge.configBaseUrl')">
            <a-input v-model:value="configForm.base_url" :placeholder="t('knowledge.configBaseUrlImaPh')" />
          </a-form-item>
          <a-form-item :label="t('knowledge.configToken')">
            <a-input-password v-model:value="configForm.credential" :placeholder="t('knowledge.configTokenPh')" />
          </a-form-item>
          <a-form-item :label="t('knowledge.configKbId')">
            <a-input v-model:value="configForm.knowledge_base_id" :placeholder="t('knowledge.configKbIdPh')" />
          </a-form-item>
          <a-form-item :label="t('knowledge.configAllowLocal')">
            <a-switch v-model:checked="configForm.allow_local" />
            <span class="kb-config-hint">{{ t('knowledge.configAllowLocalHint') }}</span>
          </a-form-item>
        </template>

        <!-- custom：API URL + API Key（可选）+ dataset_id -->
        <template v-else>
          <a-form-item :label="t('knowledge.configApiUrl')">
            <a-input v-model:value="configForm.api_url" :placeholder="t('knowledge.configApiUrlPh')" />
          </a-form-item>
          <a-form-item :label="t('knowledge.configApiKey')">
            <a-input-password v-model:value="configForm.credential" :placeholder="t('knowledge.configApiKeyPlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('knowledge.configDatasetId')">
            <a-input v-model:value="configForm.dataset_id" :placeholder="t('knowledge.configDatasetIdPh')" />
          </a-form-item>
        </template>

        <GlassButton variant="primary" size="sm" :loading="configSaving" @click="handleCreateConfig">
          {{ t('knowledge.configCreate') }}
        </GlassButton>
      </a-form>
      <a-table
        :data-source="kbConfigs"
        :columns="configColumns"
        :pagination="false"
        row-key="id"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'actions'">
            <a-button type="link" size="small" @click="copyConfigId(record)">
              {{ t('knowledge.configCopyId') }}
            </a-button>
            <a-button type="link" danger size="small" @click="handleDeleteConfig(record)">
              {{ t('knowledge.configDelete') }}
            </a-button>
          </template>
        </template>
      </a-table>

      <a-divider style="margin: 12px 0" />
      <div class="kb-config-create">
        <a-select
          v-model:value="collectionForm.config_id"
          :options="kbConfigs.map(c => ({ label: c.name, value: c.id }))"
          :placeholder="t('knowledge.collectionConfigPh')"
          style="width: 180px"
        />
        <a-input v-model:value="collectionForm.collection_name" :placeholder="t('knowledge.collectionNamePlaceholder')" style="width: 180px" />
        <GlassButton variant="primary" size="sm" :loading="collectionSaving" @click="handleCreateCollection">
          {{ t('knowledge.collectionCreate') }}
        </GlassButton>
      </div>
      <a-table
        :data-source="kbCollections"
        :columns="collectionColumns"
        :pagination="false"
        row-key="id"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'actions'">
            <a-button type="link" danger size="small" @click="handleDeleteCollection(record)">
              {{ t('knowledge.configDelete') }}
            </a-button>
          </template>
        </template>
      </a-table>
    </a-modal>

    <!-- P2 标注闭环：精准回复命中表管理 -->
    <AnnotationDrawer v-model:open="annotationOpen" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message, Modal } from 'ant-design-vue'
import type { UploadFile } from 'ant-design-vue'
import {
  getKnowledgeNodes,
  searchKnowledge,
  createKnowledgeNode,
  updateKnowledgeNode,
  deleteKnowledgeNode,
  hybridKnowledgeSearch,
  shareKnowledgeNode,
  submitKnowledgeToPublic,
  listPublicSubmissions,
  reviewKnowledgePublic,
  listKbConfigs,
  createKbConfig,
  deleteKbConfig,
  listKbCollections,
  createKbCollection,
  deleteKbCollection,
  listKnowledgeConflicts,
  resolveKnowledgeConflict,
  listDeletedKnowledge,
  restoreKnowledgeNode,
  listKnowledgeRevisions,
  listResolutionReviews,
  resolveResolutionReview,
  runEntityResolution,
} from '@/api/modules/knowledge'
import type { KbConfig, KbCollection, KnowledgeNode, KnowledgeScope, KnowledgeConflict, DeletedKnowledge, GraphResolutionReview } from '@/api/modules/knowledge'
import { request } from '@/api'
import { useAuthStore } from '@/stores/auth'
import GlassPanel from '@/components/GlassPanel.vue'
import AnnotationDrawer from '@/modules/collaboration/AnnotationDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAgentPage } from '@/composables/useAgentPage'

interface KnowledgeItem {
  id: string
  knowledge_id?: string
  title: string
  category: string
  content: string
  tags?: string[]
  created_at?: string
  updated_at?: string
  visibility?: 'public' | 'private'
  owner_user_id?: string
  shared_with?: string[]
  submission?: { status?: string } | null
  // P0-2 分块契约：块数 + 检索命中的块级溯源
  chunk_count?: number
  chunk_hits?: { chunk_index: number; content: string; score?: number }[]
}

const { t } = useI18n()

const { agentId } = useAgentPage({
  onAgentChange: () => {
    currentPage.value = 1
    fetchKnowledge()
  },
})

const knowledgeItems = ref<KnowledgeItem[]>([])
const loading = ref(false)
const searchQuery = ref('')
const semanticSearch = ref(false)
const activeScope = ref<KnowledgeScope>('all')
const activeCategory = ref<string | undefined>(undefined)
const totalItems = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)

// P2 标注闭环：精准回复命中表抽屉
const annotationOpen = ref(false)

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')
const currentUserId = computed(() => String(authStore.user?.id ?? ''))

// 共享 / 提交 / 审批
const shareVisible = ref(false)
const sharing = ref(false)
const shareTarget = ref<KnowledgeItem | null>(null)
const shareUsernames = ref('')
const publicSubmissions = ref<KnowledgeItem[]>([])
// P0-3 冲突队列 / P0-2 墓碑 + revisions / P1-1 消解队列
const conflicts = ref<KnowledgeConflict[]>([])
const tombstones = ref<DeletedKnowledge[]>([])
const resolutionReviews = ref<GraphResolutionReview[]>([])
const resolutionRunning = ref(false)
const revisionsOpen = ref(false)
const revisions = ref<{ old: Record<string, unknown>; changed_fields: string[]; updated_at: string }[]>([])
// 语义检索的可信度映射（id → rrf 归一化分）
const confidenceMap = ref<Record<string, number>>({})

function normalizeItem(raw: KnowledgeNode): KnowledgeItem {
  return {
    ...raw,
    id: raw.id || raw.knowledge_id || '',
  } as KnowledgeItem
}

function isSharedToMe(record: KnowledgeItem): boolean {
  return (
    record.visibility === 'private' &&
    (record.shared_with ?? []).includes(currentUserId.value)
  )
}

function canManage(record: KnowledgeItem): boolean {
  return isAdmin.value || record.owner_user_id === currentUserId.value
}

function onScopeChange() {
  currentPage.value = 1
  fetchKnowledge()
}

const categoryOptions = ref<{ label: string; value: string }[]>([])

// Modal
const modalVisible = ref(false)
const saving = ref(false)
const editingItem = ref<KnowledgeItem | null>(null)
const form = ref({ title: '', category: '', content: '', tags: [] as string[] })

// Import
const importVisible = ref(false)
const importing = ref(false)
const importFiles = ref<UploadFile[]>([])
// 批量导入：支持多选 + 整文件夹（directory）；不支持扩展名入队时过滤并计数
const KB_IMPORT_EXTS = [
  'json', 'jsonl', 'csv', 'txt', 'md', 'rst', 'html', 'htm', 'xml',
  'yaml', 'yml', 'toml', 'log', 'rtf', 'odt', 'ods', 'odp', 'docx', 'xlsx', 'pptx', 'pdf',
]
const MAX_IMPORT_BATCH = 50
const importSkipped = ref(0)
const importTooMany = ref(0)
let importQueueSeq = 0
const importUrlValue = ref('')
const importingUrl = ref(false)

// R-7 A: 远程知识库配置管理
// 表单字段与后端适配器契约对齐（adapters.py）：
//   iflow: api_key(必填) + base_url/dataset_id
//   feishu: app_id + app_secret(必填) + base_url/space_id —— app_secret 走顶层
//           api_key 加密通道；其余进 settings
//   ima: base_url(必填) + token(必填) + knowledge_base_id/allow_local —— token
//        走顶层 api_key 加密通道
//   custom: api_url(必填) + api_key(可选) + dataset_id
const configVisible = ref(false)
const configSaving = ref(false)
const kbConfigs = ref<KbConfig[]>([])
interface ConfigFormState {
  name: string
  source_type: string
  /** 主凭据：iflow/custom=API Key；feishu=App Secret；ima=Token（后端加密存储） */
  credential: string
  base_url: string
  dataset_id: string
  app_id: string
  space_id: string
  api_url: string
  knowledge_base_id: string
  allow_local: boolean
}
const configForm = ref<ConfigFormState>({
  name: '',
  source_type: 'iflow',
  credential: '',
  base_url: '',
  dataset_id: '',
  app_id: '',
  space_id: '',
  api_url: '',
  knowledge_base_id: '',
  allow_local: false,
})
const configSourceOptions = [
  { label: 'iflow', value: 'iflow' },
  { label: 'feishu', value: 'feishu' },
  { label: 'ima', value: 'ima' },
  { label: 'custom', value: 'custom' },
]
const configColumns = [
  { title: t('knowledge.configName'), key: 'name', dataIndex: 'name' },
  { title: t('knowledge.configSource'), key: 'source_type', dataIndex: 'source_type' },
  { title: t('knowledge.configHasKey'), key: 'has_api_key', dataIndex: 'has_api_key', width: 90 },
  { title: t('knowledge.configId'), key: 'id', dataIndex: 'id', ellipsis: true },
  { title: '', key: 'actions', width: 130 },
]

function resetConfigForm(keepName = true) {
  const name = configForm.value.name
  configForm.value = {
    name: keepName ? name : '',
    source_type: configForm.value.source_type,
    credential: '',
    base_url: '',
    dataset_id: '',
    app_id: '',
    space_id: '',
    api_url: '',
    knowledge_base_id: '',
    allow_local: false,
  }
}

/** 切换远程库类型：清空上一类型的字段残留，避免错误值混入下一类型的 payload */
function onConfigTypeChange() {
  resetConfigForm()
}

/** 各类型必填校验（与后端适配器失败条件一致） */
function validateConfigForm(): boolean {
  const f = configForm.value
  if (!f.name.trim()) return false
  switch (f.source_type) {
    case 'iflow':
      return !!f.credential.trim()
    case 'feishu':
      return !!f.app_id.trim() && !!f.credential.trim()
    case 'ima':
      return !!f.base_url.trim() && !!f.credential.trim()
    case 'custom':
      return !!f.api_url.trim()
    default:
      return false
  }
}
const kbCollections = ref<KbCollection[]>([])
const collectionSaving = ref(false)
const collectionForm = ref<{ config_id: string; collection_name: string }>({
  config_id: '',
  collection_name: '',
})
const collectionColumns = [
  { title: t('knowledge.configName'), key: 'collection_name', dataIndex: 'collection_name' },
  { title: t('knowledge.configSource'), key: 'vector_store', dataIndex: 'vector_store' },
  { title: '', key: 'actions', width: 80 },
]

const columns = computed(() => [
  { title: t('knowledge.colTitle'), key: 'title', dataIndex: 'title', ellipsis: true },
  { title: t('knowledge.colCategory'), key: 'category', dataIndex: 'category', width: 140 },
  { title: t('knowledge.colVisibility'), key: 'visibility', width: 170 },
  { title: t('knowledge.colContent'), key: 'content', dataIndex: 'content', ellipsis: true },
  { title: t('knowledge.colCreated'), key: 'created_at', dataIndex: 'created_at', width: 160 },
  { title: t('knowledge.colActions'), key: 'actions', width: 260 },
])

const pagination = computed(() => ({
  current: currentPage.value,
  pageSize: pageSize.value,
  total: totalItems.value,
  showSizeChanger: true,
  showTotal: (total: number) => t('knowledge.totalItems', { total }),
}))

function truncate(str: string, len: number) {
  return str?.length > len ? str.slice(0, len) + '...' : str ?? ''
}

function formatDate(dateStr?: string) {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString()
}

function onTableChange(pag: any) {
  currentPage.value = pag.current
  pageSize.value = pag.pageSize
  fetchKnowledge()
}

async function handleSearch() {
  if (semanticSearch.value && searchQuery.value.trim()) {
    await semanticSearchFn()
  } else {
    currentPage.value = 1
    await fetchKnowledge()
  }
}

async function fetchKnowledge() {
  loading.value = true
  confidenceMap.value = {}
  try {
    // 关键词搜索走 POST /knowledge/search（后端带 chunk_hits 块级溯源）；
    // GET /knowledge 列表端点不支持 q（传了也被忽略，属断链）
    if (searchQuery.value.trim()) {
      const res: any = await searchKnowledge(searchQuery.value.trim(), {
        agent_id: agentId.value,
        scope: activeScope.value,
        limit: pageSize.value,
      })
      const data = res?.data ?? res
      const rawItems: KnowledgeNode[] = Array.isArray(data) ? data : data?.items ?? []
      knowledgeItems.value = rawItems.map(normalizeItem)
      totalItems.value = knowledgeItems.value.length
    } else {
      const params: Record<string, any> = {
        agent_id: agentId.value,
        scope: activeScope.value,
        page: currentPage.value,
        page_size: pageSize.value,
      }
      if (activeCategory.value) params.category = activeCategory.value

      const res: any = await getKnowledgeNodes(params)
      const data = res?.data ?? res
      const rawItems: KnowledgeNode[] = Array.isArray(data) ? data : data?.items ?? []
      knowledgeItems.value = rawItems.map(normalizeItem)
      totalItems.value = data?.total ?? knowledgeItems.value.length
    }

    // Extract categories from results
    const cats = new Set(knowledgeItems.value.map((i: KnowledgeItem) => i.category).filter(Boolean))
    if (cats.size && !categoryOptions.value.length) {
      categoryOptions.value = [...cats].map((c) => ({ label: c, value: c }))
    }
  } catch {
    message.error(t('knowledge.loadError'))
  } finally {
    loading.value = false
  }
}

async function semanticSearchFn() {
  loading.value = true
  try {
    // 批次 2：语义搜索开关首次真正生效——走 hybrid（BM25+向量+RRF）
    const res: any = await hybridKnowledgeSearch(searchQuery.value, { top_k: pageSize.value })
    const data = res?.data ?? res
    const results: any[] = data?.results ?? []
    knowledgeItems.value = results.map((r) =>
      normalizeItem({
        ...(r as any),
        id: r.id,
        title: r.title || truncate(r.content, 40),
        category: 'semantic',
      }),
    )
    confidenceMap.value = Object.fromEntries(
      results.map((r) => [r.id, r.confidence_breakdown?.rrf ?? r.rrf_score ?? 0]),
    )
    totalItems.value = results.length
    if (!results.length) message.info(t('knowledge.searchError'))
  } catch {
    message.error(t('knowledge.searchError'))
  } finally {
    loading.value = false
  }
}

function openCreateModal() {
  editingItem.value = null
  form.value = { title: '', category: '', content: '', tags: [] }
  modalVisible.value = true
}

// ── 共享 / 提交公共库 / 管理员审批 ──────────────────────────

function openShareModal(record: KnowledgeItem) {
  shareTarget.value = record
  shareUsernames.value = ''
  shareVisible.value = true
}

async function handleShare() {
  if (!shareTarget.value) return
  const names = shareUsernames.value
    .split(/[,，;；\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (!names.length) {
    message.error(t('knowledge.shareUsernamesPlaceholder'))
    return
  }
  sharing.value = true
  try {
    await shareKnowledgeNode(shareTarget.value.id, names)
    message.success(t('knowledge.shareSuccess'))
    shareVisible.value = false
    fetchKnowledge()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    message.error(typeof detail === 'string' ? detail : t('knowledge.shareError'))
  } finally {
    sharing.value = false
  }
}

function handleSubmitPublic(record: KnowledgeItem) {
  Modal.confirm({
    title: t('knowledge.submitPublic'),
    content: t('knowledge.submitConfirm'),
    okText: t('common.confirm'),
    cancelText: t('common.cancel'),
    onOk: async () => {
      try {
        await submitKnowledgeToPublic(record.id)
        message.success(t('knowledge.submitSuccess'))
        fetchKnowledge()
      } catch (err: any) {
        const detail = err?.response?.data?.detail
        message.error(typeof detail === 'string' ? detail : t('knowledge.submitError'))
      }
    },
  })
}

async function fetchSubmissions() {
  if (!isAdmin.value) return
  try {
    const res: any = await listPublicSubmissions()
    const data = res?.data ?? res
    const rawItems: any[] = Array.isArray(data) ? data : data?.items ?? []
    publicSubmissions.value = rawItems.map(normalizeItem)
  } catch {
    message.error(t('knowledge.loadSubmissionsError'))
  }
}

async function handleReview(item: KnowledgeItem, approve: boolean) {
  try {
    await reviewKnowledgePublic(item.id, approve)
    message.success(t('knowledge.reviewSuccess'))
    await fetchSubmissions()
    fetchKnowledge()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    message.error(typeof detail === 'string' ? detail : t('knowledge.reviewError'))
  }
}

// ── P0-3 同值冲突 / P0-2 墓碑 + revisions / P1-1 消解 ──────────

async function fetchConflicts() {
  if (!isAdmin.value) return
  try {
    const res: any = await listKnowledgeConflicts('pending')
    const data = res?.data ?? res
    conflicts.value = Array.isArray(data) ? data : data?.items ?? []
  } catch {
    conflicts.value = []
  }
}

async function handleResolveConflict(item: KnowledgeConflict, resolution: 'keep_both' | 'supersede_old') {
  try {
    await resolveKnowledgeConflict(item.conflict_id, resolution)
    message.success(t('knowledge.conflictResolved'))
    await fetchConflicts()
    fetchKnowledge()
    if (isAdmin.value) fetchTombstones()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    message.error(typeof detail === 'string' ? detail : t('knowledge.reviewError'))
  }
}

async function fetchTombstones() {
  if (!isAdmin.value) return
  try {
    const res: any = await listDeletedKnowledge()
    tombstones.value = Array.isArray(res?.data ?? res) ? res?.data ?? res : []
  } catch {
    tombstones.value = []
  }
}

async function handleRestore(item: DeletedKnowledge) {
  try {
    await restoreKnowledgeNode(item.knowledge_id)
    message.success(t('knowledge.tombstoneRestored'))
    await fetchTombstones()
    fetchKnowledge()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    message.error(typeof detail === 'string' ? detail : t('knowledge.tombstoneRestoreError'))
  }
}

async function openRevisions(item: KnowledgeItem) {
  try {
    const res: any = await listKnowledgeRevisions(item.id)
    revisions.value = Array.isArray(res) ? res : (res?.data ?? [])
    revisionsOpen.value = true
  } catch {
    message.error(t('knowledge.revisionsError'))
  }
}

async function fetchResolutionReviews() {
  if (!isAdmin.value) return
  try {
    const res: any = await listResolutionReviews(agentId.value)
    resolutionReviews.value = res?.data?.reviews ?? []
  } catch {
    resolutionReviews.value = []
  }
}

async function handleRunResolution() {
  resolutionRunning.value = true
  try {
    await runEntityResolution(agentId.value)
    message.success(t('knowledge.resolutionRan'))
    await fetchResolutionReviews()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    message.error(typeof detail === 'string' ? detail : t('knowledge.resolutionRunError'))
  } finally {
    resolutionRunning.value = false
  }
}

async function handleResolveReview(item: GraphResolutionReview, decision: 'merged' | 'kept') {
  try {
    await resolveResolutionReview(agentId.value, item.review_id, decision)
    message.success(t('knowledge.resolutionResolved'))
    await fetchResolutionReviews()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    message.error(typeof detail === 'string' ? detail : t('knowledge.resolutionRunError'))
  }
}

function editItem(item: KnowledgeItem) {
  editingItem.value = item
  form.value = {
    title: item.title,
    category: item.category,
    content: item.content,
    tags: item.tags ?? [],
  }
  modalVisible.value = true
}

async function saveItem() {
  saving.value = true
  try {
    if (editingItem.value) {
      await updateKnowledgeNode(editingItem.value.id, form.value, { agent_id: agentId.value })
      message.success(t('knowledge.updateSuccess'))
    } else {
      await createKnowledgeNode({ ...form.value, agent_id: agentId.value })
      message.success(t('knowledge.createSuccess'))
    }
    modalVisible.value = false
    fetchKnowledge()
  } catch {
    message.error(t('knowledge.saveError'))
  } finally {
    saving.value = false
  }
}

function confirmDelete(item: KnowledgeItem) {
  Modal.confirm({
    title: t('knowledge.confirmDelete'),
    content: item.title,
    okText: t('common.confirm'),
    cancelText: t('common.cancel'),
    onOk: async () => {
      try {
        await deleteKnowledgeNode(item.id, { agent_id: agentId.value })
        knowledgeItems.value = knowledgeItems.value.filter((k) => k.id !== item.id)
        message.success(t('knowledge.deleteSuccess'))
      } catch {
        message.error(t('knowledge.deleteError'))
      }
    },
  })
}

function exportKnowledge() {
  const blob = new Blob([JSON.stringify(knowledgeItems.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'knowledge-export.json'
  a.click()
  URL.revokeObjectURL(url)
  message.success(t('knowledge.exportSuccess'))
}

function beforeImportUpload(file: File) {
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (!KB_IMPORT_EXTS.includes(ext)) {
    importSkipped.value++
    return false
  }
  if (importFiles.value.length >= MAX_IMPORT_BATCH) {
    importTooMany.value++
    return false
  }
  importFiles.value = [
    ...importFiles.value,
    { uid: `kbq-${++importQueueSeq}`, name: file.name, status: 'done', originFileObj: file } as any,
  ]
  return false
}

/** 批量导入：逐个文件上传，聚合成功/失败结果（支持多选与整文件夹队列） */
async function handleImport() {
  if (!importFiles.value.length) return
  importing.value = true
  const failures: string[] = []
  let success = 0
  try {
    for (const entry of importFiles.value) {
      const file = (entry as any).originFileObj as File
      const formData = new FormData()
      formData.append('file', file)
      try {
        // 后端对抽取失败（旧版 .ppt/纯图片页等）返回 code=1 + status，
        // 不再以成功语义静默返回空列表——按文件聚合失败原因
        const res: any = await request.post('/knowledge/import', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
          params: { agent_id: agentId.value },
        })
        const status: string = res?.data?.status || ''
        if (res?.code !== 0 || !res?.data?.items?.length) {
          failures.push(`${file.name}（${importFailText(status)}）`)
          continue
        }
        success++
      } catch {
        failures.push(`${file.name}（${t('knowledge.importError')}）`)
      }
    }
    importVisible.value = false
    importFiles.value = []
    if (importSkipped.value > 0) message.info(t('knowledge.importSkippedUnsupported', { n: importSkipped.value }))
    if (success > 0 && failures.length === 0) {
      message.success(t('knowledge.importBatchSuccess', { n: success }))
    } else if (success > 0) {
      message.warning(t('knowledge.importBatchPartial', { success, fail: failures.length }))
    } else {
      message.error(failures.join('；') || t('knowledge.importError'))
    }
    if (success > 0) fetchKnowledge()
  } finally {
    importing.value = false
  }
}

function importFailText(status: string): string {
  if (status === 'unsupported_format') return t('knowledge.importUnsupported')
  return t('knowledge.importParseFailed')
}

async function handleImportUrl() {
  const url = importUrlValue.value.trim()
  if (!url) {
    message.error(t('knowledge.importError'))
    return
  }
  importingUrl.value = true
  try {
    await request.post('/knowledge/import-url', null, {
      params: { agent_id: agentId.value, url },
    })
    message.success(t('knowledge.importSuccess'))
    importUrlValue.value = ''
    fetchKnowledge()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    message.error(typeof detail === 'string' ? detail : t('knowledge.importError'))
  } finally {
    importingUrl.value = false
  }
}

// R-7 A: 远程配置管理
async function fetchKbConfigs() {
  try {
    const res: any = await listKbConfigs()
    const data = res?.data ?? {}
    kbConfigs.value = data?.configs ?? []
  } catch {
    message.error(t('knowledge.importError'))
  }
}

async function handleCreateConfig() {
  if (!validateConfigForm()) {
    message.error(t('knowledge.configMissingRequired'))
    return
  }
  configSaving.value = true
  try {
    const f = configForm.value
    const settings: Record<string, unknown> = {}
    if (f.base_url.trim()) settings.base_url = f.base_url.trim()
    if (f.dataset_id.trim()) settings.dataset_id = f.dataset_id.trim()
    if (f.app_id.trim()) settings.app_id = f.app_id.trim()
    if (f.space_id.trim()) settings.space_id = f.space_id.trim()
    if (f.api_url.trim()) settings.api_url = f.api_url.trim()
    if (f.knowledge_base_id.trim()) settings.knowledge_base_id = f.knowledge_base_id.trim()
    if (f.source_type === 'ima') settings.allow_local = f.allow_local

    await createKbConfig({
      name: f.name.trim(),
      source_type: f.source_type,
      // 主凭据走顶层 api_key（后端 Fernet 加密存储）：
      // iflow/custom=API Key、feishu=App Secret、ima=Token
      api_key: f.credential.trim() || undefined,
      settings,
    })
    message.success(t('knowledge.importSuccess'))
    resetConfigForm(false)
    await fetchKbConfigs()
  } catch {
    message.error(t('knowledge.importError'))
  } finally {
    configSaving.value = false
  }
}

async function handleDeleteConfig(record: KbConfig) {
  try {
    await deleteKbConfig(record.id)
    message.success(t('knowledge.importSuccess'))
    await fetchKbConfigs()
  } catch {
    message.error(t('knowledge.importError'))
  }
}

function copyConfigId(record: KbConfig) {
  try {
    navigator.clipboard.writeText(record.id)
    message.success(t('knowledge.configIdCopied'))
  } catch {
    message.error(t('knowledge.importError'))
  }
}

async function fetchKbCollections() {
  try {
    const res: any = await listKbCollections()
    const data = res?.data ?? {}
    kbCollections.value = data?.collections ?? []
  } catch {
    message.error(t('knowledge.importError'))
  }
}

async function handleCreateCollection() {
  if (!collectionForm.value.config_id || !collectionForm.value.collection_name) {
    message.error(t('knowledge.configFormIncomplete'))
    return
  }
  collectionSaving.value = true
  try {
    await createKbCollection({ ...collectionForm.value, vector_store: 'qdrant' })
    message.success(t('knowledge.importSuccess'))
    collectionForm.value = { config_id: '', collection_name: '' }
    await fetchKbCollections()
  } catch {
    message.error(t('knowledge.importError'))
  } finally {
    collectionSaving.value = false
  }
}

async function handleDeleteCollection(record: KbCollection) {
  try {
    await deleteKbCollection(record.id)
    message.success(t('knowledge.importSuccess'))
    await fetchKbCollections()
  } catch {
    message.error(t('knowledge.importError'))
  }
}

onMounted(() => {
  fetchKnowledge()
  fetchKbConfigs()
  fetchKbCollections()
  fetchSubmissions()
  fetchConflicts()
  fetchTombstones()
  fetchResolutionReviews()
})

// 闭环审查：消解队列按 agent 分库，切换 agent 后 admin 面板数据会陈旧
watch(agentId, () => {
  if (!isAdmin.value) return
  fetchResolutionReviews()
})
</script>

<style scoped>
.knowledge-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 远程配置创建表单：名称 + 类型 一行 */
.kb-config-create {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}

.kb-config-hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--nr-text-tertiary, #999);
}


.kb-header .header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-title {
  font-family: var(--nr-font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--nr-text-primary);
  margin: 0;
  white-space: nowrap;
}

.kb-title-cell {
  font-weight: 500;
  color: var(--nr-text-primary);
}

.kb-conf-tag {
  margin-left: 6px;
}

.kb-preview {
  font-size: 13px;
  color: var(--nr-text-secondary);
}

/* P0-2 块级溯源：命中片段明细 */
.kb-chunk-hits {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.kb-chunk-label {
  font-size: 12px;
  color: var(--nr-text-tertiary, #999);
}

.kb-chunk-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
}

.kb-chunk-idx {
  flex-shrink: 0;
  margin: 0;
  font-family: monospace;
}

.kb-chunk-text {
  color: var(--nr-text-secondary);
  word-break: break-all;
}

.kb-share-target {
  margin: 0 0 12px;
  font-weight: 500;
  color: var(--nr-text-primary);
}

.kb-review-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
}

.kb-review-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--nr-text-primary);
}

.rev-time {
  margin: 0 0 4px;
  font-size: 12px;
  color: var(--nr-text-secondary);
}

.rev-field {
  margin: 2px 0;
  font-size: 13px;
}

.rev-name {
  display: inline-block;
  min-width: 72px;
  font-weight: 600;
  color: var(--nr-text-primary);
}

.rev-old {
  color: var(--nr-text-secondary);
  word-break: break-all;
}
</style>
