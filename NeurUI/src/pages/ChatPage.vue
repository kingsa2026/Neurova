<template>
  <div
    class="nr-chat-page"
    :class="{ 'nr-chat-page--main': isMainLayout }"
    @dragenter.prevent="onDragEnter"
    @dragover.prevent="onDragOver"
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <!-- Drag & Drop Overlay -->
    <transition name="fade-scale">
      <div v-if="isDragOver" class="nr-drop-overlay">
        <div class="nr-drop-overlay-content">
          <span class="nr-drop-icon">📂</span>
          <span class="nr-drop-text">{{ t('chat.dropFiles') }}</span>
        </div>
      </div>
    </transition>

    <!-- Left Sidebar: Sessions -->
    <aside v-if="!isMainLayout" class="nr-chat-sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="nr-sidebar-header">
        <GlassButton variant="primary" size="md" style="flex: 1" @click="createSession">
          + {{ t('chat.newChat') }}
        </GlassButton>
      </div>

      <div class="nr-sidebar-search">
        <GlassInput
          v-model:model-value="searchQuery"
          :placeholder="t('common.search')"
          @update:model-value="searchQuery = $event"
        />
        <button class="nr-msg-search-open" :title="t('chat.searchInSession')" @click="openMsgSearch">🔍</button>
      </div>

      <div class="nr-session-list">
        <div
          v-for="session in filteredSessions"
          :key="session.id"
          class="nr-session-item"
          :class="{ active: session.id === currentSessionId }"
          @click="switchSession(session.id)"
        >
          <span class="nr-session-icon">💬</span>
          <span class="nr-session-name">{{ session.pinned ? '📌 ' : '' }}{{ session.title }}</span>
          <a-dropdown :trigger="['click']" @click.stop>
            <span class="nr-session-menu-btn" @click.stop>⋯</span>
            <template #overlay>
              <a-menu>
                <a-menu-item @click="renameSession(session.id)">
                  {{ t('chat.rename') }}
                </a-menu-item>
                <a-menu-item @click="togglePin(session)">
                  {{ session.pinned ? t('chat.unpin') : t('chat.pin') }}
                </a-menu-item>
                <a-menu-item @click="archiveSession(session.id)">
                  {{ t('chat.archive') }}
                </a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </div>
        <div v-if="filteredSessions.length === 0" class="nr-session-empty">
          {{ t('chat.noSessions') }}
        </div>
      </div>
    </aside>

    <!-- Main Chat Area -->
    <main class="nr-chat-main">
      <!-- Page Header (when inside MainLayout) -->
      <div v-if="isMainLayout" class="nr-chat-page-header">
        <div class="nr-chat-header-left">
          <a-dropdown :trigger="['click']" placement="bottomLeft">
            <button class="nr-chat-session-select">
              <span class="nr-chat-session-select-icon">💬</span>
              <span class="nr-chat-session-select-name">{{ currentSessionTitle || t('chat.noSessions') }}</span>
              <span class="nr-chat-session-select-arrow">▾</span>
            </button>
            <template #overlay>
              <div class="nr-glass-dropdown">
                <div class="nr-glass-dropdown-item" style="font-weight:600; color: var(--nr-text-primary);" @click="createSession">
                  + {{ t('chat.newChat') }}
                </div>
                <div class="nr-glass-dropdown-divider" />
                <div
                  v-for="s in filteredSessions"
                  :key="s.id"
                  class="nr-glass-dropdown-item"
                  :class="{ 'is-active': s.id === currentSessionId }"
                  @click="switchSession(s.id)"
                >
                  <span>{{ s.title }}</span>
                </div>
                <div v-if="filteredSessions.length === 0" class="nr-glass-dropdown-item" style="opacity:0.5">
                  {{ t('common.noData') }}
                </div>
              </div>
            </template>
          </a-dropdown>
        </div>
        <div class="nr-chat-header-actions">
          <!-- 思考程度：简单 / 标准 / 深度 -->
          <div class="nr-thinking-seg" :title="t('chat.thinkingEffort')">
            <button
              v-for="opt in thinkingOptions"
              :key="opt.value"
              class="nr-thinking-opt"
              :class="{ active: thinkingEffort === opt.value }"
              @click="setThinkingEffort(opt.value)"
            >
              {{ t(opt.label) }}
            </button>
          </div>
          <a-select
            v-model:value="selectedModel"
            class="nr-chat-model-select"
            :options="chatModelOptions"
            :loading="chatModelLoading"
            :title="t('agent.model')"
            size="small"
          />
          <button
            class="nr-chat-toggle-btn"
            :class="{ 'cu-active': computerPanelState.open }"
            :title="t('computerPanel.title')"
            @click="toggleComputerPanel"
          >
            🖥
          </button>
          <button class="nr-chat-toggle-btn" @click="historyPanelOpen = !historyPanelOpen" :title="t('chat.history')">
            {{ historyPanelOpen ? '›' : '‹' }}
          </button>
        </div>
      </div>
      <!-- Message List -->
      <!-- 会话内消息搜索（补课 B） -->
      <div v-if="msgSearchOpen" class="nr-msg-search">
        <input
          v-model="msgSearchQuery"
          class="nr-msg-search-input"
          :placeholder="t('chat.searchInSession')"
          @keydown.enter.prevent
        />
        <span class="nr-msg-search-count">
          {{ msgSearchQuery.trim() ? t('chat.searchMatches', { n: msgSearchHits.length }) : '' }}
        </span>
        <button class="nr-msg-search-btn" :disabled="msgSearchHits.length === 0" @click="jumpToMatch(-1)">↑</button>
        <button class="nr-msg-search-btn" :disabled="msgSearchHits.length === 0" @click="jumpToMatch(1)">↓</button>
        <button class="nr-msg-search-btn" @click="msgSearchOpen = false">✕</button>
      </div>

      <div class="nr-chat-messages" ref="messagesRef">
        <div v-if="messages.length === 0" class="nr-chat-empty">
          <div v-if="isMainLayout && !agentId" class="nr-chat-empty">
            <div class="nr-chat-empty-icon">💬</div>
            <h3>{{ t('nav.chat') }}</h3>
            <p>{{ t('chat.selectAgentFirst') }}</p>
          </div>
          <div v-else class="nr-chat-empty">
            <div class="nr-chat-empty-icon">🤖</div>
            <h3>{{ currentAgent?.name || t('agent.title') }}</h3>
            <p>{{ t('chat.placeholder') }}</p>
          </div>
        </div>

        <div
          v-for="(msg, idx) in messages"
          :id="`nr-msg-${idx}`"
          :key="idx"
          class="nr-msg"
          :class="[`nr-msg--${msg.role}`, { 'nr-msg--hit': msgSearchHits.includes(idx) && idx === msgSearchCursor }]"
        >
          <div class="nr-msg-avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
          <div class="nr-msg-body">
            <!-- Reasoning / Thinking Block -->
            <div v-if="msg.reasoning" class="nr-msg-reasoning">
              <div class="nr-reasoning-header" @click="msg.reasoningOpen = !msg.reasoningOpen">
                <span>💭 {{ t('chat.reasoning') }}</span>
                <span class="nr-reasoning-toggle">{{ msg.reasoningOpen ? '▾' : '▸' }}</span>
              </div>
              <div v-show="msg.reasoningOpen" class="nr-reasoning-content">
                {{ msg.reasoning }}
              </div>
            </div>

            <!-- Tool Call Block (collapsible, supports multi-round) -->
            <template v-if="msg.toolCalls && msg.toolCalls.length > 0">
              <div v-for="(tc, tcIdx) in msg.toolCalls" :key="tcIdx" class="nr-msg-tool-call">
                <div class="nr-tool-header" @click="msg.toolOpen = !msg.toolOpen">
                  <span class="nr-tool-icon">{{ variantIcon(toolCardVariant(tc.name)) }}</span>
                  <span class="nr-tool-name">{{ tc.name }}</span>
                  <a-tag :color="isBackgroundResult(tc.result) ? 'warning' : tc.result ? 'success' : 'processing'">
                    {{ isBackgroundResult(tc.result) ? t('chat.toolBackground') : tc.result ? t('chat.toolDone') : t('chat.toolCalling') }}
                  </a-tag>
                  <span class="nr-tool-toggle">{{ msg.toolOpen ? '▾' : '▸' }}</span>
                </div>
                <div v-show="msg.toolOpen">
                  <pre class="nr-tool-args">{{ formatJSON(tc.arguments) }}</pre>
                  <div v-if="isBackgroundResult(tc.result)" class="nr-tool-background">
                    {{ t('chat.toolBackgroundHint') }}
                  </div>
                  <div v-if="tc.result" class="nr-tool-result">
                    <div class="nr-tool-result-header">{{ t('chat.toolResult') }}</div>
                    <pre class="nr-tool-result-content">{{ tc.result }}</pre>
                  </div>
                </div>
              </div>
            </template>
            <!-- Legacy single tool call (backward compat) -->
            <div v-else-if="msg.toolCall" class="nr-msg-tool-call">
              <div class="nr-tool-header" @click="msg.toolOpen = !msg.toolOpen">
                <span class="nr-tool-icon">{{ variantIcon(toolCardVariant(msg.toolCall.name)) }}</span>
                <span class="nr-tool-name">{{ msg.toolCall.name }}</span>
                <a-tag :color="msg.toolResult ? 'success' : variantColor(toolCardVariant(msg.toolCall.name))">
                  {{ msg.toolResult ? t('chat.toolDone') : t('chat.toolCalling') }}
                </a-tag>
                <span class="nr-tool-toggle">{{ msg.toolOpen ? '▾' : '▸' }}</span>
              </div>
              <div v-show="msg.toolOpen">
                <pre class="nr-tool-args">{{ formatJSON(msg.toolCall.arguments) }}</pre>
                <div v-if="msg.toolResult" class="nr-tool-result">
                  <div class="nr-tool-result-header">{{ t('chat.toolResult') }}</div>
                  <pre class="nr-tool-result-content">{{ msg.toolResult }}</pre>
                </div>
              </div>
            </div>

            <!-- Edit mode（编辑最后一条用户消息）：内联编辑框替换消息内容 -->
            <div v-if="isEditingMessage(idx)" class="nr-msg-edit">
              <textarea
                v-model="editDraft"
                class="nr-msg-edit-textarea"
                rows="3"
                @keydown.enter.exact.prevent="confirmEditMessage"
                @keydown.esc.prevent="cancelEditMessage"
              />
              <div class="nr-msg-edit-actions">
                <button
                  class="nr-edit-btn nr-edit-btn--primary"
                  :disabled="isStreaming || !editDraft.trim()"
                  @click="confirmEditMessage"
                >
                  {{ t('chat.editResend') }}
                </button>
                <button class="nr-edit-btn" @click="cancelEditMessage">
                  {{ t('common.cancel') }}
                </button>
              </div>
            </div>

            <!-- Message Content (Rich Media Rendering) -->
            <div
              v-else-if="msg.content"
              class="nr-msg-content"
              v-html="renderRichContent(msg.content)"
              @click="handleContentClick"
            />

            <!-- File Attachments (Enhanced) -->
            <div v-if="msg.attachments?.length" class="nr-msg-attachments">
              <div
                v-for="(file, fi) in msg.attachments"
                :key="fi"
                class="nr-attachment-thumb"
                :class="`nr-attachment--${getFileCategory(file.type)}`"
                @click="file.type?.startsWith('image/') && openLightbox(file.preview!, file.name)"
              >
                <img
                  v-if="file.type?.startsWith('image/')"
                  :src="file.preview"
                  :alt="file.name"
                  class="nr-attachment-img"
                />
                <span v-else class="nr-attachment-file-icon">{{ getFileIcon(file.type) }}</span>
                <div class="nr-attachment-info">
                  <span class="nr-attachment-name">{{ file.name }}</span>
                  <span v-if="file.size" class="nr-attachment-size">{{ formatFileSize(file.size) }}</span>
                </div>
              </div>
            </div>

            <!-- Custom Audio Player for TTS -->
            <div v-if="msg.audioUrl" class="nr-msg-audio-player">
              <div class="nr-audio-player">
                <button
                  class="nr-audio-play-btn"
                  @click="toggleAudioPlay(msg)"
                >
                  {{ msg.audioPlaying ? '⏸' : '▶' }}
                </button>
                <div class="nr-audio-progress-wrap" @click="seekAudio(msg, $event)">
                  <div class="nr-audio-progress-bar">
                    <div
                      class="nr-audio-progress-fill"
                      :style="{ width: (msg.audioProgress || 0) + '%' }"
                    />
                  </div>
                </div>
                <span class="nr-audio-time">{{ formatAudioTime(msg.audioCurrentTime || 0) }}</span>
                <button class="nr-audio-speed-btn" @click="cycleAudioSpeed(msg)">
                  {{ msg.audioSpeed || 1 }}x
                </button>
              </div>
              <!-- Hidden audio element -->
              <audio
                :ref="(el) => setAudioRef(msg, el as HTMLAudioElement)"
                :src="msg.audioUrl"
                preload="metadata"
                @timeupdate="onAudioTimeUpdate(msg)"
                @loadedmetadata="onAudioLoaded(msg)"
                @ended="onAudioEnded(msg)"
              />
            </div>

            <!-- TTS Action for assistant messages -->
            <div
              v-if="msg.role === 'assistant' && !msg.streaming && msg.content && !msg.audioUrl && ttsAvailable"
              class="nr-msg-tts-action"
            >
              <button class="nr-tts-btn" @click="synthesizeTTS(msg)" :disabled="msg.ttsLoading">
                {{ msg.ttsLoading ? '⏳' : '🔊' }}
                <span>{{ msg.ttsLoading ? t('chat.ttsLoading') : t('chat.playTTS') }}</span>
              </button>
            </div>

            <!-- Message footer: 时间 + 操作条（复制 / 点赞点踩 / 编辑 / 删除轮次） -->
            <div v-if="!msg.streaming && !isEditingMessage(idx)" class="nr-msg-footer">
              <span v-if="displayTime(msg)" class="nr-msg-time">{{ displayTime(msg) }}</span>
              <span class="nr-msg-footer-spacer" />
              <button class="nr-msg-action" :title="t('chat.copy')" @click="copyMessage(msg)">⧉</button>
              <template v-if="msg.role === 'assistant'">
                <button
                  class="nr-msg-action"
                  :class="{ 'nr-msg-action--active': msg.feedback === 'like' }"
                  :title="t('chat.like')"
                  @click="rateReply(msg, 'like')"
                >👍</button>
                <button
                  class="nr-msg-action"
                  :class="{ 'nr-msg-action--active-negative': msg.feedback === 'dislike' }"
                  :title="t('chat.dislike')"
                  @click="rateReply(msg, 'dislike')"
                >👎</button>
              </template>
              <template v-else>
                <button
                  v-if="isLastUserMessage(idx)"
                  class="nr-msg-action"
                  :title="t('chat.editMessage')"
                  @click="startEditMessage(idx)"
                >✎</button>
              </template>
              <a-popconfirm
                v-if="msg.role === 'user'"
                :title="t('chat.deleteRoundConfirm')"
                :ok-text="t('common.confirm')"
                :cancel-text="t('common.cancel')"
                @confirm="deleteRoundAt(idx)"
              >
                <button class="nr-msg-action nr-msg-action--danger" :title="t('chat.deleteRound')">🗑</button>
              </a-popconfirm>
            </div>

            <!-- Streaming indicator -->
            <div v-if="msg.streaming" class="nr-msg-streaming">
              <span class="nr-typing-dot" /><span class="nr-typing-dot" /><span class="nr-typing-dot" />
            </div>
          </div>
        </div>
      </div>

      <!-- Input Area -->
      <div class="nr-chat-input-area">
        <!-- Attachment previews -->
        <div v-if="pendingFiles.length > 0" class="nr-pending-files">
          <div v-for="(file, i) in pendingFiles" :key="i" class="nr-pending-file">
            <img v-if="file.preview" :src="file.preview" :alt="file.name" />
            <span v-else class="nr-pending-file-icon">{{ getFileIcon(file.type) }}</span>
            <div class="nr-pending-file-info">
              <span class="nr-pending-file-name">{{ file.name }}</span>
              <span class="nr-pending-file-size">{{ formatFileSize(file.file.size) }}</span>
            </div>
            <button class="nr-pending-file-remove" @click="removePendingFile(i)">×</button>
          </div>
        </div>

        <!-- ASR Recording Indicator -->
        <transition name="fade-slide">
          <div v-if="isRecording" class="nr-recording-bar">
            <div class="nr-recording-dot" />
            <span class="nr-recording-label">{{ t('chat.recording') }}</span>
            <div class="nr-recording-wave">
              <span v-for="n in 12" :key="n" class="nr-wave-bar" :style="{ animationDelay: `${n * 0.08}s` }" />
            </div>
            <span class="nr-recording-time">{{ recordingTimeStr }}</span>
            <button class="nr-recording-cancel" @click="cancelRecording">{{ t('common.cancel') }}</button>
          </div>
        </transition>

        <!-- 实时记忆检索进度（临时态：回复开始即消失，不落消息历史） -->
        <div v-if="retrievalStatus" class="nr-retrieval-status">
          <span class="nr-retrieval-spinner">⟳</span>
          <span>{{ retrievalStatus }}</span>
        </div>
        <div class="nr-input-row">
          <input
            ref="fileInputRef"
            type="file"
            multiple
            accept="image/*,audio/*,video/*,.pdf,.doc,.docx,.txt,.csv,.json,.py,.js,.ts,.vue,.html,.css,.md"
            style="display: none"
            @change="handleFileSelect"
          />
          <GlassButton variant="ghost" size="md" @click="fileInputRef?.click()" :title="t('chat.upload')">
            📎
          </GlassButton>
          <!-- ASR Voice Button -->
          <GlassButton
            v-if="asrAvailable"
            variant="ghost"
            size="md"
            :class="{ 'nr-voice-active': isRecording }"
            @click="toggleRecording"
            :title="t('chat.voice')"
          >
            {{ isRecording ? '🔴' : '🎙️' }}
          </GlassButton>
          <textarea
            ref="textareaRef"
            v-model="inputText"
            class="nr-chat-textarea"
            :placeholder="isRecording ? t('chat.recording') : t('chat.placeholder')"
            rows="1"
            @compositionstart="onCompositionStart"
            @compositionend="onCompositionEnd"
            @keydown="handleKeydown"
            @input="autoResize"
            @paste="handlePaste"
          />
      <!-- 429 限流横幅（补课 A1）：一键切换备选模型 -->
      <div v-if="rateLimitBanner" class="nr-rate-limit-banner">
        <span class="nr-rate-limit-text">
          ⚠ {{ t('chat.rateLimited', { model: rateLimitBanner.model || t('ui.autoRoute') }) }}
        </span>
        <div class="nr-rate-limit-alts">
          <button
            v-for="alt in rateLimitBanner.alternatives.slice(0, 3)"
            :key="alt.value"
            class="nr-rate-limit-alt"
            @click="switchAfterRateLimit(alt.value)"
          >
            {{ alt.label }}
          </button>
        </div>
        <button class="nr-rate-limit-dismiss" @click="rateLimitBanner = null">✕</button>
      </div>

      <!-- 消息队列提示（补课 P3-b）：流式中的排队发送 -->
      <div v-if="messageQueue.items.length > 0" class="nr-msg-queue">
        <span class="nr-msg-queue-count">
          {{ t('chat.queued', { n: messageQueue.pendingCount }) }}
        </span>
        <button
          v-for="qi in messageQueue.items"
          :key="qi.id"
          class="nr-msg-queue-item"
          :title="qi.status === 'failed' ? qi.error : qi.text"
          @click="messageQueue.retry(qi.id) && drainMessageQueue()"
        >
          <span class="nr-msg-queue-text">{{ qi.text.slice(0, 40) }}</span>
          <span class="nr-msg-queue-status" :class="qi.status">{{ qi.status }}</span>
        </button>
        <button class="nr-msg-queue-clear" @click="messageQueue.clear()">
          {{ t('common.clear') }}
        </button>
      </div>

          <GlassButton
            v-if="isStreaming"
            variant="danger"
            size="md"
            @click="stopStreaming"
          >
            {{ t('chat.stop') }}
          </GlassButton>
          <GlassButton
            v-else
            variant="primary"
            size="md"
            :disabled="!inputText.trim() && pendingFiles.length === 0"
            @click="sendMessage"
          >
            {{ t('chat.send') }}
          </GlassButton>
        </div>
      </div>

      <!-- 蜂群子 Agent 对话小窗（右下角堆叠，可最小化） -->
      <div class="subagent-window-stack">
        <SubAgentPanel
          v-for="win in subAgentWindows"
          :key="win.subagentId"
          :state="win"
          @close="closeSubAgentWindow"
        />
      </div>
    </main>

    <!-- 电脑操作分屏（Agent 使用电脑/浏览器工具时自动展开，ZCode 式跟随） -->
    <ComputerUsePanel
      v-if="computerPanelState.open"
      :state="computerPanelState"
      :agent-id="agentId"
      @close="closeComputerPanel"
    />

    <!-- Right Panel: Conversation History (main layout mode) -->
    <aside v-if="isMainLayout && agentId && historyPanelOpen" class="nr-chat-history-panel">
      <div class="nr-history-header">
        <GlassButton variant="primary" size="sm" @click="createSession">+ {{ t('chat.newChat') }}</GlassButton>
        <GlassButton
          variant="ghost"
          size="sm"
          :class="{ 'is-active': archivedPanelOpen }"
          @click="toggleArchivedPanel"
        >
          🗂 {{ t('chat.archivedSessions') }}
        </GlassButton>
      </div>
      <div class="nr-history-search">
        <GlassInput
          v-model:model-value="searchQuery"
          :placeholder="t('common.search')"
          @update:model-value="searchQuery = $event"
        />
      </div>
      <div class="nr-session-list">
        <div
          v-for="session in filteredSessions"
          :key="session.id"
          class="nr-session-item"
          :class="{ active: session.id === currentSessionId }"
          @click="switchSession(session.id)"
        >
          <span class="nr-session-icon">💬</span>
          <span class="nr-session-name">{{ session.title }}</span>
          <a-dropdown :trigger="['click']" @click.stop>
            <span class="nr-session-menu-btn" @click.stop>⋯</span>
            <template #overlay>
              <a-menu>
                <a-menu-item @click="renameSession(session.id)">
                  {{ t('chat.rename') }}
                </a-menu-item>
                <a-menu-item @click="archiveSession(session.id)">
                  {{ t('chat.archive') }}
                </a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </div>
        <div v-if="filteredSessions.length === 0" class="nr-session-empty">
          {{ t('chat.noSessions') }}
        </div>
      </div>
    </aside>

    <!-- Right Panel: Archived Sessions (存档会话卡片页，位于历史会话右侧) -->
    <aside v-if="isMainLayout && agentId && archivedPanelOpen" class="nr-chat-archived-panel">
      <div class="nr-history-header">
        <span class="nr-history-title">{{ t('chat.archivedSessions') }}</span>
        <button class="nr-archived-close" @click="archivedPanelOpen = false">✕</button>
      </div>
      <div class="nr-session-list">
        <div v-for="session in archivedSessions" :key="session.id" class="nr-session-item archived">
          <span class="nr-session-icon">🗄</span>
          <span class="nr-session-name">{{ session.title }}</span>
          <button class="nr-archived-restore-btn" @click="restoreArchivedSession(session.id)">
            {{ t('chat.restore') }}
          </button>
        </div>
        <div v-if="archivedSessions.length === 0" class="nr-session-empty">
          {{ t('chat.noArchivedSessions') }}
        </div>
      </div>
    </aside>

    <!-- Image Lightbox -->
    <transition name="fade-scale">
      <div v-if="lightbox.open" class="nr-lightbox" @click="lightbox.open = false">
        <div class="nr-lightbox-content" @click.stop>
          <img :src="lightbox.src" :alt="lightbox.alt" />
          <div class="nr-lightbox-caption">{{ lightbox.alt }}</div>
        </div>
        <button class="nr-lightbox-close" @click="lightbox.open = false">✕</button>
      </div>
    </transition>

    <!-- Rename Modal -->
    <a-modal
      v-model:open="renameModal.open"
      :title="t('chat.rename')"
      @ok="confirmRename"
    >
      <GlassInput
        v-model:model-value="renameModal.title"
        :placeholder="t('chat.rename')"
        @update:model-value="renameModal.title = $event"
      />
    </a-modal>

    <!-- Governance Approval Modal (P0: ASK 人工确认) -->
    <a-modal
      v-model:open="approvalModal.open"
      :title="t('ui.confirmNeeded')"
      :confirm-loading="approvalModal.loading"
      :ok-text="t('ui.approveExecute')"
      :cancel-text="t('ui.reject')"
      @ok="confirmApproval"
      @cancel="rejectApproval"
    >
      <div class="approval-body">
        <div class="approval-field">
          <span class="approval-label">{{ t('ui.tool') }}</span>
          <a-tag color="orange">{{ approvalModal.toolName || t('ui.unknown') }}</a-tag>
        </div>
        <div v-if="approvalModal.command" class="approval-field">
          <span class="approval-label">{{ t('ui.content') }}</span>
          <pre class="approval-command">{{ approvalModal.command }}</pre>
        </div>
        <div v-if="approvalModal.reason" class="approval-field">
          <span class="approval-label">{{ t('ui.reason') }}</span>
          <span class="approval-reason">{{ approvalModal.reason }}</span>
        </div>
        <a-checkbox v-model:checked="approvalAddWhitelist">
          {{ t('ui.addToWhitelistAndApprove') }}
        </a-checkbox>
        <a-radio-group v-model:value="approvalRemember" class="approval-remember" size="small">
          <a-radio value="">{{ t('ui.rememberNone') }}</a-radio>
          <a-radio value="exact">{{ t('ui.rememberExact') }}</a-radio>
          <a-radio value="similar">{{ t('ui.rememberSimilar') }}</a-radio>
        </a-radio-group>
        <p class="approval-hint">{{ t('ui.approvalHint') }}</p>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { useAgentPage } from '@/composables/useAgentPage'
