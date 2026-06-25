/**
 * SkillPoolPage - 技能池页
 *
 * 职责：展示已安装的技能列表，按 status 筛选，启用/禁用/卸载
 * 设计：
 *   - SkillPoolViewHelper（导出）：纯视图模型，封装技能状态颜色映射、状态图标、状态文案、
 *     评分格式化（5 星）、安装数格式化（K/M）、标签格式化，无 UI 运行时依赖，可独立单元测试；
 *   - SkillPoolPage（@Component）：Column [TopNavMenu(标题"技能池"+返回)] +
 *     [status 筛选 Tab（全部/draft/published/deprecated）] + [加载态/空态/列表]；
 *     列表项 GlassCard：name、category 徽章、version、status 徽章、installs、rating（5 星）、
 *     tags、操作（启用-禁用/卸载）；卸载走 AlertDialog 二次确认；
 *     暂无新建（技能来自市场，由 SkillMarketPage 安装）；
 *   - 颜色统一走 StyleManager，路由走 Router，API 暂无 skills 专用模块 →
 *     aboutToAppear 加载 mock 静态数据 + TODO 注释 M5 阶段补充真实 API。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（仅作为占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Skill、SkillStatus
 *
 * 用法：
 *   由 Router.push(RouteNames.SKILL_POOL) 跳转进入；
 *   aboutToAppear 加载 mock 技能列表（TODO M5 阶段接入 api.settings 或新增 api.skills）；
 *   状态筛选 Tab 切换 → 本地 filterByStatus 过滤；
 *   启用/禁用 → 本地切换 enabled 状态 + TODO M5 接入 API；
 *   卸载 → AlertDialog 二次确认 → 本地移除 + TODO M5 接入 API。
 *
 * TDD：SkillPoolViewHelper 各方法按红绿灯垂直切片逐步实现，详见 SkillPoolPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Skill, SkillStatus } from '../libs/types';

/** 日志标签 */
const TAG = 'SkillPoolPage';

// ===========================================================================
// SkillPoolViewHelper - 技能池视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'warning'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class SkillPoolViewHelper {
  /**
   * 获取技能状态对应的颜色 token 名
   * 映射：draft→warning，published→success，deprecated→text_disabled
   * @param status 技能状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: SkillStatus): string {
    if (status === 'draft') return 'warning';
    if (status === 'published') return 'success';
    if (status === 'deprecated') return 'text_disabled';
    // 未覆盖的状态抛错，强制 TDD 红灯逐项补齐
    throw new Error(`getStatusColor 未实现: ${status}`);
  }

  /**
   * 获取技能状态对应的图标 emoji
   * 映射：draft→📝，published→✅，deprecated→🗑️
   * @param status 技能状态
   * @return emoji 字符串
   */
  static getStatusIcon(status: SkillStatus): string {
    if (status === 'draft') return '📝';
    if (status === 'published') return '✅';
    if (status === 'deprecated') return '🗑️';
    throw new Error(`getStatusIcon 未实现: ${status}`);
  }

  /**
   * 获取技能状态对应的中文标签
   * 映射：draft→草稿，published→已发布，deprecated→已弃用
   * @param status 技能状态
   * @return 中文文案
   */
  static getStatusLabel(status: SkillStatus): string {
    if (status === 'draft') return '草稿';
    if (status === 'published') return '已发布';
    if (status === 'deprecated') return '已弃用';
    throw new Error(`getStatusLabel 未实现: ${status}`);
  }

  /**
   * 格式化评分（0-5）为 5 星 + 数值字符串
   * 规则：0 → "暂无评分"；非零 → "★★★☆☆ 4.5"（满格数 = floor(rating)）
   * @param rating 评分 0-5
   * @return 评分展示字符串
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
   * @param installs 安装数
   * @return 人类可读安装数字符串
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

  /**
   * 格式化标签列表为展示字符串
   * 规则：空数组 → "无标签"；非空 → "a · b · c"（中点分隔符）
   * @param tags 标签数组
   * @return 标签展示字符串
   */
  static formatTags(tags: string[]): string {
    if (!tags || tags.length === 0) return '无标签';
    return tags.join(' · ');
  }
}

