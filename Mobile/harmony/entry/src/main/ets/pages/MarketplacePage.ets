/**
 * MarketplacePage - 应用市场页
 *
 * 职责：展示商品网格列表，按 category 筛选（agent/skill/template/plugin/workflow），
 *   按 itemType 筛选（free/paid/subscription），搜索框，评分显示，下载按钮
 * 设计：
 *   - MarketplaceViewHelper（导出）：纯视图模型，封装分类颜色/图标/文案、商品类型文案、
 *     价格格式化、下载数格式化、评分格式化；无 UI 运行时依赖，可独立单元测试；
 *   - MarketplacePage（@Component）：Column [TopNavMenu(标题"应用市场"+返回)] +
 *     [搜索框 GlassInput] + [category 筛选 Tab + itemType 筛选 Tab] +
 *     [加载态/空态/网格列表]；
 *     网格项 GlassCard：分类徽章、名称、描述、价格、评分、下载数、下载按钮；
 *     搜索/筛选 → 本地 filter；下载 → AlertDialog 二次确认 → TODO M6 接入 API；
 *   - 颜色统一走 StyleManager，路由走 Router，API 暂无 marketplace 专用模块 →
 *     aboutToAppear 加载 mock 静态数据 + TODO 注释 M6 阶段补充真实 API。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput
 *   - ../libs/api/ApiFacade：统一 API 门面（仅作为占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：MarketplaceItem、MarketplaceCategory、MarketplaceItemType
 *
 * 用法：
 *   由 Router.push(RouteNames.MARKETPLACE) 跳转进入；
 *   aboutToAppear 加载 mock 商品列表（TODO M6 接入 api.marketplace.list）；
 *   搜索框输入 → 本地按 name/description 过滤；
 *   category/itemType 筛选 Tab 切换 → 本地过滤；
 *   下载 → AlertDialog 二次确认 → TODO M6 接入 API。
 *
 * TDD：MarketplaceViewHelper 各方法按红绿灯垂直切片逐步实现，详见 MarketplacePage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { MarketplaceItem, MarketplaceCategory, MarketplaceItemType } from '../libs/types';

/** 日志标签 */
const TAG = 'MarketplacePage';

/** 描述截断默认最大长度 */
const DEFAULT_DESC_MAX_LEN = 60;