import { useASRRestartGuard } from '@/composables/useASRRestartGuard'
import { useAppStore } from '@/stores/app'
import { useChatStore } from '@/stores/chat'
import { useMessageQueueStore } from '@/stores/messageQueue'
import { useRouter } from 'vue-router'
import { useChat } from '@/composables/useChat'
import type { ChatMessage, Session, PendingFile } from '@/types/chat'
import { api } from '@/api'
import {
  approveRequest as apiApproveRequest,
  rejectRequest as apiRejectRequest,
  addWhitelistEntry,
} from '@/api/modules/governance'
import { secureStorage } from '@/utils/security'
import { renderMarkdown } from '@/utils/markdown'
import { uiMessage } from '@/utils/message'
import { resolveI18nMessage } from '@/utils/i18n'
import GlassButton from '@/components/GlassButton.vue'
import GlassInput from '@/components/GlassInput.vue'
import SubAgentPanel, { type SubAgentWindowState } from '@/components/chat/SubAgentPanel.vue'
import ComputerUsePanel from '@/components/chat/ComputerUsePanel.vue'
import { useComputerPanel, isComputerTool, } from '@/composables/useComputerPanel'
import { toolCardVariant, variantIcon, variantColor } from '@/utils/toolCardVariant'
import { useThinkingEffort } from '@/composables/useThinkingEffort'
import { useMermaidRenderer } from '@/composables/useMermaidRenderer'
import { useChatDraft } from '@/composables/useChatDraft'
import { useInputHistory } from '@/composables/useInputHistory'
import { useIMEComposition } from '@/composables/useIMEComposition'
import { isBackgroundResult } from '@/utils/toolCallStatus'
import { findMessageMatches } from '@/utils/messageSearch'
import type { ThinkingEffort } from '@/composables/useThinkingEffort'
import { useSessionSync } from '@/composables/useSessionSync'
import { listModels } from '@/api/modules/models'
import { normalizeModel } from '@/types/model'

