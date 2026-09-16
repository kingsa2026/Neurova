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
          <template v-for="item in cat.items" :key="item.labelKey">
            <!-- 二级菜单组（children 非空）：组头不导航，子项悬停面板展开 -->
            <div v-if="item.children" class="nr-glass-dropdown-submenu">
              <div
                class="nr-glass-dropdown-group"
                :class="{ 'is-active': isItemActive(item) }"
              >
                <component :is="item.icon" />
                <span>{{ t(item.labelKey) }}</span>
                <RightOutlined class="nr-glass-dropdown-group-arrow" />
              </div>
              <div class="nr-glass-submenu-panel">
                <router-link
                  v-for="child in item.children"
                  :key="child.to"
                  :to="child.to!"
                  class="nr-glass-dropdown-item"
                  :class="{ 'is-active': isActiveRoute(child.to) }"
                >
                  <component :is="child.icon" />
                  <span>{{ t(child.labelKey) }}</span>
                </router-link>
              </div>
            </div>
            <!-- 叶子项：直达路由链接 -->
            <router-link
              v-else
              :to="item.to!"
              class="nr-glass-dropdown-item"
              :class="{ 'is-active': isActiveRoute(item.to) }"
            >
              <component :is="item.icon" />
              <span>{{ t(item.labelKey) }}</span>
            </router-link>
          </template>
        </div>
      </template>
    </a-dropdown>
  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { DownOutlined, RightOutlined, DashboardOutlined } from '@ant-design/icons-vue'
import { TOP_NAV_CATEGORIES, type TopNavItem } from '@/config/navigation'
import { useAuthStore } from '@/stores/auth'
import { canAccessModule } from '@/utils/permissions'

const route = useRoute()
const { t } = useI18n()
const authStore = useAuthStore()

// ── 快捷入口 ──
const quickItems = [
  { to: '/dashboard', labelKey: 'nav.dashboard', icon: DashboardOutlined },
]

// ── 系统配置分类（4 组数据源 config/navigation.ts；按用户组 allowed_modules 过滤）──
interface FilteredCategory {
  key: string
  labelKey: string
  icon: (typeof TOP_NAV_CATEGORIES)[number]['icon']
  items: TopNavItem[]
}

// 二级菜单组按子项逐个过滤，全部无权限则整组隐藏；叶子项按自身路由过滤
function filterItem(item: TopNavItem, user: Record<string, unknown>): TopNavItem | null {
  if (item.children) {
    const children = item.children.filter(c => canAccessModule(c.to!, user))
    return children.length ? { ...item, children } : null
  }
  return canAccessModule(item.to!, user) ? item : null
}

const categories = computed<FilteredCategory[]>(() =>
  TOP_NAV_CATEGORIES.map(cat => ({
    ...cat,
    items: cat.items
      .map(item => filterItem(item, authStore.user ?? {}))
      .filter((item): item is TopNavItem => item !== null),
  })).filter(cat => cat.items.length > 0),
)

// ── 路由状态判定 ──
function isActiveRoute(to?: string): boolean {
  if (!to) return false
  return route.path === to || route.path.startsWith(to + '/')
}

// 二级菜单组：任一子项命中即高亮组头
function isItemActive(item: TopNavItem): boolean {
  if (item.children) return item.children.some(c => isActiveRoute(c.to))
  return isActiveRoute(item.to)
}

function isCategoryActive(cat: FilteredCategory): boolean {
  return cat.items.some(isItemActive)
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
  border-radius: 12px;
  color: var(--nr-text-secondary);
  font-size: 13px;
  font-weight: 500;
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
  font-weight: 600;
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
  border-radius: 12px;
  color: var(--nr-text-secondary);
  font-size: 13px;
  font-weight: 500;
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

/* ── 二级菜单组（悬停向右展开子面板）── */
.nr-glass-dropdown-submenu {
  position: relative;
}
.nr-glass-dropdown-group {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 10px;
  color: var(--nr-text-secondary);
  font-size: 13px;
  font-weight: 450;
  cursor: pointer;
  transition: all 0.18s ease;
  white-space: nowrap;
}
.nr-glass-dropdown-group:hover,
.nr-glass-dropdown-group.is-active {
  color: var(--nr-text-primary);
  background: var(--nr-glass-bg-hover);
}
.nr-glass-dropdown-group.is-active {
  color: var(--nr-primary-light);
  background: var(--nr-primary-soft);
}
.nr-glass-dropdown-group-arrow {
  margin-left: auto;
  font-size: 10px;
  opacity: 0.6;
}
.nr-glass-submenu-panel {
  position: absolute;
  top: -6px;
  left: calc(100% + 4px);
  display: none;
  flex-direction: column;
  gap: 2px;
  background: var(--nr-bg-overlay);
  backdrop-filter: blur(40px) saturate(180%);
  -webkit-backdrop-filter: blur(40px) saturate(180%);
  border: 1px solid var(--nr-glass-border);
  border-radius: 14px;
  padding: 6px;
  min-width: 160px;
  box-shadow: var(--nr-shadow-lg);
  z-index: 10;
}
.nr-glass-dropdown-submenu:hover .nr-glass-submenu-panel {
  display: flex;
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
