/**
 * SkillMarketPage - 技能市场页
 *
 * 职责：浏览可安装技能，搜索、按 category 筛选、安装
 * 设计：
 *   - SkillMarketViewHelper（导出）：纯视图模型，封装分类颜色映射、分类图标、分类文案、
 *     描述截断（默认 120）、评分格式化（5 星）、安装数格式化（K/M），无 UI 依赖，可独立单元测试；
 *   - SkillMarketPage（@Component）：Column [TopNavMenu(标题"技能市场"+返回+刷新)] +
 *     [搜索栏 GlassInput] + [category 筛选 Tab（全部/AI/工具/集成/数据处理/其他）]
 *     + [加载态/空态/列表]；
 *     列表项 GlassCard：name、author、category 徽章、version、installs、rating、
 *     description 摘要、tags、安装按钮；安装走 AlertDialog 二次确认；
 *   - 颜色统一走 StyleManager，路由走 Router，API 暂无 skills 专用模块 →
 *     aboutToAppear 加载 mock 静态数据 + TODO 注释 M5 阶段补充真实 API。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput
 *   - ../libs/api/ApiFacade：统一 API 门面（仅作为占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Skill
 *
 * 用法：
 *   由 Router.push(RouteNames.SKILL_MARKET) 跳转进入；
 *   aboutToAppear 加载 mock 技能列表（TODO M5 接入真实 API）；
 *   搜索栏输入 → 本地按 name/description 关键词过滤；
 *   category 筛选 Tab 切换 → 本地按 category 过滤；
 *   安装按钮 → AlertDialog 二次确认 → 本地标记 + TODO M5 接入 API。
 *
 * TDD：SkillMarketViewHelper 各方法按红绿灯垂直切片逐步实现，详见 SkillMarketPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Skill } from '../libs/types';

/** 日志标签 */
const TAG = 'SkillMarketPage';

/** 描述截断默认最大长度 */
const DEFAULT_DESC_MAX_LEN = 120;

// ===========================================================================
// SkillMarketViewHelper - 技能市场视图模型（纯函数，无 UI 依赖，可独立单元测试）
// ===========================================================================

export class SkillMarketViewHelper {
  /**
   * 获取分类对应的颜色 token 名
   * 映射：AI→primary，工具→info，集成→warning，数据处理→success，其他→text_secondary
   * @param category 分类名
   * @return StyleManager 颜色 token 名
   */
  static getCategoryColor(category: string): string {
    if (category === 'AI') return 'primary';
    if (category === '工具') return 'info';
    if (category === '集成') return 'warning';
    if (category === '数据处理') return 'success';
    return 'text_secondary';
  }

  /**
   * 获取分类对应的图标 emoji
   * 映射：AI→🤖，工具→🔧，集成→🔌，数据处理→📊，其他→📦
   * @param category 分类名
   * @return emoji 字符串
   */
  static getCategoryIcon(category: string): string {
    if (category === 'AI') return '🤖';
    if (category === '工具') return '🔧';
    if (category === '集成') return '🔌';
    if (category === '数据处理') return '📊';
    return '📦';
  }

  /**
   * 获取分类对应的中文标签
   * 规则：已知分类（AI/工具/集成/数据处理）原样返回；未知 → "其他"
   * @param category 分类名
   * @return 中文标签
   */
  static getCategoryLabel(category: string): string {
    if (category === 'AI' || category === '工具' || category === '集成' || category === '数据处理') {
      return category;
    }
    return '其他';
  }

  /**
   * 截断描述，超长时截取 maxLen 字符并追加省略号
   * @param desc 原始描述
   * @param maxLen 最大字符数，默认 120
   * @return 截断后的描述；未超长则原样返回
   */
  static truncateDescription(desc: string, maxLen: number = DEFAULT_DESC_MAX_LEN): string {
    if (desc.length <= maxLen) return desc;
    return desc.substring(0, maxLen) + '...';
  }