/** 聊天页可切换的模型选项（空串 = 自动路由） */
interface ChatModelOption {
  label: string
  value: string
  provider_id: string
}

const { t } = useI18n()
const appStore = useAppStore()
const { agentId, currentAgent } = useAgentPage()

const props = defineProps<{
  layoutMode?: 'chat' | 'main'
}>()

const isMainLayout = computed(() => props.layoutMode === 'main')

// ---------------------------------------------------------------------------
// Store-backed domain state (single source of truth via Pinia)
// #2 / ADR 0008: ChatPage 不再持有领域状态,统一由 useChatStore 管理。
// sessions/currentSessionId/messages/isStreaming/inputText/searchQuery 通过
// storeToRefs 解构为本地 ref(保持响应性 + 模板兼容),所有 mutation 走 store actions。
// ---------------------------------------------------------------------------
const chatStore = useChatStore()
const messageQueue = useMessageQueueStore()
const router = useRouter()
const {
  messages,
  sessions,
  archivedSessions,
  currentSessionId,
  inputText,
  searchQuery,
  isStreaming,
  currentSessionTitle,
  filteredSessions,
} = storeToRefs(chatStore)

// ---------------------------------------------------------------------------
// Local UI state (UI concerns, not domain state)
// ---------------------------------------------------------------------------
const messagesRef = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

const pendingFiles = ref<PendingFile[]>([])
// 实时记忆检索进度（SSE memory_progress；临时态：不落消息历史，回复开始即清空）
const retrievalStatus = ref('')
const sidebarCollapsed = computed(() => appStore.sidebarCollapsed)
const historyPanelOpen = ref(true)

// ---------------------------------------------------------------------------
// 思考程度（简单/标准/深度）：持久化于 localStorage，随消息发给后端
// ---------------------------------------------------------------------------
const { effort: thinkingEffort, setEffort: setThinkingEffort } = useThinkingEffort()
const thinkingOptions: Array<{ value: ThinkingEffort; label: string }> = [
  { value: 'light', label: 'chat.thinkingLight' },
  { value: 'standard', label: 'chat.thinkingStandard' },
  { value: 'deep', label: 'chat.thinkingDeep' },
]

// ---------------------------------------------------------------------------
// 蜂群子 Agent 小窗：订阅会话 WS 事件（subagent_started/chunk/completed），
// 每个子 Agent 一个可最小化的浮动小窗
// ---------------------------------------------------------------------------
const subAgentWindows = ref<Record<string, SubAgentWindowState>>({})

function onSessionSyncEvent(event: { event_type: string; payload: Record<string, unknown> }) {
  // 电脑操作实时事件 → 分屏面板（不携带 subagent_id，先于子 Agent 分支处理）
  if (event.event_type === 'computer_action') {
    computerPanel.handleComputerAction(event.payload)
    return
  }
  const p = event.payload as Record<string, string>
  const sid = p?.subagent_id
  if (!sid) return
  if (event.event_type === 'subagent_started') {
    subAgentWindows.value[sid] = {
      subagentId: sid,
      agentName: p.agent_name || sid,
      task: p.task || '',
      chunks: [],
      status: 'running',
      report: '',
    }
  } else if (event.event_type === 'subagent_chunk') {
    const win = subAgentWindows.value[sid]
    if (win && p.data !== undefined) {
      win.chunks.push({ type: String(p.chunk_type || 'content'), data: String(p.data) })
    }
  } else if (event.event_type === 'subagent_completed') {
    const win = subAgentWindows.value[sid]
    if (win) {
      win.status = (p.status as SubAgentWindowState['status']) || 'completed'
      win.report = String(p.report || '')
      win.error = p.error || null
    }
  }
}

function closeSubAgentWindow(subagentId: string) {
  delete subAgentWindows.value[subagentId]
}

// ---------------------------------------------------------------------------
// 电脑操作分屏：Agent 调用 computer_*/browser_* 工具时自动展开，
// 实时显示操作截图与动作日志（WS computer_action 事件驱动）
// ---------------------------------------------------------------------------
const computerPanel = useComputerPanel()
const computerPanelState = computerPanel.state

function toggleComputerPanel() {
  if (computerPanelState.open) {
    computerPanel.close()
  } else {
    computerPanel.open()
  }
}

function closeComputerPanel() {
  computerPanel.close()
}

useSessionSync(() => currentSessionId.value, onSessionSyncEvent)

// Drag & Drop
const isDragOver = ref(false)
let dragCounter = 0

// ASR
const asrAvailable = ref(false)
const isRecording = ref(false)
const recordingTimeStr = ref('0:00')
let recognition: any = null
// Guard against infinite ASR auto-restart when the recognizer keeps dying.
const asrRestartGuard = useASRRestartGuard(3)
let recordingTimer: ReturnType<typeof setInterval> | null = null
let recordingSeconds = 0
// Timer for the delayed ASR restart (breaks tight onend→start loops)
let asrRestartTimer: ReturnType<typeof setTimeout> | null = null

// MediaRecorder for backend ASR fallback
let mediaRecorder: MediaRecorder | null = null
let recordedChunks: Blob[] = []

// TTS
const ttsAvailable = ref(true) // assume available, verify on mount

// Lightbox
const lightbox = reactive({ open: false, src: '', alt: '' })

const renameModal = reactive({ open: false, sessionId: '', title: '' })

// 治理审批弹窗（P0: ASK 人工确认）
const approvalModal = reactive({
  open: false,
  loading: false,
  approvalId: '',
  toolName: '',
  command: '',
  reason: '',
})
const approvalAddWhitelist = ref(false)
/** 审批记忆档位：'' = 仅本次 / exact / similar（补课 3.2，后端 approval_manager 记忆规则） */
const approvalRemember = ref<'' | 'exact' | 'similar'>('')

// ---------------------------------------------------------------------------
// 手动模型切换（聊天页右上角）
// 空串'' = 自动路由（默认，不影响富媒体→多模态 LLM 的自动路由）
// 非空 = 手动指定模型，随消息 POST body 的 model 字段转发到后端热切换
const chatModelOptions = ref<ChatModelOption[]>([])
// 补课 A1：429 限流横幅——当前轮被限流的模型 + 一键切换候选列表
const rateLimitBanner = ref<{ model: string; alternatives: ChatModelOption[] } | null>(null)
// 补课 A2：无已启用模型提示（自动路由将无人可派）——引导去模型管理页
const noModelsHint = ref(false)
const selectedModel = ref<string>('')
const chatModelLoading = ref(false)

async function loadChatModels() {
  chatModelLoading.value = true
  try {
    const modelsRes = await listModels()
    const rawModels = Array.isArray(modelsRes) ? modelsRes : modelsRes?.models ?? []
    const normalized = rawModels.map((m) => normalizeModel(m))
    // 只展示已启用（可用）的模型，避免用户选到不可用的模型
    const enabled = normalized.filter((m) => m.enabled !== false)
    const AUTO_ROUTE_LABEL = t('ui.autoRoute')
    const options: ChatModelOption[] = [
      { label: AUTO_ROUTE_LABEL, value: '', provider_id: '' },
      ...enabled.map((m) => ({
        label: `${m.name || m.id}${m.is_active ? ' ●' : ''}`,
        value: m.id || m.name,
        provider_id: m.provider_id || '',
      })),
    ]
    chatModelOptions.value = options
    // 补课 A2：列表拉取成功但零已启用模型 → 自动路由无候选可派，提示配置
    noModelsHint.value = enabled.length === 0
  } catch (e) {
    // 加载失败不阻塞聊天，保留"自动路由"选项即可
    console.warn('[ChatPage] failed to load model list:', e)
    chatModelOptions.value = []
  } finally {
    chatModelLoading.value = false
  }
}

let abortController: AbortController | null = null

// ---------------------------------------------------------------------------
// Session Management (delegated to useChat composable)
// #2 / ADR 0008: 所有 session CRUD 通过 useChat 统一函数调用库,禁止直接调后端 API。
// 5 个 session 函数(load/create/switch/delete/rename)委托给 useChat,
// 本地仅保留"无参模板适配 + UI 副作用(scrollToBottom / modal)"包装。
// ---------------------------------------------------------------------------
const {
  loadSessions: _loadSessions,
  createSession: _createSession,
  switchSession: _switchSession,
  deleteSession: _deleteSession,
  renameSession: _renameSession,
  pinSession: _pinSession,
  // 存档操作：删除 → 存档（历史列表隐藏，存档卡片页可随时恢复）
  archiveSession: _archiveSession,
  loadArchivedSessions: _loadArchivedSessions,
  restoreSession: _restoreSession,
  // 轮次操作：删除一轮（编辑覆写复用）/ 点赞点踩反馈
  deleteRound: _deleteRound,
  sendFeedback: _sendFeedback,
  // 用户主动调用 switchSession / deleteSession 失败时弹 toast 的错误策略 helper
  // (#2 / ADR 0008 函数调用库契约的一部分 — switchSession / deleteSession 本身
  //  不弹 toast, 调用方按需调 notifySwitchFailure / notifyDeleteFailure;
  //  副作用调用方如 loadSessions/createSession 不调).
  notifySwitchFailure: _notifySwitchFailure,
  notifyDeleteFailure: _notifyDeleteFailure,
  loadingSessions,
  switchingSession,
} = useChat({
  // 修复 chat.loadHistoryFailed toast 异常显示 bug:
  // 旧契约 `t(key) || fallback` 在 vue-i18n 缺失 key 时不工作 —
  // vue-i18n Composition API (legacy: false) 在缺失 key 时返回 key 字符串
  // 本身 (truthy), 导致 `|| fallback` 短路求值不触发, toast 显示 raw key.
  // resolveI18nMessage 用 `t(key) === key` 检测缺失翻译信号, 缺失时返回 fallback.
  // 详见 docs/bugfix-delete-session-userid-mismatch.md "i18n fallback resolver" 小节.
  errorMessage: (key, fallback) => resolveI18nMessage(t, key, fallback),
  onError: (msg) => uiMessage.error(msg),
})

/** 加载当前 agent 的 session 列表(模板 onMounted / agentId watch 调用)。 */
async function loadSessions(): Promise<void> {
  await _loadSessions(agentId.value)
}

/** 创建新会话(模板按钮无参调用),委托给 useChat.createSession。 */
async function createSession(): Promise<void> {
  await _createSession(agentId.value, t('chat.newChat'))
}

/**
 * 切换会话 (用户主动点击侧栏 session 项):
 *   1. 调 useChat.switchSession — 返回 SwitchResult (不弹 toast)
 *   2. 用户主动场景 → 调 notifySwitchFailure,历史加载失败时弹 toast
 *   3. 补充 scrollToBottom UI 副作用 (历史加载后滚到底部)
 *
 * 注: loadSessions/createSession/deleteSession 内部自动切换不弹 toast
 * (副作用场景), 不调 notifySwitchFailure — 详见 useChat.ts 的 silent 契约.
 */
async function switchSession(sessionId: string): Promise<void> {
  const result = await _switchSession(sessionId)
  _notifySwitchFailure(result)
  // 补课 D：恢复新会话草稿
  chatStore.setInputText(chatDraft.restore(sessionId))
  scrollToBottom()
}

/** 打开重命名 modal(只读取 sessions,不调 API)。 */
function renameSession(sessionId: string): void {
  const session = sessions.value.find((s) => s.id === sessionId)
  if (!session) return
  renameModal.sessionId = sessionId
  renameModal.title = session.title
  renameModal.open = true
}

/** 确认重命名(modal @ok),委托给 useChat.renameSession。 */
async function confirmRename(): Promise<void> {
  if (!renameModal.title.trim()) return
  const ok = await _renameSession(renameModal.sessionId, renameModal.title.trim())
  if (ok) renameModal.open = false
}

// ---------------------------------------------------------------------------
// Governance Approval (P0: ASK 人工确认)
// ---------------------------------------------------------------------------

/** 批准执行；勾选白名单时先加入免检列表再批准 */
async function confirmApproval(): Promise<void> {
  if (!approvalModal.approvalId || approvalModal.loading) return
  approvalModal.loading = true
  try {
    if (approvalAddWhitelist.value) {
      const pattern = extractWhitelistPattern(approvalModal.command)
      if (pattern) {
        await addWhitelistEntry({
          pattern,
          match_type: 'prefix',
          note: t('ui.approvalNote', { id: approvalModal.approvalId }),
        })
      }
    }
    const resp = await apiApproveRequest(
      approvalModal.approvalId,
      t('ui.userConfirmed'),
      approvalRemember.value || undefined,
    )
    approvalModal.open = false
    approvalRemember.value = ''
    const data = (resp as any)?.data?.data ?? (resp as any)?.data
    if (data?.executed && data?.result) {
      uiMessage.success(t('ui.approvedExecuted'))
    } else {
      uiMessage.success(t('ui.approved'))
    }
  } catch (e) {
    console.error('[Approval] approve failed:', e)
    uiMessage.error(t('ui.approveFailed'))
  } finally {
    approvalModal.loading = false
  }
}

