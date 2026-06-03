&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;h2 &gt;
          &lt;ShopOutlined style="color: #f59e0b" /&gt;
          市场
        &lt;/h2&gt;
        &lt;div &gt;
          &lt;a-tag&gt;组件 &lt;strong&gt;{{ totalCount }}&lt;/strong&gt;&lt;/a-tag&gt;
          &lt;a-tag color="orange"&gt;精选 &lt;strong&gt;{{ featuredCount }}&lt;/strong&gt;&lt;/a-tag&gt;
          &lt;a-tag color="green"&gt;已安装 &lt;strong&gt;{{ installedCount }}&lt;/strong&gt;&lt;/a-tag&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;a-input-search
          v-model:value="searchKeyword"
          placeholder="搜索..."
          style="width: 300px"
          @search="loadMarketItems"
        /&gt;
        &lt;a-button type="primary" @click="refresh"&gt;
          &lt;ReloadOutlined /&gt;
          刷新
        &lt;/a-button&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;span &gt;分类:&lt;/span&gt;
        &lt;a-radio-group v-model:value="selectedType" button-style="solid" size="small" @change="loadMarketItems"&gt;
          &lt;a-radio-button value=""&gt;全部&lt;/a-radio-button&gt;
          &lt;a-radio-button value="agent"&gt;Agent&lt;/a-radio-button&gt;
          &lt;a-radio-button value="skill"&gt;技能&lt;/a-radio-button&gt;
          &lt;a-radio-button value="workflow"&gt;工作流&lt;/a-radio-button&gt;
          &lt;a-radio-button value="model"&gt;模型&lt;/a-radio-button&gt;
          &lt;a-radio-button value="template"&gt;模板&lt;/a-radio-button&gt;
          &lt;a-radio-button value="theme"&gt;主题&lt;/a-radio-button&gt;
        &lt;/a-radio-group&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;span &gt;筛选:&lt;/span&gt;
        &lt;a-checkbox v-model:checked="showFeatured" @change="loadMarketItems"&gt;仅精选&lt;/a-checkbox&gt;
        &lt;a-checkbox v-model:checked="showVerified" @change="loadMarketItems"&gt;仅认证&lt;/a-checkbox&gt;
        &lt;a-checkbox v-model:checked="showFree" @change="loadMarketItems"&gt;仅免费&lt;/a-checkbox&gt;
        &lt;a-select v-model:value="sortBy" style="width: 150px" placeholder="排序" size="small" @change="loadMarketItems"&gt;
          &lt;a-select-option value="newest"&gt;最新&lt;/a-select-option&gt;
          &lt;a-select-option value="popular"&gt;热门&lt;/a-select-option&gt;
          &lt;a-select-option value="rating"&gt;评分&lt;/a-select-option&gt;
          &lt;a-select-option value="downloads"&gt;下载量&lt;/a-select-option&gt;
          &lt;a-select-option value="price_low"&gt;价格低到高&lt;/a-select-option&gt;
          &lt;a-select-option value="price_high"&gt;价格高到低&lt;/a-select-option&gt;
        &lt;/a-select&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;a-spin :spinning="loading"&gt;
      &lt;div  v-if="!loading"&gt;
        &lt;a-empty v-if="marketItems.length === 0" description="暂无商品" /&gt;
        &lt;div
          v-for="item in marketItems"
          :key="item.id"
          @click="showItemDetail(item.id)"
        &gt;
          &lt;div  :style="{ background: getTypeBg(item.type) }"&gt;
            &lt;component :is="getTypeIcon(item.type)"  /&gt;
            &lt;div &gt;
              &lt;a-tag v-if="item.featured" color="orange" size="small"&gt;精选&lt;/a-tag&gt;
              &lt;a-tag v-if="item.verified" color="green" size="small"&gt;认证&lt;/a-tag&gt;
              &lt;a-tag v-if="item.is_free" color="blue" size="small"&gt;免费&lt;/a-tag&gt;
            &lt;/div&gt;
          &lt;/div&gt;
          &lt;div &gt;
            &lt;div &gt;
              &lt;h3 &gt;{{ item.name }}&lt;/h3&gt;
              &lt;a-rate v-model:value="item.rating" disabled :allow-half="true" /&gt;
            &lt;/div&gt;
            &lt;p &gt;{{ item.description }}&lt;/p&gt;
            &lt;div &gt;
              &lt;div &gt;
                &lt;a-tag :color="getTypeColor(item.type)" size="small"&gt;{{ getTypeText(item.type) }}&lt;/a-tag&gt;
                &lt;span &gt;&lt;UserOutlined /&gt; {{ item.author_name }}&lt;/span&gt;
                &lt;span &gt;&lt;DownloadOutlined /&gt; {{ item.download_count }}&lt;/span&gt;
              &lt;/div&gt;
              &lt;div &gt;
                &lt;span  v-if="!item.is_free"&gt;¥{{ item.price }}&lt;/span&gt;
                &lt;span  v-else&gt;免费&lt;/span&gt;
              &lt;/div&gt;
            &lt;/div&gt;
            &lt;div &gt;
              &lt;a-tag size="small" v-for="tag in item.tags.slice(0, 3)" :key="tag"&gt;{{ tag }}&lt;/a-tag&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/a-spin&gt;
    &lt;a-pagination
      v-if="totalCount &gt; pageSize"
      v-model:current="currentPage"
      v-model:page-size="pageSize"
      :total="totalCount"
      :show-size-changer="true"
      :show-quick-jumper="true"
      :page-size-options="['12', '24', '48']"
      show-total="共 {{ total }} 个"
      @change="loadMarketItems"
      style="margin-top: 24px; text-align: center"
    /&gt;
    &lt;a-modal
      v-model:open="detailModalVisible"
      :title="selectedItem?.name"
      width="800px"
      :footer="null"
    &gt;
      &lt;div v-if="selectedItem" &gt;
        &lt;div &gt;
          &lt;div  :style="{ background: getTypeBg(selectedItem.type) }"&gt;
            &lt;component :is="getTypeIcon(selectedItem.type)"  /&gt;
          &lt;/div&gt;
          &lt;div &gt;
            &lt;h2&gt;{{ selectedItem.name }}&lt;/h2&gt;
            &lt;a-rate v-model:value="selectedItem.rating" disabled :allow-half="true" /&gt;
            &lt;span &gt;({{ selectedItem.rating_count }} 评价)&lt;/span&gt;
            &lt;div &gt;
              &lt;span&gt;&lt;DownloadOutlined /&gt; {{ selectedItem.download_count }} 下载&lt;/span&gt;
              &lt;span&gt;&lt;EyeOutlined /&gt; {{ selectedItem.view_count }} 浏览&lt;/span&gt;
              &lt;span&gt;&lt;HeartOutlined /&gt; {{ selectedItem.like_count }} 喜欢&lt;/span&gt;
            &lt;/div&gt;
            &lt;div &gt;
              &lt;span  v-if="!selectedItem.is_free"&gt;¥{{ selectedItem.price }}&lt;/span&gt;
              &lt;span  v-else&gt;免费&lt;/span&gt;
            &lt;/div&gt;
            &lt;div &gt;
              &lt;a-button type="primary" size="large" @click="installItem" :loading="installing"&gt;
                &lt;DownloadOutlined /&gt; 安装
              &lt;/a-button&gt;
              &lt;a-button size="large" @click="purchaseItem" v-if="!selectedItem.is_free"&gt;
                购买
              &lt;/a-button&gt;
              &lt;a-button size="large" @click="likeItem"&gt;
                &lt;HeartOutlined /&gt;
              &lt;/a-button&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;a-tabs&gt;
            &lt;a-tab-pane key="description" tab="详情"&gt;
              &lt;div &gt;
                &lt;p&gt;{{ selectedItem.long_description || selectedItem.description }}&lt;/p&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;版本&lt;/span&gt;
                    &lt;span &gt;{{ selectedItem.version }}&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;div &gt;
                    &lt;span &gt;作者&lt;/span&gt;
                    &lt;span &gt;{{ selectedItem.author_name }}&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;div &gt;
                    &lt;span &gt;更新时间&lt;/span&gt;
                    &lt;span &gt;{{ formatTime(selectedItem.updated_at) }}&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;div &gt;
                    &lt;span &gt;发布时间&lt;/span&gt;
                    &lt;span &gt;{{ formatTime(selectedItem.created_at) }}&lt;/span&gt;
                  &lt;/div&gt;
                &lt;/div&gt;
              &lt;/div&gt;
            &lt;/a-tab-pane&gt;
            &lt;a-tab-pane key="reviews" tab="评价"&gt;
              &lt;div &gt;
                &lt;a-empty description="暂无评价" v-if="reviews.length === 0" /&gt;
                &lt;div v-else&gt;
                  &lt;div v-for="review in reviews" :key="review.id" &gt;
                    &lt;div &gt;
                      &lt;span &gt;{{ review.user_name }}&lt;/span&gt;
                      &lt;a-rate v-model:value="review.rating" disabled :allow-half="true" /&gt;
                      &lt;span &gt;{{ formatTime(review.created_at) }}&lt;/span&gt;
                    &lt;/div&gt;
                    &lt;p v-if="review.title" &gt;{{ review.title }}&lt;/p&gt;
                    &lt;p v-if="review.content" &gt;{{ review.content }}&lt;/p&gt;
                  &lt;/div&gt;
                &lt;/div&gt;
              &lt;/div&gt;
            &lt;/a-tab-pane&gt;
          &lt;/a-tabs&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/a-modal&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  ShopOutlined,
  UserOutlined,
  DownloadOutlined,
  HeartOutlined,
  EyeOutlined,
  ReloadOutlined,
  AppstoreOutlined,
  ThunderboltOutlined,
  FileTextOutlined,
  ExperimentOutlined,
  ApiOutlined,
  LayoutOutlined,
} from '@ant-design/icons-vue'
import { marketplaceAPI, type MarketItem, type MarketItemReview } from '@/api/modules/marketplace'
import type { Component } from 'vue'
const marketItems = ref&lt;MarketItem[]&gt;([])
const reviews = ref&lt;MarketItemReview[]&gt;([])
const selectedItem = ref&lt;MarketItem | null&gt;(null)
const loading = ref(false)
const installing = ref(false)
const detailModalVisible = ref(false)
const totalCount = ref(0)
const featuredCount = ref(0)
const installedCount = ref(0)
const currentPage = ref(1)
const pageSize = ref(12)
const searchKeyword = ref('')
const selectedType = ref('')
const showFeatured = ref(false)
const showVerified = ref(false)
const showFree = ref(false)
const sortBy = ref('popular')
const typeIcons: Record&lt;string, Component&gt; = {
  agent: UserOutlined,
  skill: ThunderboltOutlined,
  workflow: ApiOutlined,
  model: ExperimentOutlined,
  template: FileTextOutlined,
  theme: LayoutOutlined,
}
const typeColors: Record&lt;string, string&gt; = {
  agent: 'blue',
  skill: 'orange',
  workflow: 'cyan',
  model: 'purple',
  template: 'green',
  theme: 'magenta',
}
const typeBgs: Record&lt;string, string&gt; = {
  agent: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
  skill: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
  workflow: 'linear-gradient(135deg, #06b6d4 0%, #0891b2 100%)',
  model: 'linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%)',
  template: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
  theme: 'linear-gradient(135deg, #ec4899 0%, #db2777 100%)',
}
const typeTexts: Record&lt;string, string&gt; = {
  agent: 'Agent',
  skill: '技能',
  workflow: '工作流',
  model: '模型',
  template: '模板',
  theme: '主题',
}
function getTypeIcon(type: string) {
  return typeIcons[type] || AppstoreOutlined
}
function getTypeColor(type: string) {
  return typeColors[type] || 'default'
}
function getTypeBg(type: string) {
  return typeBgs[type] || 'linear-gradient(135deg, #60a5fa 0%, #3b82f6 100%)'
}
function getTypeText(type: string) {
  return typeTexts[type] || '其他'
}
function formatTime(timeStr: string) {
  return new Date(timeStr).toLocaleDateString('zh-CN')
}
async function loadMarketItems() {
  loading.value = true
  try {
    const res = await marketplaceAPI.getMarketItems({
      page: currentPage.value,
      page_size: pageSize.value,
      type: (selectedType.value || undefined) as 'agent' | 'skill' | 'workflow' | 'model' | 'template' | 'theme' | undefined,
      keyword: searchKeyword.value || undefined,
      featured: showFeatured.value || undefined,
      verified: showVerified.value || undefined,
      free_only: showFree.value || undefined,
      sort_by: sortBy.value as 'popular' | 'newest' | 'rating' | 'downloads',
    })
    marketItems.value = res.items || []
    totalCount.value = res.total || 0
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '加载市场商品失败')
  } finally {
    loading.value = false
  }
}
async function loadFeaturedItems() {
  try {
    const res = await marketplaceAPI.getFeaturedItems()
    featuredCount.value = res.total || 0
  } catch (err) {
    console.error('Failed to load featured items:', err)
  }
}
async function loadInstalledItems() {
  try {
    const res = await marketplaceAPI.getInstalledItems()
    installedCount.value = res.total || 0
  } catch (err) {
    console.error('Failed to load installed items:', err)
  }
}
async function showItemDetail(id: string) {
  try {
    const res = await marketplaceAPI.getMarketItem(id)
    selectedItem.value = res
    detailModalVisible.value = true
    await loadItemReviews(id)
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '加载详情失败')
  }
}
async function loadItemReviews(id: string) {
  try {
    const res = await marketplaceAPI.getMarketItemReviews(id)
    reviews.value = res.items || []
  } catch (err) {
    console.error('Failed to load reviews:', err)
  }
}
async function installItem() {
  if (!selectedItem.value) return
  installing.value = true
  try {
    await marketplaceAPI.installItem(selectedItem.value.id)
    message.success('安装成功')
    await loadInstalledItems()
  } catch (err: unknown) {
    const e = err as {response?:{data?:{message?:string}}}
    message.error(e.response?.data?.message || '安装失败')
  } finally {
    installing.value = false
  }
}
async function purchaseItem() {
  if (!selectedItem.value) return
  try {
    await marketplaceAPI.purchaseItem(selectedItem.value.id)
    message.success('购买成功')
  } catch (err: unknown) {
    const e = err as {response?:{data?:{message?:string}}}
    message.error(e.response?.data?.message || '购买失败')
  }
}
async function likeItem() {
  if (!selectedItem.value) return
  try {
    await marketplaceAPI.likeItem(selectedItem.value.id)
    message.success('已收藏')
  } catch (err: unknown) {
    const e = err as {response?:{data?:{message?:string}}}
    message.error(e.response?.data?.message || '操作失败')
  }
}
async function refresh() {
  await Promise.all([loadMarketItems(), loadFeaturedItems(), loadInstalledItems()])
}
onMounted(async () =&gt; {
  await refresh()
})
&lt;/script&gt;
&lt;style scoped&gt;
.marketplace-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-radius: 12px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.page-title {
  font-size: 1.2rem;
  color: #e2e8f0;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.stats {
  display: flex;
  gap: 8px;
}
.header-right {
  display: flex;
  gap: 12px;
  align-items: center;
}
.filter-section {
  padding: 16px 24px;
  border-radius: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.filter-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.filter-label {
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.9rem;
}
.market-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 20px;
}
.market-item {
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.2s;
}
.market-item:hover {
  transform: translateY(-4px);
}
.item-cover {
  height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}
