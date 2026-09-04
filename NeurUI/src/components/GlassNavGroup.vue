<template>
  <!-- 侧栏折叠态: 退化为图标直达第一个子项 -->
  <template v-if="collapsed">
    <router-link
      v-if="firstItemTo"
      :to="firstItemTo"
      class="nr-nav-group-collapsed-link"
      :class="{ 'is-active': isActiveRoute(firstItemTo) }"
      :title="t(labelKey)"
    >
      <slot name="icon" />
    </router-link>
  </template>

  <!-- 展开态: 可折叠分组 -->
  <template v-else>
    <button
      type="button"
      class="nr-nav-group-head"
      :class="{ 'is-active': anyChildActive }"
      @click="toggle"
    >
      <span class="nr-nav-group-caret" :class="{ 'is-open': open }">
        <RightOutlined />
      </span>
      <span class="nr-nav-group-label">{{ t(labelKey) }}</span>
      <span v-if="count > 0" class="nr-nav-group-count">{{ count }}</span>
    </button>
    <div v-if="open" class="nr-nav-group-body">
      <slot />
    </div>
  </template>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { secureStorage } from '@/utils/security'
import { RightOutlined } from '@ant-design/icons-vue'

const props = withDefaults(defineProps<{
  /** i18n 键: 分组标题 */
  labelKey: string
  /** localStorage 持久化键后缀 */
  storageKey: string
  /** 侧栏折叠态 */
  collapsed?: boolean
  /** 第一个子项路由（折叠态图标直达目标） */
  firstItemTo?: string
  /** 子项数（折叠徽标展示） */
  count?: number
}>(), {
  collapsed: false,
  firstItemTo: '',
  count: 0,
})

const route = useRoute()
const { t } = useI18n()

const STORAGE_PREFIX = 'nr-nav-group-'

const initial = secureStorage.getObject<boolean>(STORAGE_PREFIX + props.storageKey, false)
const open = ref(initial)

function toggle() {
  open.value = !open.value
  secureStorage.setObject(STORAGE_PREFIX + props.storageKey, open.value)
}

function isActiveRoute(to: string): boolean {
  return route.path === to || route.path.startsWith(to + '/')
}

const anyChildActive = computed(() => isActiveRoute(props.firstItemTo))
</script>

<style scoped>
.nr-nav-group-head {
  display: flex; align-items: center; gap: 6px;
  width: 100%; border: 1px solid var(--nr-glass-border);
  background: var(--nr-glass-bg);
  -webkit-backdrop-filter: blur(var(--nr-glass-blur)) saturate(160%);
  backdrop-filter: blur(var(--nr-glass-blur)) saturate(160%);
  padding: 7px 10px; margin: 10px 0 4px; cursor: pointer;
  border-radius: 10px;
  transition: background 0.2s, border-color 0.2s, box-shadow 0.2s;
  font-size: 11px; font-weight: 600;
  letter-spacing: 0.02em; color: var(--nr-text-secondary);
  font-family: inherit;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}
.nr-nav-group-head:hover {
  background: var(--nr-glass-bg-hover);
  border-color: var(--nr-glass-border-hover);
  color: var(--nr-text-primary);
}
.nr-nav-group-head.is-active {
  background: var(--nr-primary-soft);
  border-color: var(--nr-primary-soft-border);
  color: var(--nr-primary-light);
}

.nr-nav-group-caret {
  display: flex; align-items: center;
  font-size: 9px; transition: transform 0.2s ease;
  color: var(--nr-text-muted);
}
.nr-nav-group-head:hover .nr-nav-group-caret { color: var(--nr-text-secondary); }
.nr-nav-group-caret.is-open { transform: rotate(90deg); }

.nr-nav-group-label { flex: 1; text-align: left; }

.nr-nav-group-count {
  font-size: 10px; font-weight: 600; letter-spacing: 0;
  color: var(--nr-text-secondary);
  background: var(--nr-glass-bg-active);
  padding: 0 7px; border-radius: 9px;
  line-height: 17px;
}

.nr-nav-group-body {
  display: flex; flex-direction: column; gap: 2px;
  padding-left: 8px;
}

/* 折叠态图标链接（与 GlassNavItem 的 collapsed 形态保持同尺寸） */
.nr-nav-group-collapsed-link {
  display: flex; align-items: center; justify-content: center;
  width: 20px; height: 20px;
  margin: 10px auto;
  color: var(--nr-text-secondary); text-decoration: none;
  font-size: 18px; border-radius: 10px;
  transition: all 0.2s ease;
}
.nr-nav-group-collapsed-link:hover { color: var(--nr-text-primary); background: var(--nr-glass-bg); }
.nr-nav-group-collapsed-link.is-active {
  color: var(--nr-primary-light); background: var(--nr-primary-soft);
}
</style>