/** 拒绝执行 */
async function rejectApproval(): Promise<void> {
  if (!approvalModal.approvalId || approvalModal.loading) return
  approvalModal.loading = true
  try {
    await apiRejectRequest(approvalModal.approvalId, t('ui.userRejected'))
    approvalModal.open = false
    approvalRemember.value = ''
    uiMessage.info(t('ui.rejectedOperation'))
  } catch (e) {
    console.error('[Approval] reject failed:', e)
    uiMessage.error(t('ui.operationFailed'))
  } finally {
    approvalModal.loading = false
  }
}

/** 从命令中提取适合加入白名单的前缀（首个词或可执行文件名） */
function extractWhitelistPattern(command: string): string {
  const trimmed = (command || '').trim()
  if (!trimmed) return ''
  // 取第一段管道/分号之前的内容的首个 token 作为前缀
  const head = trimmed.split(/[|;&]/)[0].trim()
  return head.split(/\s+/)[0] || head
}

/** 删除会话,委托给 useChat.deleteSession; 失败时弹 toast 让用户感知. */
async function deleteSession(sessionId: string): Promise<void> {
  const result = await _deleteSession(sessionId)
  _notifyDeleteFailure(result)
}

// ---------------------------------------------------------------------------
// 会话存档（删除 → 存档：历史列表隐藏，存档卡片页可随时恢复）
// ---------------------------------------------------------------------------
const archivedPanelOpen = ref(false)

/** 置顶/取消置顶（模板菜单无参调用；静默失败不打断列表交互）。 */
async function togglePin(session: Session): Promise<void> {
  const ok = await _pinSession(session.id, !session.pinned)
  if (!ok) {
    uiMessage.error(resolveI18nMessage(t, 'chat.pinFailed', t('chat.pinFailed')))
  }
}

/** 存档会话（模板菜单无参调用），失败弹 toast（错误策略与 deleteSession wrapper 一致）。 */
async function archiveSession(sessionId: string): Promise<void> {
  const result = await _archiveSession(sessionId)
  if (!result.ok) {
    uiMessage.error(resolveI18nMessage(t, 'chat.archiveFailed', t('chat.archiveFailed')))
  }
}

/** 打开/关闭存档卡片页，打开时加载当前 agent 的存档会话列表。 */
async function toggleArchivedPanel(): Promise<void> {
  archivedPanelOpen.value = !archivedPanelOpen.value
  if (archivedPanelOpen.value) {
    await _loadArchivedSessions(agentId.value)
  }
}

/** 恢复存档会话为正常会话。 */
async function restoreArchivedSession(sessionId: string): Promise<void> {
  const result = await _restoreSession(sessionId)
  if (!result.ok) {
    uiMessage.error(resolveI18nMessage(t, 'chat.restoreFailed', t('chat.restoreFailed')))
  }
}

// ---------------------------------------------------------------------------
// 轮次操作：时间显示 / 复制 / 点赞点踩 / 编辑最后一条用户消息 / 删除一轮
// ---------------------------------------------------------------------------

const editIndex = ref<number>(-1)
const editDraft = ref('')

function isEditingMessage(idx: number): boolean {
  return editIndex.value === idx
}

/** 最后一条用户消息 = 其后没有其他 user 消息（编辑按钮只出现在它上面） */
function isLastUserMessage(idx: number): boolean {
  return (
    messages.value[idx]?.role === 'user' &&
    !messages.value.slice(idx + 1).some((m) => m.role === 'user')
  )
}

const _pad2 = (n: number) => String(n).padStart(2, '0')

/** 消息时间展示：今天 → HH:mm；同年 → MM-DD HH:mm；跨年 → YYYY-MM-DD HH:mm */
function formatMsgTime(ts?: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const hm = `${_pad2(d.getHours())}:${_pad2(d.getMinutes())}`
  if (d.getFullYear() !== now.getFullYear()) {
    return `${d.getFullYear()}-${_pad2(d.getMonth() + 1)}-${_pad2(d.getDate())} ${hm}`
  }
  if (d.toDateString() === now.toDateString()) return hm
  return `${_pad2(d.getMonth() + 1)}-${_pad2(d.getDate())} ${hm}`
}

/** 展示时间：用户 = 发送时刻；assistant = 回复完成时刻（回退轮次时间） */
function displayTime(msg: ChatMessage): string {
  return formatMsgTime(msg.role === 'assistant' ? msg.repliedAt || msg.timestamp : msg.timestamp)
}

async function copyMessage(msg: ChatMessage): Promise<void> {
  const text = msg.content || ''
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    uiMessage.success(t('chat.copied'))
  } catch {
    // 非安全上下文（如 http 局域网部署）无 clipboard API，回退 execCommand
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      uiMessage.success(t('chat.copied'))
    } catch {
      uiMessage.error(t('chat.copyFailed'))
    }
  }
}

/** 点赞/点踩（可切换/取消）：乐观更新本地，失败回滚 */
async function rateReply(msg: ChatMessage, fb: 'like' | 'dislike'): Promise<void> {
  if (!currentSessionId.value || !msg.timestamp || isStreaming.value) return
  const prev = msg.feedback
  const next = prev === fb ? null : fb
  msg.feedback = next ?? undefined
  const ok = await _sendFeedback(currentSessionId.value, msg.timestamp, next)
  if (!ok) msg.feedback = prev
}

function startEditMessage(idx: number): void {
  if (isStreaming.value) return
  const msg = messages.value[idx]
  if (!msg || msg.role !== 'user') return
  editIndex.value = idx
  editDraft.value = msg.content
}

function cancelEditMessage(): void {
  editIndex.value = -1
  editDraft.value = ''
}

/**
 * 确认编辑并重发（覆写旧轮）：
 * 1. deleteRound 删除旧轮 — 后端清 session 记录 + 该轮记忆 + agent 内存历史
 * 2. 本地 removeRoundFrom 移除旧轮消息
 * 3. 新文本走 sendMessage() 原链路 — 管线写入新轮 session 记录与新记忆
 * （删除+重发 = 覆写：不复制发送逻辑，session/上下文/记忆由既有链路保证一致）
 */
async function confirmEditMessage(): Promise<void> {
  const idx = editIndex.value
  const msg = messages.value[idx]
  const newText = editDraft.value.trim()
  if (!msg || msg.role !== 'user' || !newText || isStreaming.value) return
  if (!agentId.value || !currentSessionId.value) {
    uiMessage.error(t('chat.selectAgentFirst'))
    return
  }
  if (!msg.timestamp) {
    uiMessage.error(t('chat.deleteRoundFailed'))
    cancelEditMessage()
    return
  }
  const result = await _deleteRound(currentSessionId.value, msg.timestamp)
  if (!result.ok) {
    uiMessage.error(t('chat.deleteRoundFailed'))
    return
  }
  chatStore.removeRoundFrom(idx)
  cancelEditMessage()
  chatStore.setInputText(newText)
  await sendMessage()
}

/** 删除一轮记录（模板 popconfirm 确认后调用） */
async function deleteRoundAt(idx: number): Promise<void> {
  const msg = messages.value[idx]
  if (!msg || msg.role !== 'user' || isStreaming.value || !currentSessionId.value) return
  if (!msg.timestamp) {
    uiMessage.error(t('chat.deleteRoundFailed'))
    return
  }
  const result = await _deleteRound(currentSessionId.value, msg.timestamp)
  if (!result.ok) {
    uiMessage.error(t('chat.deleteRoundFailed'))
    return
  }
  chatStore.removeRoundFrom(idx)
}

// ---------------------------------------------------------------------------
// Message Sending with SSE Streaming
// ---------------------------------------------------------------------------
/**
 * 429 限流识别与横幅（补课 A1）：错误文本含 429/rate limit 措辞时，
 * 从已启用模型列表（排除当前选中）生成备选候选，弹出横幅一键切换。
 * 非限流错误返回 false 走原有错误路径。
 */
function handleRateLimit(err: any): boolean {
  const msg = String(err?.message || '')
  if (!/429|rate.?limit|too many requests|限流|请求过于频繁/i.test(msg)) return false
  const current = selectedModel.value || ''
  const alternatives = chatModelOptions.value.filter(
    (o) => o.value && o.value !== current,
  )
  rateLimitBanner.value = { model: current, alternatives }
  return true
}

/** 横幅一键切换：选定备选模型后关闭横幅（用户重发即走新模型）。 */
function switchAfterRateLimit(modelValue: string): void {
  selectedModel.value = modelValue
  rateLimitBanner.value = null
  uiMessage.success(t('chat.rateLimitSwitched'))
}

/**
 * 队列续发（补课 P3-b）：当前轮 done 后取下一条 pending 发送。
 * 递归经由 sendMessage → 流式 finally → drainMessageQueue 链自然排空。
 * markSending/markSent 失败说明状态竞争（如用户手动移除）——静默跳过。
 */
const _draining = ref(false)
async function drainMessageQueue(): Promise<void> {
  if (_draining.value || messageQueue.paused) return
  const item = messageQueue.next()
  if (!item) return
  _draining.value = true
  try {
    if (!messageQueue.markSending(item.id)) return
    chatStore.setInputText(item.text)
    try {
      await sendMessage()
      messageQueue.markSent(item.id)
    } catch (err: any) {
      messageQueue.markFailed(item.id, err?.message || 'send failed')
    }
  } finally {
    _draining.value = false
  }
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text && pendingFiles.value.length === 0) return
  // 补课 P3-b：流式中再次发送 → 入队（纯文本轮；附件轮保持丢弃语义，
  // 避免队列项携带上传会话）。done 后 drainMessageQueue 自动续发。
  if (isStreaming.value) {
    if (text && pendingFiles.value.length === 0 && agentId.value) {
      messageQueue.enqueue(text)
      chatStore.setInputText('')
      uiMessage.info(t('chat.queued', { n: messageQueue.pendingCount }))
    }
    return
  }
  if (!agentId.value) return
  // 补课 A2：零可用模型时提示（QP 模型未配 Result 提示对齐）——
  // 只拦自动路由且无任何已启用模型的场景；用户已手动选模型则放行
  if (!selectedModel.value && noModelsHint.value) {
    uiMessage.warning(t('chat.noModelsConfigured'))
    router.push({ path: '/models' })
    return
  }

  // Stop any active ASR recording
  if (isRecording.value) stopRecording()

  // 补课 C：发送即记录输入历史（↑↓ 回溯用）
  recordInputHistory(text)

  // Build user message
  // timestamp 同时是轮次定位键：随 client_timestamp 发给后端持久化到
  // 该轮消息 metadata（服务端 add_message 用自己的 now 落盘，客户端
  // 时间戳不落盘会导致编辑/删除/反馈无法定位实时轮次）
  const roundTimestamp = new Date().toISOString()
  const userMsg: ChatMessage = {
    role: 'user',
    content: text,
    timestamp: roundTimestamp,
    attachments: pendingFiles.value.map((f) => ({
      name: f.name,
      type: f.type,
      preview: f.preview,
      size: f.file.size,
    })),
  }
  chatStore.addMessage(userMsg)

  // Prepare assistant placeholder
  // assistant.timestamp = 所在轮的用户发送时刻（轮次定位键，点赞点踩用）
  const assistantMsg: ChatMessage = {
    role: 'assistant',
    content: '',
    reasoning: '',
    reasoningOpen: false,
    toolCalls: [],
    toolOpen: false,
    streaming: true,
    timestamp: roundTimestamp,
  }
  // 必须使用 store 返回的 proxy 引用继续写入（R-1 修复）：
  // 沿用原始引用会绕过 Vue 响应式代理，SSE 事件不触发依赖收集，
  // 思考/正文会等到组件下次整帧重渲染才一次性出现（无法逐字显示）。
  const streamingMsg = chatStore.addMessage(assistantMsg)

  chatStore.setInputText('')
  const filesToUpload = [...pendingFiles.value]
  pendingFiles.value = []
  chatStore.setStreaming(true)
  scrollToBottom()

  // Upload files first if any
  const fileIds: string[] = []
  for (const pf of filesToUpload) {
    try {
      const uploadRes: any = await api.upload('/files/upload', pf.file, 'file', {
        agent_id: agentId.value,
      })
      const uploadData = uploadRes?.data ?? uploadRes
      if (uploadData?.id) fileIds.push(uploadData.id)
    } catch (err) {
      console.error('[Chat] File upload failed:', err)
    }
  }

  // Initiate SSE streaming request
  abortController = new AbortController()
  const token = secureStorage.get('auth_token')

  // 补课 8（断线重连+replay 快进）：读流网络中断（非用户中止/非 HTTP 错）
  // 时自动带 replay_from=<已消费事件数> 重连一次——服务端快进重放缓冲尾段，
  // 只补发未确认增量，不重放已渲染内容。
  const buildBody = (replayFrom?: number) => ({
    agent_id: agentId.value,
    session_id: currentSessionId.value,
    message: text,
    file_ids: fileIds.length > 0 ? fileIds : undefined,
    // 轮次定位键：随 metadata 持久化，供编辑/删除/反馈定位实时轮次
    client_timestamp: roundTimestamp,
    // 手动模型切换：携带用户选择的模型。
    // 含富媒体文件时不携带（置空），交由后端自动路由至多模态能力 LLM。
    model: fileIds.length > 0 ? undefined : (selectedModel.value || undefined),
    // 思考程度：light/standard/deep，后端注入对应回答深度指令
    thinking_effort: thinkingEffort.value,
    ...(replayFrom !== undefined ? { replay_from: replayFrom } : {}),
  })

  const receivedSeq: number[] = [0]

  const readStream = async (replayFrom?: number): Promise<void> => {
    abortController = new AbortController()
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
      const response = await fetch(`${baseUrl}/console/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(buildBody(replayFrom)),
        signal: abortController.signal,
      })

      if (!response.ok) {
        const errBody = await response.text()
        throw new Error(errBody || `HTTP ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (!data || data === '[DONE]') continue

          try {
            const event = JSON.parse(data)
            receivedSeq[0] += 1
            processSSEEvent(event, streamingMsg)
          } catch {
            // Non-JSON line, skip
          }
        }
        scrollToBottom()
      }
    } finally {
      abortController = null
    }
  }

  try {
    await readStream()
  } catch (err: any) {
    if (err.name === 'AbortError') {
      // 用户主动停止
    } else if (handleRateLimit(err)) {
      // 补课 A1：429 → 横幅一键切模型（不计入消息正文错误）
    } else {
      // 网络层中断且已收到至少一个事件 → 重连快进一次（HTTP 错误/中止不重连）
      const networkDrop =
        receivedSeq[0] > 0 && (err instanceof TypeError || /network|failed|fetch/i.test(String(err.message || '')))
      if (networkDrop) {
        try {
          await readStream(receivedSeq[0])
        } catch (retryErr: any) {
          if (retryErr.name !== 'AbortError') {
            streamingMsg.content += `\n\n**Error:** ${retryErr.message || 'Stream failed.'}`
          }
        }
      } else {
        streamingMsg.content += `\n\n**Error:** ${err.message || 'Stream failed.'}`
      }
    }
  } finally {
    streamingMsg.streaming = false
    // 回复完成时刻（消息底部时间展示用；轮次定位键仍是 timestamp）
    streamingMsg.repliedAt = new Date().toISOString()
    chatStore.setStreaming(false)
    abortController = null
    scrollToBottom()
    // 补课 P3-b：当前轮结束 → 自动续发下一条排队消息（暂停时不续发）
    await drainMessageQueue()
  }
}

