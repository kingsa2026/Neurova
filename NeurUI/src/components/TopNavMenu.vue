<template>
  <nav class="nr-topnav" :aria-label="t('nav.globalNav')">
    <!-- 快捷入口: 总览 -->
    <router-link
      v-for="quick in quickItems"
      :key="quick.to"
      :to="quick.to"
      class="nr-topnav-quick"
      :class="{ 'is-active': isActiveRoute(quick.to) }"
    >
      <component :is="quick.icon" />
      <span class="nr-topnav-quick-label">{{ t(quick.labelKey) }}</span>
    </router-link>

    <!-- 系统配置分类下拉（数据源: config/navigation.ts，全用户可见） -->
    <a-dropdown
      v-for="cat in categories"
      :key="cat.key"
      :trigger="['hover']"
      placement="bottomLeft"
    >
      <div class="nr-topnav-cat" :class="{ 'is-active': isCategoryActive(cat) }">
        <component :is="cat.icon" />
        <span class="nr-topnav-cat-label">{{ t(cat.labelKey) }}</span>
        <DownOutlined class="nr-topnav-cat-arrow" />
      </div>
      <template #overlay>
        <div class="nr-glass-dropdown">
          <router-link
            v-for="item in cat.items"
            :key="item.to"
            :to="item.to"
            class="nr-glass-dropdown-item"
            :class="{ 'is-active': isActiveRoute(item.to) }"
          >
            <component :is="item.icon" />
            <span>{{ t(item.labelKey) }}</span>
          </router-link>
        </div>
      </template>
    </a-dropdown>
  </nav>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { DownOutlined, DashboardOutlined } from '@ant-design/icons-vue'
import { TOP_NAV_CATEGORIES } from '@/config/navigation'

const route = useRoute()
const { t } = useI18n()

// ── 快捷入口 ──
const quickItems = [
  { to: '/dashboard', labelKey: 'nav.dashboard', icon: DashboardOutlined },
]

// ── 系统配置分类（4 组，模板仅渲染) ──
const categories = TOP_NAV_CATEGORIES

// ── 路由状态判定 ──
function isActiveRoute(to: string): boolean {
  return route.path === to || route.path.startsWith(to + '/')
}

function isCategoryActive(cat: (typeof TOP_NAV_CATEGORIES)[number]): boolean {
  return cat.items.some(item => isActiveRoute(item.to))
}
</script>

<style scoped>
.nr-topnav {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 1;
  justify-content: center;
  overflow-x: auto;
  overflow-y: hidden;
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.nr-topnav::-webkit-scrollbar {
  display: none;
}

/* ── 快捷入口 ── */
.nr-topnav-quick {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 10px;
  color: var(--nr-text-secondary);
  font-size: 13px;
  font-weight: 450;
  text-decoration: none;
  transition: all 0.2s ease;
  white-space: nowrap;
}
.nr-topnav-quick:hover {
  color: var(--nr-text-primary);
  background: var(--nr-glass-bg-hover);
}
.nr-topnav-quick.is-active {
  color: var(--nr-primary-light);
  background: var(--nr-primary-soft);
  font-weight: 550;
}
.nr-topnav-quick-label {
  display: inline;
}

/* ── 分类下拉触发器 ── */
.nr-topnav-cat {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 10px;
  color: var(--nr-text-secondary);
  font-size: 13px;
  font-weight: 450;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
  user-select: none;
}
.nr-topnav-cat:hover,
.nr-topnav-cat.is-active {
  color: var(--nr-text-primary);
  background: var(--nr-glass-bg-hover);
}
.nr-topnav-cat.is-active {
  color: var(--nr-primary-light);
  background: var(--nr-primary-soft);
}
.nr-topnav-cat-arrow {
  font-size: 10px;
  opacity: 0.6;
  transition: transform 0.2s ease;
}

/* ── 液态玻璃弹出层 ── */
.nr-glass-dropdown {
  background: var(--nr-bg-overlay);
  backdrop-filter: blur(40px) saturate(180%);
  -webkit-backdrop-filter: blur(40px) saturate(180%);
  border: 1px solid var(--nr-glass-border);
  border-radius: 14px;
  padding: 6px;
  min-width: 180px;
  box-shadow: var(--nr-shadow-lg);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* ── 弹出层菜单项 ── */
.nr-glass-dropdown-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 10px;
  color: var(--nr-text-secondary);
  font-size: 13px;
  font-weight: 450;
  text-decoration: none;
  transition: all 0.18s ease;
  white-space: nowrap;
}
.nr-glass-dropdown-item:hover {
  color: var(--nr-text-primary);
  background: var(--nr-glass-bg-hover);
}
.nr-glass-dropdown-item.is-active {
  color: var(--nr-primary-light);
  background: var(--nr-primary-soft);
  font-weight: 550;
}

/* ── 响应式: 小屏隐藏快捷入口文字和分类标签 ── */
@media (max-width: 1024px) {
  .nr-topnav-quick-label,
  .nr-topnav-cat-label {
    display: none;
  }
  .nr-topnav-cat-arrow {
    display: none;
  }
}
</style>
