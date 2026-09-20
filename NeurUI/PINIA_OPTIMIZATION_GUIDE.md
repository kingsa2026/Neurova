# Neurova Pinia Store 优化指南 - Zustand 理念实践

## 🎯 优化目标

基于 Zustand 的设计哲学，优化 Neurova 现有的 Pinia stores：
- ⚡ **简化 API** - 减少样板代码
- 🔧 **模块化** - 更好的组合性
- 📦 **类型安全** - 完善的 TypeScript 支持
- 🌐 **离线优先** - 操作队列和自动同步

---

## 📊 现有 Store 分析

### 1. Chat Store (`chat.ts`) - 316 行

**当前问题**:
- ❌ 大量独立的 setter 函数（setSessions, setMessages, etc.）
- ❌ 状态和操作混合在一起
- ❌ 缺少组合式 API

**优化方向**:
```typescript
// Before: 分散的 setters
function setSessions(next: Session[]): void { sessions.value = next }
function addSession(session: Session): void { sessions.value.unshift(session) }
function removeSession(sessionId: string): void { sessions.value = ...filter... }

// After: 组合式操作 (推荐模式)
const sessionActions = {
  selectSession: (sessionId: string) => {
    currentSessionId.value = sessionId
  },
  
  renameSession: (sessionId: string, title: string) => {
    const session = sessions.value.find(s => s.id === sessionId)
    if (session) session.title = title
  },
  
  pinSession: (sessionId: string, pinned: boolean) => {
    const session = sessions.value.find(s => s.id === sessionId)
    if (session) session.pinned = pinned
  },
}
```

---

### 2. Collaboration Store (`collaboration.ts`) - 207 行

**当前问题**:
- ❌ 重复的 loading/error 处理模式
- ❌ asArray 工具函数过于复杂
- ❌ 缺少与 CRDT 的集成

**优化方向**:
```typescript
// 集成 CRDT Document
async function createCollaborativeDocument(title: string, participants: string[]) {
  // Create CRDT document
  const doc = get_document(`collab_${Date.now()}`, currentNodeId)
  doc.set_title(title, currentUser.id)
  participants.forEach(id => doc.add_author(id))
  
  // Save to backend
  const docRef = await saveCanvas({
    id: null,
    name: title,
    content: doc.to_dict(),
  })
  
  // Subscribe to real-time updates
  subscribeToDocumentUpdates(docRef.id, (updates) => {
    const localDoc = get_document(docRef.id, currentNodeId)
    localDoc.merge(updates)
  })
  
  return docRef
}
```

---

### 3. Agents Store (`agents.ts`) - 353 行

**当前问题**:
- ❌ mapAgentResponse 和 mapConfigToApi 重复转换逻辑
- ❌ 缓存逻辑分散在函数内部
- ❌ workflowAgents 与普通 agents 混在一起

**优化方向**:
```typescript
// 使用适配器模式分离转换逻辑
const agentAdapter = {
  toDomain: (raw: Record<string, any>): Agent => {
    const config = raw.config || {}
    return {
      id: raw.id ?? raw.agent_id,
      name: raw.name,
      description: raw.description ?? '',
      model: raw.model ?? config.model ?? '',
      provider: raw.provider ?? config.provider ?? '',
      status: raw.status ?? 'inactive',
      avatar: raw.avatar ?? null,
      createdAt: raw.created_at ?? raw.createdAt ?? '',
      updatedAt: raw.updated_at ?? raw.updatedAt ?? '',
      config: {
        systemPrompt: config.system_prompt ?? config.systemPrompt ?? '',
        temperature: config.temperature ?? 0.7,
        maxTokens: config.max_tokens ?? config.maxTokens ?? 4096,
        topP: config.top_p ?? config.topP ?? 1.0,
        ttsEnabled: config.tts_enabled ?? config.ttsEnabled ?? false,
        ttsVoice: config.tts_voice ?? config.ttsVoice ?? '',
        ttsSpeed: config.tts_speed ?? config.ttsSpeed ?? 1.0,
        ttsPitch: config.tts_pitch ?? config.ttsPitch ?? 1.0,
        tools: config.tools ?? [],
        skills: config.skills ?? [],
      },
      stats: raw.stats ? { /* mapping */ } : undefined,
    }
  },
  
  toAPI: (agent: Agent): Record<string, any> => ({
    system_prompt: agent.config.systemPrompt,
    temperature: agent.config.temperature,
    max_tokens: agent.config.maxTokens,
    top_p: agent.config.topP,
    tts_enabled: agent.config.ttsEnabled,
    tts_voice: agent.config.ttsVoice,
    tts_speed: agent.config.ttsSpeed,
    tts_pitch: agent.config.ttsPitch,
    tools: agent.config.tools,
    skills: agent.config.skills,
  }),
}

// 分层存储
const agents = ref<Agent[]>([])
const workflowAgents = ref<WorkflowAgent[]>([])

// 统一的加载策略
async function syncAgents(force = false) {
  await Promise.all([
    fetchRegularAgents(force),
    fetchWorkflowAgents(force),
  ])
}
```

