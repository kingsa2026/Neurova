/**
 * 流式实时 TTS 单声道门控。
 *
 * 问题：ChatPage 里 live 元素与每条消息的播放器 audio 各自独立，
 * 两个音源可以同时播放（两轮对话间隔相近时声音重叠）。
 * 本组合式记录所有在用的 TTS 音频元素，任何音源起播前先软停其他轨道，
 * 并返回被停的轨道 id 供宿主同步 UI 状态（▶/⏸ 复位）。
 */
export interface TtsAudioHandle {
  pause: () => void
}

export function useTtsAudioGate() {
  const tracks = new Map<string, TtsAudioHandle>()

  /** 注册/注销轨道（el=null 注销）。同 id 覆盖旧句柄（元素重渲染）。 */
  function track(id: string, el: TtsAudioHandle | null): void {
    if (el) tracks.set(id, el)
    else tracks.delete(id)
  }

  /**
   * 起播判定：除 exceptId 外全部软停；返回被停的轨道 id。
   * exceptId 省略时暂停所有轨道（手动合成等无归属音源起播）。
   */
  function pauseOthers(exceptId?: string): string[] {
    const stopped: string[] = []
    for (const [id, el] of tracks) {
      if (id === exceptId) continue
      try {
        el.pause()
      } catch {
        // 元素已卸载/失效：忽略
      }
      stopped.push(id)
    }
    return stopped
  }

  return { track, pauseOthers }
}
