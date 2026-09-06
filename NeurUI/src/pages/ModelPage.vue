<template>
  <div class="nr-model-page">
    <!-- 非管理员:个人配置范围提示 -->
    <div v-if="!isAdmin" class="nr-scope-hint">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
      {{ t('model.personalScopeHint') }}
    </div>
    <!-- ===================== Header: Default LLM ===================== -->
    <GlassCard variant="default" padding="16px 20px">
      <div class="nr-header-row">
        <div class="nr-header-label">{{ t('model.defaultLLM') }}</div>
        <div class="nr-header-controls">
          <a-select
            v-model:value="defaultConfig.provider_id"
            :placeholder="t('model.defaultProvider')"
            style="width: 200px"
            @change="onDefaultProviderChange"
          >
            <a-select-option v-for="p in providersWithModels" :key="p.id" :value="p.id">
              {{ p.name }}
            </a-select-option>
          </a-select>
          <a-select
            v-model:value="defaultConfig.model_id"
            :placeholder="t('model.defaultModel')"
            style="width: 260px"
          >
            <a-select-option v-for="m in defaultModelOptions" :key="m.id" :value="m.id">
              <div class="nr-model-option">
                <span>{{ m.name }}</span>
                <span v-if="m.id !== m.name" class="nr-model-subtitle">{{ m.id }}</span>
                <span v-if="m.is_active" class="nr-model-active-tag">{{ t('model.active') }}</span>
              </div>
            </a-select-option>
          </a-select>
          <GlassButton variant="primary" size="sm" :loading="savingDefault" @click="saveDefaultLLM">
            {{ t('model.save') }}
          </GlassButton>
        </div>
      </div>
    </GlassCard>

    <!-- ===================== Providers Section ===================== -->
    <div class="nr-providers-section">
      <!-- Toolbar -->
      <div class="nr-toolbar">
        <div class="nr-search-box">
          <span class="nr-search-icon">&#x1F50D;</span>
          <input
            v-model="providerSearch"
            :placeholder="t('model.searchProviders')"
            class="nr-search-input"
            autocomplete="off"
          />
        </div>
        <div class="nr-toolbar-right">
          <GlassButton variant="ghost" size="sm" @click="fetchProviders" :title="t('model.refreshProviders')">
            &#x1F504;
          </GlassButton>
          <GlassButton variant="primary" size="sm" @click="showAddProvider = true">
            + {{ t('model.addProvider') }}
          </GlassButton>
        </div>
      </div>

      <div v-if="loading" class="nr-loading">
        <a-spin />
      </div>
      <template v-else>
        <a-spin :spinning="loadingModels">
        <!-- Grid of provider cards -->
        <div v-if="filteredProviders.length > 0" class="nr-providers-grid">
          <GlassCard
            v-for="p in filteredProviders"
            :key="p.id"
            variant="default"
            padding="0"
          >
            <div class="nr-pv-card" :class="'st-' + p.status">
              <!-- Icon + Name + Badge -->
              <div class="nr-pv-head">
                <div class="nr-pv-icon" :style="{ background: p.color }">
                  <img v-if="p.iconSrc" :src="p.iconSrc" :alt="p.name" class="nr-pv-icon-img" />
                  <span v-else>{{ p.icon }}</span>
                </div>
                <div class="nr-pv-title">
                  <span class="nr-pv-name">{{ p.name }}</span>
                  <a-tag :color="p.category === 'local' ? 'purple' : p.category === 'free' ? 'green' : 'blue'" size="small">
                    {{ p.category === 'local' ? t('model.local') : p.category === 'free' ? t('model.free') : p.type === 'builtin' ? t('model.builtin') : t('model.custom') }}
                  </a-tag>
                </div>
              </div>

              <!-- Status -->
              <div class="nr-pv-status">
                <span class="nr-pv-dot" :class="p.status" />
                <span :class="'nr-pv-status-text st-' + p.status">{{ p.statusLabel }}</span>
              </div>

              <!-- Details -->
              <div class="nr-pv-body">
                <div class="nr-pv-row">
                  <span class="nr-pv-label">Base URL</span>
                  <span class="nr-pv-val mono">{{ p.base_url || '—' }}</span>
                </div>
                <div class="nr-pv-row">
                  <span class="nr-pv-label">API Key</span>
                  <template v-if="p.api_key_configured">
                    <span class="nr-pv-val mono">{{ revealKey[p.id] ? (p.api_key || '') : maskApiKey(p.api_key) }}</span>
                    <button class="nr-icon-btn" @click="revealKey[p.id] = !revealKey[p.id]" :title="revealKey[p.id] ? 'Hide' : 'Show'">
                      {{ revealKey[p.id] ? '🙈' : '👁' }}
                    </button>
                    <button class="nr-icon-btn nr-save-sm" @click="saveProviderKey(p)" :title="t('model.save')">✓</button>
                  </template>
                  <template v-else-if="p.status === 'not_configured' || p.status === 'not_ready'">
                    <div class="nr-inline-key">
                      <input v-model="inlineApiKeys[p.id]" :type="revealKey[p.id] ? 'text' : 'password'" class="nr-inline-key-input" placeholder="sk-..." />
                      <button class="nr-icon-btn tiny" @click="revealKey[p.id] = !revealKey[p.id]">{{ revealKey[p.id] ? '🙈' : '👁' }}</button>
                      <button class="nr-inline-key-save" @click="saveInlineKey(p)">{{ t('model.save') }}</button>
                    </div>
                  </template>
                  <span v-else class="nr-pv-val muted">{{ t('model.noApiKey') }}</span>
                </div>
                <div class="nr-pv-row">
                  <span class="nr-pv-label">{{ t('model.models') }}</span>
                  <span class="nr-pv-val">{{ p.model_count > 0 ? t('model.modelCount', { n: p.model_count }) : t('model.noModels') }}</span>
                </div>
              </div>

              <!-- Actions -->
              <div class="nr-pv-actions">
                <button class="nr-action-btn primary" @click="openModelManagement(p)">{{ t('model.models') }}</button>
                <button class="nr-action-btn" @click="openConfigure(p)">{{ t('model.settings') }}</button>
                <a-popconfirm v-if="p.type !== 'builtin'" :title="t('common.confirm') + '?'" @confirm="deleteProvider(p)">
                  <button class="nr-action-btn danger">{{ t('model.delete') }}</button>
                </a-popconfirm>
              </div>
            </div>
          </GlassCard>
        </div>

        <div v-else class="nr-empty">
          <span class="nr-empty-icon">📦</span>
          <p>{{ t('model.noProviders') }}</p>
        </div>
        </a-spin>
      </template>
    </div>

    <!-- ===================== Modal: Add Custom Provider ===================== -->
    <Teleport to="body">
      <div v-if="showAddProvider" class="nr-overlay" @click.self="showAddProvider = false">
        <div class="nr-modal" style="width: 500px">
          <div class="nr-modal-head">
            <span>{{ t('model.addCustomProvider') }}</span>
            <button class="nr-close" @click="showAddProvider = false">&times;</button>
          </div>
          <div class="nr-modal-body">
            <div class="nr-field">
              <label>{{ t('model.displayName') }} <span class="req">*</span></label>
              <input v-model="addForm.name" class="nr-input" placeholder="OpenAI, Google Gemini, My Provider" autocomplete="off" />
            </div>
            <div class="nr-field">
              <label>{{ t('model.providerType') }} <span class="req">*</span></label>
              <select v-model="addForm.provider_type" class="nr-select">
                <option value="openai">{{ t('model.typeOpenAI') }}</option>
                <option value="anthropic">{{ t('model.typeAnthropic') }}</option>
                <option value="gemini">{{ t('model.typeGemini') }}</option>
                <option value="ollama">{{ t('model.typeOllama') }}</option>
                <option value="openrouter">{{ t('model.typeOpenRouter') }}</option>
              </select>
            </div>
            <div class="nr-field">
              <label>{{ t('model.defaultBaseUrl') }}</label>
              <input v-model="addForm.base_url" class="nr-input" placeholder="https://api.example.com/v1" />
            </div>
            <div class="nr-field">
              <label>{{ t('model.apiKey') }}</label>
              <input v-model="addForm.api_key" type="password" class="nr-input" :placeholder="t('model.apiKeyOptional')" />
            </div>
          </div>
          <div class="nr-modal-foot">
            <GlassButton variant="ghost" size="md" @click="showAddProvider = false">{{ t('common.cancel') }}</GlassButton>
            <GlassButton variant="primary" size="md" :loading="savingProvider" @click="createProvider">{{ t('model.create') }}</GlassButton>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ===================== Modal: Configure Provider ===================== -->
    <Teleport to="body">
      <div v-if="showConfigure" class="nr-overlay" @click.self="showConfigure = false">
        <div class="nr-modal" style="width: 560px">
          <div class="nr-modal-head">
            <span>{{ t('model.configureTitle', { name: configureTarget?.name || '' }) }}</span>
            <button class="nr-close" @click="showConfigure = false">&times;</button>
          </div>
          <div v-if="configureTarget" class="nr-modal-body">
            <!-- Base URL -->
            <div class="nr-field">
              <label>Base URL <span class="req">*</span></label>
              <input v-model="configForm.base_url" class="nr-input" />
              <span class="nr-hint">{{ t('model.selectRegion') }}</span>
            </div>
            <!-- API Key -->
            <div class="nr-field">
              <label>{{ t('model.apiKey') }}</label>
              <input v-model="configForm.api_key" type="password" class="nr-input" :placeholder="t('model.apiKeyOptional')" />
            </div>
            <!-- Advanced Config -->
            <div class="nr-advanced">
              <div class="nr-advanced-toggle" @click="advancedOpen = !advancedOpen">
                <span>{{ advancedOpen ? '▾' : '▸' }}</span>
                <span>{{ t('model.advancedConfig') }}</span>
              </div>
              <div v-show="advancedOpen" class="nr-advanced-body">
                <!-- Auth Method -->
                <div class="nr-field">
                  <label>{{ t('model.authMethod') }}</label>
                  <div class="nr-radio-group">
                    <label class="nr-radio" :class="{ active: configForm.auth_method === 'api_key' }">
                      <input type="radio" v-model="configForm.auth_method" value="api_key" />
                      <span>API Key (x-api-key)</span>
                    </label>
                    <label class="nr-radio" :class="{ active: configForm.auth_method === 'bearer' }">
                      <input type="radio" v-model="configForm.auth_method" value="bearer" />
                      <span>Auth Token (Bearer)</span>
                    </label>
                  </div>
                </div>
                <!-- Custom Headers -->
                <div class="nr-field">
                  <label>{{ t('model.customHeaders') }}</label>
                  <div class="nr-hint-row">
                    <span class="nr-hint">{{ t('model.headerHint') }}</span>
                    <span class="nr-link-btn" @click="addCustomHeader">{{ t('model.addHeader') }}</span>
                  </div>
                  <div v-for="(h, i) in configForm.headers" :key="i" class="nr-header-row">
                    <input v-model="h.key" class="nr-input" placeholder="Header name" />
                    <input v-model="h.value" class="nr-input" placeholder="Value" />
                    <button class="nr-remove-btn" @click="configForm.headers.splice(i, 1)">&times;</button>
                  </div>
                </div>
                <!-- Generation Params JSON -->
                <div class="nr-field">
                  <label>{{ t('model.genParams') }}</label>
                  <span class="nr-hint">{{ t('model.genParamsDesc') }}</span>
                  <textarea v-model="configForm.genParamsJson" class="nr-json-editor" rows="6" spellcheck="false" />
                </div>
              </div>
            </div>
          </div>
          <div class="nr-modal-foot">
            <GlassButton variant="ghost" size="md" :loading="testingProvider" @click="testProviderConnection">
              {{ t('model.testConnection') }}
            </GlassButton>
            <div class="nr-modal-foot-right">
              <GlassButton variant="ghost" size="md" @click="showConfigure = false">{{ t('common.cancel') }}</GlassButton>
              <GlassButton variant="primary" size="md" :loading="savingConfig" @click="saveConfiguration">{{ t('model.save') }}</GlassButton>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ===================== Modal: Model Management ===================== -->
    <Teleport to="body">
      <div v-if="showModelManagement" class="nr-overlay" @click.self="showModelManagement = false">
        <div class="nr-modal nr-modal-wide">
          <div class="nr-modal-head">
            <span>{{ modelTarget?.name || '' }} — {{ t('model.modelManagement') }}</span>
            <button class="nr-close" @click="showModelManagement = false">&times;</button>
          </div>

          <div v-if="modelTarget" class="nr-mm-body">
            <!-- Search bar -->
            <div class="nr-mm-search">
              <svg class="nr-mm-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
              <input v-model="modelSearch" :placeholder="t('model.searchModels')" class="nr-mm-search-input" autocomplete="off" @keydown="onModelSearchKeydown" />
              <button v-if="modelSearch" class="nr-mm-search-clear" @click="clearModelSearch" title="Clear">&times;</button>
              <GlassButton variant="ghost" size="sm" @click="applyModelSearch">
                {{ t('common.search') }}
              </GlassButton>
              <GlassButton variant="ghost" size="sm" :loading="discoveringId === modelTarget.id" @click="discoverModels(modelTarget!.id)">
                {{ t('model.discover') }}
              </GlassButton>
              <GlassButton variant="ghost" size="sm" :loading="detectingCaps" @click="detectCapabilities(modelTarget!.id)" :title="t('model.detectCapsTip')">
                {{ t('model.detectCaps') }}
              </GlassButton>
            </div>

            <!-- OpenRouter 模型筛选 -->
            <div v-if="isOpenRouterTarget" class="nr-mm-filter">
              <button class="nr-mm-filter-toggle" @click="filterExpanded = !filterExpanded">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 6 7 7v7l4-2v-5l7-7V4H3z"/></svg>
                {{ t('model.filterModels') }}
              </button>
              <div v-if="filterExpanded" class="nr-mm-filter-panel">
                <div class="nr-mm-filter-row">
                  <span class="nr-mm-filter-label">{{ t('model.filterByProvider') }}</span>
                  <div class="nr-mm-series-list">
                    <button v-for="s in providerSeries" :key="s" class="nr-mm-series-pill" :class="{ active: selectedSeries.includes(s) }" @click="toggleSeries(s)">{{ s }}</button>
                    <span v-if="providerSeries.length === 0" class="nr-mm-filter-hint">—</span>
                  </div>
                </div>
                <div class="nr-mm-filter-row">
                  <span class="nr-mm-filter-label">{{ t('model.filterByModality') }}</span>
                  <div class="nr-mm-series-list">
                    <button v-for="opt in MODALITY_OPTIONS" :key="opt.key" class="nr-mm-series-pill" :class="{ active: selectedModalities.includes(opt.key) }" @click="toggleModality(opt.key)">{{ t(`model.${opt.label}`) }}</button>
                  </div>
                </div>
                <div class="nr-mm-filter-row">
                  <label class="nr-mm-filter-free">
                    <input type="checkbox" v-model="filterFreeOnly" />
                    <span>{{ t('model.filterFreeOnly') }}</span>
                  </label>
                </div>
                <div class="nr-mm-filter-actions">
                  <GlassButton variant="primary" size="sm" :loading="filteringModels" @click="applyProviderFilter">
                    {{ t('model.applyFilter') }}
                  </GlassButton>
                </div>
                <div v-if="filterApplied" class="nr-mm-filter-results">
                  <div class="nr-mm-filter-results-title">{{ t('model.filterResults') }} ({{ filteredResultModels.length }})</div>
                  <div v-if="filteredResultModels.length === 0" class="nr-mm-empty">{{ t('model.noFilteredModels') }}</div>
                  <div v-for="m in filteredResultModels" :key="m.id" class="nr-mm-item">
                    <div class="nr-mm-item-info">
                      <div class="nr-mm-item-name-row">
                        <span class="nr-mm-item-name">{{ m.name }}</span>
                      </div>
                      <span class="nr-mm-item-id">{{ m.id }}</span>
                      <div v-if="coreCapabilityLabels(m).length > 0" class="nr-mm-item-caps">
                        <span v-for="cap in coreCapabilityLabels(m)" :key="cap.key" class="nr-mm-cap" :class="'nr-mm-cap-' + cap.key">{{ cap.label }}</span>
                      </div>
                    </div>
                    <div class="nr-mm-item-tags">
                      <span v-if="m.is_free" class="nr-mm-tag nr-mm-tag-free">{{ t('model.freeModels') }}</span>
                      <span v-if="m.pricing && m.pricing.input != null" class="nr-mm-tag">${{ Number(m.pricing.input) * 1_000_000 }}</span>
                    </div>
                    <div class="nr-mm-item-actions">
                      <button class="nr-mm-btn-submit" @click="addFilteredModel(m)">{{ t('model.addFiltered') }}</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Model list -->
            <div class="nr-mm-list">
              <div v-if="filteredModels.length === 0" class="nr-mm-empty">{{ t('model.noModels') }}</div>
              <div v-for="m in filteredModels" :key="m.id" class="nr-mm-item" :class="{ 'is-active': m.is_active }">
                <div class="nr-mm-item-info">
                  <div class="nr-mm-item-name-row">
                    <span class="nr-mm-item-name">{{ m.name }}</span>
                    <span v-if="m.is_active" class="nr-mm-active-dot" title="Active"></span>
                  </div>
                  <span class="nr-mm-item-id">{{ m.id }}</span>
                  <div v-if="coreCapabilityLabels(m).length > 0 || m.context_window" class="nr-mm-item-caps">
                    <span v-for="cap in coreCapabilityLabels(m)" :key="cap.key" class="nr-mm-cap" :class="'nr-mm-cap-' + cap.key">{{ cap.label }}</span>
                    <span v-if="m.context_window" class="nr-mm-cap nr-mm-cap-limit">{{ modelLimitLabel(m) }}</span>
                  </div>
                </div>
                <div class="nr-mm-item-tags">
                  <span v-if="m.capabilities.includes('text') || m.type === 'text'" class="nr-mm-tag nr-mm-tag-text">{{ t('ui.text') }}</span>
                  <span v-if="m.tags.includes('user-added')" class="nr-mm-tag nr-mm-tag-user">{{ t('model.userAdded') }}</span>
                  <span v-if="m.tags.includes('free')" class="nr-mm-tag nr-mm-tag-free">{{ t('model.freeModels') }}</span>
                  <span v-if="m.tags.includes('built-in')" class="nr-mm-tag nr-mm-tag-builtin">{{ t('model.builtin') }}</span>
                </div>
                <div class="nr-mm-item-actions">
                  <button class="nr-mm-icon-btn" :title="t('model.testConnectionTip')" :disabled="testingModelId === m.id" @click="testModelConnection(m)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
                  </button>
                  <button class="nr-mm-icon-btn" :title="t('model.probeMultimodalTip')" :disabled="probingModelId === m.id" @click="probeModel(m)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>
                  </button>
                  <button class="nr-mm-icon-btn" :title="t('model.editModel')" @click="startEditModel(m)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/></svg>
                  </button>
                  <button class="nr-mm-icon-btn" :title="t('model.settings')" @click="activateModel(m)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                  </button>
                  <button class="nr-mm-icon-btn nr-mm-icon-danger" :title="t('model.delete')" @click="deleteModel(m)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
                  </button>
                </div>
              </div>
            </div>

            <!-- Edit model section -->
            <div v-if="editingModel" class="nr-mm-add-section">
              <div class="nr-mm-add-form">
                <div class="nr-mm-add-title">{{ t('model.editModel') }} — {{ editingModel.id }}</div>
                <div class="nr-mm-add-fields">
                  <div class="nr-mm-add-field">
                    <label>{{ t('model.modelId') }} <span class="req">*</span></label>
                    <input v-model="editModelId" class="nr-input" :placeholder="t('ui.egModelId')" autocomplete="off" />
                  </div>
                  <div class="nr-mm-add-field">
                    <label>{{ t('model.modelNameOptional') }}</label>
                    <input v-model="editModelName" class="nr-input" :placeholder="t('ui.egModelName')" autocomplete="off" />
                  </div>
                </div>
                <div class="nr-mm-add-buttons">
                  <button class="nr-mm-btn-cancel" @click="cancelEditModel">
                    {{ t('common.cancel') }}
                  </button>
                  <button class="nr-mm-btn-submit" :disabled="!editModelId.trim() || savingEdit" @click="saveEditedModel">
                    {{ savingEdit ? '...' : t('common.save') }}
                  </button>
                </div>
              </div>
            </div>

            <!-- Add model section -->
            <div class="nr-mm-add-section">
              <button v-if="!addModelExpanded" class="nr-mm-add-trigger" @click="addModelExpanded = true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>
                {{ t('model.addModel') }}
              </button>
              <div v-else class="nr-mm-add-form">
                <div class="nr-mm-add-fields">
                  <div class="nr-mm-add-field">
                    <label>Model ID <span class="req">*</span></label>
                    <input v-model="newModelId" class="nr-input" :placeholder="t('ui.egModelId')" autocomplete="off" />
                  </div>
                  <div class="nr-mm-add-field">
                    <label>{{ t('common.name') }}</label>
                    <input v-model="newModelName" class="nr-input" :placeholder="t('ui.egModelName')" autocomplete="off" />
                  </div>
                </div>
                <div class="nr-mm-add-buttons">
                  <button class="nr-mm-btn-cancel" @click="addModelExpanded = false; newModelId = ''; newModelName = ''">
                    {{ t('common.cancel') }}
                  </button>
                  <button class="nr-mm-btn-submit" :disabled="!newModelId.trim() || addingModel" @click="addNewModel">
                    {{ addingModel ? '...' : t('model.addModel') }}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import { listProviders, getActiveModel, activateModel as apiActivateModel, updateProvider, createProvider as apiCreateProvider, deleteProvider as apiDeleteProvider, discoverModelsStructured, filterProviderModels, getProviderSeries, testConnection } from '@/api/modules/providers'