---

## 🚀 核心原则

### 原则 1: 组合式 Actions

将相关操作分组到对象中，提高可读性和可维护性：

```typescript
export const useChatStore = defineStore('chat', () => {
  // State
  const sessions = ref<Session[]>([])
  const currentSessionId = ref<string | null>(null)
  
  // Getters
  const currentSession = computed(() => 
    sessions.value.find(s => s.id === currentSessionId.value)
  )
  
  // Actions - 按功能分组
  const sessionActions = {
    select: (id: string) => currentSessionId.value = id,
    rename: (id: string, title: string) => {
      const s = sessions.value.find(s => s.id === id)
      if (s) s.title = title
    },
    pin: (id: string, pinned: boolean) => {
      const s = sessions.value.find(s => s.id === id)
      if (s) s.pinned = pinned
    },
  }
  
  const messageActions = {
    add: (msg: ChatMessage) => messages.value.push(msg),
    clear: () => messages.value = [],
    deleteRound: (fromIndex: number) => {
      // Delete logic
    },
  }
  
  return {
    sessions,
    currentSessionId,
    currentSession,
    ...sessionActions,
    ...messageActions,
  }
})
```

### 原则 2: 统一错误处理

创建通用的错误处理辅助函数：

```typescript
// utils/storeErrorHandler.ts
import { logger } from '@/utils/logger'

export function handleStoreError(
  err: unknown,
  context: string,
  options: { rethrow?: boolean; silent?: boolean } = {}
): string {
  const error = err instanceof Error ? err.message : String(err)
  
  if (!options.silent) {
    logger.error(`[Store Error] ${context}:`, error)
  }
  
  if (options.rethrow) {
    throw err
  }
  
  return error
}

// Usage in store
async function fetchData() {
  try {
    const data = await api.getData()
    state.data = data
  } catch (err) {
    const errorMessage = handleStoreError(err, 'fetchData', { rethrow: true })
    state.error = errorMessage
    throw err
  }
}
```

### 原则 3: 响应式计算

充分利用 Vue 3 的 computed 属性：

```typescript
const activeDocuments = computed(() => 
  documents.value.filter(d => d.status === 'active')
)

const pendingDocuments = computed(() => 
  documents.value.filter(d => d.status === 'pending')
)

const totalDocuments = computed(() => documents.value.length)

const hasActiveDocuments = computed(() => activeDocuments.value.length > 0)
```

### 原则 4: 离线优先架构

实现操作队列，支持离线编辑：

```typescript
interface QueuedOperation {
  id: string
  type: string
  payload: any
  timestamp: number
  retries: number
}

class OfflineQueue {
  private queue: QueuedOperation[] = []
  private isSyncing = false
  
  enqueue(op: Omit<QueuedOperation, 'id' | 'timestamp' | 'retries'>) {
    const operation: QueuedOperation = {
      ...op,
      id: crypto.randomUUID(),
      timestamp: Date.now(),
      retries: 0,
    }
    
    this.queue.push(operation)
    
    if (navigator.onLine) {
      this.sync()
    }
  }
  
  async sync() {
    if (this.isSyncing || !navigator.onLine) return
    
    this.isSyncing = true
    
    try {
      for (const op of [...this.queue]) {
        try {
          await executeOperation(op)
          this.queue = this.queue.filter(q => q.id !== op.id)
        } catch (err) {
          if (op.retries < 3) {
            op.retries++
          } else {
            // Move to failed queue
            this.queue = this.queue.filter(q => q.id !== op.id)
          }
        }
      }
    } finally {
      this.isSyncing = false
    }
  }
}
```

---

## 📈 预期改进

### 代码量减少

| Store | Before | After | Reduction |
|-------|--------|-------|-----------|
| chat.ts | 316 lines | ~250 lines | 21% ↓ |
| collaboration.ts | 207 lines | ~180 lines | 13% ↓ |
| agents.ts | 353 lines | ~280 lines | 21% ↓ |

### 开发体验提升

✅ **更清晰的 API** - Actions 按功能分组  
✅ **更好的可测试性** - 纯函数为主  
✅ **更容易调试** - 统一的错误处理  
✅ **TypeScript 友好** - 完整的类型支持  

---

## 🎯 下一步行动

1. ✅ **分析现有 Store** - 识别优化机会
2. ⏳ **应用组合式模式** - 重构 actions
3. ⏳ **统一错误处理** - 创建辅助函数
4. ⏳ **集成 CRDT** - 协作文档实时更新
5. ⏳ **添加离线支持** - 操作队列
6. ⏳ **编写测试** - 确保功能正确
7. ⏳ **性能优化** - 懒加载、批量更新

---

## 📝 总结

通过借鉴 Zustand 的设计理念，我们可以显著改善 Neurova 的 Pinia store：

- 🎯 **简化 API** - 更少的样板代码
- 🔧 **模块化** - 更好的组合性和可测试性
- 🌐 **离线优先** - 更好的用户体验
- 📦 **类型安全** - 完整的 TypeScript 支持

这些改进将使代码更易于维护、测试和扩展！
