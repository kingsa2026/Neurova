/**
 * MarketplacePage - 技能市场页（R6 接真实 API）
 *
 * 职责：展示市场技能列表（/v1/marketplace/skills?with_total=true），按来源筛选，
 *       搜索，安装/卸载（installed 徽章如实区分）
 * 设计：
 *   - MarketplaceViewHelper（导出）：纯视图模型，封装来源徽章颜色/文案、
 *     下载数格式化、评分格式化、描述截断；无 UI 运行时依赖，可独立单元测试；
 *   - MarketplacePage（@Component）：Column [TopNavMenu(标题"技能市场"+返回)] +
 *     [搜索框 GlassInput] + [source 筛选 Tab] +
 *     [加载态/空态/列表]；
 *     列表项 GlassCard：分类徽章、名称、描述、版本、评分、下载数、安装/卸载按钮；
 *   - 颜色统一走 StyleManager，路由走 Router，已接线 PageMap（P1-33）；
 *     数据源 MarketplaceApi（R6：替换 mock）。
 *
 * 契约说明（诚实缺省）：
 *   - 后端 marketplace.py 是技能市场（skill/author/version/downloads/installed/
 *     source），不是旧 mock 的应用商店（agent/template/plugin/workflow 分类、
 *     free/paid/subscription 价型）——那些维度本页不再渲染；
 *   - 安装走 POST /skills/{id}/install（agent 过属主门，409=安全门拒装拒因透传）；
 *     卸载走 DELETE /skills/{id}/install（联邦注销），操作后整表刷新拿真值；
 *   - category 是开放集合（general 等），本地过滤；来源（local/aliyun/xfyun）
 *     传服务端 source 参数。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput
 *   - ../libs/api/ApiFacade：统一 API 门面（api.marketplace.*）
 *   - ../libs/api/modules/MarketplaceApi：MarketSkillDto 契约
 *   - ../routing/Router、../libs/style/StyleManager、../libs/logger/Logger、
 *     ../libs/message/MessageManager
 *
 * 用法：
 *   由 Router.push(RouteNames.MARKETPLACE) 跳转进入；
 *   aboutToAppear 经 api.marketplace.list() 加载（一次 50 条）；
 *   搜索框输入 → 本地按 name/description 过滤；
 *   source 筛选 Tab 切换 → 服务端过滤重拉；
 *   安装/卸载 → AlertDialog 二次确认 → api → 刷新。
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { MarketSkillDto } from '../libs/api/modules/MarketplaceApi';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';

/** 日志标签 */
const TAG = 'MarketplacePage';

/** 描述截断默认最大长度 */
const DEFAULT_DESC_MAX_LEN = 60;

/** 列表拉取条数上限 */
const LIST_LIMIT = 50;

// ===========================================================================
// MarketplaceViewHelper - 技能市场视图模型（纯函数，无 UI 依赖，可独立单元测试）
// ===========================================================================

export class MarketplaceViewHelper {
  /**
   * 获取来源对应的颜色 token 名（未知兜 'info'——source 开放集合）
   * 映射：local→primary、aliyun→secondary、xfyun→info
   * @param source 条目来源
   * @return StyleManager 颜色 token 名
   */
  static getSourceColor(source: string): string {
    if (source === 'local') return 'primary';
    if (source === 'aliyun') return 'secondary';
    if (source === 'xfyun') return 'info';
    return 'info';
  }

  /**
   * 获取来源对应的中文标签（未知原样返回）
   * 映射：local→官方上架、aliyun→阿里云市场、xfyun→讯飞市场
   * @param source 条目来源
   * @return 中文文案
   */
  static getSourceLabel(source: string): string {
    if (source === 'local') return '官方上架';
    if (source === 'aliyun') return '阿里云市场';
    if (source === 'xfyun') return '讯飞市场';
    return source;
  }

  /**
   * 获取分类对应的图标 emoji（未知兜 '🧩'——category 开放集合）
   * @param category 分类
   * @return emoji 字符串
   */
  static getCategoryIcon(category: string): string {
    if (category === 'general') return '🧩';
    if (category === 'code') return '💻';
    if (category === 'docs') return '📄';
    if (category === 'data') return '📊';
    if (category === 'integration') return '🔌';
    return '🧩';
  }

  /**
   * 格式化下载数为人类可读字符串
   * 规则：0 → "暂无下载"；≥1M → "1.0M 次下载"；≥1K → "1.0K 次下载"；其他 → "{n} 次下载"
   * @param downloads 下载次数（后端 downloads）
   * @return 下载数展示字符串
   */
  static formatDownloadCount(downloads: number): string {
    if (downloads === 0) return '暂无下载';
    const M = 1024 * 1024;
    const K = 1024;
    if (downloads >= M) {
      return `${(downloads / M).toFixed(1)}M 次下载`;
    }
    if (downloads >= K) {
      return `${(downloads / K).toFixed(1)}K 次下载`;
    }
    return `${downloads} 次下载`;
  }