import type { FilteredProviderModel } from '@/api/modules/providers'
import { listModels, updateModel, deleteModel as apiDeleteModel, detectCapabilities as apiDetectCapabilities, checkModelConnection, probeModelMultimodal } from '@/api/modules/models'
import type { ModelConnectionResult } from '@/api/modules/models'
import { getSettings, updateSettings } from '@/api/modules/settings'
import { useAuthStore } from '@/stores/auth'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'
import type { Provider, ModelItem, DefaultLLMConfig, GenerationParams } from '@/types/model'

const { t } = useI18n()
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function maskApiKey(key?: string): string {
  if (!key) return ''
  if (key.length <= 8) return '••••••'
  return key.slice(0, 6) + '•••••' + key.slice(-2)
}

/** Map a backend ModelInfo to our frontend ModelItem. */
function mapModel(m: any, fallbackProvider = ''): ModelItem {
  return {
    id: m.model_id || m.id || m.name || 'unknown',
    name: m.name || m.model_id || m.id || 'Unknown',
    provider_id: m.provider || m.provider_id || fallbackProvider || '',
    type: m.type || 'text',
    tags: m.tags || (m.is_active ? ['built-in'] : []),
    enabled: m.enabled !== false && m.status !== 'unavailable',
    capabilities: Array.isArray(m.capabilities) ? m.capabilities : [],
    is_active: m.is_active === true,
    context_window: m.context_window,
    max_tokens: m.max_tokens,
    pricing: m.pricing,
    owned_by: m.owned_by,
  }
}

