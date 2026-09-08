<template>
  <div class="subagent-window-stack">
    <SubAgentPanel
      v-for="win in subAgentWindows"
      :key="win.subagentId"
      :state="win"
      @close="closeSubAgentWindow"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * 蜂群子 Agent 浮窗堆叠（右下角，可最小化）。
 * 模板+状态原样迁自 ChatPage（2026-09-08 拆分，逻辑零改写）；
 * 事件消费在页面编排层的 onSessionSyncEvent → handleSubAgentSyncEvent。
 */
import SubAgentPanel from '@/components/chat/SubAgentPanel.vue'
import { useSubAgentWindows } from '@/composables/useSubAgentWindows'

const { subAgentWindows, closeSubAgentWindow } = useSubAgentWindows()
</script>