  /**
   * 格式化评分（0-5）为 5 星 + 数值字符串
   * 规则：0 → "暂无评分"；非零 → "★★★☆☆ 4.5"（满格数 = floor(rating)）
   */
  static formatRating(rating: number): string {
    if (rating === 0) return '暂无评分';
    const full = Math.floor(rating);
    const empty = 5 - full;
    const stars = '★'.repeat(full) + '☆'.repeat(empty);
    return `${stars} ${rating.toFixed(1)}`;
  }

  /**
   * 格式化安装数为人类可读字符串
   * 规则：0 → "无安装"；≥1M → "1.0M 安装"；≥1K → "1.0K 安装"；其他 → "{n} 安装"
   */
  static formatInstalls(installs: number): string {
    if (installs === 0) return '无安装';
    const M = 1024 * 1024;
    const K = 1024;
    if (installs >= M) {
      return `${(installs / M).toFixed(1)}M 安装`;
    }
    if (installs >= K) {
      return `${(installs / K).toFixed(1)}K 安装`;
    }
    return `${installs} 安装`;
  }
}

/** 分类筛选 Tab 配置 */
interface CategoryFilterOption {
  value: string;
  label: string;
}

/** 分类筛选 Tab 列表 */
const CATEGORY_FILTERS: CategoryFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'AI', label: 'AI' },
  { value: '工具', label: '工具' },
  { value: '集成', label: '集成' },
  { value: '数据处理', label: '数据处理' },
  { value: '其他', label: '其他' },
];

/**
 * Mock 技能市场数据（数组字面量）
 * TODO M5 阶段：替换为 api.skills.market() 或类似真实 API
 */
const MOCK_MARKET_SKILLS: Skill[] = [
  {
    id: 'm_skill_1',
    name: '代码生成器 Pro',
    description: '基于上下文生成代码片段，支持多种语言',
    category: 'AI',
    version: '2.0.0',
    status: 'published',
    author: 'Neurova',
    installs: 5120,
    rating: 4.5,
    tags: ['code', 'ai'],
    publishedAt: '2025-02-10T08:00:00Z',
  },
  {
    id: 'm_skill_2',
    name: '文件转换工具',
    description: 'PDF/Word/Excel 互转，保留格式',
    category: '工具',
    version: '1.5.0',
    status: 'published',
    author: 'Community',
    installs: 2048,
    rating: 4.0,
    tags: ['file', 'convert'],
    publishedAt: '2025-01-20T08:00:00Z',
  },
  {
    id: 'm_skill_3',
    name: '飞书工作流',
    description: '与飞书多维表格深度集成',
    category: '集成',
    version: '1.0.0',
    status: 'published',
    author: 'Feishu',
    installs: 800,
    rating: 5.0,
    tags: ['feishu', 'workflow'],
    publishedAt: '2025-03-01T08:00:00Z',
  },
];