/** Process a single SSE event and update the assistant message. */
function processSSEEvent(event: any, msg: ChatMessage) {
  const type = event.type || event.event

  switch (type) {
    case 'memory_progress': {
      // 实时记忆检索进度：临时显示，回复内容开始后由 chunk 分支清空
      const stage = event.stage || ''
      const retriever = event.retriever || ''
      const names: Record<string, string> = {
        unified: '统一检索',
        MoERetriever: 'MoE 专家路由',
        CacheRetriever: '缓存检索',
        FallbackRetriever: '兜底检索',
      }
      const rName = names[retriever] || retriever
      if (stage === 'retriever_start') {
        retrievalStatus.value = `记忆检索中（${rName}）…`
      } else if (stage === 'retriever_done') {
        retrievalStatus.value = `${rName} 完成：命中 ${event.count ?? 0} 条 (${event.ms ?? 0}ms)`
      } else if (stage === 'retriever_error' || stage === 'retriever_timeout') {
        retrievalStatus.value = `${rName} 检索异常，降级下一通道…`
      } else if (stage === 'moe_gate') {
        retrievalStatus.value = `MoE 专家路由：激活 ${(event.experts || []).length} 个专家`
      } else if (stage === 'moe_expert') {
        retrievalStatus.value = `专家下钻 ${event.expert || ''}：${event.count ?? 0} 条`
      } else if (stage === 'moe_done') {
        retrievalStatus.value = event.fallback
          ? `全库语义兜底：命中 ${event.count ?? 0} 条`
          : `专家检索完成：${event.count ?? 0} 条`
      }
      break
    }

    case 'reasoning':
    case 'thinking':
      msg.reasoning = (msg.reasoning || '') + (event.content || event.text || '')
      // 首次收到思考内容时自动展开（用户手动折叠后不再打扰）
      if (msg.reasoning && !msg.reasoningOpen && !msg.reasoningAutoOpened) {
        msg.reasoningOpen = true
        msg.reasoningAutoOpened = true
      }
      break

    case 'tool_call':
      if (!msg.toolCalls) msg.toolCalls = []
      msg.toolCalls.push({
        name: event.name || event.tool_name || 'unknown',
        arguments: event.arguments || event.input || '',
      })
      // legacy compat
      msg.toolCall = msg.toolCalls[msg.toolCalls.length - 1]
      // SSE 兜底：电脑/浏览器工具调用即开分屏（主通道为 WS computer_action）
      if (isComputerTool(event.name || event.tool_name || '')) {
        computerPanel.handleToolCall(String(event.name || event.tool_name))
      }
      break

    case 'tool_result':
      if (msg.toolCalls && msg.toolCalls.length > 0) {
        const last = msg.toolCalls[msg.toolCalls.length - 1]
        last.result = typeof event.result === 'string' ? event.result : JSON.stringify(event.result, null, 2)
      }
      // legacy compat
      msg.toolResult = typeof event.result === 'string' ? event.result : JSON.stringify(event.result, null, 2)
      if (isComputerTool(event.name || '')) {
        computerPanel.markIdle()
      }
      break

    case 'approval_required': {
      // 治理 ASK: 弹出人工确认框（P0）
      approvalModal.approvalId = event.approval_id || ''
      approvalModal.toolName = event.tool_name || ''
      const params = typeof event.params === 'string' ? event.params : JSON.stringify(event.params ?? {}, null, 2)
      approvalModal.command =
        params !== '{}' ? params : (event.command || '')
      approvalModal.reason = event.reason || ''
      approvalAddWhitelist.value = false
      approvalModal.open = true
      break
    }

    case 'message':
    case 'content':
    case 'delta':
    case 'chunk':
      // 回复内容开始 → 检索已结束，清空临时进度显示
      if (retrievalStatus.value) retrievalStatus.value = ''
      msg.content += event.content || event.text || event.delta || ''
      break

    case 'audio':
    case 'tts':
      if (event.url) {
        msg.audioUrl = event.url
        msg.audioProgress = 0
        msg.audioCurrentTime = 0
        msg.audioSpeed = 1
      }
      break

    case 'image':
      // Inline image from backend (e.g., AIGC generated image)
      if (event.url) {
        msg.content += `\n![${event.alt || 'image'}](${event.url})\n`
      }
      break

    case 'done':
    case 'complete':
      msg.streaming = false
      // 补课 4.4 兜底：后端把 audio_url 附在 done 事件上（而非独立 audio 帧）
      if (event.audio_url && !msg.audioUrl) {
        msg.audioUrl = event.audio_url
        msg.audioProgress = 0
        msg.audioCurrentTime = 0
        msg.audioSpeed = 1
      }
      // Auto-create session if this is the first exchange
      if (!currentSessionId.value && event.session_id) {
        chatStore.setCurrentSession(event.session_id)
        chatStore.addSession({
          id: event.session_id,
          title: inputText.value.slice(0, 50) || t('chat.newChat'),
        })
      }
      break

    case 'error':
      msg.content += `\n\n**Error:** ${event.message || event.error || 'Unknown error'}`
      break
  }
}

function stopStreaming() {
  abortController?.abort()
  chatStore.setStreaming(false)
}

// ---------------------------------------------------------------------------
// ASR - Voice Input (Web Speech API + Backend Fallback)
// ---------------------------------------------------------------------------
function initASR() {
  const SpeechRecognition =
    (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  if (!SpeechRecognition) {
    asrAvailable.value = false
    console.warn('[ASR] Web Speech API not available')
    return
  }

  asrAvailable.value = true
  recognition = new SpeechRecognition()
  recognition.continuous = true
  recognition.interimResults = true
  recognition.lang = appStore.locale === 'zh-CN' ? 'zh-CN' : 'en-US'

  recognition.onresult = (event: any) => {
    let finalTranscript = ''
    let interimTranscript = ''
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript
      if (event.results[i].isFinal) {
        finalTranscript += transcript
      } else {
        interimTranscript += transcript
      }
    }
    if (finalTranscript) {
      chatStore.setInputText(inputText.value + (inputText.value ? ' ' : '') + finalTranscript)
      nextTick(() => autoResize())
    }
  }

  recognition.onerror = (event: any) => {
    console.error('[ASR] Error:', event.error)
    if (event.error !== 'aborted') {
      stopRecording()
    }
  }

  recognition.onend = () => {
    // Auto-restart if still in recording mode, but cap consecutive restarts
    // to avoid an infinite loop when isRecording is stuck true or the
    // recognizer keeps dying. After the cap, stop and tell the user.
    if (isRecording.value && asrRestartGuard.canRestart()) {
      asrRestartGuard.recordRestart()
      // Delay restart by 1s to break tight onend→start loops and give the
      // recognizer time to fully reset before we start() it again.
      asrRestartTimer = setTimeout(() => {
        asrRestartTimer = null
        if (!isRecording.value) return
        try {
          recognition.start()
        } catch {
          // Already started
        }
      }, 1000)
    } else if (isRecording.value && asrRestartGuard.limitReached.value) {
      console.warn('[ASR] Restart limit reached, stopping auto-restart')
      isRecording.value = false
      if (recordingTimer) {
        clearInterval(recordingTimer)
        recordingTimer = null
      }
      uiMessage.warning(t('chat.asrRestartLimit') || 'Speech recognition stopped after multiple retries. Please try again.')
    }
  }
}

function toggleRecording() {
  if (isRecording.value) {
    stopRecording()
  } else {
    startRecording()
  }
}

function startRecording() {
  if (!recognition) return
  isRecording.value = true
  recordingSeconds = 0
  recordingTimeStr.value = '0:00'
  // Fresh user-initiated start → reset the restart counter
  asrRestartGuard.reset()

  try {
    recognition.start()
  } catch {
    // Already started
  }

  recordingTimer = setInterval(() => {
    recordingSeconds++
    const mins = Math.floor(recordingSeconds / 60)
    const secs = recordingSeconds % 60
    recordingTimeStr.value = `${mins}:${secs.toString().padStart(2, '0')}`
  }, 1000)
}

function stopRecording() {
  isRecording.value = false
  if (recordingTimer) {
    clearInterval(recordingTimer)
    recordingTimer = null
  }
  if (asrRestartTimer) {
    clearTimeout(asrRestartTimer)
    asrRestartTimer = null
  }
  try {
    recognition?.stop()
  } catch {
    // Ignore
  }
}

function cancelRecording() {
  stopRecording()
}

// Backend ASR fallback for uploaded audio files
async function transcribeAudioFile(file: File): Promise<string | null> {
  try {
    const formData = new FormData()
    formData.append('audio_file', file)
    formData.append('language', appStore.locale === 'zh-CN' ? 'zh' : 'en')
    const res: any = await api.post('/audio/transcribe', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    const data = res?.data ?? res
    return data?.data?.text || data?.text || null
  } catch (err) {
    console.error('[ASR] Backend transcription failed:', err)
    return null
  }
}

// ---------------------------------------------------------------------------
// TTS - Voice Output
// ---------------------------------------------------------------------------
async function checkTTSAvailability() {
  try {
    const res: any = await api.get('/audio/status')
    const data = res?.data ?? res
    const ttsInfo = data?.data?.tts || data?.tts
    ttsAvailable.value = ttsInfo?.initialized ?? false
  } catch {
    ttsAvailable.value = false
  }
}

async function synthesizeTTS(msg: ChatMessage) {
  if (!msg.content || msg.ttsLoading) return
  msg.ttsLoading = true

  try {
    const baseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const token = secureStorage.get('auth_token')
    const response = await fetch(`${baseUrl}/audio/synthesize-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        text: msg.content.replace(/[*`#\[\]()]/g, '').slice(0, 5000),
        speed: 1.0,
        format: 'wav',
      }),
    })

    if (!response.ok) throw new Error(`TTS failed: ${response.status}`)

    // 补课 4.3：流式端点按引擎返回 audio/mpeg 或 audio/wav——blob type
    // 交给 <audio> 自动嗅探，长文本首字节到达即开始下载（整段合成时间
    // 不再阻塞在服务端全量编码完成后）
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    msg.audioUrl = url
    msg.audioProgress = 0
    msg.audioCurrentTime = 0
    msg.audioSpeed = 1

    // Auto-play
    nextTick(() => {
      if (msg.audioEl) {
        msg.audioEl.play().catch(() => {})
      }
    })
  } catch (err) {
    console.error('[TTS] Synthesis failed:', err)
  } finally {
    msg.ttsLoading = false
  }
}

// Custom Audio Player Controls
function setAudioRef(msg: ChatMessage, el: HTMLAudioElement | null) {
  msg.audioEl = el
}

function toggleAudioPlay(msg: ChatMessage) {
  if (!msg.audioEl) return
  if (msg.audioPlaying) {
    msg.audioEl.pause()
    msg.audioPlaying = false
  } else {
    msg.audioEl.play().catch(() => {})
    msg.audioPlaying = true
  }
}

function onAudioTimeUpdate(msg: ChatMessage) {
  if (!msg.audioEl) return
  msg.audioCurrentTime = msg.audioEl.currentTime
  if (msg.audioDuration) {
    msg.audioProgress = (msg.audioEl.currentTime / msg.audioDuration) * 100
  }
}

