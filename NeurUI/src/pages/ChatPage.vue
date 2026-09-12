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

    <!-- Left Sidebar: Sessions（拆分组件，2026-09-08） -->
    <ChatSessionSidebar
      v-if="!isMainLayout"
      @switch="switchSession"
      @open-msg-search="openMsgSearch"
      @cross-search="crossSearchOpen = true"
    />

    <!-- Main Chat Area -->
    <main class="nr-chat-main">
      <!-- Page Header (when inside MainLayout) -->
      <div v-if="isMainLayout" class="nr-chat-page-header">
        <div class="nr-chat-header-left">
          <!-- 静态会话标题：切换会话走右侧历史面板（下拉菜单已移除，功能重叠） -->
          <span class="nr-chat-header-title">{{ currentSessionTitle || t('chat.noSessions') }}</span>
        </div>
        <div class="nr-chat-header-actions">
          <button
            class="nr-chat-toggle-btn"
            :title="t('chat.crossSearchTitle')"
            @click="crossSearchOpen = true"
          >
            <UiIcon name="globe" :size="15" />
          </button>
          <button class="nr-chat-toggle-btn" @click="toggleHistoryPanel" :title="t('chat.history')">
            {{ isHistoryTabActive ? '›' : '‹' }}
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

      <div class="nr-chat-messages" ref="messagesRef" @scroll="onMessagesScroll">
        <div v-if="messages.length === 0" class="nr-chat-empty">
          <div v-if="isMainLayout && !agentId" class="nr-chat-empty">
            <div class="nr-chat-empty-icon"><UiIcon name="chat" :size="44" /></div>
            <h3>{{ t('nav.chat') }}</h3>
            <p>{{ t('chat.selectAgentFirst') }}</p>
          </div>
          <div v-else class="nr-chat-empty">
            <div class="nr-chat-empty-icon"><UiIcon name="monitor" :size="44" /></div>
            <h3>{{ currentAgent?.name || t('agent.title') }}</h3>
            <p>{{ t('chat.placeholder') }}</p>
          </div>
        </div>

        <div
          v-for="(msg, idx) in renderedMessages"
          :id="`nr-msg-${absIdx(idx)}`"
          :key="msgKey(msg, absIdx(idx))"
          class="nr-msg"
          :class="[`nr-msg--${msg.role}`, { 'nr-msg--hit': msgSearchHits.includes(absIdx(idx)) && absIdx(idx) === msgSearchCursor, 'nr-msg--checkpoint': msg.checkpoint }]"
        >
          <div class="nr-msg-avatar"><UiIcon :name="msg.role === 'user' ? 'chat' : 'monitor'" :size="16" /></div>
          <div class="nr-msg-body">
            <!-- 钩子/检查点标记（ZCode checkpoint 对齐） -->
            <div v-if="msg.checkpoint" class="nr-msg-checkpoint-badge" :title="t('chat.checkpointSet')"><UiIcon name="anchor" :size="12" /> {{ t('chat.checkpoint') }}</div>
            <!-- 流式状态条（三需求①）：理解→思考→工具→输出，进行中扫光 -->
            <div v-if="msg.streaming" class="nr-stream-status" :data-phase="deriveStreamPhase(msg)">
              <span class="nr-stream-status-icon"><UiIcon :name="streamPhaseMeta(deriveStreamPhase(msg)).icon" :size="13" /></span>
              <span class="nr-stream-status-label">{{ streamPhaseMeta(deriveStreamPhase(msg)).label }}</span>
              <span class="nr-stream-status-shimmer" />
            </div>
            <!-- 429 重试/切换倒计时（ZCode 对齐）：限流等待/模型切换提示条 -->
            <div v-if="msg.retryNotice" class="nr-retry-notice">
              <span class="nr-retry-notice-icon"><UiIcon name="radar" :size="13" /></span>
              <span class="nr-retry-notice-label">{{ retryNoticeText(msg) }}</span>
            </div>

            <!-- 步骤化时间轴（三需求②）：推理/工具按到达顺序成段，独立折叠 -->
            <div v-if="msg.steps && msg.steps.length > 0" class="nr-steps-timeline">
              <div
                v-for="step in msg.steps"
                :key="step.id"
                class="nr-step-item"
                :class="[`nr-step--${step.kind}`, { 'is-active': step.active, 'is-open': step.open }]"
              >
                <div class="nr-step-header" @click="toggleStep(msg.steps!, step.id)">
                  <span class="nr-step-icon"><UiIcon :name="step.kind === 'reasoning' ? 'brain' : variantIcon(toolCardVariant(step.name))" :size="14" /></span>
                  <span class="nr-step-title">{{ step.kind === 'reasoning' ? t('chat.stepThinking') : (step.taskName || step.name) }}</span>
                  <span v-if="step.active" class="nr-step-badge is-running">{{ t('chat.stepRunning') }}</span>
                  <span v-else-if="step.kind === 'tool'" class="nr-step-badge" :class="!step.result || isToolFailureResult(step.result) ? 'is-error' : 'is-done'">
                    {{ !step.result ? t('chat.stepNoResult') : isToolFailureResult(step.result) ? t('chat.toolFailed') : t('chat.toolDone') }}
                  </span>
                  <span v-if="stepDurationText(step)" class="nr-step-duration">{{ stepDurationText(step) }}</span>
                  <span class="nr-step-toggle">{{ step.open ? '▾' : '▸' }}</span>
                </div>
                <div v-show="step.open" class="nr-step-body">
                  <template v-if="step.kind === 'reasoning'">
                    <div class="nr-step-reasoning" @scroll="onReasoningScroll">{{ step.text }}</div>
                  </template>
                  <template v-else>
                    <pre class="nr-tool-args">{{ formatJSON(step.arguments) }}</pre>
                    <div v-if="isBackgroundResult(step.result)" class="nr-tool-background">
                      {{ t('chat.toolBackgroundHint') }}
                    </div>
                    <div v-if="step.result" class="nr-tool-result">
                      <div class="nr-tool-result-header">
                        {{ t('chat.toolResult') }}
                        <button
                          class="nr-tool-result-preview-btn"
                          :title="t('chat.openInPreview')"
                          @click.stop="openToolResultArtifacts(step.result)"
                        ><UiIcon name="eye" :size="12" /></button>
                      </div>
                      <pre class="nr-tool-result-content">{{ step.result }}</pre>
                    </div>
                  </template>
                </div>
              </div>
            </div>

            <!-- Legacy reasoning block（旧消息无 steps 时兜底） -->
            <div v-if="!msg.steps?.length && msg.reasoning" class="nr-msg-reasoning">
              <div class="nr-reasoning-header" @click="msg.reasoningOpen = !msg.reasoningOpen">
                <span>💭 {{ t('chat.reasoning') }}</span>
                <span class="nr-reasoning-toggle">{{ msg.reasoningOpen ? '▾' : '▸' }}</span>
              </div>
              <div v-show="msg.reasoningOpen" class="nr-reasoning-content">
                {{ msg.reasoning }}
              </div>
            </div>

            <!-- Legacy tool call blocks（旧消息无 steps 时兜底，含历史兼容单工具） -->
            <template v-if="!msg.steps?.length && legacyToolList(msg).length > 0">
              <div v-for="(tc, tcIdx) in legacyToolList(msg)" :key="tcIdx" class="nr-msg-tool-call">
                <div class="nr-tool-header" @click="msg.toolOpen = !msg.toolOpen">
                  <span class="nr-tool-icon"><UiIcon :name="variantIcon(toolCardVariant(tc.name))" :size="14" /></span>
                  <span class="nr-tool-name">{{ tc.name }}</span>
                  <a-tag :color="isBackgroundResult(tc.result) ? 'warning' : isToolFailureResult(tc.result) ? 'error' : tc.result ? 'success' : 'processing'">
                    {{ isBackgroundResult(tc.result) ? t('chat.toolBackground') : isToolFailureResult(tc.result) ? t('chat.toolFailed') : tc.result ? t('chat.toolDone') : t('chat.toolCalling') }}
                  </a-tag>
                  <span class="nr-tool-toggle">{{ msg.toolOpen ? '▾' : '▸' }}</span>
                </div>
                <div v-show="msg.toolOpen">
                  <pre class="nr-tool-args">{{ formatJSON(tc.arguments) }}</pre>
                  <div v-if="isBackgroundResult(tc.result)" class="nr-tool-background">
                    {{ t('chat.toolBackgroundHint') }}
                  </div>
                  <div v-if="tc.result" class="nr-tool-result">
                    <div class="nr-tool-result-header">
                      {{ t('chat.toolResult') }}
                      <button
                        class="nr-tool-result-preview-btn"
                        :title="t('chat.openInPreview')"
                        @click.stop="openToolResultArtifacts(tc.result)"
                      ><UiIcon name="eye" :size="12" /></button>
                    </div>
                    <pre class="nr-tool-result-content">{{ tc.result }}</pre>
                  </div>
                </div>
              </div>
            </template>

            <!-- Edit mode（编辑最后一条用户消息）：内联编辑框替换消息内容 -->
            <div v-if="isEditingMessage(absIdx(idx))" class="nr-msg-edit">
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
                @click="onAttachmentClick(file)"
              >
                <img
                  v-if="file.type?.startsWith('image/')"
                  :src="file.preview"
                  :alt="file.name"
                  class="nr-attachment-img"
                />
                <span v-else class="nr-attachment-file-icon"><UiIcon :name="getFileIcon(file.type)" :size="16" /></span>
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
                <span class="nr-audio-time">
                  {{ msg.ttsUrls ? `${(msg.ttsIdx || 0) + 1}/${msg.ttsUrls.length}` : formatAudioTime(msg.audioCurrentTime || 0) }}
                </span>
                <button class="nr-audio-speed-btn" @click="cycleAudioSpeed(msg)">
                  {{ msg.audioSpeed || 1 }}x
                </button>
              </div>
              <!-- Hidden audio element（句块回放：src 随 ttsIdx 逐句切换） -->
              <audio
                :ref="(el) => setAudioRef(msg, el as HTMLAudioElement)"
                :src="audioSourceFor(msg)"
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
              <button v-if="!msg.ttsUrls" class="nr-tts-btn" @click="synthesizeTTS(msg)" :disabled="msg.ttsLoading">
                <UiIcon v-if="msg.ttsLoading" name="clock" :size="14" /><UiIcon v-else name="audio" :size="14" />
                <span>{{ msg.ttsLoading ? t('chat.ttsLoading') : t('chat.playTTS') }}</span>
              </button>
            </div>

            <!-- 产出物卡片（回答结尾）：本轮真实产出，可收纳展开 + 审验/预览 -->
            <ArtifactCard
              v-if="msg.role === 'assistant' && msg.artifacts && msg.artifacts.length > 0"
              :artifacts="msg.artifacts"
              @review="reviewArtifact"
              @open="openMessageArtifact"
            />

            <!-- Message footer: 时间 + 操作条（复制 / 点赞点踩 / 编辑 / 删除轮次） -->
            <div v-if="!msg.streaming && !isEditingMessage(absIdx(idx))" class="nr-msg-footer">
              <span v-if="displayTime(msg)" class="nr-msg-time">{{ displayTime(msg) }}</span>
              <span class="nr-msg-footer-spacer" />
              <button class="nr-msg-action" :title="t('chat.copy')" @click="copyMessage(msg)"><UiIcon name="copy" :size="14" /></button>
              <template v-if="msg.role === 'assistant'">
                <button
                  class="nr-msg-action"
                  :title="t('chat.regenerate')"
                  @click="regenerateLastRound"
                ><UiIcon name="refresh" :size="14" /></button>
                <button
                  class="nr-msg-action"
                  :class="{ 'nr-msg-action--active': msg.feedback === 'like' }"
                  :title="t('chat.like')"
                  @click="rateReply(msg, 'like')"
                ><UiIcon name="like" :size="14" /></button>
                <button
                  class="nr-msg-action"
                  :class="{ 'nr-msg-action--active-negative': msg.feedback === 'dislike' }"
                  :title="t('chat.dislike')"
                  @click="rateReply(msg, 'dislike')"
                ><UiIcon name="dislike" :size="14" /></button>
                <button
                  class="nr-msg-action"
                  :title="t('chat.forkFromHere')"
                  @click="forkFromMessage(msg)"
                ><UiIcon name="fork" :size="14" /></button>
                <button
                  class="nr-msg-action"
                  :class="{ 'nr-msg-action--active': msg.checkpoint }"
                  :title="msg.checkpoint ? t('chat.checkpointRemove') : t('chat.checkpointSet')"
                  @click="toggleCheckpoint(msg)"
                ><UiIcon name="anchor" :size="14" /></button>
              </template>
              <template v-else>
                <button
                  class="nr-msg-action"
                  :title="t('chat.forkFromHere')"
                  @click="forkFromMessage(msg)"
                ><UiIcon name="fork" :size="14" /></button>
                <button
                  class="nr-msg-action"
                  :class="{ 'nr-msg-action--active': msg.checkpoint }"
                  :title="msg.checkpoint ? t('chat.checkpointRemove') : t('chat.checkpointSet')"
                  @click="toggleCheckpoint(msg)"
                ><UiIcon name="anchor" :size="14" /></button>
                <button
                  v-if="isLastUserMessage(absIdx(idx))"
                  class="nr-msg-action"
                  :title="t('chat.editMessage')"
                  @click="startEditMessage(absIdx(idx))"
                ><UiIcon name="edit" :size="14" /></button>
              </template>
              <a-popconfirm
                v-if="msg.role === 'user'"
                :title="t('chat.deleteRoundConfirm')"
                :ok-text="t('common.confirm')"
                :cancel-text="t('common.cancel')"
                @confirm="deleteRoundAt(absIdx(idx))"
              >
                <button class="nr-msg-action nr-msg-action--danger" :title="t('chat.deleteRound')"><UiIcon name="trash" :size="14" /></button>
              </a-popconfirm>
            </div>

            <!-- Streaming indicator -->
            <div v-if="msg.streaming && !msg.content && !(msg.steps?.length)" class="nr-msg-streaming">
              <span class="nr-typing-dot" /><span class="nr-typing-dot" /><span class="nr-typing-dot" />
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区（Composer + 工具条 + 429/事件丢失横幅，2026-09-08 拆分） -->
      <ChatComposerArea
        @send="sendMessage()"
        @stop="stopStreaming()"
        @send-queued-now="onSendQueuedNow"
        @slash-plan="onSlashPlan"
        @slash-compact="onSlashCompact"
      />


      <!-- 蜂群子 Agent 对话小窗（右下角堆叠，可最小化） -->
      <SubAgentWindowStack />
    </main>

    <!-- 右侧多标签 dock（2026-09-08）：产物文档/历史会话/存档/电脑分屏统一容器，
         左缘可拖拽调宽；tabs 全空时整体不渲染 -->
    <RightDock :agent-id="agentId" @switch="switchSession" @cross-search="crossSearchOpen = true" />

    <!-- 跨会话全文搜索（QwenPaw ChatSearchPanel 对齐） -->
    <CrossSessionSearch
      :open="crossSearchOpen"
      :sessions="sessions"
      @close="crossSearchOpen = false"
      @jump="onCrossSearchJump"
    />

    <!-- 会话重命名弹窗（侧栏与 dock 历史 tab 共用，状态在 useSessionOps） -->
    <SessionRenameModal />

    <!-- Governance Approval Modal (P0: ASK 人工确认，状态在 useGovernanceApproval) -->
    <GovernanceApprovalModal />

    <!-- 计划模式面板（/plan）：澄清问答 → MD 计划预览 → 审批执行 -->
    <PlanPanel
      :open="planPanelOpen"
      :agent-id="agentId || 'default'"
      :initial-request="planRequestSeed"
      @close="planPanelOpen = false"
      @approved="onPlanApproved"
    />

    <!-- 流式实时语音：常驻隐藏 live 播放器。src 逐句切换，播完自动推进下一句 -->
    <audio
      class="nr-live-tts-audio"
      :ref="(el) => setLiveTtsAudioRef(el as HTMLAudioElement | null)"
      :src="liveTtsUrl"
      @ended="onLiveTtsEnded"
      @error="onLiveTtsError"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { useAgentPage } from '@/composables/useAgentPage'
