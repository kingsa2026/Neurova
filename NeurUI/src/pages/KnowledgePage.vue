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
          <a-popover v-model:open="filterOpen" trigger="click" placement="bottomLeft">
            <template #content>
              <div class="kb-filter-form">
                <a-input v-model:value="metaFilters.author" size="small" :placeholder="t('knowledge.filterAuthor')" />
                <a-input v-model:value="metaFilters.source_type" size="small" :placeholder="t('knowledge.filterSourceType')" />
                <a-select v-model:value="metaFilters.ocr_used" size="small" allow-clear :placeholder="t('knowledge.filterOcrUsed')"
                          :options="[{ value: true, label: t('knowledge.filterOcrYes') }, { value: false, label: t('knowledge.filterOcrNo') }]" />
                <a-input-number v-model:value="metaFilters.page_min" size="small" :min="0" :placeholder="t('knowledge.filterPageMin')" style="width: 100%" />
                <a-input v-model:value="metaFilters.source" size="small" :placeholder="t('knowledge.filterSource')" />
                <a-date-picker v-model:value="metaFilters.modifiedRange" type="daterange" value-format="YYYY-MM-DD" size="small"
                               style="width: 100%" :placeholder="[t('knowledge.filterDocModifiedFrom'), t('knowledge.filterDocModifiedTo')]" />
                <div class="kb-filter-actions">
                  <GlassButton size="sm" @click="clearMetaFilters">{{ t('knowledge.filterClear') }}</GlassButton>
                  <GlassButton size="sm" variant="primary" @click="applyMetaFilters">{{ t('knowledge.filterApply') }}</GlassButton>
                </div>
              </div>
            </template>
            <a-badge :count="activeFilterCount" size="small">
              <GlassButton variant="secondary" size="sm">{{ t('knowledge.filterMore') }}</GlassButton>
            </a-badge>
          </a-popover>
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
            @change="onCategoryFilterChange"
          />
          <!-- 分类管理入口（admin）：分类注册表的管理面接线，变更后刷新分类下拉 -->
          <GlassButton v-if="isAdmin" variant="ghost" size="sm" @click="catMgmtOpen = true">
            {{ t('knowledge.catMgmtTitle') }}
          </GlassButton>
          <GlassButton variant="secondary" size="sm" @click="exportKnowledge">
            {{ t('knowledge.export') }}
          </GlassButton>
          <GlassButton variant="secondary" size="sm" @click="importVisible = true">
            {{ t('knowledge.import') }}
          </GlassButton>
          <GlassButton variant="ghost" size="sm" @click="configVisible = true; fetchKbConfigs()">
            {{ t('knowledge.remoteConfig') }}
          </GlassButton>
          <GlassButton variant="ghost" size="sm" @click="mcpVisible = true; fetchMcpSources()">
            {{ t('knowledge.mcpTitle') }}
          </GlassButton>
          <GlassButton variant="ghost" size="sm" @click="openIngress()">
            {{ t('knowledge.ingressBtn') }}
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
      <div v-if="selectedRowKeys.length > 0" class="kb-batch-bar">
        <span class="kb-batch-count">{{ t('knowledge.batchSelected', { n: selectedRowKeys.length }) }}</span>
        <GlassButton variant="primary" size="sm" @click="openBatchCategory">
          {{ t('knowledge.batchCategorize') }}
        </GlassButton>
        <GlassButton variant="ghost" size="sm" @click="clearSelection">
          {{ t('knowledge.batchClearSelection') }}
        </GlassButton>
      </div>
      <a-table
        :columns="columns"
        :data-source="knowledgeItems"
        :loading="loading"
        :locale="{ emptyText: '' }"
        :pagination="pagination"
        :row-selection="rowSelection"
        row-key="id"
        @change="onTableChange"
      >
        <template #expandedRowRender="{ record }">
          <div class="kb-meta-detail">
            <div v-if="record.source_created_at" class="kb-meta-line">
              <span class="kb-meta-name">{{ t('knowledge.itemSourceCreated') }}</span>
              <span>{{ formatTimestampText(record.source_created_at) }}</span>
            </div>
            <div v-if="record.source_modified_at" class="kb-meta-line">
              <span class="kb-meta-name">{{ t('knowledge.itemSourceModified') }}</span>
              <span>{{ formatTimestampText(record.source_modified_at) }}</span>
            </div>
            <div v-if="record.geo" class="kb-meta-line">
              <span class="kb-meta-name">{{ t('knowledge.itemGeo') }}</span>
              <span>{{ record.geo.lat }}, {{ record.geo.lon }}</span>
            </div>
            <div class="kb-meta-line">
              <span class="kb-meta-name">{{ t('knowledge.sourcesTitle') }}</span>
              <template v-if="(record.sources || []).length">
                <a-tag v-for="(src, i) in record.sources" :key="i" class="kb-src-tag">
                  {{ src.source || src.source_type || src.source_path || '-' }}<template v-if="src.ingest_time"> · {{ src.ingest_time }}</template>
                </a-tag>
              </template>
              <span v-else class="kb-src-empty">{{ t('knowledge.sourcesEmpty') }}</span>
            </div>
          </div>
        </template>
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
            {{ formatEpochSecondDate(record.created_at) }}
          </template>
          <template v-if="column.key === 'source_modified_at'">
            {{ formatTimestampText(record.source_modified_at) }}
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
              <GlassButton variant="ghost" size="sm" @click="openChunks(record)">
                {{ t('knowledge.chunksBtn') }}
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

    <!-- 冲突队列（admin）：条目侧同值 + 治理层分歧，两条轴一个队列（工单 016） -->
    <GlassPanel v-if="isAdmin" class="kb-conflicts">
      <div class="kb-review-header">
        <h3 class="kb-review-title">{{ t('knowledge.conflictQueue') }}</h3>
      </div>
      <a-empty v-if="!conflicts.length" :description="t('knowledge.conflictEmpty')" />
      <a-list v-else :data-source="conflicts" row-key="conflict_id">
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta
              :title="conflictTitle(item)"
              :description="conflictDescription(item)"
            />
            <div class="kb-conflict-meta">
              <a-tag data-testid="conflict-axis">{{ t(`conflictAxis.${item.axis}`) }}</a-tag>
              <template v-if="item.axis === 'entry' && item.time_context">
                <a-tag data-testid="conflict-newer-side">{{ conflictNewerSideLabel(item.time_context) }}</a-tag>
                <p class="kb-conflict-basis" data-testid="conflict-time-readout">
                  {{ conflictTimeReadout(item.time_context) }}
                </p>
              </template>
              <template v-if="item.axis === 'fact'">
                <a-tag data-testid="conflict-kind">{{ enumLabel('conflictKind', item.kind) }}</a-tag>
                <a-tag :color="item.severity >= 0.7 ? 'red' : 'orange'">
                  {{ t('knowledge.conflictSeverity', { score: Math.round(item.severity * 100) }) }}
                </a-tag>
                <a-tag color="blue">
                  {{ t('knowledge.conflictPolicy', { policy: conflictPolicyLabel(item.recommended_policy) }) }}
                </a-tag>
                <a-tag v-if="conflictPolicies[item.predicate_term_id]" data-testid="conflict-declared-policy">
                  {{ t('ontology.conflictDeclaredPolicy', { policy: conflictPolicies[item.predicate_term_id] }) }}
                </a-tag>
                <a-tag v-if="!item.policy_basis" color="red" data-testid="conflict-no-basis">
                  {{ t('knowledge.conflictNoBasis') }}
                </a-tag>
                <p v-if="item.policy_basis" class="kb-conflict-basis">{{ item.policy_basis }}</p>
                <!-- C2：LLM 参考意见（只读辅助，不参与自动裁决） -->
                <p
                  v-if="conflictLlmAdvice[item.conflict_id]"
                  class="kb-conflict-basis"
                  data-testid="conflict-llm-advice"
                >🤖 {{ conflictLlmAdvice[item.conflict_id] }}</p>
              </template>
            </div>
            <template #actions>
              <a-button size="small" @click="handleResolveConflict(item, 'keep_both')">
                {{ t('knowledge.conflictKeepBoth') }}
              </a-button>
              <a-button
                v-if="item.axis === 'entry'"
                type="primary"
                size="small"
                @click="handleResolveConflict(item, 'supersede_old')"
              >
                {{ t('knowledge.conflictSupersede') }}
              </a-button>
              <template v-else>
                <!-- 事实侧没有"自动裁决"这条路：胜方必须有人指明，无依据也不给一键关闭 -->
                <a-select
                  v-model:value="conflictWinner[item.conflict_id]"
                  size="small"
                  :placeholder="t('knowledge.conflictPickWinner')"
                  style="width: 190px"
                  :options="conflictMemberOptions(item)"
                />
                <a-button
                  type="primary"
                  size="small"
                  :disabled="!conflictWinner[item.conflict_id]"
                  @click="handleResolveConflict(item, 'supersede_old')"
                >
                  {{ t('knowledge.conflictSupersede') }}
                </a-button>
                <a-button size="small" @click="handleResolveConflict(item, 'dismiss')">
                  {{ t('knowledge.conflictDismiss') }}
                </a-button>
                <!-- 裁决前先看清每条说法的来源：血缘抽屉吃 member_fact_id，选中的成员优先 -->
                <a-button size="small" @click="openLineage(conflictLineageTarget(item))">
                  {{ t('knowledge.conflictViewLineage') }}
                </a-button>
                <!-- C2：LLM 语义参考意见（管理员主动触发，仅 pending 事实轴冲突） -->
                <a-button
                  size="small"
                  :loading="!!conflictLlmAdviceLoading[item.conflict_id]"
                  @click="handleRequestLlmAdvice(item)"
                >
                  {{ t('knowledge.conflictLlmAdvice') }}
                </a-button>
              </template>
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
      <template v-else>
        <h4 class="rev-section">{{ t('knowledge.revisionsTimelineTitle') }}</h4>
        <a-timeline>
        <a-timeline-item v-for="(rev, idx) in revisions" :key="idx">
          <p class="rev-time">
            {{ formatTimestampText(rev.updated_at) }}
            <a-tag v-if="rev.reason" color="blue" class="rev-reason" data-testid="revision-reason">
              {{ rev.reason === 'rollback' ? t('knowledge.revisionReasonRollback') : t('knowledge.revisionReasonReingest') }}
            </a-tag>
          </p>
          <p v-for="field in rev.changed_fields" :key="field" class="rev-field">
            <span class="rev-name">{{ field }}</span>
            <span class="rev-old">{{ truncate(String(rev.old?.[field] ?? ''), 120) }}</span>
          </p>
          <GlassButton size="sm" variant="secondary" data-testid="revision-diff-btn"
                       @click="toggleRevisionDiff(idx)">
            {{ t('knowledge.revisionDiffBtn') }}
          </GlassButton>
          <div v-if="diffOpen[idx]" class="rev-diff" data-testid="revision-diff">
            <p v-for="field in rev.changed_fields" :key="'diff-' + field" class="rev-diff-row">
              <span class="rev-name">{{ field }}</span>
              <span class="rev-old">{{ t('knowledge.revisionDiffOld') }}: {{ truncate(String(rev.old?.[field] ?? ''), 160) }}</span>
              <span class="rev-new">{{ t('knowledge.revisionDiffNew') }}: {{ truncate(revisionNewValue(idx, field), 160) }}</span>
            </p>
          </div>
          <GlassButton v-if="isAdmin && revisionsEntry && canManage(revisionsEntry)"
                       size="sm" variant="secondary" data-testid="revision-rollback-btn"
                       :loading="rollbackPending === idx" @click="handleRevisionRollback(idx)">
            {{ t('knowledge.revisionsRollbackBtn') }}
          </GlassButton>
        </a-timeline-item>
        </a-timeline>
        <h4 class="rev-section">{{ t('knowledge.versionsTitle') }}</h4>
        <a-empty v-if="!versions.length" :description="t('knowledge.revisionsEmpty')" />
        <div v-for="ver in versions" :key="ver.version" class="version-row" data-testid="version-snapshot">
          <span class="mono">v{{ ver.version }}</span>
          <a-tag color="blue">{{ versionReasonLabel(ver.reason) }}</a-tag>
          <span class="rev-time">{{ formatTimestampText(ver.time) }}</span>
          <span class="rev-actor">{{ ver.actor }}</span>
        </div>
      </template>
    </a-drawer>

    <!-- P1-1 图谱实体消解队列（admin） -->
    <GlassPanel v-if="isAdmin" class="kb-resolution">
      <div class="kb-review-header">
        <h3 class="kb-review-title">{{ t('knowledge.resolutionQueue') }}</h3>
        <a-button size="small" :loading="resolutionRunning" @click="handleRunResolution">
          {{ t('knowledge.resolutionRun') }}
        </a-button>
      </div>
      <div v-if="blockingStats" class="kb-blocking-readout" data-testid="blocking-readout">
        {{ t('ontology.blockingReadout', { blocked: blockingStats.blocking, full: blockingStats.full_scan, pct: blockingStats.reduction_pct }) }}
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
          <a-select
            v-model:value="form.category"
            :options="categoryOptions"
            allow-clear
            :placeholder="t('knowledge.categoryPlaceholder')"
          />
        </a-form-item>
        <a-form-item :label="t('knowledge.itemContent')">
          <a-textarea v-model:value="form.content" :rows="10" :placeholder="t('knowledge.contentPlaceholder')" />
          <!-- P1#7 切分 live-preview：与生产单源（split_with_meta/build_entry_chunks） -->
          <div class="kb-preview-row">
            <a-select
              v-if="chunkStrategies.length"
              v-model:value="chunkStrategyId"
              size="small"
              allow-clear
              style="min-width: 180px"
              :options="chunkStrategyOptions"
              :placeholder="t('knowledge.chunkStrategyPlaceholder')"
              data-testid="chunk-strategy-select"
            />
            <a-select
              v-model:value="communityMode"
              size="small"
              style="min-width: 120px"
              :options="[{ value: '', label: t('knowledge.communityModeDefault') },
                         { value: 'global', label: t('knowledge.communityModeGlobal') },
                         { value: 'drift', label: t('knowledge.communityModeDrift') }]"
              :placeholder="t('knowledge.communityModePlaceholder')"
              data-testid="community-mode-select"
            />
            <a-button type="link" size="small" :loading="previewLoading" @click="handlePreviewChunking">
              {{ t('knowledge.previewBtn') }}
            </a-button>
            <span v-if="previewResult" class="kb-config-hint">
              {{ t('knowledge.previewResult', {
                children: previewResult.children.length,
                parents: previewResult.parents.length,
                maxChars: previewResult.max_chars,
              }) }}
            </span>
          </div>
          <div v-if="previewResult" class="kb-preview-list">
            <div v-for="c in previewResult.children.slice(0, 8)" :key="c.index" class="kb-preview-item">
              #{{ c.index }}<template v-if="c.context_header"> · HEAD</template>
              : {{ String(c.content || '').slice(0, 60) }}…
            </div>
          </div>
        </a-form-item>
        <a-form-item :label="t('knowledge.itemTags')">
          <a-select
            v-model:value="form.tags"
            mode="tags"
            :placeholder="t('knowledge.tagsPlaceholder')"
          />
        </a-form-item>
        <a-form-item :label="t('knowledge.itemAuthor')">
          <a-input v-model:value="form.author" :placeholder="t('knowledge.itemAuthor')" />
        </a-form-item>
        <a-form-item :label="t('knowledge.itemGeo')">
          <div class="kb-geo-row">
            <a-input-number v-model:value="form.geoLat" size="small" :min="-90" :max="90" :placeholder="t('knowledge.geoLat')" />
            <a-input-number v-model:value="form.geoLon" size="small" :min="-180" :max="180" :placeholder="t('knowledge.geoLon')" />
          </div>
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
      <a-form-item :label="t('knowledge.importCategory')" style="margin-bottom: 12px">
        <p class="modules-hint">{{ t('knowledge.importCategoryHint') }}</p>
        <a-select
          v-model:value="importCategory"
          :options="categoryOptions"
          allow-clear
          :placeholder="t('knowledge.importCategoryPlaceholder')"
        />
      </a-form-item>
      <a-upload-dragger
        :file-list="importFiles"
        :before-upload="beforeImportUpload"
        :multiple="true"
        :accept="kbImportAcceptAttr"
      >
        <p class="ant-upload-text">{{ t('knowledge.dragOrClick') }}</p>
        <p class="ant-upload-hint">{{ t('knowledge.importFormats') }}</p>
      </a-upload-dragger>
      <!-- 整文件夹为独立入口：原生目录对话框会忽略 accept（无类型过滤），入队前按扩展名过滤兜底 -->
      <div style="margin-top: 8px">
        <a-upload
          :before-upload="beforeImportUpload"
          :show-upload-list="false"
          directory
        >
          <GlassButton variant="ghost" size="sm">{{ t('knowledge.importFolder') }}</GlassButton>
        </a-upload>
      </div>

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
          <a-form-item :label="t('knowledge.configSyncInterval')">
            <a-input-number v-model:value="configForm.sync_interval_minutes" :min="0" :max="1440" style="width: 100%" />
            <span class="kb-config-hint">{{ t('knowledge.configSyncIntervalHint') }}</span>
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
            <a-button
              v-if="record.source_type === 'feishu'"
              type="link"
              size="small"
              :loading="syncingConfigId === record.id"
              @click="handleSyncConfig(record)"
            >
              {{ t('knowledge.configSyncNow') }}
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

    <!-- P1#12（WeKnora）：摄取任务 span 时间线 + stop-parse -->
    <a-modal v-model:open="ingressVisible" :title="t('knowledge.ingressTitle')" :footer="null" width="820px">
      <div class="kb-ingress-toolbar">
        <a-space size="small">
          <a-tag v-for="(n, k) in ingressStats" :key="k" :color="ingressStatColor(String(k))">
            {{ ingressStatusLabel(String(k)) }} {{ n }}
          </a-tag>
        </a-space>
        <GlassButton variant="ghost" size="sm" :loading="ingressLoading" @click="refreshIngress">
          {{ t('knowledge.ingressRefresh') }}
        </GlassButton>
      </div>
      <a-table
        :data-source="ingressTasks"
        :columns="ingressColumns"
        :pagination="false"
        :loading="ingressLoading"
        row-key="task_id"
        size="small"
        :expand-column-width="36"
        @expand="(expanded: boolean, record: IngressTask) => expanded && handleIngressExpand(record)"
      >
        <template #expandedRowRender="{ record }">
          <a-spin :spinning="!!spanLoading[record.task_id]">
            <div v-if="!(spanMap[record.task_id] || []).length" class="kb-config-hint">
              {{ t('common.noData') }}
            </div>
            <div v-for="sp in spanMap[record.task_id] || []" :key="sp.stage" class="kb-span-row">
              <a-tag :color="ingressStatusColor(sp.status)">{{ ingressStatusLabel(sp.status) }}</a-tag>
              <span class="kb-span-stage">{{ ingressStageLabel(sp.stage) }}</span>
              <span class="kb-span-time">{{ sp.updated_at || '' }}</span>
              <span v-if="sp.error" class="kb-span-error">{{ sp.error }}</span>
            </div>
          </a-spin>
        </template>
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="ingressStatusColor(record.status)">{{ ingressStatusLabel(record.status) }}</a-tag>
          </template>
          <template v-if="column.key === 'actions'">
            <a-button
              v-if="record.status === 'pending' || record.status === 'processing'"
              type="link"
              size="small"
              danger
              @click="handleCancelIngress(record)"
            >
              {{ t('knowledge.ingressCancel') }}
            </a-button>
          </template>
        </template>
      </a-table>
    </a-modal>

    <!-- P1#12（WeKnora）：块级查看与编辑（乐观锁 + 修订账本） -->
    <a-modal v-model:open="chunksVisible" :title="t('knowledge.chunksTitle')" :footer="null" width="760px">
      <a-spin :spinning="chunksLoading">
        <a-empty v-if="!chunkRows.length" :description="t('common.noData')" />
        <div v-for="ch in chunkRows" :key="ch.index" class="kb-chunk-row">
          <div class="kb-chunk-meta">
            #{{ ch.index }}
            <a-tag v-if="ch.parent_index !== undefined">P{{ ch.parent_index }}</a-tag>
            <a-tag v-if="ch.revision" color="blue">{{ t('knowledge.chunkRevision') }} {{ ch.revision }}</a-tag>
            <a-button type="link" size="small" @click="showChunkHistory(ch.index)">
              {{ t('knowledge.chunkHistory') }}
            </a-button>
          </div>
          <a-textarea v-model:value="ch.content" :auto-size="{ minRows: 2, maxRows: 8 }" />
          <div class="kb-chunk-actions">
            <GlassButton variant="primary" size="sm" :loading="savingChunkIndex === ch.index" @click="handleSaveChunk(ch)">
              {{ t('common.save') }}
            </GlassButton>
            <span class="kb-config-hint">{{ ch.index_status === 'pending' ? t('knowledge.chunkIndexPending') : '' }}</span>
          </div>
        </div>
        <template v-if="chunkHistory.length">
          <a-divider style="margin: 12px 0" />
          <div class="kb-chunk-meta">{{ t('knowledge.chunkHistory') }}</div>
          <div v-for="(r, i) in chunkHistory" :key="i" class="kb-chunk-rev">
            <span>{{ r.at }} · {{ r.by || '-' }}</span>
            <div class="kb-chunk-rev-body">{{ r.content }}</div>
          </div>
        </template>
      </a-spin>
    </a-modal>

    <!-- P2 标注闭环：精准回复命中表管理 -->
    <AnnotationDrawer v-model:open="annotationOpen" />

    <!-- 工单 024：事实血缘抽屉（也可从推导跳里的前提继续往回走） -->
    <KnowledgeLineageDrawer
      v-model:open="lineageOpen"
      :fact-id="lineageFactId"
      @open-fact="openLineage"
    />

    <!-- 分类管理（admin）：变更后刷新分类下拉与过滤选项 -->
    <CategoryManagerModal v-model:open="catMgmtOpen" @changed="fetchCategories" />

    <!-- 批量分类：选中条目统一归入目标分类（逐条复用单条更新链） -->
    <a-modal
      v-model:open="batchCategoryOpen"
      :title="t('knowledge.batchCategorizeTitle')"
      :confirm-loading="batchCategorizing"
      @ok="applyBatchCategory"
      @cancel="batchCategoryOpen = false"
    >
      <p class="modules-hint">{{ t('knowledge.batchSelected', { n: selectedRowKeys.length }) }}</p>
      <a-form-item :label="t('knowledge.itemCategory')">
        <a-select
          v-model:value="batchCategory"
          :options="categoryOptions"
          :placeholder="t('knowledge.categoryPlaceholder')"
        />
      </a-form-item>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive, watch } from 'vue'
