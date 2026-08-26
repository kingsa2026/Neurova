import { ref } from 'vue'

/**
 * 聊天页思考程度选择（简单 light / 标准 standard / 深度 deep）
 *
 * 通过 localStorage 持久化，随 sendMessage 以 thinking_effort 字段
 * 发给后端；后端据此在系统提示中注入回答深度指令。
 */

export type ThinkingEffort = 'light' | 'standard' | 'deep'

export const THINKING_EFFORTS: ThinkingEffort[] = ['light', 'standard', 'deep']

const STORAGE_KEY = 'neurova.thinkingEffort'

function loadStored(): ThinkingEffort {
  try {
    const raw = localStorage.getItem(STORAGE_KEY) as ThinkingEffort | null
    if (raw && THINKING_EFFORTS.includes(raw)) return raw
  } catch {
    // localStorage 不可用（隐私模式等）时使用默认值
  }
  return 'standard'
}

// 模块级单例：同一页面内所有调用方共享同一档位
const effort = ref<ThinkingEffort>(loadStored())

function persist(value: ThinkingEffort) {
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    // 忽略持久化失败
  }
}

export function useThinkingEffort() {
  function setEffort(value: ThinkingEffort) {
    if (!THINKING_EFFORTS.includes(value)) return
    effort.value = value
    // 同步写透，避免异步 watch 造成读改不一致
    persist(value)
  }

  return { effort, setEffort }
}

/** 仅供测试：清空 localStorage 后调用，使单例按存储重新加载 */
export function _resetThinkingEffortForTest() {
  effort.value = loadStored()
}