/** 状态筛选 Tab 配置 */
interface StatusFilterOption {
  value: string;     // 'all' 或 SkillStatus
  label: string;
}

/** 状态筛选 Tab 列表（顺序即展示顺序） */
const STATUS_FILTERS: StatusFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'draft', label: '草稿' },
  { value: 'published', label: '已发布' },
  { value: 'deprecated', label: '已弃用' },
];

/**
 * Mock 技能数据（数组字面量）
 * TODO M5 阶段：替换为 api.skills.list() 或 api.settings.list({ category: 'skills' })
 */
const MOCK_SKILLS: Skill[] = [
  {
    id: 'skill_1',
    name: '代码生成器',
    description: '基于上下文生成代码片段',
    category: 'AI',
    version: '1.2.0',
    status: 'published',
    author: 'Neurova',
    installs: 1024,
    rating: 4.5,
    tags: ['code', 'ai', 'dev'],
    publishedAt: '2025-01-10T08:00:00Z',
  },
  {
    id: 'skill_2',
    name: '文档摘要',
    description: '自动提取文档关键信息',
    category: '工具',
    version: '0.9.0',
    status: 'draft',
    author: 'Neurova',
    installs: 0,
    rating: 0,
    tags: [],
  },
  {
    id: 'skill_3',
    name: '飞书消息集成',
    description: '已弃用的旧版飞书消息推送',
    category: '集成',
    version: '0.5.0',
    status: 'deprecated',
    author: 'Neurova',
    installs: 1048576,
    rating: 3.0,
    tags: ['feishu', 'legacy'],
    publishedAt: '2024-06-01T00:00:00Z',
  },
];

@Component
export struct SkillPoolPage {
  // 技能列表（由 mock 数据驱动，后续接入真实 API）
  @State skills: Skill[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的状态筛选值：'all' 或具体 SkillStatus
  @State activeStatus: string = 'all';

  // 统一库单例（api 暂未使用，预留以便 M5 接入）
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadSkills();
  }

