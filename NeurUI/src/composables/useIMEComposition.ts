/**
 * IME 合成防误发（补课：对齐 QP useIMEComposition）。
 *
 * 中文/日文等输入法选词按回车会先触发 keydown（Chrome 下 isComposing=true；
 * Safari 下 compositionend 先于 keydown、keyCode=229）——直接发送会把
 * 拼音字母当消息发出。本 composable 提供统一守卫：
 *
 *   const { composing, onCompositionStart, onCompositionEnd, shouldBlockSend } =
 *     useIMEComposition()
 *   textarea: @compositionstart="onCompositionStart"
 *             @compositionend="onCompositionEnd"
 *   handleKeydown: if (shouldBlockSend(e)) return
 */
import { ref } from 'vue'

export function useIMEComposition() {
  const composing = ref(false)

  function onCompositionStart(): void {
    composing.value = true
  }

  function onCompositionEnd(): void {
    composing.value = false
  }

  /**
   * keydown 守卫：合成中、或合成提交键（keyCode 229 / isComposing）
   * 时返回 true——调用方应跳过发送。
   */
  function shouldBlockSend(e: KeyboardEvent): boolean {
    return composing.value || e.isComposing || e.keyCode === 229
  }

  return { composing, onCompositionStart, onCompositionEnd, shouldBlockSend }
}