import { useASRRestartGuard } from '@/composables/useASRRestartGuard'
import { useAppStore } from '@/stores/app'
import { useAgentStore } from '@/stores/agents'
import { useChatStore } from '@/stores/chat'
import { useMessageQueueStore } from '@/stores/messageQueue'
import { useSessionSendLock } from '@/composables/useSessionSendLock'
import { StreamTTSRunner, audioSourceFor, requireNonEmptyAudioBlob, prepareSpeechText, createSpeechAnnouncer, toolAnnouncementText, type SpeechAnnouncer } from '@/composables/useStreamTTS'
import { useTtsAudioGate } from '@/composables/useTtsAudioGate'
import { isDefaultChatTitle } from '@/utils/sessionTitle'
import { useRouter } from 'vue-router'
import { useChat } from '@/composables/useChat'
import { reorderConsoleSessions } from '@/api/modules/console'
import type { ChatMessage, Session, PendingFile } from '@/types/chat'
import { api } from '@/api'
import { extractUploadedFileId } from '@/api/modules/files'
import { useGovernanceApproval } from '@/composables/useGovernanceApproval'
import { secureStorage } from '@/utils/security'
import { renderMarkdown } from '@/utils/markdown'
import { revokeMessageBlobUrls } from '@/utils/blobUrls'
import { openArtifactTab, openCodeBlockTab, openFileTab, openImageTab, openToolResultArtifacts, artifactFromEvent, artifactsFromToolResult, mergeMessageArtifacts, openMessageArtifact, type ArtifactEventPayload, type MessageArtifact } from '@/utils/artifacts'
import ArtifactCard from '@/components/chat/ArtifactCard.vue'
import { uiMessage } from '@/utils/message'
import { resolveI18nMessage } from '@/utils/i18n'
import GlassButton from '@/components/GlassButton.vue'
import GlassInput from '@/components/GlassInput.vue'
import UiIcon from '@/components/UiIcon.vue'

import SubAgentWindowStack from '@/components/chat/SubAgentWindowStack.vue'
import SessionRenameModal from '@/components/chat/SessionRenameModal.vue'
import ChatSessionSidebar from '@/components/chat/ChatSessionSidebar.vue'
import ChatComposerArea from '@/components/chat/ChatComposerArea.vue'
import GovernanceApprovalModal from '@/components/chat/GovernanceApprovalModal.vue'
import RightDock from '@/components/chat/dock/RightDock.vue'
import ContextUsageIndicator from '@/components/chat/ContextUsageIndicator.vue'
import QueuedMessageCards from '@/components/chat/QueuedMessageCards.vue'
import PlanPanel from '@/components/chat/PlanPanel.vue'
import CrossSessionSearch from '@/components/chat/CrossSessionSearch.vue'
import { useComputerPanel, isComputerTool, } from '@/composables/useComputerPanel'
import { useRightDockStore } from '@/stores/rightDock'
import { useSessionOps } from '@/composables/useSessionOps'
import { registerRateLimitSwitchHook, useChatModels } from '@/composables/useChatModels'
import { usePendingFiles } from '@/composables/usePendingFiles'
import { useASRRecording } from '@/composables/useASRRecording'
import { useAutoVoice } from '@/composables/useAutoVoice'
import { useSlashCommands, setupSlashCommands } from '@/composables/useSlashCommands'
import { useSubAgentWindows } from '@/composables/useSubAgentWindows'
import { toolCardVariant, variantIcon, variantColor } from '@/utils/toolCardVariant'
import { useThinkingEffort } from '@/composables/useThinkingEffort'
import { useMermaidRenderer } from '@/composables/useMermaidRenderer'
import { useChatDraft } from '@/composables/useChatDraft'
import { useInputHistory } from '@/composables/useInputHistory'
import { useIMEComposition } from '@/composables/useIMEComposition'
import { isBackgroundResult, isToolFailureResult } from '@/utils/toolCallStatus'
import { findMessageMatches } from '@/utils/messageSearch'
import {
  appendReasoningStep,
  appendToolStep,
  attachToolResult,
  finishAllSteps,
  buildStepsFromHistory,
  toggleStep,
  deriveStreamPhase,
  followActiveReasoningScroll,
  isNearBottom,
  type ChatStep,
} from '@/utils/chatSteps'
import { createQueueDrainer } from '@/utils/queueDrain'
import type { ThinkingEffort } from '@/composables/useThinkingEffort'
import { useSessionSync } from '@/composables/useSessionSync'
import { listModels } from '@/api/modules/models'
import { listProviders } from '@/api/modules/providers'
import { normalizeModel } from '@/types/model'

// 顶入卡片编辑态（queued edit）→ 已收敛进 ChatComposerArea（2026-09-08）

// ---------------------------------------------------------------------------
// Store-backed domain state（ADR 0008）+ 页面编排状态（2026-09-08 重建段）
// ---------------------------------------------------------------------------
const { t } = useI18n()
const appStore = useAppStore()
const agentStore = useAgentStore()
const { agentId, currentAgent } = useAgentPage()

const props = defineProps<{
  layoutMode?: 'chat' | 'main'
}>()

const isMainLayout = computed(() => props.layoutMode === 'main')

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

const messagesRef = ref<HTMLElement | null>(null)
const sidebarCollapsed = computed(() => appStore.sidebarCollapsed)

// ── 右侧多标签 dock（收编历史/存档/电脑分屏 + 产物预览）─────────
const rightDock = useRightDockStore()
const isHistoryTabActive = computed(() => rightDock.activeTabId === 'history')
function toggleHistoryPanel(): void {
  if (rightDock.activeTabId === 'history') {
    rightDock.closeTab('history')
  } else {
    rightDock.openHistory()
  }
}

// ── 思考程度（持久化 localStorage，随消息发给后端）──────────────
const { effort: thinkingEffort, setEffort: setThinkingEffort } = useThinkingEffort()