function onAudioLoaded(msg: ChatMessage) {
  if (!msg.audioEl) return
  msg.audioDuration = msg.audioEl.duration
}

function onAudioEnded(msg: ChatMessage) {
  msg.audioPlaying = false
  msg.audioProgress = 0
  msg.audioCurrentTime = 0
}

function seekAudio(msg: ChatMessage, event: MouseEvent) {
  if (!msg.audioEl || !msg.audioDuration) return
  const target = event.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  const x = event.clientX - rect.left
  const pct = x / rect.width
  msg.audioEl.currentTime = pct * msg.audioDuration
}

function cycleAudioSpeed(msg: ChatMessage) {
  const speeds = [0.5, 0.75, 1, 1.25, 1.5, 2]
  const current = msg.audioSpeed || 1
  const idx = speeds.indexOf(current)
  const next = speeds[(idx + 1) % speeds.length]
  msg.audioSpeed = next
  if (msg.audioEl) msg.audioEl.playbackRate = next
}

function formatAudioTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

// ---------------------------------------------------------------------------
// File Handling (Enhanced with Drag & Drop, Paste, Type Detection)
// ---------------------------------------------------------------------------
const MAX_FILE_SIZE = 50 * 1024 * 1024 // 50MB

function handleFileSelect(e: Event) {
  const target = e.target as HTMLInputElement
  if (!target.files) return
  addFiles(Array.from(target.files))
  target.value = ''
}

function addFiles(files: File[]) {
  for (const file of files) {
    if (file.size > MAX_FILE_SIZE) {
      console.warn(`[File] ${file.name} exceeds 50MB limit, skipped`)
      continue
    }

    const pf: PendingFile = { name: file.name, file, type: file.type }
    if (file.type.startsWith('image/')) {
      pf.preview = URL.createObjectURL(file)
    }
    pendingFiles.value.push(pf)
  }
}

function removePendingFile(index: number) {
  const pf = pendingFiles.value[index]
  if (pf.preview) URL.revokeObjectURL(pf.preview)
  pendingFiles.value.splice(index, 1)
}

// Drag & Drop
function onDragEnter(e: DragEvent) {
  dragCounter++
  isDragOver.value = true
}

function onDragOver(e: DragEvent) {
  // needed for drop to work
}

function onDragLeave(e: DragEvent) {
  dragCounter--
  if (dragCounter <= 0) {
    dragCounter = 0
    isDragOver.value = false
  }
}

function onDrop(e: DragEvent) {
  dragCounter = 0
  isDragOver.value = false
  if (e.dataTransfer?.files) {
    addFiles(Array.from(e.dataTransfer.files))
  }
}

// Paste from clipboard
function handlePaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return

  const files: File[] = []
  for (let i = 0; i < items.length; i++) {
    const item = items[i]
    if (item.kind === 'file') {
      const file = item.getAsFile()
      if (file) files.push(file)
    }
  }
  if (files.length > 0) {
    e.preventDefault()
    addFiles(files)
  }
}

// File type utilities
function getFileCategory(type?: string): string {
  if (!type) return 'unknown'
  if (type.startsWith('image/')) return 'image'
  if (type.startsWith('audio/')) return 'audio'
  if (type.startsWith('video/')) return 'video'
  if (type === 'application/pdf') return 'pdf'
  if (type.includes('spreadsheet') || type.includes('csv')) return 'spreadsheet'
  if (type.includes('presentation') || type.includes('powerpoint')) return 'presentation'
  if (
    type.includes('document') ||
    type.includes('msword') ||
    type.includes('wordprocessing')
  )
    return 'document'
  if (type.startsWith('text/')) return 'text'
  return 'file'
}

function getFileIcon(type?: string): string {
  const cat = getFileCategory(type)
  const icons: Record<string, string> = {
    image: '🖼️',
    audio: '🎵',
    video: '🎬',
    pdf: '📕',
    spreadsheet: '📊',
    presentation: '📑',
    document: '📄',
    text: '📝',
    file: '📎',
    unknown: '📎',
  }
  return icons[cat] || '📎'
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

// ---------------------------------------------------------------------------
// Rich Content Rendering
// ---------------------------------------------------------------------------
/**
 * 消息内容 Markdown 渲染。
 *
 * 旧实现是手写正则伪 MD: 标题/列表/引用/表格/删除线全部退化纯文本,
 * 且正则顺序会二次污染代码块 (** 变 <strong>、\n 变 <br/>、<div> 当标签)。
 * 现统一走 src/utils/markdown.ts 的 marked (GFM+breaks) + 语法高亮 +
 * DOMPurify 白名单兜底 (渲染与安全细节见该模块, 纯函数便于测试)。
 */
function renderRichContent(text: string): string {
  return renderMarkdown(text, t('common.copy'))
}

/** Handle clicks within rendered content (image lightbox + code copy). */
function handleContentClick(e: MouseEvent) {
  const target = e.target as HTMLElement

  // 事件委托处理代码块复制按钮; 代码内容直接从 DOM textContent 读取,
  // 不依赖 data-code 属性 (旧链路 encodeURIComponent+decodeURIComponent 脆弱)
  const copyBtn = target.closest('.nr-code-copy-btn') as HTMLButtonElement | null
  if (copyBtn) {
    const codeEl = copyBtn.closest('.nr-code-wrap')?.querySelector('code')
    const code = codeEl ? codeEl.textContent || '' : ''
    navigator.clipboard.writeText(code).then(() => {
      copyBtn.textContent = '✓'
      setTimeout(() => {
        copyBtn.textContent = t('common.copy')
      }, 1500)
    }).catch(() => {
      copyBtn.textContent = '✗'
      setTimeout(() => {
        copyBtn.textContent = t('common.copy')
      }, 1500)
    })
    return
  }

  // 图片 lightbox
  if (target.tagName === 'IMG' && target.closest('.nr-inline-image')) {
    const img = target as HTMLImageElement
    openLightbox(img.src, img.alt)
  }
}

// Lightbox
function openLightbox(src: string, alt: string) {
  lightbox.src = src
  lightbox.alt = alt
  lightbox.open = true
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
// ── 会话内消息搜索（补课 B）─────────────────────────────
const msgSearchOpen = ref(false)
const msgSearchQuery = ref('')
const msgSearchCursor = ref(0)  // 当前命中下标（0..hits.length-1）
const msgSearchHits = computed(() => findMessageMatches(messages.value, msgSearchQuery.value))

function openMsgSearch(): void {
  msgSearchOpen.value = !msgSearchOpen.value
  if (msgSearchOpen.value) {
    msgSearchQuery.value = ''
    msgSearchCursor.value = 0
  }
}

function jumpToMatch(dir: 1 | -1): void {
  const hits = msgSearchHits.value
  if (hits.length === 0) return
  // 游标循环移动
  msgSearchCursor.value = (msgSearchCursor.value + dir + hits.length) % hits.length
  const idx = hits[msgSearchCursor.value]
  // 滚动到命中消息（offsetTop 相对滚动容器）
  const el = document.getElementById(`nr-msg-${idx}`)
  if (el && messagesRef.value) {
    messagesRef.value.scrollTop = el.offsetTop - 80
  }
}

// ── 输入历史回溯（补课 C）─────────────────────────────
const chatDraft = useChatDraft()

// ── mermaid 渲染（补课 E）─────────────────────────────
const { renderIn: renderMermaid, scheduleRender: scheduleMermaidRender, dispose: disposeMermaid } =
  useMermaidRenderer(() => !appStore.isDark)

const { record: recordInputHistory, up: historyUp, down: historyDown } = useInputHistory()

const { onCompositionStart, onCompositionEnd, shouldBlockSend } = useIMEComposition()

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    // IME 合成防误发（补课 A）：输入法选词回车不发送
    if (shouldBlockSend(e)) return
    e.preventDefault()
    sendMessage()
    return
  }
  // ↑↓ 历史回溯（补课 C）：仅无修饰键时生效
  if (e.key === 'ArrowUp' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
    const next = historyUp(inputText.value)
    if (next !== null) {
      e.preventDefault()
      chatStore.setInputText(next)
    }
  } else if (e.key === 'ArrowDown' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
    const next = historyDown(inputText.value)
    if (next !== null) {
      e.preventDefault()
      chatStore.setInputText(next)
    }
  }
}

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

// 补课 E：消息内容变更 → 防抖渲染 mermaid 占位
watch(
  () => messages.value.map((m) => m.content.length).reduce((a, b) => a + b, 0),
  () => scheduleMermaidRender(messagesRef.value),
)
onMounted(() => void nextTick().then(() => renderMermaid(messagesRef.value)))

function formatJSON(str: string): string {
  try {
    return JSON.stringify(JSON.parse(str), null, 2)
  } catch {
    return str
  }
}

// ---------------------------------------------------------------------------
// Watch locale change → update ASR language
// ---------------------------------------------------------------------------
watch(
  () => appStore.locale,
  (newLocale) => {
    if (recognition) {
      recognition.lang = newLocale === 'zh-CN' ? 'zh-CN' : 'en-US'
    }
  },
)

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
// 切换 agent 时重新加载 sessions
watch(agentId, (newId, oldId) => {
  if (newId && newId !== oldId) {
    chatStore.clearMessages()
    chatStore.setCurrentSession(null)
    loadSessions()
    // 存档卡片页开着时随 agent 切换刷新列表
    if (archivedPanelOpen.value) {
      _loadArchivedSessions(newId)
    }
  }
})

onMounted(() => {
  loadSessions()
  initASR()
  checkTTSAvailability()
  loadChatModels()
})

onBeforeUnmount(() => {
  // 补课 D：离开页面保存当前会话草稿
  if (currentSessionId.value) chatDraft.save(currentSessionId.value, inputText.value)
  disposeMermaid()
  abortController?.abort()
  stopRecording()
  for (const pf of pendingFiles.value) {
    if (pf.preview) URL.revokeObjectURL(pf.preview)
  }
  // Revoke TTS blob URLs
  for (const msg of messages.value) {
    if (msg.audioUrl?.startsWith('blob:')) {
      URL.revokeObjectURL(msg.audioUrl)
    }
  }
})
</script>

<style scoped>
.nr-chat-page {
  display: flex;
  height: calc(100vh - 64px);
  gap: 0;
  animation: chat-enter 0.4s ease both;
  position: relative;
}

@keyframes chat-enter {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* Drag & Drop Overlay */
.nr-drop-overlay {
  position: absolute;
  inset: 0;
  z-index: 100;
  background: var(--nr-primary-soft);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px dashed var(--nr-primary);
  border-radius: 16px;
  pointer-events: none;
}

.nr-drop-overlay-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.nr-drop-icon {
  font-size: 48px;
  animation: drop-bounce 0.6s ease infinite alternate;
}

@keyframes drop-bounce {
  from { transform: translateY(0); }
  to { transform: translateY(-8px); }
}

.nr-drop-text {
  font-size: 18px;
  font-weight: 600;
  color: var(--nr-primary-light);
}

/* Sidebar */
.nr-chat-sidebar {
  width: 280px;
  min-width: 280px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--nr-glass-border);
  background: var(--nr-bg-inset);
  transition: width 0.3s ease, min-width 0.3s ease;
}

.nr-chat-sidebar.collapsed {
  width: 0;
  min-width: 0;
  overflow: hidden;
  border-right: none;
}

.nr-sidebar-header {
  display: flex;
  gap: 8px;
  padding: 16px;
}

.nr-sidebar-search {
  padding: 0 16px 12px;
}

.nr-session-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}

.nr-session-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.2s;
  margin-bottom: 2px;
}

.nr-session-item:hover {
  background: var(--nr-glass-bg-hover);
}

.nr-session-item.active {
  background: var(--nr-primary-soft);
  border: 1px solid var(--nr-primary-soft-border);
}

