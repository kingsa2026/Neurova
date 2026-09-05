<template>
  <a-config-provider :get-popup-container="getPopupContainer" :theme="antdTheme" :locale="antdLocale">
    <div :data-theme="appStore.theme" :data-skin="appStore.skin" class="nr-app">
      <!-- 氛围壁纸（登录页与受保护页面共用，随主题明暗变化） -->
      <div class="star-bg" />
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

/** Ant Design 主题联动：双皮肤（cosmic 原版 / ios Liquid Glass）× 深浅色。
 *  与 variables.css 四组令牌 + tokens.ts 保持一致。 */
const COSMIC_FONT =
  "'DM Sans', 'Noto Sans SC', 'Noto Sans JP', system-ui, sans-serif"
const IOS_FONT =
  "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'SF Pro', 'Segoe UI Variable', 'Segoe UI', 'Helvetica Neue', 'PingFang SC', 'Hiragino Sans GB', 'Noto Sans SC', 'Microsoft YaHei', sans-serif"

type AntdSkinTheme = {
  algorithm: typeof antdThemeAlgo.darkAlgorithm | typeof antdThemeAlgo.defaultAlgorithm
  token: Record<string, unknown>
}

/** skin × dark → antd 令牌（与 CSS 变量四组一一对应）。 */
const ANTD_SKIN_THEMES: Record<'cosmic' | 'ios', Record<'dark' | 'light', AntdSkinTheme>> = {
  cosmic: {
    dark: {
      algorithm: antdThemeAlgo.darkAlgorithm,
      token: {
        colorPrimary: '#6366f1',
        colorInfo: '#6366f1',
        colorLink: '#818cf8',
        colorLinkHover: '#a78bfa',
        colorBgBase: '#06080f',
        colorTextBase: '#ffffff',
        colorBgSpotlight: '#1a2236',
        colorSuccess: '#10b981',
        colorWarning: '#f59e0b',
        colorError: '#ef4444',
        borderRadius: 10,
        fontFamily: COSMIC_FONT,
        fontSize: 14,
      },
    },
    light: {
      algorithm: antdThemeAlgo.defaultAlgorithm,
      token: {
        colorPrimary: '#4d6bfe',
        colorInfo: '#4d6bfe',
        colorLink: '#4d6bfe',
        colorLinkHover: '#6a86ff',
        colorBgBase: '#ffffff',
        colorTextBase: '#1f2329',
        colorBgSpotlight: '#ffffff',
        colorSuccess: '#059669',
        colorWarning: '#d97706',
        colorError: '#dc2626',
        borderRadius: 10,
        fontFamily: COSMIC_FONT,
        fontSize: 14,
      },
    },
  },
  ios: {
    dark: {
      algorithm: antdThemeAlgo.darkAlgorithm,
      token: {
        colorPrimary: '#0a84ff',
        colorInfo: '#0a84ff',
        colorLink: '#409cff',
        colorLinkHover: '#64d2ff',
        colorBgBase: '#000000',
        colorTextBase: '#ffffff',
        colorBgSpotlight: '#2c2c2e',
        colorSuccess: '#30d158',
        colorWarning: '#ff9f0a',
        colorError: '#ff453a',
        borderRadius: 14,
        fontFamily: IOS_FONT,
        fontSize: 14,
      },
    },
    light: {
      algorithm: antdThemeAlgo.defaultAlgorithm,
      token: {
        colorPrimary: '#007aff',
        colorInfo: '#007aff',
        colorLink: '#007aff',
        colorLinkHover: '#3395ff',
        colorBgBase: '#ffffff',
        colorTextBase: '#000000',
        colorBgSpotlight: '#ffffff',
        colorSuccess: '#34c759',
        colorWarning: '#ff9500',
        colorError: '#ff3b30',
        borderRadius: 14,
        fontFamily: IOS_FONT,
        fontSize: 14,
      },
    },
  },
}

const antdTheme = computed(() => ANTD_SKIN_THEMES[appStore.skin][appStore.theme])

onMounted(() => {
  appStore.init()
  document.documentElement.setAttribute('data-theme', appStore.theme)
  document.documentElement.setAttribute('data-skin', appStore.skin)
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
