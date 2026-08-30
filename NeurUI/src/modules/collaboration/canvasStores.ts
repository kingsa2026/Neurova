/**
 * 画布店铺下拉数据助手 — 纯函数层（对齐后端 /stores 契约）
 */
import i18n from '@/i18n'

export interface StoreItem {
  store_id: string
  platform: string
  store_name: string
  status?: string
}

export interface StoreSelectOption {
  label: string
  value: string
}

/** 平台键 → i18n key（与后端 COMMERCE_PLATFORMS 一致的常用集） */
export const PLATFORM_NAME_KEYS: Record<string, string> = {
  amazon: 'canvas.platAmazon',
  taobao: 'canvas.platTaobao',
  jd: 'canvas.platJd',
  pdd: 'canvas.platPdd',
  'douyin-ecom': 'canvas.platDouyin',
  tiktok: 'canvas.platTiktok',
  ali1688: 'canvas.platAli1688',
  xiaohongshu: 'canvas.platXhs',
  xianyu: 'canvas.platXianyu',
  shein: 'canvas.platShein',
}

/** 平台展示名（i18n；未知平台回落原始键） */
export function platformDisplayName(key: string): string {
  const i18nKey = PLATFORM_NAME_KEYS[key]
  return i18nKey ? i18n.global.t(i18nKey) : key
}

/** 店铺显示名：店铺名（平台 · 状态）；状态缺失省略状态段 */
export function storeOptionLabel(store: StoreItem): string {
  const platform = platformDisplayName(store.platform)
  if (store.status) return `${store.store_name}（${platform} · ${store.status}）`
  return `${store.store_name}（${platform}）`
}

/** 按当前平台过滤店铺并生成下拉选项（保持后端返回顺序；平台为空=店铺授权节点，展示全部） */
export function buildStoreSelectOptions(stores: StoreItem[], currentPlatform: string): StoreSelectOption[] {
  const source = currentPlatform ? stores.filter(s => s.platform === currentPlatform) : stores
  return source.map(s => ({ label: storeOptionLabel(s), value: s.store_id }))
}