.cover-icon {
  font-size: 3rem;
  color: white;
}
.item-badges {
  position: absolute;
  top: 12px;
  left: 12px;
  display: flex;
  gap: 6px;
}
.item-info {
  padding: 16px;
}
.item-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.item-title {
  color: #e2e8f0;
  font-size: 1rem;
  margin: 0;
}
.item-desc {
  color: rgba(255, 255, 255, 0.5);
  font-size: 0.85rem;
  margin: 0 0 12px;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.item-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.meta-left {
  display: flex;
  gap: 10px;
  align-items: center;
}
.meta-item {
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.8rem;
  display: flex;
  align-items: center;
  gap: 4px;
}
.item-price {
  font-weight: 600;
  color: #f59e0b;
  font-size: 1rem;
}
.item-price.free {
  color: #34d399;
}
.item-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.item-detail {
  color: #e2e8f0;
}
.detail-header {
  display: flex;
  gap: 24px;
  padding-bottom: 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  margin-bottom: 24px;
}
.detail-cover {
  width: 160px;
  height: 160px;
  border-radius: 12px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.detail-cover .cover-icon {
  font-size: 4rem;
}
.detail-info {
  flex: 1;
}
.detail-info h2 {
  margin: 0 0 12px;
  color: #e2e8f0;
}
.rating-count {
  color: rgba(255, 255, 255, 0.5);
  margin-left: 8px;
}
.detail-stats {
  display: flex;
  gap: 20px;
  margin: 12px 0;
  color: rgba(255, 255, 255, 0.6);
}
.detail-price {
  margin: 16px 0;
}
.detail-price .price {
  font-size: 1.5rem;
  font-weight: 600;
  color: #f59e0b;
}
.detail-price .price.free {
  color: #34d399;
}
.detail-actions {
  display: flex;
  gap: 12px;
}
.tab-content {
  padding: 16px 0;
}
.tab-content p {
  color: rgba(255, 255, 255, 0.7);
  line-height: 1.6;
}
.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  margin-top: 24px;
}
.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.info-label {
  color: rgba(255, 255, 255, 0.5);
  font-size: 0.85rem;
}
.info-value {
  color: #e2e8f0;
  font-weight: 500;
}
.review-item {
  padding: 16px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.review-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.review-user {
  color: #e2e8f0;
  font-weight: 500;
}
.review-time {
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.8rem;
  margin-left: auto;
}
.review-title {
  color: #e2e8f0;
  margin: 4px 0;
  font-weight: 500;
}
.review-content {
  color: rgba(255, 255, 255, 0.6);
  margin: 0;
}
&lt;/style&gt;
&nbsp;