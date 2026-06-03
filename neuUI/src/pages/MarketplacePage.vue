<template>
  <div >
    <div >
      <div >
        <h2 >
          <ShopOutlined style="color: #f59e0b" />
          市场
        </h2>
        <div >
          <a-tag>组件 <strong>{{ totalCount }}</strong></a-tag>
          <a-tag color="orange">精选 <strong>{{ featuredCount }}</strong></a-tag>
          <a-tag color="green">已安装 <strong>{{ installedCount }}</strong></a-tag>
        </div>
      </div>
      <div >
        <a-input-search
          v-model:value="searchKeyword"
          placeholder="搜索..."
          style="width: 300px"
          @search="loadMarketItems"
        />
        <a-button type="primary" @click="refresh">
          <ReloadOutlined />
          刷新
        </a-button>
      </div>
    </div>
    <div >
      <div >
        <span >分类:</span>
        <a-radio-group v-model:value="selectedType" button-style="solid" size="small" @change="loadMarketItems">
          <a-radio-button value="">全部</a-radio-button>
          <a-radio-button value="agent">Agent</a-radio-button>
          <a-radio-button value="skill">技能</a-radio-button>
          <a-radio-button value="workflow">工作流</a-radio-button>
          <a-radio-button value="model">模型</a-radio-button>
          <a-radio-button value="template">模板</a-radio-button>
          <a-radio-button value="theme">主题</a-radio-button>
        </a-radio-group>
      </div>
      <div >
        <span >筛选:</span>
        <a-checkbox v-model:checked="showFeatured" @change="loadMarketItems">仅精选</a-checkbox>
        <a-checkbox v-model:checked="showVerified" @change="loadMarketItems">仅认证</a-checkbox>
        <a-checkbox v-model:checked="showFree" @change="loadMarketItems">仅免费</a-checkbox>
        <a-select v-model:value="sortBy" style="width: 150px" placeholder="排序" size="small" @change="loadMarketItems">
          <a-select-option value="newest">最新</a-select-option>
          <a-select-option value="popular">热门</a-select-option>
          <a-select-option value="rating">评分</a-select-option>
          <a-select-option value="downloads">下载量</a-select-option>
          <a-select-option value="price_low">价格低到高</a-select-option>
          <a-select-option value="price_high">价格高到低</a-select-option>
        </a-select>
      </div>
    </div>
    <a-spin :spinning="loading">
      <div  v-if="!loading">
        <a-empty v-if="marketItems.length === 0" description="暂无商品" />
        <div
          v-for="item in marketItems"
          :key="item.id"
          @click="showItemDetail(item.id)"
        >
          <div  :style="{ background: getTypeBg(item.type) }">
            <component :is="getTypeIcon(item.type)"  />
            <div >
              <a-tag v-if="item.featured" color="orange" size="small">精选</a-tag>
              <a-tag v-if="item.verified" color="green" size="small">认证</a-tag>
              <a-tag v-if="item.is_free" color="blue" size="small">免费</a-tag>
            </div>
          </div>
          <div >
            <div >
              <h3 >{{ item.name }}</h3>
              <a-rate v-model:value="item.rating" disabled :allow-half="true" />
            </div>
            <p >{{ item.description }}</p>
            <div >
              <div >
                <a-tag :color="getTypeColor(item.type)" size="small">{{ getTypeText(item.type) }}</a-tag>
                <span ><UserOutlined /> {{ item.author_name }}</span>
                <span ><DownloadOutlined /> {{ item.download_count }}</span>
              </div>
              <div >
                <span  v-if="!item.is_free">¥{{ item.price }}</span>
                <span  v-else>免费</span>
              </div>
            </div>
            <div >
              <a-tag size="small" v-for="tag in item.tags.slice(0, 3)" :key="tag">{{ tag }}</a-tag>
            </div>
          </div>
        </div>
      </div>
    </a-spin>
    <a-pagination
      v-if="totalCount > pageSize"
      v-model:current="currentPage"
      v-model:page-size="pageSize"
      :total="totalCount"
      :show-size-changer="true"
      :show-quick-jumper="true"
      :page-size-options="['12', '24', '48']"
      show-total="共 {{ total }} 个"
      @change="loadMarketItems"
      style="margin-top: 24px; text-align: center"
    />
    <a-modal
      v-model:open="detailModalVisible"
      :title="selectedItem?.name"
      width="800px"
      :footer="null"
    >
      <div v-if="selectedItem" >
        <div >
          <div  :style="{ background: getTypeBg(selectedItem.type) }">
            <component :is="getTypeIcon(selectedItem.type)"  />
          </div>
          <div >
            <h2>{{ selectedItem.name }}</h2>
            <a-rate v-model:value="selectedItem.rating" disabled :allow-half="true" />
            <span >({{ selectedItem.rating_count }} 评价)</span>
            <div >
              <span><DownloadOutlined /> {{ selectedItem.download_count }} 下载</span>
              <span><EyeOutlined /> {{ selectedItem.view_count }} 浏览</span>
              <span><HeartOutlined /> {{ selectedItem.like_count }} 喜欢</span>
            </div>
            <div >
              <span  v-if="!selectedItem.is_free">¥{{ selectedItem.price }}</span>
              <span  v-else>免费</span>
            </div>
            <div >
              <a-button type="primary" size="large" @click="installItem" :loading="installing">
                <DownloadOutlined /> 安装
              </a-button>
              <a-button size="large" @click="purchaseItem" v-if="!selectedItem.is_free">
                购买
              </a-button>
              <a-button size="large" @click="likeItem">
                <HeartOutlined />
              </a-button>
            </div>
          </div>
        </div>
        <div >
          <a-tabs>
            <a-tab-pane key="description" tab="详情">
              <div >
                <p>{{ selectedItem.long_description || selectedItem.description }}</p>
                <div >
                  <div >
                    <span >版本</span>
                    <span >{{ selectedItem.version }}</span>
                  </div>
                  <div >
                    <span >作者</span>
                    <span >{{ selectedItem.author_name }}</span>
                  </div>
                  <div >
                    <span >更新时间</span>
                    <span >{{ formatTime(selectedItem.updated_at) }}</span>
                  </div>
                  <div >
                    <span >发布时间</span>
                    <span >{{ formatTime(selectedItem.created_at) }}</span>
                  </div>
                </div>
              </div>
            </a-tab-pane>
            <a-tab-pane key="reviews" tab="评价">
              <div >
                <a-empty description="暂无评价" v-if="reviews.length === 0" />
                <div v-else>
                  <div v-for="review in reviews" :key="review.id" >
                    <div >
                      <span >{{ review.user_name }}</span>
                      <a-rate v-model:value="review.rating" disabled :allow-half="true" />
                      <span >{{ formatTime(review.created_at) }}</span>
                    </div>
                    <p v-if="review.title" >{{ review.title }}</p>
                    <p v-if="review.content" >{{ review.content }}</p>
                  </div>
                </div>
              </div>
            </a-tab-pane>
          </a-tabs>
        </div>
      </div>
    </a-modal>
  </div>
</template>
<script setup lang="ts">
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
const marketItems = ref<MarketItem[]>([])
const reviews = ref<MarketItemReview[]>([])
const selectedItem = ref<MarketItem | null>(null)
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
const typeIcons: Record<string, Component> = {
  agent: UserOutlined,
  skill: ThunderboltOutlined,
  workflow: ApiOutlined,
  model: ExperimentOutlined,
  template: FileTextOutlined,
  theme: LayoutOutlined,
}
const typeColors: Record<string, string> = {
  agent: 'blue',
  skill: 'orange',
  workflow: 'cyan',
  model: 'purple',
  template: 'green',
  theme: 'magenta',
}
const typeBgs: Record<string, string> = {
  agent: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
  skill: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
  workflow: 'linear-gradient(135deg, #06b6d4 0%, #0891b2 100%)',
  model: 'linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%)',
  template: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
  theme: 'linear-gradient(135deg, #ec4899 0%, #db2777 100%)',
}
const typeTexts: Record<string, string> = {
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
onMounted(async () => {
  await refresh()
})
</script>
<style scoped>
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
</style>
 