@Component
export struct SkillMarketPage {
  // 市场技能列表（由 mock 数据驱动）
  @State skills: Skill[] = [];
  // 加载态
  @State loading: boolean = true;
  // 搜索关键词
  @State keyword: string = '';
  // 当前激活的分类筛选
  @State activeCategory: string = 'all';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadSkills();
  }

  /**
   * 加载市场技能列表
   * TODO M5 阶段：替换为真实 API
   */
  private async loadSkills(): Promise<void> {
    this.loading = true;
    try {
      // TODO M5 阶段补充真实 API
      // const res = await this.api.skills.market();
      // if (res.code === 0 && res.data) { this.skills = res.data.items; }
      this.skills = MOCK_MARKET_SKILLS.slice();
    } catch (e) {
      this.logger.error(TAG, '加载市场失败', e as Error);
      this.msg.error('加载技能市场失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换分类筛选 */
  private switchCategory(value: string): void {
    this.activeCategory = value;
  }

  /**
   * 获取经搜索 + 分类筛选后的列表
   * 规则：先按关键词过滤 name/description；再按 category 过滤
   *       activeCategory === 'all' 时不按 category 过滤；
   *       activeCategory === '其他' 时过滤未匹配已知分类的项
   */
  private getFilteredSkills(): Skill[] {
    let result = this.skills;
    const kw = this.keyword.trim();
    if (kw) {
      result = result.filter((s: Skill) =>
        s.name.includes(kw) || s.description.includes(kw));
    }
    if (this.activeCategory === 'all') {
      return result;
    }
    if (this.activeCategory === '其他') {
      return result.filter((s: Skill) =>
        SkillMarketViewHelper.getCategoryLabel(s.category) === '其他');
    }
    return result.filter((s: Skill) => s.category === this.activeCategory);
  }

  /**
   * 安装前二次确认
   * 使用 AlertDialog 弹窗，避免误装
   */
  private confirmInstall(skill: Skill): void {
    AlertDialog.show({
      title: '确认安装',
      message: `确定要安装技能"${skill.name}"（v${skill.version}）吗？`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '安装',
        fontColor: this.sm.getColor('primary'),
        action: () => { this.installSkill(skill.id); }
      }
    });
  }

  /**
   * 执行安装
   * TODO M5 阶段：调用真实 API（api.skills.install）
   * 当前为本地提示 + TODO
   */
  private async installSkill(skillId: string): Promise<void> {
    try {
      // TODO M5 阶段：const res = await this.api.skills.install(skillId);
      this.msg.success('已安装');
    } catch (e) {
      this.logger.error(TAG, '安装技能失败', e as Error);
      this.msg.error('安装技能失败');
    }
  }

  build() {
    Column() {
      // 顶部导航栏：标题"技能市场" + 返回 + 刷新
      TopNavMenu({
        title: '技能市场',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      }) {
        GlassButton({
          text: '刷新',
          type: 'default',
          size: 'small',
          onClick: () => { this.loadSkills(); }
        })
      }

      // 搜索栏
      Row() {
        GlassInput({
          placeholder: '搜索技能...',
          value: this.keyword,
          type: 'text',
          onChange: (v: string) => { this.keyword = v; },
          onSubmit: () => {}
        })
      }
      .width('100%')
      .padding({
        left: this.sm.getSpacing('md'),
        right: this.sm.getSpacing('md'),
        top: this.sm.getSpacing('sm'),
        bottom: this.sm.getSpacing('sm'),
      })
      .alignItems(VerticalAlign.Center)

      // 分类筛选 Tab：横向滚动胶囊
      Scroll() {
        Row({ space: 8 }) {
          ForEach(CATEGORY_FILTERS, (opt: CategoryFilterOption) => {
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
          }, (opt: CategoryFilterOption) => opt.value)
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
      } else if (this.getFilteredSkills().length === 0) {
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
          ForEach(this.getFilteredSkills(), (skill: Skill) => {
            ListItem() {
              this.buildMarketCard(skill)
            }
          }, (skill: Skill) => skill.id)
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
  // 市场卡片构建器
  // ===========================================================================

  /** 单个市场卡片：分类徽章 + 名称 + 作者 + 描述 + 评分/安装数 + 标签 + 安装按钮 */
  @Builder
  buildMarketCard(skill: Skill) {
    GlassCard() {
      Column() {
        // 顶部行：分类图标 + 分类徽章 + 名称
        Row() {
          Text(SkillMarketViewHelper.getCategoryIcon(skill.category))
            .fontSize(20)
          Text(SkillMarketViewHelper.getCategoryLabel(skill.category))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor(SkillMarketViewHelper.getCategoryColor(skill.category)))
            .margin({ left: this.sm.getSpacing('xs') })
          Text(skill.name)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .margin({ left: this.sm.getSpacing('sm') })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 作者 + 版本
        Row() {
          Text(`作者: ${skill.author}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text(`v${skill.version}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .alignItems(VerticalAlign.Center)

        // 描述摘要（默认 120 字符截断）
        Text(SkillMarketViewHelper.truncateDescription(skill.description))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')

        // 评分 + 安装数
        Row() {
          Text(SkillMarketViewHelper.formatRating(skill.rating))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('warning'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Text(SkillMarketViewHelper.formatInstalls(skill.installs))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .alignItems(VerticalAlign.Center)

        // 标签
        Text(skill.tags && skill.tags.length > 0 ? skill.tags.join(' · ') : '无标签')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')

        // 安装按钮（右对齐）
        Row() {
          GlassButton({
            text: '安装',
            type: 'primary',
            size: 'small',
            onClick: () => { this.confirmInstall(skill); }
          })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }
}
