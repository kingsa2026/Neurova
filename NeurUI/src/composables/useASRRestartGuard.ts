import { ref } from 'vue'

/**
 * ASR (Automatic Speech Recognition) restart guard.
 *
 * Prevents the speech recognition `onend` handler from entering an infinite
 * auto-restart loop when `isRecording` is stuck true or the recognizer keeps
 * dying. The guard caps the number of consecutive restarts; once the cap is
 * hit, `canRestart()` returns false so the caller can stop restarting and
 * surface a user-visible message instead.
 *
 * Lifecycle:
 *  - `reset()` is called every time the user explicitly starts recording.
 *  - `recordRestart()` is called each time `onend` triggers a restart.
 *  - `canRestart()` gates the restart decision.
 */
export function useASRRestartGuard(maxRestarts = 3) {
  const restartCount = ref(0)
  const limitReached = ref(false)

  function reset() {
    restartCount.value = 0
    limitReached.value = false
  }

  function canRestart() {
    return !limitReached.value && restartCount.value < maxRestarts
  }

  function recordRestart() {
    restartCount.value++
    if (restartCount.value >= maxRestarts) {
      limitReached.value = true
    }
  }

  return { restartCount, limitReached, reset, canRestart, recordRestart }
}