// ===========================================================================
// MarketplaceViewHelper - 应用市场视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'primary'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class MarketplaceViewHelper {
  /**
   * 获取商品分类对应的颜色 token 名
   * 映射：agent→primary，skill→info，template→success，plugin→warning，workflow→secondary
   * @param category 商品分类
   * @return StyleManager 颜色 token 名
   */
  static getCategoryColor(category: MarketplaceCategory): string {
    if (category === 'agent') return 'primary';
    if (category === 'skill') return 'info';
    if (category === 'template') return 'success';
    if (category === 'plugin') return 'warning';
    if (category === 'workflow') return 'secondary';
    // 未覆盖的分类抛错，强制 TDD 红灯逐项补齐
    throw new Error(`getCategoryColor 未实现: ${category}`);
  }

  /**
   * 获取商品分类对应的图标 emoji
   * 映射：agent→🤖，skill→⚡，template→📋，plugin→🔌，workflow→🔄
   * @param category 商品分类
   * @return emoji 字符串
   */
  static getCategoryIcon(category: MarketplaceCategory): string {
    if (category === 'agent') return '🤖';
    if (category === 'skill') return '⚡';
    if (category === 'template') return '📋';
    if (category === 'plugin') return '🔌';
    if (category === 'workflow') return '🔄';
    throw new Error(`getCategoryIcon 未实现: ${category}`);
  }

  /**
   * 获取商品分类对应的中文标签
   * 映射：agent→智能体，skill→技能，template→模板，plugin→插件，workflow→工作流
   * @param category 商品分类
   * @return 中文文案
   */
  static getCategoryLabel(category: MarketplaceCategory): string {
    if (category === 'agent') return '智能体';
    if (category === 'skill') return '技能';
    if (category === 'template') return '模板';
    if (category === 'plugin') return '插件';
    if (category === 'workflow') return '工作流';
    throw new Error(`getCategoryLabel 未实现: ${category}`);
  }

  /**
   * 获取商品类型对应的中文标签
   * 映射：free→免费，paid→付费，subscription→订阅
   * @param itemType 商品类型
   * @return 中文文案
   */
  static getItemTypeLabel(itemType: MarketplaceItemType): string {
    if (itemType === 'free') return '免费';
    if (itemType === 'paid') return '付费';
    if (itemType === 'subscription') return '订阅';
    throw new Error(`getItemTypeLabel 未实现: ${itemType}`);
  }

  /**
   * 格式化价格展示字符串
   * 规则：free→"免费"（忽略 price）；paid→"¥{price}"；subscription→"¥{price}/月"
   * @param price 价格数值
   * @param currency 货币代码（当前固定使用 ¥ 符号）
   * @param itemType 商品类型
   * @return 价格展示字符串
   */
  static formatPrice(price: number, currency: string, itemType: MarketplaceItemType): string {
    if (itemType === 'free') return '免费';
    if (itemType === 'paid') return `¥${price}`;
    if (itemType === 'subscription') return `¥${price}/月`;
    throw new Error(`formatPrice 未实现: ${itemType}`);
  }

  /**
   * 格式化下载数为人类可读字符串
   * 规则：0 → "未下载"；1-999 → "{n}次下载"；≥1000 → "999+次下载"
   * @param count 下载次数
   * @return 下载数展示字符串
   */
  static formatDownloadCount(count: number): string {
    if (count === 0) return '未下载';
    if (count >= 1000) return '999+次下载';
    return `${count}次下载`;
  }

  /**
   * 格式化评分为星号字符串
   * 规则：1 星 → "★"，N 星 → "★"重复 N 次（N = rating）
   * @param rating 评分（1-5 整数）
   * @return 星号字符串
   */
  static formatRating(rating: number): string {
    const full = Math.floor(rating);
    if (full <= 0) return '';
    return '★'.repeat(full);
  }

  /**
   * 截断描述文本，超长时截取 maxLen 字符并追加省略号
   * @param desc 原始描述
   * @param maxLen 最大字符数
   * @return 截断后的描述；未超长则原样返回
   */
  static truncateDescription(desc: string, maxLen: number): string {
    if (desc.length <= maxLen) return desc;
    return desc.substring(0, maxLen) + '...';
  }
}

/** 分类筛选 Tab 配置 */
interface FilterOption {
  value: string;
  label: string;
}

/** 分类筛选 Tab 列表 */
const CATEGORY_FILTERS: FilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'agent', label: '智能体' },
  { value: 'skill', label: '技能' },
  { value: 'template', label: '模板' },
  { value: 'plugin', label: '插件' },
  { value: 'workflow', label: '工作流' },
];

/** 商品类型筛选 Tab 列表 */
const ITEM_TYPE_FILTERS: FilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'free', label: '免费' },
  { value: 'paid', label: '付费' },
  { value: 'subscription', label: '订阅' },
];

/**
 * Mock 市场商品数据
 * TODO M6 阶段：替换为 api.marketplace.list() 真实 API
 */
const MOCK_ITEMS: MarketplaceItem[] = [
  {
    id: 'item_1',
    name: '代码生成智能体',
    description: '基于上下文生成高质量代码片段，支持多语言',
    category: 'agent',
    itemType: 'free',
    price: 0,
    currency: 'CNY',
    author: 'Neurova',
    rating: 5,
    downloadCount: 1500,
    tags: ['code', 'ai'],
    publishedAt: '2025-01-10T08:00:00Z',
  },
  {
    id: 'item_2',
    name: '文档摘要技能',
    description: '自动提取文档关键信息，生成结构化摘要',
    category: 'skill',
    itemType: 'paid',
    price: 99,
    currency: 'CNY',
    author: 'Neurova',
    rating: 4,
    downloadCount: 50,
    tags: ['doc', 'summary'],
    publishedAt: '2025-01-15T08:00:00Z',
  },
  {
    id: 'item_3',
    name: '敏捷开发模板',
    description: '完整敏捷开发流程模板，含需求/迭代/站会等环节',
    category: 'template',
    itemType: 'subscription',
    price: 10,
    currency: 'CNY',
    author: 'Community',
    rating: 3,
    downloadCount: 0,
    tags: ['agile', 'process'],
    publishedAt: '2025-02-01T08:00:00Z',
  },
  {
    id: 'item_4',
    name: '飞书集成插件',
    description: '飞书消息推送与日程同步插件',
    category: 'plugin',
    itemType: 'free',
    price: 0,
    currency: 'CNY',
    author: 'Neurova',
    rating: 4,
    downloadCount: 200,
    tags: ['feishu', 'integration'],
    publishedAt: '2025-02-15T08:00:00Z',
  },
  {
    id: 'item_5',
    name: '自动化部署工作流',
    description: 'CI/CD 自动化部署工作流，支持灰度发布',
    category: 'workflow',
    itemType: 'paid',
    price: 199,
    currency: 'CNY',
    author: 'DevOps',
    rating: 5,
    downloadCount: 999,
    tags: ['cicd', 'deploy'],
    publishedAt: '2025-03-01T08:00:00Z',
  },
];