// ── 蜂群子 Agent 浮窗（WS subagent_* 事件 → useSubAgentWindows）──
const { handleSubAgentSyncEvent, clearSubAgentWindows } = useSubAgentWindows()

function onSessionSyncEvent(event: { event_type: string; payload: Record<string, unknown> }) {
  // 电脑操作实时事件 → 分屏面板（不携带 subagent_id，先于子 Agent 分支处理）
  if (event.event_type === 'computer_action') {
    computerPanel.handleComputerAction(event.payload)
    return
  }
  handleSubAgentSyncEvent(event)
}

// 实时事件丢失提示（seq gap 检测，OpenOcta P0-1）：计数入 chatStore（composer 读）
function onSyncGap(missed: number) {
  chatStore.bumpEventsLost(missed)
}

// ── 电脑操作分屏（useComputerPanel 共享单例，自动开屏走 rightDock）──
const computerPanel = useComputerPanel()
const computerPanelState = computerPanel.state

useSessionSync(() => currentSessionId.value, onSessionSyncEvent, { onGap: onSyncGap })

// ── 页面级 UI 临时态 ──────────────────────────────────────
const isDragOver = ref(false)
let dragCounter = 0

const ttsAvailable = ref(true) // assume available, verify on mount

// 计划模式（/plan）：面板开关 + 初始需求种子；会话态收敛在 PlanPanel 内部
const planPanelOpen = ref(false)
const planRequestSeed = ref('')

function onPlanApproved(executePrompt: string): void {
  planPanelOpen.value = false
  // 审批通过 → 计划全文（execute_prompt）走 sendMessage 原链路执行
  // （含流式/排队/锁互斥全部既有语义，零管线改动）
  chatStore.setInputText(executePrompt)
  void sendMessage()
}

/** /plan 斜杠命令（ChatComposerArea emit 上抛）：打开计划面板并注入需求种子 */
function onSlashPlan(seed: string): void {
  planRequestSeed.value = seed
  planPanelOpen.value = true
}

/** /compact 斜杠命令（ChatComposerArea emit 上抛）：经 sendMessage 原链路
 *  发往后端命令分发（报告为该轮回复；流式/排队/锁互斥全复用） */
function onSlashCompact(): void {
  chatStore.setInputText('/compact')
  void sendMessage()
}

/** 「↑ 立即」排队项（ChatComposerArea emit 上抛）：走 drain force 入口 */
function onSendQueuedNow(id: string): void {
  messageQueue.moveToTop(id)
  if (isStreaming.value || _queueDrainer.isDraining()) {
    uiMessage.info(t('chat.queueTopAuto'))
    return
  }
  void drainMessageQueue(true, currentSessionId.value)
}

// 治理审批弹窗（P0: ASK 人工确认）→ 状态机收敛在 useGovernanceApproval
const { approvalModal, openApprovalModal, confirmApproval, rejectApproval } = useGovernanceApproval()

// 斜杠命令面板（共享单例；命令注册表在 ChatComposerArea 组装）
const { closeSlashPanel } = useSlashCommands()

// ── 模型切换器 / 429 横幅 / 待传附件（共享单例 composables）──────
const {
  chatModelOptions,
  selectedModel,
  rateLimitBanner,
  handleRateLimit,
  loadChatModels,
  noModelsHint,
} = useChatModels()
const { pendingFiles } = usePendingFiles()

// ── 会话操作共享层（侧栏与 dock 历史/存档 tab 共用）─────────────
const {
  renameModal,
  groupedSessions,
  onSessionDragStart,
  onSessionDrop,
  dragOver,
  togglePin,
  archiveSession,
  createSession,
  renameSession,
} = useSessionOps()
const dragOverSessionId = dragOver

// ── ASR（共享单例：composer 录音 UI 与本页 sendMessage 共享）──────
const { asrAvailable, isRecording, initASR, stopRecording, syncLocale } = useASRRecording()

// ── 流式实时 TTS（live 播放器接线；autoVoice 开关为共享单例）──────
const { autoVoice, toggleAutoVoice: _toggleAutoVoice } = useAutoVoice()
function toggleAutoVoice(): void {
  _toggleAutoVoice(() => streamTTSRunner?.abort())
}
let streamTTSRunner: StreamTTSRunner | null = null
// live 播放：专用 audio 元素顺序播句子块；结束后由模板 onended 推进
const liveTtsUrl = ref('')
const liveTtsQueue = ref<string[]>([])
const liveTtsIdx = ref(0)
const liveTtsAudio = ref<HTMLAudioElement | null>(null)


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
  // 会话分叉 / 消息钩子（ZCode fork/checkpoint 对齐）
  forkSession: _forkSession,
  setCheckpoint: _setCheckpoint,
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

// 补课 A4：跨标签单发送者锁（同 session 多标签只有一个能发）
const { isOwner: isSendLockOwner } = useSessionSendLock(currentSessionId)

// 补课 A6：长会话窗口化渲染（虚拟列表轻量版）——超过阈值只渲染尾部
// WINDOW+BUFFER 条，向上滚动到顶部附近再向前扩窗（保留原生滚动条，
// 不引入固定高度虚拟库——消息高度差异大，库方案需全量预测量）。
const RENDER_WINDOW = 60
const RENDER_BUFFER = 30
const renderStart = ref(0)

const renderedMessages = computed(() => {
  const all = messages.value
  // F-07：getter 内禁止写 renderStart（写后又读同一 ref → computed 自依赖，
  // 可能递归更新）。短列表归零由下方 messages.length watch 负责。
  if (all.length <= RENDER_WINDOW + RENDER_BUFFER) {
    return all
  }
  const start = Math.max(0, Math.min(renderStart.value, all.length - RENDER_WINDOW))
  return all.slice(start, start + RENDER_WINDOW)
})

/** 窗口相对下标 → messages 绝对下标（DATA-P0-5 根因修复：
 *  renderedMessages 是 slice 切片，deleteRoundAt 等用绝对下标索引）。 */
function absIdx(windowIdx: number): number {
  return renderStart.value + windowIdx
}

// P2-9（审计 2026-09-11）：v-for key 用消息稳定键——旧实现 key=绝对下标，
// 上滚扩窗（renderStart 前移）后整窗 key 全变 → DOM 全量重建、滚动锚点跳动。
// timestamp 同轮共享（user+assistant 同戳），按 role 组合；无 timestamp 回退下标。
function msgKey(msg: ChatMessage, idx: number): string {
  return msg.timestamp ? `${msg.timestamp}-${msg.role}` : `idx-${idx}`
}

// ── 流式状态条 + 步骤时间轴 helpers（2026-09-07 三需求①②） ─────────────

/** 流式阶段 → 图标 + i18n 标签。 */
function streamPhaseMeta(phase: ReturnType<typeof deriveStreamPhase>): { icon: string; label: string } {
  switch (phase) {
    case 'understanding':
      return { icon: 'radar', label: t('chat.phaseUnderstanding') }
    case 'thinking':
      return { icon: 'brain', label: t('chat.phaseThinking') }
    case 'tool':
      return { icon: 'wrench', label: t('chat.phaseTool') }
    case 'output':
      return { icon: 'edit', label: t('chat.phaseOutput') }
  }
}

/** 段落耗时文案（"持续 N 秒"；未封口的活跃段按当前时刻计）。 */
function stepDurationText(step: ChatStep): string {
  if (!step.startedAt) return ''
  const end = step.endedAt ?? Date.now()
  const secs = Math.max(1, Math.round((end - step.startedAt) / 1000))
  return t('chat.stepDuration', { n: secs })
}

/** 旧消息（无 steps）的兜底工具列表：toolCalls 优先，legacy 单工具次之。 */
function legacyToolList(
  msg: ChatMessage,
): Array<{ name: string; arguments: string; result?: string }> {
  if (msg.toolCalls && msg.toolCalls.length > 0) return msg.toolCalls
  if (msg.toolCall) return [{ ...msg.toolCall, result: msg.toolResult }]
  return []
}

// ── 429 重试/切换倒计时（ZCode 对齐，2026-09-11）─────────────────────────

const retryTickNow = ref(Date.now())
let retryTicker: ReturnType<typeof setInterval> | null = null

/** 每秒驱动倒计时；无任何活跃提示时自停。 */
function startRetryTicker(): void {
  if (retryTicker) return
  retryTicker = setInterval(() => {
    retryTickNow.value = Date.now()
    if (!messages.value.some((m) => m.retryNotice)) stopRetryTicker()
  }, 1000)
}

function stopRetryTicker(): void {
  if (retryTicker) {
    clearInterval(retryTicker)
    retryTicker = null
  }
}

/** 流式恢复/结束 → 清除倒计时提示。 */
function clearRetryNotice(msg: ChatMessage): void {
  if (msg.retryNotice) {
    msg.retryNotice = undefined
    stopRetryTicker()
  }
}

/** 提示条文案：等待倒计时 / 已切换模型 / 全部耗尽，i18n 组装。 */
function retryNoticeText(msg: ChatMessage): string {
  const n = msg.retryNotice
  if (!n) return ''
  if (n.phase === 'waiting') {
    const elapsed = n.receivedAt ? Math.floor((retryTickNow.value - n.receivedAt) / 1000) : 0
    const remain = Math.max(0, Math.round((n.remainingSeconds ?? 0) - elapsed))
    return t('chat.retryWaiting', { retry: n.retry ?? 0, max: n.maxRetries ?? 0, seconds: remain })
  }
  if (n.phase === 'switched') {
    return t('chat.retrySwitched', {
      model: n.model ?? '',
      count: n.failCount ?? 0,
      total: n.maxSwitches ?? 0,
    })
  }
  return t('chat.retryExhausted', { count: n.failCount ?? 0 })
}

watch(
  () => messages.value.length,
  (len, prev) => {
    if (len <= RENDER_WINDOW + RENDER_BUFFER) {
      renderStart.value = 0
      return
    }
    if (renderStart.value + RENDER_WINDOW >= (prev ?? len)) {
      renderStart.value = Math.max(0, len - RENDER_WINDOW)
    }
  },
)

/** 上滚扩窗：滚动接近容器顶且窗口前还有未渲染消息 → 前扩 BUFFER 条。 */
function onMessagesScroll(): void {
  const el = messagesRef.value
  if (!el) return
  if (
    el.scrollTop < 120 &&
    renderStart.value > 0 &&
    messages.value.length > RENDER_WINDOW + RENDER_BUFFER
  ) {
    renderStart.value = Math.max(0, renderStart.value - RENDER_BUFFER)
  }
}

// 补课 A4：跨标签单发送者锁（同 session 多标签只有一个能发）

/** 窗口相对下标 → messages 绝对下标（DATA-P0-5 根因修复：
 *  renderedMessages 是 slice 切片，deleteRoundAt 等用绝对下标索引）。 */


let abortController: AbortController | null = null

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

/**
 * 审验产出物：强制源码形态开 dock tab（text kind 走 TextPanel 源码审读），
 * 与「打开」的渲染预览区分——审验看源，打开看效果。
 */
