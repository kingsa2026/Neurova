<template>
  <Teleport to="body">
    <div v-if="open" class="nr-overlay" @click.self="$emit('update:open', false)">
      <div class="nr-modal" style="width: 540px">
        <div class="nr-modal-head">
          <span>{{ t('identity.title') }}</span>
          <button class="nr-close" @click="$emit('update:open', false)">&times;</button>
        </div>
        <div class="nr-modal-body">
          <div class="nr-identity-row">
            <span class="nr-identity-label">{{ t('identity.clientId') }}</span>
            <code class="nr-identity-code">{{ clientId }}</code>
            <button class="nr-copy-btn" @click="copy">
              {{ copied ? t('identity.copied') : t('identity.copy') }}
            </button>
          </div>
          <div class="nr-identity-row">
            <span class="nr-identity-label">{{ t('identity.platform') }}</span>
            <span class="nr-identity-value">{{ platformLabel }}</span>
          </div>
          <div class="nr-identity-row">
            <span class="nr-identity-label">{{ t('identity.reportStatus') }}</span>
            <span class="nr-identity-value">{{ reportEnabled ? t('identity.reportOn') : t('identity.reportOff') }}</span>
            <button
              class="nr-switch"
              :class="{ on: reportEnabled }"
              :aria-checked="reportEnabled"
              role="switch"
              @click="$emit('toggle-report')"
            >
              <span class="nr-switch-thumb" />
            </button>
          </div>
          <div class="nr-manual-row">
            <button class="nr-copy-btn" @click="manualOpen = !manualOpen">
              {{ manualOpen ? t('identity.manualCancel') : t('identity.manualReport') }}
            </button>
            <template v-if="manualOpen">
              <textarea
                v-model="manualText"
                class="nr-manual-input"
                rows="3"
                :placeholder="t('identity.manualPlaceholder')"
              />
              <button class="nr-copy-btn" :disabled="!manualText.trim()" @click="submitManual">
                {{ t('identity.manualSubmit') }}
              </button>
            </template>
          </div>
          <p class="nr-identity-hint">{{ t('identity.hint') }}</p>
        </div>
        <div class="nr-modal-foot">
          <button class="nr-action-btn" @click="$emit('update:open', false)">{{ t('identity.close') }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  open: boolean
  clientId: string
  platform?: string
  reportEnabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'toggle-report'): void
  (e: 'submit-manual', text: string): void
}>()

const { t } = useI18n()

const copied = ref(false)
const manualOpen = ref(false)
const manualText = ref('')

watch(
  () => props.open,
  (v) => {
    if (v) {
      copied.value = false
      manualOpen.value = false
      manualText.value = ''
    }
  },
)

function submitManual() {
  const text = manualText.value.trim()
  if (!text) return
  emit('submit-manual', text)
  manualOpen.value = false
  manualText.value = ''
}

const platformLabel = computed(() => {
  const map: Record<string, string> = {
    web: t('identity.platformWeb'),
    'desktop-windows': t('identity.platformDesktopWindows'),
    'desktop-linux': t('identity.platformDesktopLinux'),
    linux: t('identity.platformLinux'),
    mac: t('identity.platformMac'),
  }
  return map[props.platform ?? ''] ?? t('identity.platformUnknown')
})

async function copy() {
  try {
    await navigator.clipboard.writeText(props.clientId)
  } catch {
    // 剪贴板 API 不可用时降级：临时 textarea + execCommand
    const ta = document.createElement('textarea')
    ta.value = props.clientId
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
    } finally {
      document.body.removeChild(ta)
    }
  }
  copied.value = true
  setTimeout(() => {
    copied.value = false
  }, 2000)
}
</script>

<style scoped>
.nr-overlay {
  position: fixed;
  inset: 0;
  background: rgba(10, 14, 26, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  backdrop-filter: blur(2px);
}

.nr-modal {
  background: var(--nr-bg-card, #141a2e);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  color: var(--nr-text-primary, #fff);
  max-width: 92vw;
}

.nr-modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  font-weight: 600;
}

.nr-close {
  background: none;
  border: none;
  color: var(--nr-text-tertiary, #8a92a8);
  font-size: 18px;
  cursor: pointer;
}

.nr-modal-body {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.nr-identity-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.nr-identity-label {
  font-size: 12px;
  color: var(--nr-text-tertiary, #8a92a8);
  min-width: 88px;
}

.nr-identity-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 6px 10px;
  color: var(--nr-text-primary, #fff);
  word-break: break-all;
  flex: 1;
}

.nr-identity-value {
  font-size: 13px;
}

.nr-copy-btn {
  background: rgba(99, 102, 241, 0.15);
  color: var(--nr-primary-light, #818cf8);
  border: 1px solid rgba(99, 102, 241, 0.35);
  border-radius: 8px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.nr-copy-btn:hover {
  background: rgba(99, 102, 241, 0.25);
}

.nr-identity-hint {
  font-size: 12px;
  line-height: 1.8;
  color: var(--nr-text-tertiary, #8a92a8);
  margin: 4px 0 0;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding-top: 10px;
}

.nr-switch {
  position: relative;
  width: 40px;
  height: 22px;
  border-radius: 11px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: rgba(255, 255, 255, 0.08);
  cursor: pointer;
  transition: background 0.2s;
  padding: 0;
}

.nr-switch.on {
  background: rgba(99, 102, 241, 0.45);
  border-color: rgba(99, 102, 241, 0.6);
}

.nr-switch-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.2s;
}

.nr-switch.on .nr-switch-thumb {
  transform: translateX(18px);
}

.nr-manual-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.nr-manual-input {
  flex: 1;
  min-width: 220px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: var(--nr-text-primary, #fff);
  font-size: 12px;
  padding: 8px 10px;
  resize: vertical;
}

.nr-manual-input:focus {
  outline: none;
  border-color: rgba(99, 102, 241, 0.6);
}

.nr-modal-foot {
  padding: 0 20px 16px;
  text-align: right;
}

.nr-action-btn {
  background: rgba(255, 255, 255, 0.06);
  color: var(--nr-text-primary, #fff);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  padding: 6px 16px;
  font-size: 13px;
  cursor: pointer;
}

.nr-action-btn:hover {
  background: rgba(255, 255, 255, 0.12);
}
</style>