import { formatEpochSecondDate, formatEpochSecondText, formatTimestampText, localDayEndIso, localDayStartIso } from '@/utils/displayText'
import { extractApiDetail } from '@/utils/error'
import { useI18n } from 'vue-i18n'
import { useEnumLabel } from '@/composables/useEnumLabel'
import { message, Modal } from 'ant-design-vue'
import type { UploadFile } from 'ant-design-vue'
import {
  getKnowledgeNodes,
  searchKnowledge,
  createKnowledgeNode,
  type KnowledgeCreatePayload,
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
  requestConflictLlmAdvice,
  type ConflictResolution,
  listDeletedKnowledge,
  restoreKnowledgeNode,
  listKnowledgeVersions,
  rollbackKnowledgeRevision,
  listKnowledgeRevisions,
  syncKbConfig,
  previewChunking,
  listIngressTasks,
  getIngressTask,
  cancelIngressTask,
  listKnowledgeChunks,
  updateKnowledgeChunk,
  listKnowledgeChunkRevisions,
  listResolutionReviews,
  resolveResolutionReview,
  runEntityResolution,
} from '@/api/modules/knowledge'
import type { KbConfig, KbCollection, KnowledgeNode, KnowledgeScope, KnowledgeConflict, ConflictTimeContext, DeletedKnowledge, GraphResolutionReview, KnowledgeChunkRow, IngressTask, IngressSpan } from '@/api/modules/knowledge'
import { listKnowledgeCategories } from '@/api/modules/knowledge'
import {
  listMcpSources,
  probeMcpTools as probeMcpToolsApi,
  createMcpSource,
  updateMcpSource,
  pullMcpSource as pullMcpSourceApi,
  deleteMcpSource as deleteMcpSourceApi,
  importKnowledgeFile,
  importKnowledgeFromUrl,
} from '@/api/modules/knowledge'
import { listChunkStrategies, searchCommunityGraph, getOntologyBlockingStats, getOntologyConflictPolicy } from '@/api/modules/ontology'
import { useAuthStore } from '@/stores/auth'
import GlassPanel from '@/components/GlassPanel.vue'
import AnnotationDrawer from '@/modules/collaboration/AnnotationDrawer.vue'
import KnowledgeLineageDrawer from '@/components/KnowledgeLineageDrawer.vue'
import CategoryManagerModal from '@/components/CategoryManagerModal.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAgentPage } from '@/composables/useAgentPage'