function reviewArtifact(artifact: MessageArtifact): void {
  const dock = useRightDockStore()
  dock.openTab({
    id: `review:${artifact.name || artifact.path || artifact.artifactId || ''}`,
    kind: 'text',
    title: artifact.name || artifact.path || '',
    icon: 'fileText',
    data: {
      artifactId: artifact.artifactId,
      path: artifact.path,
    },
  })
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

/**
 * 重新生成（QwenPaw regenerate 对齐）：以最后一轮用户消息原文重发。
 * 复用"删旧轮+重发"契约（与编辑重发同链路）：删除旧轮（后端清 session
 * 记录+该轮记忆+agent 内存历史）→ 原文经 sendMessage 原链路重写新轮。
 */
async function regenerateLastRound(): Promise<void> {
  if (isStreaming.value) return
  // 从尾部找最后一条 user 消息
  let userIdx = -1
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].role === 'user') {
      userIdx = i
      break
    }
  }
  if (userIdx < 0) return
  const userMsg = messages.value[userIdx]
  const text = (userMsg.content || '').trim()
  if (!text || !agentId.value || !currentSessionId.value) return
  if (!userMsg.timestamp) {
    uiMessage.error(t('chat.deleteRoundFailed'))
    return
  }
  if (!isSendLockOwner.value) {
    uiMessage.warning(t('chat.anotherTabSending'))
    return
  }
  const result = await _deleteRound(currentSessionId.value, userMsg.timestamp)
  if (!result.ok) {
    uiMessage.error(t('chat.deleteRoundFailed'))
    return
  }
  chatStore.removeRoundFrom(userIdx)
  chatStore.setInputText(text)
  await sendMessage()
}

/**
 * 会话分叉（ZCode fork 对齐）：从该消息处（含）截取历史复制为新会话并切换。
 * 消息级操作：msg.timestamp 即截取定位键。
 */
let forkInFlight = false
async function forkFromMessage(msg: ChatMessage): Promise<void> {
  if (!currentSessionId.value || !msg.timestamp || isStreaming.value) return
  if (forkInFlight) return // 防连点重复分叉
  forkInFlight = true
  try {
    const result = await _forkSession(currentSessionId.value, msg.timestamp)
    if (!result.ok) {
      uiMessage.error(t('chat.forkFailed'))
      return
    }
    // 刷新会话列表并切到分叉出的新会话（历史加载走 switchSession 既有链路）
    await _loadSessions(agentId.value)
    const switchResult = await _switchSession(result.newSessionId)
    _notifySwitchFailure(switchResult)
    chatStore.setInputText(chatDraft.restore(result.newSessionId))
    scrollToBottomForHistory()
    uiMessage.success(t('chat.forkDone'))
  } finally {
    forkInFlight = false
  }
}

/** 设置/移除消息钩子（checkpoint）：乐观更新，失败回滚。 */
async function toggleCheckpoint(msg: ChatMessage): Promise<void> {
  if (!currentSessionId.value || !msg.timestamp) return
  const next = !msg.checkpoint
  msg.checkpoint = next
  const ok = await _setCheckpoint(currentSessionId.value, msg.timestamp, next)
  if (!ok) msg.checkpoint = !next
}

// ---------------------------------------------------------------------------
/** 加载当前 agent 的 session 列表(模板 onMounted / agentId watch 调用)。
 *  BUG-11 修复：发起时记录 agentId，写 store 前校验归属——
 *  快速切 agent 时旧响应后到会覆盖新 agent 的会话列表。 */
async function loadSessions(): Promise<void> {
  const requestedAgent = agentId.value
  await _loadSessions(requestedAgent)
  if (agentId.value !== requestedAgent) return
}

async function switchSession(sessionId: string): Promise<void> {
  // BUG-2 修复：流式中切走先 abort 旧流并复位 streaming 态，
  // 否则 usage 记账/队列 drain 会污染刚打开的新会话
  if (isStreaming.value) {
    abortController?.abort()
    abortController = null
    chatStore.setStreaming(false)
    stopStreamTTS()
  }
  // 顶入编辑态跨会话失效 → ChatComposerArea 内 watch(currentSessionId) 统一处理
  // BUG-4 修复：restore 前先保存旧会话草稿（原实现只在组件卸载时保存，
  // 切会话即丢）
  const prevSid = currentSessionId.value
  if (prevSid && prevSid !== sessionId) {
    chatDraft.save(prevSid, inputText.value)
  }
  const result = await _switchSession(sessionId)
  _notifySwitchFailure(result)
  // 补课 D：恢复新会话草稿；补课 A6+F：历史会话打开定位到最新记录
  chatStore.setInputText(chatDraft.restore(sessionId))
  scrollToBottomForHistory()
}

// 跨会话全文搜索（QwenPaw ChatSearchPanel 对齐）
// ---------------------------------------------------------------------------
const crossSearchOpen = ref(false)

/** 跳转命中：切会话 → 历史加载后按关键词滚动定位第一条命中消息。 */
async function onCrossSearchJump(sessionId: string, keyword: string): Promise<void> {
  crossSearchOpen.value = false
  if (sessionId !== currentSessionId.value) {
    await switchSession(sessionId)
  }
  void nextTick(() => {
    void scrollToFirstHit(sessionId, keyword)
  })
}

/** 在已加载历史里定位含关键词的消息并滚动（找不到则仅贴底）。 */
async function scrollToFirstHit(sessionId: string, keyword: string): Promise<void> {
  if (currentSessionId.value !== sessionId) return
  // 历史加载是异步的，给一帧缓冲后尝试定位（最多重试 3 次）
  for (let attempt = 0; attempt < 3; attempt++) {
    const idx = messages.value.findIndex((m) =>
      String(m.content || '').toLowerCase().includes(keyword.toLowerCase()),
    )
    if (idx >= 0) {
      // P2-10：窗口化渲染下命中可能在窗口外（未渲染，getElementById 必空）
      // ——先扩窗再取元素（与 jumpToMatch 同法）
      if (idx < renderStart.value) {
        renderStart.value = Math.max(0, idx - RENDER_BUFFER)
      }
      await nextTick()
      const el = document.getElementById(`nr-msg-${idx}`)
      if (el) {
        el.scrollIntoView({ block: 'center' })
        return
      }
    }
    await new Promise((r) => setTimeout(r, 250))
  }
  scrollToBottom()
}
// 429 限流识别/横幅切换 → 已收敛进 useChatModels（handleRateLimit/switchAfterRateLimit）

/**
 * 队列续发（审计①③⑯ 修复，2026-09-08）：queueDrain runner 驱动。
 * - ① P0 续发死锁：旧实现外层 drain 持 _draining 守卫 await sendMessage，
 *   sendMessage finally 的递归 drain 被守卫吞掉 → 排队 ≥2 条只发 1 条。
 *   runner 内单层 while 循环排空，递归调用降级 no-op。
 * - ③ 会话隔离：drain 启动时快照发起会话，takeNext 只取该会话排队项——
 *   流中切会话后不泄漏到新会话；会话无排队项自然空转。
 * - ⑯ paused 语义：自动续发尊重暂停；用户点「立即」走 force 入口。
 */
let _drainSessionId: string | null = null
const _queueDrainer = createQueueDrainer({
  isPaused: () => messageQueue.paused,
  takeNext: () => {
    const item = messageQueue.next(_drainSessionId || undefined)
    return item ? { id: item.id, text: item.text } : undefined
  },
  markSending: (id) => messageQueue.markSending(id),
  markSent: (id) => messageQueue.markSent(id),
  markFailed: (id, error) => messageQueue.markFailed(id, error),
  send: async (text) => {
    // drain 要占用输入框通道传文案，编辑中的草稿先退出（防覆盖/误提交）
    // 顶入编辑态取消 → ChatComposerArea 内部（drain 复用输入框通道前由 store 清空）
    chatStore.setInputText(text)
    // 审计⑪：sendMessage 的空输入/无 agent 等早退分支返回 undefined，
    // 一律按失败处理（不出队）
    return (await sendMessage()) === true
  },
})

async function drainMessageQueue(force = false, sessionId?: string | null): Promise<void> {
  _drainSessionId = sessionId ?? activeStreamSessionId ?? currentSessionId.value
  await _queueDrainer.drain(force)
}

/** 当前流所属会话快照（BUG-2 修复：usage/drain 用发起时的 session_id，
 *  流式中切会话不再把旧轮的用量/队列消息记到新会话头上）。 */
let activeStreamSessionId: string | null = null
let lastSentMessageText = ''

/**
 * 429 横幅一键切换后的闭环（ZCode 对齐）：切到候选模型 → 自动重发上一条
 * 消息继续推理，用户不再需要"点了候选却毫无反应"地手动重发。
 * 仅重发纯文本（lastSentMessageText）；附件轮由后端同模型重试/自动切换兜底。
 */
function onRateLimitSwitch(_model: string): void {
  if (isStreaming.value) return
  const text = (lastSentMessageText || '').trim()
  if (!text) return
  inputText.value = text
  void sendMessage()
}