// ---------------------------------------------------------------------------
// Built-in provider seeds (30+ providers)
// ---------------------------------------------------------------------------
type SeedProvider = {
  id: string; name: string; icon: string; iconSrc?: string; color: string
  type: 'builtin' | 'custom'; category: 'paid' | 'free' | 'local'
  base_url: string; protocol: 'openai' | 'anthropic'; enabled: boolean
}

const BUILTIN_PROVIDERS: SeedProvider[] = [
  // ── Local ──
  { id: 'ollama', name: 'Ollama', icon: '🦙', color: '#000000', type: 'builtin', category: 'local', base_url: 'http://192.168.2.2:11434', protocol: 'openai', enabled: true },
  { id: 'lm-studio', name: 'LM Studio', icon: 'LM', color: '#7c3aed', type: 'builtin', category: 'local', base_url: 'http://localhost:1234/v1', protocol: 'openai', enabled: true },
  // ── Free ──
  { id: 'openrouter', name: 'OpenRouter', icon: '←', iconSrc: 'https://gw.alicdn.com/imgextra/i4/O1CN01oX74jS1ciQR9xBtZ2_!!6000000003634-2-tps-252-252.png', color: '#111827', type: 'builtin', category: 'free', base_url: 'https://openrouter.ai/api/v1', protocol: 'openai', enabled: true },
  { id: 'opencode', name: 'OpenCode', icon: '⬜', iconSrc: 'https://gw.alicdn.com/imgextra/i1/O1CN01d3RfoB28G5dbN4i97_!!6000000007904-2-tps-30-30.png', color: '#000000', type: 'builtin', category: 'free', base_url: 'https://opencode.ai/zen/v1', protocol: 'openai', enabled: true },
  { id: 'kilo-code', name: 'Kilo Code', icon: 'K', iconSrc: 'https://kilo.ai/favicon/android-chrome-192x192.png', color: '#3b82f6', type: 'builtin', category: 'free', base_url: 'https://api.kilo.ai/api/gateway', protocol: 'openai', enabled: true },
  { id: 'github-models', name: 'GitHub Models', icon: '🐙', iconSrc: 'https://github.githubassets.com/assets/GitHub-Mark-ea2971cee799.png', color: '#1f2937', type: 'builtin', category: 'free', base_url: 'https://models.inference.ai.azure.com', protocol: 'openai', enabled: true },
  // ── Paid ──
  { id: 'google-gemini', name: 'Google Gemini', icon: '◆', iconSrc: 'https://gw.alicdn.com/imgextra/i2/O1CN01pDWy7z25caEvmJ3u1_!!6000000007547-2-tps-400-400.png', color: '#4285f4', type: 'builtin', category: 'paid', base_url: 'https://generativelanguage.googleapis.com', protocol: 'openai', enabled: true },
  { id: 'zhipu', name: 'Zhipu (BigModel)', icon: 'Z', iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01TFZcQz23xX7qacIEv_!!6000000007322-2-tps-640-640.png', color: '#4a90d9', type: 'builtin', category: 'paid', base_url: 'https://open.bigmodel.cn/api/paas/v4', protocol: 'openai', enabled: true },
  { id: 'siliconflow-cn', name: 'SiliconFlow (China)', icon: 'SF', iconSrc: 'https://img.alicdn.com/imgextra/i1/O1CN01TUkzVC1clAoPa2ix8_!!6000000003640-2-tps-520-520.png', color: '#6366f1', type: 'builtin', category: 'paid', base_url: 'https://api.siliconflow.cn/v1', protocol: 'openai', enabled: true },
  { id: 'siliconflow-intl', name: 'SiliconFlow (International)', icon: 'SF', iconSrc: 'https://img.alicdn.com/imgextra/i1/O1CN01TUkzVC1clAoPa2ix8_!!6000000003640-2-tps-520-520.png', color: '#818cf8', type: 'builtin', category: 'paid', base_url: 'https://api.siliconflow.com/v1', protocol: 'openai', enabled: true },
  { id: 'ark-coding', name: 'ark-coding', icon: 'AC', color: '#0ea5e9', type: 'builtin', category: 'paid', base_url: 'https://ark.cn-beijing.volces.com/api/coding/v3', protocol: 'openai', enabled: true },
  { id: 'arkcoding-anthropic', name: 'arkcoding-anthropic', icon: 'AA', color: '#0891b2', type: 'builtin', category: 'paid', base_url: 'https://ark.cn-beijing.volces.com/api/coding/v3', protocol: 'anthropic', enabled: true },
  { id: 'sambanova', name: 'sambanova.ai', icon: 'SN', color: '#dc2626', type: 'builtin', category: 'paid', base_url: 'https://api.sambanova.ai/v1', protocol: 'openai', enabled: true },
  { id: 'nsc', name: t('ui.providerNsc'), icon: 'N', color: '#b91c1c', type: 'builtin', category: 'paid', base_url: 'https://api.nsc.org.cn/v1', protocol: 'openai', enabled: true },
  { id: 'sensetime', name: t('ui.providerSensetime'), icon: 'S', color: '#7c3aed', type: 'builtin', category: 'paid', base_url: 'https://token.sensenova.cn/v1', protocol: 'openai', enabled: true },
  { id: 'xiaomi', name: t('ui.providerXiaomi'), icon: 'Mi', iconSrc: 'https://img.alicdn.com/imgextra/i1/O1CN01TSCOAt1XP7fywLDei_!!6000000002915-2-tps-3483-3483.png', color: '#f97316', type: 'builtin', category: 'paid', base_url: 'https://api.xiaomi.com/v1', protocol: 'openai', enabled: true },
  { id: 'modelscope', name: 'ModelScope', icon: 'MS', iconSrc: 'https://gw.alicdn.com/imgextra/i4/O1CN01exenB61EAwhgY4pmA_!!6000000000312-2-tps-400-400.png', color: '#0d9488', type: 'builtin', category: 'paid', base_url: 'https://api.modelscope.cn/v1', protocol: 'openai', enabled: true },
  { id: 'dashscope', name: 'DashScope', icon: 'DS', iconSrc: 'https://gw.alicdn.com/imgextra/i4/O1CN01aDHDeq1mgj7gbRkhi_!!6000000004984-2-tps-400-400.png', color: '#0284c7', type: 'builtin', category: 'paid', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', protocol: 'openai', enabled: true },
  { id: 'aliyun-coding-cn', name: 'Aliyun Coding Plan (China)', icon: '☁', iconSrc: 'https://gw.alicdn.com/imgextra/i4/O1CN01nEmGhQ1we71GXW6eo_!!6000000006332-2-tps-400-400.png', color: '#f97316', type: 'builtin', category: 'paid', base_url: 'https://coding.dashscope.aliyuncs.com/v1', protocol: 'openai', enabled: true },
  { id: 'aliyun-coding-intl', name: 'Aliyun Coding Plan (International)', icon: '☁', iconSrc: 'https://gw.alicdn.com/imgextra/i4/O1CN01nEmGhQ1we71GXW6eo_!!6000000006332-2-tps-400-400.png', color: '#fb923c', type: 'builtin', category: 'paid', base_url: 'https://coding.dashscope-intl.aliyuncs.com/v1', protocol: 'openai', enabled: true },
  { id: 'aliyun-token', name: 'Aliyun Token Plan', icon: '☁', iconSrc: 'https://gw.alicdn.com/imgextra/i4/O1CN01nEmGhQ1we71GXW6eo_!!6000000006332-2-tps-400-400.png', color: '#ea580c', type: 'builtin', category: 'paid', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', protocol: 'openai', enabled: true },
  { id: 'openai', name: 'OpenAI', icon: 'OA', iconSrc: 'https://gw.alicdn.com/imgextra/i3/O1CN01rQSexq1D7S4AYstKh_!!6000000000169-2-tps-400-400.png', color: '#10a37f', type: 'builtin', category: 'paid', base_url: 'https://api.openai.com/v1', protocol: 'openai', enabled: true },
  { id: 'azure-openai', name: 'Azure OpenAI', icon: 'Az', iconSrc: 'https://gw.alicdn.com/imgextra/i2/O1CN01R42n1y1hQAjCEiVlB_!!6000000004271-2-tps-400-400.png', color: '#0078d4', type: 'builtin', category: 'paid', base_url: 'https://YOUR_RESOURCE.openai.azure.com', protocol: 'openai', enabled: true },
  { id: 'anthropic', name: 'Anthropic', icon: 'A', iconSrc: 'https://gw.alicdn.com/imgextra/i2/O1CN014LwvBJ1tNDYvc3FfA_!!6000000005889-2-tps-400-400.png', color: '#d4a574', type: 'builtin', category: 'paid', base_url: 'https://api.anthropic.com', protocol: 'anthropic', enabled: true },
  { id: 'deepseek', name: 'DeepSeek', icon: 'DS', iconSrc: 'https://gw.alicdn.com/imgextra/i4/O1CN01YfmXc81ogO3pR0aW8_!!6000000005254-2-tps-400-400.png', color: '#4d6bfe', type: 'builtin', category: 'paid', base_url: 'https://api.deepseek.com', protocol: 'openai', enabled: true },
  { id: 'kimi-cn', name: 'Kimi (China)', icon: 'K', iconSrc: 'https://gw.alicdn.com/imgextra/i1/O1CN01xCKAr81Yz8Q9pXh1u_!!6000000003129-2-tps-400-400.png', color: '#1e1b4b', type: 'builtin', category: 'paid', base_url: 'https://api.moonshot.cn/v1', protocol: 'openai', enabled: true },
  { id: 'kimi-intl', name: 'Kimi (International)', icon: 'K', iconSrc: 'https://gw.alicdn.com/imgextra/i1/O1CN01xCKAr81Yz8Q9pXh1u_!!6000000003129-2-tps-400-400.png', color: '#312e81', type: 'builtin', category: 'paid', base_url: 'https://api.moonshot.ai/v1', protocol: 'openai', enabled: true },
  { id: 'minimax-cn', name: 'MiniMax (China)', icon: 'MM', iconSrc: 'https://gw.alicdn.com/imgextra/i1/O1CN01B0FaVn1VzBcO4nF1C_!!6000000002723-2-tps-400-400.png', color: '#ef4444', type: 'builtin', category: 'paid', base_url: 'https://api.minimax.chat/v1', protocol: 'openai', enabled: true },
  { id: 'minimax-intl', name: 'MiniMax (International)', icon: 'MM', iconSrc: 'https://gw.alicdn.com/imgextra/i1/O1CN01B0FaVn1VzBcO4nF1C_!!6000000002723-2-tps-400-400.png', color: '#f87171', type: 'builtin', category: 'paid', base_url: 'https://api.minimaxi.chat/v1', protocol: 'openai', enabled: true },
  { id: 'zhipu-coding', name: 'Zhipu Coding Plan', icon: 'Z', iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01TFZcQz23xX7qacIEv_!!6000000007322-2-tps-640-640.png', color: '#2563eb', type: 'builtin', category: 'paid', base_url: 'https://open.bigmodel.cn/api/coding/paas/v4', protocol: 'openai', enabled: true },
  { id: 'zhipu-zai', name: 'Zhipu Z.AI', icon: 'Z', iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01TFZcQz23xX7qacIEv_!!6000000007322-2-tps-640-640.png', color: '#059669', type: 'builtin', category: 'paid', base_url: 'https://api.z.ai/api/paas/v4', protocol: 'openai', enabled: true },
  { id: 'zhipu-coding-zai', name: 'Zhipu Coding Z.AI', icon: 'ZC', iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01TFZcQz23xX7qacIEv_!!6000000007322-2-tps-640-640.png', color: '#047857', type: 'builtin', category: 'paid', base_url: 'https://api.z.ai/api/coding/paas/v4', protocol: 'openai', enabled: true },
  { id: 'volcano', name: 'Volcano Engine', icon: '🌋', iconSrc: 'https://img.alicdn.com/imgextra/i1/O1CN01KusRg42AJPkUV5ken_!!6000000008182-2-tps-1892-1660.png', color: '#dc2626', type: 'builtin', category: 'paid', base_url: 'https://ark.cn-beijing.volces.com/api/v3', protocol: 'openai', enabled: true },
  { id: 'volcano-coding', name: 'Volcano Engine Coding Plan', icon: '🌋', iconSrc: 'https://img.alicdn.com/imgextra/i1/O1CN01KusRg42AJPkUV5ken_!!6000000008182-2-tps-1892-1660.png', color: '#b91c1c', type: 'builtin', category: 'paid', base_url: 'https://ark.cn-beijing.volces.com/api/coding/v3', protocol: 'openai', enabled: true },
  { id: 'xiaomi-mimo', name: 'Xiaomi MiMo Token Plan', icon: 'Mi', iconSrc: 'https://img.alicdn.com/imgextra/i1/O1CN01TSCOAt1XP7fywLDei_!!6000000002915-2-tps-3483-3483.png', color: '#ea580c', type: 'builtin', category: 'paid', base_url: 'https://api.xiaomi.com/v1', protocol: 'openai', enabled: true },
]

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const loading = ref(true)
const loadingModels = ref(false)
const savingDefault = ref(false)
const savingProvider = ref(false)
const savingConfig = ref(false)
const testingProvider = ref(false)
const addingModel = ref(false)
const advancedOpen = ref(false)
const discoveringId = ref<string | null>(null)

const providers = ref<Provider[]>([])
const allModels = ref<ModelItem[]>([])
const providerSearch = ref('')
const modelSearch = ref('')
const modelSearchApplied = ref('')
const inlineApiKeys = reactive<Record<string, string>>({})
const revealKey = reactive<Record<string, boolean>>({})

// Default LLM config
const defaultConfig = reactive<DefaultLLMConfig>({ provider_id: '', model_id: '' })
const activeModelInfo = reactive({ model_id: '', name: '', provider: '' })

// Add provider form
const showAddProvider = ref(false)
const addForm = reactive({ name: '', provider_type: 'openai', base_url: '', api_key: '' })

// Configure provider modal
const showConfigure = ref(false)
const configureTarget = ref<Provider | null>(null)
const configForm = reactive({
  base_url: '',
  api_key: '',
  auth_method: 'api_key' as 'api_key' | 'bearer',
  headers: [] as { key: string; value: string }[],
  genParamsJson: '{}',
})

// Model management modal
const showModelManagement = ref(false)
const modelTarget = ref<Provider | null>(null)
// 模型筛选状态(OpenRouter)
const filterExpanded = ref(false)
const providerSeries = ref<string[]>([])
const selectedSeries = ref<string[]>([])
const selectedModalities = ref<string[]>([])
const filterFreeOnly = ref(false)
const filteringModels = ref(false)
const filterApplied = ref(false)
const filteredResultModels = ref<FilteredProviderModel[]>([])
const MODALITY_OPTIONS = [
  { key: 'image', label: 'modalityImage' },
  { key: 'audio', label: 'modalityAudio' },
  { key: 'video', label: 'modalityVideo' },
] as const
const isOpenRouterTarget = computed(() => modelTarget.value?.id === 'openrouter')
const newModelId = ref('')
const newModelName = ref('')
const addModelExpanded = ref(false)
const editingModel = ref<ModelItem | null>(null)
const editModelId = ref('')
const editModelName = ref('')
const savingEdit = ref(false)

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------
const providersWithModels = computed(() =>
  providers.value.filter((p) => p.model_count > 0),
)

const defaultModelOptions = computed(() => {
  const pid = defaultConfig.provider_id
  const p = providers.value.find((pr) => pr.id === pid)
  return p?.models ?? []
})

const filteredProviders = computed(() => {
  if (!providerSearch.value) return providers.value
  const q = providerSearch.value.toLowerCase()
  return providers.value.filter((p) => p.name.toLowerCase().includes(q) || p.id.toLowerCase().includes(q))
})

const filteredModels = computed(() => {
  if (!modelTarget.value) return []
  // 直接从 allModels 过滤，避免依赖 providers.value 中嵌套的 models 数组引用
  let list = allModels.value.filter((m) => m.provider_id === modelTarget.value!.id || m.provider_id === modelTarget.value!.name)
  if (modelSearchApplied.value) {
    const q = modelSearchApplied.value.toLowerCase()
    list = list.filter((m) => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q))
  }
  return list
})

function applyModelSearch() {
  modelSearchApplied.value = modelSearch.value
}

function onModelSearchKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') applyModelSearch()
}

function clearModelSearch() {
  modelSearch.value = ''
  modelSearchApplied.value = ''
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------
async function fetchProviders() {
  loading.value = true
  try {
    const res: any = await listProviders()
    // Interceptor already unwraps response.data
    // Backend may return: raw array [...], {data:[...]}, {providers:[...]}, or {code:0, data:[...]}
    let apiProviders: any[] = []
    if (Array.isArray(res)) {
      apiProviders = res
    } else if (res?.data && Array.isArray(res.data)) {
      apiProviders = res.data
    } else if (res?.providers && Array.isArray(res.providers)) {
      apiProviders = res.providers
    }
    console.log('[ModelPage] fetchProviders API response:', apiProviders.length, 'providers from backend')
    providers.value = mergeProviders(apiProviders)
    console.log('[ModelPage] fetchProviders merged:', providers.value.length, 'providers')
  } catch (err) {
    console.warn('[ModelPage] fetchProviders failed, showing built-in only:', err)
    // Always show built-in providers even if API fails (SPA navigation race condition)
    providers.value = buildDefaultProviders()
  } finally {
    loading.value = false
  }
}

async function fetchModels() {
  loadingModels.value = true
  try {
    const res: any = await listModels()
    const raw = res?.data ?? res ?? []
    const list = Array.isArray(raw) ? raw : (raw?.data ?? raw?.models ?? [])
    allModels.value = list.map((m: any) => mapModel(m))
    // Rebuild providers array with new object references to ensure Vue reactivity
    providers.value = providers.value.map((p) => {
      const models = allModels.value.filter((m) => m.provider_id === p.id || m.provider_id === p.name)
      return { ...p, models, model_count: models.length }
    })
  } catch {
    message.error(t('common.error'))
    allModels.value = []
  } finally {
    loadingModels.value = false
  }
}

async function fetchActiveModel() {
  try {
    const res: any = await getActiveModel()
    const data = res?.data ?? res ?? {}
    activeModelInfo.model_id = data.model_id || data.model || ''
    activeModelInfo.name = data.name || data.model_id || data.model || ''
    activeModelInfo.provider = data.provider_name || data.provider || ''
    if (activeModelInfo.model_id && activeModelInfo.model_id !== 'unknown') {
      if (activeModelInfo.provider && !defaultConfig.provider_id) {
        const match = providers.value.find((p) => p.id === activeModelInfo.provider || p.name === activeModelInfo.provider)
        if (match) {
          defaultConfig.provider_id = match.id
          defaultConfig.model_id = activeModelInfo.model_id
        }
      }
    }
  } catch {
    message.error(t('common.error'))
  }
}

async function fetchDefaultConfig() {
  try {
    const res = await getSettings()
    const settings = res?.data
    if (settings?.llm?.default_provider) defaultConfig.provider_id = settings.llm.default_provider
    if (settings?.llm?.default_model) defaultConfig.model_id = settings.llm.default_model
  } catch {
    message.error(t('common.error'))
  }
}

/** Merge API-returned providers with built-in seeds. */
function mergeProviders(apiList: any[]): Provider[] {
  const map = new Map<string, any>()
  for (const p of apiList) map.set(p.provider_id || p.id || p.name, p)

  const result: Provider[] = []
  const seen = new Set<string>()

  for (const seed of BUILTIN_PROVIDERS) {
    const apiData = map.get(seed.id)
    seen.add(seed.id)
    result.push(buildProvider(seed, apiData))
  }

  for (const [id, apiData] of map) {
    if (seen.has(id)) continue
    result.push({
      id,
      name: apiData.name || id,
      icon: (apiData.name || id).charAt(0).toUpperCase(),
      color: '#6b7280',
      type: 'custom',
      category: 'paid',
      status: resolveStatus(apiData),
      statusLabel: resolveStatusLabel(apiData),
      base_url: apiData.base_url || '',
      api_key: apiData.api_key,
      api_key_configured: !!apiData.api_key,
      auth_method: apiData.auth_method || 'api_key',
      protocol: apiData.provider_type === 'anthropic' ? 'anthropic' : 'openai',
      models: [],
      model_count: apiData.models_count || apiData.models?.length || 0,
      enabled: apiData.is_active !== false && apiData.enabled !== false,
      health: apiData.health || 'unknown',
      priority: apiData.priority || 0,
      config: apiData.config,
      headers: apiData.headers,
    })
  }

  return result
}

function buildProvider(seed: SeedProvider, apiData?: any): Provider {
  const models: ModelItem[] = apiData?.models?.map((m: any) => mapModel(m, seed.id)) ?? []
  return {
    ...seed,
    base_url: apiData?.base_url || seed.base_url,
    api_key: apiData?.api_key,
    api_key_configured: !!apiData?.api_key || (seed.category === 'free' && !['github-models', 'google-gemini', 'zhipu'].includes(seed.id)),
    auth_method: apiData?.auth_method || (seed.protocol === 'anthropic' ? 'api_key' : 'bearer'),
    status: resolveStatus(apiData || {}),
    statusLabel: resolveStatusLabel(apiData || {}),
    models,
    model_count: models.length || apiData?.models_count || 0,
    enabled: apiData?.is_active !== false && apiData?.enabled !== false,
    health: apiData?.health || 'unknown',
    priority: apiData?.priority || 0,
    config: apiData?.config,
    headers: apiData?.headers,
  }
}

function buildDefaultProviders(): Provider[] {
  return BUILTIN_PROVIDERS.map((s) => buildProvider(s))
}

function resolveStatus(data: any): Provider['status'] {
  if (data.status === 'active' || data.is_active || data.enabled) return 'available'
  if (data.models?.length > 0 || data.models_count > 0) return 'available'
  if (data.api_key) return 'not_ready'
  return 'not_configured'
}

function resolveStatusLabel(data: any): string {
  const status = resolveStatus(data)
  switch (status) {
    // active/已启用的 provider 若无模型列表（models_count=0），
    // 不应再显示「可用（有模型）」——与模型计数行保持语义一致
    case 'available': return (data.models?.length || data.models_count) ? t('model.statusAvailable') : t('model.statusNotReady')
    case 'unavailable': return t('model.statusUnavailable')
    case 'not_ready': return data.models?.length ? t('model.statusNoModels') : t('model.statusNotReady')
    case 'not_configured': return t('model.statusNotReady')
  }
}

function onDefaultProviderChange() {
  defaultConfig.model_id = ''
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------
async function saveDefaultLLM() {
  if (!defaultConfig.provider_id || !defaultConfig.model_id) {
    message.warning(t('model.selectProviderAndModel'))
    return
  }
  savingDefault.value = true
  try {
    await apiActivateModel({
      provider_id: defaultConfig.provider_id,
      model_id: defaultConfig.model_id,
    })
    await updateSettings('llm', { default_provider: defaultConfig.provider_id, default_model: defaultConfig.model_id })
    activeModelInfo.model_id = defaultConfig.model_id
    activeModelInfo.provider = defaultConfig.provider_id
    const p = providers.value.find((pr) => pr.id === defaultConfig.provider_id)
    if (p) activeModelInfo.name = p.name
    for (const prov of providers.value) {
      for (const m of prov.models) {
        m.is_active = (m.id === defaultConfig.model_id && prov.id === defaultConfig.provider_id)
      }
    }
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    savingDefault.value = false
  }
}

async function saveInlineKey(p: Provider) {
  const key = inlineApiKeys[p.id]
  if (!key) return
  try {
    await ensureProvider(p)
    await updateProvider(p.id, { api_key: key })
    p.api_key = key
    p.api_key_configured = true
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  }
}

/** Ensure provider exists in backend — try PUT, if 404 then POST create */
async function ensureProvider(p: { id: string; name: string; base_url: string; protocol?: string }) {
  try {
    await updateProvider(p.id, {})
  } catch (err: any) {
    if (err?.response?.status === 404) {
      // Provider not found — try to create it
      let created: any = null
      try {
        created = await apiCreateProvider({
          name: p.name,
          provider_type: p.protocol || 'openai',
          base_url: p.base_url || undefined,
        })
      } catch (createErr: any) {
        console.warn('[ensureProvider] createProvider failed:', createErr?.response?.status, createErr?.message)
      }
      if (created?.provider_id) {
        // Backend created with a different ID — update caller reference
        if (created.provider_id !== p.id) {
          p.id = created.provider_id
        }
      } else {
        // Both PUT and POST failed — provider cannot be resolved
        throw new Error(`Provider "${p.name}" not found and could not be created`)
      }
    } else {
      throw err
    }
  }
}

async function saveProviderKey(p: Provider) {
  // Re-save the existing key (e.g., after toggling visibility or updating)
  if (!p.api_key) return
  try {
    await ensureProvider(p)
    await updateProvider(p.id, { api_key: p.api_key })
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  }
}

async function createProvider() {
  if (!addForm.name) return
  savingProvider.value = true
  try {
    await apiCreateProvider({
      name: addForm.name,
      provider_type: addForm.provider_type,
      base_url: addForm.base_url || undefined,
      api_key: addForm.api_key || undefined,
    })
    message.success(t('common.success'))
    showAddProvider.value = false
    addForm.name = ''
    addForm.provider_type = 'openai'
    addForm.base_url = ''
    addForm.api_key = ''
    await fetchProviders()
  } catch {
    message.error(t('common.error'))
  } finally {
    savingProvider.value = false
  }
}

async function deleteProvider(p: Provider) {
  try {
    await apiDeleteProvider(p.id)
    providers.value = providers.value.filter((pp) => pp.id !== p.id)
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  }
}

async function discoverModels(providerId: string) {
  discoveringId.value = providerId
  try {
    // QwenPaw 对齐:结构化结果(success/discovered_count/used_static_fallback/error_kind)
    const res: any = await discoverModelsStructured(providerId) as any
    const data = res?.data ?? res ?? {}
    const discovered: any[] = data.models ?? []
    if (!data.success && data.used_static_fallback) {
      // 发现失败:展示 error_kind 可行动提示,已回退展示配置存量
      const kindHints: Record<string, string> = {
        authentication: t('model.discoverAuthFailed'),
        network: t('model.discoverNetworkFailed'),
        provider_unavailable: t('model.discoverUnavailable'),
        rate_limited: t('model.discoverRateLimited'),
        invalid_response: t('model.discoverInvalidResponse'),
        configuration: t('model.discoverNotConfigured'),
      }
      message.warning(kindHints[data.error_kind] || data.message || t('model.discoverFailed'))
      return
    }
    if (discovered.length === 0) {
      // 后端 message(如"请先配置 API Key")优先;无可行动脚本时回到通用文案
      message.info(data.message || t('model.noNewModels'))
      return
    }
    const provider = providers.value.find((p) => p.id === providerId)
    if (provider) {
      const existingIds = new Set(provider.models.map((m) => m.id))
      for (const dm of discovered) {
        const mapped = mapModel(dm, providerId)
        if (!existingIds.has(mapped.id)) {
          provider.models.push(mapped)
          allModels.value.push(mapped)
        }
      }
      provider.model_count = provider.models.length
    }
    const newCount = typeof data.discovered_count === 'number' ? data.discovered_count : discovered.length
    message.success(t('model.modelsDiscovered', { n: newCount }))
  } catch {
    message.error(t('model.discoverFailed'))
  } finally {
    discoveringId.value = null
  }
}

// ---------------------------------------------------------------------------
// 模型能力自动检测（2026-09-03）
// 六类核心能力：text/reasoning/vision/video/image_generation/video_generation
// ---------------------------------------------------------------------------
/** 能力 key → i18n 标签（model.capText 等），按 canonical 顺序渲染。 */
const CAP_LABEL_KEYS: Array<{ key: string; labelKey: string }> = [
  { key: 'text', labelKey: 'model.capText' },
  { key: 'reasoning', labelKey: 'model.capReasoning' },
  { key: 'vision', labelKey: 'model.capVision' },
  { key: 'video', labelKey: 'model.capVideo' },
  { key: 'image_generation', labelKey: 'model.capImageGen' },
  { key: 'video_generation', labelKey: 'model.capVideoGen' },
]

function coreCapabilityLabels(m: { capabilities?: string[] }): Array<{ key: string; label: string }> {
  return CAP_LABEL_KEYS.filter((c) => m.capabilities?.includes(c.key)).map((c) => ({
    key: c.key,
    label: t(c.labelKey),
  }))
}

/** 限额 chip：展示上下文窗口（预埋/服务商值，4096 占位由后端过滤不外发）。 */
function modelLimitLabel(m: { context_window?: number; max_tokens?: number }): string {
  if (!m.context_window) return ''
  const ctx = m.context_window >= 1000 ? `${Math.round(m.context_window / 1000)}K` : String(m.context_window)
  return `ctx ${ctx}`
}

const detectingCaps = ref(false)

// ---------------------------------------------------------------------------
// 模型级连接测试 + 多模态真实探测（QwenPaw 对齐）
// ---------------------------------------------------------------------------
const testingModelId = ref<string | null>(null)
const probingModelId = ref<string | null>(null)

/** 可用性七态 → 结果消息的语气与文案。 */
function modelTestResultMessage(r: ModelConnectionResult): { type: 'success' | 'warning' | 'error'; text: string } {
  if (r.connected) {
    // provider_only=仅验证服务商连通（如非对话模型降级验证），提示用户非全量验证
    const verificationHint = r.verification === 'provider_only' ? ` (${t('model.verifiedProviderOnly')})` : ''
    return { type: 'success', text: t('model.connectionOk') + verificationHint }
  }
  const kindHints: Record<string, string> = {
    permission_denied: t('model.testPermissionDenied'),
    model_not_found: t('model.testModelNotFound'),
    incompatible_api: t('model.testIncompatible'),
    rate_limited: t('model.testRateLimited'),
    transient_error: t('model.testTransient'),
  }
  // 后端 error_hint（脱敏可行动提示）优先
  return { type: 'error', text: r.error_hint || kindHints[r.status || ''] || r.message || t('model.connectionFailed') }
}

/** 对单个模型发真实连接测试（chat ping），结果以消息展示。 */
async function testModelConnection(m: ModelItem) {
  testingModelId.value = m.id
  try {
    const res: any = await checkModelConnection(m.id) as any
    const data: ModelConnectionResult = res?.data ?? res ?? {}
    const result = modelTestResultMessage(data)
    if (result.type === 'success') message.success(result.text)
    else message.error(result.text)
  } catch {
    message.error(t('model.connectionFailed'))
  } finally {
    testingModelId.value = null
  }
}

/** 对单个模型发真实多模态探测（图像问答），支持 vision 时补拉能力标记。 */
async function probeModel(m: ModelItem) {
  probingModelId.value = m.id
  try {
    const res: any = await probeModelMultimodal({ model_id: m.id, force: true }) as any
    const result = res?.data?.result ?? res?.result ?? {}
    const source = result?.probe_source ?? result?.metadata?.probe_source
    const caps: string[] = result?.capabilities?.map((c: any) => (typeof c === 'string' ? c : c.value ?? String(c))) ?? []
    if (source === 'probed' && caps.includes('vision')) {
      message.success(t('model.probeVisionYes'))
      await fetchModels()
    } else if (source === 'probed') {
      message.info(t('model.probeVisionNo'))
    } else {
      message.warning(t('model.probeInconclusive'))
    }
  } catch {
    message.error(t('model.probeFailed'))
  } finally {
    probingModelId.value = null
  }
}

async function detectCapabilities(providerId: string) {
  detectingCaps.value = true
  try {
    const res: any = await apiDetectCapabilities({ provider_id: providerId, force: true })
    const detected = res?.data?.detected ?? res?.detected ?? 0
    if (detected > 0) {
      // 重新拉取模型列表以带上新能力标记
      await fetchModels()
      message.success(t('model.detectCapsDone', { n: detected }))
    } else {
      message.info(t('model.noModels'))
    }
  } catch {
    message.error(t('model.detectCapsFailed'))
  } finally {
    detectingCaps.value = false
  }
}

async function activateModel(m: ModelItem) {
  try {
    await apiActivateModel({
      provider_id: m.provider_id,
      model_id: m.id,
    })
    for (const prov of providers.value) {
      for (const model of prov.models) {
        model.is_active = (model.id === m.id && prov.id === m.provider_id)
      }
    }
    activeModelInfo.model_id = m.id
    activeModelInfo.name = m.name
    activeModelInfo.provider = m.provider_id
    defaultConfig.provider_id = m.provider_id
    defaultConfig.model_id = m.id
    message.success(t('model.modelActivated'))
  } catch {
    message.error(t('common.error'))
  }
}

function openConfigure(p: Provider) {
  configureTarget.value = p
  configForm.base_url = p.base_url
  configForm.api_key = p.api_key || ''
  configForm.auth_method = p.auth_method || (p.protocol === 'anthropic' ? 'api_key' : 'bearer')
  configForm.headers = p.headers
    ? Object.entries(p.headers).map(([key, value]) => ({ key, value }))
    : []
  configForm.genParamsJson = p.config ? JSON.stringify(p.config, null, 2) : '{}'
  advancedOpen.value = false
  showConfigure.value = true
}

function addCustomHeader() {
  configForm.headers.push({ key: '', value: '' })
}

async function testProviderConnection() {
  if (!configureTarget.value) return
  testingProvider.value = true
  try {
    const res: any = await testConnection(configureTarget.value.id) as any
    // 后端信封 {code, data:{connected, success, ...}}：须解包再读字段（2026-09-05 修复恒报连接失败）
    const data = res?.data ?? res ?? {}
    if (data.success || data.connected) {
      message.success(t('model.connectionOk', { ms: data.latency_ms || '' }))
    } else {
      // error_hint（五类归一错误的可行动提示）优先，原始错误信息次之
      message.warning(data.error_hint || data.error || data.message || t('model.connectionFailed'))
    }
  } catch {
    message.error(t('model.connectionFailed'))
  } finally {
    testingProvider.value = false
  }
}

async function saveConfiguration() {
  if (!configureTarget.value) return
  savingConfig.value = true
  try {
    const headers: Record<string, string> = {}
    for (const h of configForm.headers) {
      if (h.key) headers[h.key] = h.value
    }
    let genParams: Record<string, unknown> = {}
    try { genParams = JSON.parse(configForm.genParamsJson) } catch { /* keep empty */ }

    const configPayload = {
      base_url: configForm.base_url,
      api_key: configForm.api_key || undefined,
      config: {
        ...genParams,
        auth_method: configForm.auth_method,
        ...(Object.keys(headers).length ? { headers } : {}),
      },
    }
    await ensureProvider(configureTarget.value)
    await updateProvider(configureTarget.value.id, configPayload)
    configureTarget.value.base_url = configForm.base_url
    configureTarget.value.api_key = configForm.api_key
    configureTarget.value.api_key_configured = !!configForm.api_key
    configureTarget.value.auth_method = configForm.auth_method
    configureTarget.value.headers = headers
    configureTarget.value.config = genParams
    message.success(t('common.success'))
    showConfigure.value = false
  } catch {
    message.error(t('common.error'))
  } finally {
    savingConfig.value = false
  }
}

function openModelManagement(p: Provider) {
  modelTarget.value = p
  modelSearch.value = ''
  modelSearchApplied.value = ''
  newModelId.value = ''
  newModelName.value = ''
  addModelExpanded.value = false
  // 重置筛选状态;OpenRouter 展开时预载系列列表
  filterExpanded.value = false
  providerSeries.value = []
  selectedSeries.value = []
  selectedModalities.value = []
  filterFreeOnly.value = false
  filterApplied.value = false
  filteredResultModels.value = []
  showModelManagement.value = true
  if (p.id === 'openrouter') {
    void loadProviderSeries(p)
  }
}

function toggleSeries(series: string) {
  selectedSeries.value = selectedSeries.value.includes(series)
    ? selectedSeries.value.filter((s) => s !== series)
    : [...selectedSeries.value, series]
}

function toggleModality(modality: string) {
  selectedModalities.value = selectedModalities.value.includes(modality)
    ? selectedModalities.value.filter((m) => m !== modality)
    : [...selectedModalities.value, modality]
}

async function loadProviderSeries(p: Provider) {
  try {
    const res: any = await getProviderSeries(p.id)
    providerSeries.value = res?.data?.series ?? res?.series ?? []
  } catch {
    providerSeries.value = []
  }
}

async function applyProviderFilter() {
  if (!modelTarget.value) return
  filteringModels.value = true
  try {
    const body: Record<string, unknown> = {}
    if (selectedSeries.value.length > 0) {
      body.providers = selectedSeries.value
    }
    if (selectedModalities.value.length > 0) {
      body.input_modalities = selectedModalities.value
    }
    if (filterFreeOnly.value) {
      body.is_free = true
    }
    const res: any = await filterProviderModels(modelTarget.value.id, body as any)
    filteredResultModels.value = res?.data?.models ?? res?.models ?? []
    filterApplied.value = true
    if (filteredResultModels.value.length === 0 && res?.data?.message) {
      message.info(res.data.message)
    }
  } catch {
    filteredResultModels.value = []
    filterApplied.value = true
    message.error(t('model.discoverFailed'))
  } finally {
    filteringModels.value = false
  }
}

async function addFilteredModel(m: FilteredProviderModel) {
  if (!modelTarget.value) return
  try {
    await ensureProvider(modelTarget.value)
    await updateProvider(modelTarget.value.id, {
      config: { add_model: m.id, add_model_name: m.name },
    })
    message.success(t('common.success'))
    filteredResultModels.value = filteredResultModels.value.filter((x) => x.id !== m.id)
    const mapped = mapModel(
      {
        id: m.id,
        name: m.name,
        provider_id: modelTarget.value.id,
        capabilities: m.capabilities,
        is_free: m.is_free,
        pricing: m.pricing,
        context_window: m.context_window,
        max_tokens: m.max_tokens,
        tags: ['user-added'],
      },
      modelTarget.value.id,
    )
    const exists = allModels.value.some(
      (x) => x.id === m.id && x.provider_id === modelTarget.value!.id,
    )
    if (!exists) {
      allModels.value.push(mapped)
    }
    const live = providers.value.find((p) => p.id === modelTarget.value!.id)
    if (live) {
      live.models = live.models.filter((mm) => mm.id !== m.id)
      live.models.push(mapped)
      live.model_count = live.models.length
    }
  } catch {
    message.error(t('common.error'))
  }
}

async function deleteModel(m: ModelItem) {
  try {
    await apiDeleteModel(m.id)
    message.success(t('common.success'))
    if (modelTarget.value) {
      const live = providers.value.find((p) => p.id === modelTarget.value!.id)
      if (live) {
        live.models = live.models.filter((mm) => mm.id !== m.id)
        live.model_count = live.models.length
      }
    }
    allModels.value = allModels.value.filter((mm) => mm.id !== m.id)
  } catch {
    message.error(t('common.error'))
  }
}

function startEditModel(m: ModelItem) {
  editingModel.value = m
  editModelId.value = m.id
  editModelName.value = m.name
}

function cancelEditModel() {
  editingModel.value = null
  editModelId.value = ''
  editModelName.value = ''
}

async function saveEditedModel() {
  if (!editingModel.value) return
  const target = editingModel.value
  const newId = editModelId.value.trim()
  const newName = editModelName.value.trim()
  if (!newId) return
  // 前端去重:改 ID 不得与相同服务商下其他条目冲突
  const dup = allModels.value.some(
    (mm) => mm.id === newId && mm !== target && mm.provider_id === target.provider_id,
  )
  if (dup) {
    message.warning(t('model.modelAlreadyExists', { name: newId }))
    return
  }
  savingEdit.value = true
  try {
    await updateModel(target.id, { id: newId, name: newName || newId, provider_id: target.provider_id })
    message.success(t('common.success'))
    const oldId = target.id
    target.id = newId
    target.name = newName || newId
    const live = providers.value.find((p) => p.id === target.provider_id)
    if (live) {
      const idx = live.models.findIndex((mm) => mm.id === oldId)
      if (idx >= 0) live.models[idx] = { ...target }
    }
    const allIdx = allModels.value.findIndex((mm) => mm.id === oldId && mm.provider_id === target.provider_id)
    if (allIdx >= 0) allModels.value[allIdx] = { ...target }
    cancelEditModel()
  } catch {
    message.error(t('common.error'))
  } finally {
    savingEdit.value = false
  }
}

async function addNewModel() {
  if (!newModelId.value.trim() || !modelTarget.value) return
  const modelId = newModelId.value.trim()
  // 前端去重：检查该服务商下是否已存在相同 model ID
  const exists = allModels.value.some(
    (m) => m.id === modelId && (m.provider_id === modelTarget.value!.id || m.provider_id === modelTarget.value!.name),
  )
  if (exists) {
    message.warning(t('model.modelAlreadyExists', { name: modelId }))
    return
  }
  addingModel.value = true
  try {
    const modelName = newModelName.value.trim() || modelId
    await ensureProvider(modelTarget.value)
    await updateProvider(modelTarget.value.id, {
      config: { add_model: modelId, add_model_name: modelName },
    })
    message.success(t('common.success'))
    const newModel: ModelItem = {
      id: modelId,
      name: modelName,
      provider_id: modelTarget.value.id,
      type: 'text',
      tags: ['user-added'],
      enabled: true,
      capabilities: ['text'],
      is_active: false,
    }
    modelTarget.value.models.unshift(newModel)
    modelTarget.value.model_count++
    allModels.value.unshift(newModel)
    const live = providers.value.find((p) => p.id === modelTarget.value!.id)
    if (live) {
      live.models.unshift(newModel)
      live.model_count++
    }
    newModelId.value = ''
    newModelName.value = ''
    addModelExpanded.value = false
  } catch {
    message.error(t('common.error'))
  } finally {
    addingModel.value = false
  }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(async () => {
  providerSearch.value = ''
  console.log('[ModelPage] onMounted start')
  await fetchProviders()
  console.log('[ModelPage] after fetchProviders:', providers.value.length, 'providers')
  await fetchModels()
  console.log('[ModelPage] after fetchModels:', providers.value.length, 'providers,', allModels.value.length, 'models')
  await fetchActiveModel()
  console.log('[ModelPage] after fetchActiveModel:', providers.value.length, 'providers')
  await fetchDefaultConfig()
  console.log('[ModelPage] after fetchDefaultConfig:', providers.value.length, 'providers, done')
})

watch(() => defaultConfig.provider_id, () => {
  defaultConfig.model_id = ''
})
</script>

<style scoped>
.nr-model-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ======================== Header ======================== */
.nr-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.nr-header-label {
  font-size: 15px;
  font-weight: 700;
  color: var(--nr-text-primary);
  font-family: var(--nr-font-display);
  white-space: nowrap;
}
.nr-header-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.nr-model-subtitle {
  font-size: 11px;
  color: var(--nr-text-muted);
  margin-left: 4px;
}
.nr-model-active-tag {
  font-size: 9px;
  font-weight: 700;
  padding: 0 4px;
  border-radius: 3px;
  background: rgba(34, 197, 94, 0.15);
  color: var(--nr-success);
  text-transform: uppercase;
}

/* ======================== Toolbar ======================== */
.nr-providers-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.nr-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.nr-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.nr-search-box {
  position: relative;
  width: 240px;
}
.nr-search-input {
  width: 100%;
  height: 36px;
  padding: 0 12px 0 34px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  color: var(--nr-text-primary);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s;
}
.nr-search-input:focus { border-color: var(--nr-primary); }
.nr-search-input::placeholder { color: var(--nr-text-muted); }
.nr-search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 13px;
  pointer-events: none;
}

/* ======================== Grid ======================== */
.nr-providers-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
/* Override GlassPanel overflow:hidden → clip to keep border-radius while not clipping content */
.nr-providers-grid :deep(.nr-glass-panel) {
  overflow: clip !important;
}

/* ======================== Provider Card ======================== */
.nr-pv-card {
  display: flex;
  flex-direction: column;
  transition: border-color 0.2s;
}
.nr-pv-card.st-available { border-left: 3px solid var(--nr-success); }
.nr-pv-card.st-unavailable { border-left: 3px solid var(--nr-error); }
.nr-pv-card.st-not_ready { border-left: 3px solid var(--nr-warning); }
.nr-pv-card.st-not_configured { border-left: 3px solid var(--nr-text-tertiary); }

.nr-pv-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 5px 0 10px;
  padding-left: 20px;
}
.nr-pv-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 20px;
  font-weight: 700;
  flex-shrink: 0;
  overflow: hidden;
}
.nr-pv-icon-img {
  width: 24px;
  height: 24px;
  object-fit: contain;
}
.nr-pv-status {
  display: flex; align-items: center; gap: 6px; margin-bottom: 10px; padding: 0 2px 0 30px;
}
.nr-pv-status-text { font-size: 13px; }
.nr-pv-status-text.st-available { color: var(--nr-success); }
.nr-pv-status-text.st-unavailable { color: var(--nr-error); }
.nr-pv-status-text.st-not_ready { color: var(--nr-warning); }
.nr-pv-status-text.st-not_configured { color: var(--nr-text-tertiary); }

.nr-pv-title {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.nr-pv-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--nr-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  overflow: hidden;
  text-overflow: ellipsis;
}
.nr-pv-badge {
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 4px;
  width: fit-content;
  letter-spacing: 0.02em;
}
.nr-pv-badge.local { background: rgba(139, 92, 246, 0.12); color: var(--nr-accent-secondary); }
.nr-pv-badge.free { background: rgba(34, 197, 94, 0.1); color: var(--nr-success); }
.nr-pv-badge.paid { background: rgba(99, 102, 241, 0.1); color: var(--nr-primary-light); }

.nr-pv-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
}
.nr-pv-dot.available { background: var(--nr-success); }
.nr-pv-dot.unavailable { background: var(--nr-error); }
.nr-pv-dot.not_ready { background: var(--nr-warning); }
.nr-pv-dot.not_configured { background: var(--nr-text-tertiary); }

/* Card body */
.nr-pv-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 18px 12px 30px;
}
.nr-pv-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  overflow: hidden;
}
.nr-pv-label {
  font-size: 11px;
  color: var(--nr-text-muted);
  width: 60px;
  flex-shrink: 0;
}
.nr-pv-val {
  font-size: 13px;
  color: var(--nr-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.nr-pv-val.mono { font-family: var(--nr-font-mono); }
.nr-pv-val.muted { color: var(--nr-text-muted); font-style: italic; }

/* Icon buttons (eye, save) */
.nr-icon-btn {
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 6px;
  background: var(--nr-glass-bg);
  cursor: pointer;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.15s;
}
.nr-icon-btn:hover { background: rgba(255, 255, 255, 0.08); }
.nr-icon-btn.tiny { width: 22px; height: 22px; font-size: 11px; }
.nr-icon-btn.nr-save-sm { color: var(--nr-primary); font-weight: 700; font-size: 14px; }

/* Inline API key input */
.nr-inline-key {
  display: flex;
  align-items: center;
  gap: 5px;
  flex: 1;
  min-width: 0;
}
.nr-inline-key-input {
  flex: 1;
  height: 26px;
  padding: 0 8px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.04);
  color: var(--nr-text-primary);
  font-size: 12px;
  font-family: var(--nr-font-mono);
  outline: none;
  min-width: 0;
}
.nr-inline-key-input:focus { border-color: var(--nr-primary); }
.nr-inline-key-save {
  padding: 0 10px;
  height: 26px;
  border: none;
  border-radius: 6px;
  background: var(--nr-primary);
  color: white;
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}

/* Card actions */
.nr-pv-actions {
  display: flex;
  gap: 8px;
  padding: 12px 18px 12px 30px;
  border-top: 1px solid var(--nr-glass-border);
}
.nr-action-btn {
  padding: 2px 14px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 8px;
  background: var(--nr-glass-bg);
  color: var(--nr-text-secondary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}
.nr-action-btn:hover { background: var(--nr-glass-bg-hover); color: var(--nr-text-primary); border-color: var(--nr-glass-border-hover); }
.nr-action-btn.primary { background: var(--nr-primary); color: white; border-color: var(--nr-primary); }
.nr-action-btn.primary:hover { opacity: 0.9; }
.nr-action-btn.danger { color: var(--nr-error); border-color: var(--nr-error); }
.nr-action-btn.danger:hover { background: rgba(239, 68, 68, 0.12); }

/* Loading state */
.nr-loading {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 60px 0;
}

/* Empty state */
.nr-empty {
  text-align: center;
  padding: 60px 0;
  color: var(--nr-text-muted);
}
.nr-empty-icon { font-size: 32px; display: block; margin-bottom: 12px; }

/* ======================== Modals (Teleported) ======================== */
.nr-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(8px) saturate(120%);
  -webkit-backdrop-filter: blur(8px) saturate(120%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.nr-modal {
  background: linear-gradient(145deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.015) 50%, rgba(255,255,255,0.03) 100%);
  backdrop-filter: blur(var(--nr-glass-blur)) saturate(180%);
  -webkit-backdrop-filter: blur(var(--nr-glass-blur)) saturate(180%);
  border: 1px solid var(--nr-glass-border);
  border-radius: var(--nr-radius-xl, 20px);
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.5), inset 0 0.5px 0 rgba(255,255,255,0.1), inset 0 -0.5px 0 rgba(255,255,255,0.03);
  max-height: 90vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.nr-modal-wide { width: 680px; }
.nr-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--nr-glass-border);
  font-size: 15px;
  font-weight: 600;
  color: var(--nr-text-primary);
  font-family: var(--nr-font-display);
  background: linear-gradient(180deg, rgba(255,255,255,0.02) 0%, transparent 100%);
}
.nr-close {
  width: 30px;
  height: 30px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: var(--nr-glass-bg);
  backdrop-filter: blur(10px);
  color: var(--nr-text-secondary);
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}
.nr-close:hover { background: var(--nr-glass-bg-hover); border-color: var(--nr-glass-border); }
.nr-modal-body {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.nr-modal-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  border-top: 1px solid var(--nr-glass-border);
  gap: 12px;
  background: linear-gradient(0deg, rgba(255,255,255,0.015) 0%, transparent 100%);
}
.nr-modal-foot-right {
  display: flex;
  gap: 8px;
}

/* Form fields */
.nr-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.nr-field label {
  font-size: 13px;
  font-weight: 500;
  color: var(--nr-text-primary);
}
.req { color: var(--nr-error); }
.nr-hint {
  font-size: 11px;
  color: var(--nr-text-muted);
  line-height: 1.4;
}
.nr-hint-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.nr-link-btn {
  font-size: 12px;
  color: var(--nr-primary);
  cursor: pointer;
  font-weight: 500;
}
.nr-link-btn:hover { text-decoration: underline; }

.nr-input {
  width: 100%;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  backdrop-filter: blur(10px);
  color: var(--nr-text-primary);
  font-size: 13px;
  outline: none;
  transition: all 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}
.nr-input:focus {
  border-color: var(--nr-primary);
  background: rgba(99, 102, 241, 0.06);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.nr-select {
  width: 100%;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  color: var(--nr-text-primary);
  font-size: 13px;
  outline: none;
}

/* Radio group */
.nr-radio-group {
  display: flex;
  gap: 10px;
}
.nr-radio {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--nr-text-secondary);
  transition: all 0.15s;
}
.nr-radio input { display: none; }
.nr-radio.active {
  border-color: var(--nr-primary);
  background: rgba(99, 102, 241, 0.06);
  color: var(--nr-text-primary);
}

/* Header rows */
.nr-header-row { /* inside advanced config */ }
.nr-header-row .nr-input { flex: 1; }
.nr-remove-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: rgba(239, 68, 68, 0.12);
  color: var(--nr-error);
  cursor: pointer;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

/* JSON editor */
.nr-json-editor {
  width: 100%;
  padding: 12px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.3);
  color: var(--nr-text-primary);
  font-family: var(--nr-font-mono);
  font-size: 12px;
  line-height: 1.5;
  resize: vertical;
  outline: none;
}
.nr-json-editor:focus { border-color: var(--nr-primary); }

