/**
 * useTtsAudioGate — 流式实时 TTS 单声道门控（2026-09-03）。
 *
 * 实测缺陷：两轮对话时间间隔相近时声音重叠——live 元素与消息播放器
 * 各自独立，任何音源起播前都没有停掉其他音源（同响=两个 audio 同时
 * paused:false）。本门控记录所有 TTS 元素，起播前 pauseOthers 软停。
 */
import { describe, expect, it, vi } from 'vitest'
import { useTtsAudioGate } from '@/composables/useTtsAudioGate'

describe('useTtsAudioGate 起播门控', () => {
  it('pauseOthers 停掉除 exclude 外的所有轨道并返回被停 id', () => {
    const gate = useTtsAudioGate()
    const live = { pause: vi.fn() }
    const msg1 = { pause: vi.fn() }
    const msg2 = { pause: vi.fn() }
    gate.track('live', live)
    gate.track('msg:m1', msg1)
    gate.track('msg:m2', msg2)

    const stopped = gate.pauseOthers('live')

    expect(live.pause).not.toHaveBeenCalled()
    expect(msg1.pause).toHaveBeenCalledTimes(1)
    expect(msg2.pause).toHaveBeenCalledTimes(1)
    expect(stopped.sort()).toEqual(['msg:m1', 'msg:m2'])
  })

  it('无 exclude 时全部暂停（手动合成起播场景）', () => {
    const gate = useTtsAudioGate()
    const live = { pause: vi.fn() }
    const msg = { pause: vi.fn() }
    gate.track('live', live)
    gate.track('msg:m1', msg)

    const stopped = gate.pauseOthers()

    expect(live.pause).toHaveBeenCalledTimes(1)
    expect(msg.pause).toHaveBeenCalledTimes(1)
    expect(stopped.sort()).toEqual(['live', 'msg:m1'])
  })

  it('untrack（轨=null）后不再被暂停', () => {
    const gate = useTtsAudioGate()
    const live = { pause: vi.fn() }
    gate.track('live', live)
    gate.track('live', null)

    expect(gate.pauseOthers()).toEqual([])
  })

  it('重复 track 同 id 覆盖旧句柄（元素重渲染）', () => {
    const gate = useTtsAudioGate()
    const old = { pause: vi.fn() }
    const fresh = { pause: vi.fn() }
    gate.track('live', old)
    gate.track('live', fresh)

    gate.pauseOthers('live')
    expect(old.pause).not.toHaveBeenCalled()
    expect(fresh.pause).not.toHaveBeenCalled()
    // 旧句柄已被替换，pauseOthers('other') 停的是新句柄
    const stopped = gate.pauseOthers('other')
    expect(stopped).toEqual(['live'])
    expect(fresh.pause).toHaveBeenCalledTimes(1)
  })
})