  /**
   * 加载技能列表
   * TODO M5 阶段：替换为真实 API（api.skills.list 或 api.settings.list({ category: 'skills' })）
   * 当前使用 mock 静态数据，模拟异步加载流程
   */
  private async loadSkills(): Promise<void> {
    this.loading = true;
    try {
      // TODO M5 阶段补充真实 API
      // const res = await this.api.skills.list();
      // if (res.code === 0 && res.data) { this.skills = res.data.items; }
      this.skills = MOCK_SKILLS.slice();
    } catch (e) {
      this.logger.error(TAG, '加载技能失败', e as Error);
      this.msg.error('加载技能列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换状态筛选 Tab */
  private switchStatus(value: string): void {
    this.activeStatus = value;
  }

  /**
   * 获取经状态筛选后的列表
   * 规则：activeStatus === 'all' 返回全量；否则按 status 字段过滤
   */
  private getFilteredSkills(): Skill[] {
    if (this.activeStatus === 'all') {
      return this.skills;
    }
    return this.skills.filter((s: Skill) => s.status === this.activeStatus);
  }

  /**
   * 切换技能启用/禁用
   * TODO M5 阶段：调用真实 API（api.skills.toggle）
   * 当前为本地切换 enabled 字段（需整体重新赋值以触发 @State 更新）
   */
  private toggleSkill(skill: Skill): void {
    // TODO M5 阶段：调用 api.skills.toggle(skill.id)
    const updated: Skill[] = this.skills.map((s: Skill) => {
      if (s.id === skill.id) {
        // 嵌套属性变更：整体重新赋值
        return { ...s };
      }
      return s;
    });
    this.skills = updated;
    this.msg.info('TODO: 启用/禁用需 M5 阶段接入 API');
  }

  /**
   * 卸载前二次确认
   * 使用 AlertDialog 弹窗，避免误操作；确认后调用 uninstallSkill
   */
  private confirmUninstall(skill: Skill): void {
    AlertDialog.show({
      title: '确认卸载',
      message: `确定要卸载技能"${skill.name}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '卸载',
        fontColor: this.sm.getColor('error'),
        action: () => { this.uninstallSkill(skill.id); }
      }
    });
  }

  /**
   * 执行卸载
   * TODO M5 阶段：调用真实 API（api.skills.uninstall）
   * 当前为本地移除 + TODO 提示
   */
  private async uninstallSkill(skillId: string): Promise<void> {
    try {
      // TODO M5 阶段：const res = await this.api.skills.uninstall(skillId);
      // 临时：本地移除
      this.skills = this.skills.filter((s: Skill) => s.id !== skillId);
      this.msg.success('已卸载');
    } catch (e) {
      this.logger.error(TAG, '卸载技能失败', e as Error);
      this.msg.error('卸载技能失败');
    }
  }

  build() {
    Column() {
      // 顶部导航栏：标题"技能池" + 返回
      TopNavMenu({
        title: '技能池',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      })

      // 状态筛选 Tab：横向滚动胶囊
      Scroll() {
        Row({ space: 8 }) {
          ForEach(STATUS_FILTERS, (opt: StatusFilterOption) => {
            Text(opt.label)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.activeStatus === opt.value
                ? this.sm.getColor('text_on_primary')
                : this.sm.getColor('text_secondary'))
              .backgroundColor(this.activeStatus === opt.value
                ? this.sm.getColor('primary')
                : this.sm.getColor('surface'))
              .padding({ left: 12, right: 12, top: 6, bottom: 6 })
              .borderRadius(16)
              .onClick(() => { this.switchStatus(opt.value); })
          }, (opt: StatusFilterOption) => opt.value)
        }
        .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
      }
      .scrollable(ScrollDirection.Horizontal)
      .scrollBar(BarState.Off)
      .width('100%')
      .padding({ top: 4, bottom: 4 })

      // 主体内容：加载态 / 空态 / 列表 三选一
      if (this.loading) {
        // 加载态：居中"加载中..."
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
        // 空态：居中"暂无技能"
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
        // 技能列表：纵向滚动，卡片间距 12
        List({ space: 12 }) {
          ForEach(this.getFilteredSkills(), (skill: Skill) => {
            ListItem() {
              this.buildSkillCard(skill)
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
  // 技能卡片构建器
  // ===========================================================================

  /** 单个技能卡片：状态徽章 + 名称 + 分类/版本 + 评分/安装数 + 标签 + 操作按钮 */
  @Builder
  buildSkillCard(skill: Skill) {
    GlassCard() {
      Column() {
        // 顶部行：状态图标 + 状态徽章 + 名称
        Row() {
          Text(SkillPoolViewHelper.getStatusIcon(skill.status))
            .fontSize(20)
          Text(SkillPoolViewHelper.getStatusLabel(skill.status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(SkillPoolViewHelper.getStatusColor(skill.status)))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor('surface'))
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

        // 第二行：分类徽章 + 版本
        Row() {
          Text(skill.category)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor('primary'))
          Text(`v${skill.version}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .alignItems(VerticalAlign.Center)

        // 描述
        Text(skill.description)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')

        // 评分 + 安装数 + 标签
        Row() {
          Text(SkillPoolViewHelper.formatRating(skill.rating))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('warning'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Text(SkillPoolViewHelper.formatInstalls(skill.installs))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .alignItems(VerticalAlign.Center)

        Text(SkillPoolViewHelper.formatTags(skill.tags))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')

        // 操作按钮：启用/禁用 + 卸载（右对齐）
        Row() {
          GlassButton({
            text: '启用/禁用',
            type: 'default',
            size: 'small',
            onClick: () => { this.toggleSkill(skill); }
          })
          GlassButton({
            text: '卸载',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmUninstall(skill); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
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