async function sendMessage() {
  closeSlashPanel()
  const text = inputText.value.trim()
  if (!text && pendingFiles.value.length === 0) return
  // 补课 P3-b：流式中再次发送 → 入队（纯文本轮；附件轮保持丢弃语义，
  // 避免队列项携带上传会话）。done 后 drainMessageQueue 自动续发。
  if (isStreaming.value) {
    if (text && pendingFiles.value.length === 0 && agentId.value) {
      // 审计③：排队项绑定入队时会话——续发只进原会话，不跨会话泄漏
      messageQueue.enqueue(text, currentSessionId.value || undefined)
      chatStore.setInputText('')
      uiMessage.info(t('chat.queued', { n: messageQueue.countPending(currentSessionId.value || undefined) }))
    }
    return
  }
  if (!agentId.value) return
  // 补课 A4：非锁持有者标签禁止发送（同 session 多标签互斥）
  if (!isSendLockOwner.value) {
    uiMessage.warning(t('chat.anotherTabSending'))
    return
  }
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
  // 捕获流所属会话（流式中用户切走时，usage/drain 仍归属发起会话）
  activeStreamSessionId = currentSessionId.value
  lastSentMessageText = text
  chatStore.addMessage(userMsg)

  // Prepare assistant placeholder
  // assistant.timestamp = 所在轮的用户发送时刻（轮次定位键，点赞点踩用）
  const assistantMsg: ChatMessage = {
    role: 'assistant',
    content: '',
    reasoning: '',
    reasoningOpen: false,
    steps: [],
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
  // 补课：自动语音开启 → 本轮流式 TTS 会话开始（句级实时播）
  beginStreamTTS(streamingMsg)
  scrollToBottom()

  // Upload files first if any
  const fileIds: string[] = []
  for (const pf of filesToUpload) {
    try {
      const uploadRes: any = await api.upload('/files/upload', pf.file, 'file', {
        agent_id: agentId.value,
      })
      // 后端 FileInfo 契约字段是 file_id（无 id、无信封）；提取失败不得静默——
      // 缺 file_ids 会导致该轮附件整轮丢失（agent 收不到图片）
      const fid = extractUploadedFileId(uploadRes)
      if (fid) fileIds.push(fid)
      else console.error('[Chat] File upload response missing file_id:', uploadRes)
    } catch (err) {
      console.error('[Chat] File upload failed:', err)
    }
  }

  // Initiate SSE streaming request
  // F-10：控制器由 readStream 独自创建/持有（重连重试会再建新控制器），
  // 此处不得预建——预建的控制器会被 readStream 内的创建覆盖成孤儿。
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

  // 审计⑪：失败路径必须返回 false——旧实现 catch 后落入恒 return true，
  // drain 把排队项 markSent 出队（BUG-21 修复只覆盖了早期 return 路径）
  let _sendOk = true
  try {
    await readStream()
  } catch (err: any) {
    if (err.name === 'AbortError') {
      // 用户主动停止：本轮已终止，视为失败（不算成功出队排队项）
      _sendOk = false
    } else if (handleRateLimit(err)) {
      // 补课 A1：429 → 横幅一键切模型（不计入消息正文错误）
      _sendOk = false
    } else {
      // 网络层中断且已收到至少一个事件 → 重连快进一次（HTTP 错误/中止不重连）
      const networkDrop =
        receivedSeq[0] > 0 && (err instanceof TypeError || /network|failed|fetch/i.test(String(err.message || '')))
      if (networkDrop) {
        try {
          await readStream(receivedSeq[0])
        } catch (retryErr: any) {
          // F-08：中止（含重试被中止）一律视为失败——否则 drain 把排队项
          // markSent 出队，内容只播一半却标记已发送（与主中止路径口径一致）
          if (retryErr.name !== 'AbortError') {
            streamingMsg.content += `\n\n**Error:** ${retryErr.message || 'Stream failed.'}`
          }
          _sendOk = false
        }
      } else {
        streamingMsg.content += `\n\n**Error:** ${err.message || 'Stream failed.'}`
        _sendOk = false
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
    // BUG-2 修复：仅当用户仍停留在发起会话时才 drain，
    // 否则排队消息会被发进刚切到的新会话
    // （审计③：runner 的 takeNext 按发起会话快照过滤，双保险）
    if (currentSessionId.value === activeStreamSessionId) {
      await drainMessageQueue(false, activeStreamSessionId)
    }
  }
  return _sendOk
}

/**
 * F-4 带凭证内容端点（台账 2026-09-11）：后端 audio 事件 url / done.audio_url
 * 指向 /api/ 鉴权内容端点（JWT 在 Authorization header，<audio> 直链带不了
 * 凭证）→ 带凭证取流转 blob URL（与 synthesize-stream 同模式；blob 生命
 * 周期由 revokeMessageBlobUrls 统一回收）。其余形态（blob: 等）原样透传。
 */
async function attachAudioUrl(msg: ChatMessage, url: string): Promise<void> {
  msg.audioProgress = 0
  msg.audioCurrentTime = 0
  msg.audioSpeed = 1
  if (!url.startsWith('/api/')) {
    msg.audioUrl = url
    return
  }
  try {
    const token = secureStorage.get('auth_token')
    const resp = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (!resp.ok) return
    msg.audioUrl = URL.createObjectURL(requireNonEmptyAudioBlob(await resp.blob()))
  } catch {
    // 内容端点取流失败：不设 audioUrl，气泡回落"生成语音"手动合成链路
  }
}

// 思考段滚动跟随（2026-09-12 bug）：流式推理段出内部滚动条后贴底展示最新思考。
// reasoningStick 记录用户最近一次滚动是否贴底——向上翻阅即暂停拽回，回到底部恢复。
const reasoningStick = ref(true)

function onReasoningScroll(e: Event): void {
  const el = e.target as HTMLElement
  reasoningStick.value = isNearBottom(el.scrollTop, el.scrollHeight, el.clientHeight)
}

function followReasoningScroll(): void {
  if (!reasoningStick.value) return
  // nextTick：文本已入 DOM（scrollHeight 增长）后再贴底
  nextTick(() => {
    followActiveReasoningScroll()
  })
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
        unified: t('chat.retrievalUnified'),
        MoERetriever: t('chat.retrievalMoE'),
        CacheRetriever: t('chat.retrievalCache'),
        FallbackRetriever: t('chat.retrievalFallback'),
      }
      const rName = names[retriever] || retriever
      if (stage === 'retriever_start') {
        chatStore.retrievalStatus = t('chat.retrievalStatus', { name: rName })
      } else if (stage === 'retriever_done') {
        chatStore.retrievalStatus = t('chat.retrievalDone', { name: rName, count: event.count ?? 0, ms: event.ms ?? 0 })
      } else if (stage === 'retriever_error' || stage === 'retriever_timeout') {
        chatStore.retrievalStatus = t('chat.retrievalError', { name: rName })
      } else if (stage === 'moe_gate') {
        chatStore.retrievalStatus = t('chat.retrievalExpert', { n: (event.experts || []).length })
      } else if (stage === 'moe_expert') {
        chatStore.retrievalStatus = `${event.expert || ''}：${event.count ?? 0}`
      } else if (stage === 'moe_done') {
        chatStore.retrievalStatus = event.fallback
          ? t('chat.retrievalSemanticFallback', { count: event.count ?? 0 })
          : t('chat.retrievalExpertDone', { count: event.count ?? 0 })
      }
      break
    }

    case 'reasoning':
    case 'thinking': {
      const rText = event.content || event.text || ''
      // 流式恢复 → 清除 429 重试倒计时提示
      clearRetryNotice(msg)
      // 步骤化时间轴：推理按到达顺序成段（工具打断即封口，再次思考开新段）
      if (rText) {
        const tail = msg.steps?.[msg.steps.length - 1]
        // 新开推理段 → 新滚动容器，恢复默认贴底跟随（上一段被用户翻阅过的 stick 态不继承）
        const newSegment = !(tail && tail.kind === 'reasoning' && tail.active)
        if (!msg.steps) msg.steps = []
        appendReasoningStep(msg.steps, rText)
        msg.reasoning = (msg.reasoning || '') + rText
        if (newSegment) reasoningStick.value = true
        followReasoningScroll()
      }
      break
    }

    case 'tool_call':
      if (!msg.toolCalls) msg.toolCalls = []
      msg.toolCalls.push({
        name: event.name || event.tool_name || 'unknown',
        arguments: event.arguments || event.input || '',
      })
      // 步骤化时间轴：工具段（尾部活跃推理段自动封口收起）
      if (!msg.steps) msg.steps = []
      appendToolStep(
        msg.steps,
        String(event.name || event.tool_name || 'unknown'),
        String(event.arguments || event.input || ''),
        event.task_name ? String(event.task_name) : undefined,
      )
      // legacy compat
      msg.toolCall = msg.toolCalls[msg.toolCalls.length - 1]
      // 自动语音：工具/命令执行播报提示（独立分轨，不打断正文）。
      // 必须经 getToolAnnouncer() 惰性创建——直接判 toolAnnouncer 恒 null
      // 是死接线（核验 2026-09-07 修复）。
      getToolAnnouncer()?.announce(toolAnnouncementText(String(event.name || event.tool_name || '')))
      // SSE 兜底：电脑/浏览器工具调用即开分屏（主通道为 WS computer_action）
      if (isComputerTool(event.name || event.tool_name || '')) {
        computerPanel.handleToolCall(String(event.name || event.tool_name))
      }
      break

    case 'tool_result': {
      const resultText = typeof event.result === 'string' ? event.result : JSON.stringify(event.result, null, 2)
      if (msg.toolCalls && msg.toolCalls.length > 0) {
        const last = msg.toolCalls[msg.toolCalls.length - 1]
        last.result = resultText
      }
      // 步骤化时间轴：结果按工具名归属匹配段并封口（审计⑫：并行工具时
      // "最近活跃段"会把 A 的结果挂到 B——携带工具名供按名匹配）
      if (msg.steps)
        attachToolResult(
          msg.steps,
          resultText,
          event.task_name ? String(event.task_name) : undefined,
          event.name || event.tool_name ? String(event.name || event.tool_name) : undefined,
        )
      // legacy compat
      msg.toolResult = resultText
      // 产出物收集（兜底通道）：后端 artifact 事件缺位/历史回放时，
      // 从 tool_result 文本提取路径引用（读形态过滤与后端同契约）
      msg.artifacts = mergeMessageArtifacts(msg.artifacts, artifactsFromToolResult(resultText))
      // 产物预览钩子（2026-09-08）：tool_result 文本含 file_path 等路径引用时
      // 开 dock 预览 tab（后端 artifact 事件为主通道，此处为兜底/历史兼容）
      openToolResultArtifacts(resultText)
      if (isComputerTool(event.name || '')) {
        computerPanel.markIdle()
      }
      break
    }

    case 'artifact': {
      // 后端 artifact 事件（产物预览主通道）：注册完成的产物文件 → dock tab
      openArtifactTab(event as unknown as ArtifactEventPayload)
      // 产出物收集（主通道）：同时挂到本轮消息，回答结尾产出物卡片渲染
      msg.artifacts = mergeMessageArtifacts(
        msg.artifacts,
        [artifactFromEvent(event as unknown as ArtifactEventPayload)].filter(
          (a): a is MessageArtifact => a !== null,
        ),
      )
      break
    }

    case 'approval_required': {
      // 治理 ASK: 弹出人工确认框（P0）→ useGovernanceApproval 状态机
      openApprovalModal(event)
      break
    }

    case 'message':
    case 'content':
    case 'delta':
    case 'chunk':
      // 回复内容开始 → 检索已结束，清空临时进度显示
      if (chatStore.retrievalStatus) chatStore.retrievalStatus = ''
      // 流式恢复 → 清除 429 重试倒计时提示
      clearRetryNotice(msg)
      // 步骤化时间轴：正文开始输出，封口一切仍活跃的推理/工具段
      if (msg.steps?.some((s) => s.active)) finishAllSteps(msg.steps)
      msg.content += event.content || event.text || event.delta || ''
      // 补课：自动语音 → 流式文本增量喂入句子流水线
      if (autoVoice.value && streamTTSRunner && !streamTTSRunner.isFinished) {
        streamTTSRunner.feed(event.content || event.text || event.delta || '')
      }
      break

    case 'audio':
    case 'tts':
      // autoVoice 已实时逐句播过——忽略整段音频事件避免重复
      if (autoVoice.value && streamTTSRunner) break
      if (event.url) {
        void attachAudioUrl(msg, event.url)
      }
      break

    case 'image':
      // Inline image from backend (e.g., AIGC generated image)
      if (event.url) {
        msg.content += `\n![${event.alt || 'image'}](${event.url})\n`
      }
      break

    case 'usage':
      // QwenPaw turn_usage 对齐:真实 token 用量入 store（per-session 累计）
      if (typeof event.total_tokens === 'number') {
        // 2026-09-07 根因修复：新会话首轮流式时 activeStreamSessionId 为
        // null（session_id 由后端 done 才回传），原实现把 usage 记到 null
        // 键被 store 丢弃 → 环形用量图永不显示。usage 事件现已携带
        // session_id（后端同批补上），优先采信。
        chatStore.applyTurnUsage((event.session_id as string) || activeStreamSessionId, {
          prompt: Number(event.prompt_tokens || 0),
          completion: Number(event.completion_tokens || 0),
          total: Number(event.total_tokens || 0),
          estimated: Boolean(event.estimated),
        })
      }
      break

    case 'stopped':
      // P0-2：用户主动停止（后端真取消任务后发的显式事件）——气泡收口并标记
      msg.streaming = false
      clearRetryNotice(msg)
      if (msg.steps?.some((s) => s.active)) finishAllSteps(msg.steps)
      msg.content += `\n\n_(${t('chat.stoppedByUser')})_`
      break

    case 'retry': {
      // 429 限流重试/切换（ZCode 对齐 2026-09-11）：reset=半截回复作废；
      // 写入倒计时提示条（等待期间每秒本地倒数，流式恢复即清除）
      if (event.reset) {
        msg.content = ''
        msg.reasoning = ''
        if (msg.steps?.length) msg.steps = []
      }
      msg.retryNotice = {
        phase: event.phase || 'waiting',
        retry: event.retry,
        maxRetries: event.max_retries,
        remainingSeconds: event.wait_seconds,
        receivedAt: Date.now(),
        failCount: event.fail_count,
        maxSwitches: event.max_switches,
        model: event.model,
      }
      startRetryTicker()
      break
    }

    case 'done':
    case 'complete':
      msg.streaming = false
      clearRetryNotice(msg)
      // 步骤化时间轴：整轮流收尾（活跃段全部封口收起）
      if (msg.steps?.some((s) => s.active)) finishAllSteps(msg.steps)
      // 补课：流式语音会话收尾（滞留句 flush；回放列表定稿）
      if (autoVoice.value && streamTTSRunner) streamTTSRunner.end()
      // 补课 4.4 兜底：后端把 audio_url 附在 done 事件上（而非独立 audio 帧）
      if (event.audio_url && !msg.audioUrl && !msg.ttsUrls) {
        void attachAudioUrl(msg, event.audio_url)
      }
      // Auto-create session if this is the first exchange
      if (!currentSessionId.value && event.session_id) {
        chatStore.setCurrentSession(event.session_id)
        // P1-12（审计 2026-09-11）：新会话首轮 done 拿到 session_id 时同步
        // 流快照——否则 finally 守卫 `currentSessionId === activeStreamSessionId`
        // 变成 "新id" === null 恒假，流式期间入队的消息永不自动续发
        activeStreamSessionId = event.session_id
        // BUG-6 修复：标题取发送时文本（inputText 此时已被清空，
        // 流式中又输入的草稿会污染标题）
        chatStore.addSession({
          id: event.session_id,
          title: lastSentMessageText.slice(0, 50) || t('chat.newChat'),
        })
      }
      // 补课 6：默认标题（新对话/新建对话）→ 语义概括自动填充，不再停留默认名
      void maybeAutoTitle()
      break

    case 'error': {
      // 2026-09-07 修复：429 限流错误 → 触发限流横幅（一键换模型），
      // 不把原始 429 JSON 拼进气泡；其余错误仍追加错误文本
      clearRetryNotice(msg)
      const errMsg = String(event.message || event.error || 'Unknown error')
      if (handleRateLimit({ message: errMsg })) break
      msg.content += `\n\n**Error:** ${errMsg}`
      break
    }
  }
}

