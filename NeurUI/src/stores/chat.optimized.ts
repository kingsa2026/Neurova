/**
 * Optimized Chat Store - Zustand-inspired refactoring
 * 
 * Key improvements:
 * - Compositional action groups
 * - Better separation of concerns
 * - Improved TypeScript types
 * - Cleaner API surface
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatMessage, Session } from '@/types/chat'
import { revokeMessageBlobUrls } from '@/utils/blobUrls'
import { handleStoreError, logStoreOperation } from './utils'

export const useChatStore = defineStore('chat', () => {
  // ===========================================================================
  // State
  // ===========================================================================
  
  const sessions = ref<Session[]>([])
  const archivedSessions = ref<Session[]>([])
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const isStreaming = ref<boolean>(false)
  const inputText = ref<string>('')
  const searchQuery = ref<string>('')
  
  // Token usage tracking
  const sessionTokenUsage = ref<Record<string, { prompt: number; completion: number; total: number }>>({})
  const lastTurnUsage = ref<{ prompt: number; completion: number; total: number; estimated: boolean } | null>(null)
  
  // UI state
  const retrievalStatus = ref('')
  const eventsLostBanner = ref<number | null>(null)
  
  // ===========================================================================
  // Getters
  // ===========================================================================
  
  const currentSession = computed<Session | undefined>(() =>
    sessions.value.find((s) => s.id === currentSessionId.value),
  )
  
  const filteredSessions = computed<Session[]>(() => {
    const q = searchQuery.value.trim().toLowerCase()
    const base = q
      ? sessions.value.filter(
          (s) =>
            s.title.toLowerCase().includes(q) ||
            (s.updatedAt ?? '').toLowerCase().includes(q),
        )
      : sessions.value
    
    return [...base].sort((a, b) => Number(b.pinned ?? false) - Number(a.pinned ?? false))
  })
  
  const currentSessionTitle = computed<string>(() => {
    if (currentSession.value) return currentSession.value.title
    return ''
  })
  
  // ===========================================================================
  // Action Groups - Organized by domain concern
  // ===========================================================================
  
  /** Session management actions */
  const sessionActions = {
    setSessions(next: Session[]): void {
      logStoreOperation('chat', 'setSessions', next.length)
      sessions.value = next
    },
    
    addSession(session: Session): void {
      logStoreOperation('chat', 'addSession', session.id)
      sessions.value.unshift(session)
    },
    
    removeSession(sessionId: string): void {
      logStoreOperation('chat', 'removeSession', sessionId)
      sessions.value = sessions.value.filter((s) => s.id !== sessionId)
    },
    
    selectSession(sessionId: string | null): void {
      currentSessionId.value = sessionId
    },
    
    renameSession(sessionId: string, title: string): void {
      const session = sessions.value.find((s) => s.id === sessionId)
      if (session) {
        session.title = title
        logStoreOperation('chat', 'renameSession', `${sessionId}: ${title}`)
      }
    },
    
    pinSession(sessionId: string, pinned: boolean): void {
      const session = sessions.value.find((x) => x.id === sessionId)
      if (session) {
        session.pinned = pinned
        logStoreOperation('chat', 'pinSession', `${sessionId}: ${pinned}`)
      }
    },
    
    moveSessionAfter(sourceId: string, targetId: string): void {
      const src = sessions.value.find((s) => s.id === sourceId)
      const tgt = sessions.value.find((s) => s.id === targetId)
      if (!src || !tgt) return
      
      const tgtTs = tgt.updatedAt ? Date.parse(tgt.updatedAt) : Date.now()
      src.updatedAt = new Date(tgtTs + 1).toISOString()
      
      logStoreOperation('chat', 'moveSessionAfter', `${sourceId} after ${targetId}`)
    },
    
    applySessionOrder(orderedIds: string[]): void {
      const rank = new Map(orderedIds.map((id, idx) => [id, idx]))
      sessions.value.sort((a, b) => 
        (rank.get(a.id) ?? Number.MAX_SAFE_INTEGER) - (rank.get(b.id) ?? Number.MAX_SAFE_INTEGER)
      )
      
      logStoreOperation('chat', 'applySessionOrder', orderedIds.length)
    },
  }
  
  /** Archived session actions */
  const archivedSessionActions = {
    setArchivedSessions(next: Session[]): void {
      archivedSessions.value = next
    },
    
    removeArchivedSession(sessionId: string): void {
      archivedSessions.value = archivedSessions.value.filter((s) => s.id !== sessionId)
    },
  }
  
  /** Message management actions */
  const messageActions = {
    setMessages(next: ChatMessage[]): void {
      // Revoke blob URLs before replacing
      for (const m of messages.value) revokeMessageBlobUrls(m)
      messages.value = next
      
      logStoreOperation('chat', 'setMessages', next.length)
    },
    
    addMessage(message: ChatMessage): ChatMessage {
      messages.value.push(message)
      logStoreOperation('chat', 'addMessage', 'new')
      
      return messages.value[messages.value.length - 1]
    },
    
    clearMessages(): void {
      for (const m of messages.value) revokeMessageBlobUrls(m)
      messages.value = []
      
      logStoreOperation('chat', 'clearMessages', 0)
    },
    
    removeRoundFrom(fromIndex: number): void {
      if (fromIndex < 0 || fromIndex >= messages.value.length) return
      
      let removedFirst = false
      let i = fromIndex
      
      while (i < messages.value.length) {
        if (removedFirst && messages.value[i].role !== 'assistant') break
        
        revokeMessageBlobUrls(messages.value[i])
        messages.value.splice(i, 1)
        removedFirst = true
      }
      
      logStoreOperation('chat', 'removeRoundFrom', fromIndex)
    },
  }
  
  /** Streaming and composer actions */
  const streamingActions = {
    startStreaming(): void {
      isStreaming.value = true
      logStoreOperation('chat', 'startStreaming', true)
    },
    
    endStreaming(): void {
      isStreaming.value = false
      logStoreOperation('chat', 'endStreaming', false)
    },
    
    setInputText(text: string): void {
      inputText.value = text
    },
    
    setSearchQuery(query: string): void {
      searchQuery.value = query
    },
  }
  
  /** Token usage actions */
  const tokenUsageActions = {
    applyTurnUsage(
      sessionId: string | null,
      usage: { prompt: number; completion: number; total: number; estimated: boolean }
    ): void {
      lastTurnUsage.value = usage
      
      if (!sessionId) return
      
      const acc = sessionTokenUsage.value[sessionId] ?? { prompt: 0, completion: 0, total: 0 }
      sessionTokenUsage.value[sessionId] = {
        prompt: acc.prompt + usage.prompt,
        completion: acc.completion + usage.completion,
        total: acc.total + usage.total,
      }
      
      logStoreOperation('chat', 'applyTurnUsage', { sessionId, ...usage })
    },
    
    getSessionTokenUsage(sessionId: string | null): { prompt: number; completion: number; total: number } | null {
      if (!sessionId) return null
      return sessionTokenUsage.value[sessionId] ?? null
    },
  }
  
  /** UI state actions */
  const uiActions = {
    setRetrievalStatus(status: string): void {
      retrievalStatus.value = status
    },
    
    bumpEventsLost(count: number): void {
      eventsLostBanner.value = (eventsLostBanner.value ?? 0) + count
    },
    
    clearEventsLost(): void {
      eventsLostBanner.value = null
    },
  }
  
  // ===========================================================================
  // Lifecycle actions
  // ===========================================================================
  
  const reset = (): void => {
    // Revoke blob URLs before clearing
    for (const m of messages.value) revokeMessageBlobUrls(m)
    
    sessions.value = []
    archivedSessions.value = []
    currentSessionId.value = null
    messages.value = []
    isStreaming.value = false
    inputText.value = ''
    retrievalStatus.value = ''
    eventsLostBanner.value = null
    sessionTokenUsage.value = {}
    lastTurnUsage.value = null
    
    logStoreOperation('chat', 'reset', true)
  }
  
  // ===========================================================================
  // Return all state, getters, and actions
  // ===========================================================================
  
  return {
    // State
    sessions,
    archivedSessions,
    currentSessionId,
    messages,
    isStreaming,
    inputText,
    searchQuery,
    sessionTokenUsage,
    lastTurnUsage,
    retrievalStatus,
    eventsLostBanner,
    
    // Getters
    currentSession,
    filteredSessions,
    currentSessionTitle,
    
    // Actions - grouped by domain
    ...sessionActions,
    ...archivedSessionActions,
    ...messageActions,
    ...streamingActions,
    ...tokenUsageActions,
    ...uiActions,
    reset,
  }
})
