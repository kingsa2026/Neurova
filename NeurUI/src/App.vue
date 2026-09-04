<template>
  <a-config-provider :get-popup-container="getPopupContainer" :theme="antdTheme" :locale="antdLocale">
    <div :data-theme="appStore.theme" class="nr-app">
      <div class="star-bg" v-if="appStore.isDark" />
      <router-view />
      <ModelDownloadDialog ref="modelDownloadDialog" />
    </div>
  </a-config-provider>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { theme as antdThemeAlgo, type ConfigProviderProps } from 'ant-design-vue'
import localeZhCN from 'ant-design-vue/locale/zh_CN'
import localeEnUS from 'ant-design-vue/locale/en_US'
import localeArEG from 'ant-design-vue/locale/ar_EG'
import localeDeDE from 'ant-design-vue/locale/de_DE'
import localeEsES from 'ant-design-vue/locale/es_ES'
import localeFrFR from 'ant-design-vue/locale/fr_FR'
import localeHiIN from 'ant-design-vue/locale/hi_IN'
import localeItIT from 'ant-design-vue/locale/it_IT'
import localeJaJP from 'ant-design-vue/locale/ja_JP'
import localeKoKR from 'ant-design-vue/locale/ko_KR'
import localeRuRU from 'ant-design-vue/locale/ru_RU'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useAgentStore } from '@/stores/agents'
import { initErrorReporter, setErrorReporterInstance } from '@/utils/errorReporter'
import ModelDownloadDialog from '@/components/ModelDownloadDialog.vue'
import { listPendingDownloads } from '@/api/modules/models'

const appStore = useAppStore()
const authStore = useAuthStore()
const agentStore = useAgentStore()
const { locale } = useI18n()

/** App i18n 语言 → ant-design-vue 组件语言包。
 *  此前 ConfigProvider 未传 locale，antd 组件（空态/分页/日期弹窗/弹窗按钮）
 *  全站烙英文默认值（如 Empty "No data"），与页面 i18n 语言不一致。 */
const antdLocale = computed<ConfigProviderProps['locale']>(() => {
  const map: Record<string, ConfigProviderProps['locale']> = {
    'zh-CN': localeZhCN,
    'en-US': localeEnUS,
    'ar-SA': localeArEG,
    'de-DE': localeDeDE,
    'es-ES': localeEsES,
    'fr-FR': localeFrFR,
    'hi-IN': localeHiIN,
    'it-IT': localeItIT,
    'ja-JP': localeJaJP,
    'ko-KR': localeKoKR,
    'ru-RU': localeRuRU,
  }
  return map[locale.value] ?? localeEnUS
})

const getPopupContainer = (triggerNode?: HTMLElement) =>
  (triggerNode?.parentNode || document.body) as HTMLElement

/** Ant Design 主题跟随应用主题：深色用 darkAlgorithm，浅色用 defaultAlgorithm。 */
const antdTheme = computed(() =>
  appStore.isDark
    ? {
        algorithm: antdThemeAlgo.darkAlgorithm,
        token: {
          colorPrimary: '#6366f1',
          colorInfo: '#6366f1',
          colorBgBase: '#0a0e1a',
          colorTextBase: '#ffffff',
          borderRadius: 10,
        },
      }
    : {
        algorithm: antdThemeAlgo.defaultAlgorithm,
        token: {
          colorPrimary: '#4d6bfe',
          colorInfo: '#4d6bfe',
          colorBgBase: '#ffffff',
          colorTextBase: '#1f2329',
          borderRadius: 10,
        },
      },
)

onMounted(() => {
  appStore.init()
  document.documentElement.setAttribute('data-theme', appStore.theme)
  agentStore.loadAgents()
  agentStore.loadWorkflowAgents() // 遗留③b：合并 Neurflow 工作流 Agent（静默失败）
  if (authStore.isAuthenticated) {
    authStore.fetchCurrentUser()
  }
  // 错误日志自动上报：桌面/浏览器端崩溃与运行期错误采集（官网收报端点）
  setErrorReporterInstance(
    initErrorReporter({
      version: import.meta.env.VITE_APP_VERSION || '',
    }),
  )
})

// 模型下载提示框：登录态下查一次待下载清单，有缺失才弹（尽力而为，静默失败）
const modelDownloadDialog = ref<InstanceType<typeof ModelDownloadDialog> | null>(null)
watch(
  () => authStore.isAuthenticated,
  (authed) => {
    if (authed) {
      listPendingDownloads()
        .then((items) => {
          if (Array.isArray(items) && items.some((i) => i && !i.available)) {
            modelDownloadDialog.value?.open()
          }
        })
        .catch(() => {})
    }
  },
  { immediate: true },
)
</script>

<style>
.nr-app {
  position: relative;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  z-index: 1;
}
</style>