function stopStreaming() {
  // P0-2：真停止——除 abort SSE 外，请求后端取消该会话运行中的任务
  //（旧实现仅断流，后端照常跑完整轮并消耗 token）
  const sid = activeStreamSessionId || currentSessionId.value
  if (sid) {
    void api
      .post(`/console/chat/stop?session_id=${encodeURIComponent(sid)}`)
      .catch(() => {})
  }
  abortController?.abort()
  stopStreamTTS()
  chatStore.setStreaming(false)
}

/**
 * 补课 6：默认标题 → 会话语义概括自动填充。
 * 仅当标题命中默认清单（新对话/新建对话等）时调用；失败静默不影响聊天。
 */
async function maybeAutoTitle(): Promise<void> {
  const sid = currentSessionId.value
  if (!sid) return
  const session = sessions.value.find((s) => s.id === sid)
  if (!session) return
  if (!isDefaultChatTitle(session.title, [t('ui.newConversation'), t('chat.newChat')])) return
  try {
    const res: any = await api.post(`/console/chat/sessions/${sid}/auto-title`)
    const data = res?.data ?? res
    const title: string | undefined = data?.title
    if (title && title !== session.title) chatStore.renameSessionTitle(sid, title)
  } catch {
    // 自动填充是增强：失败静默，用户仍可手动改名
  }
}

// ---------------------------------------------------------------------------
// ASR - Voice Input (Web Speech API + Backend Fallback)
// ---------------------------------------------------------------------------

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
        // 语音预处理：代码/网址/图片/视频改为"以下是…"播报提示；
        // 字数上限已取消（后端引擎分句切块合成）
        text: prepareSpeechText(msg.content),
        // 编辑 Agent 换音色的生效链：当前 Agent 配置的音色/语速随请求透传
        voice: currentAgent?.value?.config?.ttsVoice || undefined,
        speed: currentAgent?.value?.config?.ttsSpeed || 1.0,
        format: 'wav',
      }),
    })

    if (!response.ok) throw new Error(`TTS failed: ${response.status}`)

    // 补课 4.3：流式端点按引擎返回 audio/mpeg 或 audio/wav——blob type
    // 交给 <audio> 自动嗅探，长文本首字节到达即开始下载（整段合成时间
    // 不再阻塞在服务端全量编码完成后）
    const blob = await response.blob()
    // 实测根因：后端引擎链失败时流式端点返回 200+0 字节 → 0 字节 blob
    // 交给 <audio> 必发 Range 请求 416。拒绝造 blob URL，给用户真实报错。
    requireNonEmptyAudioBlob(blob)
    const url = URL.createObjectURL(blob)
    msg.audioUrl = url
    msg.audioProgress = 0
    msg.audioCurrentTime = 0
    msg.audioSpeed = 1

    // Auto-play（起播门控：先软停 live/其他消息音源，防两声音重叠）
    nextTick(() => {
      if (msg.audioEl) {
        syncAudioUiState(audioGate.pauseOthers(ttsGateId(msg)))
        msg.audioEl.play().catch(() => {})
      }
    })
  } catch (err) {
    console.error('[TTS] Synthesis failed:', err)
    uiMessage.error(t('chat.ttsFailed'))
  } finally {
    msg.ttsLoading = false
  }
}

// Custom Audio Player Controls
function setAudioRef(msg: ChatMessage, el: HTMLAudioElement | null) {
  msg.audioEl = el
  audioGate.track(ttsGateId(msg), el)
}

function toggleAudioPlay(msg: ChatMessage) {
  if (!msg.audioEl) return
  if (msg.audioPlaying) {
    msg.audioEl.pause()
    msg.audioPlaying = false
  } else {
    // 起播门控：本消息播放器开播 → 先软停 live/其他消息音源
    syncAudioUiState(audioGate.pauseOthers(ttsGateId(msg)))
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
  // 补课：chunk 列表回放——还有下一句则自动续播
  if (msg.ttsUrls && (msg.ttsIdx ?? 0) < msg.ttsUrls.length - 1) {
    msg.ttsIdx = (msg.ttsIdx ?? 0) + 1
    msg.audioPlaying = true
    msg.audioProgress = 0
    msg.audioCurrentTime = 0
    nextTick(() => msg.audioEl?.play().catch(() => {}))
    return
  }
  msg.audioPlaying = false
  msg.ttsIdx = 0
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
    image: 'image',
    audio: 'audio',
    video: 'image',
    pdf: 'fileText',
    spreadsheet: 'fileText',
    presentation: 'fileText',
    document: 'fileText',
    text: 'fileText',
    file: 'file',
    unknown: 'file',
  }
  return icons[cat] || 'file'
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

// P2-10：复制按钮复位定时器句柄（卸载时清理，防回调触碰已销毁 DOM）
const copyResetTimers: number[] = []

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

/** Handle clicks within rendered content (code copy/preview + image → dock). */
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
      copyResetTimers.push(window.setTimeout(() => {
        copyBtn.textContent = t('common.copy')
      }, 1500))
    }).catch(() => {
      copyBtn.textContent = '✗'
      copyResetTimers.push(window.setTimeout(() => {
        copyBtn.textContent = t('common.copy')
      }, 1500))
    })
    return
  }

  // 代码块预览按钮（产物预览 2026-09-08）：md/html/svg 分派到对应 dock 面板
  const previewBtn = target.closest('.nr-code-preview-btn') as HTMLElement | null
  if (previewBtn) {
    const wrap = previewBtn.closest('.nr-code-wrap')
    const codeEl = wrap?.querySelector('code')
    const langEl = wrap?.querySelector('.nr-code-lang')
    const lang = (langEl?.textContent || '').trim().toLowerCase()
    if (codeEl) openCodeBlockTab(codeEl.textContent || '', lang === 'code' ? '' : lang)
    return
  }

  // 消息内联图片 → dock 图片预览（lightbox 模态已收编入 dock）
  if (target.tagName === 'IMG' && target.closest('.nr-inline-image')) {
    const img = target as HTMLImageElement
    openImageTab(img.src, img.alt || 'image')
  }
}

