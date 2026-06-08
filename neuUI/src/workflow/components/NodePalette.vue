<template>
  <div class="node-palette">
    <!-- 搜索框 -->
    <div class="palette-header">
      <a-input-search
        v-model:value="searchQuery"
        placeholder="搜索节点..."
        allow-clear
        class="search-input"
      />
      
      <!-- 筛选器 -->
      <div class="filters">
        <a-select
          v-model:value="selectedCategory"
          placeholder="分类"
          allow-clear
          class="filter-select"
        >
          <a-select-option
            v-for="category in categories"
            :key="category"
            :value="category"
          >
            {{ getCategoryLabel(category) }}
          </a-select-option>
        </a-select>
        
        <a-select
          v-model:value="selectedSource"
          placeholder="来源"
          allow-clear
          class="filter-select"
        >
          <a-select-option value="builtin">内置</a-select-option>
          <a-select-option value="tool">工具</a-select-option>
          <a-select-option value="skill">技能</a-select-option>
          <a-select-option value="mcp">MCP</a-select-option>
        </a-select>
      </div>
    </div>
    
    <!-- 节点列表 -->
    <div class="palette-content">
      <!-- 按分类分组显示 -->
      <template v-if="groupedNodes.length > 0">
        <div
          v-for="group in groupedNodes"
          :key="group.category"
          class="node-group"
        >
          <div class="group-header" @click="toggleGroup(group.category)">
            <span class="group-icon">{{ getCategoryIcon(group.category) }}</span>
            <span class="group-title">{{ getCategoryLabel(group.category) }}</span>
            <span class="group-count">{{ group.nodes.length }}</span>
            <span class="group-toggle">
              <caret-down-outlined v-if="expandedGroups.has(group.category)" />
              <caret-right-outlined v-else />
            </span>
          </div>
          
          <div v-if="expandedGroups.has(group.category)" class="group-content">
            <div
              v-for="node in group.nodes"
              :key="node.type"
              class="node-item"
              draggable="true"
              @dragstart="handleDragStart($event, node)"
              @click="handleNodeClick(node)"
            >
              <div class="node-icon" :style="{ backgroundColor: getNodeColor(node) }">
                {{ getNodeIcon(node) }}
              </div>
              <div class="node-info">
                <div class="node-label">{{ node.label }}</div>
                <div class="node-description">{{ node.description }}</div>
              </div>
              <div class="node-source">
                <a-tag :color="getSourceColor(node.source)" size="small">
                  {{ getSourceLabel(node.source) }}
                </a-tag>
              </div>
            </div>
          </div>
        </div>
      </template>
      
      <!-- 无结果提示 -->
      <a-empty
        v-else-if="searchQuery || selectedCategory || selectedSource"
        description="没有找到匹配的节点"
        :image-style="{ height: '60px' }"
      />
      
      <!-- 加载中 -->
      <a-spin v-else-if="loading" class="loading-spinner" />
    </div>
    
    <!-- 底部统计 -->
    <div class="palette-footer">
      <span class="node-count">{{ filteredNodes.length }} 个节点</span>
      <a-button type="link" size="small" @click="handleRefresh">
        <reload-outlined />
        刷新
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import {
  CaretDownOutlined,
  CaretRightOutlined,
  ReloadOutlined,
} from '@ant-design/icons-vue'
import type { NodeDefinition, NodeCategory, NodeSource } from '../types'
import { nodeRegistry, getNodeColor, getNodeIcon, loadNodesFromBackend } from '../registry'

// ==================== Props ====================

interface Props {
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
})

// ==================== Emits ====================

const emit = defineEmits<{
  (e: 'select', node: NodeDefinition): void
  (e: 'drag-start', node: NodeDefinition, event: DragEvent): void
  (e: 'refresh'): void
}>()

// ==================== 状态 ====================

const searchQuery = ref('')
const selectedCategory = ref<NodeCategory | undefined>(undefined)
const selectedSource = ref<NodeSource | undefined>(undefined)
const expandedGroups = ref(new Set<string>())

// ==================== 计算属性 ====================

/**
 * 所有节点
 */
const allNodes = computed(() => nodeRegistry.getAll())

/**
 * 分类列表
 */
const categories = computed(() => {
  const cats = new Set<string>()
  allNodes.value.forEach(node => cats.add(node.category))
  return Array.from(cats).sort()
})

/**
 * 过滤后的节点
 */
const filteredNodes = computed(() => {
  let nodes = allNodes.value
  
  // 搜索过滤
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    nodes = nodes.filter(node => 
      node.label.toLowerCase().includes(query) ||
      node.description?.toLowerCase().includes(query) ||
      node.type.toLowerCase().includes(query) ||
      node.tags?.some(tag => tag.toLowerCase().includes(query))
    )
  }
  
  // 分类过滤
  if (selectedCategory.value) {
    nodes = nodes.filter(node => node.category === selectedCategory.value)
  }
  
  // 来源过滤
  if (selectedSource.value) {
    nodes = nodes.filter(node => node.source === selectedSource.value)
  }
  
  return nodes
})

/**
 * 按分类分组的节点
 */