  /**
   * 格式化评分为星号字符串（0 → 空串由"暂无评分"兜底展示）
   * 规则：1 星 → "★"，N 星 → "★"重复 N 次（N = floor(rating)）
   * @param rating 评分（0-5，可带小数）
   * @return 星号字符串
   */
  static formatRating(rating: number): string {
    const full = Math.floor(rating);
    if (full <= 0) return '';
    return '★'.repeat(full);
  }

  /**
   * 评分展示字符串（0 → "暂无评分"，否则星级 + 数值）
   * @param rating 评分（0-5）
   * @return 评分展示字符串
   */
  static formatRatingText(rating: number): string {
    if (rating <= 0) return '暂无评分';
    return `${MarketplaceViewHelper.formatRating(rating)} ${rating.toFixed(1)}`;
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

/** 来源筛选 Tab 配置 */
interface SourceFilterOption {
  value: string;
  label: string;
}

/** 来源筛选 Tab 列表（value 传服务端 source 参数） */
const SOURCE_FILTERS: SourceFilterOption[] = [
  { value: '', label: '全部' },
  { value: 'local', label: '官方上架' },
  { value: 'aliyun', label: '阿里云' },
  { value: 'xfyun', label: '讯飞' },
];

@Component
export struct MarketplacePage {
  // 市场技能列表（api.marketplace.list() 真实数据）
  @State items: MarketSkillDto[] = [];
  // 加载态
  @State loading: boolean = true;
  // 搜索关键词
  @State searchKeyword: string = '';
  // 当前激活的来源筛选值（'' = 全部）
  @State activeSource: string = '';
  // 服务端总数
  @State totalCount: number = 0;
  // 写操作进行中（防重复点击）
  @State operatingId: string = '';

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
   * 加载市场技能列表（GET /v1/marketplace/skills?with_total=true，source 走服务端）
   */
  private async loadItems(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.marketplace.list({
        limit: LIST_LIMIT,
        offset: 0,
        source: this.activeSource,
      });
      if (res.code === 0 && res.data) {
        this.items = res.data.items;
        this.totalCount = res.data.total;
      } else {
        this.items = [];
        this.totalCount = 0;
        this.msg.error(res.message && res.message.length > 0 ? res.message : '加载市场技能失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载市场技能失败', e as Error);
      this.msg.error('加载市场技能失败');
      this.items = [];
    } finally {
      this.loading = false;
    }
  }

  /** 切换来源筛选（服务端过滤 → 重拉） */
  private switchSource(value: string): void {
    this.activeSource = value;
    this.loadItems();
  }

  /** 输入搜索关键词 */
  private inputSearch(v: string): void {
    this.searchKeyword = v;
  }

  /**
   * 获取经搜索过滤后的列表（本地过滤 name/description；category 为开放集合随条目展示）
   */
  private getFilteredItems(): MarketSkillDto[] {
    let result = this.items;
    const kw = this.searchKeyword.trim().toLowerCase();
    if (kw) {
      result = result.filter((i: MarketSkillDto) => {
        return i.name.toLowerCase().includes(kw) || i.description.toLowerCase().includes(kw);
      });
    }
    return result;
  }

  /**
   * 安装前二次确认
   */
  private confirmInstall(item: MarketSkillDto): void {
    AlertDialog.show({
      title: '确认安装',
      message: `确定要安装技能"${item.name}"（v${item.version}）到 default 智能体吗？`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '安装',
        fontColor: this.sm.getColor('primary'),
        action: () => { this.installSkill(item.skill_id); }
      }
    });
  }

  /**
   * 卸载前二次确认
   */
  private confirmUninstall(item: MarketSkillDto): void {
    AlertDialog.show({
      title: '确认卸载',
      message: `确定要卸载技能"${item.name}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '卸载',
        fontColor: this.sm.getColor('error'),
        action: () => { this.uninstallSkill(item.skill_id); }
      }
    });
  }

  /**
   * 执行安装（POST /v1/marketplace/skills/{id}/install）
   * 409=安全门拒装 / 403=属主门拦截：错误信息透传
   */
  private async installSkill(skillId: string): Promise<void> {
    if (this.operatingId.length > 0) {
      return;
    }
    this.operatingId = skillId;
    try {
      const res = await this.api.marketplace.install(skillId, { agentId: 'default' });
      if (res.code === 0) {
        this.msg.success(res.message && res.message.length > 0 ? res.message : '已安装');
        await this.loadItems();
      } else {
        this.msg.error(res.message && res.message.length > 0 ? res.message : '安装失败');
      }
    } catch (e) {
      this.logger.error(TAG, '安装技能失败', e as Error);
      this.msg.error('安装失败（可能被安装安全门拒绝或无属主权限）');
    } finally {
      this.operatingId = '';
    }
  }

  /**
   * 执行卸载（DELETE /v1/marketplace/skills/{id}/install）
   */
  private async uninstallSkill(skillId: string): Promise<void> {
    if (this.operatingId.length > 0) {
      return;
    }
    this.operatingId = skillId;
    try {
      const res = await this.api.marketplace.uninstall(skillId, 'default');
      if (res.code === 0) {
        this.msg.success('已卸载');
        await this.loadItems();
      } else {
        this.msg.error(res.message && res.message.length > 0 ? res.message : '卸载失败');
      }
    } catch (e) {
      this.logger.error(TAG, '卸载技能失败', e as Error);
      this.msg.error('卸载失败');
    } finally {
      this.operatingId = '';
    }
  }

  build() {
    Column() {
      // 顶部导航栏：标题"技能市场" + 返回
      TopNavMenu({
        title: '技能市场',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      })

      // 搜索框
      GlassInput({
        placeholder: '搜索技能...',
        value: this.searchKeyword,
        type: 'text',
        onChange: (v: string) => { this.inputSearch(v); },
      })
        .width('100%')
        .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })

      // 来源筛选 Tab（服务端过滤）
      Scroll() {
        Row({ space: 8 }) {
          ForEach(SOURCE_FILTERS, (opt: SourceFilterOption) => {
            Text(opt.label)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.activeSource === opt.value
                ? this.sm.getColor('text_on_primary')
                : this.sm.getColor('text_secondary'))
              .backgroundColor(this.activeSource === opt.value
                ? this.sm.getColor('primary')
                : this.sm.getColor('surface'))
              .padding({ left: 12, right: 12, top: 6, bottom: 6 })
              .borderRadius(16)
              .onClick(() => { this.switchSource(opt.value); })
          }, (opt: SourceFilterOption) => opt.value)
        }
        .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
      }
      .scrollable(ScrollDirection.Horizontal)
      .scrollBar(BarState.Off)
      .width('100%')
      .padding({ top: 4, bottom: 4 })

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
          Text('暂无技能')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        List({ space: 12 }) {
          ForEach(this.getFilteredItems(), (item: MarketSkillDto) => {
            ListItem() {
              this.buildSkillCard(item)
            }
          }, (item: MarketSkillDto) => item.skill_id)
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
  // 技能卡片构建器
  // ===========================================================================

  /** 单个技能卡片：来源徽章 + 名称 + 分类/版本 + 描述 + 评分/下载 + 安装/卸载按钮 */
  @Builder
  buildSkillCard(item: MarketSkillDto) {
    GlassCard() {
      Column() {
        // 顶部行：分类图标 + 来源徽章 + 已安装徽章 + 操作按钮
        Row() {
          Text(MarketplaceViewHelper.getCategoryIcon(item.category))
            .fontSize(20)
          Text(MarketplaceViewHelper.getSourceLabel(item.source))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor(MarketplaceViewHelper.getSourceColor(item.source)))
            .margin({ left: this.sm.getSpacing('xs') })
          if (item.installed) {
            Text('已安装')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('success'))
              .padding({ left: 6, right: 6, top: 2, bottom: 2 })
              .borderRadius(this.sm.getRadius('sm'))
              .backgroundColor(this.sm.getColor('surface'))
              .margin({ left: this.sm.getSpacing('xs') })
          }
          // 操作按钮（右对齐）
          GlassButton({
            text: this.operatingId === item.skill_id
              ? '处理中'
              : (item.installed ? '卸载' : '安装'),
            type: item.installed ? 'danger' : 'primary',
            btnSize: 'small',
            onTap: () => {
              if (item.installed) {
                this.confirmUninstall(item);
              } else {
                this.confirmInstall(item);
              }
            }
          })
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .justifyContent(FlexAlign.Start)

        // 技能名称 + 版本
        Row() {
          Text(item.name)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
          Text(`v${item.version}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .alignItems(VerticalAlign.Center)

        // 作者 + 分类
        Row() {
          Text(`${item.category} · ${item.author}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
        }
        .width('100%')
        .margin({ top: 2 })
        .alignItems(VerticalAlign.Center)

        // 描述（默认 60 字符截断）
        Text(MarketplaceViewHelper.truncateDescription(item.description, DEFAULT_DESC_MAX_LEN))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')

        // 评分 + 下载数
        Row() {
          Text(MarketplaceViewHelper.formatRatingText(item.rating))
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('warning'))
            .layoutWeight(1)
          Text(MarketplaceViewHelper.formatDownloadCount(item.downloads))
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
  }
}
