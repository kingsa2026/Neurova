import { ref } from 'vue'
import { getSettings, updateSettings } from '@/api/modules/settings'

/**
 * 桌面运行权限档（对话页 composer 选择器，参考 ZCode 对话框模式）。
 *
 * 与系统设置页同源：读写 settings.advanced.desktop_runtime_mode，后端
 * computer_use/runtime_policy.py 热读该值决定 computer_* 动作"在哪跑 /
 * 要不要先问用户"，并驱动沙箱会话自动领用（sandbox/auto 档变更动作
 * 经会话池领用隔离桌面）。四档语义：
 * - sandbox 沙箱运行：所有变更动作进隔离桌面会话；无池/无会话 fail-closed 拒
 * - review  审核模式：变更动作经 approval_required 事件弹交互面板，用户同意/拒绝
 * - full    完全放开：本机执行，仅受治理内容裁决约束（后端默认 = 现状）
 * - auto    自动模式：低风险自动执行，中/高风险进沙箱
 *
 * 模块级单例：composer 与设置页共享同一档位；不做 localStorage 缓存——
 * 后端是唯一真源（设置页可能改），挂载时 load() 对齐。
 */

export type DesktopRuntimeMode = 'sandbox' | 'review' | 'full' | 'auto'

export const DESKTOP_RUNTIME_MODES: DesktopRuntimeMode[] = ['sandbox', 'review', 'full', 'auto']

const DEFAULT_MODE: DesktopRuntimeMode = 'full'

const mode = ref<DesktopRuntimeMode>(DEFAULT_MODE)

function normalize(value: unknown): DesktopRuntimeMode {
  return DESKTOP_RUNTIME_MODES.includes(value as DesktopRuntimeMode)
    ? (value as DesktopRuntimeMode)
    : DEFAULT_MODE
}

export function useDesktopRuntimeMode() {
  /** 从后端读取当前档（失败静默保持现值） */
  async function load(): Promise<void> {
    try {
      const res = await getSettings()
      // 后端 GET /settings 返回 SettingsResponse{settings:{advanced:{...}}}；
      // 经拦截器解包后多为 res.settings，保留 ApiResponse 包裹壳兜底（同 SettingPage 防御式读法）
      const env = res as unknown as Record<string, any>
      const settings = env?.settings ?? env?.data?.settings ?? env?.data
      mode.value = normalize(settings?.advanced?.desktop_runtime_mode)
    } catch {
      // 后端不可达时保持现值，不阻断对话
    }
  }

  /** 切换档位：先乐观更新，写失败回滚 */
  async function setMode(value: DesktopRuntimeMode): Promise<void> {
    if (!DESKTOP_RUNTIME_MODES.includes(value)) return
    const prev = mode.value
    mode.value = value
    try {
      await updateSettings('advanced', { desktop_runtime_mode: value })
    } catch {
      mode.value = prev
    }
  }

  return { mode, load, setMode }
}

/** 仅供测试：重置单例到默认档 */
export function _resetDesktopRuntimeModeForTest() {
  mode.value = DEFAULT_MODE
}