const groupedNodes = computed(() => {
  const groups = new Map<string, NodeDefinition[]>()
  
  filteredNodes.value.forEach(node => {
    const category = node.category
    if (!groups.has(category)) {
      groups.set(category, [])
    }
    groups.get(category)!.push(node)
  })
  
  return Array.from(groups.entries())
    .map(([category, nodes]) => ({
      category,
      nodes: nodes.sort((a, b) => a.label.localeCompare(b.label)),
    }))
    .sort((a, b) => a.category.localeCompare(b.category))
})

// ==================== 方法 ====================

/**
 * 获取分类标签
 */
function getCategoryLabel(category: string): string {
  const labels: Record<string, string> = {
    input: '输入',
    output: '输出',
    llm: 'LLM',
    tool: '工具',
    skill: '技能',
    control: '控制',
    data: '数据',
    memory: '记忆',
    evolution: '进化',
    tdd: 'TDD',
    media: '媒体',
    integration: '集成',
    custom: '自定义',
  }
  return labels[category] || category
}

/**
 * 获取分类图标
 */
function getCategoryIcon(category: string): string {
  const icons: Record<string, string> = {
    input: '📥',
    output: '📤',
    llm: '🤖',
    tool: '🔧',
    skill: '⚡',
    control: '🔀',
    data: '📊',
    memory: '🧠',
    evolution: '📈',
    tdd: '🧪',
    media: '🎬',
    integration: '🔗',
    custom: '📦',
  }
  return icons[category] || '📦'
}

/**
 * 获取来源标签
 */
function getSourceLabel(source: string): string {
  const labels: Record<string, string> = {
    builtin: '内置',
    tool: '工具',
    skill: '技能',
    mcp: 'MCP',
  }
  return labels[source] || source
}

/**
 * 获取来源颜色
 */
function getSourceColor(source: string): string {
  const colors: Record<string, string> = {
    builtin: 'blue',
    tool: 'green',
    skill: 'orange',
    mcp: 'purple',
  }
  return colors[source] || 'default'
}

/**
 * 切换分组展开/折叠
 */
function toggleGroup(category: string) {
  if (expandedGroups.value.has(category)) {
    expandedGroups.value.delete(category)
  } else {
    expandedGroups.value.add(category)
  }
}

/**
 * 处理拖拽开始
 */
function handleDragStart(event: DragEvent, node: NodeDefinition) {
  // 设置拖拽数据
  event.dataTransfer?.setData('application/neurflow-node', JSON.stringify({
    type: node.type,
    label: node.label,
    category: node.category,
    source: node.source,
  }))
  
  // 设置拖拽效果
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'copy'
  }
  
  emit('drag-start', node, event)
}

/**
 * 处理节点点击
 */
function handleNodeClick(node: NodeDefinition) {
  emit('select', node)
}

/**
 * 处理刷新
 */
async function handleRefresh() {
  await loadNodesFromBackend()
  emit('refresh')
}

// ==================== 生命周期 ====================

onMounted(() => {
  // 默认展开所有分类
  categories.value.forEach(category => {
    expandedGroups.value.add(category)
  })
})

// ==================== 监听器 ====================

watch(searchQuery, () => {
  // 搜索时展开所有匹配的分类
  if (searchQuery.value) {
    groupedNodes.value.forEach(group => {
      expandedGroups.value.add(group.category)
    })
  }
})
</script>

<style scoped>
.node-palette {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
  border-right: 1px solid #f0f0f0;
}

.palette-header {
  padding: 12px;
  border-bottom: 1px solid #f0f0f0;
}

.search-input {
  margin-bottom: 8px;
}

.filters {
  display: flex;
  gap: 8px;
}

.filter-select {
  flex: 1;
}

.palette-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.node-group {
  margin-bottom: 8px;
}

.group-header {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  border-radius: 6px;
  transition: background-color 0.2s;
}

.group-header:hover {
  background: #f5f5f5;
}

.group-icon {
  margin-right: 8px;
  font-size: 16px;
}

.group-title {
  flex: 1;
  font-weight: 500;
  color: #262626;
}

.group-count {
  margin-right: 8px;
  color: #8c8c8c;
  font-size: 12px;
}

.group-toggle {
  color: #8c8c8c;
}

.group-content {
  padding: 4px 0 4px 16px;
}

.node-item {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  margin: 4px 0;
  cursor: grab;
  border-radius: 6px;
  transition: all 0.2s;
  border: 1px solid transparent;
}

.node-item:hover {
  background: #e6f7ff;
  border-color: #91d5ff;
}

.node-item:active {
  cursor: grabbing;
  background: #bae7ff;
}

.node-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  margin-right: 12px;
  font-size: 16px;
  color: #fff;
  flex-shrink: 0;
}

.node-info {
  flex: 1;
  min-width: 0;
}

.node-label {
  font-weight: 500;
  color: #262626;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-description {
  font-size: 12px;
  color: #8c8c8c;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 2px;
}

.node-source {
  margin-left: 8px;
  flex-shrink: 0;
}

.loading-spinner {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 200px;
}

.palette-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-top: 1px solid #f0f0f0;
  background: #fafafa;
}

.node-count {
  font-size: 12px;
  color: #8c8c8c;
}
</style>