interface KnowledgeItem {
  id: string
  knowledge_id?: string
  title: string
  category: string
  content: string
  tags?: string[]
  created_at?: number
  updated_at?: number
  source_created_at?: string
  source_modified_at?: string
  visibility?: 'public' | 'private'
  owner_user_id?: string
  shared_with?: string[]
  submission?: { status?: string } | null
  // P0-2 分块契约：块数 + 检索命中的块级溯源
  chunk_count?: number
  chunk_hits?: { chunk_index: number; content: string; score?: number }[]
}

const { t, te } = useI18n()
const { enumLabel } = useEnumLabel()

const { agentId } = useAgentPage({
  onAgentChange: () => {
    currentPage.value = 1
    clearSelection()
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
// U3：blocking 预读数（候选对/全对比）＋术语级 conflict_policy 声明缓存
const blockingStats = ref<{ full_scan: number; blocking: number; reduction_pct: number } | null>(null)
const conflictPolicies = ref<Record<string, string>>({})
const revisionsOpen = ref(false)
const revisions = ref<{ old: Record<string, unknown>; changed_fields: string[]; updated_at: string; reason?: string }[]>([])
const revisionsEntryId = ref('')
const revisionsEntry = ref<KnowledgeItem | null>(null)
const rollbackPending = ref(-1)
const versions = ref<Array<{ version: number; reason: string; actor: string; time: string; data: { title: string; content: string } }>>([])
const diffOpen = ref<Record<number, boolean>>({})
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

// 分类写权限（用户裁定 2026-11-09）：仅公共库设归属门；私有条目（私人库＋共享
// 给我）已由可见性按用户隔离，可见即可改分类。与后端 entry_for_update 的
// 按字段选门同口径（只写 category 才放行）。
function canCategorize(record: KnowledgeItem): boolean {
  return record.visibility !== 'public' || canManage(record)
}

function onScopeChange() {
  currentPage.value = 1
  clearSelection()
  fetchKnowledge()
}

const categoryOptions = ref<{ label: string; value: string }[]>([])

// 分类注册表（specs/2026-11-07 批 F2）：分类下拉的单源；服务端已按请求身份过滤
const importCategory = ref('')

async function fetchCategories() {
  try {
    const res: any = await listKnowledgeCategories()
    const items: any[] = res?.data ?? res ?? []
    categoryOptions.value = items
      .filter((c) => c.is_active !== false)
      .map((c) => ({ label: c.name, value: c.category_id }))
  } catch {
    categoryOptions.value = []
  }
}

// Modal
const modalVisible = ref(false)
const saving = ref(false)
const editingItem = ref<KnowledgeItem | null>(null)
const form = ref({ title: '', category: '', content: '', tags: [] as string[], author: '', geoLat: undefined as number | undefined, geoLon: undefined as number | undefined })

// A3 元数据过滤（后端 visible/search 已支持；这里只做入口与透传，判权在服务端）。
const filterOpen = ref(false)
const metaFilters = ref<{ author: string; source_type: string; ocr_used?: boolean; page_min?: number; source: string; modifiedRange: [string, string] | undefined }>({ author: '', source_type: '', ocr_used: undefined, page_min: undefined, source: '', modifiedRange: undefined })
const activeFilterCount = computed(() =>
  [metaFilters.value.author, metaFilters.value.source_type, metaFilters.value.source, metaFilters.value.modifiedRange]
    .filter((v) => String(v || '').trim()).length
  + (metaFilters.value.ocr_used !== undefined ? 1 : 0)
  + (metaFilters.value.page_min !== undefined && metaFilters.value.page_min !== null ? 1 : 0))
const applyMetaFilters = () => {
  filterOpen.value = false
  clearSelection()
  void fetchKnowledge()
}
const clearMetaFilters = () => {
  metaFilters.value = { author: '', source_type: '', ocr_used: undefined, page_min: undefined, source: '', modifiedRange: undefined }
  clearSelection()
  void fetchKnowledge()
}

// Import
const importVisible = ref(false)
const importing = ref(false)
const importFiles = ref<UploadFile[]>([])
// 批量导入：文件多选走主拖拽区（accept 让原生对话框置灰非支持类型）+ 整文件夹
// 独立入口；两路共用 beforeImportUpload 按扩展名过滤并计数。accept 单源于此表，防漂移。
const KB_IMPORT_EXTS = [
  'json', 'jsonl', 'csv', 'txt', 'md', 'rst', 'html', 'htm', 'xml',
  'yaml', 'yml', 'toml', 'log', 'rtf', 'odt', 'ods', 'odp', 'docx', 'xlsx', 'pptx', 'pdf',
]
const kbImportAcceptAttr = computed(() => KB_IMPORT_EXTS.map((e) => `.${e}`).join(','))
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

// 分类管理弹窗（admin）：注册/编辑/停用/删除分类注册表，变更后刷新分类下拉
const catMgmtOpen = ref(false)

// 批量分类：多选按分类写权限放行（公共库归属主/admin，私有可见即可，见
// canCategorize）；应用时逐条走既有 updateKnowledgeNode 单更新链（payload 只带
// category，不触正文重抽），聚合成功/失败——不新造平行批量端点。
const selectedRowKeys = ref<string[]>([])
const batchCategoryOpen = ref(false)
const batchCategorizing = ref(false)
const batchCategory = ref<string | undefined>(undefined)

const rowSelection = computed(() => ({
  selectedRowKeys: selectedRowKeys.value,
  preserveSelectedRowKeys: true,
  onChange: (keys: string[]) => { selectedRowKeys.value = keys },
  getCheckboxProps: (record: KnowledgeItem) => ({ disabled: !canCategorize(record) }),
}))

function clearSelection() {
  selectedRowKeys.value = []
}

function onCategoryFilterChange() {
  clearSelection()
  fetchKnowledge()
}

function openBatchCategory() {
  batchCategory.value = undefined
  batchCategoryOpen.value = true
}

async function applyBatchCategory() {
  if (!batchCategory.value) {
    message.error(t('knowledge.batchCategorizeNoCategory'))
    return
  }
  batchCategorizing.value = true
  const category = batchCategory.value
  const ids = [...selectedRowKeys.value]
  let success = 0
  let firstError: unknown = null
  try {
    for (const id of ids) {
      try {
        await updateKnowledgeNode(id, { category }, { agent_id: agentId.value })
        success++
      } catch (err) {
        if (firstError === null) firstError = err
      }
    }
  } finally {
    batchCategorizing.value = false
  }
  batchCategoryOpen.value = false
  const fail = ids.length - success
  if (success > 0) {
    if (fail === 0) message.success(t('knowledge.batchCategorizeSuccess', { n: success }))
    else message.warning(t('knowledge.batchCategorizePartial', { success, fail }))
    clearSelection()
    fetchKnowledge()
  } else {
    // 全败保留选择供重试；detail 原话优先
    message.error(extractApiDetail(firstError) || t('knowledge.batchCategorizeFailed'))
  }
}

// MCP 信息源（B 方案）：外部 MCP server 作为知识库信息源。拉取直接入知识库
// （dedupe/租户全链），token 只登记不回显（列表脱敏）。
const mcpVisible = ref(false)
const mcpLoading = ref(false)
const mcpSaving = ref(false)
const mcpProbing = ref(false)
const mcpSources = ref<any[]>([])
const mcpFormVisible = ref(false)
const editingMcpId = ref('')
const mcpTools = ref<Array<{ name: string; description: string }>>([])
const pullingId = ref('')
const mcpForm = reactive({
  name: '', endpoint: '', auth_token: '', tool_name: '',
  tool_args_json: '{}',
})

const fetchMcpSources = async () => {
  mcpLoading.value = true
  try {
    const res: any = await listMcpSources()
    const data = res?.data ?? res
    mcpSources.value = data?.items ?? []
  } catch (e: any) {
    message.error(extractApiDetail(e) || e?.message || t('common.error'))
  } finally {
    mcpLoading.value = false
  }
}

const openMcpForm = () => {
  editingMcpId.value = ''
  mcpForm.name = ''
  mcpForm.endpoint = ''
  mcpForm.auth_token = ''
  mcpForm.tool_name = ''
  mcpForm.tool_args_json = '{}'
  mcpTools.value = []
  mcpFormVisible.value = true
}

const probeMcpTools = async () => {
  if (!mcpForm.endpoint.trim()) {
    message.warning(t('knowledge.mcpEndpointRequired'))
    return
  }
  mcpProbing.value = true
  try {
    const res: any = await probeMcpToolsApi({
      endpoint: mcpForm.endpoint,
      auth_token: mcpForm.auth_token,
    })
    mcpTools.value = (res?.data ?? res)?.tools ?? []
    if (!mcpTools.value.length) message.info(t('knowledge.mcpToolsEmpty'))
  } catch (e: any) {
    message.error(extractApiDetail(e) || e?.message || t('common.error'))
  } finally {
    mcpProbing.value = false
  }
}

const saveMcpSource = async () => {
  if (!mcpForm.name.trim() || !mcpForm.endpoint.trim()) {
    message.warning(t('knowledge.mcpNameRequired'))
    return
  }
  let toolArgs: Record<string, unknown> = {}
  try {
    toolArgs = JSON.parse(mcpForm.tool_args_json || '{}')
  } catch {
    message.warning(t('knowledge.mcpArgsInvalid'))
    return
  }
  mcpSaving.value = true
  try {
    const payload = {
      name: mcpForm.name, endpoint: mcpForm.endpoint,
      auth_token: mcpForm.auth_token, tool_name: mcpForm.tool_name,
      tool_args: toolArgs, agent_id: agentId.value,
    }
    if (editingMcpId.value) {
      await updateMcpSource(editingMcpId.value, payload)
      message.success(t('knowledge.mcpUpdated'))
    } else {
      await createMcpSource(payload)
      message.success(t('knowledge.mcpCreated'))
    }
    mcpFormVisible.value = false
    await fetchMcpSources()
  } catch (e: any) {
    message.error(extractApiDetail(e) || e?.message || t('common.error'))
  } finally {
    mcpSaving.value = false
  }
}

const pullMcpSource = async (item: any) => {
  pullingId.value = item.source_id
  try {
    const res: any = await pullMcpSourceApi(item.source_id)
    const data = res?.data ?? res
    if (data?.duplicate) {
      message.info(t('knowledge.duplicateMerged'))
    } else {
      message.success(t('knowledge.mcpPulled'))
    }
    await fetchMcpSources()
    await fetchKnowledge()
  } catch (e: any) {
    message.error(extractApiDetail(e) || e?.message || t('common.error'))
  } finally {
    pullingId.value = ''
  }
}

const deleteMcpSource = async (item: any) => {
  try {
    await deleteMcpSourceApi(item.source_id)
    message.success(t('knowledge.mcpDeleted'))
    await fetchMcpSources()
  } catch (e: any) {
    message.error(extractApiDetail(e) || e?.message || t('common.error'))
  }
}
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
  /** P1#12 飞书定时同步间隔（分钟，0=不定时） */
  sync_interval_minutes: number
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
  sync_interval_minutes: 0,
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
  { title: '', key: 'actions', width: 200 },
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
    sync_interval_minutes: 0,
  }
}

// ── P1#12（WeKnora）：飞书同步 + 块级编辑 ──────────────────────────
const syncingConfigId = ref<string | null>(null)

// 摄取任务 span 时间线 + stop-parse
const ingressVisible = ref(false)
const ingressLoading = ref(false)
const ingressTasks = ref<IngressTask[]>([])
const ingressStats = ref<Record<string, number>>({})
const spanMap = ref<Record<string, IngressSpan[]>>({})
const spanLoading = ref<Record<string, boolean>>({})

const ingressColumns = [
  { title: 'task', key: 'task_id', dataIndex: 'task_id', ellipsis: true, width: 150 },
  { title: t('knowledge.itemTitle'), key: 'filename', dataIndex: 'filename', ellipsis: true },
  { title: t('knowledge.configSource'), key: 'source', dataIndex: 'source', width: 90 },
  { title: t('common.status'), key: 'status', dataIndex: 'status', width: 90 },
  { title: t('common.createdAt'), key: 'created_at', dataIndex: 'created_at', width: 150 },
  { title: '', key: 'actions', width: 70 },
]

function ingressStatusLabel(status: string): string {
  const key = `knowledge.ingressStatus${status.charAt(0).toUpperCase()}${status.slice(1)}`
  const label = t(key)
  return label === key ? status : label
}
function ingressStatusColor(status: string): string {
  return (
    { pending: 'default', processing: 'processing', running: 'processing',
      done: 'success', failed: 'error', dead: 'error', cancelled: 'warning' } as Record<string, string>
  )[status] || 'default'
}
function ingressStatColor(k: string): string { return ingressStatusColor(k) }
function ingressStageLabel(stage: string): string {
  const key = `knowledge.ingressStage${stage.charAt(0).toUpperCase()}${stage.slice(1)}`
  const label = t(key)
  return label === key ? stage : label
}

async function refreshIngress() {
  ingressLoading.value = true
  try {
    const res: any = await listIngressTasks()
    ingressTasks.value = res?.data?.tasks || []
    ingressStats.value = res?.data?.stats || {}
  } catch (e: any) {
    message.error(extractApiDetail(e) || e?.message || String(e))
  } finally {
    ingressLoading.value = false
  }
}

function openIngress() {
  ingressVisible.value = true
  void refreshIngress()
}

async function handleIngressExpand(record: IngressTask) {
  if (spanMap.value[record.task_id]) return
  spanLoading.value = { ...spanLoading.value, [record.task_id]: true }
  try {
    const res: any = await getIngressTask(record.task_id)
    spanMap.value = { ...spanMap.value, [record.task_id]: res?.data?.spans || [] }
  } catch (e: any) {
    message.error(extractApiDetail(e) || e?.message || String(e))
  } finally {
    const next = { ...spanLoading.value }
    delete next[record.task_id]
    spanLoading.value = next
  }
}

async function handleCancelIngress(record: IngressTask) {
  try {
    await cancelIngressTask(record.task_id)
    message.success(t('knowledge.ingressCancelled'))
    await refreshIngress()
  } catch (e: any) {
    message.error(extractApiDetail(e) || e?.message || String(e))
  }
}

const previewLoading = ref(false)
const chunkStrategies = ref<Array<{ strategy_id: string; kind: string; params: Record<string, unknown> }>>([])
const chunkStrategyId = ref<string>('')
const communityMode = ref<string>('')

const chunkStrategyOptions = computed(() =>
  chunkStrategies.value.map((s) => ({
    value: s.strategy_id,
    label: `${s.strategy_id} (${s.kind})`,
  })))

async function loadChunkStrategies() {
  try {
    const res = await listChunkStrategies()
    chunkStrategies.value = res.data ?? []
  } catch {
    chunkStrategies.value = []  // 名册失败＝选择器缺席（缺省零漂移，诚实回退）
  }
}

onMounted(loadChunkStrategies)
const previewResult = ref<{
  children: Array<{ index?: number; context_header?: string; content?: string }>
  parents: Array<{ index?: number }>
  max_chars: number
} | null>(null)

async function handlePreviewChunking() {
  const content = String(form.value?.content || '')
  if (!content.trim()) {
    message.warning(t('knowledge.previewEmpty'))
    return
  }
  previewLoading.value = true
  try {
    const strategy = chunkStrategies.value.find(
      (s) => s.strategy_id === chunkStrategyId.value)
    const res: any = await previewChunking({
      content,
      strategy: strategy ? { kind: strategy.kind, params: strategy.params } : null,
    })
    previewResult.value = res?.data || null
  } catch (e: any) {
    message.error(extractApiDetail(e) || e?.message || String(e))
  } finally {
    previewLoading.value = false
  }
}

async function handleSyncConfig(record: KbConfig) {
  syncingConfigId.value = record.id
  try {
    const res: any = await syncKbConfig(record.id)
    const st = res?.data || {}
    message.info(
      t('knowledge.syncDone', {
        upserted: st.upserted ?? 0,
        deleted: st.deleted ?? 0,
        failed: st.failed ?? 0,
      }),
    )
  } catch (e: any) {
    message.error(extractApiDetail(e) || e?.message || String(e))
  } finally {
    syncingConfigId.value = null
  }
}

const chunksVisible = ref(false)
const chunksLoading = ref(false)
const chunkRows = ref<KnowledgeChunkRow[]>([])
const chunkKid = ref('')
const savingChunkIndex = ref<number | null>(null)
const chunkHistory = ref<Array<{ content: string; at: string; by: string }>>([])

async function openChunks(record: KnowledgeNode) {
  chunkKid.value = record.knowledge_id || record.id || ''
  chunkHistory.value = []
  chunksVisible.value = true
  chunksLoading.value = true
  try {
    const res: any = await listKnowledgeChunks(chunkKid.value)
    chunkRows.value = (res?.data || []).map((c: any) => ({ ...c }))
  } catch (e: any) {
    message.error(extractApiDetail(e) || e?.message || String(e))
    chunkRows.value = []
  } finally {
    chunksLoading.value = false
  }
}

async function handleSaveChunk(ch: KnowledgeChunkRow) {
  savingChunkIndex.value = ch.index
  try {
    const res: any = await updateKnowledgeChunk(chunkKid.value, ch.index, {
      content: ch.content,
      expected_revision: ch.revision ?? 0,
    })
    ch.revision = res?.data?.revision ?? ch.revision
    message.success(t('knowledge.chunkSaved'))
    const list: any = await listKnowledgeChunks(chunkKid.value)
    chunkRows.value = (list?.data || []).map((c: any) => ({ ...c }))
  } catch (e: any) {
    if (e?.response?.status === 409) {
      message.warning(t('knowledge.chunkConflict'))
      await openChunks({ knowledge_id: chunkKid.value } as KnowledgeNode)
    } else {
      message.error(extractApiDetail(e) || e?.message || String(e))
    }
  } finally {
    savingChunkIndex.value = null
  }
}

async function showChunkHistory(index: number) {
  try {
    const res: any = await listKnowledgeChunkRevisions(chunkKid.value, index)
    chunkHistory.value = res?.data || []
  } catch (e: any) {
    message.error(extractApiDetail(e) || e?.message || String(e))
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
  { title: t('knowledge.colModified'), key: 'source_modified_at', dataIndex: 'source_modified_at', width: 170 },
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



function onTableChange(pag: any) {
  currentPage.value = pag.current
  pageSize.value = pag.pageSize
  fetchKnowledge()
}

async function handleSearch() {
  clearSelection()
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
      const f = metaFilters.value
      const searchFilters: Record<string, any> = {}
      if (f.author.trim()) searchFilters.author = f.author.trim()
      if (f.modifiedRange?.[0]) searchFilters.source_modified_after = localDayStartIso(f.modifiedRange[0])
      if (f.modifiedRange?.[1]) searchFilters.source_modified_before = localDayEndIso(f.modifiedRange[1])
      if (f.source_type.trim()) searchFilters.source_type = f.source_type.trim()
      if (f.ocr_used !== undefined && f.ocr_used !== null) searchFilters.ocr_used = f.ocr_used
      if (f.page_min !== undefined && f.page_min !== null) searchFilters.page_min = f.page_min
      if (f.source.trim()) searchFilters.source = f.source.trim()
      const res: any = await searchKnowledge(searchQuery.value.trim(), {
        agent_id: agentId.value,
        scope: activeScope.value,
        limit: pageSize.value,
        ...searchFilters,
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

    // 分类下拉单源＝分类注册表（specs/2026-11-07 批 F2）：服务端按身份过滤，
    // 受限部门只见白名单内分类；不再从当前页结果反推（反推会漏掉本页没出现的分类）
  } catch (err) {
    message.error(extractApiDetail(err) || t('knowledge.loadError'))
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
  } catch (err) {
    message.error(extractApiDetail(err) || t('knowledge.searchError'))
  } finally {
    loading.value = false
  }
}

function openCreateModal() {
  editingItem.value = null
  form.value = { title: '', category: '', content: '', tags: [], author: '', geoLat: undefined, geoLon: undefined }
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
    message.error(extractApiDetail(err) || t('knowledge.shareError'))
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
        message.error(extractApiDetail(err) || t('knowledge.submitError'))
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
  } catch (err) {
    message.error(extractApiDetail(err) || t('knowledge.loadSubmissionsError'))
  }
}

async function handleReview(item: KnowledgeItem, approve: boolean) {
  try {
    await reviewKnowledgePublic(item.id, approve)
    message.success(t('knowledge.reviewSuccess'))
    await fetchSubmissions()
    fetchKnowledge()
  } catch (err: any) {
    message.error(extractApiDetail(err) || t('knowledge.reviewError'))
  }
}

// ── P0-3 同值冲突 / P0-2 墓碑 + revisions / P1-1 消解 ──────────

async function fetchConflicts() {
  if (!isAdmin.value) return
  try {
    const res: any = await listKnowledgeConflicts('pending', 'all')
    const data = res?.data ?? res
    conflicts.value = Array.isArray(data) ? data : data?.items ?? []
  } catch {
    conflicts.value = []
  }
  await loadConflictPolicies()
}

/** U3：事实轴冲突的术语级 conflict_policy 声明读数（逐 term 拉，失败留空不冒充）。 */
async function loadConflictPolicies() {
  const termIds = [...new Set(conflicts.value
    .filter((c): c is Extract<typeof c, { axis: 'fact' }> => c.axis === 'fact' && !!c.predicate_term_id)
    .map((c) => c.predicate_term_id))]
  await Promise.all(termIds.map(async (termId) => {
    if (conflictPolicies.value[termId]) return
    try {
      const res: any = await getOntologyConflictPolicy(termId)
      conflictPolicies.value[termId] = res?.data?.conflict_policy ?? ''
    } catch {
      conflictPolicies.value[termId] = ''
    }
  }))
}

/** 事实侧的胜方由人指明：没有"自动裁决"按钮，也没有默认胜方。 */
const conflictWinner = ref<Record<string, string>>({})

// 血缘抽屉：一次只开一条事实；从推导跳点前提时替换当前事实（不叠抽屉）
const lineageOpen = ref(false)
const lineageFactId = ref('')

function openLineage(factId: string) {
  if (!factId) return
  lineageFactId.value = factId
  lineageOpen.value = true
}

function conflictLineageTarget(item: KnowledgeConflict): string {
  if (item.axis !== 'fact') return ''
  return conflictWinner.value[item.conflict_id] || item.member_fact_ids[0] || ''
}

/** 建议策略的枚举值是蛇形，而 i18n 守卫要求键段驼峰——中间这一步映射就是翻译表本身。 */
const CONFLICT_POLICY_KEYS: Record<string, string> = {
  most_recent: 'mostRecent',
  highest_confidence: 'highestConfidence',
  credibility_weighted: 'credibilityWeighted',
  keep_both: 'keepBoth',
  manual: 'manual',
}

function conflictPolicyLabel(name?: string): string {
  if (!name) return ''
  const key = `conflictPolicyKind.${CONFLICT_POLICY_KEYS[name] ?? name}`
  return te(key) ? t(key) : name
}

function conflictTitle(item: KnowledgeConflict): string {
  return item.axis === 'entry' ? item.title : `${item.subject_label || item.subject_key} · ${item.predicate_term_id}`
}

function conflictDescription(item: KnowledgeConflict): string {
  if (item.axis === 'entry') {
    return t('knowledge.conflictSimilarity', { score: (item.similarity * 100).toFixed(0) })
  }
  return t('knowledge.conflictMembers', { members: item.members_summary.join(' ｜ ') })
}

function conflictNewerSideLabel(ctx: ConflictTimeContext): string {
  if (ctx.newer_side === 'new') return t('knowledge.conflictNewerNew')
  if (ctx.newer_side === 'old') return t('knowledge.conflictNewerOld')
  return t('knowledge.conflictNewerUnknown')
}

function conflictTimeReadout(ctx: ConflictTimeContext): string {
  const sourceBasis = ctx.basis === 'source_modified_at'
  const basis = sourceBasis ? t('knowledge.conflictBasisSource') : t('knowledge.conflictBasisIngested')
  const oldTime = sourceBasis
    ? formatTimestampText(ctx.old_source_modified_at)
    : formatEpochSecondText(ctx.old_ingested_at)
  const newTime = sourceBasis
    ? formatTimestampText(ctx.new_source_modified_at)
    : formatEpochSecondText(ctx.new_ingested_at)
  return t('knowledge.conflictTimeReadout', {
    basis,
    old: oldTime || '—',
    new: newTime || '—',
  })
}

function conflictMemberOptions(item: KnowledgeConflict) {
  if (item.axis !== 'fact') return []
  return item.member_fact_ids.map((id, i) => ({
    value: id,
    label: item.members_summary[i] ?? id,
  }))
}

async function handleResolveConflict(item: KnowledgeConflict, resolution: ConflictResolution) {
  try {
    await resolveKnowledgeConflict(
      item.conflict_id,
      resolution,
      resolution === 'supersede_old' && item.axis === 'fact'
        ? conflictWinner.value[item.conflict_id]
        : undefined,
    )
    message.success(t('knowledge.conflictResolved'))
    await fetchConflicts()
    fetchKnowledge()
    if (isAdmin.value) fetchTombstones()
  } catch (err: any) {
    message.error(extractApiDetail(err) || t('knowledge.reviewError'))
  }
}

/** C2：LLM 参考意见（只读辅助）——按 conflict_id 缓存展示，不落账不改状态 */
const conflictLlmAdvice = ref<Record<string, string>>({})
const conflictLlmAdviceLoading = ref<Record<string, boolean>>({})

async function handleRequestLlmAdvice(item: KnowledgeConflict) {
  const cid = item.conflict_id
  conflictLlmAdviceLoading.value = { ...conflictLlmAdviceLoading.value, [cid]: true }
  try {
    const res: any = await requestConflictLlmAdvice(cid)
    const data = res?.data?.data ?? res?.data
    if (!data) throw new Error('empty advice')
    conflictLlmAdvice.value = {
      ...conflictLlmAdvice.value,
      [cid]: data.contradicts
        ? `${data.reason}（${t('knowledge.conflictLlmAdviceWinner')}: ${data.winner_fact_id || t('knowledge.conflictLlmAdviceNoWinner')}）`
        : t('knowledge.conflictLlmAdviceNoConflict'),
    }
  } catch (err: any) {
    message.error(extractApiDetail(err) || t('common.error'))
  } finally {
    conflictLlmAdviceLoading.value = { ...conflictLlmAdviceLoading.value, [cid]: false }
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
    message.error(extractApiDetail(err) || t('knowledge.tombstoneRestoreError'))
  }
}

async function openRevisions(item: KnowledgeItem) {
  try {
    const res: any = await listKnowledgeRevisions(item.id)
    revisions.value = Array.isArray(res) ? res : (res?.data ?? [])
    try {
      const vres: any = await listKnowledgeVersions(item.id)
      versions.value = vres?.data ?? []
    } catch {
      versions.value = []
    }
    revisionsEntryId.value = item.id
    revisionsEntry.value = item
    diffOpen.value = {}
    revisionsOpen.value = true
  } catch (err) {
    message.error(extractApiDetail(err) || t('knowledge.revisionsError'))
  }
}

async function handleRevisionRollback(idx: number) {
  if (!revisionsEntryId.value) return
  rollbackPending.value = idx
  try {
    await rollbackKnowledgeRevision(revisionsEntryId.value, idx)
    message.success(t('knowledge.revisionsRollbackDone'))
    const res: any = await listKnowledgeRevisions(revisionsEntryId.value)
    revisions.value = Array.isArray(res) ? res : (res?.data ?? [])
    fetchKnowledge()
  } catch (err) {
    message.error(extractApiDetail(err) || t('knowledge.revisionsRollbackError'))
  } finally {
    rollbackPending.value = -1
  }
}

/** 较上一版本的新值：下一较新修订的 old 即本修订后的值；最新一条取条目现值。 */
function revisionNewValue(idx: number, field: string): string {
  if (idx > 0) {
    const newer = revisions.value[idx - 1]
    if (newer?.old && field in newer.old) return String(newer.old[field] ?? '')
  }
  const entry = revisionsEntry.value as unknown as Record<string, unknown> | null
  return String(entry?.[field] ?? '')
}

function versionReasonLabel(reason: string): string {
  if (reason === 'rollback') return t('knowledge.revisionReasonRollback')
  if (reason === 'source_update_reingest') return t('knowledge.revisionReasonReingest')
  return t('knowledge.versionReasonUpdate')
}

function toggleRevisionDiff(idx: number) {
  diffOpen.value = { ...diffOpen.value, [idx]: !diffOpen.value[idx] }
}

async function fetchResolutionReviews() {
  if (!isAdmin.value) return
  try {
    const res: any = await listResolutionReviews(agentId.value)
    resolutionReviews.value = res?.data?.reviews ?? []
  } catch {
    resolutionReviews.value = []
  }
  // U3：blocking 预读数随队列刷新（失败留 null 不冒充零剪枝）
  try {
    const res: any = await getOntologyBlockingStats()
    blockingStats.value = res?.data ?? null
  } catch {
    blockingStats.value = null
  }
}

async function handleRunResolution() {
  resolutionRunning.value = true
  try {
    await runEntityResolution(agentId.value)
    message.success(t('knowledge.resolutionRan'))
    await fetchResolutionReviews()
  } catch (err: any) {
    message.error(extractApiDetail(err) || t('knowledge.resolutionRunError'))
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
    message.error(extractApiDetail(err) || t('knowledge.resolutionRunError'))
  }
}

function editItem(item: KnowledgeItem) {
  editingItem.value = item
  form.value = {
    title: item.title,
    category: item.category,
    content: item.content,
    tags: item.tags ?? [],
    author: (item as any).author ?? '',
    geoLat: (item as any).geo?.lat,
    geoLon: (item as any).geo?.lon,
  }
  modalVisible.value = true
}

async function saveItem() {
  saving.value = true
  try {
    if (editingItem.value) {
      // 只发变更字段：未改动的正文不再进 payload（后端 exclude_unset 语义），
      // 也让「只改分类」的编辑走与批量一致的按字段选门口径。
      const before = editingItem.value
      const changed: Record<string, unknown> = {}
      if (form.value.title !== before.title) changed.title = form.value.title
      if (form.value.category !== before.category) changed.category = form.value.category
      if (form.value.content !== before.content) changed.content = form.value.content
      if (JSON.stringify(form.value.tags ?? []) !== JSON.stringify(before.tags ?? [])) {
        changed.tags = form.value.tags
      }
      if (!Object.keys(changed).length) {
        modalVisible.value = false
        return
      }
      await updateKnowledgeNode(before.id, changed, { agent_id: agentId.value })
      message.success(t('knowledge.updateSuccess'))
    } else {
      const raw: Record<string, any> = { ...form.value, agent_id: agentId.value }
      const geo = (raw.geoLat !== undefined && raw.geoLon !== undefined
        && raw.geoLat !== null && raw.geoLon !== null)
        ? { lat: raw.geoLat, lon: raw.geoLon } : undefined
      delete raw.geoLat
      delete raw.geoLon
      const payload = Object.assign({} as KnowledgeCreatePayload, raw)
      if (geo) payload.geo = geo
      const res: any = await createKnowledgeNode(payload)
      const created = res?.data ?? res
      if (created?.duplicate) {
        // A1：同文命中既有条目，来源已并入 sources[]——如实告知，不冒充新建成功。
        message.info(t('knowledge.duplicateMerged'))
      } else {
        message.success(t('knowledge.createSuccess'))
      }
    }
    modalVisible.value = false
    fetchKnowledge()
  } catch (err) {
    message.error(extractApiDetail(err) || t('knowledge.saveError'))
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
        selectedRowKeys.value = selectedRowKeys.value.filter((k) => k !== item.id)
        message.success(t('knowledge.deleteSuccess'))
      } catch (err) {
        message.error(extractApiDetail(err) || t('knowledge.deleteError'))
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
        const res: any = await importKnowledgeFile(formData, {
          agent_id: agentId.value,
          ...(importCategory.value ? { category: importCategory.value } : {}),
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
    await importKnowledgeFromUrl({
      agent_id: agentId.value,
      url,
      ...(importCategory.value ? { category: importCategory.value } : {}),
    })
    message.success(t('knowledge.importSuccess'))
    importUrlValue.value = ''
    fetchKnowledge()
  } catch (err: any) {
    message.error(extractApiDetail(err) || t('knowledge.importError'))
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
  } catch (err) {
    message.error(extractApiDetail(err) || t('knowledge.importError'))
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
    // P1#12：飞书定时同步间隔（分钟）>0 才写入 settings，供后台循环调度
    if (f.source_type === 'feishu' && f.sync_interval_minutes > 0) {
      settings.sync_interval_minutes = f.sync_interval_minutes
    }

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
  } catch (err) {
    message.error(extractApiDetail(err) || t('knowledge.importError'))
  } finally {
    configSaving.value = false
  }
}

async function handleDeleteConfig(record: KbConfig) {
  try {
    await deleteKbConfig(record.id)
    message.success(t('knowledge.importSuccess'))
    await fetchKbConfigs()
  } catch (err) {
    message.error(extractApiDetail(err) || t('knowledge.importError'))
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
  } catch (err) {
    message.error(extractApiDetail(err) || t('knowledge.importError'))
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
  } catch (err) {
    message.error(extractApiDetail(err) || t('knowledge.importError'))
  } finally {
    collectionSaving.value = false
  }
}

async function handleDeleteCollection(record: KbCollection) {
  try {
    await deleteKbCollection(record.id)
    message.success(t('knowledge.importSuccess'))
    await fetchKbCollections()
  } catch (err) {
    message.error(extractApiDetail(err) || t('knowledge.importError'))
  }
}

onMounted(() => {
  fetchKnowledge()
  fetchCategories()
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
.kb-blocking-readout {
  font-size: 12px;
  color: var(--nr-text-secondary);
  font-family: var(--nr-font-mono);
  margin: 6px 0;
}

.knowledge-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.kb-batch-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  margin-bottom: 12px;
  border: 1px solid var(--nr-glass-border);
  border-radius: var(--nr-radius-md);
  background: var(--nr-glass-bg);
}

.kb-batch-count {
  font-size: 13px;
  color: var(--nr-text-secondary);
}

/* 远程配置创建表单：名称 + 类型 一行 */
.kb-config-create {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}

.kb-preview-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.kb-preview-list {
  margin-top: 4px;
  max-height: 160px;
  overflow: auto;
  font-size: 12px;
  opacity: 0.75;
}

.kb-preview-item {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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

.rev-diff {
  margin: 6px 0 0;
  padding: 8px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
  border-radius: 6px;
  background: var(--nr-bg-inset, rgba(0, 0, 0, 0.15));
}

.rev-diff-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 4px 0;
  font-size: 12px;
}

.rev-new {
  color: var(--nr-success, #10b981);
  word-break: break-all;
}

.rev-section {
  margin: 4px 0 8px;
  font-size: 13px;
  font-weight: 600;
}

.version-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
}

.rev-actor {
  color: var(--nr-text-secondary, rgba(128, 128, 128, 0.7));
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

/* A3 过滤 popover：纵向小表单 */
.kb-filter-form {
  display: flex;
  flex-direction: column;
  gap: var(--nr-space-sm, 8px);
  min-width: 220px;
}

.kb-filter-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--nr-space-sm, 8px);
}

/* A6 创建表单坐标行 */
.kb-geo-row {
  display: flex;
  gap: var(--nr-space-sm, 8px);
}

/* A1 展开行：来源链与坐标 */
.kb-meta-detail {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.kb-meta-line {
  display: flex;
  align-items: center;
  gap: var(--nr-space-sm, 8px);
  flex-wrap: wrap;
}

.kb-meta-name {
  min-width: 72px;
  font-weight: 600;
  color: var(--nr-text-primary);
}

.kb-src-tag {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kb-mcp-toolbar {
  display: flex;
  justify-content: space-between;
  margin-bottom: var(--nr-space-sm, 8px);
}

.kb-mcp-form {
  display: flex;
  flex-direction: column;
  gap: var(--nr-space-sm, 8px);
  padding: var(--nr-space-sm, 8px);
  margin-bottom: var(--nr-space-sm, 8px);
  border: 1px solid var(--nr-glass-border);
  border-radius: var(--nr-radius-md, 12px);
  background: var(--nr-glass-bg);
}

.kb-mcp-row {
  display: flex;
  align-items: center;
  gap: var(--nr-space-sm, 8px);
}

.kb-mcp-tools-hint {
  opacity: 0.7;
  font-size: 12px;
}

.kb-mcp-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--nr-space-sm, 8px);
  width: 100%;
}

.kb-mcp-item-main {
  display: flex;
  align-items: center;
  gap: var(--nr-space-sm, 8px);
  overflow: hidden;
}

.kb-mcp-name {
  font-weight: 600;
  color: var(--nr-text-primary);
}

.kb-mcp-endpoint {
  color: var(--nr-text-secondary);
  font-size: 12px;
  font-family: monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-mcp-item-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: none;
}

.kb-src-empty {
  color: var(--nr-text-secondary);
  font-size: 12px;
}
</style>