@Component
export struct MarketplacePage {
  // 商品列表
  @State items: MarketplaceItem[] = [];
  // 加载态
  @State loading: boolean = true;
  // 搜索关键词
  @State searchKeyword: string = '';
  // 当前激活的分类筛选值
  @State activeCategory: string = 'all';
  // 当前激活的商品类型筛选值
  @State activeItemType: string = 'all';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadItems();
  }

  /**
   * 加载商品列表
   * TODO M6 阶段：替换为真实 API（api.marketplace.list）
   */
  private async loadItems(): Promise<void> {
    this.loading = true;
    try {
      // TODO M6 阶段补充真实 API
      // const res = await this.api.marketplace.list();
      // if (res.code === 0 && res.data) { this.items = res.data.items; }
      this.items = MOCK_ITEMS.slice();
    } catch (e) {
      this.logger.error(TAG, '加载商品失败', e as Error);
      this.msg.error('加载市场商品失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换分类筛选 */
  private switchCategory(value: string): void {
    this.activeCategory = value;
  }

  /** 切换商品类型筛选 */
  private switchItemType(value: string): void {
    this.activeItemType = value;
  }

  /** 输入搜索关键词 */
  private inputSearch(v: string): void {
    this.searchKeyword = v;
  }

  /**
   * 获取经筛选+搜索后的列表
   * 规则：先按 category 过滤，再按 itemType 过滤，最后按搜索关键词匹配 name/description
   */
  private getFilteredItems(): MarketplaceItem[] {
    let result = this.items;
    if (this.activeCategory !== 'all') {
      result = result.filter((i: MarketplaceItem) => i.category === this.activeCategory);
    }
    if (this.activeItemType !== 'all') {
      result = result.filter((i: MarketplaceItem) => i.itemType === this.activeItemType);
    }
    const kw = this.searchKeyword.trim().toLowerCase();
    if (kw) {
      result = result.filter((i: MarketplaceItem) => {
        return i.name.toLowerCase().includes(kw) || i.description.toLowerCase().includes(kw);
      });
    }
    return result;
  }

  /**
   * 下载前二次确认
   */
  private confirmDownload(item: MarketplaceItem): void {
    AlertDialog.show({
      title: '确认下载',
      message: `确定要下载"${item.name}"吗？\n价格：${MarketplaceViewHelper.formatPrice(item.price, item.currency, item.itemType)}`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '下载',
        fontColor: this.sm.getColor('primary'),
        action: () => { this.download(item.id); }
      }
    });
  }

  /**
   * 执行下载
   * TODO M6 阶段：调用真实 API（api.marketplace.download）
   */
  private async download(itemId: string): Promise<void> {
    try {
      // TODO M6 阶段：const res = await this.api.marketplace.download(itemId);
      // 临时：本地增加下载计数
      this.items = this.items.map((i: MarketplaceItem) => {
        if (i.id === itemId) {
          return { ...i, downloadCount: i.downloadCount + 1 };
        }
        return i;
      });
      this.msg.success('已下载');
    } catch (e) {
      this.logger.error(TAG, '下载失败', e as Error);
      this.msg.error('下载失败');
    }
  }

  build() {
    Column() {
      // 顶部导航栏：标题"应用市场" + 返回
      TopNavMenu({
        title: '应用市场',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      })

      // 搜索框
      GlassInput({
        placeholder: '搜索商品...',
        value: this.searchKeyword,
        type: 'text',
        onChange: (v: string) => { this.inputSearch(v); },
      })
        .width('100%')
        .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })

      // 分类筛选 Tab（横向滚动）
      Scroll() {
        Row({ space: 8 }) {
          ForEach(CATEGORY_FILTERS, (opt: FilterOption) => {
            Text(opt.label)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.activeCategory === opt.value
                ? this.sm.getColor('text_on_primary')
                : this.sm.getColor('text_secondary'))
              .backgroundColor(this.activeCategory === opt.value
                ? this.sm.getColor('primary')
                : this.sm.getColor('surface'))
              .padding({ left: 12, right: 12, top: 6, bottom: 6 })
              .borderRadius(16)
              .onClick(() => { this.switchCategory(opt.value); })
          }, (opt: FilterOption) => opt.value)
        }
        .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
      }
      .scrollable(ScrollDirection.Horizontal)
      .scrollBar(BarState.Off)
      .width('100%')
      .padding({ top: 4, bottom: 4 })

      // 商品类型筛选 Tab（横向滚动）
      Scroll() {
        Row({ space: 8 }) {
          ForEach(ITEM_TYPE_FILTERS, (opt: FilterOption) => {
            Text(opt.label)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.activeItemType === opt.value
                ? this.sm.getColor('text_on_primary')
                : this.sm.getColor('text_secondary'))
              .backgroundColor(this.activeItemType === opt.value
                ? this.sm.getColor('primary')
                : this.sm.getColor('surface'))
              .padding({ left: 12, right: 12, top: 6, bottom: 6 })
              .borderRadius(16)
              .onClick(() => { this.switchItemType(opt.value); })
          }, (opt: FilterOption) => opt.value)
        }
        .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
      }
      .scrollable(ScrollDirection.Horizontal)
      .scrollBar(BarState.Off)
      .width('100%')
      .padding({ bottom: 4 })

      // 主体内容：加载态 / 空态 / 列表 三选一
      if (this.loading) {
        Column() {
          Text('加载中...')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else if (this.getFilteredItems().length === 0) {
        Column() {
          Text('暂无商品')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        List({ space: 12 }) {
          ForEach(this.getFilteredItems(), (item: MarketplaceItem) => {
            ListItem() {
              this.buildItemCard(item)
            }
          }, (item: MarketplaceItem) => item.id)
        }
        .layoutWeight(1)
        .width('100%')
        .scrollBar(BarState.Off)
        .padding({
          left: this.sm.getSpacing('md'),
          right: this.sm.getSpacing('md'),
          top: this.sm.getSpacing('sm'),
          bottom: this.sm.getSpacing('sm'),
        })
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }

  // ===========================================================================
  // 商品卡片构建器
  // ===========================================================================

  /** 单个商品卡片：分类徽章 + 名称 + 描述 + 价格 + 评分/下载 + 下载按钮 */
  @Builder
  buildItemCard(item: MarketplaceItem) {
    GlassCard() {
      Column() {
        // 顶部行：分类图标 + 分类徽章 + 类型徽章 + 下载按钮
        Row() {
          Text(MarketplaceViewHelper.getCategoryIcon(item.category))
            .fontSize(20)
          Text(MarketplaceViewHelper.getCategoryLabel(item.category))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor(MarketplaceViewHelper.getCategoryColor(item.category)))
            .margin({ left: this.sm.getSpacing('xs') })
          Text(MarketplaceViewHelper.getItemTypeLabel(item.itemType))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor('surface'))
            .margin({ left: this.sm.getSpacing('xs') })
          // 下载按钮（右对齐）
          GlassButton({
            text: '下载',
            type: 'primary',
            size: 'small',
            onClick: () => { this.confirmDownload(item); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .justifyContent(FlexAlign.Start)

        // 商品名称
        Text(item.name)
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')

        // 描述（默认 60 字符截断）
        Text(MarketplaceViewHelper.truncateDescription(item.description, DEFAULT_DESC_MAX_LEN))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')

        // 价格行
        Text(MarketplaceViewHelper.formatPrice(item.price, item.currency, item.itemType))
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('primary'))
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')

        // 评分 + 下载数
        Row() {
          Text(MarketplaceViewHelper.formatRating(item.rating))
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('warning'))
            .layoutWeight(1)
          Text(MarketplaceViewHelper.formatDownloadCount(item.downloadCount))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        .width('100%')
        .margin({ top: 4 })
        .alignItems(VerticalAlign.Center)
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }
}
