<template>
  <!-- 皮肤切换（与语言切换交互一致：头部图标按钮 + 下拉菜单） -->
  <a-dropdown placement="bottomRight" :trigger="['click']">
    <button
      class="nr-skin-trigger"
      :title="t('theme.skinLabel')"
      :aria-label="t('theme.skinLabel')"
    >
      <BgColorsOutlined />
    </button>
    <template #overlay>
      <a-menu :selected-keys="[appStore.skin]" @click="onSelect">
        <a-menu-item key="cosmic">
          <CheckOutlined v-if="appStore.skin === 'cosmic'" />
          {{ t('theme.skinCosmic') }}
        </a-menu-item>
        <a-menu-item key="ios">
          <CheckOutlined v-if="appStore.skin === 'ios'" />
          {{ t('theme.skinIos') }}
        </a-menu-item>
      </a-menu>
    </template>
  </a-dropdown>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { BgColorsOutlined, CheckOutlined } from '@ant-design/icons-vue'
import { useAppStore, type AppSkin } from '@/stores/app'

const { t } = useI18n()
const appStore = useAppStore()

function onSelect({ key }: { key: string | number }): void {
  if (key === 'cosmic' || key === 'ios') {
    appStore.setSkin(key as AppSkin)
  }
}
</script>

<style scoped>
/* 与 MainLayout 语言切换按钮（.nr-header-action）完全同款：
 * 36px 圆角方块、透明底、hover 玻璃背景 */
.nr-skin-trigger {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--nr-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  transition: all 0.2s;
  text-decoration: none;
}
.nr-skin-trigger:hover {
  background: var(--nr-glass-bg-hover);
  color: var(--nr-text-primary);
}
</style>