.nr-session-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.nr-session-name {
  flex: 1;
  font-size: 13px;
  color: var(--nr-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nr-session-menu-btn {
  color: var(--nr-text-muted);
  font-size: 16px;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s;
}

.nr-session-item:hover .nr-session-menu-btn {
  opacity: 1;
}

.nr-chat-page-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 24px; border-bottom: 1px solid var(--nr-glass-border);
  background: var(--nr-glass-bg); flex-shrink: 0;
}
.nr-chat-header-left { display: flex; align-items: center; gap: 12px; }
.nr-chat-header-left .page-title { margin: 0; font-family: var(--nr-font-display); font-size: 20px; font-weight: 700; color: var(--nr-text-primary); }
.nr-chat-header-actions { display: flex; gap: 8px; align-items: center; }
.nr-chat-model-select {
  min-width: 190px;
  background: var(--nr-glass-bg);
  border-radius: 8px;
}
.nr-chat-model-select:hover { border-color: var(--nr-glass-border-hover); }
.nr-chat-model-select .ant-select-selection-item,
.nr-chat-model-select .ant-select-selection-placeholder {
  font-size: 13px;
}
.nr-chat-toggle-btn {
  width: 32px; height: 32px; border: 1px solid var(--nr-glass-border); border-radius: 8px;
  background: var(--nr-glass-bg); color: var(--nr-text-secondary); font-size: 18px;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all 0.2s ease;
}
.nr-chat-toggle-btn:hover { border-color: var(--nr-glass-border-hover); color: var(--nr-text-primary); background: var(--nr-glass-bg-hover); }
.nr-chat-toggle-btn.cu-active { border-color: color-mix(in srgb, var(--nr-primary-light) 70%, transparent); color: var(--nr-primary-light, #818cf8); background: var(--nr-primary-soft); }

/* 思考程度三档选择器（简单/标准/深度） */
.nr-thinking-seg {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 8px;
  background: var(--nr-glass-bg);
}
.nr-thinking-opt {
  border: none;
  background: transparent;
  color: var(--nr-text-tertiary);
  font-size: 12px;
  line-height: 1;
  padding: 6px 9px;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}
.nr-thinking-opt:hover { color: var(--nr-text-primary); }
.nr-thinking-opt.active {
  color: #fff;
  background: var(--nr-primary);
}
@media (max-width: 720px) {
  .nr-thinking-seg { display: none; }
}
.nr-chat-session-select {
  display: flex; align-items: center; gap: 8px; padding: 6px 14px;
  border-radius: 10px; border: 1px solid var(--nr-glass-border);
  background: var(--nr-glass-bg); color: var(--nr-text-primary);
  font-size: 14px; font-weight: 500; cursor: pointer;
  transition: all 0.2s ease;
}
.nr-chat-session-select:hover { border-color: var(--nr-glass-border-hover); background: var(--nr-glass-bg-hover); }
.nr-chat-session-select-icon { font-size: 16px; }
.nr-chat-session-select-name { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nr-chat-session-select-arrow { font-size: 10px; opacity: 0.5; }
.nr-glass-dropdown {
  background: var(--nr-bg-surface); backdrop-filter: blur(40px) saturate(180%);
  border: 1px solid var(--nr-glass-border); border-radius: 14px;
  padding: 6px; min-width: 220px; box-shadow: var(--nr-shadow-lg);
  display: flex; flex-direction: column; gap: 2px;
}
.nr-glass-dropdown-item {
  display: flex; align-items: center; gap: 10px; padding: 9px 12px;
  border-radius: 10px; color: var(--nr-text-secondary);
  font-size: 13px; cursor: pointer; transition: all 0.18s ease; white-space: nowrap;
}
.nr-glass-dropdown-item:hover { color: var(--nr-text-primary); background: var(--nr-glass-bg-hover); }
.nr-glass-dropdown-item.is-active { color: var(--nr-primary-light); background: var(--nr-primary-soft); font-weight: 550; }
.nr-glass-dropdown-divider { height: 1px; background: var(--nr-glass-border); margin: 4px 8px; }

.nr-session-empty {
  text-align: center;
  color: var(--nr-text-muted);
  padding: 32px 16px;
  font-size: 13px;
}

/* Main Chat Area */
.nr-chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;

  /* 蜂群子 Agent 小窗堆叠（右下角） */
  .subagent-window-stack {
    position: absolute;
    right: 16px;
    bottom: 96px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    z-index: 90;
    pointer-events: none;
    max-height: 70%;
    overflow: visible;

    :deep(.subagent-panel) {
      pointer-events: auto;
    }
  }
  min-width: 0;
}

.nr-chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.nr-chat-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--nr-text-tertiary);
  gap: 8px;
}

.nr-chat-empty-icon {
  font-size: 48px;
  margin-bottom: 8px;
}

.nr-chat-empty h3 {
  font-family: var(--nr-font-display);
  font-size: 20px;
  color: var(--nr-text-primary);
  margin: 0;
}

.nr-chat-empty p {
  font-size: 14px;
  margin: 0;
}

/* Message Bubbles */
.nr-msg {
  display: flex;
  gap: 12px;
  max-width: 85%;
  animation: msg-in 0.3s ease both;
}

@keyframes msg-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.nr-msg--user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.nr-msg--assistant {
  align-self: flex-start;
}

.nr-msg-avatar {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
  background: var(--nr-glass-bg);
}

.nr-msg-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.nr-msg--user .nr-msg-body {
  align-items: flex-end;
}

.nr-msg-content {
  padding: 12px 16px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

.nr-msg--user .nr-msg-content {
  background: var(--nr-bubble-user);
  border: 1px solid var(--nr-bubble-user-border);
  color: var(--nr-text-primary);
}

.nr-msg--assistant .nr-msg-content {
  background: var(--nr-glass-bg);
  border: 1px solid var(--nr-glass-border);
  color: var(--nr-text-primary);
}

/* Reasoning Block */
.nr-msg-reasoning {
  background: var(--nr-glass-bg);
  border: 1px solid var(--nr-glass-border);
  border-radius: 10px;
  overflow: hidden;
}

.nr-reasoning-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  color: var(--nr-text-secondary);
  font-weight: 500;
  transition: background 0.2s;
}

.nr-reasoning-header:hover {
  background: var(--nr-glass-bg-hover);
}

.nr-reasoning-toggle {
  font-size: 14px;
  color: var(--nr-text-muted);
}

.nr-reasoning-content {
  padding: 8px 12px 12px;
  font-size: 13px;
  color: var(--nr-text-tertiary);
  line-height: 1.5;
  white-space: pre-wrap;
  border-top: 1px solid var(--nr-border-light);
}

/* Tool Call Block */
.nr-msg-tool-call {
  background: rgba(245, 158, 11, 0.06);
  border: 1px solid rgba(245, 158, 11, 0.15);
  border-radius: 10px;
  padding: 10px 14px;
}

.nr-tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}

.nr-tool-header:hover {
  opacity: 0.8;
}

.nr-tool-toggle {
  margin-left: auto;
  font-size: 14px;
  color: var(--nr-text-muted);
}

.nr-tool-icon {
  font-size: 16px;
}

.nr-tool-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-text-primary);
}

.nr-tool-args {
  font-size: 12px;
  color: var(--nr-text-secondary);
  background: var(--nr-bg-inset);
  border-radius: 6px;
  padding: 8px 10px;
  margin: 0;
  overflow-x: auto;
  font-family: var(--nr-font-mono);
  max-height: 120px;
}

/* Governance approval modal (P0) */
.approval-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.approval-field {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.approval-label {
  min-width: 42px;
  font-size: 13px;
  color: var(--nr-text-secondary);
  line-height: 22px;
  flex-shrink: 0;
}

.approval-command {
  font-size: 12px;
  color: var(--nr-text-primary, inherit);
  background: var(--nr-bg-inset);
  border-radius: 6px;
  padding: 8px 10px;
  margin: 0;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 140px;
  flex: 1;
}

.approval-reason {
  font-size: 13px;
  color: var(--nr-warning);
  line-height: 1.5;
}

.approval-hint {
  font-size: 12px;
  color: var(--nr-text-secondary);
  margin: 4px 0 0;
}

.nr-tool-result {
  margin-top: 8px;
  border-top: 1px solid var(--nr-glass-border);
  padding-top: 8px;
}

.nr-tool-result-header {
  font-size: 11px;
  color: var(--nr-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 4px;
}

.nr-tool-result-content {
  font-size: 12px;
  color: var(--nr-text-secondary);
  background: var(--nr-bg-inset);
  border-radius: 6px;
  padding: 8px 10px;
  margin: 0;
  overflow-x: auto;
  font-family: var(--nr-font-mono);
  max-height: 120px;
}

/* Enhanced Attachments */
.nr-msg-attachments {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.nr-attachment-thumb {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--nr-glass-bg);
  border: 1px solid var(--nr-glass-border);
  font-size: 12px;
  color: var(--nr-text-secondary);
  transition: background 0.2s, border-color 0.2s;
}

.nr-attachment-thumb:hover {
  background: var(--nr-glass-bg-hover);
  border-color: var(--nr-glass-border-hover);
}

.nr-attachment--image {
  cursor: pointer;
}

.nr-attachment-img {
  width: 48px;
  height: 48px;
  object-fit: cover;
  border-radius: 8px;
}

.nr-attachment-file-icon {
  font-size: 24px;
}

.nr-attachment-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nr-attachment-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.nr-attachment-size {
  font-size: 10px;
  color: var(--nr-text-muted);
}

/* Custom Audio Player */
.nr-msg-audio-player {
  margin-top: 4px;
}

.nr-audio-player {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: var(--nr-primary-soft);
  border: 1px solid var(--nr-primary-soft-border);
  border-radius: 12px;
  min-width: 280px;
}

.nr-audio-play-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: none;
  background: var(--nr-primary);
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.15s, background 0.2s;
}

.nr-audio-play-btn:hover {
  background: var(--nr-primary-light);
}

.nr-audio-progress-wrap {
  flex: 1;
  cursor: pointer;
  padding: 4px 0;
}

.nr-audio-progress-bar {
  height: 4px;
  background: var(--nr-glass-bg-active);
  border-radius: 2px;
  overflow: hidden;
}

.nr-audio-progress-fill {
  height: 100%;
  background: var(--nr-primary);
  border-radius: 2px;
  transition: width 0.1s linear;
}

.nr-audio-time {
  font-size: 11px;
  color: var(--nr-text-muted);
  font-family: var(--nr-font-mono);
  min-width: 36px;
  text-align: right;
}

.nr-audio-speed-btn {
  background: var(--nr-glass-bg-hover);
  border: 1px solid var(--nr-glass-border);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  color: var(--nr-text-secondary);
  cursor: pointer;
  transition: background 0.2s;
}

.nr-audio-speed-btn:hover {
  background: var(--nr-glass-bg-active);
}

/* TTS Action Button */
.nr-msg-tts-action {
  margin-top: 4px;
}

.nr-tts-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 8px;
  border: 1px solid var(--nr-glass-border);
  background: var(--nr-glass-bg);
  color: var(--nr-text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}

.nr-tts-btn:hover {
  background: var(--nr-primary-soft);
  border-color: var(--nr-primary-soft-border);
}

.nr-tts-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Message footer: 时间 + 操作条（复制/点赞/点踩/编辑/删除轮次） */
.nr-msg-footer {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
  opacity: 0.75;
  transition: opacity 0.2s;
}

.nr-msg:hover .nr-msg-footer {
  opacity: 1;
}

.nr-msg-time {
  font-size: 11px;
  color: var(--nr-text-muted);
  font-family: var(--nr-font-mono);
  user-select: none;
}

.nr-msg-footer-spacer {
  flex: 0 0 6px;
}

.nr-msg-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--nr-text-muted);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.nr-msg-action:hover {
  background: var(--nr-glass-bg-active);
  color: var(--nr-text-primary);
}

.nr-msg-action--active {
  color: var(--nr-primary);
  background: var(--nr-primary-soft);
}

.nr-msg-action--active-negative {
  color: var(--nr-danger, #e5484d);
  background: rgba(229, 72, 77, 0.12);
}

.nr-msg-action--danger:hover {
  color: var(--nr-danger, #e5484d);
}

/* 编辑最后一条用户消息（内联编辑框） */
.nr-msg-edit {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.nr-msg-edit-textarea {
  width: 100%;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--nr-primary-soft-border);
  background: var(--nr-glass-bg);
  color: var(--nr-text-primary);
  font-size: 14px;
  line-height: 1.6;
  resize: vertical;
  font-family: inherit;
}

.nr-msg-edit-textarea:focus {
  outline: none;
  border-color: var(--nr-primary);
}

.nr-msg-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.nr-edit-btn {
  padding: 5px 14px;
  border-radius: 8px;
  border: 1px solid var(--nr-glass-border);
  background: var(--nr-glass-bg);
  color: var(--nr-text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}

.nr-edit-btn:hover {
  background: var(--nr-glass-bg-active);
}

.nr-edit-btn--primary {
  background: var(--nr-primary-soft);
  border-color: var(--nr-primary-soft-border);
  color: var(--nr-primary);
}

.nr-edit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Streaming indicator */
.nr-msg-streaming {
  display: flex;
  gap: 4px;
  padding: 8px 0;
}

.nr-typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--nr-primary-light);
  animation: typing 1.4s infinite;
}

.nr-typing-dot:nth-child(2) { animation-delay: 0.2s; }
.nr-typing-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing {
  0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-4px); }
}

/* Input Area */
.nr-chat-input-area {
  padding: 12px 24px 20px;
  border-top: 1px solid var(--nr-glass-border);
}

.nr-pending-files {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.nr-pending-file {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 10px;
  background: var(--nr-glass-bg);
  border: 1px solid var(--nr-glass-border);
  font-size: 12px;
  color: var(--nr-text-secondary);
}

.nr-pending-file img {
  width: 32px;
  height: 32px;
  object-fit: cover;
  border-radius: 6px;
}

.nr-pending-file-icon {
  font-size: 20px;
}

.nr-pending-file-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.nr-pending-file-name {
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nr-pending-file-size {
  font-size: 10px;
  color: var(--nr-text-muted);
}

.nr-pending-file-remove {
  background: none;
  border: none;
  color: var(--nr-text-muted);
  cursor: pointer;
  font-size: 16px;
  padding: 0 2px;
  line-height: 1;
}

.nr-pending-file-remove:hover {
  color: var(--nr-error);
}

/* ASR Recording Bar */
.nr-recording-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  margin-bottom: 8px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 10px;
}

.nr-recording-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #ef4444;
  animation: rec-pulse 1s ease infinite;
}

@keyframes rec-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.8); }
}

.nr-recording-label {
  font-size: 13px;
  color: var(--nr-error);
  font-weight: 500;
}

.nr-recording-wave {
  display: flex;
  align-items: center;
  gap: 2px;
  height: 20px;
  flex: 1;
}

.nr-wave-bar {
  width: 3px;
  height: 100%;
  background: rgba(239, 68, 68, 0.5);
  border-radius: 2px;
  animation: wave-anim 0.8s ease-in-out infinite alternate;
}

@keyframes wave-anim {
  0% { height: 20%; }
  100% { height: 90%; }
}

.nr-recording-time {
  font-size: 13px;
  font-family: var(--nr-font-mono);
  color: var(--nr-text-secondary);
}

