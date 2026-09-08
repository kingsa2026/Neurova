<template>
  <div class="nr-dock-computer">
    <ComputerUsePanel :state="panelState" :agent-id="agentId" @close="onClose" />
  </div>
</template>

<script setup lang="ts">
/**
 * dock 电脑分屏 tab：包裹原 ComputerUsePanel（组件保留不动）。
 * 宽度由 dock 统一管理（:deep 覆盖原 clamp 固定宽）；关闭按钮 → 关 tab。
 * computer_action 自动开屏由 useComputerPanel → rightDock.openComputer 驱动。
 */
import ComputerUsePanel from '@/components/chat/ComputerUsePanel.vue'
import { useComputerPanel } from '@/composables/useComputerPanel'
import { useRightDockStore } from '@/stores/rightDock'

const props = defineProps<{
  agentId?: string
}>()

const { state: panelState, close } = useComputerPanel()
const dock = useRightDockStore()

function onClose(): void {
  close()
  dock.closeTab('computer')
}

void props
</script>

<style scoped>
.nr-dock-computer {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
/* dock 内铺满容器：覆盖原 aside 的固定宽度与高度约束 */
.nr-dock-computer :deep(.cu-panel) {
  width: 100%;
  max-width: none;
  min-width: 0;
  height: 100%;
  border-left: none;
  flex: none;
}
</style>
