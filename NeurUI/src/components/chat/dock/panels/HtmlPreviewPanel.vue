<template>
  <div class="nr-dock-html">
    <div class="nr-dock-html-bar">
      <span class="nr-dock-html-hint">{{ t('dock.htmlSandboxHint') }}</span>
      <button class="nr-dock-html-refresh" :title="t('dock.refresh')" @click="reloadKey++"><UiIcon name="reload" :size="13" /></button>
    </div>
    <div v-if="error" class="nr-dock-error">{{ error }}</div>
    <iframe
      v-else
      :key="reloadKey"
      class="nr-dock-html-frame"
      sandbox="allow-scripts"
      :srcdoc="html"
      referrerpolicy="no-referrer"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * dock HTML 预览面板：sandbox="allow-scripts"（用户拍板）。
 * 不给 allow-same-origin —— 脚本可执行（图表/交互生效），但无同源权限：
 * 读不到 cookie/localStorage/后端 API 凭据，禁止顶层导航。
 * 已知边界：相对路径资源（./x.js）因 srcdoc 无基 URL 不加载。
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { fetchArtifactText } from '@/utils/artifacts'
import UiIcon from '@/components/UiIcon.vue'
import type { DockTab } from '@/stores/rightDock'

const props = defineProps<{ tab: DockTab }>()
const { t } = useI18n()

const reloadKey = ref(0)
const fetchedContent = ref('')
const error = ref('')

const html = computed(() => props.tab.data.content ?? fetchedContent.value)

async function loadRemote(): Promise<void> {
  const id = props.tab.data.artifactId
  if (!id) return
  error.value = ''
  try {
    fetchedContent.value = await fetchArtifactText(id)
  } catch {
    error.value = t('chat.artifactUnavailable')
  }
}

watch(
  () => [props.tab.id, props.tab.data.artifactId, props.tab.data.content],
  () => {
    if (!props.tab.data.content && props.tab.data.artifactId) void loadRemote()
  },
  { immediate: true },
)
</script>

<style scoped>
.nr-dock-html {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.nr-dock-html-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08));
}
.nr-dock-html-hint {
  flex: 1;
  font-size: 11px;
  color: var(--nr-text-secondary, #8b8fa3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nr-dock-html-refresh {
  flex: none;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--nr-text-secondary, #8b8fa3);
  cursor: pointer;
}
.nr-dock-html-refresh:hover {
  background: rgba(255, 255, 255, 0.08);
}
.nr-dock-html-frame {
  flex: 1;
  width: 100%;
  border: none;
  background: #fff;
}
.nr-dock-error {
  padding: 20px;
  text-align: center;
  color: #e5484d;
  font-size: 13px;
}
</style>