.nr-recording-cancel {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  padding: 2px 10px;
  font-size: 12px;
  color: var(--nr-error);
  cursor: pointer;
  transition: background 0.2s;
}

.nr-recording-cancel:hover {
  background: rgba(239, 68, 68, 0.25);
}

.nr-input-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}

.nr-voice-active {
  animation: voice-glow 1s ease infinite alternate;
}

@keyframes voice-glow {
  from { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.2); }
  to { box-shadow: 0 0 0 8px rgba(239, 68, 68, 0); }
}

.nr-chat-textarea {
  flex: 1;
  resize: none;
  background: var(--nr-glass-bg);
  border: 1px solid var(--nr-glass-border);
  border-radius: 12px;
  padding: 10px 14px;
  color: var(--nr-text-primary);
  font-size: 14px;
  font-family: var(--nr-font-body);
  line-height: 1.5;
  outline: none;
  transition: border-color 0.25s;
  max-height: 160px;
}

.nr-chat-textarea:focus {
  border-color: var(--nr-primary);
  box-shadow: 0 0 0 3px var(--nr-primary-ring);
}

.nr-chat-textarea::placeholder {
  color: var(--nr-text-muted);
}

/* Rich Content: Code Blocks */
:deep(.nr-code-wrap) {
  margin: 10px 0;
  border-radius: 10px;
  overflow: hidden;
  background: var(--nr-bg-inset-deep);
  border: 1px solid var(--nr-glass-border);
}

:deep(.nr-code-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 14px;
  background: var(--nr-glass-bg);
  border-bottom: 1px solid var(--nr-glass-border);
}

:deep(.nr-code-lang) {
  font-size: 11px;
  color: var(--nr-primary-light);
  font-family: var(--nr-font-mono);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

:deep(.nr-code-copy-btn) {
  background: var(--nr-glass-bg-hover);
  border: 1px solid var(--nr-glass-border);
  border-radius: 4px;
  padding: 1px 8px;
  font-size: 11px;
  color: var(--nr-text-muted);
  cursor: pointer;
  transition: background 0.2s, color 0.2s;
}

:deep(.nr-code-copy-btn:hover) {
  background: var(--nr-glass-bg-active);
  color: var(--nr-text-primary);
}

:deep(.nr-code-block) {
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 10px 14px;
  overflow-x: auto;
  font-family: var(--nr-font-mono);
  font-size: 12px;
  line-height: 1.6;
  margin: 0;
}

:deep(.nr-code-inline) {
  background: var(--nr-bg-inset);
  border-radius: 4px;
  padding: 1px 5px;
  font-family: var(--nr-font-mono);
  font-size: 0.9em;
  color: var(--nr-accent-secondary);
}

/* Rich Content: Inline Images */
:deep(.nr-inline-image) {
  margin: 10px 0;
  display: inline-block;
  max-width: 100%;
  cursor: pointer;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--nr-glass-border);
  transition: border-color 0.2s;
}

:deep(.nr-inline-image:hover) {
  border-color: color-mix(in srgb, var(--nr-primary) 30%, transparent);
}

:deep(.nr-inline-image img) {
  display: block;
  max-width: 100%;
  max-height: 400px;
  object-fit: contain;
}

:deep(.nr-img-caption) {
  display: block;
  padding: 6px 12px;
  font-size: 11px;
  color: var(--nr-text-muted);
  background: var(--nr-bg-inset);
  text-align: center;
}

/* Message Links */
:deep(.nr-msg-link) {
  color: var(--nr-primary-light);
  text-decoration: underline;
  text-underline-offset: 2px;
}

:deep(.nr-msg-link:hover) {
  color: var(--nr-accent);
}

/* Rich Content: Markdown 块级元素 (标题/列表/引用/表格) */
:deep(.nr-msg-content) {
  line-height: 1.65;
}

:deep(.nr-msg-content h1),
:deep(.nr-msg-content h2),
:deep(.nr-msg-content h3),
:deep(.nr-msg-content h4),
:deep(.nr-msg-content h5),
:deep(.nr-msg-content h6) {
  margin: 0.9em 0 0.45em;
  font-weight: 600;
  color: var(--nr-text-primary);
  line-height: 1.35;
}

:deep(.nr-msg-content h1) {
  font-size: 1.35em;
  border-bottom: 1px solid var(--nr-glass-border);
  padding-bottom: 0.25em;
}

:deep(.nr-msg-content h2) {
  font-size: 1.2em;
}

:deep(.nr-msg-content h3) {
  font-size: 1.1em;
}

:deep(.nr-msg-content h4),
:deep(.nr-msg-content h5),
:deep(.nr-msg-content h6) {
  font-size: 1em;
}

:deep(.nr-msg-content ul),
:deep(.nr-msg-content ol) {
  margin: 0.4em 0 0.8em;
  padding-left: 1.5em;
}

:deep(.nr-msg-content ul) {
  list-style: disc;
}

:deep(.nr-msg-content ol) {
  list-style: decimal;
}

:deep(.nr-msg-content li) {
  margin: 0.2em 0;
}

:deep(.nr-msg-content blockquote) {
  margin: 0.6em 0;
  padding: 0.3em 0.9em;
  border-left: 3px solid var(--nr-primary);
  background: var(--nr-bg-inset);
  border-radius: 0 6px 6px 0;
  color: var(--nr-text-secondary);
}

:deep(.nr-msg-content table) {
  border-collapse: collapse;
  margin: 0.6em 0;
  max-width: 100%;
  display: block;
  overflow-x: auto;
  font-size: 0.92em;
}

:deep(.nr-msg-content th),
:deep(.nr-msg-content td) {
  border: 1px solid var(--nr-glass-border);
  padding: 5px 10px;
}

:deep(.nr-msg-content th) {
  background: var(--nr-glass-bg);
  font-weight: 600;
}

:deep(.nr-msg-content p) {
  margin: 0.35em 0;
}

:deep(.nr-msg-content :not(pre) > code) {
  background: var(--nr-bg-inset);
  border-radius: 4px;
  padding: 1px 5px;
  font-family: var(--nr-font-mono);
  font-size: 0.9em;
  color: var(--nr-accent-secondary);
}

:deep(.nr-msg-content hr) {
  border: none;
  border-top: 1px solid var(--nr-glass-border);
  margin: 0.9em 0;
}

/* Rich Content: highlight.js token 配色 (玻璃暗色系) */
:deep(.nr-code-block .hljs-comment),
:deep(.nr-code-block .hljs-quote) {
  color: #6b7280;
  font-style: italic;
}

:deep(.nr-code-block .hljs-keyword),
:deep(.nr-code-block .hljs-selector-tag),
:deep(.nr-code-block .hljs-meta) {
  color: #c792ea;
}

:deep(.nr-code-block .hljs-string),
:deep(.nr-code-block .hljs-regexp),
:deep(.nr-code-block .hljs-symbol) {
  color: #7ec699;
}

:deep(.nr-code-block .hljs-number),
:deep(.nr-code-block .hljs-literal) {
  color: #f78c6c;
}

:deep(.nr-code-block .hljs-title),
:deep(.nr-code-block .hljs-title.class_),
:deep(.nr-code-block .hljs-title.function_),
:deep(.nr-code-block .hljs-section) {
  color: #82aaff;
}

:deep(.nr-code-block .hljs-built_in),
:deep(.nr-code-block .hljs-attr),
:deep(.nr-code-block .hljs-attribute),
:deep(.nr-code-block .hljs-variable),
:deep(.nr-code-block .hljs-template-variable) {
  color: #ffcb6b;
}

:deep(.nr-code-block .hljs-tag),
:deep(.nr-code-block .hljs-name),
:deep(.nr-code-block .hljs-selector-tag) {
  color: #f07178;
}

:deep(.nr-code-block .hljs-params),
:deep(.nr-code-block .hljs-type) {
  color: #eeffff;
}

:deep(.nr-code-block .hljs-function) {
  color: #82aaff;
}

:deep(.nr-code-block .hljs-punctuation),
:deep(.nr-code-block .hljs-operator) {
  color: #89ddff;
}

/* Lightbox */
.nr-lightbox {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(0, 0, 0, 0.85);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.nr-lightbox-content {
  max-width: 90vw;
  max-height: 85vh;
  cursor: default;
}

.nr-lightbox-content img {
  max-width: 90vw;
  max-height: 80vh;
  object-fit: contain;
  border-radius: 12px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.5);
}

.nr-lightbox-caption {
  text-align: center;
  padding: 12px;
  color: rgba(255, 255, 255, 0.7);
  font-size: 13px;
}

.nr-lightbox-close {
  position: absolute;
  top: 20px;
  right: 24px;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 1px solid var(--nr-glass-border);
  background: var(--nr-bg-overlay);
  color: var(--nr-text-primary);
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
}

.nr-lightbox-close:hover {
  background: rgba(255, 255, 255, 0.1);
}

/* Transitions */
.fade-scale-enter-active,
.fade-scale-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.fade-scale-enter-from,
.fade-scale-leave-to {
  opacity: 0;
  transform: scale(0.95);
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

/* Main layout mode: fill parent container instead of viewport */
.nr-chat-page--main {
  height: calc(100vh - var(--nr-header-h) - 48px);
  border-radius: 12px;
}

/* Right-side conversation history panel (main layout mode) */
.nr-chat-history-panel {
  width: 280px;
  min-width: 280px;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--nr-glass-border);
  background: var(--nr-bg-inset);
}

.nr-chat-archived-panel {
  width: 280px;
  min-width: 280px;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--nr-glass-border);
  background: var(--nr-bg-inset);
}

.nr-archived-close {
  background: none;
  border: none;
  color: var(--nr-text-secondary);
  cursor: pointer;
  font-size: 14px;
  padding: 4px 8px;
}

.nr-archived-restore-btn {
  background: var(--nr-bg-elevated, rgba(255, 255, 255, 0.08));
  border: 1px solid var(--nr-border-light);
  border-radius: 8px;
  color: var(--nr-text-primary);
  cursor: pointer;
  font-size: 12px;
  padding: 4px 10px;
  white-space: nowrap;
}

.nr-archived-restore-btn:hover {
  border-color: var(--nr-primary, var(--nr-border-light));
}

.nr-history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--nr-border-light);
}

.nr-history-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--nr-text-primary);
}

.nr-history-search {
  padding: 0 16px 12px;
}

/* 实时记忆检索进度条（临时态，不落历史） */
.nr-retrieval-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  margin: 0 16px 6px;
  font-size: 12px;
  color: var(--nr-text-secondary);
  background: var(--nr-bg-secondary);
  border: 1px solid var(--nr-border);
  border-radius: 10px;
}

.nr-retrieval-spinner {
  display: inline-block;
  animation: nr-retrieval-spin 1.2s linear infinite;
  color: var(--nr-accent);
}

@keyframes nr-retrieval-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.nr-rate-limit-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 0 0 8px;
  padding: 8px 12px;
  border-radius: 10px;
  border: 1px solid rgba(245, 158, 11, 0.4);
  background: rgba(245, 158, 11, 0.08);
  font-size: 12px;
}

.nr-rate-limit-text {
  color: var(--nr-text-primary);
}

.nr-rate-limit-alts {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.nr-rate-limit-alt {
  padding: 3px 10px;
  border-radius: 8px;
  border: 1px solid rgba(99, 102, 241, 0.5);
  background: rgba(99, 102, 241, 0.1);
  color: var(--nr-text-primary);
  cursor: pointer;
  font-size: 12px;
}

.nr-rate-limit-alt:hover {
  background: rgba(99, 102, 241, 0.2);
}

.nr-rate-limit-dismiss {
  margin-left: auto;
  border: none;
  background: none;
  color: var(--nr-text-tertiary);
  cursor: pointer;
}

.nr-msg-queue {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 0 0 8px;
  font-size: 12px;
}

.nr-msg-queue-count {
  color: var(--nr-text-secondary);
}

.nr-msg-queue-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border-radius: 8px;
  border: 1px solid var(--nr-glass-border);
  background: rgba(255, 255, 255, 0.04);
  color: var(--nr-text-primary);
  cursor: pointer;
}

.nr-msg-queue-item .nr-msg-queue-status.pending { color: var(--nr-text-tertiary); }
.nr-msg-queue-item .nr-msg-queue-status.sending { color: #6366f1; }
.nr-msg-queue-item .nr-msg-queue-status.failed { color: #ef4444; }

.nr-msg-queue-clear {
  border: none;
  background: none;
  color: var(--nr-text-tertiary);
  cursor: pointer;
  font-size: 12px;
}

.nr-msg-search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  margin: 0 0 8px;
  border-radius: 8px;
  border: 1px solid var(--nr-glass-border);
  background: rgba(255, 255, 255, 0.04);
}

.nr-msg-search-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--nr-text-primary);
  font-size: 13px;
}

.nr-msg-search-count {
  font-size: 12px;
  color: var(--nr-text-tertiary);
  white-space: nowrap;
}

.nr-msg-search-btn {
  border: none;
  background: none;
  color: var(--nr-text-secondary);
  cursor: pointer;
  font-size: 14px;
  padding: 0 4px;
}

.nr-msg-search-btn:disabled {
  opacity: 0.4;
  cursor: default;
}

.nr-msg--hit {
  outline: 2px solid rgba(99, 102, 241, 0.7);
  border-radius: 10px;
}

.nr-msg-search-open {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 14px;
}

.nr-tool-background {
  margin: 8px 0;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid rgba(245, 158, 11, 0.4);
  background: rgba(245, 158, 11, 0.08);
  color: #b45309;
  font-size: 12px;
}
</style>