/** 消息附件缩略图点击：图片 → dock 图片预览；其余类型带 fileId → 文档预览 */
async function onAttachmentClick(file: { name?: string; type?: string; preview?: string; fileId?: string }): Promise<void> {
  if (file.type?.startsWith('image/') && file.preview) {
    // P1-10（审计 2026-09-11）：dock 面板卸载时会 revoke 持有的 src，不得把
    // 消息自身的 blob URL 交给它（面板一关消息缩略图的 URL 即失效）——
    // 经 fetch 自建一份交给 dock，随面板生命周期配对释放。
    // #11/#18（2026-09-11）：自建 URL 标记 createdBy:'panel'（所有权随面板
    // 释放；自建失败回退的消息 blob 不标记，由 store.revokeMessageBlobUrls
    // 统一释放）；去重键用稳定标识（fileId 优先，回退消息 preview），重复
    // 点击回焦既有 tab 而非每次自建新 blob 生成新 tab。
    let url = file.preview
    let createdByPanel = false
    if (url.startsWith('blob:')) {
      try {
        url = URL.createObjectURL(await (await fetch(file.preview)).blob())
        createdByPanel = true
      } catch {
        /* 自建失败回退原 URL（外来 URL 契约：面板不 revoke，无连带撤消） */
      }
    }
    openImageTab(url, file.name || 'image', {
      dedupeKey: file.fileId || file.preview,
      createdBy: createdByPanel ? 'panel' : undefined,
    })
  } else if (file.fileId) {
    openFileTab(file.fileId, file.name || 'file', file.type)
  }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
// ── 会话内消息搜索（补课 B）─────────────────────────────
const msgSearchOpen = ref(false)
const msgSearchQuery = ref('')
const msgSearchCursor = ref(-1)  // 当前命中的绝对消息下标；-1 = 尚未跳转
const msgSearchHits = computed(() => findMessageMatches(messages.value, msgSearchQuery.value))

function openMsgSearch(): void {
  msgSearchOpen.value = !msgSearchOpen.value
  if (msgSearchOpen.value) {
    msgSearchQuery.value = ''
    msgSearchCursor.value = -1
  }
}

function jumpToMatch(dir: 1 | -1): void {
  const hits = msgSearchHits.value
  if (hits.length === 0) return
  // 游标循环移动（P1-10：cursor 语义 = 命中消息的绝对下标；旧实现把
  // "命中在 hits 数组中的序号"与绝对下标混用，高亮落到错误消息）
  const cursor = hits.indexOf(msgSearchCursor.value)
  const next = cursor === -1
    ? (dir === 1 ? 0 : hits.length - 1)
    : (cursor + dir + hits.length) % hits.length
  msgSearchCursor.value = hits[next]!
  const idx = msgSearchCursor.value
  // 窗口化渲染（补课 A6）：命中在窗口外时先前扩窗直到包含该下标
  if (idx < renderStart.value) {
    renderStart.value = Math.max(0, idx - RENDER_BUFFER)
  }
  // 滚动到命中消息（offsetTop 相对滚动容器）
  nextTick(() => {
    const el = document.getElementById(`nr-msg-${idx}`)
    if (el && messagesRef.value) {
      messagesRef.value.scrollTop = el.offsetTop - 80
    }
  })
}

// ── 输入历史回溯（补课 C）─────────────────────────────
const chatDraft = useChatDraft()

// ── mermaid 渲染（补课 E）─────────────────────────────
const { renderIn: renderMermaid, scheduleRender: scheduleMermaidRender, dispose: disposeMermaid } =
  useMermaidRenderer(() => !appStore.isDark)

const { record: recordInputHistory, up: historyUp, down: historyDown } = useInputHistory()

const { onCompositionStart, onCompositionEnd, shouldBlockSend } = useIMEComposition()

// handleKeydown/onComposerInput/autoResize → 已迁 ChatComposerArea（2026-09-08）

function scrollToBottom() {
  nextTick(() => {
    const el = messagesRef.value
    if (!el) return
    el.scrollTop = el.scrollHeight
    // 代码高亮/mermaid 渲染会随后续帧继续撑高内容——再锚定两帧，
    // 否则打开历史会话时视口停在中部（用户感知"不在最新消息处"）
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight
      })
    })
  })
}

// ── 流式 TTS 会话编排 ──────────────────────────────────────

// live 播放（补课）：audio 元素常驻模板（此前 liveTtsAudio 从未被模板
// ref 赋值 → 播放链整条是哑的：onChunkReady 开播 no-op）
const livePlaying = ref(false)
// 单声道门控：所有 TTS 音源（live + 各消息播放器）起播前软停其他音源，
// 防两轮对话间隔相近时两个声音重叠播放（实测缺陷）。
const audioGate = useTtsAudioGate()

/** 消息播放器的门控 id（元素随 v-for 重渲染，同消息固定 id 覆盖旧句柄）。
 *  ChatMessage 无业务 id，用对象上惰性挂的序号保持同一消息稳定。 */
let ttsGateSeq = 0
function ttsGateId(msg: ChatMessage): string {
  const withId = msg as ChatMessage & { __ttsGateId?: string }
  withId.__ttsGateId ??= `msg:${++ttsGateSeq}`
  return withId.__ttsGateId
}

/** 门控软停后的宿主状态同步：live 解锁；消息播放器 ⏸→▶ 复位。 */
function syncAudioUiState(stoppedIds: string[]): void {
  for (const id of stoppedIds) {
    if (id === 'live') {
      livePlaying.value = false
      continue
    }
    const msg = messages.value.find((m) => ttsGateId(m) === id)
    if (msg) msg.audioPlaying = false
  }
}

function setLiveTtsAudioRef(el: HTMLAudioElement | null): void {
  liveTtsAudio.value = el
  audioGate.track('live', el)
}

function onLiveTtsError(): void {
  // 单句加载/解码失败：解除播放锁，下一句就绪即可重试
  livePlaying.value = false
}

/** live 播放推进：当前句播完自动播下一句（顺序保持合成序）。 */
function playLiveChunk(index: number): void {
  const urls = streamTTSRunner?.urls.value ?? []
  if (index >= urls.length) return
  // 起播门控：live 开播/续播 → 先软停消息播放器等其他音源
  syncAudioUiState(audioGate.pauseOthers('live'))
  liveTtsIdx.value = index
  liveTtsUrl.value = urls[index]
  livePlaying.value = true
  nextTick(() => {
    liveTtsAudio.value?.play().catch(() => {
      // 自动播放被拒（浏览器策略等）：解锁，等服务端下一句就绪重试
      livePlaying.value = false
    })
  })
}

function startStreamTTS(): void {
  streamTTSRunner = new StreamTTSRunner({
    synthesize: async (text, signal) => {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
      const token = secureStorage.get('auth_token')
      const resp = await fetch(`${baseUrl}/audio/synthesize-stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          text,
          // 当前 Agent 音色/语速（换音色生效链）
          voice: currentAgent?.value?.config?.ttsVoice || undefined,
          speed: currentAgent?.value?.config?.ttsSpeed || 1.0,
        }),
        signal,
      })
      if (!resp.ok) throw new Error(`TTS ${resp.status}`)
      const blob = await resp.blob()
      // 0 字节 blob 不允许造 URL（<audio> 加载必 416）；抛错由 Runner
      // 跳过该句继续后续句子。
      return URL.createObjectURL(requireNonEmptyAudioBlob(blob))
    },
    onChunkReady: (_url, index) => {
      // 首句就绪即开播；后续句由 onended 推进。
      // 若当前未在播放（含上一句已播完而下一句尚未合成完的间隙），
      // 新句就绪立即补播——原判 liveTtsIdx<0/url=='' 会漏掉该间隙。
      if (!livePlaying.value) playLiveChunk(index)
    },
    onDone: (urls) => {
      // 回放定稿：句块列表挂到消息上（下方播放器按列表回放）
      const msg = streamingTtsMsg
      if (msg && urls.length > 0) {
        msg.ttsUrls = urls
        msg.ttsIdx = 0
        // 播放器 v-if=msg.audioUrl 才显示——挂首块 URL 出回放入口
        msg.audioUrl = urls[0]
      }
      streamingTtsMsg = null
    },
  })
  streamTTSRunner.begin()
}

let streamingTtsMsg: ChatMessage | null = null

// 工具调用语音提示（独立分轨，不进正文流式队列）
let toolAnnouncer: SpeechAnnouncer | null = null

function getToolAnnouncer(): SpeechAnnouncer | null {
  if (!ttsAvailable.value) return null
  if (!toolAnnouncer) {
    toolAnnouncer = createSpeechAnnouncer(async (text) => {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
      const token = secureStorage.get('auth_token')
      const resp = await fetch(`${baseUrl}/audio/synthesize-stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          text,
          // 当前 Agent 音色/语速（换音色生效链）
          voice: currentAgent?.value?.config?.ttsVoice || undefined,
          speed: currentAgent?.value?.config?.ttsSpeed || 1.0,
        }),
      })
      if (!resp.ok) throw new Error(`TTS ${resp.status}`)
      return resp.blob()
    }, { enabled: () => autoVoice.value && ttsAvailable.value })
  }
  return toolAnnouncer
}

/** 开启一轮流式语音（autoVoice 开启时在发起对话时调用）。 */
function beginStreamTTS(msg: ChatMessage): void {
  if (!autoVoice.value || !ttsAvailable.value) return
  // 新轮次硬停上一轮 live（旧的 runner/播放若还活着会与新轮重叠）
  stopStreamTTS()
  streamingTtsMsg = msg
  startStreamTTS()
}

function stopStreamTTS(): void {
  streamTTSRunner?.abort()
  streamTTSRunner = null
  streamingTtsMsg = null
  liveTtsUrl.value = ''
  liveTtsQueue.value = []
  liveTtsIdx.value = -1
  livePlaying.value = false
  if (liveTtsAudio.value) liveTtsAudio.value.pause()
}

/** live 元素当前句播完 → 下一句；全部播完静默收尾。 */
function onLiveTtsEnded(): void {
  livePlaying.value = false
  const urls = streamTTSRunner?.urls.value ?? liveTtsQueue.value
  const next = liveTtsIdx.value + 1
  if (next < urls.length) playLiveChunk(next)
}

/**
 * 打开/切换会话 → 定位到最新记录（结尾处）。与实时流的 scrollToBottom
 * 不同：历史渲染含 hljs/mermaid/图片异步膨胀，且窗口化渲染（补课 A6）
 * 切换时 renderStart 可能停在旧位置——这里三重保障：
 * 1) renderStart 归位贴尾；2) 双 rAF 连滚；3) ResizeObserver 兜底
 * 渲染膨胀期的最后位置校正（首个膨胀帧后自断）。
 */
let historyAnchorObserver: ResizeObserver | null = null
function scrollToBottomForHistory(): void {
  // A6：窗口化渲染下打开历史会话必须先贴尾窗口
  renderStart.value = Math.max(0, messages.value.length - RENDER_WINDOW)
  nextTick(() => {
    const el = messagesRef.value
    if (!el) return
    el.scrollTop = el.scrollHeight
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight
    })
    if (typeof ResizeObserver === 'undefined') return
    historyAnchorObserver?.disconnect()
    let ticks = 0
    historyAnchorObserver = new ResizeObserver(() => {
      if (el && messagesRef.value === el) el.scrollTop = el.scrollHeight
      // 渲染稳定（连续 3 帧高度不变或观察 10 次）后停表
      if (++ticks >= 10) {
        historyAnchorObserver?.disconnect()
        historyAnchorObserver = null
      }
    })
    historyAnchorObserver.observe(el)
  })
}

/** 定位到指定下标消息（会话内搜索跳转用；无则回退底部）。 */
function scrollToMessage(idx: number): void {
  nextTick(() => {
    const el = document.getElementById(`nr-msg-${idx}`)
    if (el) {
      el.scrollIntoView({ block: 'center' })
      return
    }
    scrollToBottomForHistory()
  })
}

// 补课 E：消息内容变更 → 防抖渲染 mermaid 占位
// P2-16（审计 2026-09-11）：源改为增量信号（消息条数 + 末条 content 长度）。
// 原 map+reduce 对全部历史消息求长度和，流式每 chunk 全量重算；流式只追加
// 末条消息，条数或末条长度变化即覆盖了需要触发渲染的全部场景。
watch(
  () => {
    const msgs = messages.value
    const last = msgs[msgs.length - 1]
    return `${msgs.length}:${last ? last.content.length : 0}`
  },
  () => scheduleMermaidRender(messagesRef.value),
)
onMounted(() => void nextTick().then(() => renderMermaid(messagesRef.value)))

function formatJSON(str?: string): string {
  if (!str) return ''
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
    syncLocale(newLocale)
  },
)

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
// 切换 agent 时重新加载 sessions
// 当前 agent 默认模型 → 同步切换器 pill（agent 隔离：每个 agent 记忆自己的模型）
watch(
  () => currentAgent.value?.model,
  (model) => {
    selectedModel.value = model && model !== 'auto' ? model : ''
  },
  { immediate: true },
)

