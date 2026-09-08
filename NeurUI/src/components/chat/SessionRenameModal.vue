<template>
  <a-modal
    :open="renameModal.open"
    :title="t('chat.rename')"
    @ok="confirmRename"
    @update:open="renameModal.open = $event"
  >
    <GlassInput
      v-model:model-value="renameModal.title"
      :placeholder="t('chat.rename')"
      @update:model-value="renameModal.title = $event"
    />
  </a-modal>
</template>

<script setup lang="ts">
/**
 * 会话重命名弹窗：状态收敛在 useSessionOps 的模块级 renameModal，
 * 侧栏与 dock 历史 tab 的菜单都能触发（零 props 连线）。
 */
import { useI18n } from 'vue-i18n'
import GlassInput from '@/components/GlassInput.vue'
import { useSessionOps } from '@/composables/useSessionOps'

const { t } = useI18n()
const { renameModal, confirmRename } = useSessionOps()
</script>