/* Advanced config */
.nr-advanced {
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
  overflow: hidden;
}
.nr-advanced-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  cursor: pointer;
  color: var(--nr-text-secondary);
  font-size: 13px;
  font-weight: 500;
  transition: background 0.15s;
}
.nr-advanced-toggle:hover { background: rgba(255, 255, 255, 0.03); }
.nr-advanced-body {
  padding: 12px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ======================== Model Management ======================== */
.nr-mgmt-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.nr-mgmt-search {
  flex: 1;
  position: relative;
}
.nr-search-input-pad {
  padding-left: 34px;
}
.nr-mgmt-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 380px;
  overflow-y: auto;
}
.nr-mgmt-empty {
  text-align: center;
  color: var(--nr-text-muted);
  padding: 40px 0;
  font-size: 14px;
}
.nr-mgmt-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 8px;
  border-radius: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
  transition: background 0.15s;
}
.nr-mgmt-item:hover { background: rgba(255, 255, 255, 0.02); }
.nr-mgmt-item.active { background: rgba(99, 102, 241, 0.06); border-color: rgba(99, 102, 241, 0.12); }
.nr-mgmt-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nr-mgmt-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.nr-mgmt-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--nr-text-primary);
}
.nr-mgmt-active-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(34, 197, 94, 0.12);
  color: var(--nr-success);
}
.nr-mgmt-id {
  font-size: 11px;
  color: var(--nr-text-muted);
  font-family: var(--nr-font-mono);
}
.nr-mgmt-caps {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 2px;
}
.nr-cap-tag {
  font-size: 9px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  background: rgba(139, 92, 246, 0.1);
  color: var(--nr-accent-secondary);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.nr-mgmt-tags {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}
.nr-mgmt-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}
.nr-mgmt-tag.user-added { background: rgba(59, 130, 246, 0.12); color: #3b82f6; }
.nr-mgmt-tag.free { background: rgba(34, 197, 94, 0.1); color: #22c55e; }
.nr-mgmt-tag.builtin { background: rgba(34, 197, 94, 0.1); color: #22c55e; }
.nr-mgmt-actions {
  display: flex;
  gap: 4px;
}
.nr-mgmt-act {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.04);
  cursor: pointer;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s;
}
.nr-mgmt-act:hover { background: rgba(255, 255, 255, 0.08); }
.nr-mgmt-act.is-active { color: #22c55e; background: rgba(34, 197, 94, 0.08); }
.nr-mgmt-act.danger:hover { background: rgba(239, 68, 68, 0.12); }

/* Add model row */
.nr-mgmt-add {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}
.nr-mgmt-add-btn {
  flex-shrink: 0;
  padding-bottom: 2px;
}

/* ======================== Model Management (Redesigned — Liquid Glass) ======================== */
.nr-mm-body {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.nr-mm-search {
  display: flex;
  align-items: center;
  gap: 10px;
  position: relative;
  padding: 6px;
  border-radius: 12px;
  background: var(--nr-glass-bg);
  border: 1px solid var(--nr-glass-border);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}
.nr-mm-search-icon {
  position: absolute;
  left: 16px;
  top: 50%;
  transform: translateY(-50%);
  width: 15px;
  height: 15px;
  color: var(--nr-text-tertiary);
  pointer-events: none;
}
.nr-mm-search-input {
  flex: 1;
  height: 32px;
  padding: 0 12px 0 34px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--nr-text-primary);
  font-size: 13px;
  outline: none;
}
.nr-mm-search-input::placeholder { color: var(--nr-text-muted); }
.nr-mm-search-clear {
  background: none; border: none; cursor: pointer;
  color: var(--nr-text-muted); font-size: 18px; line-height: 1;
  padding: 0 2px; transition: color 0.2s;
}
/* 个人配置范围提示(非管理员) */
.nr-scope-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 10px 4px;
  font-size: 12px;
  color: var(--nr-text-secondary, #8a8a92);
}

.nr-mm-search-clear:hover { color: var(--nr-text-primary); }

/* 模型筛选面板(OpenRouter) */
.nr-mm-filter {
  padding: 0 12px 4px;
}

.nr-mm-filter-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  font-size: 12px;
  color: var(--nr-text-secondary, #8a8a92);
  background: transparent;
  border: 1px solid rgba(127, 127, 127, 0.25);
  border-radius: 6px;
  cursor: pointer;
  transition: color 0.2s, border-color 0.2s;
}

.nr-mm-filter-toggle:hover {
  color: var(--nr-accent, #5b8def);
  border-color: var(--nr-accent, #5b8def);
}

.nr-mm-filter-panel {
  margin-top: 8px;
  padding: 10px 12px;
  background: rgba(127, 127, 127, 0.06);
  border: 1px solid rgba(127, 127, 127, 0.15);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.nr-mm-filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.nr-mm-filter-label {
  font-size: 12px;
  color: var(--nr-text-secondary, #8a8a92);
  white-space: nowrap;
  min-width: 88px;
}

.nr-mm-series-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}

.nr-mm-series-pill {
  padding: 2px 9px;
  font-size: 11px;
  color: var(--nr-text-primary, #d6d6de);
  background: transparent;
  border: 1px solid rgba(127, 127, 127, 0.25);
  border-radius: 999px;
  cursor: pointer;
}

.nr-mm-series-pill.active {
  color: #fff;
  background: var(--nr-accent, #5b8def);
  border-color: var(--nr-accent, #5b8def);
}

.nr-mm-filter-hint {
  font-size: 11px;
  color: rgba(127, 127, 127, 0.7);
}

.nr-mm-filter-free {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--nr-text-primary, #d6d6de);
  cursor: pointer;
}

.nr-mm-filter-actions {
  display: flex;
  justify-content: flex-end;
}

.nr-mm-filter-results {
  border-top: 1px solid rgba(127, 127, 127, 0.15);
  padding-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nr-mm-filter-results-title {
  font-size: 12px;
  color: var(--nr-text-secondary, #8a8a92);
}

.nr-mm-btn-submit {
  padding: 3px 10px;
  font-size: 12px;
  color: #fff;
  background: var(--nr-accent, #5b8def);
  border: none;
  border-radius: 6px;
  cursor: pointer;
}

.nr-mm-btn-submit:hover {
  opacity: 0.88;
}

.nr-mm-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 400px;
  overflow-y: auto;
  padding: 4px;
  border-radius: var(--nr-radius-lg, 16px);
  background: rgba(255, 255, 255, 0.015);
  border: 1px solid var(--nr-border-light);
}
.nr-mm-empty {
  text-align: center;
  color: var(--nr-text-muted);
  padding: 40px 0;
  font-size: 14px;
}
.nr-mm-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 12px;
  border-radius: 12px;
  border: 1px solid transparent;
  transition: all 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}
.nr-mm-item:hover {
  background: var(--nr-glass-bg-hover);
  border-color: var(--nr-glass-border);
}
.nr-mm-item.is-active {
  background: rgba(99, 102, 241, 0.06);
  border-color: rgba(99, 102, 241, 0.15);
  box-shadow: 0 0 16px rgba(99, 102, 241, 0.06);
}

.nr-mm-item-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.nr-mm-item-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.nr-mm-item-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--nr-text-primary);
  font-family: var(--nr-font-display);
}
.nr-mm-active-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--nr-success);
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.4);
  flex-shrink: 0;
}
.nr-mm-item-id {
  font-size: 11px;
  color: var(--nr-text-muted);
  font-family: var(--nr-font-mono);
}
.nr-mm-item-caps {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 3px;
}
.nr-mm-cap {
  font-size: 9px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 4px;
  background: rgba(139, 92, 246, 0.1);
  border: 1px solid rgba(139, 92, 246, 0.12);
  color: var(--nr-accent-secondary);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.nr-mm-item-tags {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}
.nr-mm-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid transparent;
}
.nr-mm-tag-text { background: rgba(148, 163, 184, 0.08); border-color: rgba(148, 163, 184, 0.1); color: #94a3b8; }
.nr-mm-tag-user { background: rgba(59, 130, 246, 0.1); border-color: rgba(59, 130, 246, 0.12); color: var(--nr-info); }
.nr-mm-tag-free { background: rgba(34, 197, 94, 0.08); border-color: rgba(34, 197, 94, 0.1); color: var(--nr-success); }
.nr-mm-tag-builtin { background: rgba(34, 197, 94, 0.08); border-color: rgba(34, 197, 94, 0.1); color: var(--nr-success); }

.nr-mm-item-actions {
  display: flex;
  gap: 4px;
}
.nr-mm-icon-btn {
  width: 30px;
  height: 30px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: var(--nr-glass-bg);
  backdrop-filter: blur(8px);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.25s cubic-bezier(0.22, 1, 0.36, 1);
  color: var(--nr-text-secondary);
}
.nr-mm-icon-btn svg { width: 14px; height: 14px; }
.nr-mm-icon-btn:hover {
  background: var(--nr-glass-bg-hover);
  border-color: var(--nr-glass-border);
  color: var(--nr-text-primary);
}
.nr-mm-icon-danger:hover {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.15);
  color: var(--nr-error);
}

/* Add model section */
.nr-mm-add-section {
  padding-top: 14px;
  border-top: 1px solid var(--nr-glass-border);
}
.nr-mm-add-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 14px 18px;
  border: 1.5px dashed var(--nr-glass-border-hover);
  border-radius: var(--nr-radius-lg, 16px);
  background: var(--nr-glass-bg);
  backdrop-filter: blur(10px);
  color: var(--nr-text-secondary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.22, 1, 0.36, 1);
}
.nr-mm-add-trigger svg { width: 16px; height: 16px; flex-shrink: 0; }
.nr-mm-add-trigger:hover {
  border-color: var(--nr-primary);
  border-style: solid;
  color: var(--nr-text-primary);
  background: rgba(99, 102, 241, 0.06);
  box-shadow: 0 0 20px rgba(99, 102, 241, 0.08);
}

.nr-mm-add-form {
  border: 1.5px solid var(--nr-glass-border-hover);
  border-radius: var(--nr-radius-lg, 16px);
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: linear-gradient(145deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.01) 100%);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow: inset 0 0.5px 0 rgba(255,255,255,0.06);
}
.nr-mm-add-fields {
  display: flex;
  gap: 12px;
}
.nr-mm-add-field {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.nr-mm-add-field label {
  font-size: 13px;
  font-weight: 500;
  color: var(--nr-text-primary);
}
.nr-mm-add-buttons {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}
.nr-mm-btn-cancel {
  padding: 7px 20px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 10px;
  background: var(--nr-glass-bg);
  backdrop-filter: blur(8px);
  color: var(--nr-text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}
.nr-mm-btn-cancel:hover {
  background: var(--nr-glass-bg-hover);
  border-color: var(--nr-glass-border-hover);
  color: var(--nr-text-primary);
}
.nr-mm-btn-submit {
  padding: 7px 20px;
  border: none;
  border-radius: 10px;
  background: var(--nr-gradient-primary);
  color: white;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.25), inset 0 1px 0 rgba(255,255,255,0.15);
  transition: all 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}
.nr-mm-btn-submit:hover {
  box-shadow: 0 6px 24px rgba(99, 102, 241, 0.35), inset 0 1px 0 rgba(255,255,255,0.15);
}
.nr-mm-btn-submit:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

/* Header rows in advanced config */
.nr-header-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* Model option in select */
.nr-model-option {
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