watch(agentId, (newId, oldId) => {
  if (newId && newId !== oldId) {
    // P1-11（审计 2026-09-11）：切 Agent 必须先中止在途流并复位 streaming 态——
    // 旧流继续把增量写进已换走的孤儿 assistant proxy，且 isStreaming 挂到
    // finally 才复位，新 Agent 页面发送按钮被禁用数十秒；旧草稿同样先存后走
    if (isStreaming.value) {
      abortController?.abort()
      abortController = null
      activeStreamSessionId = null
      chatStore.setStreaming(false)
      stopStreamTTS()
    }
    const prevSession = currentSessionId.value
    if (prevSession) chatDraft.save(prevSession, inputText.value)
    chatStore.clearMessages()
    chatStore.setCurrentSession(null)
    // P2-15（审计 2026-09-11）：切 Agent 整栈回收子 Agent 浮窗
    // （旧 Agent 流已在上面的 abort 分支中止，运行窗也不会再有事件）
    clearSubAgentWindows()
    loadSessions()
    // 存档 tab 开着时随 agent 切换刷新列表（dock ArchiveTab 自身挂载时也会加载）
    if (rightDock.tabs.some((tab) => tab.kind === 'archive')) {
      _loadArchivedSessions(newId)
    }
  }
})

// P2-15（审计 2026-09-11）：会话切换回收子 Agent 浮窗（模块级单例跨会话残留）。
// 浮窗状态不随会话持久化，切换后旧窗不再有事件流入，一律整栈回收。
watch(currentSessionId, () => clearSubAgentWindows())

onMounted(() => {
  loadSessions()
  initASR()
  checkTTSAvailability()
  loadChatModels()
  // 429 横幅一键切换 → 自动重发上一条消息（切走后继续推理的闭环）
  registerRateLimitSwitchHook(onRateLimitSwitch)
  // 打开页面即定位到最新记录（loadSessions 自动切换首会话后双保险）
  void nextTick().then(() => scrollToBottomForHistory())
})

onBeforeUnmount(() => {
  historyAnchorObserver?.disconnect()
  historyAnchorObserver = null
  // 429 切换钩子随页面卸载解除（composable 为模块级单例，防跨页残留）
  registerRateLimitSwitchHook(null)
  stopStreamTTS()
  // P2-10：清理复制按钮复位定时器
  for (const t of copyResetTimers) window.clearTimeout(t)
  copyResetTimers.length = 0
  // 补课 D：离开页面保存当前会话草稿
  if (currentSessionId.value) chatDraft.save(currentSessionId.value, inputText.value)
  disposeMermaid()
  abortController?.abort()
  stopRecording()
  for (const pf of pendingFiles.value) {
    if (pf.preview) URL.revokeObjectURL(pf.preview)
  }
  // P1-10（审计 2026-09-11）：统一经 revokeMessageBlobUrls 回收消息 blob URL。
  // 覆盖 audioUrl/ttsUrls（原 BUG-23 补课逻辑）+ attachments[].preview（原实现漏撤）。
  for (const msg of messages.value) revokeMessageBlobUrls(msg)
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
.nr-chat-page-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 24px; border-bottom: 1px solid var(--nr-glass-border);
  background: var(--nr-glass-bg); flex-shrink: 0;
}
.nr-chat-header-left { display: flex; align-items: center; gap: 12px; }
.nr-chat-header-left .page-title { margin: 0; font-family: var(--nr-font-display); font-size: 20px; font-weight: 700; color: var(--nr-text-primary); }
.nr-chat-header-actions { display: flex; gap: 8px; align-items: center; }
.nr-chat-toggle-btn {
  width: 32px; height: 32px; border: 1px solid var(--nr-glass-border); border-radius: 8px;
  background: var(--nr-glass-bg); color: var(--nr-text-secondary); font-size: 18px;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all 0.2s ease;
}
.nr-chat-toggle-btn:hover { border-color: var(--nr-glass-border-hover); color: var(--nr-text-primary); background: var(--nr-glass-bg-hover); }
.nr-chat-toggle-btn.cu-active { border-color: color-mix(in srgb, var(--nr-primary-light) 70%, transparent); color: var(--nr-primary-light, #818cf8); background: var(--nr-primary-soft); }

/* 思考程度三档选择器（简单/标准/深度） */
@media (max-width: 720px) {
  .nr-thinking-seg { display: none; }
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

/* Governance approval modal 样式已随组件迁移（GovernanceApprovalModal.vue） */

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
  display: flex;
  align-items: center;
  gap: 6px;
}

.nr-tool-result-preview-btn {
  border: none;
  background: transparent;
  color: var(--nr-text-muted);
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
  padding: 1px 4px;
  border-radius: 4px;
}

.nr-tool-result-preview-btn:hover {
  color: var(--nr-text-primary);
  background: var(--nr-bg-secondary);
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

/* ── 流式状态条（三需求①）：阶段图标 + 文案 + 扫光，结束随 streaming 消失 ── */
.nr-stream-status {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 14px 6px 10px;
  margin: 4px 0 8px;
  border-radius: 999px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.25));
  background: var(--nr-bg-tertiary, rgba(120, 120, 140, 0.08));
  overflow: hidden;
  max-width: 100%;
}

.nr-stream-status-icon {
  font-size: 13px;
  line-height: 1;
}

.nr-stream-status-label {
  font-size: 12px;
  color: var(--nr-text-secondary, #9aa0ac);
  white-space: nowrap;
}

/* 429 重试/切换倒计时提示条（ZCode 对齐）：琥珀色系区分于常规流式状态 */
.nr-retry-notice {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 12px 5px 10px;
  margin: 0 0 8px;
  border-radius: 999px;
  border: 1px solid rgba(230, 160, 60, 0.35);
  background: rgba(230, 160, 60, 0.1);
  max-width: 100%;
}

.nr-retry-notice-label {
  font-size: 12px;
  color: #d2994a;
  white-space: nowrap;
}

/* 扫光：一条高光从左到右掠过状态条；仅流式期间存在（v-if 随 streaming 消失） */
.nr-stream-status-shimmer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(
    100deg,
    transparent 20%,
    rgba(120, 170, 255, 0.18) 45%,
    rgba(255, 255, 255, 0.22) 50%,
    rgba(120, 170, 255, 0.18) 55%,
    transparent 80%
  );
  background-size: 220% 100%;
  animation: nr-shimmer 1.8s linear infinite;
}

@keyframes nr-shimmer {
  0% { background-position: 120% 0; }
  100% { background-position: -120% 0; }
}

/* ── 步骤化时间轴（三需求②）：推理/工具按到达顺序，独立折叠 ─────────── */
.nr-steps-timeline {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 4px 0 8px;
  position: relative;
}

.nr-step-item {
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
  border-radius: 10px;
  background: var(--nr-bg-tertiary, rgba(120, 120, 140, 0.06));
  overflow: hidden;
}

.nr-step-header {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
  min-width: 0;
}

.nr-step-header:hover {
  background: rgba(120, 170, 255, 0.07);
}

.nr-step-icon {
  font-size: 13px;
  line-height: 1;
  flex-shrink: 0;
}

.nr-step-title {
  font-size: 12px;
  color: var(--nr-text-secondary, #9aa0ac);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 活跃段标题扫光：文字渐变高光横扫（进行中语义，结束即灭） */
.nr-step-item.is-active .nr-step-title {
  background: linear-gradient(90deg, var(--nr-text-secondary, #9aa0ac) 35%, #cfe1ff 50%, var(--nr-text-secondary, #9aa0ac) 65%);
  background-size: 200% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: nr-step-shimmer 1.6s linear infinite;
}

@keyframes nr-step-shimmer {
  0% { background-position: 100% 0; }
  100% { background-position: -100% 0; }
}

.nr-step-badge {
  font-size: 10px;
  line-height: 1;
  padding: 2px 7px;
  border-radius: 999px;
  flex-shrink: 0;
  color: var(--nr-text-tertiary, #8a8f99);
  background: rgba(128, 128, 140, 0.14);
}

.nr-step-badge.is-running {
  color: #6aa5ff;
  background: rgba(106, 165, 255, 0.14);
}

.nr-step-badge.is-done {
  color: #67c23a;
  background: rgba(103, 194, 58, 0.13);
}

.nr-step-badge.is-error {
  color: #e6a23c;
  background: rgba(230, 162, 60, 0.13);
}

.nr-step-duration {
  font-size: 10px;
  color: var(--nr-text-tertiary, #7a7f8a);
  flex-shrink: 0;
}

.nr-step-toggle {
  margin-left: auto;
  font-size: 11px;
  color: var(--nr-text-tertiary, #7a7f8a);
  flex-shrink: 0;
}

.nr-step-body {
  padding: 4px 10px 8px;
  border-top: 1px dashed var(--nr-border, rgba(128, 128, 128, 0.15));
}

.nr-step-reasoning {
  font-size: 12px;
  line-height: 1.7;
  color: var(--nr-text-secondary, #9aa0ac);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 320px;
  overflow-y: auto;
}

@keyframes typing {
  0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-4px); }
}

/* Input Area */
/* ASR Recording Bar */
/* Composer 一体化外壳（参考图：textarea+工具条同框，边框聚焦态由外壳承载） */
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

/* Main layout mode: fill parent container instead of viewport */
.nr-chat-page--main {
  height: calc(100vh - var(--nr-header-h) - 48px);
  border-radius: 12px;
}

/* Right-side conversation history panel (main layout mode) */
/* 实时记忆检索进度条（临时态，不落历史） */
/* 顶入卡片态：composer 内嵌队列时 textarea 区域收进内框（对齐截图） */
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

/* ── 斜杠命令面板（QwenPaw slash commands 对齐） ── */
/* ── Composer 工具条：用量环 + 思考程度 + 语音 + 模型 + 圆形发送（QwenPaw/ZCode 输入条风格） ── */
.nr-chat-header-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--nr-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 42vw;
}

/* 工具条线性图标：currentColor 描边，左右风格统一（替代彩色 emoji） */
/* ── 模型切换器二级级联菜单（参考图：左服务商 / 右模型 / 底管理模型）── */
/* 模型连通点：绿=真实可用，灰=不可联通 */
/* 独立模型子菜单：向左弹出，固定高度+内部滚动（切换服务商主菜单尺寸恒定） */
/* 顶入编辑确认态：✓ 图标时着色提示"回车/点击=保存改写" */
/* ── 消息钩子/检查点（ZCode checkpoint 对齐） ── */
.nr-msg-checkpoint-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--nr-primary, #4a9eff);
  background: rgba(74, 158, 255, 0.12);
  border: 1px solid rgba(74, 158, 255, 0.35);
  border-radius: 10px;
  padding: 1px 8px;
  margin-bottom: 4px;
  width: fit-content;
}

.nr-msg--checkpoint .nr-msg-body {
  border-left: 2px solid rgba(74, 158, 255, 0.45);
  padding-left: 6px;
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
